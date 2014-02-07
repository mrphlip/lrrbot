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
				event_time_cutoff = rrule.after(after)
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
