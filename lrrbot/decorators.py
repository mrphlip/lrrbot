import asyncio
import functools
import logging
import time

import irc.client

from common.utils import coro_decorator, Visibility, throttle_base, DEFAULT_THROTTLE
from lrrbot.docstring import encode_docstring, add_header, parse_docstring

log = logging.getLogger("lrrbot.decorators")

@coro_decorator
def mod_only(func):
	"""Prevent an event-handler function from being called by non-moderators

	Usage:
	@mod_only
	def on_event(self, conn, event, ...):
		...
	"""

	# Only complain about non-mods with throttle
	# but allow the command itself to be run without throttling
	@throttle(notify=Visibility.SILENT, modoverride=False)
	def mod_complaint(self, conn, event):
		source = irc.client.NickMask(event.source)
		if irc.client.is_channel(event.target):
			respond_to = event.target
		else:
			respond_to = source.nick
		conn.privmsg(respond_to, "%s: That is a mod-only command" % source.nick)

	@functools.wraps(func)
	@asyncio.coroutine
	def wrapper(self, conn, event, *args, **kwargs):
		if self.is_mod(event):
			return (yield from func(self, conn, event, *args, **kwargs))
		else:
			log.info("Refusing %s due to not-a-mod" % func.__name__)
			mod_complaint(self, conn, event)
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

	@throttle(notify=Visibility.SILENT, modoverride=False)
	def sub_complaint(self, conn, event):
		source = irc.client.NickMask(event.source)
		if irc.client.is_channel(event.target):
			respond_to = event.target
		else:
			respond_to = source.nick
		conn.privmsg(respond_to, "%s: That is a subscriber-only command" % source.nick)

	@functools.wraps(func)
	@asyncio.coroutine
	def wrapper(self, conn, event, *args, **kwargs):
		if self.is_sub(event) or self.is_mod(event):
			return (yield from func(self, conn, event, *args, **kwargs))
		else:
			log.info("Refusing %s due to not-a-sub" % func.__name__)
			sub_complaint(self, conn, event)
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
	@asyncio.coroutine
	def wrapper(self, conn, event, *args, **kwargs):
		if event.type == "pubmsg" or self.is_mod(event):
			return (yield from func(self, conn, event, *args, **kwargs))
		else:
			source = irc.client.NickMask(event.source)
			conn.privmsg(source.nick, "That command cannot be used via private message")
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
		super().__init__(period=period, notify=notify, modoverride=modoverride, params=params, log=log, count=count, allowprivate=allowprivate)
