import json
import sqlalchemy
from sqlalchemy.dialects.postgresql import insert
import collections

import common.http
from common import utils
from common import postgres
from common.config import config
from common.account_providers import ACCOUNT_PROVIDER_TWITCH

GAME_CHECK_INTERVAL = 5*60

User = collections.namedtuple('User', ['id', 'name', 'display_name', 'token'])
async def get_user(id=None, name=None, get_missing=True):
	"""
	Get the details for a given user, specified by either name or id.

	Returns a named tuple of (id, name, display_name, token)

	If get_missing is true, get the details for this user from Twitch if the user
	is not already in the database. Otherwise, if the user isn't in the database,
	this returns None.

	https://dev.twitch.tv/docs/api/reference#get-users
	"""
	engine, metadata = postgres.get_engine_and_metadata()
	accounts = metadata.tables["accounts"]
	with engine.connect() as conn:
		query = sqlalchemy.select(accounts.c.provider_user_id, accounts.c.name, accounts.c.display_name, accounts.c.access_token) \
			.where(accounts.c.provider == ACCOUNT_PROVIDER_TWITCH)
		if id is not None:
			query = query.where(accounts.c.provider_user_id == id)
			data = {'id': id}
		elif name is not None:
			query = query.where(accounts.c.name == name)
			data = {'login': name}
		else:
			raise ValueError("Pass at least one of name or id")

		row = conn.execute(query).first()
		if row:
			return User(*row)

		if get_missing:
			headers = {
				'Client-ID': config['twitch_clientid'],
				'Authorization': f"Bearer {await get_token()}",
			}
			res = await common.http.request("https://api.twitch.tv/helix/users", data=data, headers=headers)
			user = json.loads(res)['data'][0]
			insert_query = insert(accounts)
			insert_query = insert_query.on_conflict_do_update(
				index_elements=[accounts.c.provider, accounts.c.provider_user_id],
				set_={
					'name': insert_query.excluded.name,
					'display_name': insert_query.excluded.display_name,
				},
			)
			conn.execute(insert_query, {
				"provider": ACCOUNT_PROVIDER_TWITCH,
				"provider_user_id": user["id"],
				"name": user["login"],
				"display_name": user["display_name"],
			})
			conn.commit()

			return User(user["id"], user["login"], user['display_name'], None)

async def get_token(id=None, name=None):
	"""
	Get the OAuth token for a given user, specified by either name or id.

	Defaults to getting the OAuth token for the bot user.
	"""
	if id is None and name is None:
		name = config['username']
	return (await get_user(id=id, name=name, get_missing=False)).token

