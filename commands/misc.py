from lrrbot import bot
from config import config
import datetime
import googlecalendar
import utils
import storage
import twitch
import json
import logging
import urllib.error
import irc.client
import dateutil.parser
import pytz
import bs4

log = logging.getLogger('misc')

@bot.command("test")
@utils.mod_only
def test(lrrbot, conn, event, respond_to):
	conn.privmsg(respond_to, "Test")
	
@bot.command("music")
@utils.throttle()
def music(lrrbot, conn, event, respond_to):
	"""
	Command: !music
	
	Displays the string currently stored in Music: playing:
	"""
	conn.privmsg(respond_to, "Now playing: %s" % storage.data["music"]["playing"])
	
@bot.command("music playing (.*?)")
@utils.mod_only
def music(lrrbot, conn, event, respond_to, name):
	"""
	Command: !music playing NAME
	
	Replaces current Music: playing: string with NAME
	"""
	storage.data['music']["playing"] = name
	storage.save()
	conn.privmsg(respond_to, "Music added, now playing: %s" % name)

@bot.command("storm(?:count)?")
@utils.throttle()
def stormcount(lrrbot, conn, event, respond_to):
	"""
	Command: !storm
	Command: !stormcount

	Show the current storm count (the number of viewers who have subscribed today)
	"""
	today = datetime.datetime.now(config["timezone"]).date().toordinal()
	if today != storage.data.get("storm", {}).get("date"):
		storage.data["storm"] = {
			"date": today,
			"count": 0
		}
		storage.save()
	conn.privmsg(respond_to, "Today's storm count: %d" % storage.data["storm"]["count"])
	
@bot.command("spam(?:count)?")
@utils.throttle()
def spamcount(lrrbot, conn, event, respond_to):
	"""
	Command: !spam
	Command: !spamcount

	Show the number of users who have been automatically banned today for spamming
	"""
	today = datetime.datetime.now(config["timezone"]).date().toordinal()
	if today != storage.data.get("spam", {}).get("date"):
		storage.data["spam"] = {
			"date": today,
			"count": [0, 0, 0],
		}
		storage.save()
	conn.privmsg(respond_to, "Today's spam counts: %d hits, %d repeat offenders, %d bannings" % tuple(storage.data["spam"]["count"]))

DESERTBUS_START = 1415988000
DESERTBUS_START = datetime.datetime.utcfromtimestamp(DESERTBUS_START).replace(tzinfo=datetime.timezone.utc)
DESERTBUS_END = DESERTBUS_START + datetime.timedelta(days=6) # Six days of plugs should be long enough

@bot.command("(?:next(?:stream)?|sched(?:ule)?)( .*)?")
@utils.throttle()
def next(lrrbot, conn, event, respond_to, timezone):
	"""
	Command: !next
	Command: !nextstream
	Command: !sched
	Command: !schedule

	Gets the next scheduled stream from the LoadingReadyLive calendar

	Can specify a timezone, to show stream in your local time, eg: !next America/New_York

	If no time zone is specified, times will be shown in Moonbase time.
	"""
	if datetime.datetime.now(datetime.timezone.utc) < DESERTBUS_END:
		# If someone says !next before/during Desert Bus, plug that instead
		desertbus(lrrbot, conn, event, respond_to, timezone)
	else:
		conn.privmsg(respond_to, googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL, tz=timezone))

@bot.command("desert ?bus( .*)?")
@utils.throttle()
def desertbus(lrrbot, conn, event, respond_to, timezone):
	if not timezone:
		timezone = config['timezone']
	else:
		timezone = timezone.strip()
		try:
			timezone = utils.get_timezone(timezone)
		except pytz.exceptions.UnknownTimeZoneError:
			conn.privmsg(respond_to, "Unknown timezone: %s" % timezone)

	now = datetime.datetime.now(datetime.timezone.utc)

	if now < DESERTBUS_START:
		nice_duration = utils.nice_duration(DESERTBUS_START - now, 1) + " from now"
		conn.privmsg(respond_to, "Desert Bus for Hope will begin at %s (%s)" % (DESERTBUS_START.astimezone(timezone).strftime(googlecalendar.DISPLAY_FORMAT), nice_duration))
	elif now < DESERTBUS_END:
		conn.privmsg(respond_to, "Desert Bus for Hope is currently live! Go watch it now at http://desertbus.org/live/")
	else:
		conn.privmsg(respond_to, "Desert Bus for Hope will return next year, start saving your donation money now!")


