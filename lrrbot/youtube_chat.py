import asyncio
import datetime
import functools
import logging
from urllib.error import HTTPError

import irc.client

import common.rpc
from common import utils, state, storm, slack, time
from common import youtube
from common.config import config

log = logging.getLogger(__name__)

BROADCAST_CHECK_DELAY = 5 * 60
# The daily quota for the YouTube Data API is 10,000 units. Each `LiveChatMessages: list` is 5 units.
# So the limit is 10_000 / 5 / 24 / 60 ≈ 1.4 requests/minute. Further limit it to once every 75 seconds
# so we stay under the 80% alert threshold.
MIN_POLL_DELAY = 75.0
# The card viewer spams the chat with a lot of messages that eat up most of the quota.
CARD_VIEWER_POLL_DELAY_MULTIPLIER = 5.0
GIFT_CLEANUP_INTERVAL = 240
PAGE_TOKEN_STATE_KEY = 'lrrbot.youtube_chat.%s.next_page_token'
CHANNEL_PREFIX = '&youtube:'

class YoutubeChatConnection:
	"""
	A fake `irc.client.ServerConnection` for bridging to YouTube's chat system.
	"""
	def __init__(self, loop):
		self.loop = loop

	def privmsg(self, target, message):
		if not target.startswith(CHANNEL_PREFIX):
			log.debug('Not sending a private message to %s: %s', target, message)
			return
		chat_id = target.removeprefix(CHANNEL_PREFIX)
		log.debug('Sending message to %s: %s', chat_id, message)
		self.loop.create_task(youtube.send_chat_message(config['youtube_bot_id'], chat_id, message)).add_done_callback(utils.check_exception)

