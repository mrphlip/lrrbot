import json
import random
import socket
import dateutil.parser
import sqlalchemy
from sqlalchemy.dialects.postgresql import insert
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

	https://dev.twitch.tv/docs/api/reference#get-users
	"""
	engine, metadata = postgres.get_engine_and_metadata()
	users = metadata.tables["users"]
	with engine.begin() as conn:
		query = sqlalchemy.select([users.c.id, users.c.name, users.c.display_name, users.c.twitch_oauth])
		if id is not None:
			query = query.where(users.c.id == id)
			data = {'id': id}
			by_name = False
		elif name is not None:
			query = query.where(users.c.name == name)
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
				'Authorization': f"Bearer {get_token()}",
			}
			res = common.http.request("https://api.twitch.tv/helix/users", data=data, headers=headers)
			user = json.loads(res)['data'][0]
			insert_query = insert(users)
			insert_query = insert_query.on_conflict_do_update(
				index_elements=[users.c.id],
				set_={
					'name': insert_query.excluded.name,
					'display_name': insert_query.excluded.display_name,
				},
			)
			conn.execute(insert_query, {
				"id": user["id"],
				"name": user["login"],
				"display_name": user["display_name"],
			})

			return User(int(user["id"]), user["login"], user['display_name'], None)

def get_token(id=None, name=None):
	"""
	Get the OAuth token for a given user, specified by either name or id.

	Defaults to getting the OAuth token for the bot user.
	"""
	if id is None and name is None:
		name = config['username']
	return get_user(id=id, name=name, get_missing=False).token

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

	def __aiter__(self):
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

	def __aiter__(self):
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

class get_paginated_helix:
	"""
	Collect all the results from a pgainated query that uses the before/after
	method of pagination.

	See:
	https://dev.twitch.tv/docs/api/guide#pagination

	Provide the url/data/headers without the before/after arguments.

	Optionally can provide a limit to stop the process before the end of the list.
	The returned list may be longer than limit, but once the limit is reached, no
	further pages will be requested.
	"""
	def __init__(self, url, attr="data", data=None, headers=None, limit=None, per_page=None):
		self.url = url
		self.attr = attr
		if data:
			self.data = dict(data)
		else:
			self.data = {}
		if per_page is not None:
			self.data['first'] = per_page
		self.headers = headers
		self.limit = limit

		self.count = 0
		self.cursor = True
		self.buffer = None

	def __aiter__(self):
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
			self.cursor = self.data['after'] = res.get('pagination', {}).get('cursor')

def get_info_uncached(username=None, use_fallback=True):
	"""
	Get the Twitch info for a particular user or channel.

	Defaults to the stream channel if not otherwise specified.

	For response object structure, see:
	https://dev.twitch.tv/docs/api/reference#get-users
	https://dev.twitch.tv/docs/api/reference#get-streams
	https://dev.twitch.tv/docs/api/reference#get-channel-information

	May throw exceptions on network/Twitch error.
	"""
	if username is None:
		username = config['channel']
	userid = get_user(name=username).id

	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {get_token()}",
	}
	res = common.http.request("https://api.twitch.tv/helix/users", {"id": userid}, headers=headers)
	user_data = json.loads(res)['data'][0]

	# Attempt to get the channel data from /streams
	# If this succeeds, it means the channel is currently live
	res = common.http.request("https://api.twitch.tv/helix/streams", {"user_id": userid}, headers=headers)
	data = json.loads(res)['data']
	channel_data = data and data[0]
	if channel_data:
		user_data.update(channel_data)
		user_data['live'] = True
		return user_data

	if not use_fallback:
		return None

	# If that failed, it means the channel is offline
	# Ge the channel data from here instead
	res = common.http.request("https://api.twitch.tv/helix/channels", {"broadcaster_id": userid}, headers=headers)
	channel_data = json.loads(res)['data'][0]
	user_data.update(channel_data)
	user_data['live'] = False
	return user_data

@utils.cache(GAME_CHECK_INTERVAL, params=[0, 1])
def get_info(username=None, use_fallback=True):
	return get_info_uncached(username, use_fallback=use_fallback)

Game = collections.namedtuple('Game', ['id', 'name'])
def get_game_playing(username=None):
	"""
	Get the game information for the game the stream is currently playing
	"""
	channel_data = get_info(username, use_fallback=False)
	if not channel_data or not channel_data['live']:
		return None
	if channel_data.get('game_id'):
		return Game(channel_data['game_id'], channel_data['game_name'])
	return None

def is_stream_live(username=None):
	"""
	Get whether the stream is currently live
	"""
	channel_data = get_info(username, use_fallback=False)
	return channel_data and channel_data['live']

async def get_follows_channels(username=None):
	"""
	Get a list of all channels followed by a given user.

	See:
	https://dev.twitch.tv/docs/api/reference#get-users-follows
	"""
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {get_token()}",
	}
	if username is None:
		username = config["username"]
	userid = get_user(name=username).id
	url = "https://api.twitch.tv/helix/users/follows"
	return await utils.async_to_list(get_paginated_helix(url, data={'from_id': userid}, headers=headers))

async def get_streams_followed():
	"""
	Get a list of all currently-live streams on channels followed by us.

	See:
	https://dev.twitch.tv/docs/v5/reference/streams/#get-followed-streams
	"""
	userid, username, display_name, token = get_user(name=config["username"])
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {token}",
	}
	return await utils.async_to_list(get_paginated_helix("https://api.twitch.tv/helix/streams/followed", data={"user_id": userid}, headers=headers))

async def follow_channel(target):
	raise Exception("Automated following of channels has been disabled by Twitch")

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
	raise Exception("Automated unfollowing of channels has been disabled by Twitch")

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
	https://dev.twitch.tv/docs/api/reference#get-videos
	"""
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {get_token()}",
	}
	data = await common.http.request_coro("https://api.twitch.tv/helix/videos", {"id": videoid.lstrip('v')}, headers=headers)
	return json.loads(data)["data"][0]

async def get_videos(channel=None, limit=10, broadcasts=False):
	"""
	Get the details for the latest videos (either broadcasts or highlights) from a channel.

	See:
	https://dev.twitch.tv/docs/api/reference#get-videos
	"""
	channelid = get_user(name=channel or config["channel"]).id
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {get_token()}",
	}
	data = await common.http.request_coro("https://api.twitch.tv/helix/videos", headers=headers, data={
		"user_id": channelid,
		"first": str(limit),
		"sort": "time",
		"type": "archive" if broadcasts else "highlight",
	})
	return json.loads(data)["data"]

def get_followers(channel=None):
	"""
	Get an asynchronous list of all the followers of a given channel.

	See:
	https://dev.twitch.tv/docs/v5/reference/channels/#get-channel-followers
	"""
	channelid = get_user(name=channel or config["channel"]).id
	url = "https://api.twitch.tv/helix/users/follows"
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {get_token()}",
	}
	return get_paginated_helix(url, data={"to_id": channelid}, headers=headers)
