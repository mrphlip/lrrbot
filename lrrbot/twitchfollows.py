import asyncio

from common import rpc
from common import storm
from common import twitch
from common import utils
import dateutil.parser

FOLLOWER_CHECK_DELAY = 60

class TwitchFollows:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop

		self.last_timestamp = None
		self.last_users = set()
		self.schedule_check()

	def schedule_check(self):
		asyncio.ensure_future(self.check_follows(), loop=self.loop).add_done_callback(utils.check_exception)
		self.loop.call_later(FOLLOWER_CHECK_DELAY, self.schedule_check)

	async def check_follows(self):
		if self.last_timestamp is None:
			async for follower in twitch.get_followers():
				if self.last_timestamp is None or self.last_timestamp == follower['followed_at']:
					self.last_timestamp = follower['followed_at']
					self.last_users.add(follower['user_id'])
				else:
					break
		else:
			last_users = self.last_users
			self.last_users = set()
			events = []

			async for follower in twitch.get_followers():
				if follower['followed_at'] >= self.last_timestamp:
					if follower['user_id'] not in last_users:
						events.append((
							follower['user_name'],
							follower['followed_at'],
						))
						self.last_users.add(follower['user_id'])
				else:
					break

			if not events:
				self.last_users = last_users

			for name, timestamp in events[::-1]:
				self.last_timestamp = timestamp
				timestamp = dateutil.parser.parse(timestamp)
				event = {
					'name': name,
					'count': storm.increment(self.lrrbot.engine, self.lrrbot.metadata, 'twitch-follow'),
				}
				await rpc.eventserver.event('twitch-follow', event, timestamp)
