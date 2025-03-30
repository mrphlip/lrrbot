import asyncio

import irc.client
import sqlalchemy

from common import utils, twitch
from common.config import config

INITIAL_DELAY = 15
CHECK_INTERVAL = 60

class BroadcastConnection:
	"""
	A fake `irc.client.ServerConnection` for broadcasting to all chats.
	"""
	def __init__(self, timers):
		self.timers = timers

	def privmsg(self, target, message):
		self.timers.loop.create_task(self.timers.broadcast(message)).add_done_callback(utils.check_exception)


class Timers:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop

		self.loop.call_later(INITIAL_DELAY, self.schedule_check)

	def schedule_check(self):
		self.loop.call_later(CHECK_INTERVAL, self.schedule_check)
		asyncio.ensure_future(self.check_timers(), loop=self.loop).add_done_callback(utils.check_exception)

	async def broadcast(self, message):
		if await twitch.is_stream_live():
			self.lrrbot.connection.privmsg("#" + config['channel'], message)

		if self.lrrbot.youtube_chat:
			await self.lrrbot.youtube_chat.broadcast_message(message)

	async def check_timers(self):
		timers = self.lrrbot.metadata.tables['timers']
		with self.lrrbot.engine.begin() as conn:
			expired_timers = conn.execute(
				timers.update()
					.values(last_run=sqlalchemy.func.current_timestamp())
					.where(
						(timers.c.last_run == None) |
						(timers.c.last_run + timers.c.interval < sqlalchemy.func.current_timestamp())
					)
					.returning(timers.c.mode, timers.c.message)
			).all()
			conn.commit()

		for mode, message in expired_timers:
			if mode == 'command':
				if not message.startswith(config['commandprefix']):
					message = config['commandprefix'] + message

				event = irc.client.Event(
					'pubmsg',
					'lrrbot',
					"#" + config['channel'],
					[message],
					{
						'display-name': 'LRRbot',
						'mod': True,
						'subscriber': True,
					}
				)

				self.lrrbot.commands.on_message(BroadcastConnection(self), event)

			elif mode == 'message':
				await self.broadcast(message)
