from lrrbot import bot
from config import config
import datetime
import googlecalendar
import utils
import storage

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
