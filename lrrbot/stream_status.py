import logging

from common.config import config
from common import twitch
from common import rpc

log = logging.getLogger(__name__)

class StreamStatus:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop

		self.lrrbot.started_signal.connect(self.subscribe)

	async def subscribe(self, sender):
		channel = await twitch.get_user(name=config['channel'])
		await self.lrrbot.eventsub.listen_stream_online(channel.id, self.stream_online)
		await self.lrrbot.eventsub.listen_stream_offline(channel.id, self.stream_offline)

	async def stream_online(self, event):
		log.debug("Stream is now live")

		twitch.get_info.reset_throttle()
		self.lrrbot.get_game_id.reset_throttle()

		await rpc.eventserver.event('stream-up', {}, None)
		await rpc.eris.announcements.stream_up()

	async def stream_offline(self, event):
		log.debug("Stream is now offline")
		await rpc.eventserver.event('stream-down', {}, None)
