import datetime
import json
import logging
import random

import dateutil.parser
import pytz
import irc.client

import common.http
import common.time
import lrrbot.decorators
from common import utils
from common.config import config
from lrrbot import googlecalendar, storage, twitch
from lrrbot.main import bot

log = logging.getLogger('misc')

@bot.command("test")
@lrrbot.decorators.mod_only
def test(lrrbot, conn, event, respond_to):
	conn.privmsg(respond_to, "Test")

@bot.command("storm(?:count)?")
@lrrbot.decorators.throttle()
def stormcount(lrrbot, conn, event, respond_to):
	"""
	Command: !storm
	Command: !stormcount
	Section: info

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
@lrrbot.decorators.throttle()
def spamcount(lrrbot, conn, event, respond_to):
	"""
	Command: !spam
	Command: !spamcount
	Section: misc

	Show the number of users who have been automatically banned today for spamming
	"""
	today = datetime.datetime.now(config["timezone"]).date().toordinal()
	if today != storage.data.get("spam", {}).get("date"):
		storage.data["spam"] = {
			"date": today,
			"count": [0, 0, 0],
		}
		storage.save()
	conn.privmsg(respond_to, "Today's spam counts: %d hits, %d repeat offenders, %d bannings" % tuple(
		storage.data["spam"]["count"]))

DESERTBUS_START = datetime.datetime(2015, 11, 14, 10, 0, tzinfo=config["timezone"])
DESERTBUS_PRESTART = datetime.datetime(2015, 11, 12, 14, 0, tzinfo=config["timezone"])  # during the last stream before DB
DESERTBUS_END = DESERTBUS_START + datetime.timedelta(days=6)  # Six days of plugs should be long enough

@bot.command("next( .*)?")
@lrrbot.decorators.throttle()
def next(lrrbot, conn, event, respond_to, timezone):
	"""
	Command: !next
	Section: info

	Gets the next scheduled stream from the LoadingReadyLive calendar

	Can specify a timezone, to show stream in your local time, eg: !next America/New_York

	If no time zone is specified, times will be shown in Moonbase time.
	"""
	if DESERTBUS_PRESTART < datetime.datetime.now(datetime.timezone.utc) < DESERTBUS_END:
		# If someone says !next before/during Desert Bus, plug that instead
		desertbus(lrrbot, conn, event, respond_to, timezone)
	else:
		conn.privmsg(respond_to, googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL, tz=timezone))

@bot.command("desert ?bus( .*)?")
@lrrbot.decorators.throttle()
def desertbus(lrrbot, conn, event, respond_to, timezone):
	if not timezone:
		timezone = config['timezone']
	else:
		timezone = timezone.strip()
		try:
			timezone = common.time.get_timezone(timezone)
		except pytz.exceptions.UnknownTimeZoneError:
			conn.privmsg(respond_to, "Unknown timezone: %s" % timezone)

	now = datetime.datetime.now(datetime.timezone.utc)

	if now < DESERTBUS_START:
		nice_duration = common.time.nice_duration(DESERTBUS_START - now, 1) + " from now"
		conn.privmsg(respond_to, "Desert Bus for Hope will begin at %s (%s)" % (DESERTBUS_START.astimezone(timezone).strftime(
			googlecalendar.DISPLAY_FORMAT), nice_duration))
	elif now < DESERTBUS_END:
		conn.privmsg(respond_to, "Desert Bus for Hope is currently live! Go watch it now at https://desertbus.org/ or https://twitch.tv/desertbus")
	else:
		conn.privmsg(respond_to, "Desert Bus for Hope will return next year, start saving your donation money now!")

@bot.command("nextfan( .*)?")
@lrrbot.decorators.throttle()
def nextfan(lrrbot, conn, event, respond_to, timezone):
	"""
	Command: !nextfan
	Section: info

	Gets the next scheduled stream from the fan-streaming calendar
	"""
	conn.privmsg(respond_to, googlecalendar.get_next_event_text(googlecalendar.CALENDAR_FAN, tz=timezone, include_current=True))

@bot.command("time")
@lrrbot.decorators.throttle()
def time(lrrbot, conn, event, respond_to):
	"""
	Command: !time
	Section: misc

	Post the current moonbase time.
	"""
	now = datetime.datetime.now(config["timezone"])
	conn.privmsg(respond_to, "Current moonbase time: %s" % now.strftime("%l:%M %p"))

@bot.command("time 24")
@lrrbot.decorators.throttle()
def time24(lrrbot, conn, event, respond_to):
	"""
	Command: !time 24
	Section: misc

	Post the current moonbase time using a 24-hour clock.
	"""
	now = datetime.datetime.now(config["timezone"])
	conn.privmsg(respond_to, "Current moonbase time: %s" % now.strftime("%H:%M"))

@bot.command("viewers")
@lrrbot.decorators.throttle(30) # longer cooldown as this involves 2 API calls
def viewers(lrrbot, conn, event, respond_to):
	"""
	Command: !viewers
	Section: info

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
	chatters = common.http.request("https://tmi.twitch.tv/group/user/%s/chatters" % config["channel"])
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

