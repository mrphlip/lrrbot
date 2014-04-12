#!/usr/bin/python
if __name__ == '__main__':
	import sys
	sys.stderr.write("utils.py accessed directly")
	sys.exit(1)

import flask.json
import queue
import functools
import threading
import oursql
import secrets
import server

def nice_duration(s, detail=1):
	"""
	Convert a duration in seconds to a human-readable duration.

	detail can be:
		0 - Always show to the nearest second
		1 - Show to the nearest minute, unless less than a minute
		2 - Show to the nearest hour, unless less than an hour
	"""
	if s < 0:
		return "-" + nice_duration(-s, detail)
	if s < 60:
		return ["0:%(s)02d", "%(s)ds", "%(s)ds"][detail] % {'s': s}
	m, s = divmod(s, 60)
	if m < 60:
		return ["%(m)d:%(s)02d", "%(m)dm", "%(m)dm"][detail] % {'s': s, 'm': m}
	h, m = divmod(m, 60)
	if h < 24:
		return ["%(h)d:%(m)02d:%(s)02d", "%(h)d:%(m)02d", "%(h)dh"][detail] % {'s': s, 'm': m, 'h': h}
	d, h = divmod(h, 24)
	return ["%(d)dd, %(h)d:%(m)02d:%(s)02d", "%(d)dd, %(h)d:%(m)02d", "%(d)dd, %(h)dh"][detail] % {'s': s, 'm': m, 'h': h, 'd': d}
server.app.add_template_filter(nice_duration)

def with_mysql(func):
	"""Decorator to pass a mysql connection and cursor to a function"""
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		conn = oursql.connect(**secrets.mysqlopts)
		with conn as cur:
			return func(conn, cur, *args, **kwargs)
	return wrapper

def ucfirst(s):
	return s[0].upper() + s[1:]
server.app.add_template_filter(ucfirst)

# Timer code from http://stackoverflow.com/questions/3393612/run-certain-code-every-n-seconds/13151299#13151299
class RepeatedTimer(object):
	"""Run a function regularly after a particular interval of time"""
	def __init__(self, interval, function, *args, **kwargs):
		self._timer     = None
		self.interval   = interval
		self.function   = function
		self.args       = args
		self.kwargs     = kwargs
		self.is_running = False
		self.start()

	def _run(self):
		self.is_running = False
		self.start()
		self.function(*self.args, **self.kwargs)

	def start(self):
		if not self.is_running:
			self._timer = threading.Timer(self.interval, self._run)
			self._timer.start()
			self.is_running = True

	def stop(self):
		self._timer.cancel()
		self.is_running = False

# SSE code based from http://flask.pocoo.org/snippets/116/
class ServerSentEvent(object):
	"""Class to hold an event that should be sent to an SSE client"""
	def __init__(self, data, event=None, id=None):
		self.data = data
		self.event = event
		self.id = id

	def encode(self):
		if not isinstance(self.data, str):
			data = flask.json.dumps(self.data)
		if not data:
			return ""
		lines = []
		for key, val in [('data', data), ('event', self.event), ('id', self.id)]:
			if not val:
				continue
			for line in str(val).split('\n'):
				lines.append("%s: %s" % (key, line))
		return '\n'.join(lines) + "\n\n"

class SSEKeepAlive(ServerSentEvent):
	def __init__(self):
		pass
	def encode(self):
		return ": keepalive\n\n"

class SSEServer(object):
	"""Mediates a server-sent-event channel."""
	def __init__(self, keepalive_timeout=30):
		self._subscriptions = []
		if keepalive_timeout is not None:
			self._timer = RepeatedTimer(keepalive_timeout, self.keepalive)

	def _event_generator(self):
		q = queue.Queue()
		self._subscriptions.append(q)
		try:
			while True:
				ev = q.get()
				yield ev.encode()
		finally:
			self._subscriptions.remove(q)

	def subscribe(self):
		"""
		Called by event consumers, returns the event stream.

		Can be bound directly to a URL:
			app.add_url_rule('/endpoint', view_func=event_server.subscribe)
		or called from a handler:
			@app.route('/endpoint')
			def handler():
				return event_server.subscribe()
		"""
		return flask.Response(self._event_generator(), mimetype="text/event-stream")

	def publish(self, *args, **kwargs):
		"""
		Called by event producers, sends an event to all subscribed clients.
		"""
		if len(args) == 1 and not kwargs and isinstance(args[0], ServerSentEvent):
			event = args[0]
		else:
			event = ServerSentEvent(*args, **kwargs)
		for sub in self._subscriptions[:]:
			sub.put(event)

	def keepalive(self):
		self.publish(SSEKeepAlive())
