import asyncio
import datetime
import pytz

import discord

from common.config import config
from common import utils

import logging
log = logging.getLogger('eris.channel_reaper')

class ChannelReaper:
	def __init__(self, eris, signals):
		self.eris = eris
		self.signals = signals

		self.timer_scheduled = False
		self.signals.signal('ready').connect(self.schedule_timer)

	@utils.swallow_errors
	async def reap_channels(self):
		for channel in list(self.eris.get_server(config['discord_serverid']).channels):
			if channel.type != discord.ChannelType.voice:
				continue
			if not channel.name.startswith(config['discord_temp_channel_prefix']):
				continue
			channel_age = datetime.datetime.now(pytz.utc) - pytz.utc.localize(channel.created_at)
			if channel_age > datetime.timedelta(minutes=15) and len(channel.voice_members) == 0:
				log.info("Deleting %r (%r) due to no activity.", channel.name, channel.id)
				await self.eris.delete_channel(channel)

	def schedule_reap_channels(self):
		asyncio.ensure_future(self.reap_channels(), loop=self.eris.loop).add_done_callback(utils.check_exception)
		self.eris.loop.call_later(60, self.schedule_reap_channels)

	def schedule_timer(self, eris):
		if not self.timer_scheduled:
			self.timer_scheduled = True
			self.schedule_reap_channels()
