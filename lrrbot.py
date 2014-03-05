#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Dependencies:
#   easy_install irc icalendar python-dateutil

import re
import time
import datetime
import random
import urllib.request, urllib.parse
import json
import logging
import irc.bot, irc.client
from config import config
import storage
import twitch
import utils
import googlecalendar
import http.server
import select
from http_handler import HTTPHandler
import types
from functools import partial

log = logging.getLogger('lrrbot')

def main():
	init_logging()

	try:
		log.info("Bot startup")
		bot = LRRBot()
		bot._connect()
		httpd = http.server.HTTPServer(("localhost", 8000), HTTPHandler)
		httpd.bot = bot
		not_none = lambda x: x is not None
		while True:
			irc = list(filter(not_none,
				map(lambda x: x.socket,
					filter(not_none, bot.ircobj.connections))))
			r, w, x = select.select(irc+[httpd], [], [], 0.2)
			if httpd in r:	
				httpd.handle_request()
				del r[r.index(httpd)]
			bot.ircobj.process_data(r)
			bot.ircobj.process_timeout()
	except (KeyboardInterrupt, SystemExit):
		pass
	finally:
		log.info("Bot shutdown")
		logging.shutdown()

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

		# Precompile regular expressions
		self.re_subscription = re.compile(r"^(.*) just subscribed!", re.IGNORECASE)

		# Set up bot state
		self.game_override = None
		self.storm_count = 0
		self.storm_count_date = None

		# Generate !help-like commands
		for command in storage.data["help"]:
			f = utils.throttle()(
				lambda conn, event, params, respond_to, command=command: \
					conn.privmsg(respond_to, storage.data["help"][command]))
			f.__doc__ = "Post '{}'".format(storage.data["help"][command])
			setattr(self, "on_command_{}".format(command), f)

		parse_int = lambda params: int(params[0]) if len(params) > 0 and params[0].isdigit() else 1

		# Generate commands for statistics
		stats = storage.data["stats"]
		for stat in storage.data["stats"]:
			plural = stats[stat]["plural"]
			f = utils.throttle(30, notify=True)(partial(self.stat_modify, stat=stat, n=1))
			f.__doc__ = "Increments the number of {}".format(plural)
			setattr(self, "on_command_{}".format(stat), f)
			
			f = types.MethodType(utils.mod_only(
				lambda self, conn, event, params, respond_to, stat=stat: \
					self.stat_modify(conn, event, params, respond_to, stat, parse_int(params))),
				self)
			f.__func__.__doc__ = "Adds # to the number of {}".format(plural)
			setattr(self, "on_command_{}_add".format(stat), f)
			
			f = types.MethodType(utils.mod_only(
				lambda self, conn, event, params, respond_to, stat=stat: \
					self.stat_modify(conn, event, params, respond_to, stat, -parse_int(params))), self)
			f.__func__.__doc__ = "Removes # from the number of {}".format(plural)
			setattr(self, "on_command_{}_remove".format(stat), f)
			
			c = "{}{} set".format(config["commandprefix"], stat)
			f = types.MethodType(utils.mod_only(
				lambda self, conn, event, params, respond_to, stat=stat: \
					self.stat_set(conn, event, respond_to, stat, int(params[0])) \
						if len(params[0]) > 0 and params[0].isdigit() \
						else conn.privmsg(respond_to,
							"'{}' needs an integer parameter".format(c))), self)
			f.__func__.__doc__ = "Resets the number of {} to the specified value for the current game."\
				.format(plural)
			setattr(self, "on_command_{}_set".format(stat), f)
			
			f = utils.throttle()(partial(self.print_stat, stat=stat))
			f.__doc__ = "Post the number of {} for the current game.".format(plural)
			setattr(self, "on_command_{}count".format(stat), f)
			
			f = utils.throttle()(partial(self.print_stat_total, stat=stat))
			f.__doc__ = "Post the number of {} for every game.".format(plural)
			setattr(self, "on_command_total{}".format(stat), f)

	def on_connect(self, conn, event):
		"""On connecting to the server, join our target channel"""
		log.info("Connected to server")
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

	@utils.swallow_errors
	def on_message(self, conn, event):
		if not hasattr(conn.privmsg, "__wrapped__"):
			conn.privmsg = utils.twitch_throttle()(conn.privmsg)
		source = irc.client.NickMask(event.source)
		# If the message was sent to a channel, respond in the channel
		# If it was sent via PM, respond via PM
		if irc.client.is_channel(event.target):
			respond_to = event.target
		else:
			respond_to = source.nick

		if (source.nick.lower() == config['notifyuser']):
			self.on_notification(conn, event, respond_to)
		else:
			command = event.arguments[0].split()
			if not command[0].startswith(config["commandprefix"]):
				return
			command[0] = command[0][len(config["commandprefix"]):]
			log.info("Command from {}: {}".format(source.nick, command))

			# Find the command procedure for this command
			for i in range(len(command), 0, -1):
				name = "on_command_"+"_".join(command[:i]).lower()
				proc = getattr(self, name, None)
				if proc:
					log.info("Calling {}".format(name))
					proc(conn, event, command[i:], respond_to)
					break

	def on_notification(self, conn, event, respond_to):
		"""Handle notification messages from Twitch, sending the message up to the web"""
		log.info("Notification: %s" % event.arguments[0])
		notifyparams = {
			'eventtime': time.time(),
		}
		if irc.client.is_channel(event.target):
			notifyparams['channel'] = event.target[1:]
		subscribe_match = self.re_subscription.match(event.arguments[0])
		if subscribe_match:
			notifyparams['subuser'] = subscribe_match.group(1)
			try:
				channel_info = twitch.get_info(subscribe_match.group(1))
			except:
				pass
			else:
				if channel_info.get('logo'):
					notifyparams['avatar'] = channel_info['logo']
			# have to get this in a roundabout way as datetime.date.today doesn't take a timezone argument
			today = datetime.datetime.now(config['timezone']).date()
			if today != self.storm_count_date:
				self.storm_count_date = today
				self.storm_count = 0
			self.storm_count += 1
			conn.privmsg(respond_to, "lrrSPOT Thanks for subscribing, %s! (Today's storm count: %d)" % (notifyparams['subuser'], self.storm_count))
		else:
			notifyparams["message"] = event.arguments[0]
		storage.data.setdefault("notifications", [])
		storage.data["notifications"] += [notifyparams]
		storage.save()

	@utils.throttle()
	def on_command_help(self, conn, event, params, respond_to):
		"""Post a link to the command list"""
		conn.privmsg(respond_to, "Help: %s" % config['siteurl'])
	on_command_halp = on_command_help
	on_command_commands = on_command_help
	
	@utils.mod_only
	def on_command_test(self, conn, event, params, respond_to):
		"Post 'Test'"
		conn.privmsg(respond_to, "Test")
	
	@utils.throttle()
	def on_command_link(self, conn, event, params, respond_to):
		"""Post a link to <a href="http://loadingreadyrun.com/">loadingreadyrun.com</a>"""
		conn.privmsg(respond_to, "Visit LoadingReadyRun: http://loadingreadyrun.com/")
	on_command_lrr = on_command_link

	@utils.throttle(5) # throttle can be a little shorter on this one
	def on_command_fliptable(self, conn, event, params, respond_to):
		"""(╯°□°）╯︵ ┻━┻"""
		conn.privmsg(respond_to, random.choice([
			"(╯°□°）╯︵ ┻━┻",
			"(╯°□°）╯︵ ┻━┻", # Make the classic a bit more likely
			"(╯°Д°）╯︵ ┻━┻",
			"(ﾉಠ益ಠ）ﾉ 彡 ┻━┻",
		]))
	on_command_tableflip = on_command_fliptable

	@utils.throttle(5)
	def on_command_fixtable(self, conn, event, params, respond_to):
		"""┳━┳ ノ(º_ºノ)"""
		conn.privmsg(respond_to, "┳━┳ ノ(º_ºノ)")
		
	@utils.throttle(5)
	def on_command_picnic(self, conn, event, params, respond_to):
		"""(╯°Д°）╯︵ɥɔʇıʍʇ"""
		conn.privmsg(respond_to, "(╯°Д°）╯︵ɥɔʇıʍʇ")

	@utils.throttle()
	def on_command_drink(self, conn, event, params, respond_to):
		"""Post a link to the <a href="http://bit.ly/YRRLRLager">drinking game rules</a>"""
		conn.privmsg(respond_to, "The drinking game is: http://bit.ly/YRRLRLager")

	@utils.throttle(5)
	def on_command_powah(self, conn, event, params, respond_to):
		"""ᕦ(° Д°)ᕤ STOPPIN POWAH"""
		conn.privmsg(respond_to, "ᕦ(° Д°)ᕤ STOPPIN POWAH")
	on_command_stoppin = on_command_powah
	on_command_stopping = on_command_powah
	on_command_stoppinpowah = on_command_powah
	on_command_stoppingpowah = on_command_powah

	@utils.throttle()
	def on_command_xcam(self, conn, event, params, respond_to):
		"""Post a link to Cam's <a href="http://bit.ly/CamXCOM">subs' soldiers spreadsheet</a>"""
		conn.privmsg(respond_to, "The XCam list is http://bit.ly/CamXCOM")
	on_command_xcom = on_command_xcam

	@utils.throttle()
	def on_command_game_current(self, conn, event, params, respond_to):
		"""Post the game currently being played"""
		game = self.get_current_game()
		if game is None:
			message = "Not currently playing any game"
		else:
			message = "Currently playing: %s" % self.game_name(game)
		if self.game_override is not None:
			message += " (overridden)"
		conn.privmsg(respond_to, message)
	on_command_game = on_command_game_current

	@utils.mod_only
	def on_command_game_display(self, conn, event, params, respond_to):
		"""
		Change the display name of the current game. (E.g. <code>!game display Resident Evil:
		Man Fellating Giraffe</code>)
		"""
		game = self.get_current_game()
		if game is None:
			conn.privmsg(respond_to, "Not currently playing any game")
			return
		new_name = " ".join(params)
		if game["name"] == new_name:
			del game['display']
		else:
			game['display'] = new_name
		storage.save()
		conn.privmsg(respond_to, "OK, I'll start calling %s \"%s\"" % (game['name'], new_name))

	@utils.mod_only
	def on_command_game_override(self, conn, event, params, respond_to):
		"""Override what game is being played or <code>off</code> to disable the override."""
		if len(params) == 0 or (len(params) == 1 and params[0].lower() == "off"):
			self.game_override = None
			operation = "disabled"
		else:
			self.game_override = " ".join(params)
			operation = "enabled"
		self.get_current_game_real.reset_throttle()
		self.subcommand_game_current.reset_throttle()
		game = self.get_current_game()
		if game is None:
			conn.privmsg(respond_to, "Override %s. Not currently playing any game" % operation)
		else:
			conn.privmsg(respond_to, "Override %s. Currently playing: %s" % (operation, self.game_name(game)))

	@utils.mod_only
	def on_command_game_refresh(self, conn, event, params, respond_to):
		"""Force a refresh of the current Twitch game (normally this is updated at most once every 15 minutes)"""
		self.get_current_game_real.reset_throttle()
		self.subcommand_game_current.reset_throttle()
		self.subcommand_game_current(conn, event, respond_to)
		
	@utils.mod_only
	def on_command_game_completed(self, conn, event, params, respond_to):
		"""Set current game to be completed."""
		game = self.get_current_game()
		if game is None:
			conn.privmsg(respond_to, "Not currently playing any game")
			return
		game.setdefault('stats', {}).setdefault("completed", 0)
		game['stats']["completed"] = 1
		storage.save()
		conn.privmsg(respond_to, "%s added to the completed list" % (self.game_name(game)))

	def stat_modify(self, conn, event, params, respond_to, stat=None, n=0):
		game = self.get_current_game()
		if game is None:
			conn.privmsg(respond_to, "Not currently playing any game")
			return
		game.setdefault('stats', {}).setdefault(stat, 0)
		game['stats'][stat] += n
		storage.save()
		self.print_stat(conn, event, [], respond_to, stat, game, with_emote=(n == 1))

	def stat_set(self, conn, event, respond_to, stat, n):
		game = self.get_current_game()
		if game is None:
			conn.privmsg(respond_to, "Not currently playing any game")
			return
		game.setdefault('stats', {}).setdefault(stat, 0)
		game['stats'][stat] = n
		storage.save()
		self.print_stat(conn, event, [], respond_to, stat, game)

	def print_stat_total(self, conn, event, params, respond_to, stat):
		count = sum(game.get('stats', {}).get(stat, 0) for game in storage.data['games'].values())
		display = storage.data['stats'][stat]
		display = display.get('singular', stat) if count == 1 else display.get('plural', stat + "s")
		conn.privmsg(respond_to, "%d total %s" % (count, display))

	@utils.throttle()
	def on_command_next(self, conn, event, params, respond_to):
		"""Gets the next scheduled stream from the <a href="https://www.google.com/calendar/embed?src=loadingreadyrun.com_72jmf1fn564cbbr84l048pv1go@group.calendar.google.com&ctz=America/Vancouver">calendar</a>"""
		event_name, event_time, event_wait = googlecalendar.get_next_event()
		if event_time:
			nice_time = event_time.astimezone(config['timezone']).strftime("%a %I:%M %p %Z")
			if event_wait < 0:
				nice_duration = utils.nice_duration(-event_wait, 1) + " ago"
			else:
				nice_duration = utils.nice_duration(event_wait, 1) + " from now"
			conn.privmsg(respond_to, "Next scheduled stream: %s at %s (%s)" % (event_name, nice_time, nice_duration))
		else:
			conn.privmsg(respond_to, "There don't seem to be any upcoming scheduled streams")
	on_command_schedule = on_command_next
	on_command_sched = on_command_next
	on_command_nextstream = on_command_next

	@utils.throttle(60)
	def upload_stats(self):
		url = "stats?%s" % urllib.parse.urlencode({'apipass': config['apipass']})
		utils.api_request(url, json.dumps(storage.data), 'PUT')

	@utils.throttle()
	def on_command_stats(self, conn, event, params, respond_to):
		"""Update the data on the <a href="http://lrrbot.mrphlip.com/stats">statistics page</a>"""
		self.upload_stats()
		conn.privmsg(respond_to, "Stats: %s" % config['siteurl'] + 'stats')

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

	def game_name(self, game=None):
		if game is None:
			game = self.get_current_game()
			if game is None:
				return "Not currently playing any game"
		return game.get('display', game['name'])

	def print_stat(self, conn, event, params, respond_to, stat, game=None, with_emote=False):
		if game is None:
			game = self.get_current_game()
			if game is None:
				conn.privmsg(respond_to, "Not currently playing any game")
				return
		count = game.get('stats', {}).get(stat, 0)
		countT = sum(game.get('stats', {}).get(stat, 0) for game in storage.data['games'].values())
		stat_details = storage.data['stats'][stat]
		display = stat_details.get('singular', stat) if count == 1 else stat_details.get('plural', stat + "s")
		if with_emote and stat_details.get('emote'):
			emote = stat_details['emote'] + " "
		else:
			emote = ""
		conn.privmsg(respond_to, "%s%d %s for %s" % (emote, count, display, self.game_name(game)))
		if countT == 1000:
			conn.privmsg(respond_to, "Watch and pray for another %d %s!" % (countT, display))
	
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
	logging.basicConfig(level=config['loglevel'], format="[%(asctime)s] %(levelname)s:%(name)s:%(message)s")
	if config['logfile'] is not None:
		fileHandler = logging.FileHandler(config['logfile'], 'a', 'utf-8')
		fileHandler.formatter = logging.root.handlers[0].formatter
		logging.root.addHandler(fileHandler)

if __name__ == '__main__':
	main()
