#!/usr/bin/env python3
# Dependencies:
#   easy_install irc oauth

import re
import functools
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
		self.ircobj.add_global_handler('pubmsg', self._on_pubmsg)

		self.re_botcommand = re.compile(r"^\s*%s\s*(\w+)\b\s*(.*?)\s*$" % re.escape(config['commandprefix']))

	def _on_connect(self, conn, event):
		conn.join("#%s" % config['channel'])

	def _on_pubmsg(self, conn, event):
		source = irc.client.NickMask(event.source)
		if (source.nick.lower() == config['notifyuser']):
			# TODO: everything
			log.info("Notification: %s" % event.arguments[0])
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
