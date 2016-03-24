import configparser
import logging
import re

import pytz

from common.commandline import argv

CONFIG_SECTION = 'lrrbot'

config = configparser.ConfigParser()
config.read(argv.conf)

apipass = dict(config.items("apipass"))
from_apipass = {p:u for u,p in apipass.items()}

config = dict(config.items(CONFIG_SECTION))

# hostname - server to connect to (default Twitch)
config.setdefault('hostname', 'irc.twitch.tv')
# secure - whether to use TLS to connect to the server
config.setdefault('secure', False)
config['secure'] = str(config['secure']).lower() != 'false'
# port - portname to connect on (default 6667, or 6697 for secure)
config['port'] = int(config.get('port', 6697 if config['secure'] else 6667))
# username
config.setdefault('username', 'lrrbot')
# password - server password
config.setdefault('password', None)
# channel - without the hash
config.setdefault('channel', 'loadingreadyrun')

# postgres - libpg connection string
# See https://www.postgresql.org/docs/current/static/libpq-connect.html#LIBPQ-CONNSTRING
config.setdefault('postgres', 'postgres:///lrrbot')

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
# commandprefix - symbol to prefix all bot commands
config.setdefault('commandprefix', '!')
# siteurl - root of web site
config.setdefault('siteurl', 'https://lrrbot.mrphlip.com/')
# apipass - secret string needed to communicate with web site
config["apipass"] = apipass.get(config["username"])

# datafile - file to store save data to
config.setdefault('datafile', 'data.json')

# timezone - timezone to use for display purposes - default to Pacific Time
config['timezone'] = pytz.timezone(config.get('timezone', 'America/Vancouver'))

# socket_filename - Filename for the UDS channel that the webserver uses to communicate with the bot
config.setdefault('socket_filename', 'lrrbot.sock')
# eventsocket - Filename for the UDS channel that the webserver uses to communicate with SSE clients
config.setdefault('eventsocket', "/tmp/eventserver.sock")

# google_key - Google API key
config.setdefault('google_key', '')

# twitch_clientid - Twitch API client ID
config.setdefault('twitch_clientid', '')

# twitch_clientsecret - Twitch API secret key
config.setdefault('twitch_clientsecret', '')

# session_secret - Secret key for signing session cookies
config.setdefault('session_secret', '')

# whispers - boolean option, whether to connect to group chat server and respond to whispers
config.setdefault('whispers', False)
config['whispers'] = str(config['whispers']).lower() != 'false'

# cardviewersubkey - Pubnub subscribe key for xsplit card viewer channel
config.setdefault('cardsubkey', None)

# cardviewerchannel - Pubnub channel for xsplit card viewer
config.setdefault('cardviewerchannel', 'xsplit_image')

# Slack:
# slack_webhook_url - URL to post messages to
config.setdefault('slack_webhook_url', None)

# Patreon:
# patreon_clientid - Patreon API client ID
config.setdefault('patreon_clientid', '')

# patreon_clientsecret - Patreon API secret key
config.setdefault('patreon_clientsecret', '')
