import logging

from common.config import config
from common import eventsub
from common import rpc
from common import twitch

log = logging.getLogger(__name__)

class StreamStatus:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop

		self.lrrbot.eventsub[config['channel']].connected.connect(self.subscribe)

	async def subscribe(self, session: eventsub.Session):
		condition = {"broadcaster_user_id": session.user.id}
		await session.listen("stream.online", "1", condition, self.stream_online)
		await session.listen("stream.offline", "1", condition, self.stream_offline)

	async def stream_online(self, event):
		log.debug("Stream is now live")

		await self.lrrbot.on_stream_online()

		await rpc.eventserver.event('stream-up', {}, None)
		await rpc.eris.announcements.stream_up()

	async def stream_offline(self, event):
		log.debug("Stream is now offline")

		await self.lrrbot.on_stream_offline()

		await rpc.eventserver.event('stream-down', {}, None)
