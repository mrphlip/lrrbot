import asyncio
import logging

from common import twitch
from common import rpc
from common import utils

log = logging.getLogger(__name__)

class StreamStatus:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop

		self.handle = self.loop.call_later(twitch.GAME_CHECK_INTERVAL, self.schedule)
		self.was_live = bool(twitch.is_stream_live())

	def reschedule(self):
		self.handle.cancel()
		self.schedule()

	def schedule(self):
		asyncio.ensure_future(self.check_stream(), loop=self.loop).add_done_callback(utils.check_exception)

	async def check_stream(self):
		log.debug("Checking stream")
		data = twitch.get_info(use_fallback=False)
		is_live = bool(data and data['live'])

		if is_live and not self.was_live:
			log.debug("Stream is now live")
			await rpc.eventserver.event('stream-up', {}, None)
			await rpc.eris.announcements.stream_up(data)
		elif not is_live and self.was_live:
			log.debug("Stream is now offline")
			await rpc.eventserver.event('stream-down', {}, None)

		self.was_live = is_live

		self.handle = self.loop.call_later(twitch.GAME_CHECK_INTERVAL, self.schedule)
