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
import socket
import time

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

def sse_send_event(endpoint, event=None, data=None, event_id=None):
	sse_event = {"endpoint": endpoint}
	if event is not None:
		sse_event["event"] = event
	if data is not None:
		sse_event["data"] = data
	if event_id is not None:
		sse_event["id"] = event_id

	sse = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	sse.connect("/tmp/eventserver.sock")
	sse.send(flask.json.dumps(sse_event).encode("utf-8")+b"\n")
	sse.close()

DEFAULT_THROTTLE = 15

class throttle(object):
	"""Prevent a function from being called more often than once per period

	Usage:
	@throttle([period])
	def func(...):
		...

	When called within the throttle period, the last return value is returned,
	for memoisation

	params is a list of parameters to consider as distinct, so calls where the
	watched parameters are the same are throttled together, but calls where they
	are different are throttled separately. Should be a list of ints (for positional
	parameters) and strings (for keyword parameters).
	"""
	def __init__(self, period=DEFAULT_THROTTLE, params=[]):
		self.period = period
		self.watchparams = params
		self.lastrun = {}
		self.lastreturn = {}

	def watchedparams(self, args, kwargs):
		params = []
		for i in self.watchparams:
			if isinstance(i, int):
				param = args[i]
			else:
				param = kwargs[i]
			if isinstance(param, str):
				param = param.lower()
			params.append(param)
		return tuple(params)

	def __call__(self, func):
		@functools.wraps(func)
		def wrapper(*args, **kwargs):
			params = self.watchedparams(args, kwargs)
			if params not in self.lastrun or time.time() - self.lastrun[params] >= self.period:
				self.lastreturn[params] = func(*args, **kwargs)
				self.lastrun[params] = time.time()
				return self.lastreturn[params]
			else:
				return self.lastreturn[params]
		# Copy this method across so it can be accessed on the wrapped function
		wrapper.reset_throttle = self.reset_throttle
		return wrapper

	def reset_throttle(self):
		self.lastrun = {}
		self.lastreturn = {}