class get_paginated:
	"""
	Collect all the results from a paginated query that uses the before/after
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

			res = await common.http.request(self.url, data=self.data, headers=self.headers)
			res = json.loads(res)
			self.buffer = res[self.attr]
			self.cursor = self.data['after'] = res.get('pagination', {}).get('cursor')

async def get_info_uncached(username=None, use_fallback=True):
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
	userid = (await get_user(name=username)).id

	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {await get_token()}",
	}
	res = await common.http.request("https://api.twitch.tv/helix/users", {"id": userid}, headers=headers)
	user_data = json.loads(res)['data'][0]

	# Attempt to get the channel data from /streams
	# If this succeeds, it means the channel is currently live
	res = await common.http.request("https://api.twitch.tv/helix/streams", {"user_id": userid}, headers=headers)
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
	res = await common.http.request("https://api.twitch.tv/helix/channels", {"broadcaster_id": userid}, headers=headers)
	channel_data = json.loads(res)['data'][0]
	user_data.update(channel_data)
	user_data['live'] = False
	return user_data

@utils.cache(GAME_CHECK_INTERVAL, params=[0, 1])
async def get_info(username=None, use_fallback=True):
	return await get_info_uncached(username, use_fallback=use_fallback)

Game = collections.namedtuple('Game', ['id', 'name'])
async def get_game(id=None, name=None, get_missing=True):
	"""
	Get game information by id or name (one must be provided).

	If get_missing is set to False, will return None if the game is not
	already in the database.
	"""
	engine, metadata = postgres.get_engine_and_metadata()
	games = metadata.tables["games"]
	with engine.connect() as conn:
		query = sqlalchemy.select(games.c.id, games.c.name)
		if id is not None:
			query = query.where(games.c.id == id)
			data = {'id': id}
		elif name is not None:
			query = query.where(games.c.name == name)
			data = {'name': name}
		else:
			raise ValueError("Pass at least one of name or id")

		row = conn.execute(query).first()
		if row:
			return Game(*row)

		if get_missing:
			headers = {
				'Client-ID': config['twitch_clientid'],
				'Authorization': f"Bearer {await get_token()}",
			}
			res = await common.http.request("https://api.twitch.tv/helix/games", data=data, headers=headers)
			game = json.loads(res)['data'][0]
			insert_query = insert(games)
			insert_query = insert_query.on_conflict_do_update(
				index_elements=[games.c.id],
				set_={
					'name': insert_query.excluded.name,
				},
			)
			conn.execute(insert_query, {
				"id": game["id"],
				"name": game["name"],
			})
			conn.commit()

			return Game(int(game["id"]), game["name"])

async def get_game_playing(username=None):
	"""
	Get the game information for the game the stream is currently playing
	"""
	channel_data = await get_info(username, use_fallback=False)
	if not channel_data or not channel_data['live']:
		return None
	if channel_data.get('game_id'):
		return Game(int(channel_data['game_id']), channel_data['game_name'])
	return None

async def is_stream_live(username=None):
	"""
	Get whether the stream is currently live
	"""
	channel_data = await get_info(username, use_fallback=False)
	return channel_data and channel_data['live']

async def get_streams_followed():
	"""
	Get a list of all currently-live streams on channels followed by us.

	See:
	https://dev.twitch.tv/docs/v5/reference/streams/#get-followed-streams
	"""
	userid, username, display_name, token = await get_user(name=config["username"])
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {token}",
	}
	return [stream async for stream in get_paginated("https://api.twitch.tv/helix/streams/followed", data={"user_id": userid}, headers=headers)]

async def get_video(videoid):
	"""
	Get the details for a specific VOD.

	Parameter can be passed with or without the 'v' prefix (ie '123' or 'v123').

	See:
	https://dev.twitch.tv/docs/api/reference#get-videos
	"""
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {await get_token()}",
	}
	data = await common.http.request("https://api.twitch.tv/helix/videos", {"id": videoid.lstrip('v')}, headers=headers)
	return json.loads(data)["data"][0]

async def get_videos(channel=None, limit=10, broadcasts=False):
	"""
	Get the details for the latest videos (either broadcasts or highlights) from a channel.

	See:
	https://dev.twitch.tv/docs/api/reference#get-videos
	"""
	channelid = (await get_user(name=channel or config["channel"])).id
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {await get_token()}",
	}
	data = await common.http.request("https://api.twitch.tv/helix/videos", headers=headers, data={
		"user_id": channelid,
		"first": str(limit),
		"sort": "time",
		"type": "archive" if broadcasts else "highlight",
	})
	return json.loads(data)["data"]

async def get_followers(channel=None):
	"""
	Get an asynchronous list of all the followers of a given channel.

	See:
	https://dev.twitch.tv/docs/api/reference/#get-channel-followers
	"""
	channelid = (await get_user(name=channel or config["channel"])).id
	url = "https://api.twitch.tv/helix/channels/followers"
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {await get_token()}",
	}
	async for follower in get_paginated(url, data={"broadcaster_id": channelid}, headers=headers):
		yield follower

async def ban_user(channel_id, user_id, reason=None, duration=None):
	"""
	Ban a user from chat.

	See:
	https://dev.twitch.tv/docs/api/reference/#ban-user
	"""
	moderator = await get_user(name=config['username'], get_missing=False)

	url = "https://api.twitch.tv/helix/moderation/bans?broadcaster_id=%s&moderator_id=%s" % (
		channel_id,
		moderator.id,
	)

	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {moderator.token}",
	}

	data = {
		"user_id": str(user_id),
	}
	if reason is not None:
		data["reason"] = reason
	if duration is not None:
		data["duration"] = duration

	data = await common.http.request(url, method="POST", headers=headers, data={"data": data}, asjson=True)

	return json.loads(data)['data']

async def send_whisper(target, message):
	"""
	Send a whisper message.

	See:
	https://dev.twitch.tv/docs/api/reference/#send-whisper
	"""

	from_user = await get_user(name=config['username'], get_missing=False)
	to_user = await get_user(name=target)

	url = 'https://api.twitch.tv/helix/whispers?from_user_id=%s&to_user_id=%s' % (
		from_user.id,
		to_user.id,
	)

	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {from_user.token}",
	}

	await common.http.request(url, method="POST", headers=headers, data={"message": message}, asjson=True)

async def get_number_of_chatters(channel=None, user=None):
	"""
	Get the number of users currently in chat.

	See:
	https://dev.twitch.tv/docs/api/reference/#get-chatters
	"""
	broadcaster = await get_user(name=channel or config["channel"])
	moderator = await get_user(name=user or config['username'])
	url = "https://api.twitch.tv/helix/chat/chatters"
	data = {
		"broadcaster_id": broadcaster.id,
		"moderator_id": moderator.id,
		# Since we only get the count limit the number of users we fetch
		"limit": "1",
	}
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {moderator.token}",
	}

	data = await common.http.request(url, data=data, headers=headers)

	return json.loads(data)["total"]


async def create_eventsub_subscription(topic, version, condition, transport, token):
	"""
	Create an EventSub subscription.

	See:
	https://dev.twitch.tv/docs/api/reference/#create-eventsub-subscription
	"""
	url = "https://api.twitch.tv/helix/eventsub/subscriptions"
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {token}",
	}
	data = await common.http.request(url, method="POST", headers=headers, asjson=True, data={
		"type": topic,
		"version": version,
		"condition": condition,
		"transport": transport,
	})
	return json.loads(data)["data"][0]
