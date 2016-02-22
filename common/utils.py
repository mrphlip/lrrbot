import asyncio
import datetime
import enum
import functools
import inspect
import logging
import os.path
import random
import socket
import textwrap
import time

import flask
import irc.client
import psycopg2
import pytz
import werkzeug.datastructures

from common import config
from lrrbot.docstring import parse_docstring, encode_docstring, add_header

log = logging.getLogger('utils')


def deindent(s):
	def skipblank():
		generator = map(lambda s: s.lstrip(), s.splitlines())
		for line in generator:
			if line != '':
				break
		yield line
		yield from generator
	return "\n".join(skipblank())


def shorten_fallback(text, width, **kwargs):
	"""textwrap.shorten is introduced in Python 3.4"""
	w = textwrap.TextWrapper(width=width, **kwargs)
	r = ' '.join(text.strip().split())
	r = w.wrap(r)
	if len(r) > 1:
		r = r[0]
		while len(r) + 3 > width:
			r = r[:r.rfind(' ')]
			r = r + "..."
	elif len(r) == 0:
		r = None
	else:
		r = r[0]
	return r

shorten = getattr(textwrap, "shorten", shorten_fallback)

def coro_decorator(decorator):
	"""
	Utility decorator used when defining other decorators, so they can wrap
	either normal functions or asyncio coroutines.

	Usage:
	@coro_decorator
	def decorator(func):
		@functools.wraps(func)
		@asyncio.coroutine # decorator must return a coroutine, and use "yield from" to call func
		def wrapper(...)
			...
			ret = yield from func(...)
			...
			return ...
		return wrapper

	@decorator
	def normal_func():
		pass

	@decorator # @decorator must be above @coroutine
	@asyncio.coroutine
	def coro_func():
		pass

	Note that the decorator must *not* yield from anything *except* the function
	it's decorating.
	"""
	# any extra properties that we want to assign to wrappers, in any of the decorators
	# we use this on
	EXTRA_PARAMS = ('reset_throttle',)
	@functools.wraps(decorator)
	def wrapper(func):
		is_coro = asyncio.iscoroutinefunction(func)
		if not is_coro:
			func = asyncio.coroutine(func)

		decorated_coro = decorator(func)
		assert asyncio.iscoroutinefunction(decorated_coro)

		if is_coro:
			return decorated_coro
		else:
			# Unwrap the coroutine. We know it should never yield.
			@functools.wraps(decorated_coro, assigned=functools.WRAPPER_ASSIGNMENTS + EXTRA_PARAMS, updated=())
			def decorated_func(*args, **kwargs):
				x = iter(decorated_coro(*args, **kwargs))
				try:
					next(x)
				except StopIteration as e:
					return e.value
				else:
					raise Exception("Decorator %s behaving badly wrapping non-coroutine %s" % (decorator.__name__, func.__name__))
			return decorated_func
	return wrapper

DEFAULT_THROTTLE = 15

class Visibility(enum.Enum):
	SILENT = 0
	PRIVATE = 1
	PUBLIC = 2

class throttle_base(object):
	"""Prevent a function from being called more often than once per period"""
	def __init__(self, period=DEFAULT_THROTTLE, notify=Visibility.SILENT, modoverride=False, params=[], log=True, count=1, allowprivate=False):
		self.period = period
		self.notify = notify
		self.modoverride = modoverride
		self.watchparams = params
		self.lastrun = {}
		self.lastreturn = {}
		self.log = log
		self.count = count
		self.allowprivate = allowprivate
		self.lock = asyncio.Lock()

		# need to decorate this here, rather than putting a decorator on the actual
		# function, as it needs to wrap the *bound* method, so there's no "self"
		# parameter. Meanwhile, we're wrapping this "decorate" function instead of
		# just wrapping __call__ as setting __call__ directly on instances doesn't
		# work, Python gets the __call__ function from the class, not individual
		# instances.
		self.decorate = coro_decorator(self.decorate)

	def watchedparams(self, args, kwargs):
		if not self.watchparams:
			return ()
		params = []
		bound_args = self.signature.bind(*args, **kwargs)
		for name, default in self.watchparams:
			param = bound_args.arguments.get(name, default)
			if isinstance(param, str):
				param = param.lower()
			params.append(param)
		return tuple(params)

	def __call__(self, func):
		return self.decorate(func)
	def decorate(self, func):
		if self.watchparams:
			self.signature = inspect.signature(func)
			param_list = list(self.signature.parameters.keys())
			self.watchparams = [param_list[i] if isinstance(i, int) else i for i in self.watchparams]
			self.watchparams = [(i, self.signature.parameters[i].default) for i in self.watchparams]

		@asyncio.coroutine
		@functools.wraps(func)
		def wrapper(*args, **kwargs):
			with (yield from self.lock):
				if self.modoverride:
					lrrbot = args[0]
					event = args[2]
					if lrrbot.is_mod(event):
						return (yield from func(*args, **kwargs))
				if self.allowprivate:
					event = args[2]
					if event.type == "privmsg":
						return (yield from func(*args, **kwargs))

				params = self.watchedparams(args, kwargs)
				if params not in self.lastrun or len(self.lastrun[params]) < self.count or (self.period and time.time() - self.lastrun[params][0] >= self.period):
					self.lastreturn[params] = yield from func(*args, **kwargs)
					self.lastrun.setdefault(params, []).append(time.time())
					if len(self.lastrun[params]) > self.count:
						self.lastrun[params] = self.lastrun[params][-self.count:]
				else:
					if self.log:
						log.info("Skipping %s due to throttling" % func.__name__)
					if self.notify is not Visibility.SILENT:
						conn = args[1]
						event = args[2]
						source = irc.client.NickMask(event.source)
						if irc.client.is_channel(event.target) and self.notify is Visibility.PUBLIC:
							respond_to = event.target
						else:
							respond_to = source.nick
						conn.privmsg(respond_to, "%s: A similar command has been registered recently" % source.nick)
				return self.lastreturn[params]
		# Copy this method across so it can be accessed on the wrapped function
		wrapper.reset_throttle = self.reset_throttle
		wrapper.__doc__ = encode_docstring(add_header(add_header(parse_docstring(wrapper.__doc__),
			"Throttled", str(self.period)), "Throttle-Count", str(self.count)))
		return wrapper

	def reset_throttle(self):
		self.lastrun = {}
		self.lastreturn = {}


