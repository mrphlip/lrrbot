import asyncio
import functools
import inspect
import itertools
import logging
import random
import time
import logging.config
import configparser
import re

from common import config

# Need to delay creation of our "log" until init_logging is called
log = None

# We usually don't want to catch these... so whenever we have an "except everything"
# clause, we want to explicitly catch and re-raise these.
PASSTHROUGH_EXCEPTIONS = (asyncio.CancelledError, )

# Maximum length of a chat message - this allows for 32 chars for protocol
# overhead (ie "PRIVMSG [target]" etc) to fit within 512
MAX_LEN = 480

def wrap_as_coroutine(func):
	"""
	Wrap a regular function in a coroutine function. If `func` is already a coroutine function it is
	returned unmodified.

	Replacement for `asyncio.coroutine()` which got removed in Python 3.11.
	"""

	if inspect.iscoroutinefunction(func):
		return func

	@functools.wraps(func)
	async def wrapper(*args, **kwargs):
		return func(*args, **kwargs)

	return wrapper

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
		is_coro = inspect.iscoroutinefunction(func)
		decorated_coro = decorator(wrap_as_coroutine(func))
		assert inspect.iscoroutinefunction(decorated_coro)

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
		self.lastcleanup = time.time()
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
			# periodically remove stale entries from cache
			if self.period is not None and time.time() - self.lastcleanup > self.period * 2:
				self.cleanup()

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
		self.lastcleanup = time.time()

	def cleanup(self):
		"""Remove expired cache entries"""
		cutoff = time.time() - self.period
		toremove = set()
		for key, runtimes in self.lastrun.items():
			if runtimes[-1] < cutoff:
				toremove.add(key)
		for key in toremove:
			del self.lastrun[key]
			del self.lastreturn[key]
		self.lastcleanup = time.time()


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
	asyncio.ensure_future(coro(), loop=loop).add_done_callback(check_exception)

	Apply this to any Future that is not passed to loop.run_until_complete or similar
	"""
	try:
		future.result()
	except PASSTHROUGH_EXCEPTIONS:
		raise
	except Exception:
		log.exception("Exception in future")

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

def check_length(msg, maxlen=MAX_LEN):
	"""
	Check if a message is short enough to be sent to the channel.
	"""
	return len(msg.encode("utf-8")) <= maxlen

def trim_length(msg, maxlen=MAX_LEN, do_warn=False):
	"""
	Check if a message is short enough to be sent to the channel, and if not,
	trim it to fit.
	"""
	encmsg = msg.encode("utf-8")
	if len(encmsg) > maxlen:
		if do_warn:
			log.warning("Trimming message as it is too long: %s", msg)
		# \u2026 takes up three bytes, so cut off the first maxlen-3 bytes of the
		# message
		# Are we about to cut off in the middle of a UTF-8 sequence?
		while encmsg[maxlen - 3] & 0xC0 == 0x80:
			maxlen -= 1
		return encmsg[:maxlen - 3].decode("utf-8") + "\u2026"
	else:
		return msg

re_duration = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$", re.IGNORECASE)
def parse_duration(duration):
	match = re_duration.match(duration)
	if not match:
		raise ValueError("Could not parse duration: %r" % duration)
	d, h, m, s = match.groups()
	return int(d or 0) * 86400 + int(h or 0) * 3600 + int(m or 0) * 60 + int(s or 0)
