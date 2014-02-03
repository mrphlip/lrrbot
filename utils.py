import functools
import time
import logging
import irc.client
import urllib.request

log = logging.getLogger('utils')

DEFAULT_THROTTLE = 15

class throttle(object):
	"""Prevent a function from being called more often than once per period

	Usage:
	@throttle(period)
	def func(...):
		...
	"""
	def __init__(self, period=DEFAULT_THROTTLE):
		self.period = period
		self.lastrun = None

	def __call__(self, func):
		@functools.wraps(func)
		def wrapper(*args, **kwargs):
			if self.lastrun is None or time.time() - self.lastrun >= self.period:
				self.lastrun = time.time()
				return func(*args, **kwargs)
		return wrapper

def mod_only(func):
	"""Prevent an event-handler function from being called by non-moderators

	Usage:
	@mod_only
	def on_event(self, conn, event, ...):
		...
	"""

	# Only complain about non-mods with throttle
	# but allow the command itself to be run without throttling
	@throttle()
	def mod_complaint(conn, event):
		source = irc.client.NickMask(event.source)
		if irc.client.is_channel(event.target):
			respond_to = event.target
		else:
			respond_to = source.nick
		conn.privmsg(respond_to, "%s: That is a mod-only command" % source.nick)

	@functools.wraps(func)
	def wrapper(self, conn, event, *args, **kwargs):
		if self.is_mod(event):
			return func(self, conn, event, *args, **kwargs)
		else:
			mod_complaint(conn, event)
			return None
	return wrapper

def log_errors(func):
	"""Log any errors thrown by a function"""
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		try:
			return func(*args, **kwargs)
		except:
			log.exception("Exception in " + func.name)
			raise
	return wrapper

def swallow_errors(func):
	"""Log and absorb any errors thrown by a function"""
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		try:
			return func(*args, **kwargs)
		except:
			log.exception("Exception in " + func.name)
			return None
	return wrapper