class cache(throttle_base):
	"""Cache the results of a function for a given period

	Usage:
	@cache([period])
	def func(...):
		...

	When called within the throttle period, the last return value is returned,
	for memoisation. period can be set to None to never expire, allowing this to
	be used as a basic memoisation decorator.

	params is a list of parameters to consider as distinct, so calls where the
	watched parameters are the same are throttled together, but calls where they
	are different are throttled separately. Should be a list of ints (for positional
	parameters) and strings (for keyword parameters).
	"""
	def __init__(self, period=DEFAULT_THROTTLE, params=[], log=False, count=1):
		super().__init__(period=period, notify=Visibility.SILENT, modoverride=False, params=params, log=log, count=count, allowprivate=False)


@coro_decorator
def log_errors(func):
	"""Log any errors thrown by a function"""
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		try:
			return (yield from func(*args, **kwargs))
		except:
			log.exception("Exception in " + func.__name__)
			raise
	return wrapper

@coro_decorator
def swallow_errors(func):
	"""Log and absorb any errors thrown by a function"""
	@asyncio.coroutine
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		try:
			return (yield from func(*args, **kwargs))
		except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
			raise
		except:
			log.exception("Exception in " + func.__name__)
			return None
	return wrapper

def check_exception(future):
	"""
	Log any exceptions that occurred while processing this Future.

	Usage:
	asyncio.async(coro(), loop=loop).add_done_callback(check_exception)

	Apply this to any Future that is not passed to loop.run_until_complete or similar
	"""
	try:
		future.result()
	except (KeyboardInterrupt, SystemExit):
		raise
	except:
		log.exception("Exception in future")


def immutable(obj):
	if isinstance(obj, dict):
		return werkzeug.datastructures.ImmutableDict((k, immutable(v)) for k,v in obj.items())
	elif isinstance(obj, list):
		return werkzeug.datastructures.ImmutableList(immutable(v) for v in obj)
	else:
		return obj


def get_postgres():
	return psycopg2.connect(config.config["postgres"])

def with_postgres(func):
	"""Decorator to pass a PostgreSQL connection and cursor to a function"""
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		with get_postgres() as conn, conn.cursor() as cur:
			return func(conn, cur, *args, **kwargs)
	return wrapper


def sse_send_event(endpoint, event=None, data=None, event_id=None):
	if not os.path.exists(config.config['eventsocket']):
		return

	sse_event = {"endpoint": endpoint}
	if event is not None:
		sse_event["event"] = event
	if data is not None:
		sse_event["data"] = data
	if event_id is not None:
		sse_event["id"] = event_id

	sse = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	sse.connect(config.config['eventsocket'])
	sse.send(flask.json.dumps(sse_event).encode("utf-8")+b"\n")
	sse.close()


def error_page(message):
	from www import login
	return flask.render_template("error.html", message=message, session=login.load_session(include_url=False))

def timestamp(ts):
	"""
	Outputs a given time (either unix timestamp or datetime instance) as a human-readable time
	and includes tags so that common.js will convert the time on page-load to the user's
	timezone and preferred date/time format.
	"""
	if isinstance(ts, (int, float)):
		ts = datetime.datetime.fromtimestamp(ts, tz=pytz.utc)
	elif ts.tzinfo is None:
		ts = ts.replace(tzinfo=datetime.timezone.utc)
	ts = ts.astimezone(config.config['timezone'])
	return flask.Markup("<span class=\"timestamp\" data-timestamp=\"{}\">{:%A, %-d %B, %Y %H:%M:%S %Z}</span>".format(ts.timestamp(), ts))


def ucfirst(s):
	return s[0].upper() + s[1:]


def pick_random_row(cur, query, params = ()):
	" Return a random row of a SELECT query. "
	# CSE - common subexpression elimination, an optimisation Postgres doesn't do
	cur.execute("CREATE TEMP TABLE cse AS " + query, params)
	if cur.rowcount <= 0:
		return None
	cur.execute("SELECT * FROM cse OFFSET %s LIMIT 1", (random.randrange(cur.rowcount), ))
	row = cur.fetchone()
	cur.execute("DROP TABLE cse")
	return row

def weighted_choice(options):
	"""
	Weighted random selection. Call with a list of choices and their weights:
	weighted_choice([
		("foo", 2),
		("bar", 1),
	])
	will return "foo" twice as often as "bar".

	Also, unlike random.choice, this can accept a generator:
	weighted_choice((i, len(i)) for i in lst)
	"""
	values = []
	weights = [0.0]
	total_weight = 0.0
	for value, weight in options:
		values.append(value)
		total_weight += weight
		weights.append(total_weight)
	if total_weight <= 0:
		raise ValueError("No options to choose")

	choice = random.uniform(0, total_weight)
	left, right = 0, len(weights)
	while left < right - 1:
		mid = (left + right) // 2
		if choice < weights[mid]:
			right = mid
		else:
			left = mid
	return values[left]


def escape_like(s):
	return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
