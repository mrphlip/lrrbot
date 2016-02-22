import asyncio
import datetime
import enum
import functools
import inspect
import logging
import os.path
import random
import re
import socket
import textwrap
import time
import timelib

import flask
import irc.client
import psycopg2
import pytz
import werkzeug.datastructures

from common import config
from common.http import http_request_coro
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


def nice_duration(s, detail=1):
	"""
	Convert a duration in seconds to a human-readable duration.

	detail can be:
		0 - Always show to the nearest second
		1 - Show to the nearest minute, unless less than a minute
		2 - Show to the nearest hour, unless less than an hour
	"""
	if isinstance(s, datetime.timedelta):
		s = s.days * 86400 + s.seconds
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

def get_timezone(tz):
	"""
	Look up a timezone by name, case-insensitively
	"""
	try:
		return pytz.timezone(tz)
	except pytz.exceptions.UnknownTimeZoneError:
		tznames = {i.lower(): i for i in pytz.all_timezones}
		tz = tz.lower()
		if tz in tznames:
			return pytz.timezone(tznames[tz])
		else:
			raise

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

re_timefmt1 = re.compile("^\s*(?:\s*(\d*)\s*d)?(?:\s*(\d*)\s*h)?(?:\s*(\d*)\s*m)?(?:\s*(\d*)\s*s?)?\s*$")
re_timefmt2 = re.compile("^(?:(?:(?:\s*(\d*)\s*:)?\s*(\d*)\s*:)?\s*(\d*)\s*:)?\s*(\d*)\s*$")
def parsetime(s):
	"""
	Parse user-supplied times in one of two formats:
	"10s"
	"5m3s"
	"7h2m"
	"1d7m52s"
	or:
	"10"
	"5:03"
	"7:02:00"
	"1:00:07:52"

	Returns a timedelta object of the appropriate duration, or None if the parse fails
	"""
	if s is None:
		return None
	match = re_timefmt1.match(s)
	if not match:
		match = re_timefmt2.match(s)
	if not match:
		return None
	d = int(match.group(1) or 0)
	h = int(match.group(2) or 0)
	m = int(match.group(3) or 0)
	s = int(match.group(4) or 0)
	return datetime.timedelta(days=d, hours=h, minutes=m, seconds=s)

def strtotime(s):
	if isinstance(s, str):
		s = s.encode("utf-8")
	return datetime.datetime.fromtimestamp(timelib.strtotime(s), tz=pytz.utc)

def strtodate(s):
	dt = strtotime(s)
	# if the time is exactly midnight, then the user probably entered a date
	# without time info (eg "yesterday"), so just return that date. Otherwise, they
	# did enter time info (eg "now") so convert timezone first
	if dt.time() != datetime.time(0):
		dt = dt.astimezone(config.config['timezone'])
	return dt.date()

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

@cache(60 * 60, params=[0])
@asyncio.coroutine
def canonical_url(url, depth=10):
	urls = []
	while depth > 0:
		if not url.startswith("http://") and not url.startswith("https://"):
			url = "http://" + url
		urls.append(url)
		try:
			res = yield from http_request_coro(url, method="HEAD", allow_redirects=False)
			if res.status in range(300, 400) and "Location" in res.headers:
				url = res.headers["Location"]
				depth -= 1
			else:
				break
		except Exception:
			log.error("Error fetching %r", url)
			break
	return urls

@cache(24 * 60 * 60)
@asyncio.coroutine
def get_tlds():
	tlds = set()
	data = yield from http_request_coro("https://data.iana.org/TLD/tlds-alpha-by-domain.txt")
	for line in data.splitlines():
		if not line.startswith("#"):
			line = line.strip().lower()
			tlds.add(line)
			line = line.encode("ascii").decode("idna")
			tlds.add(line)
	return tlds

@cache(24 * 60 * 60)
@asyncio.coroutine
def url_regex():
	parens = ["()", "[]", "{}", "<>", '""', "''"]

	# Sort TLDs in decreasing order by length to avoid incorrect matches.
	# For example: if 'co' is before 'com', 'example.com/path' is matched as 'example.co'.
	tlds = sorted((yield from get_tlds()), key=lambda e: len(e), reverse=True)
	re_tld = "(?:" + "|".join(map(re.escape, tlds)) + ")"
	re_hostname = "(?:(?:(?:[\w-]+\.)+" + re_tld + "\.?)|(?:\d{,3}(?:\.\d{,3}){3})|(?:\[[0-9a-fA-F:.]+\]))"
	re_url = "((?:https?://)?" + re_hostname + "(?::\d+)?(?:/[\x5E\s\u200b]*)?)"
	re_url = re_url + "|" + "|".join(map(lambda parens: re.escape(parens[0]) + re_url + re.escape(parens[1]), parens))
	return re.compile(re_url, re.IGNORECASE)

RE_PROTO = re.compile("^https?://")
def https(uri):
	return RE_PROTO.sub("https://", uri)
def noproto(uri):
	return RE_PROTO.sub("//", uri)

def escape_like(s):
	return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
