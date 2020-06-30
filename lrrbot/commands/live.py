import common.http
import lrrbot.decorators
from lrrbot.main import bot
from common import googlecalendar
from common import gdata
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
import textwrap

@utils.cache(24 * 60 * 60)
async def extract_new_channels(loop):
	token = await gdata.get_oauth_token(["https://www.googleapis.com/auth/calendar.events.readonly"])
	headers = {"Authorization": "%(token_type)s %(access_token)s" % token}
	data = await common.http.request_coro(googlecalendar.EVENTS_URL % urllib.parse.quote(googlecalendar.CALENDAR_FAN), {
		"maxResults": "25000",
	}, headers=headers)
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

	follows = await twitch.get_follows_channels()
	old_channels = {channel["channel"]["name"] for channel in follows}
	old_channels.add(config["channel"])

	futures = [twitch.follow_channel(channel) for channel in channels.difference(old_channels)]
	await asyncio.gather(*futures, loop=loop, return_exceptions=True)

@bot.command("live")
@lrrbot.decorators.throttle()
@lrrbot.decorators.private_reply_when_live
async def live(lrrbot, conn, event, respond_to):
	"""
	Command: !live

	Post the currenly live fanstreamers.
	"""

	try:
		await extract_new_channels(lrrbot.loop)
	except urllib.error.HTTPError:
		pass

	streams = await twitch.get_streams_followed()
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
	if utils.check_length(message):
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
	if utils.check_length(message):
		return conn.privmsg(respond_to, message)

	# Shortest message
	message = tag + ", ".join([
		"%s (%s%s)" % (
			data["channel"]["display_name"],
			data["channel"]["url"],
			space.SPACE
		) for data in streams
	])
	return conn.privmsg(respond_to, utils.trim_length(message))

@bot.command("live register")
async def register_self(lrrbot, conn, event, respond_to):
	"""
	Command: !live register

	Register your channel as a fanstreamer channel.
	"""
	channel = irc.client.NickMask(event.source).nick.lower()
	await twitch.follow_channel(channel)
	conn.privmsg(respond_to, "Channel '%s' added to the fanstreamer list." % channel)

@bot.command("live unregister")
async def unregister_self(lrrbot, conn, event, respond_to):
	"""
	Command: !live unregister

	Unregister your channel as a fanstreamer channel.
	"""
	channel = irc.client.NickMask(event.source).nick.lower()
	await twitch.unfollow_channel(channel)
	conn.privmsg(respond_to, "Channel '%s' removed from the fanstreamer list." % channel)

@bot.command("live register (.*)")
@lrrbot.decorators.mod_only
async def register(lrrbot, conn, event, respond_to, channel):
	"""
	Command: !live register CHANNEL

	Register CHANNEL as a fanstreamer channel.
	"""
	try:
		await twitch.follow_channel(channel)
		conn.privmsg(respond_to, "Channel '%s' added to the fanstreamer list." % channel)
	except urllib.error.HTTPError:
		conn.privmsg(respond_to, "'%s' isn't a Twitch channel." % channel)

@bot.command("live unregister (.*)")
@lrrbot.decorators.mod_only
async def unregister(lrrbot, conn, event, respond_to, channel):
	"""
	Command: !live unregister CHANNEL

	Unregister CHANNEL as a fanstreamer channel.
	"""
	try:
		await twitch.unfollow_channel(channel)
		conn.privmsg(respond_to, "Channel '%s' removed from the fanstreamer list." % channel)
	except urllib.error.HTTPError:
		conn.privmsg(respond_to, "'%s' isn't a Twitch channel." % channel)
