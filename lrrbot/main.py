# -*- coding: utf-8 -*-

import os
import re
import time
import datetime
import json
import logging
import functools
import asyncio
import traceback

import irc.bot
import irc.client
import irc.modes
import irc.connection

import common.http
import lrrbot.decorators
import lrrbot.systemd
from common import utils
from common.config import config
from lrrbot import chatlog, storage, twitch, twitchsubs, whisper, asyncreactor, linkspam, cardviewer

log = logging.getLogger('lrrbot')

SELF_METADATA = {'specialuser': {'mod', 'subscriber'}, 'usercolor': '#FF0000', 'emoteset': {317}}

class LRRBot(irc.bot.SingleServerIRCBot, linkspam.LinkSpam):
	def __init__(self, loop):
		self.loop = loop
		server = irc.bot.ServerSpec(
			host=config['hostname'],
			port=config['port'],
			password="oauth:%s" % storage.data['twitch_oauth'][config['username']] if config['password'] == "oauth" else config['password'],
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
			self.whisperconn = whisper.TwitchWhisper(self.loop, self.service)
		else:
			self.whisperconn = None
			self.service.subsystem_started("whispers")

		# create pubnub listener
		self.cardviewer = cardviewer.CardViewer(self, self.loop)

		# IRC event handlers
		self.reactor.add_global_handler('welcome', self.on_connect)
		self.reactor.add_global_handler('join', self.on_channel_join)
		self.reactor.add_global_handler('pubmsg', self.on_message)
		self.reactor.add_global_handler('privmsg', self.on_message)
		self.reactor.add_global_handler('action', self.on_message_action)
		self.reactor.add_global_handler('clearchat', self.on_clearchat)
		if self.whisperconn:
			self.whisperconn.add_whisper_handler(self.on_whisper)

		# Commands
		self.commands = {}
		self.re_botcommand = None
		self.command_groups = {}
		self.server_events = {}

		# Precompile regular expressions
		self.re_subscription = re.compile(r"^(.*) just subscribed!$", re.IGNORECASE)
		self.re_resubscription = re.compile(r"^(.*) subscribed for (\d+) months? in a row!$", re.IGNORECASE)

		# Set up bot state
		self.game_override = None
		self.show_override = None
		self.calendar_override = None
		self.vote_update = None
		self.access = "all"
		self.show = ""
		self.polls = []
		self.lastsubs = []

		self.spam_rules = [(re.compile(i['re']), i['message']) for i in storage.data['spam_rules']]
		self.spammers = {}

		self.mods = set(storage.data.get('mods', config['mods']))
		self.subs = set(storage.data.get('subs', []))
		self.autostatus = set(storage.data.get('autostatus', []))

		linkspam.LinkSpam.__init__(self, loop)

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
		substask = asyncio.async(twitchsubs.watch_subs(self), loop=self.loop)
		chatlogtask = asyncio.async(chatlog.run_task(), loop=self.loop)

		self._connect()
		if self.whisperconn:
			self.whisperconn._connect()
		self.cardviewer.start()

		# Don't fall over if the server sends something that's not real UTF-8
		self.connection.buffer.errors = "replace"
		if self.whisperconn:
			self.whisperconn.connection.buffer.errors = "replace"

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
			self.loop.close()

	def add_command(self, pattern, function):
		if not asyncio.iscoroutinefunction(function):
			function = asyncio.coroutine(function)
		pattern = pattern.replace(" ", r"(?:\s+)")
		self.commands[pattern] = {
			"groups": re.compile(pattern, re.IGNORECASE).groups,
			"func": function,
		}

	def remove_command(self, pattern):
		del self.commands[pattern.replace(" ", r"(?:\s+)")]

	def command(self, pattern):
		def wrapper(function):
			self.add_command(pattern, function)
			return function
		return wrapper

	def compile(self):
		self.re_botcommand = r"^\s*%s\s*(?:" % re.escape(config["commandprefix"])
		self.re_botcommand += "|".join(map(lambda re: '(%s)' % re, self.commands))
		self.re_botcommand += r")\s*$"
		self.re_botcommand = re.compile(self.re_botcommand, re.IGNORECASE)

		i = 1
		for val in self.commands.values():
			self.command_groups[i] = (val["func"], i+val["groups"])
			i += 1+val["groups"]

	def add_server_event(self, name, function):
		self.server_events[name.lower()] = function

	def remove_server_event(self, name):
		del self.server_events[name.lower()]

	def server_event(self, name=None):
		def wrapper(function):
			nonlocal name
			if name is None:
				name = function.__name__
			self.add_server_event(name, function)
			return function
		return wrapper

	def on_connect(self, conn, event):
		"""On connecting to the server, join our target channel"""
		log.info("Connected to server")
		conn.cap("REQ", "twitch.tv/tags") # get metadata tags
		conn.cap("REQ", "twitch.tv/commands") # get special commands
		conn.join("#%s" % config['channel'])
		conn.cap("REQ", "twitch.tv/membership") # get join/part messages - after we join, so we don't get a flood of them when we arrive
		self.check_privmsg_wrapper(conn)

	def on_channel_join(self, conn, event):
		source = irc.client.NickMask(event.source)
		if (source.nick.lower() == config['username'].lower()):
			log.info("Channel %s joined" % event.target)
			self.service.subsystem_started("irc")
		elif source.nick.lower() in self.autostatus:
			from lrrbot.commands.misc import send_status
			send_status(self, conn, source.nick)

	@utils.swallow_errors
	def do_keepalive(self):
		"""Send a ping to the server, to ensure our connection stays alive, or to detect when it drops out."""
		try:
			self.connection.ping("keep-alive")
		except irc.client.ServerNotConnectedError:
			pass

	@utils.swallow_errors
	def on_message(self, conn, event):
		self.check_privmsg_wrapper(conn)

		source = irc.client.NickMask(event.source)
		nick = source.nick.lower()

		if event.type == "pubmsg":
			tags = dict((i['key'], i['value']) for i in event.tags)
			self.check_moderator(conn, nick, tags)
			metadata = {
				'usercolor': tags.get('color'),
				'emotes': tags.get('emotes'),
				'display-name': tags.get('display-name') or nick,
				'specialuser': set(),
			}
			if int(tags.get('subscriber', 0)):
				metadata['specialuser'].add('subscriber')
			if int(tags.get('turbo', 0)):
				metadata['specialuser'].add('turbo')
			if tags.get('user-type'):
				metadata['specialuser'].add(tags.get('user-type'))
			if self.is_mod(event):
				metadata['specialuser'].add('mod')
			log.debug("Message metadata: %r", metadata)
			chatlog.log_chat(event, metadata)
			self.check_subscriber(conn, nick, metadata)

		source = irc.client.NickMask(event.source)
		# If the message was sent to a channel, respond in the channel
		# If it was sent via PM, respond via PM
		if event.type == "pubmsg":
			respond_to = event.target
		else:
			respond_to = source.nick

		if (nick == config['notifyuser']):
			self.on_notification(conn, event, respond_to)
		elif self.check_spam(conn, event, event.arguments[0]):
			return
		else:
			asyncio.async(self.check_urls(conn, event, event.arguments[0]), loop=self.loop).add_done_callback(utils.check_exception)
			if self.access == "mod" and not self.is_mod(event):
				return
			if self.access == "sub" and not self.is_mod(event) and not self.is_sub(event):
				return
			command_match = self.re_botcommand.match(event.arguments[0])
			if command_match:
				command = command_match.group(command_match.lastindex)
				log.info("Command from %s: %s " % (source.nick, command))
				proc, end = self.command_groups[command_match.lastindex]
				params = command_match.groups()[command_match.lastindex:end]
				asyncio.async(proc(self, conn, event, respond_to, *params), loop=self.loop).add_done_callback(utils.check_exception)

	def on_message_action(self, conn, event):
		# Treat CTCP ACTION messages as the raw "/me does whatever" message that
		# was actually typed in. Mostly for passing it through to the chat log
		# but also to make sure the subscriber flags are updated etc.
		event.arguments[0] = "/me " + event.arguments[0]
		if irc.client.is_channel(event.target):
			event.type = "pubmsg"
		else:
			event.type = "privmsg"
		return self.on_message(conn, event)

	def on_notification(self, conn, event, respond_to):
		"""Handle notification messages from Twitch, sending the message up to the web"""
		log.info("Notification: %s" % event.arguments[0])
		subscribe_match = self.re_subscription.match(event.arguments[0])
		if subscribe_match and irc.client.is_channel(event.target):
			# Don't highlight the same sub via both the chat and the API
			if subscribe_match.group(1).lower() not in self.lastsubs:
				self.on_subscriber(conn, event.target, subscribe_match.group(1), time.time())
			return

		subscribe_match = self.re_resubscription.match(event.arguments[0])
		if subscribe_match and irc.client.is_channel(event.target):
			if subscribe_match.group(1).lower() not in self.lastsubs:
				self.on_subscriber(conn, event.target, subscribe_match.group(1), time.time(), monthcount=int(subscribe_match.group(2)))
			return

		notifyparams = {
			'apipass': config['apipass'],
			'message': event.arguments[0],
			'eventtime': time.time(),
		}
		if irc.client.is_channel(event.target):
			notifyparams['channel'] = event.target[1:]
		common.http.api_request('notifications/newmessage', notifyparams, 'POST')

	def on_subscriber(self, conn, channel, user, eventtime, logo=None, monthcount=None):
		notifyparams = {
			'apipass': config['apipass'],
			'message': "%s just subscribed!" % user,
			'eventtime': eventtime,
			'subuser': user,
			'channel': channel,
		}

		if logo is None:
			try:
				channel_info = twitch.get_info_uncached(user)
			except:
				pass
			else:
				if channel_info.get('logo'):
					notifyparams['avatar'] = channel_info['logo']
		else:
			notifyparams['avatar'] = logo

		if monthcount is not None:
			notifyparams['monthcount'] = monthcount

		# have to get this in a roundabout way as datetime.date.today doesn't take a timezone argument
		today = datetime.datetime.now(config['timezone']).date().toordinal()
		if today != storage.data.get("storm",{}).get("date"):
			storage.data["storm"] = {
				"date": today,
				"count": 0,
			}
		storage.data["storm"]["count"] += 1
		self.lastsubs.append(user.lower())
		self.lastsubs = self.lastsubs[-10:]
		storage.save()
		conn.privmsg(channel, "lrrSPOT Thanks for subscribing, %s! (Today's storm count: %d)" % (notifyparams['subuser'], storage.data["storm"]["count"]))
		common.http.api_request('notifications/newmessage', notifyparams, 'POST')

		self.subs.add(user.lower())
		storage.data['subs'] = list(self.subs)
		storage.save()

	def check_subscriber(self, conn, nick, metadata):
		"""
		Whenever a user says something, update the subscriber list according to whether
		their message has the subscriber-badge metadata attached to it.
		"""
		is_sub = 'subscriber' in metadata.get('specialuser', set())
		if not is_sub and nick in self.subs:
			self.subs.remove(nick)
			storage.data['subs'] = list(self.subs)
			storage.save()
		elif is_sub and nick not in self.subs:
			self.subs.add(nick)
			storage.data['subs'] = list(self.subs)
			storage.save()

	@utils.swallow_errors
	def on_clearchat(self, conn, event):
		# This message is both "CLEARCHAT" to clear the whole chat
		# or "CLEARCHAT :someuser" to purge a single user
		if len(event.arguments) >= 1:
			chatlog.clear_chat_log(event.arguments[0])

	def check_moderator(self, conn, nick, tags):
		# Either:
		#  * has sword
		is_mod = tags.get('mod', '0') == '1'
		#  * is some sort of Twitchsm'n
		is_mod = is_mod or tags.get('user-type', '') in {'mod', 'global_mod', 'admin', 'staff'}
		#  * is broadcaster
		is_mod = is_mod or nick.lower() == config['channel']

		if not is_mod and nick in self.mods:
			self.mods.remove(nick)
			storage.data['mods'] = list(self.mods)
			storage.save()
		if is_mod and nick not in self.mods:
			self.mods.add(nick)
			storage.data['mods'] = list(self.mods)
			storage.save()

	def get_current_game(self, readonly=True):
		"""Returns the game currently being played, with caching to avoid hammering the Twitch server"""
		show = self.show_override or self.show
		if self.game_override is not None:
			game_obj = {'_id': self.game_override, 'name': self.game_override, 'is_override': True}
			return storage.find_game(show, game_obj, readonly)
		else:
			return storage.find_game(show, twitch.get_game_playing(), readonly)

	def is_mod(self, event):
		"""Check whether the source of the event has mod privileges for the bot, or for the channel"""
		source = irc.client.NickMask(event.source)
		return source.nick.lower() in self.mods

	def is_mod_nick(self, nick):
		return nick.lower() in self.mods

	def is_sub(self, event):
		"""Check whether the source of the event is a known subscriber to the channel"""
		source = irc.client.NickMask(event.source)
		return source.nick.lower() in self.subs

	def is_sub_nick(self, nick):
		return nick.lower() in self.subs

	def ban(self, conn, event, reason):
		source = irc.client.NickMask(event.source)
		tags = dict((i['key'], i['value']) for i in event.tags)
		display_name = tags.get("display_name") or source.nick
		self.spammers.setdefault(source.nick.lower(), 0)
		self.spammers[source.nick.lower()] += 1
		level = self.spammers[source.nick.lower()]
		if level <= 1:
			log.info("First offence, flickering %s" % display_name)
			conn.privmsg(event.target, ".timeout %s 1" % source.nick)
			conn.privmsg(event.target, "%s: Message deleted (first warning) for auto-detected spam (%s). Please contact mrphlip or d3fr0st5 if this is incorrect." % (display_name, reason))
		elif level <= 2:
			log.info("Second offence, timing out %s" % display_name)
			conn.privmsg(event.target, ".timeout %s" % source.nick)
			conn.privmsg(event.target, "%s: Timeout (second warning) for auto-detected spam (%s). Please contact mrphlip or d3fr0st5 if this is incorrect." % (display_name, reason))
		else:
			log.info("Third offence, banning %s" % display_name)
			conn.privmsg(event.target, ".ban %s" % source.nick)
			conn.privmsg(event.target, "%s: Banned for persistent spam (%s). Please contact mrphlip or d3fr0st5 if this is incorrect." % (display_name, reason))
			level = 3
		today = datetime.datetime.now(config['timezone']).date().toordinal()
		if today != storage.data.get("spam",{}).get("date"):
			storage.data["spam"] = {
				"date": today,
				"count": [0, 0, 0],
		}
		storage.data["spam"]["count"][level - 1] += 1
		storage.save()

	def check_spam(self, conn, event, message):
		"""Check the message against spam detection rules"""
		if not irc.client.is_channel(event.target):
			return False
		respond_to = event.target
		source = irc.client.NickMask(event.source)

		for re, desc in self.spam_rules:
			matches = re.search(message)
			if matches:
				log.info("Detected spam from %s - %r matches %s" % (source.nick, message, re.pattern))
				groups = {str(i+1):v for i,v in enumerate(matches.groups())}
				desc = desc % groups
				self.ban(conn, event, desc)
				return True

		return False

	def rpc_server(self):
		return RPCServer(self)

	def on_server_event(self, request):
		eventproc = self.server_events[request['command'].lower()]
		return eventproc(self, request['user'], request['param'])

	@utils.swallow_errors
	def check_polls(self):
		from lrrbot.commands.strawpoll import check_polls
		check_polls(self, self.connection)

	@utils.swallow_errors
	def vote_respond(self):
		from lrrbot.commands.game import vote_respond
		if self.vote_update is not None:
			vote_respond(self, self.connection, *self.vote_update)

	@utils.swallow_errors
	def on_api_subscriber(self, user, logo, eventtime, channel):
		if user.lower() not in self.lastsubs:
			self.on_subscriber(self.connection, "#%s" % channel, user, eventtime, logo)

	def check_privmsg_wrapper(self, conn):
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
				log.debug("Not sending private message to %s: %s", target, text)
		new_privmsg.is_wrapped = True
		conn.privmsg = new_privmsg

	def on_whisper(self, conn, event):
		# Act like this is a private message
		event.type = "privmsg"
		event.target = config['username']
		self.on_message(self.connection, event)

class RPCServer(asyncio.Protocol):
	def __init__(self, lrrbot):
		self.lrrbot = lrrbot
		self.buffer = b""
	def connection_made(self, transport):
		self.transport = transport
		log.debug("Received event connection from server")
	def data_received(self, data):
		self.buffer += data
		if b"\n" in self.buffer:
			request = json.loads(self.buffer.decode())
			log.debug("Command from server (%s): %s(%r)", request['user'], request['command'], request['param'])
			try:
				response = self.lrrbot.on_server_event(request)
			except:
				log.exception("Exception in on_server_event")
				response = {'success': False, 'result': ''.join(traceback.format_exc())}
			else:
				log.debug("Returning: %r", response)
				response = {'success': True, 'result': response}
			response = json.dumps(response).encode() + b"\n"
			self.transport.write(response)
			self.transport.close()

bot = LRRBot(asyncio.get_event_loop())
