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
import configparser

def main():
	init_logging()

	log.debug("Initialising connection")
	global GameINI
	GameINI = configparser.ConfigParser()
	GameINI.read("Game.ini")
	LRRBot().start()

class LRRBot(irc.bot.SingleServerIRCBot):
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
		self.connection.irclibobj.execute_every(period=config['keepalivetime'], function=self._do_keepalive)

		self.ircobj.add_global_handler('welcome', self._on_connect)
		self.ircobj.add_global_handler('pubmsg', self._on_message)
		self.ircobj.add_global_handler('privmsg', self._on_message)

		self.re_botcommand = re.compile(r"^\s*%s\s*(\w+)\b\s*(.*?)\s*$" % re.escape(config['commandprefix']))
		self.re_subscription = re.compile("^(.*) just subscribed!")

		global currentGame
		currentGame = 0

	def _on_connect(self, conn, event):
		"""On connecting to the server, join our target channel"""
		log.info("Connected to server")
		conn.join("#%s" % config['channel'])

	def _do_keepalive(self):
		"""Send a ping to the server, to ensure our connection stays alive, or to detect when it drops out."""
		try:
			self.connection.ping("keep-alive")
		except irc.client.ServerNotConnectedError:
			pass

	def _on_message(self, conn, event):
		source = irc.client.NickMask(event.source)
		if (source.nick.lower() == config['notifyuser']):
			self._on_notification(conn, event)
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
				try:
					command_proc = getattr(self, '_on_command_%s' % command.lower())
				except:
					self._on_fallback_command(conn, event, command, params, respond_to)
				else:
					command_proc(conn, event, params, respond_to)

	def _on_notification(self, conn, event):
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

	def _on_command_help(self, conn, event, params, respond_to):
		conn.privmsg(respond_to, "Help: http://lrrbot.mrphlip.com/")

	def _on_command_fliptable(self, conn, event, params, respond_to):
		conn.privmsg(respond_to, random.choose([
			"(╯°□°）╯︵ ┻━┻",
			"(╯°□°）╯︵ ┻━┻", # Make the classic a bit more likely
			"(╯°Д°）╯︵ ┻━┻",
			"(ﾉಠ益ಠ）ﾉ 彡ㅑ",
		]))

	def _on_command_fixtable(self, conn, event, params, respond_to):
		conn.privmsg(respond_to, "┳━┳ ノ(º_ºノ)")

	def _on_command_xcam(self, conn, event, params, respond_to):
		conn.privmsg(respond_to, "The XCam list is http://bit.ly/CamXCOM")

	def _on_command_game(self, conn, event, params, respond_to):
		#This whole thing will be obsolete once twitch api get integrated... hopefully
		game = GameINI[str(currentGame)]
		conn.privmsg(respond_to, "Current game selected is: %s" % (game['Title']))

	def _on_command_death(self, conn, event, params, respond_to):
		#got to add timer so that the command can only be called once every ~15 seconds
		game = GameINI[str(currentGame)]
		game['Deaths'] = str(int(game['Deaths']) + 1) #Does this seem redundant? Also not writing to file properly will fix tomorrow
		conn.privmsg(respond_to, "Current deathcount for %s" % (game['Deaths']))

	def _on_fallback_command(self, conn, event, command, params, respond_to):
		"""Handle dynamic commands that can't have their own named procedure"""
		# None yet... eventually, all the "stats" commands (death, flunge, etc) will be here
		pass

def init_logging():
	# TODO: something more sophisticated
	logging.basicConfig(level=config['loglevel'])
	global log
	log = logging.getLogger('lrrbot')

if __name__ == '__main__':
	main()
