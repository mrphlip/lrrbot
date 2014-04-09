import icalendar
import utils
import time
import datetime
import dateutil.rrule
import operator

CACHE_EXPIRY = 15*60
URL = "http://www.google.com/calendar/ical/loadingreadyrun.com_72jmf1fn564cbbr84l048pv1go%40group.calendar.google.com/public/basic.ics"

@utils.throttle(CACHE_EXPIRY)
def get_calendar_data():
	ical = utils.http_request(URL)
	return icalendar.Calendar.from_ical(ical)

def get_next_event(after=None, all=False):
	cal_data = get_calendar_data()
	events = []
	if after is None:
		after = datetime.datetime.now(datetime.timezone.utc)
	for ev in cal_data.subcomponents:
		if isinstance(ev, icalendar.Event):
			event_name = str(ev['summary'])
			event_time = ev['dtstart'].dt
			exception_times = ev.get('exdate')
			if not exception_times:
				exception_times = []
			elif not isinstance(exception_times, (tuple, list)):
				exception_times = [exception_times]
			exception_times = set(j.dt for i in exception_times for j in i.dts)
			if not isinstance(event_time, datetime.datetime):
				# ignore full-day events
				continue
			# Report episodes that are either in the first half, or started less than an hour ago
			# Whichever is shorter
			cutoff_delay = (ev['dtend'].dt - ev['dtstart'].dt) / 2
			if cutoff_delay > datetime.timedelta(hours=1):
				cutoff_delay = datetime.timedelta(hours=1)
			event_time_cutoff = event_time + cutoff_delay
			if 'rrule' in ev:
				rrule = dateutil.rrule.rrulestr(ev['rrule'].to_ical().decode('utf-8'), dtstart=event_time_cutoff)
				### MASSIVE HACK ALERT
				_apply_monkey_patch(rrule)
				### END MASSIVE HACK ALERT
				# Find the next event in the recurrence that isn't an exception
				search_date = after
				while True:
					search_date = rrule.after(search_date)
					if search_date is None or search_date - cutoff_delay not in exception_times:
						break
				event_time_cutoff = search_date
				if event_time_cutoff is None:
					continue
				event_time = event_time_cutoff - cutoff_delay
			if event_time_cutoff > after:
				events.append((event_name, event_time))
	if all:
		events.sort(key=operator.itemgetter(1))
		return events
	if events:
		event_name, event_time = min(events, key=operator.itemgetter(1))
		event_wait = (event_time - after).total_seconds()
		return event_name, event_time, event_wait
	else:
		return None, None, None

def _apply_monkey_patch(rrule):
	"""
	The processing in dateutil.rrule is not properly timezone-aware, mostly because
	Python's timezone handling is far from ideal. In particular, it will claim that,
	for instance, a week after "2014-03-06 19:00:00 PST" is "2014-03-13 19:00:00 PST",
	when in fact the correct answer is "2014-03-13 19:00:00 PDT", as daylight savings
	has started.

	Notably, the time from the original time to the time 1 week later is not 7*24 hours
	when calculated correctly.

	We monkey-patch the rrule class so that all the datetimes that come out of it are
	re-localised, so that the naive hour/minute values are preserved, but the DST flag
	is changed. This means that the corrected dates are what is seen by rrule.after(),
	when it does comparisons using the dates, so the correct results should come out.

	This is a hack that messes with the internals of the library, and as such is far
	from a good idea. It was written against dateutil 2.2, and no guarantees that it
	will work with any other version of that library. A better solution would be
	appreciated, even if it means ditching dateutil for a better library that does
	what we want it to here.
	"""
	import functools
	old_iter = rrule._iter
	@functools.wraps(old_iter)
	def new_iter(*args, **kwargs):
		# If the rule is Daily/Weekly/Monthly/etc, then we want to keep the naive
		# date/time values, eg 1 day after "7PM PST" is still "7pm PDT"
		# even though that's only 23 hours difference.
		# If the rule is Hourly/etc, then we want to use the timezone-aware time,
		# eg one hour after "1:30AM PST" should be "3:30AM PDT", as that is
		# a time gap of one actual hour.
		if rrule._freq <= dateutil.rrule.DAILY:
			for dt in old_iter(*args, **kwargs):
				yield dt.tzinfo.localize(dt.replace(tzinfo=None))
		else:
			for dt in old_iter(*args, **kwargs):
				yield dt.tzinfo.normalize(dt)
	rrule._iter = new_iter
