import functools
import socket
import time
import logging
import urllib.request
import urllib.parse
import json
import email.parser
import textwrap
import datetime
import re
import os.path
import timelib
import random
import enum
import asyncio
import aiohttp

import flask
import irc.client
import pytz
import werkzeug.datastructures

from common import config
import psycopg2


log = logging.getLogger('utils')

DOCSTRING_IMPLICIT_PREFIX = """Content-Type: multipart/message; boundary=command

--command"""
DOCSTRING_IMPLICIT_SUFFIX = "\n--command--"

def deindent(s):
	def skipblank():
		generator = map(lambda s: s.lstrip(), s.splitlines())
		for line in generator:
			if line != '':
				break
		yield line
		yield from generator
	return "\n".join(skipblank())

def parse_docstring(docstring):
	if docstring is None:
		docstring = ""
	docstring = DOCSTRING_IMPLICIT_PREFIX + docstring + DOCSTRING_IMPLICIT_SUFFIX
	return email.parser.Parser().parsestr(deindent(docstring))

def encode_docstring(docstring):
	docstring = str(docstring).rstrip()
	assert docstring.startswith(DOCSTRING_IMPLICIT_PREFIX)
	assert docstring.endswith(DOCSTRING_IMPLICIT_SUFFIX)
	return docstring[len(DOCSTRING_IMPLICIT_PREFIX):-len(DOCSTRING_IMPLICIT_SUFFIX)]

def add_header(doc, name, value):
	for part in doc.walk():
		if part.get_content_maintype() != "multipart":
			part[name] = value
	return doc

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

class _throttle_base(object):
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

		# need to decorate this here, rather than putting a decorator on the actual
		# function, as it needs to wrap the *bound* method, so there's no "self"
		# parameter. Meanwhile, we're wrapping this "decorate" function instead of
		# just wrapping __call__ as setting __call__ directly on instances doesn't
		# work, Python gets the __call__ function from the class, not individual
		# instances.
		self.decorate = coro_decorator(self.decorate)

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
		return self.decorate(func)
	def decorate(self, func):
		@asyncio.coroutine
		@functools.wraps(func)
		def wrapper(*args, **kwargs):
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

class throttle(_throttle_base):
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

class cache(_throttle_base):
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
	def wrapper(self, conn, event, *args, **kwargs):
		if self.is_mod(event):
			return func(self, conn, event, *args, **kwargs)
		else:
			log.info("Refusing %s due to not-a-mod" % func.__name__)
			mod_complaint(self, conn, event)
			return None
	wrapper.__doc__ = encode_docstring(add_header(parse_docstring(wrapper.__doc__),
		"Mod-Only", "true"))
	return wrapper

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
	def wrapper(self, conn, event, *args, **kwargs):
		if self.is_sub(event) or self.is_mod(event):
			return func(self, conn, event, *args, **kwargs)
		else:
			log.info("Refusing %s due to not-a-sub" % func.__name__)
			sub_complaint(self, conn, event)
			return None
	wrapper.__doc__ = encode_docstring(add_header(parse_docstring(wrapper.__doc__),
		"Sub-Only", "true"))
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

def public_only(func):
	"""Prevent an event-handler function from being called via private message

	Usage:
	@public_only
	def on_event(self, conn, event, ...):
		...
	"""
	@functools.wraps(func)
	def wrapper(self, conn, event, *args, **kwargs):
		if event.type == "pubmsg" or self.is_mod(event):
			return func(self, conn, event, *args, **kwargs)
		else:
			source = irc.client.NickMask(event.source)
			conn.privmsg(source.nick, "That command cannot be used via private message")
	wrapper.__doc__ = encode_docstring(add_header(parse_docstring(wrapper.__doc__),
		"Public-Only", "true"))
	return wrapper

def log_errors(func):
	"""Log any errors thrown by a function"""
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		try:
			return func(*args, **kwargs)
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

class Request(urllib.request.Request):
	"""Override the get_method method of Request, adding the "method" field that doesn't exist until Python 3.3"""
	def __init__(self, *args, method=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.method = method
	def get_method(self):
		if self.method is not None:
			return self.method
		else:
			return super().get_method()

def http_request(url, data=None, method='GET', maxtries=3, headers={}, timeout=5, **kwargs):
	"""Download a webpage, with retries on failure."""
	# Let's be nice.
	headers["User-Agent"] = "LRRbot/2.0 (http://lrrbot.mrphlip.com/)"
	if data:
		if isinstance(data, dict):
			data = urllib.parse.urlencode(data)
		if method == 'GET':
			url = '%s?%s' % (url, data)
			req = Request(url=url, method='GET', headers=headers, **kwargs)
		elif method == 'POST':
			req = Request(url=url, data=data.encode("utf-8"), method='POST', headers=headers, **kwargs)
		elif method == 'PUT':
			req = Request(url=url, data=data.encode("utf-8"), method='PUT', headers=headers, **kwargs)
	else:
		req = Request(url=url, method='GET', headers=headers, **kwargs)

	firstex = None
	while True:
		try:
			return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
		except Exception as e:
			maxtries -= 1
			if firstex is None:
				firstex = e
			if maxtries > 0:
				log.info("Downloading %s failed: %s: %s, retrying...", url, e.__class__.__name__, e)
			else:
				break
	raise firstex

# Limit the number of parallel HTTP connections to a server.
http_request_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=6))
@asyncio.coroutine
def http_request_coro(url, data=None, method='GET', maxtries=3, headers={}, timeout=5):
	headers["User-Agent"] = "LRRbot/2.0 (http://lrrbot.mrphlip.com/)"
	firstex = None
	if method == 'GET':
		params = data
		data = None
	else:
		params = None
	while True:
		try:
			res = yield from asyncio.wait_for(http_request_session.request(method, url, params=params, data=data, headers=headers), timeout)
			status_class = res.status // 100
			if status_class != 2:
				yield from res.read()
				if status_class == 4:
					maxtries = 1
				raise urllib.error.HTTPError(res.url, res.status, res.reason, res.headers, None)
			return (yield from res.text())
		except Exception as e:
			maxtries -= 1
			if firstex is None:
				firstex = e
			if maxtries > 0:
				log.info("Downloading %s failed: %s: %s, retrying...", url, e.__class__.__name__, e)
			else:
				break
	raise firstex

def api_request(uri, *args, **kwargs):
	# Send the information to the server
	try:
		res = http_request(config.config['siteurl'] + uri, *args, **kwargs)
	except:
		log.exception("Error at server in %s" % uri)
	else:
		try:
			res = json.loads(res)
		except:
			log.exception("Error parsing server response from %s: %s", uri, res)
		else:
			if 'success' not in res:
				log.error("Error at server in %s" % uri)
			return res

@asyncio.coroutine
def api_request_coro(uri, *args, **kwargs):
	try:
		res = yield from http_request_coro(config.config['siteurl'] + uri, *args, **kwargs)
	except:
		log.exception("Error at server in %s" % uri)
	else:
		try:
			res = json.loads(res)
		except:
			log.exception("Error parsing server response from %s: %s", uri, res)
		else:
			if 'success' not in res:
				log.error("Error at server in %s" % uri)
			return res

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
	else:
		ts = ts.astimezone(datetime.timezone.utc)
	return flask.Markup("<span class=\"timestamp\" data-timestamp=\"%d\">%s</span>" % (ts.timestamp(), flask.escape(ts.ctime())))


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
