from lrrbot.main import bot
from lrrbot import twitch
from lrrbot import googlecalendar
from common import utils
from common.config import config
import asyncio
import json
import urllib.parse
import urllib.error
import irc.client

@utils.cache(24 * 60 * 60)
@asyncio.coroutine
def extract_new_channels(loop):
	data = yield from utils.http_request_coro(googlecalendar.EVENTS_URL % urllib.parse.quote(googlecalendar.CALENDAR_FAN), {
		"key": config["google_key"],
		"maxResults": 25000,
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

	yield from asyncio.gather(*map(twitch.follow_channel, channels.difference(old_channels)), loop=loop, return_exceptions=True)

@bot.command("live")
@utils.throttle()
@asyncio.coroutine
def live(lrrbot, conn, event, respond_to):
	"""
	Command: !live
	
	Post the currenly live fanstreamers.
	"""

	try:
		yield from extract_new_channels(lrrbot.loop)
	except urllib.error.HTTPError:
		pass

	streams = yield from twitch.get_streams_followed()
	if streams == []:
		return conn.privmsg(respond_to, "No fanstreamers currently live.")

	streams.sort(key=lambda e: e["channel"]["display_name"])

	tag = "Currently live fanstreamers: "

	# Full message
	message = tag + ", ".join([
		"%s (%s)%s%s" % (
			data["channel"]["display_name"],
			data["channel"]["url"],
			" is playing %s" % data["game"] if data.get("game") is not None else "",
			" (%s)" % data["channel"]["status"] if data["channel"].get("status") not in [None, ""] else ""
		) for data in streams
	])
	if len(message) <= 450:
		return conn.privmsg(respond_to, message)

	# Shorter message
	message = tag + ", ".join([
		"%s (%s)%s" % (
			data["channel"]["display_name"],
			data["channel"]["url"],
			" is playing %s" % data["game"] if data.get("game") is not None else "",
		) for data in streams
	])
	if len(message) <= 450:
		return conn.privmsg(respond_to, message)

	# Shortest message
	message = tag + ", ".join([
		"%s (%s)" % (
			data["channel"]["display_name"],
			data["channel"]["url"]
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
	yield from twitch.follow_channel(channel)
	conn.privmsg(respond_to, "Channel '%s' added to the fanstreamer list." % channel)

@bot.command("live unregister")
@asyncio.coroutine
def unregister_self(lrrbot, conn, event, respond_to):
	"""
	Command: !live unregister

	Unregister your channel as a fanstreamer channel.
	"""
	channel = irc.client.NickMask(event.source).nick.lower()
	yield from twitch.unfollow_channel(channel)
	conn.privmsg(respond_to, "Channel '%s' removed from the fanstreamer list." % channel)

@bot.command("live register (.*)")
@utils.mod_only
@asyncio.coroutine
def register(lrrbot, conn, event, respond_to, channel):
	"""
	Command: !live register CHANNEL

	Register CHANNEL as a fanstreamer channel.
	"""
	try:
		yield from twitch.follow_channel(channel)
		conn.privmsg(respond_to, "Channel '%s' added to the fanstreamer list." % channel)
	except urllib.error.HTTPError:
		conn.privmsg(respond_to, "'%s' isn't a Twitch channel." % channel)

@bot.command("live unregister (.*)")
@utils.mod_only
@asyncio.coroutine
def unregister(lrrbot, conn, event, respond_to, channel):
	"""
	Command: !live unregister CHANNEL

	Unregister CHANNEL as a fanstreamer channel.
	"""
	try:
		yield from twitch.unfollow_channel(channel)
		conn.privmsg(respond_to, "Channel '%s' removed from the fanstreamer list." % channel)
	except urllib.error.HTTPError:
		conn.privmsg(respond_to, "'%s' isn't a Twitch channel." % channel)
