import asyncio
import common.rpc
import common.storm
from common import utils

import logging

log = logging.getLogger('cheer')

class TwitchCheer:
	LEVELS = [(10000, 'red'), (5000, 'blue'), (1000, 'green'), (100, 'purple'), (1, 'gray')]

	def __init__(self, lrrbot, loop):
		self.loop = loop
		self.lrrbot = lrrbot
		self.lrrbot.reactor.add_global_handler("pubmsg", self.check_cheer, 100)

	def check_cheer(self, conn, event):
		if event.tags.get('bits'):
			asyncio.ensure_future(self.on_cheer(event)).add_done_callback(utils.check_exception)

	async def on_cheer(self, event):
		log.info("Got %d bits from %s", event.tags['bits'], event.tags['display-name'])
		eventname = 'twitch-cheer'
		data = {
			'name': event.tags['display-name'],
			'message': event.arguments[0],
			'messagehtml': await self.lrrbot.chatlog.format_message(event.arguments[0], event.tags.get('emotes'), event.tags.get('emoteset', []), cheer=True),
			'bits': event.tags['bits'],
			'count': common.storm.increment(self.lrrbot.engine, self.lrrbot.metadata, eventname, event.tags['bits']),
			'level': self.get_level(event.tags['bits']),
		}

		await common.rpc.eventserver.event(eventname, data, None)

	@classmethod
	def get_level(cls, bits):
		for cutoff, level in cls.LEVELS:
			if bits >= cutoff:
				return level
		else:
			return "gray"
