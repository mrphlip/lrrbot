import json
import time
import utils
from config import config

def get_info(username=None, use_fallback=True):
	"""
	Get the Twitch info for a particular user or channel.

	Defaults to the stream channel if not otherwise specified.

	For response object structure, see:
	https://github.com/justintv/Twitch-API/blob/master/v3_resources/channels.md#example-response

	May throw exceptions on network/Twitch error.
	"""
	if username is None:
		username = config['channel']

	# Attempt to get the channel data from /streams/channelname
	# If this succeeds, it means the channel is currently live
	res = utils.http_request("https://api.twitch.tv/kraken/streams/%s" % username)
	data = json.loads(res)
	channel_data = data.get('stream') and data['stream'].get('channel')
	if channel_data:
		channel_data['live'] = True
		channel_data['viewers'] = data['stream']['viewers']
		return channel_data

	if not use_fallback:
		return None

	# If that failed, it means the channel is offline
	# Ge the channel data from here instead
	res = utils.http_request("https://api.twitch.tv/kraken/channels/%s" % username)
	channel_data = json.loads(res)
	channel_data['live'] = False
	return channel_data

def get_game(name, all=False):
	"""
	Get the game information for a particular game.

	For response object structure, see:
	https://github.com/justintv/Twitch-API/blob/master/v3_resources/search.md#example-response-1	

	May throw exceptions on network/Twitch error.
	"""
	search_opts = {
		'query': name,
		'type': 'suggest',
		'live': 'false',
	}
	res = utils.http_request("https://api.twitch.tv/kraken/search/games", search_opts)
	res = json.loads(res)
	if all:
		return res['games']
	else:
		for game in res['games']:
			if game['name'] == name:
				return game
		return None

def get_game_playing(username=None):
	"""
	Get the game information for the game the stream is currently playing
	"""
	channel_data = get_info(username, use_fallback=False)
	if not channel_data or not channel_data['live']:
		return None
	if channel_data['game'] is not None:
		return get_game(name=channel_data['game'])
	return None