@bot.command("(?:nextfan(?:stream)?|fansched(?:ule)?)( .*)?")
@utils.throttle()
def nextfan(lrrbot, conn, event, respond_to, timezone):
	"""
	Command: !nextfan
	Command: !nextfanstream
	Command: !fansched
	Command: !fanschedule

	Gets the next scheduled stream from the fan-streaming calendar
	"""
	conn.privmsg(respond_to, googlecalendar.get_next_event_text(googlecalendar.CALENDAR_FAN, tz=timezone, include_current=True))

@bot.command("time")
@utils.throttle()
def time(lrrbot, conn, event, respond_to):
	"""
	Command: !time

	Post the current moonbase time.
	"""
	now = datetime.datetime.now(config["timezone"])
	conn.privmsg(respond_to, "Current moonbase time: %s" % now.strftime("%l:%M %p"))
	
@bot.command("time 24")
@utils.throttle()
def time24(lrrbot, conn, event, respond_to):
	"""
	Command: !time 24

	Post the current moonbase time using a 24-hour clock.
	"""
	now = datetime.datetime.now(config["timezone"])
	conn.privmsg(respond_to, "Current moonbase time: %s" % now.strftime("%H:%M"))

@bot.command("viewers")
@utils.throttle(30) # longer cooldown as this involves 2 API calls
def viewers(lrrbot, conn, event, respond_to):
	"""
	Command: !viewers

	Post the number of viewers currently watching the stream
	"""
	stream_info = twitch.get_info()
	if stream_info:
		viewers = stream_info.get("viewers")
	else:
		viewers = None
	
	# Since we're using TWITCHCLIENT 3, we don't get join/part messages, so we can't just use
	# len(lrrbot.channels["#loadingreadyrun"].userdict)
	# as that dict won't be populated. Need to call this api instead.
	chatters = utils.http_request("http://tmi.twitch.tv/group/user/%s/chatters" % config["channel"])
	chatters = json.loads(chatters).get("chatter_count")

	if viewers is not None:
		viewers = "%d %s viewing the stream." % (viewers, "user" if viewers == 1 else "users")
	else:
		viewers = "Stream is not live."
	if chatters is not None:
		chatters = "%d %s in the chat." % (chatters, "user" if chatters == 1 else "users")
	else:
		chatters = "No-one in the chat."
	conn.privmsg(respond_to, "%s %s" % (viewers, chatters))

@bot.command("uptime")
@utils.throttle()
def uptime(lrrbot, conn, event, respond_to):
	"""
	Command: !uptime

	Post the duration the stream has been live.
	"""

	stream_info = twitch.get_info()
	if stream_info and stream_info.get("stream_created_at"):
		start = dateutil.parser.parse(stream_info["stream_created_at"])
		now = datetime.datetime.now(datetime.timezone.utc)
		conn.privmsg(respond_to, "The stream has been live for %s" % utils.nice_duration(now-start, 0))
	elif stream_info:
		conn.privmsg(respond_to, "Twitch won't tell me when the stream went live.")
	else:
		conn.privmsg(respond_to, "The stream is not live.")

PATREON_URL = "http://www.patreon.com/loadingreadyrun"

@bot.command("patreon")
@utils.throttle()
def patreon(lrrbot, conn, event, respond_to):
	"""
	Command: !patreon

	Post the number of patrons and the total earnings per month.
	"""
	patreon_body = utils.http_request(PATREON_URL)
	patreon_soup = bs4.BeautifulSoup(patreon_body)

	tag_patrons = patreon_soup.find("div", id="totalPatrons")
	nof_patrons = tag_patrons.string if tag_patrons else "N/A"

	tag_earnings = patreon_soup.find("span", id="totalEarnings")
	total_earnings = tag_earnings.string if tag_earnings else "N/A"

	conn.privmsg(respond_to, "{0} patrons for a total of ${1} per month. {2}".format(
            nof_patrons, total_earnings, PATREON_URL))
