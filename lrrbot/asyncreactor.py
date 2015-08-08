import asyncio
import irc.client

class AsyncReactor(irc.client.Reactor):
	def __init__(self, loop):
		self.loop = loop
		super().__init__(self.on_connect, self.on_disconnect, self.on_schedule)

	def on_connect(self, socket):
		self.loop.add_reader(socket, self.process_data, [socket])

	def on_disconnect(self, socket):
		self.loop.remove_reader(socket)

	def on_schedule(self, delay):
		self.loop.call_later(delay, self.process_timeout)

	def process_forever(self):
		raise NotImplementedError
