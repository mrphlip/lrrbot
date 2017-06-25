import json
import random
import socket
import dateutil.parser
import sqlalchemy
import collections

import common.http
from common import utils
from common import postgres
from common.config import config

GAME_CHECK_INTERVAL = 5*60

User = collections.namedtuple('User', ['id', 'name', 'display_name', 'token'])
def get_user(id=None, name=None, get_missing=True):
	"""
	Get the details for a given user, specified by either name or id.

	Returns a named tuple of (id, name, display_name, token)

	If get_missing is true, get the details for this user from Twitch if the user
	is not already in the database. Otherwise if the userisn't in the database,
	this returns None.
	"""
	engine, metadata = postgres.get_engine_and_metadata()
	users = metadata.tables["users"]
	with engine.begin() as conn:
		query = sqlalchemy.select([users.c.id, users.c.name, users.c.display_name, users.c.twitch_oauth])
		if id is not None:
			query = query.where(users.c.id == id)
			url = "https://api.twitch.tv/kraken/users/%d" % id
			data = {}
			by_name = False
		elif name is not None:
			query = query.where(users.c.name == name)
			url = "https://api.twitch.tv/kraken/users"
			data = {'login': name}
			by_name = True
		else:
			raise ValueError("Pass at least one of name or id")

		row = conn.execute(query).first()
		if row:
			return User(*row)

		if get_missing:
			headers = {
				'Client-ID': config['twitch_clientid'],
				'Accept': 'application/vnd.twitchtv.v5+json',
			}
			res = common.http.request(url, data=data, headers=headers)
			user = json.loads(res)
			if by_name:
				user = user['users'][0]
			insert_query = insert(users)
			insert_query = insert_query.on_conflict_do_update(
				index_elements=[users.c.id],
				set_={
					'name': insert_query.excluded.name,
					'display_name': insert_query.excluded.display_name,
				},
			)
			conn.execute(insert_query, {
				"id": user["_id"],
				"name": user["name"],
				"display_name": user["display_name"],
			})

			return User(user["_id"], user["name"], user['display_name'], None)

class get_paginated_by_offset:
	"""
	Collect all the results from a paginated query that uses the offset/limit
	method of pagination.

	See:
	https://dev.twitch.tv/docs/v5/guides/using-the-twitch-api#paging-through-results-cursor-vs-offset

	Provide the url/data/headers without the offset/limit arguments, and the name
	of the attribute in the result which contains the list to be collected.

	Optionally can provide a limit to stop the process before the end of the list.
	The returned list may be longer than limit, but once the limit is reached, no
	further pages will be requested.
	"""
	PAGE_SIZE = 25

	def __init__(self, url, attr, data=None, headers=None, limit=None):
		self.url = url
		self.attr = attr
		if data:
			self.data = dict(data)
		else:
			self.data = {}
		self.headers = headers
		self.limit = limit

		self.count = 0
		self.total = 1
		self.offset = 0
		self.buffer = None

	async def __aiter__(self):
		return self

	async def __anext__(self):
		while True:
			if self.buffer:
				self.count += 1
				return self.buffer.pop(0)

			if self.offset > self.total:
				raise StopAsyncIteration
			if self.limit is not None and self.count > self.limit:
				raise StopAsyncIteration

			self.data['offset'] = self.offset
			self.data['limit'] = self.PAGE_SIZE
			res = await common.http.request_coro(self.url, data=self.data, headers=self.headers)
			res = json.loads(res)
			self.buffer = res[self.attr]
			self.total = res['_total']
			self.offset += self.PAGE_SIZE

