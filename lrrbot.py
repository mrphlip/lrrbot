#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Dependencies:
#   easy_install irc

import re
import time
import random
import urllib.request, urllib.parse
import json
import logging
import irc.bot, irc.client
from config import config
import storage
import twitch
import utils

def main():
	init_logging()

	log.debug("Initialising connection")
	LRRBot().start()

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
		self.ircobj.add_global_handler('pubmsg', self.on_message)
		self.ircobj.add_global_handler('privmsg', self.on_message)

		# Precompile regular expressions
		self.re_botcommand = re.compile(r"^\s*%s\s*(\w+)\b\s*(.*?)\s*$" % re.escape(config['commandprefix']), re.IGNORECASE)
		self.re_subscription = re.compile(r"^(.*) just subscribed!", re.IGNORECASE)
		self.re_game_override = re.compile(r"\s*override\b\s*(.*?)\s*$", re.IGNORECASE)
		self.re_addremove = re.compile(r"\s*(add|remove|set)\s*(\d*)\d*$", re.IGNORECASE)

		# Set up bot state
		self.game_override = None
		self.game_cache = None
		self.game_last_check = None

	def on_connect(self, conn, event):
		"""On connecting to the server, join our target channel"""
		log.info("Connected to server")
		conn.join("#%s" % config['channel'])

	def do_keepalive(self):
		"""Send a ping to the server, to ensure our connection stays alive, or to detect when it drops out."""
		try:
			self.connection.ping("keep-alive")
		except irc.client.ServerNotConnectedError:
			pass

	def on_message(self, conn, event):
		source = irc.client.NickMask(event.source)
		if (source.nick.lower() == config['notifyuser']):
			self.on_notification(conn, event)
		else:
			command_match = self.re_botcommand.match(event.arguments[0])
			if command_match:
				command, params = command_match.groups()

				# If the message was sent to a channel, respond in the channel
				# If it was sent via PM, respond via PM
				if irc.client.is_channel(event.target):
					respond_to = event.target
				else:
					respond_to = source.nick

				# Find the command procedure for this command
				command_proc = getattr(self, 'on_command_%s' % command.lower(), None)
				if command_proc:
					command_proc(conn, event, params, respond_to)
				else:
					self.on_fallback_command(conn, event, command, params, respond_to)

	def on_notification(self, conn, event):
		"""Handle notification messages from Twitch, sending the message up to the web"""
		log.info("Notification: %s" % event.arguments[0])
		notifyparams = {
			'mode': 'newmessage',
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
		# Send the information to the server
		try:
			res = urllib.request.urlopen(
				config['siteurl'] + "notifications",
				urllib.parse.urlencode(notifyparams).encode('ascii'),
			).read().decode("utf-8")
		except:
			log.exception("Error sending notification to server")
		else:
			try:
				res = json.loads(res)
			except:
				log.exception("Error parsing notification server response: " + res)
			else:
				if 'success' not in res:
					log.error("Error sending notification to server")

	@utils.throttle()
	def on_command_help(self, conn, event, params, respond_to):
		conn.privmsg(respond_to, "Help: %s" % config['siteurl'])
	on_command_commands = on_command_help

	@utils.throttle()
	def on_command_link(self, conn, event, params, respond_to):
		conn.privmsg(respond_to, "Visit LoadingReadyRun: http://loadingreadyrun.com/")

	@utils.throttle(5) # throttle can be a little shorter on this one
	def on_command_fliptable(self, conn, event, params, respond_to):
		conn.privmsg(respond_to, random.choice([
			"(╯°□°）╯︵ ┻━┻",
			"(╯°□°）╯︵ ┻━┻", # Make the classic a bit more likely
			"(╯°Д°）╯︵ ┻━┻",
			"(ﾉಠ益ಠ）ﾉ 彡 ┻━┻",
		]))
	on_command_tableflip = on_command_fliptable

	@utils.throttle(5)
	def on_command_fixtable(self, conn, event, params, respond_to):
		conn.privmsg(respond_to, "┳━┳ ノ(º_ºノ)")

	@utils.throttle()
	def on_command_xcam(self, conn, event, params, respond_to):
		conn.privmsg(respond_to, "The XCam list is http://bit.ly/CamXCOM")

	def on_command_game(self, conn, event, params, respond_to):
		params = params.strip()
		if params == "": # "!game" - print current game
			self.subcommand_game_current(conn, event, respond_to)
			return

		matches = self.re_game_override.match(params)
		if matches: # "!game override xyz" - set game override
			self.subcommand_game_override(conn, event, respond_to, matches.group(1))
			return

	@utils.throttle()
	def subcommand_game_current(self, conn, event, respond_to):
		game = self.get_current_game()
		message = "Currently playing: %s" % self.game_name(game)
		if self.game_override is not None:
			message += " (overridden)"
		conn.privmsg(respond_to, message)

	@utils.mod_only
	def subcommand_game_override(self, conn, event, respond_to, param):
		if param == "" or param.lower() == "off":
			self.game_override = None
			operation = "disabled"
		else:
			self.game_override = param
			operation = "enabled"
		game = self.get_current_game()
		conn.privmsg(respond_to, "Override %s. Currently playing: %s" % (operation, self.game_name(game)))

	def on_fallback_command(self, conn, event, command, params, respond_to):
		"""Handle dynamic commands that can't have their own named procedure"""
		# General processing for all stat-management commands
		if command in storage.data['stats']:
			params = params.strip()
			if params == "": # eg "!death" - increment the counter
				self.subcommand_stat_increment(conn, event, respond_to, command)
				return
			matches = self.re_addremove.match(params)
			if matches: # eg "!death remove", "!death add 5" or "!death set 0"
				subcommand_stat_edit(conn, event, respond_to, command, matches.group(1), matches.group(2))
				return

		if command[-5:] == "count" and command[:-5] in storage.data['stats']: # eg "!deathcount"
			self.subcommand_stat_print(conn, event, respond_to, command[:-5])
			return

		if command[:5] == "total" and command[5:] in storage.data['stats']: # eg "!totaldeath"
			self.subcommand_stat_printtotal(conn, event, respond_to, command[5:])
			return

	# Longer throttle for this command, as I expect lots of people to be
	# hammering it at the same time plus or minus stream lag
	@utils.throttle(30)
	def subcommand_stat_increment(self, conn, event, respond_to, stat):
		game = self.get_current_game()
		game.setdefault('stats', {}).setdefault(stat, 0)
		game['stats'][stat] += 1
		storage.save()
		self.print_stat(conn, respond_to, stat, game)

	@utils.mod_only
	def subcommand_stat_edit(self, conn, event, respond_to, stat, operation, value):
		operation = operation.lower()
		if value:
			try:
				value = int(value)
			except ValueError:
				conn.privmsg(respond_to, "\"%s\" is not a number" % value)
				return
		else:
			if operation == "set":
				conn.privmsg(respond_to, "\"set\" needs a value")
				return
			# default to 1 for add and remove
			value = 1
		game = self.get_current_game()
		game.setdefault('stats', {}).setdefault(stat, 0)
		if operation == "add":
			game['stats'][stat] += value
		elif operation == "remove":
			game['stats'][stat] -= value
		elif operation == "set":
			game['stats'][stat] = value
		storage.save()
		self.print_stat(conn, respond_to, stat, game)

	@utils.throttle()
	def subcommand_stat_print(self, conn, event, respond_to, stat):
		self.print_stat(conn, respond_to, stat)

	@utils.throttle()
	def subcommand_stat_printtotal(self, conn, event, respond_to, stat):
		count = sum(game.get('stats', {}).get(stat, 0) for game in storage.data['games'].values())
		display = storage.data['stats'][stat]
		display = display.get('singular', stat) if count == 1 else display.get('plural', stat + "s")
		conn.privmsg(respond_to, "%d total %s" % (count, display))

	def get_current_game(self):
		"""Returns the game currently being played, with caching to avoid hammering the Twitch server"""
		if self.game_override is not None:
			game_obj = {'_id': self.game_override, 'name': self.game_override, 'is_override': True}
			return storage.find_game(game_obj)
		if self.game_cache is not None and time.time() - self.game_last_check < self.GAME_CHECK_INTERVAL:
			return storage.find_game(self.game_cache)
		self.game_cache = twitch.get_game_playing()
		self.game_last_check = time.time()
		return storage.find_game(self.game_cache)

	def game_name(self, game=None):
		if game is None:
			game = self.get_current_game()
		return game.get('display', game['name'])

	def print_stat(self, conn, respond_to, stat, game=None):
		if game is None:
			game = self.get_current_game()
		count = game.get('stats', {}).get(stat, 0)
		display = storage.data['stats'][stat]
		display = display.get('singular', stat) if count == 1 else display.get('plural', stat + "s")
		conn.privmsg(respond_to, "%d %s for %s" % (count, display, self.game_name(game)))

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

def init_logging():
	# TODO: something more sophisticated
	logging.basicConfig(level=config['loglevel'])
	global log
	log = logging.getLogger('lrrbot')

if __name__ == '__main__':
	main()
