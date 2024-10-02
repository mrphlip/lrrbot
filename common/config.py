import configparser

import pytz

from common.commandline import argv

CONFIG_SECTION = 'lrrbot'

config = configparser.ConfigParser()
config.read(argv.conf)

apipass = dict(config.items("apipass"))
from_apipass = {p: u for u, p in apipass.items()}

config = dict(config.items(CONFIG_SECTION))

# hostname - server to connect to (default Twitch)
config.setdefault('hostname', 'irc.chat.twitch.tv')
# secure - whether to use TLS to connect to the server
config.setdefault('secure', True)
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
config.setdefault('postgres', 'postgresql:///lrrbot')

# reconnecttime - seconds to wait before reconnecting after a disconnect
config['reconnecttime'] = int(config.get('reconnecttime', 15))
# keepalivetime - seconds between sending keep-alive ping messages
config['keepalivetime'] = int(config.get('keepalivetime', 60))
# keepalivethreshold - number of keep-alive pings with no response before giving up
config['keepalivethreshold'] = int(config.get('keepalivethreshold', 5))

# debug - boolean option
config.setdefault('debug', False)
config['debug'] = str(config['debug']).lower() != 'false'
# debugsql - boolean option, enables debugging mode for sqlalchemy
config.setdefault('debugsql', config['debug'])
config['debugsql'] = str(config['debugsql']).lower() != 'false'

# notifyuser - user to watch for notifications
config['notifyuser'] = config.get('notifyuser', 'twitchnotify').lower()
# commandprefix - symbol to prefix all bot commands
config.setdefault('commandprefix', '!')
# siteurl - root of web site
config.setdefault('siteurl', 'https://lrrbot.com/')

# datafile - file to store save data to
config.setdefault('datafile', 'data.json')

# timezone - timezone to use for display purposes - default to Pacific Time
config['timezone'] = pytz.timezone(config.get('timezone', 'America/Vancouver'))

# socket_filename - Filename for the UDS channel that the webserver uses to communicate with the bot
config.setdefault('socket_filename', 'lrrbot.sock')
# eventsocket - Filename for the UDS channel that the webserver uses to communicate with SSE clients
config.setdefault('eventsocket', "/tmp/eventserver.sock")
# eris_socket - Filename for the UDS channel that the Discord bot uses.
config.setdefault('eris_socket', 'eris.sock')

# socket_port - TCP port to use when Unix domain sockets are not available.
config['socket_port'] = int(config.get('socket_port', 49601))
# event_port - TCP port to use when Unix domain sockets are not available.
config['event_port'] = int(config.get('event_port', 49602))
config['eris_port'] = int(config.get('event_port', 49603))

# google_key - Google API key
config.setdefault('google_key', '')

# twitch_clientid - Twitch API client ID
config.setdefault('twitch_clientid', '')

# twitch_clientsecret - Twitch API secret key
config.setdefault('twitch_clientsecret', '')

# twitch_redirect_uri - Redirect URI set up for Twitch login
config.setdefault('twitch_redirect_uri', 'https://lrrbot.com/login')

# session_secret - Secret key for signing session cookies
config.setdefault('session_secret', '')

# preferred_url_scheme - Flask config key PREFERRED_URL_SCHEME: the URL scheme to use when no scheme is available
config.setdefault('preferred_url_scheme', 'https')

# whispers - boolean option, whether to connect to group chat server and respond to whispers
config.setdefault('whispers', False)
config['whispers'] = str(config['whispers']).lower() != 'false'

# Slack:
# slack_webhook_url - URL to post messages to
config.setdefault('slack_webhook_url', None)

# Patreon:
# patreon_user_id - Patreon creator user ID
config.setdefault('patreon_creator_user_id', '295787')

# patreon_clientid - Patreon API client ID
config.setdefault('patreon_clientid', '')

# patreon_clientsecret - Patreon API secret key
config.setdefault('patreon_clientsecret', '')

# patreon_redirect_uri - Redirect URI set up for Patreon login
config.setdefault('patreon_redirect_uri', 'https://lrrbot.com/patreon/login')

# log_desertbus_moderator_actions - log moderator actions in #desertbus
config['log_desertbus_moderator_actions'] = str(config.get('log_desertbus_moderator_actions', 'true')).lower() != 'false'

# mods - extra users who should be treated as mods by the bot even if they're not +o
config['mods'] = set(i.lower().strip() for i in config['mods'].split(',')) if config.get('mods') else set()

# YouTube:
# youtube_chat_enabled - Whether the bot is allowed to connect to YouTube chats
config['youtube_chat_enabled'] = str(config.get('youtube_chat_enabled', 'false')).lower() != 'false'

# youtube_client_id - YouTube OAuth2 client ID
config.setdefault('youtube_client_id', '')

# youtube_client_secret - YouTube OAuth2 client secret
config.setdefault('youtube_client_secret', '')

# youtube_redirect_uri - Redirect URI for the YouTube login
config.setdefault('youtube_redirect_uri', 'https://lrrbot.com/login/youtube')

# youtube_channels - YouTube channel IDs of the stream channels
config['youtube_channels'] = [channel.strip() for channel in config.get('youtube_channels', 'UCwjN2uVdL9A0i3gaIHKFzuA').split(',')] if config.get('youtube_channels') else []

# youtube_bot_id - YouTube channel ID of the bot account
config.setdefault('youtube_bot_id', 'UCskb2pkqoH_gLzOnLZqLtVg')
