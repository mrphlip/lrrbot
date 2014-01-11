import configparser
import logging

CONFIG_FILENAME = 'lrrbot.conf' # TODO: override-able from command line?
COFNIG_SECTION = 'lrrbot'

config = configparser.ConfigParser()
config.read(CONFIG_FILENAME)
config = dict(config.items(COFNIG_SECTION))

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
# debug - boolean option
config.setdefault('debug', False)
config['debug'] = str(config['debug']).lower() != 'FALSE'
# loglevel - either a number or a level name, default depends on debug setting
try:
	config['loglevel'] = int(config.get('loglevel', logging.DEBUG if config['debug'] else logging.INFO))
except ValueError:
	config['loglevel'] = logging.getLevelName(config['loglevel'])
	# This assert fails if the entered value is neither a number nor a recognised level name
	assert isinstance(config['loglevel'], int)
# notifyuser - user to watch for notifications
config['notifyuser'] = config.get('notifyuser', 'twitchnotify').lower()
# commandprefix - symbol to prefix all bot commands
config.setdefault('commandprefix', '!')
