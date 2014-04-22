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
