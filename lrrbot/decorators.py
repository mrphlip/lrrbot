import enum
import functools
import logging
import time

import irc.client

from common.utils import coro_decorator, throttle_base, DEFAULT_THROTTLE
from lrrbot.docstring import encode_docstring, add_header, parse_docstring
from common import twitch

log = logging.getLogger("lrrbot.decorators")

@coro_decorator
def mod_only(func):
	"""Prevent an event-handler function from being called by non-moderators

	Usage:
	@mod_only
	def on_event(self, conn, event, ...):
		...
	"""
	@functools.wraps(func)
	async def wrapper(self, conn, event, *args, **kwargs):
		if self.is_mod(event):
			return await func(self, conn, event, *args, **kwargs)
		else:
			log.info("Refusing %s due to not-a-mod" % func.__name__)
			source = irc.client.NickMask(event.source)
			conn.privmsg(source.nick, "That is a mod-only command.")
			return None
	wrapper.__doc__ = encode_docstring(add_header(parse_docstring(wrapper.__doc__),
		"Mod-Only", "true"))
	return wrapper

@coro_decorator
def sub_only(func):
	"""Prevent an event-handler function from being called by non-subscribers

	Usage:
	@sub_only
	def on_event(self, conn, event, ...):
		...
	"""
	@functools.wraps(func)
	async def wrapper(self, conn, event, *args, **kwargs):
		if self.is_sub(event) or self.is_mod(event):
			return await func(self, conn, event, *args, **kwargs)
		else:
			log.info("Refusing %s due to not-a-sub" % func.__name__)
			source = irc.client.NickMask(event.source)
			conn.privmsg(source.nick, "That is a sub-only command.")
			return None
	wrapper.__doc__ = encode_docstring(add_header(parse_docstring(wrapper.__doc__),
		"Sub-Only", "true"))
	return wrapper

@coro_decorator
def public_only(func):
	"""Prevent an event-handler function from being called via private message

	Usage:
	@public_only
	def on_event(self, conn, event, ...):
		...
	"""
	@functools.wraps(func)
	async def wrapper(self, conn, event, *args, **kwargs):
		if event.type == "pubmsg" or self.is_mod(event):
			return await func(self, conn, event, *args, **kwargs)
		else:
			source = irc.client.NickMask(event.source)
			conn.privmsg(source.nick, "That command cannot be used via private message.")
	wrapper.__doc__ = encode_docstring(add_header(parse_docstring(wrapper.__doc__),
		"Public-Only", "true"))
	return wrapper

class twitch_throttle:
	def __init__(self, count=20, period=30):
		self.count = count
		self.period = period
		self.timestamps = []

	def __call__(self, f):
		@functools.wraps(f, assigned=functools.WRAPPER_ASSIGNMENTS + ("is_logged",))
		def wrapper(*args, **kwargs):
			now = time.time()
			self.timestamps = [t for t in self.timestamps if now-t <= self.period]
			if len(self.timestamps) >= self.count:
				log.info("Ignoring {}(*{}, **{})".format(f.__name__, args, kwargs))
			else:
				self.timestamps.append(now)
				return f(*args, **kwargs)
		wrapper.is_throttled = True
		return wrapper

class Visibility(enum.Enum):
	SILENT = 0
	PRIVATE = 1
	PUBLIC = 2

class throttle(throttle_base):
	"""Prevent an event function from being called more often than once per period

	Usage:
	@throttle([period])
	def func(lrrbot, conn, event, ...):
		...

	count allows the function to be called a given number of times during the period,
	but no more.
	"""
	def __init__(self, period=DEFAULT_THROTTLE, notify=Visibility.PRIVATE, modoverride=True, params=[], log=True, count=1, allowprivate=True):
		super().__init__(period=period, params=params, log=log, count=count)
		self.notify = notify
		self.modoverride = modoverride
		self.allowprivate = allowprivate

	def bypass(self, func, args, kwargs):
		if self.modoverride:
			lrrbot = args[0]
			event = args[2]
			if lrrbot.is_mod(event):
				return True
		if self.allowprivate:
			event = args[2]
			if event.type == "privmsg":
				return True
		return super().bypass(func, args, kwargs)

	def cache_hit(self, func, args, kwargs):
		if self.notify is not Visibility.SILENT:
			conn = args[1]
			event = args[2]
			source = irc.client.NickMask(event.source)
			conn.privmsg(source.nick, "A similar command has been registered recently.")
		return super().cache_hit(func, args, kwargs)

	def decorate(self, func):
		wrapper = super().decorate(func)
		wrapper.__doc__ = encode_docstring(add_header(add_header(parse_docstring(wrapper.__doc__),
			"Throttled", str(self.period)), "Throttle-Count", str(self.count)))
		return wrapper

def private_reply_when_live(func):
	"""Cause command handler to respond with private message when the stream is live.

	Usage:
	@private_reply_when_live
	def on_event(self, conn, event, respond_to, ...):
		...
	"""
	@functools.wraps(func)
	async def wrapper(self, conn, event, respond_to, *args, **kwargs):
		if event.type == "pubmsg" and await twitch.is_stream_live():
			source = irc.client.NickMask(event.source)
			respond_to = source.nick
		return await func(self, conn, event, respond_to, *args, **kwargs)
	return wrapper
