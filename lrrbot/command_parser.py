import asyncio
import logging
import re

import irc.client

from common import utils
from common.config import config

log = logging.getLogger('command_parser')

class CommandParser:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop

		self.commands = {}
		self.command_groups = {}
		self.re_botcommand = None

		self.lrrbot.reactor.add_global_handler('pubmsg', self.on_message, 99)
		self.lrrbot.reactor.add_global_handler('privmsg', self.on_message, 99)

	def add(self, pattern, function):
		if not asyncio.iscoroutinefunction(function):
			function = asyncio.coroutine(function)
		pattern = pattern.replace(" ", r"(?:\s+)")
		self.commands[pattern] = {
			"groups": re.compile(pattern, re.IGNORECASE).groups,
			"func": function,
		}
		self.re_botcommand = None

	def remove(self, pattern):
		del self.commands[pattern.replace(" ", r"(?:\s+)")]
		self.re_botcommand = None

	def decorator(self, pattern):
		def wrapper(function):
			self.add(pattern, function)
			return function
		return wrapper

	def compile(self):
		self.re_botcommand = r"^\s*%s\s*(?:" % re.escape(config["commandprefix"])
		self.re_botcommand += "|".join(map(lambda re: '(%s)' % re, self.commands))
		self.re_botcommand += r")\s*$"
		self.re_botcommand = re.compile(self.re_botcommand, re.IGNORECASE)

		i = 1
		for val in self.commands.values():
			self.command_groups[i] = (val["func"], i+val["groups"])
			i += 1 + val["groups"]

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
		if self.re_botcommand is None:
			self.compile()
		command_match = self.re_botcommand.match(event.arguments[0])
		if command_match:
			command = command_match.group(command_match.lastindex)
			log.info("Command from %s: %s " % (source.nick, command))
			proc, end = self.command_groups[command_match.lastindex]
			params = command_match.groups()[command_match.lastindex:end]
			asyncio.async(proc(self.lrrbot, conn, event, respond_to, *params), loop=self.loop).add_done_callback(utils.check_exception)
