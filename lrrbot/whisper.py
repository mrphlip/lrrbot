import irc.client
import logging
import asyncio

log = logging.getLogger('whisper')

class TwitchWhisper:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop
		self.message_queue = asyncio.Queue(loop=loop)
		self.message_pump_task = asyncio.async(self.message_pump(), loop=loop)

	def stop_task(self):
		self.message_pump_task.cancel()
		return self.message_pump_task

	def add_whisper_handler(self, handler):
		self.lrrbot.reactor.add_global_handler("whisper", handler, 20)

	def whisper(self, target, text):
		log.debug("Enqueue whisper: %r", (target, text))
		self.message_queue.put_nowait((target, text))

	async def message_pump(self):
		# Throttle outgoing messages so we only send 1.5 per second (90 per minute)
		# The limits we know are roughly 3 per second or 100 per minute but allow
		# some buffer area due to network lag
		while True:
			target, text = await self.message_queue.get()
			log.debug("Dequeue whisper: %r", (target, text))
			if self.lrrbot.connection:
				try:
					self.lrrbot.connection.privmsg("#jtv", "/w %s %s" % (target, text))
				except irc.client.ServerNotConnectedError:
					pass
			await asyncio.sleep(2/3)
