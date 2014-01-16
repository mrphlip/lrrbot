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
		)

		self.ircobj.add_global_handler('welcome', self._on_connect)
		self.ircobj.add_global_handler('pubmsg', self._on_message)
		self.ircobj.add_global_handler('privmsg', self._on_message)

		self.re_botcommand = re.compile(r"^\s*%s\s*(\w+)\b\s*(.*?)\s*$" % re.escape(config['commandprefix']))
		self.re_subscription = re.compile("^(.*) just subscribed!")

		global currentGame
		currentGame = 0

	def _on_connect(self, conn, event):
		conn.join("#%s" % config['channel'])

	def _on_message(self, conn, event):
		source = irc.client.NickMask(event.source)
		if (source.nick.lower() == config['notifyuser']):
			# Notification from Twitch - send details up to the 
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
			log.info(urllib.parse.urlencode(notifyparams))
			res = urllib.request.urlopen(
				config['siteurl'] + "notifications",
				urllib.parse.urlencode(notifyparams).encode('ascii'),
			).read().decode("utf-8")
			try:
				res = json.loads(res)
			except:
				log.exception("Error parsing notification server response: " + res)
			else:
				if 'success' not in res:
					log.error("Error sending notification to server")
		else:
			command_match = self.re_botcommand.match(event.arguments[0])
			if command_match:
				command, params = command_match.groups()
				command = command.lower()
				if irc.client.is_channel(event.target):
					respond_to = event.target
				else:
					respond_to = source.nick
				if command == "help": #might try to find way to not hard code this for easier modification by LRR, once bot is functional
					conn.privmsg(respond_to, "Help: http://lrrbot.mrphlip.com/")
				if command == "fliptable":#can't be that hard for static messages
					conn.privmsg(respond_to, random.choose([
						"(╯°□°）╯︵ ┻━┻",
						"(╯°□°）╯︵ ┻━┻", # Make the classic a bit more likely
						"(╯°Д°）╯︵ ┻━┻",
						"(ﾉಠ益ಠ）ﾉ 彡ㅑ",
					]))
				if command == "fixtable":
					conn.privmsg(respond_to, "┳━┳ ノ(º_ºノ)")
				if command == "xcam":
					conn.privmsg(respond_to, "The xcam list is http://bit.ly/CamXCOM")
				if command == "game":#This whole thing will be obsolete once twitch api get integrated... hopefully
					game = GameINI[str(currentGame)]
					conn.privmsg(respond_to, "Current game selected is: %s" % (game['Title']))
				if command == "death": #got to add timer so that the command can only be called once every ~15 seconds
					game = GameINI[str(currentGame)]
					game['Deaths'] = str(int(game['Deaths']) + 1) #Does this seem redundant? Also not writing to file properly will fix tomorrow
					conn.privmsg(respond_to, "Current deathcount for %s" % (game['Deaths']))
                                        
																				

def init_logging():
	# TODO: something more sophisticated
	logging.basicConfig(level=config['loglevel'])
	global log
	log = logging.getLogger('lrrbot')

if __name__ == '__main__':
	main()