class YoutubeChat:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop
		self.chats = {}
		self.pending_gifts = {}
		self.last_ban = {}
		self.connection = YoutubeChatConnection(loop)

		self.uploads_playlists = {}
		self.seen_videos = set()

		self.schedule_check()

	async def broadcast_message(self, message):
		for chat_id, chat in self.chats.items():
			if await self.is_stream_live(chat['video_id']):
				await youtube.send_chat_message(config['youtube_bot_id'], chat_id, message)

	@utils.cache(period=5 * 60, params=['video_id'])
	async def is_stream_live(self, video_id):
		videos = await youtube.get_videos(config['youtube_bot_id'], [video_id], parts=['snippet'])
		if videos:
			return videos[0].get('snippet', {}).get('liveBroadcastContent', 'none') == 'live'
		return False

	def schedule_check(self):
		asyncio.ensure_future(self.check_broadcasts(), loop=self.loop).add_done_callback(utils.check_exception)
		self.loop.call_later(BROADCAST_CHECK_DELAY, self.schedule_check)

	async def check_broadcasts(self):
		async for video_id, chat_id in self.get_new_chats():
			task = self.loop.create_task(self.process_chat(chat_id))
			task.add_done_callback(functools.partial(self.on_chat_done, chat_id))
			self.chats[chat_id] = {
				'task': task,
				'video_id': video_id,
				'messages': {},
			}

	async def get_new_chats(self):
		for channel_id in config['youtube_channels']:
			try:
				async for video_id, chat_id in self.get_new_chats_from_broadcasts(channel_id):
					yield video_id, chat_id
			except youtube.TokenMissingError:
				async for video_id, chat_id in self.get_new_chats_from_uploads(channel_id):
					yield video_id, chat_id

	async def get_new_chats_from_broadcasts(self, channel_id):
		async for broadcast in youtube.get_user_broadcasts(channel_id, parts=['snippet', 'status']):
			chat_id = broadcast['snippet']['liveChatId']
			if chat_id not in self.chats and broadcast['status']['lifeCycleStatus'] not in {'complete', 'revoked'}:
				log.info('New YouTube chat %s for %r', chat_id, broadcast['snippet']['title'])
				yield broadcast['id'], chat_id

	async def get_new_chats_from_uploads(self, channel_id):
		if self.uploads_playlists.get(channel_id) is None:
			channel = await youtube.get_channel(config['youtube_bot_id'], channel_id, parts=['contentDetails'])
			self.uploads_playlists[channel_id] = channel['contentDetails']['relatedPlaylists']['uploads']

		playlist = await youtube.get_playlist_items_page(config['youtube_bot_id'], self.uploads_playlists[channel_id])
		video_ids = {video['snippet']['resourceId']['videoId'] for video in playlist}
		new_videos = video_ids - self.seen_videos
		self.seen_videos = video_ids

		if new_videos:
			for video in await youtube.get_videos(config['youtube_bot_id'], new_videos, parts=['snippet', 'liveStreamingDetails']):
				if (chat_id := video.get('liveStreamingDetails', {}).get('activeLiveChatId')) and chat_id not in self.chats:
					log.info('New YouTube chat %s for %r', chat_id, video['snippet']['title'])
					yield video['id'], chat_id

	def on_chat_done(self, chat_id, task):
		try:
			task.result()
		except utils.PASSTHROUGH_EXCEPTIONS:
			raise
		except Exception:
			log.exception('Chat task %s failed, restarting', chat_id)

			task = self.loop.create_task(self.process_chat(chat_id))
			task.add_done_callback(functools.partial(self.on_chat_done, chat_id))
			self.chats[chat_id]['task'] = task
			return

		log.info('Chat %s is finished.', chat_id)
		del self.chats[chat_id]
		state.delete(self.lrrbot.engine, self.lrrbot.metadata, PAGE_TOKEN_STATE_KEY % chat_id)

	async def read_chat(self, chat_id):
		state_key = PAGE_TOKEN_STATE_KEY % chat_id
		next_page_token = state.get(self.lrrbot.engine, self.lrrbot.metadata, state_key)
		while True:
			try:
				page = await youtube.get_chat_page(config['youtube_bot_id'], chat_id, page_token=next_page_token)
			except HTTPError as e:
				if e.code == 403 or e.code == 404:
					break
				raise

			for message in page['items']:
				yield message

			if next_page_token := page.get('nextPageToken'):
				state.set(self.lrrbot.engine, self.lrrbot.metadata, state_key, next_page_token)
			else:
				break

			poll_delay = MIN_POLL_DELAY * len(self.chats)
			if self.lrrbot.cardview_yt:
				poll_delay *= CARD_VIEWER_POLL_DELAY_MULTIPLIER

			await asyncio.sleep(max(page.get('pollingIntervalMillis', 0) / 1000, poll_delay))

	async def process_chat(self, chat_id):
		async for message in self.read_chat(chat_id):
			try:
				log.debug('Received message: %s', message)

				# TODO(#1503): send to the real chat log
				self.add_to_log(chat_id, message)

				if message['snippet']['type'] == 'textMessageEvent':
					await self.on_chat_message(chat_id, message)
				elif message['snippet']['type'] == 'newSponsorEvent':
					await self.on_new_member(chat_id, message)
				elif message['snippet']['type'] == 'memberMilestoneChatEvent':
					await self.on_member_milestone(chat_id, message)
				elif message['snippet']['type'] == 'membershipGiftingEvent':
					await self.on_member_gift_start(chat_id, message)
				elif message['snippet']['type'] == 'giftMembershipReceivedEvent':
					await self.on_member_gift_received(chat_id, message)
				elif message['snippet']['type'] == 'superChatEvent':
					await self.on_super_chat(chat_id, message)
				elif message['snippet']['type'] == 'superStickerEvent':
					await self.on_super_sticker(chat_id, message)
				elif message['snippet']['type'] == 'messageDeletedEvent':
					await self.on_message_deleted(chat_id, message)
				elif message['snippet']['type'] == 'userBannedEvent':
					await self.on_user_banned(chat_id, message)
				elif message['snippet']['type'] == 'sponsorOnlyModeStartedEvent':
					await self.on_member_only_enabled(chat_id, message)
				elif message['snippet']['type'] == 'sponsorOnlyModeEndedEvent':
					await self.on_member_only_disabled(chat_id, message)
				elif message['snippet']['type'] == 'tombstone':
					# A tombstone signifies that a message used to exist with this id and publish time,
					# but it has since been deleted.
					pass
				elif message['snippet']['type'] == 'chatEndedEvent':
					# The chat has ended and no more messages can be inserted after this one.
					break
				else:
					log.warning("Unknown message type '%s'", message['snippet']['type'])

			except utils.PASSTHROUGH_EXCEPTIONS:
				raise
			except Exception:
				log.exception('Failed to handle YouTube message')

	def add_to_log(self, chat_id, message):
		if message['snippet']['type'] == 'tombstone':
			return

		author_id = message['authorDetails']['channelId']
		self.chats[chat_id]['messages'].setdefault(author_id, []).append(message)
		self.chats[chat_id]['messages'][author_id] = self.chats[chat_id]['messages'][author_id][-3:]

	def message_tags(self, message):
		badges = []
		if message['authorDetails']['isChatOwner']:
			badges.append('broadcaster/1')
		if message['authorDetails']['isChatSponsor']:
			badges.append('subscriber/1')
		if message['authorDetails']['isChatModerator']:
			badges.append('moderator/1')

		return [
			{'key': 'emotes', 'value': ''},
			{'key': 'badges', 'value': ','.join(badges)},
			{'key': 'display-name', 'value': message['authorDetails']['displayName']},
			{'key': 'id', 'value': message['id']},
			{'key': 'mod', 'value': '1' if message['authorDetails']['isChatModerator'] else '0'},
			{'key': 'room-id', 'value': message['snippet']['liveChatId']},
			{'key': 'mod', 'value': '1' if message['authorDetails']['isChatSponsor'] else '0'},
			{'key': 'user-id', 'value': message['authorDetails']['channelId']},
		]

	def log_chat(self, event):
		self.lrrbot.check_message_tags(self.connection, event)
		self.lrrbot.log_chat(self.connection, event)

	async def on_chat_message(self, chat_id, message):
		"""
		A user has sent a text message.

		Docs: https://developers.google.com/youtube/v3/live/docs/liveChatMessages#snippet.textMessageDetails
		"""

		self.lrrbot.reactor._handle_event(self.connection, irc.client.Event(
			'pubmsg',
			message['authorDetails']['channelId'],
			CHANNEL_PREFIX + chat_id,
			[message['snippet']['textMessageDetails']['messageText']],
			self.message_tags(message),
		))

	async def on_new_member(self, chat_id, message):
		"""
		A new user has sponsored the channel that owns the live chat.

		('Sponsor' is the old term for 'member'.)

		Docs: https://developers.google.com/youtube/v3/live/docs/liveChatMessages#snippet.newSponsorDetails
		"""
		log.info('New member: %r at %s', message['authorDetails']['displayName'], message['snippet']['publishedAt'])

		time = datetime.datetime.fromisoformat(message['snippet']['publishedAt'])

		data = {
			'name': message['authorDetails']['displayName'],
			'channel_id': message['authorDetails']['channelId'],
			'avatar': message['authorDetails']['profileImageUrl'],
			'tier': message['snippet']['newSponsorDetails'].get('memberLevelName'),
			'is_upgrade': message['snippet']['newSponsorDetails'].get('isUpgrade'),
			'count': storm.increment(self.lrrbot.engine, self.lrrbot.metadata, 'youtube-membership'),
		}

		await common.rpc.eventserver.event('youtube-membership', data, time)

		storm_count = common.storm.get_combined(self.lrrbot.engine, self.lrrbot.metadata)
		await youtube.send_chat_message(
			config['youtube_bot_id'], chat_id,
			f"Thanks for becoming a channel member, {data['name']}! (Today's storm count: {storm_count})",
		)

		self.log_chat(irc.client.Event(
			'pubmsg',
			config['notifyuser'],
			CHANNEL_PREFIX + chat_id,
			[message['snippet']['displayMessage']],
			self.message_tags(message),
		))

	async def on_member_milestone(self, chat_id, message):
		"""
		A user has sent a Member Milestone Chat.

		Docs: https://developers.google.com/youtube/v3/live/docs/liveChatMessages#snippet.memberMilestoneChatDetails
		"""
		log.info('New member milestone: %r at %s', message['authorDetails']['displayName'], message['snippet']['publishedAt'])

		time = datetime.datetime.fromisoformat(message['snippet']['publishedAt'])

		data = {
			'name': message['authorDetails']['displayName'],
			'channel_id': message['authorDetails']['channelId'],
			'avatar': message['authorDetails']['profileImageUrl'],
			'tier': message['snippet']['memberMilestoneChatDetails'].get('memberLevelName'),
			'monthcount': message['snippet']['memberMilestoneChatDetails']['memberMonth'],
			'message': message['snippet']['memberMilestoneChatDetails'].get('userComment'),
			'count': storm.increment(self.lrrbot.engine, self.lrrbot.metadata, 'youtube-membership-milestone'),
		}

		await common.rpc.eventserver.event('youtube-membership-milestone', data, time)

		storm_count = common.storm.get_combined(self.lrrbot.engine, self.lrrbot.metadata)
		await youtube.send_chat_message(
			config['youtube_bot_id'], chat_id,
			f"Thanks for being a channel member, {data['name']}! (Today's storm count: {storm_count})",
		)

		self.log_chat(irc.client.Event(
			'pubmsg',
			config['notifyuser'],
			CHANNEL_PREFIX + chat_id,
			[message['snippet']['displayMessage']],
			self.message_tags(message),
		))
		if data['message']:
			self.log_chat(irc.client.Event(
				'pubmsg',
				message['authorDetails']['channelId'],
				CHANNEL_PREFIX + chat_id,
				[data['message']],
				self.message_tags(message),
			))

	async def on_member_gift_start(self, chat_id, message):
		"""
		A user has purchased memberships for other viewers.

		Docs: https://developers.google.com/youtube/v3/live/docs/liveChatMessages#snippet.membershipGiftingDetails
		"""
		log.info('New member gift %s: %r at %s', message['id'], message['authorDetails']['displayName'], message['snippet']['publishedAt'])

		self.pending_gifts[message['id']] = {
			'time': datetime.datetime.fromisoformat(message['snippet']['publishedAt']),
			'name': message['authorDetails']['displayName'],
			'channel_id': message['authorDetails']['channelId'],
			'avatar': message['authorDetails']['profileImageUrl'],
			'count': message['snippet']['membershipGiftingDetails']['giftMembershipsCount'],
			'tier': message['snippet']['membershipGiftingDetails'].get('giftMembershipsLevelName'),
			'members': [],
		}

		# Eventually send out the notification even if we don't get all the `giftMembershipReceivedEvent`s.
		self.loop.call_later(GIFT_CLEANUP_INTERVAL, self.clean_gift, chat_id, message['id'])

		self.log_chat(irc.client.Event(
			'pubmsg',
			config['notifyuser'],
			CHANNEL_PREFIX + chat_id,
			[message['snippet']['displayMessage']],
			self.message_tags(message),
		))

	def clean_gift(self, chat_id, gift_id):
		if gift_id in self.pending_gifts:
			self.loop.create_task(self.on_member_gift_end(chat_id, gift_id)).add_done_callback(utils.check_exception)

	async def on_member_gift_received(self, chat_id, message):
		"""
		A user has received a gift membership.

		Docs: https://developers.google.com/youtube/v3/live/docs/liveChatMessages#snippet.giftMembershipReceivedDetails
		"""
		log.info('Member gift %s received: %r at %s', message['id'], message['authorDetails']['displayName'], message['snippet']['publishedAt'])

		time = datetime.datetime.fromisoformat(message['snippet']['publishedAt'])
		gift_id = message['snippet']['giftMembershipReceivedDetails']['associatedMembershipGiftingMessageId']

		data = {
			'name': message['authorDetails']['displayName'],
			'channel_id': message['authorDetails']['channelId'],
			'avatar': message['authorDetails']['profileImageUrl'],
			'benefactor': self.pending_gifts[gift_id]['name'],
			'tier': message['snippet']['giftMembershipReceivedDetails'].get('memberLevelName'),
			'ismulti': self.pending_gifts[gift_id]['count'] > 1,
			'count': storm.increment(self.lrrbot.engine, self.lrrbot.metadata, 'youtube-membership'),
		}

		await common.rpc.eventserver.event('youtube-membership', data, time)

		self.pending_gifts[gift_id]['members'].append(data)
		if len(self.pending_gifts[gift_id]['members']) >= self.pending_gifts[gift_id]['count']:
			await self.on_member_gift_end(chat_id, gift_id)

		self.log_chat(irc.client.Event(
			'pubmsg',
			config['notifyuser'],
			CHANNEL_PREFIX + chat_id,
			[message['snippet']['displayMessage']],
			self.message_tags(message),
		))

	async def on_member_gift_end(self, chat_id, gift_id):
		data = self.pending_gifts.pop(gift_id)
		time = data.pop('time')
		await common.rpc.eventserver.event('youtube-membership-gift', data, time)

		storm_count = common.storm.get_combined(self.lrrbot.engine, self.lrrbot.metadata)

		if len(data['members']) == 1:
			message = f"Thanks for the gift, {data['name']}! Welcome to {data['members'][0]['name']}! (Today's storm count: {storm_count})",
		else:
			message = f"Thanks for the gift, {data['name']}! Welcome to {', '.join(member['name'] for member in data['members'])}! (Today's storm count: {storm_count})"
			if not youtube.check_message_length(message):
				message = f"Thanks for the gift, {data['name']}! Welcome to all {len(data['members'])} recipients! (Today's storm count: {storm_count})"

		await youtube.send_chat_message(config['youtube_bot_id'], chat_id, message)


	async def on_super_chat(self, chat_id, message):
		"""
		A user has purchased a Super Chat.

		Docs: https://developers.google.com/youtube/v3/live/docs/liveChatMessages#snippet.superChatDetails
		"""
		log.info('New Super Chat: %r at %s', message['authorDetails']['displayName'], message['snippet']['publishedAt'])

		time = datetime.datetime.fromisoformat(message['snippet']['publishedAt'])

		data = {
			'name': message['authorDetails']['displayName'],
			'channel_id': message['authorDetails']['channelId'],
			'avatar': message['authorDetails']['profileImageUrl'],
			'amount': message['snippet']['superChatDetails']['amountDisplayString'],
			'amount_micros': message['snippet']['superChatDetails']['amountMicros'],
			'amount_currency': message['snippet']['superChatDetails']['currency'],
			'level': message['snippet']['superChatDetails']['tier'],
			'message': message['snippet']['superChatDetails'].get('userComment'),
			'count': storm.increment(self.lrrbot.engine, self.lrrbot.metadata, 'youtube-super-chat'),
		}

		await common.rpc.eventserver.event('youtube-super-chat', data, time)

		self.log_chat(irc.client.Event(
			'pubmsg',
			config['notifyuser'],
			CHANNEL_PREFIX + chat_id,
			[message['snippet']['displayMessage']],
			self.message_tags(message),
		))

	async def on_super_sticker(self, chat_id, message):
		"""
		A user has purchased a Super Sticker.

		Docs: https://developers.google.com/youtube/v3/live/docs/liveChatMessages#snippet.superStickerDetails
		"""
		log.info('New Super Sticker: %r at %s', message['authorDetails']['displayName'], message['snippet']['publishedAt'])

		sticker_urls = await youtube.get_super_stickers()

		time = datetime.datetime.fromisoformat(message['snippet']['publishedAt'])

		data = {
			'name': message['authorDetails']['displayName'],
			'channel_id': message['authorDetails']['channelId'],
			'avatar': message['authorDetails']['profileImageUrl'],
			'amount': message['snippet']['superStickerDetails']['amountDisplayString'],
			'amount_micros': message['snippet']['superStickerDetails']['amountMicros'],
			'amount_currency': message['snippet']['superStickerDetails']['currency'],
			'level': message['snippet']['superStickerDetails']['tier'],
			'sticker_id': message['snippet']['superStickerDetails']['superStickerMetadata']['stickerId'],
			'sticker_url': sticker_urls.get(message['snippet']['superStickerDetails']['superStickerMetadata']['stickerId']),
			'alt_text': message['snippet']['superStickerDetails']['superStickerMetadata']['altText'],
			'alt_text_language': message['snippet']['superStickerDetails']['superStickerMetadata']['language'],
			'count': storm.increment(self.lrrbot.engine, self.lrrbot.metadata, 'youtube-super-sticker'),
		}

		await common.rpc.eventserver.event('youtube-super-sticker', data, time)

	def find_message(self, chat_id, message_id):
		for messages in self.chats[chat_id]['messages'].values():
			for message in messages:
				if message['id'] == message_id:
					return message
		return None

	def format_chatlog(self, messages, now):
		attachments = []
		for message in messages:
			message_time = datetime.datetime.fromisoformat(message['snippet']['publishedAt'])
			message_prefix = f"{message_time:%H:%M} ({time.nice_duration(now - message_time)} ago): "
			if display_message := message['snippet'].get('displayMessage'):
				attachments.append({
					'text': slack.escape(message_prefix + display_message)
				})
			elif message['snippet']['type'] == 'textMessageEvent':
				attachments.append({
					'text': slack.escape(message_prefix + message['snippet']['textMessageDetails']['messageText'])
				})
			elif message['snippet']['type'] == 'memberMilestoneChatEvent':
				attachments.append({
					'text': slack.escape(message_prefix + message['snippet']['memberMilestoneChatDetails']['userComment'])
				})
			elif message['snippet']['type'] == 'superChatEvent':
				attachments.append({
					'text': slack.escape(message_prefix + message['snippet']['superChatDetails']['userComment'])
				})
			elif message['snippet']['type'] == 'superStickerEvent':
				attachments.append({
					'text': slack.escape(message_prefix + message['snippet']['superStickerDetails']['superStickerMetadata']['altText'])
				})
		return attachments

	async def on_message_deleted(self, chat_id, message):
		"""
		A message has been deleted by a moderator.

		Docs: https://developers.google.com/youtube/v3/live/docs/liveChatMessages#snippet.messageDeletedDetails
		"""
		now = datetime.datetime.now(config["timezone"])
		deleted_message = self.find_message(chat_id, message['snippet']['messageDeletedDetails']['deletedMessageId'])
		if deleted_message:
			attachments = self.format_chatlog([deleted_message], now)

			await slack.send_message(
				f"[YT] {slack.escape(deleted_message['authorDetails']['displayName'])} had a message deleted by {slack.escape(message['authorDetails']['displayName'])}.",
				attachments=attachments,
			)
		else:
			await slack.send_message(f"[YT] {slack.escape(message['authorDetails']['displayName'])} deleted a message.")

	async def on_user_banned(self, chat_id, message):
		"""
		A user has been banned by a moderator.

		Docs: https://developers.google.com/youtube/v3/live/docs/liveChatMessages#snippet.userBannedDetails
		"""
		now = datetime.datetime.now(config["timezone"])
		user = message['snippet']['userBannedDetails']['bannedUserDetails']
		mod = message['authorDetails']
		same_user = self.last_ban.get(chat_id) == user['channelId']
		if message['snippet']['userBannedDetails']['banType'] == 'temporary':
			duration = datetime.timedelta(seconds=int(message['snippet']['userBannedDetails']['banDurationSeconds']))
			if not same_user:
				message = f"[YT] {user['displayName']} was timed out for {time.nice_duration(duration, 0)} by {mod['displayName']}."
			else:
				message = f"[YT] {user['displayName']} was also timed out for {time.nice_duration(duration, 0)} by {mod['displayName']}."
		else:
			if not same_user:
				message = f"[YT] {user['displayName']} was banned by {mod['displayName']}."
			else:
				message = f"[YT] {user['displayName']} was also banned by {mod['displayName']}."

		if same_user:
			attachments = self.format_chatlog(self.chats[chat_id]['messages'].get(user['channelId'], []), now)
		else:
			attachments = []

		await slack.send_message(slack.escape(message), attachments=attachments)

		self.last_ban[chat_id] = user['channelId']

	async def on_member_only_enabled(self, chat_id, message):
		"""
		The chat has entered members-only mode.
		"""
		await slack.send_message(slack.escape(f"[YT] {message['authorDetails']['displayName']} has enabled members-only mode."))

	async def on_member_only_disabled(self, chat_id, message):
		"""
		The chat is no longer in members-only mode.
		"""

		await slack.send_message(slack.escape(f"[YT] {message['authorDetails']['displayName']} has disabled members-only mode."))
