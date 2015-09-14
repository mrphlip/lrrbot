import json
import random
import asyncio

from common import utils
from common.config import config
from lrrbot import storage


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
		channel_data['viewers'] = data['stream'].get('viewers')
		channel_data['stream_created_at'] = data['stream'].get('created_at')
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
	if channel_data.get('game') is not None:
		return get_game(name=channel_data['game'])
	return None

@asyncio.coroutine
def get_subscribers(channel=None, count=5, offset=None, latest=True):
	if channel is None:
		channel = config['channel']
	if channel not in storage.data['twitch_oauth']:
		return None
	headers = {
		"Authorization": "OAuth %s" % storage.data['twitch_oauth'][channel],
	}
	data = {
		"limit": count,
		"direction": "desc" if latest else "asc",
	}
	if offset is not None:
		data['offset'] = offset
	res = yield from utils.http_request_coro("https://api.twitch.tv/kraken/channels/%s/subscriptions" % channel, headers=headers, data=data)
	subscriber_data = json.loads(res)
	return [
		(sub['user']['display_name'], sub['user'].get('logo'), sub['created_at'])
		for sub in subscriber_data['subscriptions']
	]

def get_group_servers():
	"""
	Get the secondary Twitch chat servers
	"""
	res = utils.http_request("https://chatdepot.twitch.tv/room_memberships", {'oauth_token': storage.data['twitch_oauth'][config['username']]}, maxtries=1)
	res = json.loads(res)
	def parse_server(s):
		if ':' in s:
			bits = s.split(':')
			return bits[0], int(bits[1])
		else:
			return s, 6667
	servers = set(parse_server(s) for m in res['memberships'] for s in m['room']['servers'])
	# each server appears in this multiple times with different ports... pick one port we prefer for each server
	server_dict = {}
	for host, port in servers:
		server_dict.setdefault(host, set()).add(port)
	def preferred_port(ports):
		if 6667 in ports:
			return 6667
		elif ports - {80, 443}:
			return random.choice(list(ports - {80, 443}))
		else:
			return random.choice(list(ports))
	servers = [(host, preferred_port(ports)) for host,ports in server_dict.items()]
	random.shuffle(servers)
	return servers

@asyncio.coroutine
def get_follows_channels(username=None):
	if username is None:
		username = config["username"]
	url = "https://api.twitch.tv/kraken/users/%s/follows/channels" % username
	follows = []
	total = 1
	while len(follows) < total:
		data = yield from utils.http_request_coro(url)
		data = json.loads(data)
		total = data["_total"]
		follows += data["follows"]
		url = data["_links"]["next"]
	return follows

@asyncio.coroutine
def get_streams_followed(username=None):
	if username is None:
		username = config["username"]
	url = "https://api.twitch.tv/kraken/streams/followed"
	headers = {
		"Authorization": "OAuth %s" % storage.data['twitch_oauth'][username],
	}
	streams = []
	total = 1
	while len(streams) < total:
		data = yield from utils.http_request_coro(url, headers=headers)
		data = json.loads(data)
		total = data["_total"]
		streams += data["streams"]
		url = data["_links"]["next"]
	return streams

@asyncio.coroutine
def follow_channel(target, user=None):
	if user is None:
		user = config["username"]
	headers = {
		"Authorization": "OAuth %s" % storage.data['twitch_oauth'][user],
	}
	yield from utils.http_request_coro("https://api.twitch.tv/kraken/users/%s/follows/channels/%s" % (user, target),
									data={"notifications": "false"}, method="PUT", headers=headers)
