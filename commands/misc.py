from lrrbot import bot
from config import config
import datetime
import googlecalendar
import utils
import storage
import twitch
import json
import random

@bot.command("test")
@utils.mod_only
def test(lrrbot, conn, event, respond_to):
	conn.privmsg(respond_to, "Test")
	
@bot.command("music")
@utils.throttle()
def music(lrrbot, conn, event, respond_to):
	conn.privmsg(respond_to, "Now playing: %s" % storage.data["music"]["playing"])
	
@bot.command("music playing (.*?)")
@utils.mod_only
def music(lrrbot, conn, event, respond_to, name):
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
	if lrrbot.calendar_override == None:
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
	else:
		now = datetime.datetime.now(config["timezone"])

		conn.privmsg(respond_to, "(Overwritten) %s, current moonbase time %s" % (lrrbot.calendar_override, now.strftime("%I:%M %p")))
		
@bot.command("calendar override (.*?)")
@utils.mod_only
def calendar_override(lrrbot, conn, event, respond_to, response):
	"""
	Command: !calendar override RESPONSE
	
	eg: !calendar override Next rescheduled stream: Video Games with Video James at Thu 12:30 PM PDT 
	
	For when the calendar isn't properly updated

	--command
	Command: !calendar override off
	
	Disable override, go back to getting the next stream from the calendar.
	"""
	if response == "" or response.lower() == "off":
		lrrbot.calendar_override = None
		operation = "disabled"
		message = "Override disabled"
	else:
		lrrbot.calendar_override = response
		operation = "enabled"
		message = "New !next response: %s. " % response
	conn.privmsg(respond_to, message)

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

DICE_NAMES = {
	1: ("a marble", "marbles"),
	2: ("a coin", "coins"),
	4: ("a tetrahedron", "tetrahedra"),
	6: ("a cube", "cubes"),
	8: ("an octahedron", "octahedra"),
	10: ("a pentagonal trapezohedron", "pentagonal trapezohedra"),
	12: ("a dodecahedron", "dodecahedra"),
	20: ("an icosahedron", "icosahedra"),
	100: ("a pair of pentagonal trapezohedra", "pairs of pentagonal trapezohedra"),
}
INSULTS = [
	"Hmm",
	"Huh",
	"Duh",
	"Funny how that works",
	"Surprising everyone"
]
@bot.command("(\d*)d(\d+)")
@utils.throttle(5)
@utils.mod_only
def dice(lrrbot, conn, event, respond_to, count, sides):
	"""
	Command: !d#
	Command: !#d#

	Roll one or more dice. For example: !d20 or !2d6
	"""
	if count == "":
		count = 1
	else:
		count = int(count)
	sides = int(sides)
	plural = (count != 1)

	if count <= 0:
		conn.privmsg(respond_to, "Rolling no things... got nothing. %s." % random.choice(INSULTS))
		return
	elif count > 100:
		if sides in DICE_NAMES:
			name = DICE_NAMES[sides][1]
		else:
			name = "d%ds" % sides
		conn.privmsg(respond_to, "I don't have that many %s..." % name)
		return
	elif sides <= 0:
		conn.privmsg(respond_to, "I'm not getting that close to the black hole" + ("s" if plural else ""))
		return
	elif sides == 1:
		if plural:
			conn.privmsg(respond_to, "Rolling %d marbles... got %d. %s." % (count, count, random.choice(INSULTS)))
		else:
			conn.privmsg(respond_to, "Rolling a marble... got 1. %s." % random.choice(INSULTS))
		return
	elif sides >= 1000:
		conn.privmsg(respond_to, "Are you sure you want THE EVENT to happen? [y/n]")
		return

	rolls = [random.randint(1, sides) for i in range(count)]
	result = sum(rolls)
	if sides == 2:
		result -= count # as though we were rolling 0 and 1, instead of 1 and 2
		if plural:
			conn.privmsg(respond_to, "Flipping %d coins... got %d %s and %d %s." % (count, result, "heads" if result == 1 else "headses", count - result, "tails" if count - result == 1 else "tailses"))
		else:
			conn.privmsg(respond_to, "Flipping a coin... got %s." % ("Heads", "Tails")[result])
	else:
		if sides in DICE_NAMES:
			if plural:
				name = "%d %s" % (count, DICE_NAMES[sides][1])
			else:
				name = DICE_NAMES[sides][0]
		else:
			if plural:
				name = "%dd%d" % (count, sides)
			else:
				name = "d%d" % sides
		if plural and count <= 10 and sides <= 1000:
			conn.privmsg(respond_to, "Rolling %s... got %d (%s)." % (name, result, ", ".join(str(i) for i in rolls)))
		else:
			conn.privmsg(respond_to, "Rolling %s... got %d." % (name, result))

@bot.command("coin")
def coin(lrrbot, conn, event, respond_to):
	dice(lrrbot, conn, event, respond_to, 1, 2)
