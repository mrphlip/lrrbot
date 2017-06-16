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
from sqlalchemy.dialects.postgresql import insert

import common.postgres
import lrrbot.decorators
import lrrbot.systemd
from common import utils
from common.config import config
from common import twitch
from common import slack
from common import game_data
from common.pubsub import PubSub
from lrrbot import chatlog, storage, twitchsubs, whisper, asyncreactor, linkspam, cardviewer
from lrrbot import spam
from lrrbot import command_parser
from lrrbot import rpc
from lrrbot import join_filter
from lrrbot import twitchfollows
from lrrbot import twitchcheer
from lrrbot import moderator_actions
from lrrbot import desertbus_moderator_actions
from lrrbot import video_playback

log = logging.getLogger('lrrbot')

SELF_METADATA = {'specialuser': {'mod', 'subscriber'}, 'usercolor': '#FF0000', 'emoteset': {317}}

class LRRBot(irc.bot.SingleServerIRCBot):
	def __init__(self, loop):
		self.engine, self.metadata = common.postgres.new_engine_and_metadata()
		users = self.metadata.tables["users"]
		if config['password'] == "oauth":
			with self.engine.begin() as conn:
				row = conn.execute(sqlalchemy.select([users.c.twitch_oauth])
					.where(users.c.name == config['username'])).first()
				if row is not None:
					password, = row
				else:
					password = ""
				if password is None:
					password = ""
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
		self.reactor.scheduler.execute_every(config['keepalivetime'], self.do_keepalive)
		self.reactor.add_global_handler('pong', self.on_pong)
		self.missed_pings = 0

		self.reactor.add_global_handler('reconnect', self.disconnect)

		self.reactor.scheduler.execute_every(5, self.check_polls)

		self.service = lrrbot.systemd.Service(loop)

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
		self.access = "all"
		self.set_show("")
		self.polls = []
		self.cardview = False

		self.spammers = {}

		self.rpc_server = rpc.Server(self, loop)

		self.commands = command_parser.CommandParser(self, loop)
		self.command = self.commands.decorator

		self.pubsub = PubSub(self.engine, self.metadata)

		self.link_spam = linkspam.LinkSpam(self, loop)
		self.spam = spam.Spam(self, loop)
		self.subs = twitchsubs.TwitchSubs(self, loop)
		self.join_filter = join_filter.JoinFilter(self, loop)
		self.twitchfollows = twitchfollows.TwitchFollows(self, loop)
		self.twitchcheer = twitchcheer.TwitchCheer(self, loop)
		self.moderator_actions = moderator_actions.ModeratorActions(self, loop)
		self.desertbus_moderator_actions = desertbus_moderator_actions.ModeratorActions(self, loop)
		self.video_playback = video_playback.VideoPlayback(self, loop)

	def reactor_class(self):
		return asyncreactor.AsyncReactor(self.loop)

	def start(self):
		try:
			os.unlink(config['socket_filename'])
		except FileNotFoundError:
			pass
		self.loop.run_until_complete(self.rpc_server.start(config['socket_filename'], config['socket_port']))

		# Start background tasks
		chatlogtask = asyncio.async(chatlog.run_task(), loop=self.loop)

		self._connect()
		self.cardviewer.start()

		# Don't fall over if the server sends something that's not real UTF-8
		self.connection.buffer.errors = "replace"

		try:
			self.loop.run_forever()
		finally:
			log.info("Bot shutting down...")
			self.pubsub.close()
			self.loop.run_until_complete(self.rpc_server.close())
			chatlog.stop_task()
			tasks_waiting = [chatlogtask]
			if self.whisperconn:
				tasks_waiting.append(self.whisperconn.stop_task())
			tasks_waiting.append(self.cardviewer.stop())
			self.loop.run_until_complete(asyncio.wait(tasks_waiting))

	def disconnect(self, msg="I'll be back!"):
		self.missed_pings = 0
		return super().disconnect(msg)

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
		if self.missed_pings >= config['keepalivethreshold']:
			self.disconnect()
			return
		try:
			self.connection.ping("keep-alive")
			self.missed_pings += 1
		except irc.client.ServerNotConnectedError:
			# Don't disconnect while disconnected.
			self.missed_pings = 0

	def on_pong(self, conn, event):
		self.missed_pings = 0

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
		if event.tags.get('subscriber'):
			metadata['specialuser'].add('subscriber')
		if int(event.tags.get('turbo', 0)):
			metadata['specialuser'].add('turbo')
		if event.tags.get('user-type'):
			metadata['specialuser'].add(event.tags.get('user-type'))
		if event.tags.get('mod'):
			metadata['specialuser'].add('mod')
		if event.tags.get('bits'):
			metadata['specialuser'].add('cheer')
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
		if 'login' in tags:
			event.source = nick = tags['login'].lower()
		else:
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

		if 'bits' in tags:
			tags['bits'] = int(tags['bits'])

		if "user-id" not in tags:
			tags["display_name"] = tags.get("display_name", nick)
			return
		tags["user-id"] = int(tags["user-id"])

		users = self.metadata.tables["users"]
		patreon_users = self.metadata.tables["patreon_users"]
		with self.engine.begin() as conn:
			if event.type == "pubmsg":
				query = insert(users)
				query = query.on_conflict_do_update(
					index_elements=[users.c.id],
					set_={
						'name': query.excluded.name,
						'display_name': query.excluded.display_name,
						'is_sub': query.excluded.is_sub,
						'is_mod': query.excluded.is_mod,
					},
				)
				conn.execute(query, {
					"id": tags["user-id"],
					"name": nick,
					"display_name": tags.get("display-name"),
					"is_sub": is_sub,
					"is_mod": is_mod,
				})
			else:
				row = conn.execute(sqlalchemy.select([users.c.is_sub, users.c.is_mod])
					.where(users.c.id == event.tags['user-id'])).first()
				if row is not None:
					tags['subscriber'], tags['mod'] = row
				else:
					tags['subscriber'] = False
					tags['mod'] = False
			is_patron = conn.execute(sqlalchemy.select([patreon_users.c.pledge_start.isnot(None)])
				.select_from(patreon_users.join(users))
				.where(users.c.id == tags['user-id'])
			).first()
			if is_patron is not None:
				tags['patron'] = is_patron[0]
			else:
				tags['patron'] = False

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
					query = insert(games)
					query = query.on_conflict_do_update(index_elements=[games.c.id], set_={
						"name": query.excluded.name,
					})
					conn.execute(query, {
						"id": game_id,
						"name": game_name
					})
				else:
					old_id, = old_id
					conn.execute(insert(games).on_conflict_do_nothing(index_elements=[games.c.id]), {
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
				query = insert(games).returning(games.c.id)
				# need to update to get the `id`
				query = query.on_conflict_do_update(
					index_elements=[games.c.name],
					set_={
						'name': query.excluded.name,
					}
				)
				self.game_override, = conn.execute(query, {
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
			query = insert(shows).returning(shows.c.id)
			query = query.on_conflict_do_update(
				index_elements=[shows.c.string_id],
				set_={
					'string_id': query.excluded.string_id,
				},
			)
			self.show_id, = conn.execute(query, {
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
		return event.tags["subscriber"] or event.tags["patron"]

	async def ban(self, conn, event, reason, bantype):
		source = irc.client.NickMask(event.source)
		display_name = event.tags.get("display_name", source.nick)
		if bantype == "spam":
			# Start lenient in case of false positives, but then escalate
			self.spammers.setdefault(source.nick.lower(), 0)
			self.spammers[source.nick.lower()] += 1
			level = self.spammers[source.nick.lower()]
			if level <= 1:
				log.info("First offence, flickering %s" % display_name)
				conn.privmsg(event.target, ".timeout %s 1 %s" % (source.nick, reason))
				conn.privmsg(source.nick, "Message deleted (first warning) for auto-detected spam (%s). Please contact mrphlip or any other channel moderator if this is incorrect." % reason)
			elif level <= 2:
				log.info("Second offence, timing out %s" % display_name)
				conn.privmsg(event.target, ".timeout %s 600 %s" % (source.nick, reason))
				conn.privmsg(source.nick, "Timeout (second warning) for auto-detected spam (%s). Please contact mrphlip or any other channel moderator if this is incorrect." % reason)
			else:
				log.info("Third offence, banning %s" % display_name)
				conn.privmsg(event.target, ".ban %s %s" % (source.nick, reason))
				conn.privmsg(source.nick, "Banned for persistent spam (%s). Please contact mrphlip or any other channel moderator if this is incorrect." % reason)
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
			conn.privmsg(event.target, ".timeout %s 1 %s" % (source.nick, reason))
			conn.privmsg(source.nick, "Your message was automatically deleted (%s). You have not been banned or timed out, and are welcome to continue participating in the chat. Please contact mrphlip or any other channel moderator if you feel this is incorrect." % reason)

	@utils.swallow_errors
	def check_polls(self):
		from lrrbot.commands.strawpoll import check_polls
		check_polls(self, self.connection)

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
