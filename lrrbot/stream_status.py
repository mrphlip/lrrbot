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

		self.handle = None
		self.was_live = bool(twitch.is_stream_live())
		self.schedule()

	def reschedule(self):
		if self.handle is not None:
			self.handle.cancel()
			self.handle = None
		self.start_check_stream()

	def schedule(self):
		if self.handle is None:
			self.handle = self.loop.call_later(twitch.GAME_CHECK_INTERVAL, self.start_check_stream)

	def start_check_stream(self):
		self.handle = None
		asyncio.ensure_future(self.check_stream(), loop=self.loop).add_done_callback(utils.check_exception)

	async def check_stream(self):
		log.debug("Checking stream")
		data = twitch.get_info(use_fallback=False)
		is_live = bool(data and data['live'])

		if is_live and not self.was_live:
			log.debug("Stream is now live")
			self.was_live = True
			await rpc.eventserver.event('stream-up', {}, None)
			await rpc.eris.announcements.stream_up(data)
		elif not is_live and self.was_live:
			log.debug("Stream is now offline")
			self.was_live = False
			await rpc.eventserver.event('stream-down', {}, None)

		self.schedule()
