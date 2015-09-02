from lrrbot.main import bot
from lrrbot import twitch
from lrrbot import storage
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

	storage.data.setdefault("fan_channels", [])
	new_channels = list(channels.difference(storage.data["fan_channels"]))
	channels_data = yield from asyncio.gather(*[twitch.get_stream_info(channel) for channel in new_channels], loop=loop, return_exceptions=True)
	for channel, data in zip(new_channels, channels_data):
		if isinstance(data, dict) and "error" not in data:
			storage.data["fan_channels"].append(channel)
	storage.save()

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

	streams = yield from asyncio.gather(*[
		twitch.get_stream_info(channel)
		for channel in storage.data.get("fan_channels", [])
	], loop=lrrbot.loop)
	streams = [data for data in streams if data.get("stream") is not None]
	if streams == []:
		return conn.privmsg(respond_to, "No fanstreamers currently live.")

	streams.sort(key=lambda e: e["stream"]["channel"]["display_name"])

	tag = "Currently live fanstreamers: "

	# Full message
	message = tag + ", ".join([
		"%s (%s)%s%s" % (
			data["stream"]["channel"]["display_name"],
			data["stream"]["channel"]["url"],
			" is playing %s" % data["stream"]["game"] if data["stream"].get("game") is not None else "",
			" (%s)" % data["stream"]["channel"]["status"] if data["stream"]["channel"].get("status") not in [None, ""] else ""
		) for data in streams
	])
	if len(message) <= 450:
		return conn.privmsg(respond_to, message)

	# Shorter message
	message = tag + ", ".join([
		"%s (%s)%s" % (
			data["stream"]["channel"]["display_name"],
			data["stream"]["channel"]["url"],
			" is playing %s" % data["stream"]["game"] if data["stream"].get("game") is not None else "",
		) for data in streams
	])
	if len(message) <= 450:
		return conn.privmsg(respond_to, message)

	# Shortest message
	message = tag + ", ".join([
		"%s (%s)" % (
			data["stream"]["channel"]["display_name"],
			data["stream"]["channel"]["url"]
		) for data in streams
	])
	return conn.privmsg(respond_to, utils.shorten(message, 450))


@bot.command("live register")
def register_self(lrrbot, conn, event, respond_to):
	"""
	Command: !live register

	Register your channel as a fanstreamer channel.
	"""
	channel = irc.client.NickMask(event.source).nick.lower()
	storage.data["fan_channels"] = list(set(storage.data.get("fan_channels", []) + [channel]))
	conn.privmsg(respond_to, "Channel '%s' added to the fanstreamer list." % channel)

@bot.command("live register (.*)")
@utils.mod_only
def register(lrrbot, conn, event, respond_to, channel):
	"""
	Command: !live register CHANNEL

	Register CHANNEL as a fanstreamer channel.
	"""
	storage.data["fan_channels"] = list(set(storage.data.get("fan_channels", []) + [channel]))
	conn.privmsg(respond_to, "Channel '%s' added to the fanstreamer list." % channel)
