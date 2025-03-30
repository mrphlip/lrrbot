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
from blinker import Signal
from sqlalchemy.dialects.postgresql import insert

from common import game_data
from common import postgres
from common import slack
from common import state
from common import twitch
from common import utils
from common import youtube
from common.config import config
from common.eventsub import EventSub
from common.account_providers import ACCOUNT_PROVIDER_TWITCH, ACCOUNT_PROVIDER_YOUTUBE

from lrrbot import asyncreactor
from lrrbot import cardviewer
from lrrbot import chatlog
from lrrbot import command_parser
from lrrbot import decorators
from lrrbot import desertbus_moderator_actions
from lrrbot import join_filter
from lrrbot import linkspam
from lrrbot import moderator_actions
from lrrbot import rpc
from lrrbot import spam
from lrrbot import storage
from lrrbot import stream_status
from lrrbot import systemd
from lrrbot import timers
from lrrbot import twitchcheer
from lrrbot import twitchfollows
from lrrbot import twitchnotify
from lrrbot import whisper
from lrrbot import youtube_chat

log = logging.getLogger('lrrbot')

SELF_METADATA = {'specialuser': {'mod', 'subscriber'}, 'usercolor': '#FF0000', 'emoteset': {317}}

class LRRBot(irc.bot.SingleServerIRCBot):
	game_override = state.Property("lrrbot.main.game_override")
	show_override = state.Property("lrrbot.main.show_override")
	access = state.Property("lrrbot.main.access", "all")
	show_id = state.Property("lrrbot.main.show_id")
	cardview = state.Property("lrrbot.main.cardview", False)
	cardview_yt = state.Property("lrrbot.main.cardview_yt", False)

	def __init__(self, loop):
		self.engine, self.metadata = postgres.get_engine_and_metadata()
		accounts = self.metadata.tables["accounts"]
		if config['password'] == "oauth":
			with self.engine.connect() as conn:
				row = conn.execute(sqlalchemy.select(accounts.c.access_token)
					.where(accounts.c.provider == ACCOUNT_PROVIDER_TWITCH)
					.where(accounts.c.name == config['username'])).first()
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
			context = ssl.create_default_context()
			connect_factory = irc.connection.Factory(wrapper=lambda socket: context.wrap_socket(socket, server_hostname=config['hostname']))
		else:
			connect_factory = irc.connection.Factory()
		super(LRRBot, self).__init__(
			server_list=[server],
			realname=config['username'],
			nickname=config['username'],
			recon=irc.bot.ExponentialBackoff(
				min_interval=config['reconnecttime'],
				max_interval=config['reconnecttime'],
			),
			connect_factory=connect_factory,
		)

		# Send a keep-alive message every minute, to catch network dropouts
		# self.connection has a set_keepalive method, but it crashes
		# if it triggers while the connection is down, so do this instead
		self.reactor.scheduler.execute_every(config['keepalivetime'], self.do_keepalive)
		self.reactor.add_global_handler('pong', self.on_pong)
		self.missed_pings = 0

		self.reactor.add_global_handler('reconnect', self.disconnect)

		self.started_signal = Signal()

		self.service = systemd.Service(loop)

		if config['whispers']:
			self.whisperconn = whisper.TwitchWhisper(self, self.loop)
		else:
			self.whisperconn = None

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
		self.reactor.add_global_handler('clearmsg', self.on_clearmsg)
		if self.whisperconn:
			self.whisperconn.add_whisper_handler(self.on_whisper_received)

		# Set up bot state
		if self.show_id is None:
			self.set_show("")

		self.spammers = {}

		self.rpc_server = rpc.Server(self, loop)

		self.chatlog = chatlog.ChatLog(self.engine, self.metadata)

		self.cardviewer = cardviewer.CardViewer(self, self.loop)

		self.commands = command_parser.CommandParser(self, loop)

		self.eventsub = EventSub(loop)

		self.desertbus_moderator_actions = desertbus_moderator_actions.ModeratorActions(self, loop)
		self.join_filter = join_filter.JoinFilter(self, loop)
		self.link_spam = linkspam.LinkSpam(self, loop)
		self.moderator_actions = moderator_actions.ModeratorActions(self, loop)
		self.spam = spam.Spam(self, loop)
		self.stream_status = stream_status.StreamStatus(self, loop)
		self.timers = timers.Timers(self, loop)
		self.twitchnotify = twitchnotify.TwitchNotify(self, loop)
		self.twitchcheer = twitchcheer.TwitchCheer(self, loop)
		self.twitchfollows = twitchfollows.TwitchFollows(self, loop)

		if config['youtube_chat_enabled']:
			self.youtube_chat = youtube_chat.YoutubeChat(self, loop)
		else:
			self.youtube_chat = None

	def reactor_class(self):
		return asyncreactor.AsyncReactor(self.loop)

	def start(self):
		try:
			os.unlink(config['socket_filename'])
		except FileNotFoundError:
			pass
		self.loop.run_until_complete(self.rpc_server.start(config['socket_filename'], config['socket_port']))

		# Start background tasks
		chatlogtask = asyncio.ensure_future(self.chatlog.run_task(), loop=self.loop)
		self.eventsub.start()

		self._connect()

		# Don't fall over if the server sends something that's not real UTF-8
		self.connection.buffer.errors = "replace"

		try:
			self.loop.run_until_complete(self.started_signal.send_async(self))

			self.loop.run_forever()
		finally:
			log.info("Bot shutting down...")
			self.loop.run_until_complete(self.eventsub.stop())
			self.loop.run_until_complete(self.rpc_server.close())
			self.chatlog.stop_task()
			tasks_waiting = [chatlogtask]
			if self.whisperconn:
				tasks_waiting.append(self.whisperconn.stop_task())
			tasks_waiting.append(self.twitchnotify.stop_task())
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
			'id': event.tags.get('id'),
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
		self.chatlog.log_chat(event, metadata)

	@utils.swallow_errors
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

		if tags.get("badges"):
			badges = set(badge.split('/')[0] for badge in tags["badges"].split(','))
		else:
			badges = set()

		# User is a subscriber if they:
		#  * Are marked as a subscriber (in a deprecated tag)
		is_sub = bool(int(tags.get("subscriber", 0)))
		#  * Have the subscriber or founder badge
		is_sub = is_sub or bool(badges & {'subscriber', 'founder'})
		tags["subscriber"] = is_sub

		# User is a moderator if they:
		#  * Are marked as a moderator (in a deprecated tag)
		is_mod = bool(int(tags.get('mod', 0)))
		#  * Is some sort of Twitchsm'n (another deprecated tag)
		is_mod = is_mod or tags.get('user-type', '') in {'mod', 'global_mod', 'admin', 'staff'}
		#  * Has one of the relevant badges
		is_mod = is_mod or bool(badges & {'moderator', 'global_mod', 'admin', 'staff', 'broadcaster'})
		#  * Is broadcaster
		is_mod = is_mod or nick.lower() == config['channel']
		#  * Is in list of extra mods
		is_mod = is_mod or nick.lower() in config['mods']
		tags["mod"] = is_mod

		if 'bits' in tags:
			tags['bits'] = int(tags['bits'])

		if "user-id" not in tags:
			tags["display-name"] = tags.get("display-name", nick)
			return

		accounts = self.metadata.tables["accounts"]
		with self.engine.connect() as db_conn:
			if isinstance(conn, irc.client.ServerConnection):
				if event.type == "pubmsg":
					query = insert(accounts).returning(accounts.c.user_id)
					query = query.on_conflict_do_update(
						index_elements=[accounts.c.provider, accounts.c.provider_user_id],
						set_={
							'name': query.excluded.name,
							'display_name': query.excluded.display_name,
							'is_sub': query.excluded.is_sub,
							'is_mod': query.excluded.is_mod,
						},
					)
					user_data = {
						"provider": ACCOUNT_PROVIDER_TWITCH,
						"provider_user_id": tags["user-id"],
						"name": nick,
						"display_name": tags.get("display-name"),
						"is_sub": is_sub,
						"is_mod": is_mod,
					}
					user_id = db_conn.execute(query, user_data).scalar_one()
				else:
					row = db_conn.execute(sqlalchemy.select(accounts.c.user_id, accounts.c.is_sub, accounts.c.is_mod)
										 .where(accounts.c.provider == ACCOUNT_PROVIDER_TWITCH)
										 .where(accounts.c.provider_user_id == event.tags['user-id'])).first()
					if row is not None:
						user_id, tags['subscriber'], tags['mod'] = row
					else:
						user_id = None
						tags['subscriber'] = False
						tags['mod'] = False
			elif isinstance(conn, youtube_chat.YoutubeChatConnection):
				query = insert(accounts).returning(accounts.c.user_id)
				query = query.on_conflict_do_update(
					index_elements=[accounts.c.provider, accounts.c.provider_user_id],
					set_={
						'name': query.excluded.name,
						'is_sub': query.excluded.is_sub,
						'is_mod': query.excluded.is_mod,
					}
				)
				user_data = {
					"provider": ACCOUNT_PROVIDER_YOUTUBE,
					"provider_user_id": tags["user-id"],
					"name": tags['display-name'],
					"is_sub": is_sub,
					"is_mod": is_mod,
				}
				user_id = db_conn.execute(query, user_data).scalar_one()
			else:
				user_id = None

			if user_id is not None:
				accounts = db_conn.execute(
					sqlalchemy.select(accounts.c.provider, accounts.c.is_sub, accounts.c.is_mod)
					.where(accounts.c.user_id == user_id)
				).all()
				tags['subscriber_anywhere'] = any(account.is_sub for account in accounts)
				tags['mod_anywhere'] = any(account.is_mod for account in accounts)
			db_conn.commit()

		tags["display-name"] = tags.get("display-name", nick)

	@utils.swallow_errors
	def on_clearchat(self, conn, event):
		# This message is both "CLEARCHAT" to clear the whole chat
		# or "CLEARCHAT :someuser" to purge a single user
		if len(event.arguments) >= 1:
			self.chatlog.clear_chat_log(event.arguments[0])

	@utils.swallow_errors
	def on_clearmsg(self, conn, event):
		# This message is sent when a single message is purged
		self.check_message_tags(conn, event)
		self.chatlog.clear_chat_log_msg(event.tags.get('target-msg-id'))

	@utils.cache(twitch.GAME_CHECK_INTERVAL)
	async def get_game_id(self):
		if self.game_override is None:
			game = await twitch.get_game_playing()
			if game is None:
				return None
			game_id, game_name = game.id, game.name

			games = self.metadata.tables["games"]
			with self.engine.connect() as conn:
				query = insert(games)
				query = query.on_conflict_do_update(index_elements=[games.c.id], set_={"name": query.excluded.name})
				conn.execute(query, {
					"id": game_id,
					"name": game_name
				})
				conn.commit()
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
			with self.engine.connect() as conn:
				row = conn.execute(sqlalchemy.select(games.c.id).where(games.c.name == name)).first()
				if not row:
					row = conn.execute(sqlalchemy.insert(games).returning(games.c.id), {"name": name}).first()
				self.game_override, = row
				conn.commit()
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
		with self.engine.connect() as conn:
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
			conn.commit()

	def override_show(self, string_id):
		"""
			Override current show.
		"""
		if string_id is None:
			self.show_override = None
		else:
			shows = self.metadata.tables["shows"]
			with self.engine.connect() as conn:
				show_id = conn.execute(sqlalchemy.select(shows.c.id)
					.where(shows.c.string_id == string_id)).first()
				if show_id is None:
					raise KeyError(string_id)
				self.show_override, = show_id

	async def on_stream_online(self):
		twitch.get_info.reset_throttle()
		self.get_game_id.reset_throttle()

		slack_message = None

		data = await twitch.get_info()

		shows = self.metadata.tables["shows"]
		with self.engine.connect() as conn:
			string_id = conn.execute(sqlalchemy.select(shows.c.string_id).where(shows.c.id == self.show_id)).scalar_one_or_none()
			if string_id != "":
				# Show has been set so something already, assume it's correct.
				return

			try:
				self.show_id = conn.execute(sqlalchemy.select(shows.c.id).where(sqlalchemy.func.regexp_like(data["title"], shows.c.pattern, 'i'))).scalar_one()
			except sqlalchemy.exc.NoResultFound:
				slack_message = "Failed to determine the show from stream title: no results found"
			except sqlalchemy.exc.MultipleResultsFound:
				slack_message = "Failed to determine the show from stream title: multiple results found"

		if slack_message is not None:
			await slack.send_message(slack_message, attachments=[{"text": slack.escape(data["title"])}])

	async def on_stream_offline(self):
		self.override_game(None)
		self.override_show(None)
		self.set_show("")

	def is_mod(self, event):
		"""Check whether the source of the event has mod privileges for the bot, or for the channel"""
		return event.tags["mod"] or event.tags.get("mod_anywhere")

	def is_sub(self, event):
		"""Check whether the source of the event is a known subscriber to the channel"""
		return event.tags["subscriber"] or event.tags.get("subscriber_anywhere")

	async def ban(self, conn, event, reason, bantype):
		source = irc.client.NickMask(event.source)
		display_name = event.tags.get("display-name", source.nick)

		if event.tags["mod"]:
			# Can't time out or ban other moderators, unfortunately.
			log.info("%s is a moderator, not timing out" % display_name)
			return

		if bantype == "spam":
			# Start lenient in case of false positives, but then escalate
			self.spammers.setdefault(source.nick.lower(), 0)
			self.spammers[source.nick.lower()] += 1
			level = self.spammers[source.nick.lower()]
			if level <= 1:
				log.info("First offence, flickering %s" % display_name)
				if isinstance(conn, irc.client.ServerConnection):
					await twitch.ban_user(event.tags['room-id'], event.tags['user-id'], reason, 1)
					conn.privmsg(source.nick, "Message deleted (first warning) for auto-detected spam (%s). Please contact mrphlip or any other channel moderator if this is incorrect." % reason)
				elif isinstance(conn, youtube_chat.YoutubeChatConnection):
					await youtube.ban_user(config['youtube_bot_id'], event.tags['room-id'], event.tags['user-id'], 1)
			elif level <= 2:
				log.info("Second offence, timing out %s" % display_name)
				if isinstance(conn, irc.client.ServerConnection):
					await twitch.ban_user(event.tags['room-id'], event.tags['user-id'], reason, 600)
					conn.privmsg(source.nick, "Timeout (second warning) for auto-detected spam (%s). Please contact mrphlip or any other channel moderator if this is incorrect." % reason)
				elif isinstance(conn, youtube_chat.YoutubeChatConnection):
					await youtube.ban_user(config['youtube_bot_id'], event.tags['room-id'], event.tags['user-id'], 600)
			else:
				log.info("Third offence, banning %s" % display_name)
				if isinstance(conn, irc.client.ServerConnection):
					await twitch.ban_user(event.tags['room-id'], event.tags['user-id'], reason)
					conn.privmsg(source.nick, "Banned for persistent spam (%s). Please contact mrphlip or any other channel moderator if this is incorrect." % reason)
				elif isinstance(conn, youtube_chat.YoutubeChatConnection):
					await youtube.ban_user(config['youtube_bot_id'], event.tags['room-id'], event.tags['user-id'])
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
			if isinstance(conn, irc.client.ServerConnection):
				await twitch.ban_user(event.tags['room-id'], event.tags['user-id'], reason, 1)
				conn.privmsg(source.nick, "Your message was automatically deleted (%s). You have not been banned or timed out, and are welcome to continue participating in the chat. Please contact mrphlip or any other channel moderator if you feel this is incorrect." % reason)
			elif isinstance(conn, youtube_chat.YoutubeChatConnection):
				await youtube.ban_user(config['youtube_bot_id'], event.tags['room-id'], event.tags['user-id'], 1)

	def check_privmsg_wrapper(self, conn, event):
		"""
		Install a wrapper around privmsg that handles:
		* Throttle messages sent so we don't get banned by Twitch
		* Turn private messages into Twitch whispers
		* Log public messages in the chat log
		"""
		if hasattr(conn.privmsg, "is_wrapped") or isinstance(conn, youtube_chat.YoutubeChatConnection):
			return
		original_privmsg = decorators.twitch_throttle()(conn.privmsg)
		@functools.wraps(original_privmsg)
		def new_privmsg(target, text):
			if irc.client.is_channel(target):
				username = config["username"]
				text = utils.trim_length(text, do_warn=True)
				self.chatlog.log_chat(irc.client.Event("pubmsg", username, target, [text]), SELF_METADATA)
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