class get_paginated_by_cursor:
	"""
	Collect all the results from a paginated query that uses the cursor
	method of pagination.

	See:
	https://dev.twitch.tv/docs/v5/guides/using-the-twitch-api#paging-through-results-cursor-vs-offset

	Provide the url/data/headers without the cursor argument, and the name
	of the attribute in the result which contains the list to be collected.

	Optionally can provide a limit to stop the process before the end of the list.
	The returned list may be longer than limit, but once the limit is reached, no
	further pages will be requested.
	"""
	def __init__(self, url, attr, data=None, headers=None, limit=None):
		self.url = url
		self.attr = attr
		if data:
			self.data = dict(data)
		else:
			self.data = {}
		self.headers = headers
		self.limit = limit

		self.count = 0
		self.cursor = True
		self.buffer = None

	async def __aiter__(self):
		return self

	async def __anext__(self):
		while True:
			if self.buffer:
				self.count += 1
				return self.buffer.pop(0)

			if not self.cursor:
				raise StopAsyncIteration
			if self.limit is not None and self.count > self.limit:
				raise StopAsyncIteration

			res = await common.http.request_coro(self.url, data=self.data, headers=self.headers)
			res = json.loads(res)
			self.buffer = res[self.attr]
			self.cursor = self.data['cursor'] = res.get('_cursor')

def get_info_uncached(username=None, use_fallback=True):
	"""
	Get the Twitch info for a particular user or channel.

	Defaults to the stream channel if not otherwise specified.

	For response object structure, see:
	https://dev.twitch.tv/docs/v5/reference/channels/#get-channel-by-id

	May throw exceptions on network/Twitch error.
	"""
	if username is None:
		username = config['channel']
	userid = get_user(name=username).id

	# Attempt to get the channel data from /streams/channelname
	# If this succeeds, it means the channel is currently live
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Accept': 'application/vnd.twitchtv.v5+json',
	}
	res = common.http.request("https://api.twitch.tv/kraken/streams/%d?stream_type=live" % userid, headers=headers)
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
	res = common.http.request("https://api.twitch.tv/kraken/channels/%d" % userid, headers=headers)
	channel_data = json.loads(res)
	channel_data['live'] = False
	return channel_data

@utils.cache(GAME_CHECK_INTERVAL, params=[0, 1])
def get_info(username=None, use_fallback=True):
	return get_info_uncached(username, use_fallback=use_fallback)

@utils.cache(GAME_CHECK_INTERVAL, params=[0, 1])
def get_game(name, all=False):
	"""
	Get the game information for a particular game.

	For response object structure, see:
	https://dev.twitch.tv/docs/v5/reference/search/#search-games

	May throw exceptions on network/Twitch error.
	"""
	search_opts = {
		'query': name,
		'type': 'suggest',
		'live': 'false',
	}
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Accept': 'application/vnd.twitchtv.v5+json',
	}
	res = common.http.request("https://api.twitch.tv/kraken/search/games", search_opts, headers=headers)
	res = json.loads(res)
	if all:
		return res['games'] or []
	else:
		for game in res['games'] or []:
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
	if channel_data.get('game'):
		return get_game(name=channel_data['game'])
	return None

def is_stream_live(username=None):
	"""
	Get whether the stream is currently live
	"""
	channel_data = get_info(username, use_fallback=False)
	return channel_data and channel_data['live']

async def get_subscribers(channel=None, count=5, offset=None, latest=True):
	channelid, channelname, display_name, token = get_user(name=channel or config["channel"])
	headers = {
		'Authorization': "OAuth %s" % token,
		'Client-ID': config['twitch_clientid'],
		'Accept': 'application/vnd.twitchtv.v5+json',
	}
	data = {
		"limit": str(count),
		"direction": "desc" if latest else "asc",
	}
	if offset is not None:
		data['offset'] = str(offset)
	res = await common.http.request_coro("https://api.twitch.tv/kraken/channels/%d/subscriptions" % channelid, headers=headers, data=data)
	subscriber_data = json.loads(res)
	return [
		(sub['user']['display_name'], sub['user'].get('logo'), sub['created_at'], sub.get('updated_at', sub['created_at']))
		for sub in subscriber_data['subscriptions']
	]

async def get_follows_channels(username=None):
	"""
	Get a list of all channels followed by a given user.

	See:
	https://dev.twitch.tv/docs/v5/reference/users/#get-user-follows
	"""
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Accept': 'application/vnd.twitchtv.v5+json',
	}
	if username is None:
		username = config["username"]
	userid = get_user(name=username).id
	url = "https://api.twitch.tv/kraken/users/%d/follows/channels" % userid
	return await utils.async_to_list(get_paginated_by_offset(url, 'follows', headers=headers))