def uptime_msg(stream_info=None, factor=1):
	if stream_info is None:
		stream_info = twitch.get_info()
	if stream_info and stream_info.get("stream_created_at"):
		start = dateutil.parser.parse(stream_info["stream_created_at"])
		now = datetime.datetime.now(datetime.timezone.utc)
		return "The stream has been live for %s." % common.time.nice_duration((now - start) * factor, 0)
	elif stream_info and stream_info.get('live'):
		return "Twitch won't tell me when the stream went live."
	else:
		return "The stream is not live."

@bot.command("(uptime|updog)")
@lrrbot.decorators.throttle()
def uptime(lrrbot, conn, event, respond_to, command):
	"""
	Command: !uptime
	Section: info

	Post the duration the stream has been live.
	"""
	conn.privmsg(respond_to, uptime_msg(factor=7 if command == "updog" else 1))

@utils.cache(30) # We could easily be sending a bunch of these at once, and the info doesn't change often
def get_status_msg(lrrbot):
	messages = []
	stream_info = twitch.get_info()
	if stream_info and stream_info.get('live'):
		game = lrrbot.get_current_game()
		game = game and game.get("display", game["name"])
		show = lrrbot.show_override or lrrbot.show
		show = show and storage.data.get("shows", {}).get(show, {}).get("name", show)
		if game and show:
			messages.append("Currently playing %s on %s." % (game, show))
		elif game:
			messages.append("Currently playing %s." % game)
		elif show:
			messages.append("Currently showing %s." % show)
		messages.append(uptime_msg(stream_info))
	else:
		messages.append(googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL))
	if 'advice' in storage.data['responses']:
		messages.append(random.choice(storage.data['responses']['advice']['response']))
	return ' '.join(messages)

def send_status(lrrbot, conn, target):
	conn.privmsg(target, get_status_msg(lrrbot))

@bot.command("status")
def status(lrrbot, conn, event, respond_to):
	"""
	Command: !status
	Section: info

	Send you a quick status message about the stream. If the stream is live, this
	will include what game is being played, and how long the stream has been live.
	Otherwise, it will tell you about the next scheduled stream.
	"""
	source = irc.client.NickMask(event.source)
	send_status(lrrbot, conn, source.nick)

@bot.command("auto(?: |-)?status")
def autostatus_check(lrrbot, conn, event, respond_to):
	"""
	Command: !autostatus
	Section: info

	Check whether you are set to be automatically sent status messages when join join the channel.
	"""
	source = irc.client.NickMask(event.source)
	if source.nick.lower() in lrrbot.autostatus:
		conn.privmsg(source.nick, "Auto-status is enabled. Disable it with: !autostatus off")
	else:
		conn.privmsg(source.nick, "Auto-status is disabled. Enable it with: !autostatus on")

@bot.command("auto(?: |-)?status (on|off)")
def autostatus_set(lrrbot, conn, event, respond_to, enable):
	"""
	Command: !autostatus on
	Command: !autostatus off
	Section: info

	Enable or disable automatically sending status messages when you join the channel.
	"""
	source = irc.client.NickMask(event.source)
	nick = source.nick.lower()
	enable = enable.lower() == "on"
	if enable:
		if nick not in lrrbot.autostatus:
			lrrbot.autostatus.add(nick)
			storage.data['autostatus'] = list(lrrbot.autostatus)
			storage.save()
		conn.privmsg(source.nick, "Auto-status enabled.")
	else:
		if nick in lrrbot.autostatus:
			lrrbot.autostatus.remove(nick)
			storage.data['autostatus'] = list(lrrbot.autostatus)
			storage.save()
		conn.privmsg(source.nick, "Auto-status disabled.")
