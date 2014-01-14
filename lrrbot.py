#!/usr/bin/env python3
# Dependencies:
#   easy_install irc oauth

import re
import time
import urllib.request, urllib.parse
import json
import logging
import irc.bot, irc.client
from config import config

def main():
	init_logging()

	log.debug("Initialising connection")
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
				# TODO: get channel info for this user and set notifyparams['avatar']
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
				if command == "help":
					conn.privmsg(respond_to, "TODO: Help messages")

def init_logging():
	# TODO: something more sophisticated
	logging.basicConfig(level=config['loglevel'])
	global log
	log = logging.getLogger('lrrbot')

if __name__ == '__main__':
	main()
