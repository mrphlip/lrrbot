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

log = logging.getLogger('lrrbot')

def main():
	init_logging()

	try:
		log.info("Bot startup")
		LRRBot().start()
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
		self.re_botcommand = re.compile(r"^\s*%s\s*(\w+)\b\s*(.*?)\s*$" % re.escape(config['commandprefix']), re.IGNORECASE)
		self.re_subscription = re.compile(r"^(.*) just subscribed!", re.IGNORECASE)
		self.re_game_display = re.compile(r"\s*display\b\s*(.*?)\s*$", re.IGNORECASE)
		self.re_game_override = re.compile(r"\s*override\b\s*(.*?)\s*$", re.IGNORECASE)
		self.re_game_refresh = re.compile(r"\s*refresh\b\s*$", re.IGNORECASE)
		self.re_game_completed = re.compile(r"\s*completed\b\s*$", re.IGNORECASE)
		self.re_game_vote = re.compile(r"\s*(good|bad)\b\s*$", re.IGNORECASE)
		self.re_addremove = re.compile(r"\s*(add|remove|set)\s*(\d*)\d*$", re.IGNORECASE)

		# Set up bot state
		self.game_override = None
		self.storm_count = 0
		self.storm_count_date = None
		self.voteUpdate = False

		self.spam_rules = [(re.compile(i['re']), i['message']) for i in storage.data['spam_rules']]
		self.spammers = {}

		self.seen_joins = False

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
			
		if self.voteUpdate:
			game = self.get_current_game()
			self.subcommand_game_vote_respond(conn, event, respond_to, game)
		
		if (source.nick.lower() == config['notifyuser']):
			self.on_notification(conn, event, respond_to)
		elif self.check_spam(conn, event, event.arguments[0]):
			return
		else:
			command_match = self.re_botcommand.match(event.arguments[0])
			if command_match:
				command, params = command_match.groups()
				log.info("Command from %s: %s %s" % (source.nick, command, params))

				# Find the command procedure for this command
				command_proc = getattr(self, 'on_command_%s' % command.lower(), None)
				if command_proc:
					command_proc(conn, event, params, respond_to)
				else:
					self.on_fallback_command(conn, event, command, params, respond_to)

	def on_notification(self, conn, event, respond_to):
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
			# have to get this in a roundabout way as datetime.date.today doesn't take a timezone argument
			today = datetime.datetime.now(config['timezone']).date()
			if today != self.storm_count_date:
				self.storm_count_date = today
				self.storm_count = 0
			self.storm_count += 1
			conn.privmsg(respond_to, "lrrSPOT Thanks for subscribing, %s! (Today's storm count: %d)" % (notifyparams['subuser'], self.storm_count))
		utils.api_request('notifications', notifyparams, 'POST')

	@utils.mod_only
	def on_command_test(self, conn, event, params, respond_to):
		conn.privmsg(respond_to, "Test")
	
	def on_command_game(self, conn, event, params, respond_to):
		params = params.strip()
		if params == "": # "!game" - print current game
			self.subcommand_game_current(conn, event, respond_to)
			return

		matches = self.re_game_display.match(params)
		if matches: # "!game display xyz" - change game display
			self.subcommand_game_display(conn, event, respond_to, matches.group(1))
			return

		matches = self.re_game_override.match(params)
		if matches: # "!game override xyz" - set game override
			self.subcommand_game_override(conn, event, respond_to, matches.group(1))
			return

		matches = self.re_game_refresh.match(params)
		if matches:
			self.subcommand_game_refresh(conn, event, respond_to)
			return
			
		matches = self.re_game_completed.match(params)
		if matches:
			self.subcommand_game_completed(conn, event, respond_to)
			return

		matches = self.re_game_vote.match(params)
		if matches:
			self.subcommand_game_vote(conn, event, respond_to, matches.group(1).lower() == "good")
			return

	@utils.throttle()
	def subcommand_game_current(self, conn, event, respond_to):
		game = self.get_current_game()
		if game is None:
			message = "Not currently playing any game"
		else:
			message = "Currently playing: %s" % self.game_name(game)
			if game.get('votes'):
				good = sum(game["votes"].values())
				message += " (rating %.0f%%)" % (100*good/len(game["votes"]))
		if self.game_override is not None:
			message += " (overridden)"
		conn.privmsg(respond_to, message)

	# No throttle here
	def subcommand_game_vote(self, conn, event, respond_to, vote):
		game = self.get_current_game()
		if game is None:
			conn.privmsg(respond_to, "Not currently playing any game")
			return
		nick = irc.client.NickMask(event.source).nick
		game.setdefault("votes", {})
		game["votes"][nick.lower()] = vote
		storage.save()
		self.voteUpdate = True
		self.subcommand_game_vote_respond(conn, event, respond_to, game)

	@utils.throttle(60)
	def subcommand_game_vote_respond(self, conn, event, respond_to, game):
		good = sum(game["votes"].values())
		count = len(game["votes"])
		conn.privmsg(respond_to, "Rating for %s is now %.0f%% (%d/%d)" % (self.game_name(game), 100*good/count, good, count))
		self.voteUpdate = False

	@utils.mod_only
	def subcommand_game_display(self, conn, event, respond_to, name):
		game = self.get_current_game()
		if game is None:
			conn.privmsg(respond_to, "Not currently playing any game")
			return
		game['display'] = name
		storage.save()
		conn.privmsg(respond_to, "OK, I'll start calling %s \"%s\"" % (game['name'], game['display']))

	@utils.mod_only
	def subcommand_game_override(self, conn, event, respond_to, param):
		if param == "" or param.lower() == "off":
			self.game_override = None
			operation = "disabled"
		else:
			self.game_override = param
			operation = "enabled"
		self.get_current_game_real.reset_throttle()
		self.subcommand_game_current.reset_throttle()
		game = self.get_current_game()
		if game is None:
			conn.privmsg(respond_to, "Override %s. Not currently playing any game" % operation)
		else:
			conn.privmsg(respond_to, "Override %s. Currently playing: %s" % (operation, self.game_name(game)))

	@utils.mod_only
	def subcommand_game_refresh(self, conn, event, respond_to):
		self.get_current_game_real.reset_throttle()
		self.subcommand_game_current.reset_throttle()
		self.subcommand_game_current(conn, event, respond_to)
		
	@utils.mod_only
	@utils.throttle(30, notify=True)
	def subcommand_game_completed(self, conn, event, respond_to):
		game = self.get_current_game()
		if game is None:
			conn.privmsg(respond_to, "Not currently playing any game")
			return
		game.setdefault('stats', {}).setdefault("completed", 0)
		game['stats']["completed"] += 1
		storage.save()
		conn.privmsg(respond_to, "%s added to the completed list" % (self.game_name(game)))

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
				self.subcommand_stat_edit(conn, event, respond_to, command, matches.group(1), matches.group(2))
				return

		if command[-5:] == "count" and command[:-5] in storage.data['stats']: # eg "!deathcount"
			self.subcommand_stat_print(conn, event, respond_to, command[:-5])
			return

		if command[:5] == "total" and command[5:] in storage.data['stats']: # eg "!totaldeath"
			self.subcommand_stat_printtotal(conn, event, respond_to, command[5:])
			return

		if command in storage.data['responses']:
			self.subcommand_static_response(conn, event, respond_to, command)
			return

	# Longer throttle for this command, as I expect lots of people to be
	# hammering it at the same time plus or minus stream lag
	@utils.throttle(30, notify=True, params=[4])
	def subcommand_stat_increment(self, conn, event, respond_to, stat):
		# Special case for this stat, should be handled through the "!game completed" code-path
		if stat == "completed":
			self.subcommand_game_completed(conn, event, respond_to)
			return
		game = self.get_current_game()
		if game is None:
			conn.privmsg(respond_to, "Not currently playing any game")
			return
		game.setdefault('stats', {}).setdefault(stat, 0)
		game['stats'][stat] += 1
		storage.save()
		self.print_stat(conn, respond_to, stat, game, with_emote=True)

	@utils.mod_only
	def subcommand_stat_edit(self, conn, event, respond_to, stat, operation, value):
		# Let "completed" go through here like any other stat, so corrections can be made if necessary
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
		if game is None:
			conn.privmsg(respond_to, "Not currently playing any game")
			return
		game.setdefault('stats', {}).setdefault(stat, 0)
		if operation == "add":
			game['stats'][stat] += value
		elif operation == "remove":
			game['stats'][stat] -= value
		elif operation == "set":
			game['stats'][stat] = value
		storage.save()
		self.print_stat(conn, respond_to, stat, game)

	@utils.throttle(params=[4])
	def subcommand_stat_print(self, conn, event, respond_to, stat):
		self.print_stat(conn, respond_to, stat)

	@utils.throttle(params=[4])
	def subcommand_stat_printtotal(self, conn, event, respond_to, stat):
		count = sum(game.get('stats', {}).get(stat, 0) for game in storage.data['games'].values())
		display = storage.data['stats'][stat]
		display = display.get('singular', stat) if count == 1 else display.get('plural', stat + "s")
		conn.privmsg(respond_to, "%d total %s" % (count, display))

	@utils.throttle(5, params=[4])
	def subcommand_static_response(self, conn, event, respond_to, command):
		response = storage.data['responses'][command]
		if isinstance(response, (tuple, list)):
			response = random.choice(response)
		conn.privmsg(respond_to, response)

	@utils.throttle()
	def on_command_next(self, conn, event, params, respond_to):
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

	def print_stat(self, conn, respond_to, stat, game=None, with_emote=False):
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

def init_logging():
	logging.basicConfig(level=config['loglevel'], format="[%(asctime)s] %(levelname)s:%(name)s:%(message)s")
	if config['logfile'] is not None:
		fileHandler = logging.FileHandler(config['logfile'], 'a', 'utf-8')
		fileHandler.formatter = logging.root.handlers[0].formatter
		logging.root.addHandler(fileHandler)

if __name__ == '__main__':
	main()
