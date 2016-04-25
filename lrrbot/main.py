# -*- coding: utf-8 -*-

import os
import datetime
import logging
import functools
import asyncio

import irc.bot
import irc.client
import irc.connection
import sqlalchemy

import common.postgres
import lrrbot.decorators
import lrrbot.systemd
from common import utils
from common.config import config
from common import twitch
from common import slack
from common import game_data
from common.sqlalchemy_pg95_upsert import DoUpdate
from lrrbot import chatlog, storage, twitchsubs, whisper, asyncreactor, linkspam, cardviewer
from lrrbot import spam
from lrrbot import command_parser
from lrrbot import rpc
from lrrbot import join_filter

log = logging.getLogger('lrrbot')

SELF_METADATA = {'specialuser': {'mod', 'subscriber'}, 'usercolor': '#FF0000', 'emoteset': {317}}

class LRRBot(irc.bot.SingleServerIRCBot):
	def __init__(self, loop):
		self.engine, self.metadata = common.postgres.new_engine_and_metadata()
		users = self.metadata.tables["users"]
		if config['password'] == "oauth":
			with self.engine.begin() as conn:
				password, = conn.execute(sqlalchemy.select([users.c.twitch_oauth])
					.where(users.c.name == config['username'])).first()
			password = "oauth:" + password
		else:
			password = config['password']
		self.loop = loop
		server = irc.bot.ServerSpec(
			host=config['hostname'],
			port=config['port'],
			password=password,
		)
		if config['secure']:
			import ssl
			connect_factory = irc.connection.Factory(wrapper=ssl.wrap_socket)
		else:
			connect_factory = irc.connection.Factory()
		super(LRRBot, self).__init__(
			server_list=[server],
			realname=config['username'],
			nickname=config['username'],
			reconnection_interval=config['reconnecttime'],
			connect_factory=connect_factory,
		)

		# Send a keep-alive message every minute, to catch network dropouts
		# self.connection has a set_keepalive method, but it crashes
		# if it triggers while the connection is down, so do this instead
		self.reactor.execute_every(period=config['keepalivetime'], function=self.do_keepalive)

		self.reactor.execute_every(period=5, function=self.check_polls)
		self.reactor.execute_every(period=5, function=self.vote_respond)

		self.service = lrrbot.systemd.Service(loop)

		# create secondary connection
		if config['whispers']:
			self.whisperconn = whisper.TwitchWhisper(self, self.loop)
		else:
			self.whisperconn = None

		# create pubnub listener
		self.cardviewer = cardviewer.CardViewer(self, self.loop)

		# IRC event handlers
		self.reactor.add_global_handler('welcome', self.check_privmsg_wrapper, 0)
		self.reactor.add_global_handler('welcome', self.on_connect, 1)
		self.reactor.add_global_handler('join', self.on_channel_join, 0)

		for event in ['pubmsg', 'privmsg']:
			self.reactor.add_global_handler(event, self.check_privmsg_wrapper, 0)
			self.reactor.add_global_handler(event, self.check_message_tags, 1)
			self.reactor.add_global_handler(event, self.log_chat, 2)

		self.reactor.add_global_handler('action', self.on_message_action, 99)
		self.reactor.add_global_handler('clearchat', self.on_clearchat)
		if self.whisperconn:
			self.whisperconn.add_whisper_handler(self.on_whisper_received)

		# Set up bot state
		self.game_override = None
		self.show_override = None
		self.vote_update = None
		self.access = "all"
		self.set_show("")
		self.polls = []
		self.cardview = False

		self.spammers = {}

		self.rpc_server = rpc.Server(self, loop)

		self.commands = command_parser.CommandParser(self, loop)
		self.command = self.commands.decorator

		self.link_spam = linkspam.LinkSpam(self, loop)
		self.spam = spam.Spam(self, loop)
		self.subs = twitchsubs.TwitchSubs(self, loop)
		self.join_filter = join_filter.JoinFilter(self, loop)

	def reactor_class(self):
		return asyncreactor.AsyncReactor(self.loop)

	def start(self):
		# Let us run on windows, without the socket
		if hasattr(self.loop, 'create_unix_server'):
			# TODO: To be more robust, the code really should have a way to shut this socket down
			# when the bot exits... currently, it's assuming that there'll only be one LRRBot
			# instance, that lasts the life of the program... which is true for now...
			try:
				os.unlink(config['socket_filename'])
			except OSError:
				if os.path.exists(config['socket_filename']):
					raise
			event_server = self.loop.create_unix_server(self.rpc_server, path=config['socket_filename'])
			self.loop.run_until_complete(event_server)
		else:
			event_server = None

		# Start background tasks
		substask = asyncio.async(self.subs.watch_subs(), loop=self.loop)
		chatlogtask = asyncio.async(chatlog.run_task(), loop=self.loop)

		self._connect()
		self.cardviewer.start()

		# Don't fall over if the server sends something that's not real UTF-8
		self.connection.buffer.errors = "replace"

		try:
			self.loop.run_forever()
		finally:
			log.info("Bot shutting down...")
			if event_server:
				event_server.close()
			substask.cancel()
			chatlog.stop_task()
			tasks_waiting = [substask, chatlogtask]
			if self.whisperconn:
				tasks_waiting.append(self.whisperconn.stop_task())
			self.cardviewer.stop()
			self.loop.run_until_complete(asyncio.wait(tasks_waiting))

	def on_connect(self, conn, event):
		"""On connecting to the server, join our target channel"""
		log.info("Connected to server")
		conn.cap("REQ", "twitch.tv/tags") # get metadata tags
		conn.cap("REQ", "twitch.tv/commands") # get special commands
		conn.cap("REQ", "twitch.tv/membership") # get join/part messages
		conn.join("#%s" % config['channel'])

	def on_channel_join(self, conn, event):
		source = irc.client.NickMask(event.source)
		if (source.nick.lower() == config['username'].lower()):
			log.info("Channel %s joined" % event.target)
			self.service.subsystem_started("irc")

	@utils.swallow_errors
	def do_keepalive(self):
		"""Send a ping to the server, to ensure our connection stays alive, or to detect when it drops out."""
		try:
			self.connection.ping("keep-alive")
		except irc.client.ServerNotConnectedError:
			pass

	def on_message_action(self, conn, event):
		# Treat CTCP ACTION messages as the raw "/me does whatever" message that
		# was actually typed in. Mostly for passing it through to the chat log
		# but also to make sure the subscriber flags are updated etc.
		event.arguments[0] = "/me " + event.arguments[0]
		if irc.client.is_channel(event.target):
			event.type = "pubmsg"
		else:
			event.type = "privmsg"
		self.reactor._handle_event(conn, event)

	def log_chat(self, conn, event):
		source = irc.client.NickMask(event.source)
		metadata = {
			'usercolor': event.tags.get('color'),
			'emotes': event.tags.get('emotes'),
			'display-name': event.tags.get('display-name') or source.nick,
			'specialuser': set(),
		}
		if event.tags['subscriber']:
			metadata['specialuser'].add('subscriber')
		if int(event.tags.get('turbo', 0)):
			metadata['specialuser'].add('turbo')
		if event.tags.get('user-type'):
			metadata['specialuser'].add(event.tags.get('user-type'))
		if event.tags['mod']:
			metadata['specialuser'].add('mod')
		log.debug("Message metadata: %r", metadata)
		chatlog.log_chat(event, metadata)

	def check_message_tags(self, conn, event):
		"""
		Whenever a user says something, update database to have the latest version of user metadata.
		Also corrects the tags.
		"""
		if isinstance(event.tags, list):
			tags = event.tags = dict((i['key'], i['value']) for i in event.tags)
		else:
			tags = event.tags
		source = irc.client.NickMask(event.source)
		nick = source.nick.lower()

		if tags.get("display-name") == '':
			del tags["display-name"]

		tags["subscriber"] = is_sub = bool(int(tags.get("subscriber", 0)))

		# Either:
		#  * has sword
		is_mod = bool(int(tags.get('mod', 0)))
		#  * is some sort of Twitchsm'n
		is_mod = is_mod or tags.get('user-type', '') in {'mod', 'global_mod', 'admin', 'staff'}
		#  * is broadcaster
		tags["mod"] = is_mod = is_mod or nick.lower() == config['channel']

		if "user-id" not in tags:
			tags["display_name"] = tags.get("display_name", nick)
			return
		tags["user-id"] = int(tags["user-id"])

		if event.type == "pubmsg":
			users = self.metadata.tables["users"]
			with self.engine.begin() as conn:
				conn.execute(users.insert(postgresql_on_conflict="update"), {
					"id": tags["user-id"],
					"name": nick,
					"display_name": tags.get("display-name"),
					"is_sub": is_sub,
					"is_mod": is_mod,
				})
		else:
			users = self.metadata.tables['users']
			with self.engine.begin() as pg_conn:
				row = pg_conn.execute(sqlalchemy.select([users.c.is_sub, users.c.is_mod])
					.where(users.c.id == event.tags['user-id'])).first()
				if row is not None:
					tags['subscriber'], tags['mod'] = row
				else:
					tags['subscriber'] = False
					tags['mod'] = False

		tags["display_name"] = tags.get("display_name", nick)

	@utils.swallow_errors
	def on_clearchat(self, conn, event):
		# This message is both "CLEARCHAT" to clear the whole chat
		# or "CLEARCHAT :someuser" to purge a single user
		if len(event.arguments) >= 1:
			chatlog.clear_chat_log(event.arguments[0])

	@utils.cache(twitch.GAME_CHECK_INTERVAL)
	def get_game_id(self):
		if self.game_override is None:
			game = twitch.get_game_playing()
			if game is None:
				return None
			game_id, game_name = game["_id"], game["name"]

			games = self.metadata.tables["games"]
			with self.engine.begin() as conn:
				game_data.lock_tables(conn, self.metadata)
				old_id = conn.execute(sqlalchemy.select([games.c.id]).where(games.c.name == game_name)).first()
				if old_id is None:
					conn.execute(games.insert(), {
						"id": game_id,
						"name": game_name
					})
				else:
					old_id, = old_id
					conn.execute(games.insert(postgresql_on_conflict="nothing"), {
						"id": game_id,
						"name": "__LRRBOT_TEMP_GAME_%s__" % game_name,
					})
					game_data.merge_games(conn, self.metadata, old_id, game_id, game_id)
					conn.execute(games.update().where(games.c.id == game_id), {
						"name": game_name,
					})
			return game_id
		return self.game_override

	def override_game(self, name):
		"""
			Override current game.

			`name`: Name of the game or `None` to disable override
		"""
		if name is None:
			self.game_override = None
		else:
			games = self.metadata.tables["games"]
			with self.engine.begin() as conn:
				# need to update to get the `id`
				self.game_override, = conn.execute(
					games.insert(postgresql_on_conflict=DoUpdate([games.c.name]).set_with_excluded(games.c.name))
						.returning(games.c.id), {
					"name": name,
				}).first()
		self.get_game_id.reset_throttle()

	def get_show_id(self):
		if self.show_override is None:
			return self.show_id
		return self.show_override

	def set_show(self, string_id):
		"""
			Set current show.
		"""
		shows = self.metadata.tables["shows"]
		with self.engine.begin() as conn:
			# need to update to get the `id`
			self.show_id, = conn.execute(shows.insert(postgresql_on_conflict=DoUpdate([shows.c.string_id])
					.set_with_excluded(shows.c.string_id)).returning(shows.c.id), {
				"name": string_id,
				"string_id": string_id,
			}).first()

	def override_show(self, string_id):
		"""
			Override current show.
		"""
		if string_id is None:
			self.show_override = None
		else:
			shows = self.metadata.tables["shows"]
			with self.engine.begin() as conn:
				show_id = conn.execute(sqlalchemy.select([shows.c.id])
					.where(shows.c.string_id == string_id)).first()
				if show_id is None:
					raise KeyError(string_id)
				self.show_override, = show_id


	def is_mod(self, event):
		"""Check whether the source of the event has mod privileges for the bot, or for the channel"""
		return event.tags["mod"]

	def is_sub(self, event):
		"""Check whether the source of the event is a known subscriber to the channel"""
		return event.tags["subscriber"]

	@asyncio.coroutine
	def ban(self, conn, event, reason, bantype):
		source = irc.client.NickMask(event.source)
		display_name = event.tags.get("display_name", source.nick)
		if bantype == "spam":
			# Start lenient in case of false positives, but then escalate
			self.spammers.setdefault(source.nick.lower(), 0)
			self.spammers[source.nick.lower()] += 1
			level = self.spammers[source.nick.lower()]
			if level <= 1:
				log.info("First offence, flickering %s" % display_name)
				conn.privmsg(event.target, ".timeout %s 1" % source.nick)
				conn.privmsg(source.nick, "Message deleted (first warning) for auto-detected spam (%s). Please contact mrphlip or any other channel moderator if this is incorrect." % reason)
				yield from slack.send_message("%s flickered for auto-detected spam (%s)" % (display_name, reason))
			elif level <= 2:
				log.info("Second offence, timing out %s" % display_name)
				conn.privmsg(event.target, ".timeout %s" % source.nick)
				conn.privmsg(source.nick, "Timeout (second warning) for auto-detected spam (%s). Please contact mrphlip or any other channel moderator if this is incorrect." % reason)
				yield from slack.send_message("%s timed out for auto-detected spam (%s)" % (display_name, reason))
			else:
				log.info("Third offence, banning %s" % display_name)
				conn.privmsg(event.target, ".ban %s" % source.nick)
				conn.privmsg(source.nick, "Banned for persistent spam (%s). Please contact mrphlip or any other channel moderator if this is incorrect." % reason)
				yield from slack.send_message("%s banned for auto-detected spam (%s)" % (display_name, reason))
				level = 3
			today = datetime.datetime.now(config['timezone']).date().toordinal()
			if today != storage.data.get("spam", {}).get("date"):
				storage.data["spam"] = {
					"date": today,
					"count": [0, 0, 0],
				}
			storage.data["spam"]["count"][level - 1] += 1
			storage.save()
		elif bantype == "censor":
			# Only purges, no escalation
			log.info("Censor hit, flickering %s" % display_name)
			conn.privmsg(event.target, ".timeout %s 1" % source.nick)
			conn.privmsg(source.nick, "Your message was automatically deleted (%s). You have not been banned or timed out, and are welcome to continue participating in the chat. Please contact mrphlip or any other channel moderator if you feel this is incorrect." % reason)
			yield from slack.send_message(text="%s censored (%s)" % (display_name, reason))

	@utils.swallow_errors
	def check_polls(self):
		from lrrbot.commands.strawpoll import check_polls
		check_polls(self, self.connection)

	@utils.swallow_errors
	def vote_respond(self):
		from lrrbot.commands.game import vote_respond
		if self.vote_update is not None:
			vote_respond(self, self.connection, *self.vote_update)

	def check_privmsg_wrapper(self, conn, event):
		"""
		Install a wrapper around privmsg that handles:
		* Throttle messages sent so we don't get banned by Twitch
		* Turn private messages into Twitch whispers
		* Log public messages in the chat log
		"""
		if hasattr(conn.privmsg, "is_wrapped"):
			return
		original_privmsg = lrrbot.decorators.twitch_throttle()(conn.privmsg)
		@functools.wraps(original_privmsg)
		def new_privmsg(target, text):
			if irc.client.is_channel(target):
				username = config["username"]
				chatlog.log_chat(irc.client.Event("pubmsg", username, target, [text]), SELF_METADATA)
				original_privmsg(target, text)
			elif self.whisperconn:
				self.whisperconn.whisper(target, text)
			else:
				log.info("Not sending private message to %s: %s", target, text)
		new_privmsg.is_wrapped = True
		conn.privmsg = new_privmsg

	def on_whisper_received(self, conn, event):
		# Act like this is a private message
		event.type = "privmsg"
		event.target = config['username']
		self.reactor._handle_event(self.connection, event)

bot = LRRBot(asyncio.get_event_loop())
