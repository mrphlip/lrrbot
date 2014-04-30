from lrrbot import bot
from config import config
import datetime
import googlecalendar
import utils
import storage
import twitch
import json

@bot.command("test")
@utils.mod_only
def test(lrrbot, conn, event, respond_to):
	conn.privmsg(respond_to, "Test")

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

@bot.command("next(?:stream)?|sched(?:ule)?")
@utils.throttle()
def next(lrrbot, conn, event, respond_to):
	"""
	Command: !next
	Command: !nextstream
	Command: !sched
	Command: !schedule

	Gets the next scheduled stream from the calendar
	"""
	event_name, event_time, event_wait = googlecalendar.get_next_event()
	if event_time:
		nice_time = event_time = event_time.astimezone(config["timezone"]).strftime("%a %I:%M %p %Z")
		if event_wait < 0:
			nice_duration = utils.nice_duration(-event_wait, 1) + " ago"
		else:
			nice_duration = utils.nice_duration(event_wait, 1) + " from now"
		conn.privmsg(respond_to, "Next scheduled stream: %s at %s (%s)" % (event_name, nice_time, nice_duration))
	else:
		conn.privmsg(respond_to, "There don't seem to be any upcoming scheduled streams")

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
	Command: !time

	Post the current moonbase time.
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
