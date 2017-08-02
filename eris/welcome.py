import asyncio

from common.config import config
from common import utils

class Welcome:
	def __init__(self, eris, signals):
		self.eris = eris
		self.signals = signals

		self.signals.signal("member_join").connect(self.on_member_join)

	def on_member_join(self, eris, member):
		if member.server.id == config["discord_serverid"]:
			asyncio.ensure_future(self.welcome(member), loop=self.eris.loop).add_done_callback(utils.check_exception)

	async def welcome(self, member):
		await self.eris.send_message(member.server.default_channel, "Welcome to the LoadingReadyRun Discord server, %s! Check the pinned messages for more information." % member.mention)
