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

import flask
import irc.client
import pytz
import werkzeug.datastructures

from common import config
import psycopg2

import Crypto.Hash.HMAC
import Crypto.Hash.SHA256
import base64

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

DEFAULT_THROTTLE = 15

class throttle(object):
	"""Prevent a function from being called more often than once per period

	Usage:
	@throttle([period])
	def func(...):
		...

	@throttle([period], notify=True)
	def func(self, conn, event, ...):
		...

	When called within the throttle period, the last return value is returned,
	for memoisation. period can be set to None to never expire, allowing this to
	be used as a basic memoisation decorator.

	params is a list of parameters to consider as distinct, so calls where the
	watched parameters are the same are throttled together, but calls where they
	are different are throttled separately. Should be a list of ints (for positional
	parameters) and strings (for keyword parameters).
	"""
	def __init__(self, period=DEFAULT_THROTTLE, notify=False, params=[], log=True):
		self.period = period
		self.notify = notify
		self.watchparams = params
		self.lastrun = {}
		self.lastreturn = {}
		self.log = log

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
			if params not in self.lastrun or (self.period and time.time() - self.lastrun[params] >= self.period):
				self.lastreturn[params] = func(*args, **kwargs)
				self.lastrun[params] = time.time()
				return self.lastreturn[params]
			else:
				if self.log:
					log.info("Skipping %s due to throttling" % func.__name__)
				if self.notify:
					conn = args[1]
					event = args[2]
					source = irc.client.NickMask(event.source)
					if irc.client.is_channel(event.target):
						respond_to = event.target
					else:
						respond_to = source.nick
					conn.privmsg(respond_to, "%s: A similar command has been registered recently" % source.nick)
				return self.lastreturn[params]
		# Copy this method across so it can be accessed on the wrapped function
		wrapper.reset_throttle = self.reset_throttle
		wrapper.__doc__ = encode_docstring(add_header(parse_docstring(wrapper.__doc__),
			"Throttled", str(self.period)))
		return wrapper

	def reset_throttle(self):
		self.lastrun = {}
		self.lastreturn = {}

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
			log.info("Refusing %s due to not-a-mod" % func.__name__)
			mod_complaint(conn, event)
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

	@throttle()
	def sub_complaint(conn, event):
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
			sub_complaint(conn, event)
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

def swallow_errors(func):
	"""Log and absorb any errors thrown by a function"""
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		try:
			return func(*args, **kwargs)
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
				log.info("Downloading %s failed: %s, retrying..." % (url, e))
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
			log.exception("Error parsing server response from %s: %s" % (uri, res))
		else:
			if 'success' not in res:
				log.error("Error at server in %s" % uri)

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


def with_postgres(func):
	"""Decorator to pass a PostgreSQL connection and cursor to a function"""
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		with psycopg2.connect(config.config["postgres"]) as conn:
			with conn.cursor() as cur:
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

HASH_ALGORITHM = Crypto.Hash.SHA256
def hmac_sign(message):
	mac = Crypto.Hash.HMAC.new(
		config.config["session_secret"].encode("utf-8"),
		msg=message,
		digestmod=HASH_ALGORITHM
	)
	return base64.urlsafe_b64encode(mac.digest() + message)

def hmac_verify(signature):
	message = base64.urlsafe_b64decode(signature)[HASH_ALGORITHM.digest_size:]
	if hmac_sign(message) == signature:
		return message
