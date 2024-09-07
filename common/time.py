import datetime
import re
import timelib

import pytz

from common import config

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

re_timefmt1 = re.compile(r"^\s*(?:\s*(\d*)\s*d)?(?:\s*(\d*)\s*h)?(?:\s*(\d*)\s*m)?(?:\s*(\d*)\s*s?)?\s*$")
re_timefmt2 = re.compile(r"^(?:(?:(?:\s*(\d*)\s*:)?\s*(\d*)\s*:)?\s*(\d*)\s*:)?\s*(\d*)\s*$")
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
