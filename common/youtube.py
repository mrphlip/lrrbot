import csv
import datetime
import json
from urllib.error import HTTPError

import pytz
import sqlalchemy

from common import http
from common import postgres
from common import utils
from common.account_providers import ACCOUNT_PROVIDER_YOUTUBE
from common.config import config

class TokenMissingError(Exception):
	def __init__(self, channel_id):
		super().__init__(f"No token found for user {channel_id}")
		self.channel_id = channel_id

token_cache = {}
async def get_token(channel_id):
	global token_cache

	if channel_id in token_cache and token_cache[channel_id]['expires'] > datetime.datetime.now(pytz.utc):
		return token_cache[channel_id]['token']

	engine, metadata = postgres.get_engine_and_metadata()
	accounts = metadata.tables["accounts"]
	with engine.connect() as conn:
		account = conn.execute(
			sqlalchemy.select(accounts.c.id, accounts.c.access_token, accounts.c.refresh_token, accounts.c.token_expires_at)
			.where(accounts.c.provider == ACCOUNT_PROVIDER_YOUTUBE)
			.where(accounts.c.provider_user_id == channel_id)
		).one_or_none()

		if account is None or account.access_token is None:
			raise TokenMissingError(channel_id)

		if account.token_expires_at > datetime.datetime.now(pytz.utc):
			token_cache[channel_id] = {'token': account.access_token, 'expires': account.token_expires_at}
			return account.access_token

		access_token, refresh_token, token_expires_at = await request_token('refresh_token', refresh_token=account.refresh_token)

		update = {
			'access_token': access_token,
			'token_expires_at': token_expires_at,
		}
		if refresh_token:
			update['refresh_token'] = refresh_token

		conn.execute(accounts.update().where(accounts.c.id == account.id), update)
		conn.commit()

		token_cache[channel_id] = {'token': access_token, 'expires': token_expires_at}

		return access_token

async def request_token(grant_type, **data):
	data['grant_type'] = grant_type
	data['client_id'] = config['youtube_client_id']
	data['client_secret'] = config['youtube_client_secret']

	data = await http.request('https://oauth2.googleapis.com/token', method='POST', data=data)
	data = json.loads(data)

	access_token = data['access_token']
	refresh_token = data.get('refresh_token')
	expiry = datetime.datetime.now(pytz.utc) + datetime.timedelta(seconds=data['expires_in'])

	return access_token, refresh_token, expiry

async def get_my_channel(access_token, parts=['snippet']):
	"""
	Get the authorized user's channel.

	Docs: https://developers.google.com/youtube/v3/docs/channels/list
	"""
	data = await http.request(
		'https://youtube.googleapis.com/youtube/v3/channels',
		data={'part': ','.join(parts), 'mine': 'true'},
		headers={'Authorization': f'Bearer {access_token}'})
	return json.loads(data)['items'][0]

async def get_paginated(url, data, headers):
	while True:
		response = json.loads(await http.request(url, data=data, headers=headers))
		for item in response['items']:
			yield item
		if next_page_token := response.get('nextPageToken'):
			data['pageToken'] = next_page_token
		else:
			break

async def get_channel(requester, channel_id, parts=['snippet']):
	"""
	Get a channel by ID.

	Docs: https://developers.google.com/youtube/v3/docs/channels/list
	"""
	data = await http.request(
		'https://youtube.googleapis.com/youtube/v3/channels',
		data={'part': ','.join(parts), 'id': channel_id},
		headers={'Authorization': f'Bearer {await get_token(requester)}'},
	)
	return json.loads(data)['items'][0]

async def get_user_broadcasts(channel_id, parts=['snippet']):
	"""
	Get the user's broadcasts.

	Docs: https://developers.google.com/youtube/v3/live/docs/liveBroadcasts/list
	"""
	headers = {'Authorization': f'Bearer {await get_token(channel_id)}'}
	broadcasts = get_paginated(
		'https://youtube.googleapis.com/youtube/v3/liveBroadcasts',
		{'part': ','.join(parts), 'mine': 'true'},
		headers,
	)
	async for broadcast in broadcasts:
		yield broadcast

