import re
from common.config import config
from common import utils

class CommandParser:
	def __init__(self, loop):
		self.loop = loop

		self.commands = {}
		self.command_groups = {}
		self.re_botcommand = None

	def add(self, pattern, function):
		function = utils.wrap_as_coroutine(function)
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

	def get_match(self, message):
		if self.re_botcommand is None:
			self.compile()
		command_match = self.re_botcommand.match(message)
		if command_match:
			command = command_match.group(command_match.lastindex)
			proc, end = self.command_groups[command_match.lastindex]
			params = command_match.groups()[command_match.lastindex:end]
			return proc, params
		return None
