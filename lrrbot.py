#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Dependencies:
#   easy_install irc icalendar python-dateutil flask oursql

import os
import re
import time
import datetime
import random
import urllib.request, urllib.parse
import json
import logging
import socket
import irc.bot, irc.client
from config import config
import storage
import twitch
import utils
import googlecalendar

log = logging.getLogger('lrrbot')

class LRRBot(irc.bot.SingleServerIRCBot):
	GAME_CHECK_INTERVAL = 5*60 # Only check the current game at most once every five minutes

	def __init__(self):
		server = irc.bot.ServerSpec(
			host=config['hostname'],
			port=config['port'],
			password=config['password'],
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
		self.connection.irclibobj.execute_every(period=config['keepalivetime'], function=self.do_keepalive)

		# IRC event handlers
		self.ircobj.add_global_handler('welcome', self.on_connect)
		self.ircobj.add_global_handler('join', self.on_channel_join)
		self.ircobj.add_global_handler('pubmsg', self.on_message)
		self.ircobj.add_global_handler('privmsg', self.on_message)

		# Commands
		self.commands = {}
		self.re_botcommand = None
		self.command_groups = {}

		# Precompile regular expressions
		self.re_subscription = re.compile(r"^(.*) just subscribed!", re.IGNORECASE)

		# Set up bot state
		self.game_override = None
		self.vote_update = None

		self.spam_rules = [(re.compile(i['re']), i['message']) for i in storage.data['spam_rules']]
		self.spammers = {}

		self.seen_joins = False

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

	def start(self):
		self._connect()

		# Don't fall over if the server sends something that's not real UTF-8
		for conn in self.ircobj.connections:
			conn.buffer.errors = "replace"

		while True:
			self.ircobj.process_once(timeout=0.2)
			try:
				conn, addr = self.event_socket.accept()
			except OSError:
				pass
			else:
				conn.setblocking(True) # docs say this "may" be necessary :-/
				self.on_server_event(conn)

	def add_command(self, pattern, function):
		self.commands[re.compile(pattern.replace(" ", r"\s+"), re.IGNORECASE)] = function

	def command(self, pattern):
		def wrapper(function):
			self.add_command(pattern, function)
			return function
		return wrapper

	def compile(self):
		self.re_botcommand = r"^\s*%s\s*(?:" % re.escape(config["commandprefix"])
		self.re_botcommand += "|".join(map(lambda re: '(%s)' % re.pattern, self.commands))
		self.re_botcommand += r")\s*$"
		self.re_botcommand = re.compile(self.re_botcommand, re.IGNORECASE)

		i = 1
		for regex, function in self.commands.items():
			self.command_groups[i] = (function, i+regex.groups)
			i += 1+regex.groups

	def on_connect(self, conn, event):
		"""On connecting to the server, join our target channel"""
		log.info("Connected to server")
		conn.join("#%s" % config['channel'])

	def on_channel_join(self, conn, event):
		source = irc.client.NickMask(event.source)
		if (source.nick.lower() == config['username'].lower()):
			log.info("Channel %s joined" % event.target)
		else:
			if not self.seen_joins:
				self.seen_joins = True
				log.info("We have joins, we're on a good server")

	@utils.swallow_errors
	def do_keepalive(self):
		"""Send a ping to the server, to ensure our connection stays alive, or to detect when it drops out."""
		try:
			self.connection.ping("keep-alive")
		except irc.client.ServerNotConnectedError:
			pass

	@utils.swallow_errors
	def on_message(self, conn, event):
		if not hasattr(conn.privmsg, "is_throttled"):
			conn.privmsg = utils.twitch_throttle()(conn.privmsg)
		source = irc.client.NickMask(event.source)
		# If the message was sent to a channel, respond in the channel
		# If it was sent via PM, respond via PM		
		if irc.client.is_channel(event.target):
			respond_to = event.target
		else:
			respond_to = source.nick
			
		if self.vote_update is not None:
			self.vote_respond(self, conn, event, respond_to, self.vote_update)
		
		if (source.nick.lower() == config['notifyuser']):
			self.on_notification(conn, event, respond_to)
		elif self.check_spam(conn, event, event.arguments[0]):
			return
		else:
			command_match = self.re_botcommand.match(event.arguments[0])
			if command_match:
				command = command_match.group(command_match.lastindex)
				log.info("Command from %s: %s " % (source.nick, command))
				proc, end = self.command_groups[command_match.lastindex]
				params = command_match.groups()[command_match.lastindex:end]
				proc(self, conn, event, respond_to, *params)

	def on_notification(self, conn, event, respond_to):
		"""Handle notification messages from Twitch, sending the message up to the web"""
		log.info("Notification: %s" % event.arguments[0])
		notifyparams = {
			'apipass': config['apipass'],
			'message': event.arguments[0],
			'eventtime': time.time(),
		}
		if irc.client.is_channel(event.target):
			notifyparams['channel'] = event.target[1:]
		subscribe_match = self.re_subscription.match(event.arguments[0])
		if subscribe_match:
			notifyparams['subuser'] = subscribe_match.group(1)
			try:
				channel_info = twitch.getInfo(subscribe_match.group(1))
			except:
				pass
			else:
				if channel_info.get('logo'):
					notifyparams['avatar'] = channel_info['logo']
			# have to get this in a roundabout way as datetime.date.today doesn't take a timezone argument
			today = datetime.datetime.now(config['timezone']).date().toordinal()
			if today != storage.data.get("storm",{}).get("date"):
				storage.data["storm"] = {
					"date": today,
					"count": 0,
				}
			storage.data["storm"]["count"] += 1
			storage.save()
			conn.privmsg(respond_to, "lrrSPOT Thanks for subscribing, %s! (Today's storm count: %d)" % (notifyparams['subuser'], storage.data["storm"]["count"]))
		utils.api_request('notifications/newmessage', notifyparams, 'POST')

	def get_current_game(self):
		"""Returns the game currently being played, with caching to avoid hammering the Twitch server"""
		if self.game_override is not None:
			game_obj = {'_id': self.game_override, 'name': self.game_override, 'is_override': True}
			return storage.find_game(game_obj)
		else:
			return storage.find_game(self.get_current_game_real())

	@utils.throttle(GAME_CHECK_INTERVAL)
	def get_current_game_real(self):
		return twitch.get_game_playing()

	def is_mod(self, event):
		"""Check whether the source of the event has mod privileges for the bot, or for the channel"""
		source = irc.client.NickMask(event.source)
		if source.nick.lower() in config['mods']:
			return True
		elif irc.client.is_channel(event.target):
			channel = self.channels[event.target]
			return channel.is_oper(source.nick) or channel.is_owner(source.nick)
		else:
			return False

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
					conn.privmsg(event.target, "%s: Message deleted, auto-detected spam (%s). Please contact mrphlip or d3fr0st5 if this is incorrect." % (source.nick, desc))
				elif level <= 2:
					log.info("Second offence, timing out %s" % source.nick)
					conn.privmsg(event.target, ".timeout %s" % source.nick)
					conn.privmsg(event.target, "%s: Timeout for auto-detected spam (%s). Please contact mrphlip or d3fr0st5 if this is incorrect." % (source.nick, desc))
				else:
					log.info("Third offence, banning %s" % source.nick)
					conn.privmsg(event.target, ".ban %s" % source.nick)
					conn.privmsg(event.target, "%s: Banned persistent spam (%s). Please contact mrphlip or d3fr0st5 if this is incorrect." % (source.nick, desc))
				return True
		return False

	@utils.swallow_errors
	def on_server_event(self, conn):
		log.debug("Received event connection from server")
		buf = b""
		while b"\n" not in buf:
			buf += conn.recv(1024)
		data = json.loads(buf.decode())
		log.info("Command from server: %s(%r)" % (data['command'], data['param']))
		event_proc = getattr(self, 'on_server_event_%s' % data['command'].lower())
		ret = event_proc(data['param'])
		log.debug("Returning: %r" % ret)
		conn.send((json.dumps(ret) + "\n").encode())
		conn.close()

	def on_server_event_set_data(self, data):
		if not isinstance(data['key'], (list, tuple)):
			data['key'] = [data['key']]
		log.info("Setting storage %s to %r" % ('.'.join(data['key']), data['value']))
		# if key is, eg, ["a", "b", "c"]
		# then we want to effectively do:
		# storage.data["a"]["b"]["c"] = value
		# But in case one of those intermediate dicts doesn't exist:
		# storage.data.setdefault("a", {}).setdefault("b", {})["c"] = value
		node = storage.data
		for subkey in data['key'][:-1]:
			node = node.setdefault(subkey, {})
		node[data['key'][-1]] = data['value']
		storage.save()
bot = LRRBot()

def init_logging():
	logging.basicConfig(level=config['loglevel'], format="[%(asctime)s] %(levelname)s:%(name)s:%(message)s")
	if config['logfile'] is not None:
		fileHandler = logging.FileHandler(config['logfile'], 'a', 'utf-8')
		fileHandler.formatter = logging.root.handlers[0].formatter
		logging.root.addHandler(fileHandler)

if __name__ == '__main__':
	# Fix module names
	import sys
	sys.modules["lrrbot"] = sys.modules["__main__"]

	init_logging()

	import commands
	bot.compile()

	try:
		log.info("Bot startup")
		bot.start()
	except (KeyboardInterrupt, SystemExit):
		pass
	finally:
		log.info("Bot shutdown")
		logging.shutdown()

