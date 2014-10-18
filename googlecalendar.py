import utils
import datetime
import dateutil.parser
import json
from config import config
import urllib.parse
import pytz, pytz.exceptions

CACHE_EXPIRY = 15*60
CALENDAR_LRL = "loadingreadyrun.com_72jmf1fn564cbbr84l048pv1go@group.calendar.google.com"
CALENDAR_FAN = "caffeinatedlemur@gmail.com"
EVENT_COUNT = 10

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/%s/events"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
DISPLAY_FORMAT = "%a %I:%M %p %Z"

HISTORY_PERIOD = datetime.timedelta(hours=1) # How long ago can an event have started to count as "recent"?
LOOKAHEAD_PERIOD = datetime.timedelta(hours=1) # How close together to events have to be to count as "the same time"?

@utils.throttle(CACHE_EXPIRY, params=[0])
def get_upcoming_events(calendar, after=None):
	"""
	Get the next several events from the calendar. Will include the currently-happening
	events (if any) and a number of following events.

	Results are cached, so we get more events than we should need, so that if the
	first few events become irrelevant by the time the cache expires, we still have
	the data we need.
	(Technically, the API quota limits allow us to get the events, for both
	calendars, every 1.7 seconds... but still, caching on principle.)

	The "after" parameter allows overriding the reference time, for testing purposes.
	"""
	if after is None:
		after = datetime.datetime.now(datetime.timezone.utc)
	url = EVENTS_URL % urllib.parse.quote(calendar)
	data = {
		"maxResults": EVENT_COUNT,
		"orderBy": "startTime",
		"singleEvents": "true",
		"timeMin": after.strftime(DATE_FORMAT),
		"timeZone": config['timezone'].zone,
		"key": config['google_key'],
	}
	res = utils.http_request(url, data)
	res = json.loads(res)
	if 'error' in res:
		raise Exception(res['error']['message'])
	formatted_items = []
	for item in res['items']:
		formatted_items.append({
			"id": item['id'],
			"url": item['htmlLink'],
			"title": item['summary'],
			"creator": item['creator']['displayName'],
			"start": dateutil.parser.parse(item['start']['dateTime']),
			"end": dateutil.parser.parse(item['end']['dateTime']),
			"location": item.get('location'),
		})
	return formatted_items

def get_next_event(calendar, after=None, include_current=False):
	"""
	Get the list of events that should be shown by the !next command.

	Our criteria:
	For pulling from the official LRL calendar, we don't care about
	events that are currently happening, as it's likely whoever's using the bot
	knows about the stream that's currently live.
	We'll still pull out the current event if it's only recently started (ie started within
	the last hour, or less than half over for streams shorter than 2 hours), so that
	!next still gives a reasonable response when a stream is running late.

	For the fan calendar, always bring out events that are current, no matter how old
	as users may not be aware of them.
	This is controlled by the include_current param.

	For future events, we show the first event that's starting in the future (or
	recently in the past), and any other events that are starting in less than an hour
	from that event (so if multiple events are scheduled at roughly the same time,
	we get all of them).
	"""
	if after is None:
		after = datetime.datetime.now(datetime.timezone.utc)
	events = get_upcoming_events(calendar, after=after)

	first_future_event = None
	for i, ev in enumerate(events):
		history = (ev['end'] - ev['start'])
		if history > HISTORY_PERIOD:
			history = HISTORY_PERIOD
		reference_time = ev['start'] + history
		if reference_time >= after:
			first_future_event = i
			break
	if first_future_event is None:
		return []

	lookahead_end = events[first_future_event]['start'] + LOOKAHEAD_PERIOD
	return [ev for i,ev in enumerate(events) if (i >= first_future_event or include_current) and ev['start'] < lookahead_end]

def get_next_event_text(calendar, after=None, include_current=None, tz=None, verbose=True):
	"""
	Build the actual human-readable response to the !next command.

	The tz parameter can override the timezone used to display the event times.
	This can be an actual timezone object, or a string timezone name.
	Defaults to moonbase time.
	"""
	if after is None:
		after = datetime.datetime.now(datetime.timezone.utc)
	if not tz:
		tz = config['timezone']
	elif isinstance(tz, str):
		tz = tz.strip()
		try:
			tz = utils.get_timezone(tz)
		except pytz.exceptions.UnknownTimeZoneError:
			return "Unknown timezone: %s" % tz

	events = get_next_event(calendar, after=after, include_current=include_current)
	if not events:
		return "There don't seem to be any upcoming scheduled streams"

	strs = []
	for i, ev in enumerate(events):
		# If several events are at the same time, just show the time once after all of them
		if i == len(events) - 1 or ev['start'] != events[i+1]['start']:
			if verbose:
				if ev['location'] is not None:
					title = "%(title)s ( %(location)s )" % ev
				else:
					title = ev['title']
				if ev['start'] < after:
					nice_duration = utils.nice_duration(after - ev['start'], 1) + " ago"
				else:
					nice_duration = utils.nice_duration(ev['start'] - after, 1) + " from now"
				strs.append("%s at %s (%s)" % (title, ev['start'].astimezone(tz).strftime(DISPLAY_FORMAT), nice_duration))
			else:
				strs.append("%s at %s" % (ev['title'], ev['start'].astimezone(tz).strftime(DISPLAY_FORMAT)))
		else:
			strs.append(ev['title'])
	response = ', '.join(strs)

	if verbose:
		if calendar == CALENDAR_LRL:
			response = "Next scheduled stream: " + response
		elif calendar == CALENDAR_FAN:
			response = "Next scheduled fan stream: " + response

	return utils.shorten(response, 450) # For safety

