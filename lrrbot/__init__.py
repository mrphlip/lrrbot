# -*- coding: utf-8 -*-

import os
import re
import time
import datetime
import json
import logging
import socket
import select
import functools

import dateutil.parser
import irc.bot
import irc.client
import irc.modes

from common import utils
from common.config import config
from lrrbot import chatlog, storage, twitch


log = logging.getLogger('lrrbot')

SELF_METADATA = {'specialuser': {'mod', 'subscriber'}, 'usercolor': '#FF0000', 'emoteset': {317}}

class LRRBot(irc.bot.SingleServerIRCBot):
	GAME_CHECK_INTERVAL = 5*60 # Only check the current game at most once every five minutes

	def __init__(self):
		server = irc.bot.ServerSpec(
			host=config['hostname'],
			port=config['port'],
			password="oauth:%s" % storage.data['twitch_oauth'][config['username']] if config['password'] == "oauth" else config['password'],
		)
		super(LRRBot, self).__init__(
			server_list=[server],
			realname=config['username'],
			nickname=config['username'],
			reconnection_interval=config['reconnecttime'],
		)

		# Send a keep-alive message every minute, to catch network dropouts
		# self.connection has a set_keepalive method, but it crashes
		# if it triggers while the connection is down, so do this instead
		self.reactor.execute_every(period=config['keepalivetime'], function=self.do_keepalive)

		self.reactor.execute_every(period=5, function=self.check_polls)
		self.reactor.execute_every(period=5, function=self.vote_respond)
		self.reactor.execute_every(period=config['checksubstime'], function=self.check_subscriber_list)

		# IRC event handlers
		self.reactor.add_global_handler('welcome', self.on_connect)
		self.reactor.add_global_handler('join', self.on_channel_join)
		self.reactor.add_global_handler('pubmsg', self.on_message)
		self.reactor.add_global_handler('privmsg', self.on_message)
		self.reactor.add_global_handler('action', self.on_message_action)
		self.reactor.add_global_handler('mode', self.on_mode)

		# Commands
		self.commands = {}
		self.re_botcommand = None
		self.command_groups = {}
		self.server_events = {}

		# Precompile regular expressions
		self.re_subscription = re.compile(r"^(.*) just subscribed!", re.IGNORECASE)

		# Set up bot state
		self.game_override = None
		self.show_override = None
		self.calendar_override = None
		self.vote_update = None
		self.access = "all"
		self.show = ""
		self.polls = []
		self.lastsubs = []
		self.havesublist = False

		self.spam_rules = [(re.compile(i['re']), i['message']) for i in storage.data['spam_rules']]
		self.spammers = {}

		self.mods = set(storage.data.get('mods', config['mods']))
		self.subs = set(storage.data.get('subs', []))

		self.metadata = {}
		self.globalflags = {}

		# Let us run on windows, without the socket
		if hasattr(socket, 'AF_UNIX'):
			# TODO: To be more robust, the code really should have a way to shut this socket down
			# when the bot exits... currently, it's assuming that there'll only be one LRRBot
			# instance, that lasts the life of the program... which is true for now...
			try:
				os.unlink(config['socket_filename'])
			except OSError:
				if os.path.exists(config['socket_filename']):
					raise
			self.event_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
			self.event_socket.bind(config['socket_filename'])
			self.event_socket.listen(5)
			self.event_socket.setblocking(False)
		else:
			self.event_socket = None

	def start(self):
		self._connect()

		# Don't fall over if the server sends something that's not real UTF-8
		for conn in self.reactor.connections:
			conn.buffer.errors = "replace"

		while True:
			sockets = [conn.socket for conn in self.reactor.connections if conn and conn.socket]
			sockets.append(self.event_socket)
			(i, o, e) = select.select(sockets, [], [], 0.2)
			if self.event_socket in i:
				try:
					conn, addr = self.event_socket.accept()
				except (OSError, socket.error):
					pass
				else:
					conn.setblocking(True) # docs say this "may" be necessary :-/
					self.on_server_event(conn)
			else:
				self.reactor.process_data(i)
			self.reactor.process_timeout()

	def add_command(self, pattern, function):
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
		self.twitchclient(conn, 3)
		conn.join("#%s" % config['channel'])

	def on_channel_join(self, conn, event):
		source = irc.client.NickMask(event.source)
		if (source.nick.lower() == config['username'].lower()):
			log.info("Channel %s joined" % event.target)

	@utils.swallow_errors
	def do_keepalive(self):
		"""Send a ping to the server, to ensure our connection stays alive, or to detect when it drops out."""
		try:
			self.connection.ping("keep-alive")
		except irc.client.ServerNotConnectedError:
			pass

	def log_outgoing(self, func):
		@functools.wraps(func, assigned=functools.WRAPPER_ASSIGNMENTS + ("is_throttled",))
		def wrapper(target, message):
			username = config["username"]
			chatlog.log_chat(irc.client.Event("pubmsg", username, target, [message]), SELF_METADATA)
			return func(target, message)
		wrapper.is_logged = True
		return wrapper

	@utils.swallow_errors
	def on_message(self, conn, event):
		source = irc.client.NickMask(event.source)
		nick = source.nick.lower()
		if (nick == config['metadatauser']):
			self.on_metadata(conn, event)
			return
		# The flags in self.metadata are sent before every message, so pop those from
		# the storage once we're done... the ones in self.globalflags, though, are sent
		# just once when they join the channel, so need to keep those around.
		metadata = self.metadata.pop(nick, {})
		metadata.setdefault('specialuser', set()).update(self.globalflags.get(nick, []))
		if self.is_mod(event):
			metadata['specialuser'].add('mod')
		if config['debug']:
			log.debug("Message metadata: %r" % metadata)

		chatlog.log_chat(event, metadata)
		if not hasattr(conn.privmsg, "is_throttled"):
			conn.privmsg = utils.twitch_throttle()(conn.privmsg)
		if not hasattr(conn.privmsg, "is_logged"):
			conn.privmsg = self.log_outgoing(conn.privmsg)
		source = irc.client.NickMask(event.source)
		# If the message was sent to a channel, respond in the channel
		# If it was sent via PM, respond via PM		
		if irc.client.is_channel(event.target):
			respond_to = event.target
		else:
			respond_to = source.nick
			
		if (nick == config['notifyuser']):
			self.on_notification(conn, event, respond_to)
		elif self.check_spam(conn, event, event.arguments[0]):
			return
		else:
			self.check_subscriber(conn, nick, metadata)
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
				proc(self, conn, event, respond_to, *params)

	def on_message_action(self, conn, event):
		# Treat CTCP ACTION messages as the raw "/me does whatever" message that
		# was actually typed in. Mostly for passing it through to the chat log
		# but also to make sure the subscriber flags are updated etc.
		event.arguments[0] = "/me " + event.arguments[0]
		return self.on_message(conn, event)

	def on_notification(self, conn, event, respond_to):
		"""Handle notification messages from Twitch, sending the message up to the web"""
		log.info("Notification: %s" % event.arguments[0])
		subscribe_match = self.re_subscription.match(event.arguments[0])
		if subscribe_match and irc.client.is_channel(event.target):
			# Don't highlight the same sub via both the chat and the API
			if subscribe_match.group(1).lower() in self.lastsubs:
				return

			self.on_subscriber(conn, event.target, subscribe_match.group(1), time.time())
		else:
			notifyparams = {
				'apipass': config['apipass'],
				'message': event.arguments[0],
				'eventtime': time.time(),
			}
			if irc.client.is_channel(event.target):
				notifyparams['channel'] = event.target[1:]
			utils.api_request('notifications/newmessage', notifyparams, 'POST')

	def on_subscriber(self, conn, channel, user, eventtime, logo=None):
		notifyparams = {
			'apipass': config['apipass'],
			'message': "%s just subscribed!" % user,
			'eventtime': eventtime,
			'subuser': user,
			'channel': channel,
		}

		if logo is None:
			try:
				channel_info = twitch.get_info(user)
			except:
				pass
			else:
				if channel_info.get('logo'):
					notifyparams['avatar'] = channel_info['logo']
		else:
			notifyparams['avatar'] = logo
			
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
		utils.api_request('notifications/newmessage', notifyparams, 'POST')

		self.subs.add(user.lower())
		storage.data['subs'] = list(self.subs)
		storage.save()

	def on_metadata(self, conn, event):
		"""
		Takes metadata messages from jtv and stores them for the following message they apply to.

		Recognised flags in metadata dict:
		{
			'specialuser': set('subscriber', 'turbo'),
			'usercolor': '#123456',
			'emoteset': set(317, 4269), # 317 is is loadingreadyrun
		}
		"""
		bits = event.arguments[0].split()
		if bits[0] == "SPECIALUSER":
			if irc.client.is_channel(event.target):
				self.metadata.setdefault(bits[1], {}).setdefault('specialuser', set()).update(bits[2:])
			else:
				self.globalflags.setdefault(bits[1], set()).update(bits[2:])
		elif bits[0] == "USERCOLOR":
			self.metadata.setdefault(bits[1], {})['usercolor'] = bits[2]
		elif bits[0] == "EMOTESET":
			# bits[2] == "[123,456,789]"
			emoteset = ''.join(bits[2:]).lstrip('[').rstrip(']').split(',')
			self.metadata.setdefault(bits[1], {})['emoteset'] = set(int(i) for i in emoteset)
		elif bits[0] == "CLEARCHAT":
			# This message is both "CLEARCHAT" to clear the whole chat
			# or "CLEARCHAT someuser" to purge a single user
			if len(bits) >= 2:
				chatlog.clear_chat_log(bits[1])

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

	def on_mode(self, conn, event):
		if irc.client.is_channel(event.target):
			for mode in irc.modes.parse_channel_modes(" ".join(event.arguments)):
				if mode[0] == "+" and mode[1] == 'o':
					self.mods.add(mode[2].lower())
					storage.data['mods'] = list(self.mods)
					storage.save()
				# Son't actually remove users from self.mods on -o, as Twitch chat sends
				# those when the user leaves the channel, and that sometimes happens
				# unreliably, or we might not get a +o when they return...
				# Will just have to remove users from storage.data['mods'] manually
				# should it ever come up.

	def get_current_game(self, readonly=True):
		"""Returns the game currently being played, with caching to avoid hammering the Twitch server"""
		show = self.show_override or self.show
		if self.game_override is not None:
			game_obj = {'_id': self.game_override, 'name': self.game_override, 'is_override': True}
			return storage.find_game(show, game_obj, readonly)
		else:
			return storage.find_game(show, self.get_current_game_real(), readonly)

	@utils.throttle(GAME_CHECK_INTERVAL, log=False)
	def get_current_game_real(self):
		return twitch.get_game_playing()

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
				self.spammers.setdefault(source.nick.lower(), 0)
				self.spammers[source.nick.lower()] += 1
				level = self.spammers[source.nick.lower()]
				if level <= 1:
					log.info("First offence, flickering %s" % source.nick)
					conn.privmsg(event.target, ".timeout %s 1" % source.nick)
					conn.privmsg(event.target, "%s: Message deleted (first warning) for auto-detected spam (%s). Please contact mrphlip or d3fr0st5 if this is incorrect." % (source.nick, desc))
				elif level <= 2:
					log.info("Second offence, timing out %s" % source.nick)
					conn.privmsg(event.target, ".timeout %s" % source.nick)
					conn.privmsg(event.target, "%s: Timeout (second warning) for auto-detected spam (%s). Please contact mrphlip or d3fr0st5 if this is incorrect." % (source.nick, desc))
				else:
					log.info("Third offence, banning %s" % source.nick)
					conn.privmsg(event.target, ".ban %s" % source.nick)
					conn.privmsg(event.target, "%s: Banned for persistent spam (%s). Please contact mrphlip or d3fr0st5 if this is incorrect." % (source.nick, desc))
					level = 3
				today = datetime.datetime.now(config['timezone']).date().toordinal()
				if today != storage.data.get("spam",{}).get("date"):
					storage.data["spam"] = {
						"date": today,
						"count": [0, 0, 0],
				}
				storage.data["spam"]["count"][level - 1] += 1
				storage.save()
				return True
		return False

	def twitchclient(self, conn, level):
		"""
		Undocumented Twitch command that sets how TMI behaves in a variety of
		interesting ways...

		Options:
		1 - The default. Behaves mostly like a real IRC server, with joins and parts
		    (though on a delay) and the like. The jtv user tells you about staff
		    members, but otherwise stays silent.
		2 - Behaves like the previous version of the Twitch web chat. No joins or
		    parts (there's a REST API call to get the current user list). The jtv user
		    sends PMs before every single chat message, to say whether the chat user
		    is a subscriber, what colour the user's name should be, and what channel
		    emote sets the user has enabled.
		3 - The same as 2, but the user "twitchnotify" also sends messages to the chat
		    for notifications, currently only for new subscribers.

		This may also have other effects... it is, after all, undocumented. Good luck!
		"""
		conn.send_raw("TWITCHCLIENT %d" % level)

	@utils.swallow_errors
	def on_server_event(self, conn):
		log.debug("Received event connection from server")
		buf = b""
		while b"\n" not in buf:
			buf += conn.recv(1024)
		data = json.loads(buf.decode())
		log.info("Command from server (%s): %s(%r)" % (data['user'], data['command'], data['param']))
		eventproc = self.server_events[data['command'].lower()]
		ret = eventproc(self, data['user'], data['param'])
		log.debug("Returning: %r" % ret)
		conn.send((json.dumps(ret) + "\n").encode())
		conn.close()

	@utils.swallow_errors
	def check_polls(self):
		from commands.strawpoll import check_polls
		check_polls(self, self.connection)

	@utils.swallow_errors
	def vote_respond(self):
		from commands.game import vote_respond
		if self.vote_update is not None:
			vote_respond(self, self.connection, *self.vote_update)

	@utils.swallow_errors
	def check_subscriber_list(self):
		sublist = twitch.get_subscribers(config['channel'])
		if not sublist:
			log.info("Failed to get subscriber list from Twitch")
			self.havesublist = False
			return
		# If this is the first time we've gotten the sub list then don't notify for all of them
		# as all of them will appear "new" even if we saw them on a previous run
		# Just add them to the "seen" list
		if not self.havesublist:
			log.debug("Got initial subscriber list from Twitch")
			self.lastsubs += [i[0].lower() for i in sublist]
			self.havesublist = True
			return

		for user, logo, eventtime in sublist:
			if user.lower() not in self.lastsubs:
				log.info("Found new subscriber via Twitch API: %s" % user)
				eventtime = dateutil.parser.parse(eventtime).timestamp()
				self.on_subscriber(self.connection, "#%s" % config['channel'], user, eventtime, logo)

bot = LRRBot()
