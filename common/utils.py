import asyncio
import functools
import inspect
import itertools
import json
import logging
import os.path
import random
import socket
import time
import heapq
import logging.config
import configparser
import sqlalchemy

import werkzeug.datastructures

from common import config
from common import postgres

# Need to delay creation of our "log" until init_logging is called
log = None

# We usually don't want to catch these... so whenever we have an "except everything"
# clause, we want to explicitly catch and re-raise these.
PASSTHROUGH_EXCEPTIONS = (asyncio.CancelledError, )

def deindent(s):
	def skipblank():
		generator = map(lambda s: s.lstrip(), s.splitlines())
		for line in generator:
			if line != '':
				break
		yield line
		yield from generator
	return "\n".join(skipblank())

def coro_decorator(decorator):
	"""
	Utility decorator used when defining other decorators, so they can wrap
	either normal functions or coroutines.

	Usage:
	@coro_decorator
	def decorator(func):
		@functools.wraps(func)
		async def wrapper(...) # decorator must return a coroutine, and use "await" or "yield from" to call func
			...
			ret = await func(...)
			...
			return ...
		return wrapper

	@decorator
	def normal_func():
		pass

	@decorator
	async def coro_func():
		pass

	Note that the decorator must *not* await anything *except* the function
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
				try:
					decorated_coro(*args, **kwargs).send(None)
				except StopIteration as e:
					return e.value
				else:
					raise Exception("Decorator %s behaving badly wrapping non-coroutine %s" % (decorator.__name__, func.__name__))
			return decorated_func
	return wrapper

DEFAULT_THROTTLE = 15
class throttle_base(object):
	"""Prevent a function from being called more often than once per period"""
	def __init__(self, period=DEFAULT_THROTTLE, params=[], log=True, count=1):
		self.period = period
		self.watchparams = params
		self.lastrun = {}
		self.lastreturn = {}
		self.log = log
		self.count = count
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

	def bypass(self, func, args, kwargs):
		"""Inspect arguments and determine if the cache should be bypassed."""
		return False

	def cache_hit(self, func, args, kwargs):
		"""Called when result was found in cache."""
		if self.log:
			log.info("Skipping %s due to throttling" % func.__name__)

	def decorate(self, func):
		if self.watchparams:
			self.signature = inspect.signature(func)
			param_list = list(self.signature.parameters.keys())
			self.watchparams = [param_list[i] if isinstance(i, int) else i for i in self.watchparams]
			self.watchparams = [(i, self.signature.parameters[i].default) for i in self.watchparams]

		@functools.wraps(func)
		async def wrapper(*args, **kwargs):
			async with self.lock:
				if self.bypass(func, args, kwargs):
					return (await func(*args, **kwargs))

				params = self.watchedparams(args, kwargs)
				if params not in self.lastrun or len(self.lastrun[params]) < self.count or (self.period and time.time() - self.lastrun[params][0] >= self.period):
					self.lastreturn[params] = await func(*args, **kwargs)
					self.lastrun.setdefault(params, []).append(time.time())
					if len(self.lastrun[params]) > self.count:
						self.lastrun[params] = self.lastrun[params][-self.count:]
				else:
					self.cache_hit(func, args, kwargs)
				return self.lastreturn[params]
		# Copy this method across so it can be accessed on the wrapped function
		wrapper.reset_throttle = self.reset_throttle
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
		super().__init__(period=period, params=params, log=log, count=count)

@coro_decorator
def log_errors(func):
	"""Log any errors thrown by a function"""
	@functools.wraps(func)
	async def wrapper(*args, **kwargs):
		try:
			return await func(*args, **kwargs)
		except:
			log.exception("Exception in " + func.__name__)
			raise
	return wrapper

@coro_decorator
def swallow_errors(func):
	"""Log and absorb any errors thrown by a function"""
	@functools.wraps(func)
	async def wrapper(*args, **kwargs):
		try:
			return await func(*args, **kwargs)
		except PASSTHROUGH_EXCEPTIONS:
			raise
		except Exception:
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
	except PASSTHROUGH_EXCEPTIONS:
		raise
	except Exception:
		log.exception("Exception in future")

def immutable(obj):
	if isinstance(obj, dict):
		return werkzeug.datastructures.ImmutableDict((k, immutable(v)) for k,v in obj.items())
	elif isinstance(obj, list):
		return werkzeug.datastructures.ImmutableList(immutable(v) for v in obj)
	else:
		return obj

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
	sse.send(json.dumps(sse_event).encode("utf-8")+b"\n")
	sse.close()

def ucfirst(s):
	return s[0].upper() + s[1:]

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

def pick_random_elements(iterable, k):
	"""
	Pick `k` random elements from `iterable`. Returns a list of length `k`.
	If there weren't enough elements, `None` is stored at that index instead.
	"""
	# Algorithm R: https://en.wikipedia.org/wiki/Reservoir_sampling#Algorithm_R
	# Changed to use zero-based indexing.
	ret = [None] * k
	iterable = enumerate(iterable)
	for i, elem in itertools.islice(iterable, len(ret)):
		ret[i] = elem

	for i, elem in iterable:
		j = random.randrange(i+1)
		if j < k:
			ret[j] = elem

	return ret

def pick_weighted_random_elements(iterable, k):
	queue = []
	for elem, weight in iterable:
		if not weight:
			continue
		r = random.random() ** (1 / weight)
		if len(queue) < k:
			heapq.heappush(queue, (r, elem))
		elif queue[0][0] < r:
			heapq.heapreplace(queue, (r, elem))
	return [elem for r, elem in queue]

def merge_config_section(configs, prefix):
	"""
	Merge prefixed sections into the real sections, so that different values can
	be set to apply to different modes.

	eg:
	merge_config_section(configs, "debug")
	will merge [debug_xyz] sections into [xyz] sections
	"""
	prefix = prefix + "_"
	for section in configs.sections():
		if section[:len(prefix)] == prefix:
			if not configs.has_section(section[len(prefix):]):
				configs.add_section(section[len(prefix):])
			for option, value in configs.items(section):
				configs.set(section[len(prefix):], option, value)

def init_logging(mode=None):
	logging.Formatter.converter = time.gmtime
	logging_conf = configparser.ConfigParser()
	logging_conf.read("logging.conf")
	if config.config['debug']:
		merge_config_section(logging_conf, "debug")
	if mode:
		merge_config_section(logging_conf, mode)
	logging.config.fileConfig(logging_conf)
	global log
	log = logging.getLogger('utils')

def get_user_id(name):
	"""
	Get the user id for a given username, if it's in our database.

	For a more thorough version that gets the id even if the name isn't in our
	database, see common.twitch.get_user
	"""
	engine, metadata = postgres.get_engine_and_metadata()
	users = metadata.tables["users"]
	with engine.begin() as conn:
		row = conn.execute(sqlalchemy.select([users.c.id]).where(users.c.name == name)).first()
	if row:
		return row[0]
	else:
		return None

def get_user_name(id):
	"""
	Get the username for a given user id, if it's in our database.

	For a more thorough version that gets the name even if the id isn't in our
	database, see common.twitch.get_user
	"""
	engine, metadata = postgres.get_engine_and_metadata()
	users = metadata.tables["users"]
	with engine.begin() as conn:
		row = conn.execute(sqlalchemy.select([users.c.name]).where(users.c.id == id)).first()
	if row:
		return row[0]
	else:
		return None

async def async_to_list(aiter):
	"""
	Convert an asynchronous generator to a simple list.
	"""
	# Can't do this until Python3.6 ...
	# https://www.python.org/dev/peps/pep-0530/
	# return [i async for i in aiter]

	res = []
	async for i in aiter:
		res.append(i)
	return res
