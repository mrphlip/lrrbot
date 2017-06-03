import time

import irc.client

from common.config import config

TIMEOUT = 90

class JoinFilter:
	def __init__(self, lrrbot, loop):
		self.loop = loop
		self.lrrbot = lrrbot

		self.bot_start = None
		self.last_parts = {}

		self.lrrbot.reactor.add_global_handler('join', self.filter_joins, 20)
		self.lrrbot.reactor.add_global_handler('part', self.on_part, 20)
		self.lrrbot.reactor.scheduler.execute_every(TIMEOUT, self.remove_stale_entries)

	def filter_joins(self, conn, event):
		source = irc.client.NickMask(event.source)
		if source.nick == config['username']:
			self.bot_start = time.time()
		else:
			now = time.time()
			last_part = self.last_parts.pop(source.nick, 0)
			if now - self.bot_start <= TIMEOUT:
				return "NO MORE"
			if now - last_part <= TIMEOUT:
				return "NO MORE"

	def on_part(self, conn, event):
		source = irc.client.NickMask(event.source)
		self.last_parts[source.nick] = time.time()

	def remove_stale_entries(self):
		now = time.time()
		for nick, last_part in list(self.last_parts.items()):
			if now - last_part > TIMEOUT:
				del self.last_parts[nick]