async def get_streams_followed():
	"""
	Get a list of all currently-live streams on channels followed by us.

	See:
	https://dev.twitch.tv/docs/v5/reference/streams/#get-followed-streams
	"""
	token = get_user(name=config["username"]).token
	headers = {
		'Authorization': "OAuth %s" % token,
		'Client-ID': config['twitch_clientid'],
		'Accept': 'application/vnd.twitchtv.v5+json',
	}
	return await utils.async_to_list(get_paginated_by_offset("https://api.twitch.tv/kraken/streams/followed", 'streams', headers=headers))

async def follow_channel(target):
	userid, username, display_name, token = get_user(name=config["username"])
	targetuserid = get_user(name=target).id
	headers = {
		'Authorization': "OAuth %s" % token,
		'Client-ID': config['twitch_clientid'],
		'Accept': 'application/vnd.twitchtv.v5+json',
	}
	await common.http.request_coro("https://api.twitch.tv/kraken/users/%d/follows/channels/%d" % (userid, targetuserid),
	                               data={"notifications": "false"}, method="PUT", headers=headers)

async def unfollow_channel(target):
	userid, username, display_name, token = get_user(name=config["username"])
	targetuserid = get_user(name=target).id
	headers = {
		'Authorization': "OAuth %s" % token,
		'Client-ID': config['twitch_clientid'],
		'Accept': 'application/vnd.twitchtv.v5+json',
	}
	await common.http.request_coro("https://api.twitch.tv/kraken/users/%s/follows/channels/%s" % (userid, targetuserid),
	                               method="DELETE", headers=headers)

async def get_video(videoid):
	"""
	Get the details for a specific VOD.

	Parameter can be passed with or without the 'v' prefix (ie '123' or 'v123').

	See:
	https://dev.twitch.tv/docs/v5/reference/videos/#get-video
	"""
	headers = {
		"Client-ID": config['twitch_clientid'],
		'Accept': 'application/vnd.twitchtv.v5+json',
	}
	data = await common.http.request_coro("https://api.twitch.tv/kraken/videos/%s" % videoid.lstrip('v'), headers=headers)
	return json.loads(data)

async def get_videos(channel=None, offset=0, limit=10, broadcasts=False):
	"""
	Get the details for the latest videos (either broadcasts or highlights) from a channel.

	See:
	https://dev.twitch.tv/docs/v5/reference/channels/#get-channel-videos
	"""
	channelid = get_user(name=channel or config["channel"]).id
	headers = {
		"Client-ID": config['twitch_clientid'],
		'Accept': 'application/vnd.twitchtv.v5+json',
	}
	data = await common.http.request_coro("https://api.twitch.tv/kraken/channels/%d/videos" % channelid, headers=headers, data={
		"offset": str(offset),
		"limit": str(limit),
		"broadcast_type": "archive" if broadcasts else "highlight",
	})
	return json.loads(data)["videos"]

def get_followers(channel=None, direction='desc'):
	"""
	Get an asynchronous list of all the followers of a given channel.

	See:
	https://dev.twitch.tv/docs/v5/reference/channels/#get-channel-followers
	"""
	channelid = get_user(name=channel or config["channel"]).id
	url = "https://api.twitch.tv/kraken/channels/%d/follows" % channelid
	headers = {
		"Client-ID": config['twitch_clientid'],
		'Accept': 'application/vnd.twitchtv.v5+json',
	}
	return get_paginated_by_cursor(url, 'follows', data={'direction': direction}, headers=headers)

async def twitchbot_approve(msg_id):
	token = get_user(name=config["username"]).token
	headers = {
		"Authorization": "OAuth %s" % token,
		"Client-ID": config['twitch_clientid'],
		"Accept": "application/vnd.twitchtv.v5+json",
	}
	data = {
		"msg_id": msg_id,
	}
	await common.http.request_coro("https://api.twitch.tv/kraken/chat/twitchbot/approve",
	                               data=data, method="POST", headers=headers, asjson=True)
