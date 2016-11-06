import common.http
import lrrbot.decorators
from lrrbot.main import bot
from lrrbot import googlecalendar
from common import space
from common import twitch
from common import utils
from common.config import config
import asyncio
import json
import urllib.parse
import urllib.error
import irc.client
import sqlalchemy

@utils.cache(24 * 60 * 60)
@asyncio.coroutine
def extract_new_channels(loop, token):
	data = yield from common.http.request_coro(googlecalendar.EVENTS_URL % urllib.parse.quote(googlecalendar.CALENDAR_FAN), {
		"key": config["google_key"],
		"maxResults": "25000",
	})
	data = json.loads(data)

	channels = set()

	for event in data["items"]:
		if "location" in event:
			for token in event["location"].split():
				url = urllib.parse.urlparse(token)
				if url.scheme == "":
					url = urllib.parse.urlparse("https://" + token)
				if url.netloc in {"www.twitch.tv", "twitch.tv"}:
					try:
						channel = url.path.split("/")[1].lower()
					except IndexError:
						continue
					channels.add(channel)

	follows = yield from twitch.get_follows_channels()
	old_channels = {channel["channel"]["name"] for channel in follows}
	old_channels.add(config["channel"])

	futures = [twitch.follow_channel(channel, token) for channel in channels.difference(old_channels)]
	yield from asyncio.gather(*futures, loop=loop, return_exceptions=True)

@bot.command("live")
@lrrbot.decorators.throttle()
@lrrbot.decorators.private_reply_when_live
@asyncio.coroutine
def live(lrrbot, conn, event, respond_to):
	"""
	Command: !live

	Post the currenly live fanstreamers.
	"""

	users = lrrbot.metadata.tables["users"]
	with lrrbot.engine.begin() as pg_conn:
		token, = pg_conn.execute(sqlalchemy.select([users.c.twitch_oauth])
			.where(users.c.name == config["username"])).first()

	try:
		yield from extract_new_channels(lrrbot.loop, token)
	except urllib.error.HTTPError:
		pass

	streams = yield from twitch.get_streams_followed(token)
	if streams == []:
		return conn.privmsg(respond_to, "No fanstreamers currently live.")

	streams.sort(key=lambda e: e["channel"]["display_name"])

	tag = "Currently live fanstreamers: "

	# Full message
	message = tag + ", ".join([
		"%s (%s%s)%s%s" % (
			data["channel"]["display_name"],
			data["channel"]["url"],
			space.SPACE,
			" is playing %s" % data["game"] if data.get("game") is not None else "",
			" (%s)" % data["channel"]["status"] if data["channel"].get("status") not in [None, ""] else ""
		) for data in streams
	])
	if len(message) <= 450:
		return conn.privmsg(respond_to, message)

	# Shorter message
	message = tag + ", ".join([
		"%s (%s%s)%s" % (
			data["channel"]["display_name"],
			data["channel"]["url"],
			space.SPACE,
			" is playing %s" % data["game"] if data.get("game") is not None else "",
		) for data in streams
	])
	if len(message) <= 450:
		return conn.privmsg(respond_to, message)

	# Shortest message
	message = tag + ", ".join([
		"%s (%s%s)" % (
			data["channel"]["display_name"],
			data["channel"]["url"],
			space.SPACE
		) for data in streams
	])
	return conn.privmsg(respond_to, utils.shorten(message, 450))

@bot.command("live register")
@asyncio.coroutine
def register_self(lrrbot, conn, event, respond_to):
	"""
	Command: !live register

	Register your channel as a fanstreamer channel.
	"""
	channel = irc.client.NickMask(event.source).nick.lower()
	users = lrrbot.metadata.tables["users"]
	with lrrbot.engine.begin() as pg_conn:
		token, = pg_conn.execute(sqlalchemy.select([users.c.twitch_oauth])
			.where(users.c.name == config["username"])).first()
	yield from twitch.follow_channel(channel, token)
	conn.privmsg(respond_to, "Channel '%s' added to the fanstreamer list." % channel)

@bot.command("live unregister")
@asyncio.coroutine
def unregister_self(lrrbot, conn, event, respond_to):
	"""
	Command: !live unregister

	Unregister your channel as a fanstreamer channel.
	"""
	channel = irc.client.NickMask(event.source).nick.lower()
	users = lrrbot.metadata.tables["users"]
	with lrrbot.engine.begin() as pg_conn:
		token, = pg_conn.execute(sqlalchemy.select([users.c.twitch_oauth])
			.where(users.c.name == config["username"])).first()
	yield from twitch.unfollow_channel(channel, token)
	conn.privmsg(respond_to, "Channel '%s' removed from the fanstreamer list." % channel)

@bot.command("live register (.*)")
@lrrbot.decorators.mod_only
@asyncio.coroutine
def register(lrrbot, conn, event, respond_to, channel):
	"""
	Command: !live register CHANNEL

	Register CHANNEL as a fanstreamer channel.
	"""
	users = lrrbot.metadata.tables["users"]
	with lrrbot.engine.begin() as pg_conn:
		token, = pg_conn.execute(sqlalchemy.select([users.c.twitch_oauth])
			.where(users.c.name == config["username"])).first()
	try:
		yield from twitch.follow_channel(channel, token)
		conn.privmsg(respond_to, "Channel '%s' added to the fanstreamer list." % channel)
	except urllib.error.HTTPError:
		conn.privmsg(respond_to, "'%s' isn't a Twitch channel." % channel)

@bot.command("live unregister (.*)")
@lrrbot.decorators.mod_only
@asyncio.coroutine
def unregister(lrrbot, conn, event, respond_to, channel):
	"""
	Command: !live unregister CHANNEL

	Unregister CHANNEL as a fanstreamer channel.
	"""
	users = lrrbot.metadata.tables["users"]
	with lrrbot.engine.begin() as pg_conn:
		token, = pg_conn.execute(sqlalchemy.select([users.c.twitch_oauth])
			.where(users.c.name == config["username"])).first()
	try:
		yield from twitch.unfollow_channel(channel, token)
		conn.privmsg(respond_to, "Channel '%s' removed from the fanstreamer list." % channel)
	except urllib.error.HTTPError:
		conn.privmsg(respond_to, "'%s' isn't a Twitch channel." % channel)
