import irc.client
import irc.schedule
import time

class Scheduler(irc.schedule.DefaultScheduler):
	def __init__(self, loop, callback):
		super().__init__()
		self._loop = loop
		self._callback = callback

	def execute_every(self, period, func):
		super().execute_every(period, func)

		def reschedule():
			self._callback()
			self._loop.call_later(period, reschedule)
		self._loop.call_later(period, reschedule)

	def execute_at(self, when, func):
		super().execute_at(when, func)
		assert isinstance(when, (int, float))
		self._loop.call_at(when - time.time() + self._loop.time(), self._callback)

	def execute_after(self, delay, func):
		super().execute_after(delay, func)
		self._loop.call_later(delay, self._callback)

class AsyncReactor(irc.client.Reactor):
	scheduler_class = Scheduler

	def __init__(self, loop):
		self._loop = loop
		super().__init__(self.on_connect, self.on_disconnect)

	def scheduler_class(self):
		return Scheduler(self._loop, self.process_timeout)

	def on_connect(self, socket):
		self._loop.add_reader(socket, self.process_data, [socket])

	def on_disconnect(self, socket):
		self._loop.remove_reader(socket)

	def process_forever(self):
		raise NotImplementedError
