import asyncio
import datetime
import logging
import random

import dateutil.parser
import pytz
import irc.client
import sqlalchemy

import common.http
import common.time
import common.storm
import lrrbot.decorators
from common import googlecalendar
from common import utils
from common.account_providers import ACCOUNT_PROVIDER_TWITCH
from common.config import config
from common import twitch
from lrrbot import storage
from lrrbot.command_parser import Blueprint
from lrrbot.commands.static import get_response

blueprint = Blueprint()
log = logging.getLogger('misc')

@blueprint.command(r"test")
@lrrbot.decorators.mod_only
def test(bot, conn, event, respond_to):
	conn.privmsg(respond_to, "Test")

@blueprint.command(r"storm(?:counts?)?")
@lrrbot.decorators.throttle()
def stormcount(bot, conn, event, respond_to):
	"""
	Command: !storm
	Command: !stormcount
	Section: info

	Show the current storm counts.
	"""
	twitch_subscription = common.storm.get(bot.engine, bot.metadata, 'twitch-subscription')
	twitch_resubscription = common.storm.get(bot.engine, bot.metadata, 'twitch-resubscription')
	twitch_follow = common.storm.get(bot.engine, bot.metadata, 'twitch-follow')
	twitch_cheer = common.storm.get(bot.engine, bot.metadata, 'twitch-cheer')
	patreon_pledge = common.storm.get(bot.engine, bot.metadata, 'patreon-pledge')
	youtube_membership = common.storm.get(bot.engine, bot.metadata, 'youtube-membership')
	youtube_membership_milestone = common.storm.get(bot.engine, bot.metadata, 'youtube-membership-milestone')
	youtube_super_chat = common.storm.get(bot.engine, bot.metadata, 'youtube-super-chat')
	youtube_super_sticker = common.storm.get(bot.engine, bot.metadata, 'youtube-super-sticker')
	storm_count = common.storm.get_combined(bot.engine, bot.metadata)
	conn.privmsg(respond_to, "Today's storm count: %d (new subscribers: %d, returning subscribers: %d, new patrons: %d, new YouTube members: %d, returning Youtube members: %d), bits cheered: %d, new followers: %d, YouTube super chats: %d, YouTube super stickers: %d" % (
		storm_count,
		twitch_subscription,
		twitch_resubscription,
		patreon_pledge,
		youtube_membership,
		youtube_membership_milestone,
		twitch_cheer,
		twitch_follow,
		youtube_super_chat,
		youtube_super_sticker,
	))

@blueprint.command(r"spam(?:count)?")
@lrrbot.decorators.throttle()
def spamcount(bot, conn, event, respond_to):
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

# When Desert Bus starts
DESERTBUS_START = config["timezone"].localize(datetime.datetime(2025, 5, 23, 16, 0))
# When !desertbus should stop claiming the run is still active
#DESERTBUS_END = DESERTBUS_START + datetime.timedelta(days=6)  # Six days of plugs should be long enough
DESERTBUS_END = DESERTBUS_START + datetime.timedelta(hours=24)

@blueprint.command(r"next( .*)?")
@lrrbot.decorators.throttle()
async def next(bot, conn, event, respond_to, timezone):
	"""
	Command: !next
	Section: info

	Gets the next scheduled stream from the LoadingReadyLive calendar

	Can specify a timezone, to show stream in your local time, eg: !next America/New_York

	If no time zone is specified, times will be shown in Moonbase time.
	"""
	message, eventtime = await googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL, tz=timezone)
	if datetime.datetime.now(datetime.timezone.utc) < DESERTBUS_END and eventtime > DESERTBUS_START:
		# If someone says !next before/during Desert Bus, plug that instead
		desertbus(bot, conn, event, respond_to, timezone)
	else:
		conn.privmsg(respond_to, message)

