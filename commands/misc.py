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

	If no time is specified, times will be shown in Moonbase time.
	"""
	conn.privmsg(respond_to, googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL, tz=timezone))

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
def time(lrrbot, conn, event, respond_to):
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

	stream_info = utils.http_request("https://api.twitch.tv/kraken/streams/%s" % config['channel'])
	stream_info = json.loads(stream_info)
	if stream_info["stream"] is not None:
		start = dateutil.parser.parse(stream_info["stream"]["created_at"])
		now = datetime.datetime.now(datetime.timezone.utc)
		conn.privmsg(respond_to, "The stream has been live for %s" % utils.nice_duration(now-start, 0))
	else:
		conn.privmsg(respond_to, "The stream is not live.")
