#!/usr/bin/python
if __name__ == '__main__':
	import sys
	sys.stderr.write("utils.py accessed directly")
	sys.exit(1)

import functools
import oursql
import secrets
import server

def nice_duration(duration):
	"""Convert a duration in seconds to a human-readable duration"""
	if duration < 0:
		return "-" + niceduration(-duration)
	if duration < 60:
		return "%ds" % duration
	duration //= 60
	if duration < 60:
		return "%dm" % duration
	duration //= 60
	if duration < 24:
		return "%dh" % duration
	return "%dd, %dh" % divmod(duration, 24)

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
