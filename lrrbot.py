#!/usr/bin/env python3
# Dependencies:
#   easy_install irc oauth

import re
import configparser
import functools
import logging
import irc.bot, irc.client

CONFIG_FILENAME = 'lrrbot.conf' # TODO: override-able from command line?
COFNIG_SECTION = 'lrrbot'

def main():
	read_config()
	init_logging()

	log.debug("Initialising connection")
	LRRBot().start()

class LRRBot(irc.bot.SingleServerIRCBot):
	def __init__(self):
		server = irc.bot.ServerSpec(
			host=conf['hostname'],
			port=conf['port'],
			password=conf['password'],
		)
		super(LRRBot, self).__init__(
			server_list=[server],
			realname=conf['username'],
			nickname=conf['username'],
		)

		self.ircobj.add_global_handler('welcome', self._on_connect)
		self.ircobj.add_global_handler('pubmsg', self._on_pubmsg)

		self.re_botcommand = re.compile(r"^\s*%s\s*(\w+)\b\s*(.*?)\s*$" % re.escape(conf['commandprefix']))

	def _on_connect(self, conn, event):
		conn.join("#%s" % conf['channel'])

	def _on_pubmsg(self, conn, event):
		source = irc.client.NickMask(event.source)
		if (source.nick.lower() == conf['notifyuser']):
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


def read_config():
	global conf

	config = configparser.ConfigParser()
	config.read(CONFIG_FILENAME)
	conf = dict(config.items(COFNIG_SECTION))

	# hostname - server to connect to (default Twitch)
	conf.setdefault('hostname', 'irc.twitch.tv')
	# port - portname to connect on (default 6667)
	conf['port'] = int(conf.get('port', 6667))
	# username
	conf.setdefault('username', 'lrrbot')
	# password - server password
	conf.setdefault('password', None)
	# channel - without the hash
	conf.setdefault('channel', 'loadingreadyrun')
	# debug - boolean option
	conf.setdefault('debug', False)
	conf['debug'] = str(conf['debug']).lower() != 'FALSE'
	# loglevel - either a number or a level name, default depends on debug setting
	try:
		conf['loglevel'] = int(conf.get('loglevel', logging.DEBUG if conf['debug'] else logging.INFO))
	except ValueError:
		conf['loglevel'] = logging.getLevelName(conf['loglevel'])
		# This assert fails if the entered value is neither a number nor a recognised level name
		assert isinstance(conf['loglevel'], int)
	# notifyuser - user to watch for notifications
	conf['notifyuser'] = conf.get('notifyuser', 'twitchnotify').lower()
	# commandprefix - symbol to prefix all bot commands
	conf.setdefault('commandprefix', '!')

def init_logging():
	# TODO: something more sophisticated
	logging.basicConfig(level=conf['loglevel'])
	global log
	log = logging.getLogger('lrrbot')

if __name__ == '__main__':
	main()
