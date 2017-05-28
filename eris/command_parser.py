import asyncio
import logging

from common import utils

from common import command_parser

log = logging.getLogger("eris.command_parser")

class CommandParser(command_parser.CommandParser):
	def __init__(self, eris, signals, engine, metadata):
		super().__init__(eris.loop)
		self.eris = eris
		self.signals = signals
		self.engine = engine
		self.metadata = metadata

		self.signals.signal('message').connect(self.on_message)

		self.command = self.decorator

	def on_message(self, eris, message):
		if message.author == eris.user:
			# Stop infinite message loops.
			return

		match = self.get_match(message.content)
		if match is not None:
			log.info("Command from %s#%s: %s " % (message.author.name, message.author.id, message.content))
			proc, params = match
			asyncio.ensure_future(proc(self, message, *params), loop=self.eris.loop).add_done_callback(utils.check_exception)
