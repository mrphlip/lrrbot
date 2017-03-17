import asyncio
import logging

from common import utils

from lrrbot.command_parser import CommandParser as IrcCommandParser

log = logging.getLogger("eris.command_parser")

class CommandParser(IrcCommandParser):
	def __init__(self, eris, signals, engine, metadata):
		self.eris = eris
		self.signals = signals
		self.engine = engine
		self.metadata = metadata

		self.commands = {}
		self.command_groups = {}
		self.re_botcommand = None

		self.signals.signal('message').connect(self.on_message)

		self.command = self.decorator

	def on_message(self, eris, message):
		if message.author == eris.user:
			# Stop infinite message loops.
			return

		if self.re_botcommand is None:
			self.compile()

		command_match = self.re_botcommand.match(message.content)
		if command_match:
			command = command_match.group(command_match.lastindex)
			log.info("Command from %s#%s: %s " % (message.author.name, message.author.id, command))
			proc, end = self.command_groups[command_match.lastindex]
			params = command_match.groups()[command_match.lastindex:end]
			asyncio.ensure_future(proc(self, message, *params), loop=self.eris.loop).add_done_callback(utils.check_exception)