@blueprint.command(r"(?:db ?count(?: |-)?down|db ?next|next ?db)( .*)?")
@lrrbot.decorators.throttle()
def desertbus(bot, conn, event, respond_to, timezone):
	"""
	Command: !db countdown
	Command: !db next
	Command: !next db
	Section: info

	Shows the countdown until the next Desert Bus for Hope marathon begins.
	"""
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
			googlecalendar.DISPLAY_FORMAT_WITH_DATE), nice_duration))
	elif now < DESERTBUS_END:
		conn.privmsg(respond_to, "Desert Bus for Hope is currently live! Go watch it now at https://desertbus.org/ or https://twitch.tv/desertbus")
	else:
		if now.month < 11:
			when = "in November"
		else:
			when = "next year"
		conn.privmsg(respond_to, f"Desert Bus for Hope will return {when}, start saving your donation money now!")

@blueprint.command(r"nextfan( .*)?")
@lrrbot.decorators.throttle()
@lrrbot.decorators.private_reply_when_live
async def nextfan(bot, conn, event, respond_to, timezone):
	"""
	Command: !nextfan
	Section: info

	Gets the next scheduled stream from the fan-streaming calendar
	"""
	message, _ = await googlecalendar.get_next_event_text(googlecalendar.CALENDAR_FAN, tz=timezone, include_current=True)
	conn.privmsg(respond_to, message)

@blueprint.command(r"time")
@lrrbot.decorators.throttle()
def time(bot, conn, event, respond_to):
	"""
	Command: !time
	Section: misc

	Post the current moonbase time.
	"""
	now = datetime.datetime.now(config["timezone"])
	conn.privmsg(respond_to, "Current moonbase time: %s" % now.strftime("%l:%M %p"))

@blueprint.command(r"time 24")
@lrrbot.decorators.throttle()
def time24(bot, conn, event, respond_to):
	"""
	Command: !time 24
	Section: misc

	Post the current moonbase time using a 24-hour clock.
	"""
	now = datetime.datetime.now(config["timezone"])
	conn.privmsg(respond_to, "Current moonbase time: %s" % now.strftime("%H:%M"))

@blueprint.command(r"viewers")
@lrrbot.decorators.throttle()
async def viewers(bot, conn, event, respond_to):
	"""
	Command: !viewers
	Section: info

	Post the number of viewers currently watching the stream
	"""
	stream_info = await twitch.get_info()
	if stream_info:
		viewers = stream_info.get("viewer_count")
	else:
		viewers = None

	chatters = len(bot.channels["#%s" % config["channel"]].users())
	# Twitch stops sending JOINs and PARTs at 1000 users. Need to double-check if over.
	if chatters > 950:
		chatters = await twitch.get_number_of_chatters()

	if viewers is not None:
		viewers = "%d %s viewing the stream." % (viewers, "user" if viewers == 1 else "users")
	else:
		viewers = "Stream is not live."
	chatters = "%d %s in the chat." % (chatters, "user" if chatters == 1 else "users")
	conn.privmsg(respond_to, "%s %s" % (viewers, chatters))

async def uptime_msg(stream_info=None, factor=1):
	if stream_info is None:
		stream_info = await twitch.get_info()
	if stream_info and stream_info.get("started_at"):
		start = dateutil.parser.parse(stream_info["started_at"])
		now = datetime.datetime.now(datetime.timezone.utc)
		return "The stream has been live for %s." % common.time.nice_duration((now - start) * factor, 0)
	elif stream_info and stream_info.get('live'):
		return "Twitch won't tell me when the stream went live."
	else:
		if factor == 7:
			if random.random() < 0.9:
				return "Not much. What's up with you, dog?"
			else:
				return "Not much. What's !updog with you?"
		else:
			return "The stream is not live."

@blueprint.command(r"uptime")
@lrrbot.decorators.throttle()
async def uptime(bot, conn, event, respond_to):
	"""
	Command: !uptime
	Section: info

	Post the duration the stream has been live.
	"""
	conn.privmsg(respond_to, await uptime_msg())

@blueprint.command(r"updog")
@lrrbot.decorators.throttle()
async def updog(bot, conn, event, respond_to):
	# intentionally not in help
	conn.privmsg(respond_to, await uptime_msg(factor=7) + " lrrSPOT")

