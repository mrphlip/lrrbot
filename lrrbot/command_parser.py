import asyncio
import logging

import irc.client

from common import utils
from common import command_parser

log = logging.getLogger('command_parser')

class CommandParser(command_parser.CommandParser):
	def __init__(self, lrrbot, loop):
		super().__init__(loop)
		self.lrrbot = lrrbot

		self.lrrbot.reactor.add_global_handler('pubmsg', self.on_message, 99)
		self.lrrbot.reactor.add_global_handler('privmsg', self.on_message, 99)

	def on_message(self, conn, event):
		source = irc.client.NickMask(event.source)
		nick = source.nick.lower()

		# If the message was sent to a channel, respond in the channel
		# If it was sent via PM, respond via PM
		if event.type == "pubmsg":
			respond_to = event.target
		else:
			respond_to = source.nick
		if self.lrrbot.access == "mod" and not self.lrrbot.is_mod(event):
			return
		if self.lrrbot.access == "sub" and not self.lrrbot.is_mod(event) and not self.lrrbot.is_sub(event):
			return
		match = self.get_match(event.arguments[0])
		if match is not None:
			log.info("Command from %s: %s " % (source.nick, event.arguments[0]))
			proc, params = match
			asyncio.ensure_future(proc(self.lrrbot, conn, event, respond_to, *params), loop=self.loop).add_done_callback(utils.check_exception)
