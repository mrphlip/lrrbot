import time
import logging

import irc.client

from common.config import config

log = logging.getLogger('lrrbot')

TIMEOUT = 90

class JoinFilter:
	def __init__(self, lrrbot, loop):
		self.loop = loop
		self.lrrbot = lrrbot

		self.bot_start = None
		self.last_parts = {}

		self.lrrbot.reactor.add_global_handler('join', self.filter_joins, 20)
		self.lrrbot.reactor.add_global_handler('part', self.on_part, 20)
		self.lrrbot.reactor.execute_every(period=TIMEOUT, function=self.remove_stale_entries)

	def filter_joins(self, conn, event):
		source = irc.client.NickMask(event.source)
		if source.nick == config['username']:
			self.bot_start = time.time()
		else:
			now = time.time()
			last_part = self.last_parts.pop(source.nick, 0)
			if now - self.bot_start <= TIMEOUT:
				log.info("Filtered JOIN from %s because it was %f seconds from bot start", source.nick, now - self.bot_start)
				return "NO MORE"
			if now - last_part <= TIMEOUT:
				log.info("Filtered JOIN from %s because it was %f seconds from last PART", source.nick, now - last_part)
				return "NO MORE"

	def on_part(self, conn, event):
		source = irc.client.NickMask(event.source)
		self.last_parts[source.nick] = time.time()

	def remove_stale_entries(self):
		now = time.time()
		for nick, last_part in list(self.last_parts.items()):
			if now - last_part > TIMEOUT:
				del self.last_parts[nick]