async def get_chat_page(requester, live_chat_id, page_token=None, parts=['snippet', 'authorDetails'], language='en'):
	"""
	Get live chat messages for a specific chat.

	Docs: https://developers.google.com/youtube/v3/live/docs/liveChatMessages/list
	"""
	data = {'liveChatId': live_chat_id, 'part': ','.join(parts), 'maxResults': '2000', 'hl': language}
	if page_token:
		data['pageToken'] = page_token
	headers = {'Authorization': f'Bearer {await get_token(requester)}'}
	return json.loads(await http.request('https://www.googleapis.com/youtube/v3/liveChat/messages', data=data, headers=headers))

def check_message_length(message, max_len = 200):
	# The limit is documented as '200 characters'.
	length = len(message.encode('utf-16-le')) // 2
	return length <= max_len

def trim_message(message, max_len = 200):
	max_len_bytes = max_len * 2
	encoded = message.encode('utf-16-le')
	if len(encoded) > max_len_bytes:
		return encoded[:max_len_bytes - 2].decode('utf-16-le') + "\u2026"
	else:
		return message

async def send_chat_message(requester, chat_id, message):
	"""
	Send a text message to a live chat.

	Returns the created LiveChatMessage object.

	Docs: https://developers.google.com/youtube/v3/live/docs/liveChatMessages/insert
	"""
	headers = {'Authorization': f'Bearer {await get_token(requester)}'}
	return json.loads(await http.request('https://www.googleapis.com/youtube/v3/liveChat/messages?part=snippet', method='POST', asjson=True, headers=headers, data={
		'snippet': {
			'liveChatId': chat_id,
			'type': 'textMessageEvent',
			'textMessageDetails': {
				'messageText': trim_message(message),
			},
		},
	}))

@utils.cache(24 * 60 * 60)
async def get_super_stickers():
	"""
	Get Super Sticker URLs.

	Semi-documented in https://developers.google.com/youtube/v3/live/docs/liveChatMessages#snippet.superStickerDetails.superStickerMetadata.stickerId
	"""
	try:
		data = await http.request('https://youtube.googleapis.com/super_stickers/sticker_ids_to_urls.csv')
		return {row['id']: row['url'] for row in csv.DictReader(data, fieldnames=['id', 'url'])}
	except HTTPError:
		return {}

async def get_playlist_items_page(requester, playlist_id, count=5, parts=['snippet']):
	"""
	Get the first `count` items from a playlist.

	Docs: https://developers.google.com/youtube/v3/docs/playlistItems/list
	"""
	data = json.loads(await http.request(
		'https://www.googleapis.com/youtube/v3/playlistItems',
		data={'part': ','.join(parts), 'playlistId': playlist_id, 'maxResults': count},
		headers={'Authorization': f'Bearer {await get_token(requester)}'},
	))
	return data['items']

async def get_videos(requester, ids, parts=['snippet']):
	"""
	Get multiple videos by ID.

	Docs: https://developers.google.com/youtube/v3/docs/videos/list
	"""
	data = json.loads(await http.request(
		'https://www.googleapis.com/youtube/v3/videos',
		data={'part': ','.join(parts), 'id': ','.join(ids)},
		headers={'Authorization': f'Bearer {await get_token(requester)}'},
	))
	return data['items']

async def ban_user(requester, chat_id, user_id, duration=None):
	"""
	Ban a user from a chat.

	Docs: https://developers.google.com/youtube/v3/live/docs/liveChatBans/insert
	"""
	headers = {'Authorization': f'Bearer {await get_token(requester)}'}
	await http.request('https://www.googleapis.com/youtube/v3/liveChat/bans?part=snippet', method='POST', asjson=True, headers=headers, data={
		'snippet': {
			'liveChatId': chat_id,
			'bannedUserDetails': {
				'channelId': user_id,
			},
			'type': 'permanent' if duration is None else 'temporary',
			'banDurationSeconds': duration,
		},
	})