@utils.cache(30) # We could easily be sending a bunch of these at once, and the info doesn't change often
async def get_status_msg(bot):
	messages = []
	stream_info = await twitch.get_info()
	if stream_info and stream_info.get('live'):
		game_id = await bot.get_game_id()
		show_id = bot.get_show_id()

		shows = bot.metadata.tables["shows"]
		games = bot.metadata.tables["games"]
		game_per_show_data = bot.metadata.tables["game_per_show_data"]
		with bot.engine.connect() as conn:
			show = conn.execute(sqlalchemy.select(shows.c.name)
				.where(shows.c.id == show_id)
				.where(shows.c.string_id != "")).first()
			if show is not None:
				show, = show

			if game_id is not None:
				game, = conn.execute(sqlalchemy.select(
					sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name)
				).select_from(
					games.outerjoin(game_per_show_data,
						(game_per_show_data.c.game_id == games.c.id) &
							(game_per_show_data.c.show_id == show_id))
				).where(games.c.id == game_id)).first()
			else:
				game = None

		if game and show:
			messages.append("Currently playing %s on %s." % (game, show))
		elif game:
			messages.append("Currently playing %s." % game)
		elif show:
			messages.append("Currently showing %s." % show)
		messages.append(await uptime_msg(stream_info))
	else:
		message, _ = await googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL)
		messages.append(message)
	advice = get_response(bot, "advice")
	if advice:
		messages.append(advice)
	return ' '.join(messages)

async def send_status(bot, conn, target):
	conn.privmsg(target, await get_status_msg(bot))

@blueprint.command(r"status")
async def status(bot, conn, event, respond_to):
	"""
	Command: !status
	Section: info

	Send you a quick status message about the stream. If the stream is live, this
	will include what game is being played, and how long the stream has been live.
	Otherwise, it will tell you about the next scheduled stream.
	"""
	source = irc.client.NickMask(event.source)
	await send_status(bot, conn, source.nick)

@blueprint.command(r"auto(?: |-)?status")
def autostatus_check(bot, conn, event, respond_to):
	"""
	Command: !autostatus
	Section: info

	Check whether you are set to be automatically sent status messages when join join the channel.
	"""
	source = irc.client.NickMask(event.source)
	accounts = bot.metadata.tables["accounts"]
	with bot.engine.connect() as pg_conn:
		enabled = pg_conn.execute(
			sqlalchemy.select(accounts.c.autostatus)
				.where(accounts.c.provider == ACCOUNT_PROVIDER_TWITCH)
				.where(accounts.c.provider_user_id == event.tags["user-id"])
		).scalar_one_or_none()
	if enabled:
		conn.privmsg(source.nick, "Auto-status is enabled. Disable it with: !autostatus off")
	else:
		conn.privmsg(source.nick, "Auto-status is disabled. Enable it with: !autostatus on")

@blueprint.command(r"auto(?: |-)?status (on|off)")
def autostatus_set(bot, conn, event, respond_to, enable):
	"""
	Command: !autostatus on
	Command: !autostatus off
	Section: info

	Enable or disable automatically sending status messages when you join the channel.
	"""
	source = irc.client.NickMask(event.source)
	enable = enable.lower() == "on"
	accounts = bot.metadata.tables["accounts"]
	with bot.engine.connect() as pg_conn:
		pg_conn.execute(
			accounts.update()
				.where(accounts.c.provider == ACCOUNT_PROVIDER_TWITCH)
				.where(accounts.c.provider_user_id == event.tags["user-id"]),
			{"autostatus": enable}
		)
		pg_conn.commit()
	if enable:
		conn.privmsg(source.nick, "Auto-status enabled.")
	else:
		conn.privmsg(source.nick, "Auto-status disabled.")

@blueprint.on_init
def register_autostatus_on_join(bot):
	def autostatus_on_join(conn, event):
		source = irc.client.NickMask(event.source)
		accounts = bot.metadata.tables["accounts"]
		with bot.engine.connect() as pg_conn:
			enabled = pg_conn.execute(sqlalchemy.select(accounts.c.autostatus)
				.where(accounts.c.provider == ACCOUNT_PROVIDER_TWITCH)
				.where(accounts.c.name == source.nick)).scalar_one_or_none()
			if enabled:
				asyncio.ensure_future(send_status(bot, conn, source.nick), loop=bot.loop)
	bot.reactor.add_global_handler('join', autostatus_on_join, 99)
