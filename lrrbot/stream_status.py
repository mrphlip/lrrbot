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
		self.was_live = None
		self.old_title = ""
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
		data = await twitch.get_info(use_fallback=False)
		if self.old_title != data['title']:
			log.debug("Title changed, parsing for show information")
			self.old_title = data['title']
			if self.lrrbot.find_show(data['title']):
				self.show_override = None
		
		is_live = bool(data and data['live'])
		if self.was_live is None:
			self.was_live = is_live
		elif is_live and not self.was_live:
			log.debug("Stream is now live")
			self.was_live = True
			await rpc.eventserver.event('stream-up', {}, None)
			await rpc.eris.announcements.stream_up(data)
		elif not is_live and self.was_live:
			log.debug("Stream is now offline")
			self.was_live = False
			await rpc.eventserver.event('stream-down', {}, None)

		self.schedule()
