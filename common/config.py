import configparser
import logging

import pytz

from common.commandline import argv


CONFIG_SECTION = 'lrrbot'

config = configparser.ConfigParser()
config.read(argv.conf)
mysqlopts = dict(config.items("mysqlopts"))
apipass = dict(config.items("apipass"))
config = dict(config.items(CONFIG_SECTION))

# hostname - server to connect to (default Twitch)
config.setdefault('hostname', 'irc.twitch.tv')
# port - portname to connect on (default 6667)
config['port'] = int(config.get('port', 6667))
# username
config.setdefault('username', 'lrrbot')
# password - server password
config.setdefault('password', None)
# channel - without the hash
config.setdefault('channel', 'loadingreadyrun')

# reconnecttime - seconds to wait before reconnecting after a disconnect
config['reconnecttime'] = int(config.get('reconnecttime', 15))
# keepalivetime - seconds between sending keep-alive ping messages
config['keepalivetime'] = int(config.get('keepalivetime', 60))
# checksubstime - seconds between checking for new subscribers via Twitch API
config['checksubstime'] = int(config.get('checksubstime', 60))

# debug - boolean option
config.setdefault('debug', False)
config['debug'] = str(config['debug']).lower() != 'false'
# loglevel - either a number or a level name, default depends on debug setting
try:
	config['loglevel'] = int(config.get('loglevel', logging.DEBUG if config['debug'] else logging.INFO))
except ValueError:
	config['loglevel'] = logging.getLevelName(config['loglevel'])
	# This assert fails if the entered value is neither a number nor a recognised level name
	assert isinstance(config['loglevel'], int)
# logfile - either blank a filename to log to, or blank to indicate logging to stderr only
config.setdefault('logfile', None)
if config['logfile'] == "":
	config['logfile'] = None

# notifyuser - user to watch for notifications
config['notifyuser'] = config.get('notifyuser', 'twitchnotify').lower()
# metadatauser - user to watch for Twitch metadata
config['metadatauser'] = config.get('metadatauser', 'jtv').lower()
# commandprefix - symbol to prefix all bot commands
config.setdefault('commandprefix', '!')
# siteurl - root of web site
config.setdefault('siteurl', 'http://lrrbot.mrphlip.com/')
# apipass - secret string needed to communicate with web site
config.setdefault('apipass', None)

# mods - comma-separated list of moderators for the bot, in addition to people with chanop privileges
config['mods'] = set(i.strip().lower() for i in config.get('mods', 'd3fr0st5,mrphlip,lord_hosk,admiralmemo,dixonij').split(','))

# datafile - file to store save data to
config.setdefault('datafile', 'data.json')

# timezone - timezone to use for display purposes - default to Pacific Time
config['timezone'] = pytz.timezone(config.get('timezone', 'America/Vancouver'))

# socket_filename - Filename for the UDS channel that the webserver uses to communicate with the bot
config.setdefault('socket_filename', 'lrrbot.sock')

# google_key - Google API key
config.setdefault('google_key', '')

# twitch_clientid - Twitch API client ID
config.setdefault('twitch_clientid', '')

# twitch_clientsecret - Twitch API secret key
config.setdefault('twitch_clientsecret', '')

# session_secret - Secret key for signing session cookies
config.setdefault('session_secret', '')
