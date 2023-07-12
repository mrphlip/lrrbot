import lrrbot.decorators
from lrrbot.main import bot
from common import space
from common import twitch
from common import utils

@bot.command("live")
@lrrbot.decorators.throttle()
@lrrbot.decorators.private_reply_when_live
async def live(lrrbot, conn, event, respond_to):
	"""
	Command: !live

	Post the currenly live fanstreamers.
	"""

	streams = await twitch.get_streams_followed()
	if streams == []:
		return conn.privmsg(respond_to, "No fanstreamers currently live.")

	streams.sort(key=lambda e: e["user_name"])

	tag = "Currently live fanstreamers: "

	# Full message
	message = tag + ", ".join([
		"%s (https://twitch.tv/%s%s)%s%s" % (
			data["user_name"],
			data["user_login"],
			space.SPACE,
			" is playing %s" % data["game_name"] if data.get("game_name") is not None else "",
			" (%s)" % data["title"] if data.get("title") not in [None, ""] else ""
		) for data in streams
	])
	if utils.check_length(message):
		return conn.privmsg(respond_to, message)

	# Shorter message
	message = tag + ", ".join([
		"%s (https://twitch.tv/%s%s)%s" % (
			data["user_name"],
			data["user_login"],
			space.SPACE,
			" is playing %s" % data["game_name"] if data.get("game_name") is not None else "",
		) for data in streams
	])
	if utils.check_length(message):
		return conn.privmsg(respond_to, message)

	# Shortest message
	message = tag + ", ".join([
		"%s (https://twitch.tv%s%s)" % (
			data["user_name"],
			data["user_login"],
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
	conn.privmsg(respond_to, "Currently the fanlist cannot be edited. Contact mrphlip if you want to be added.")

@bot.command("live unregister")
async def unregister_self(lrrbot, conn, event, respond_to):
	"""
	Command: !live unregister

	Unregister your channel as a fanstreamer channel.
	"""
	conn.privmsg(respond_to, "Currently the fanlist cannot be edited. Contact mrphlip if you want to be removed.")

@bot.command("live register (.*)")
@lrrbot.decorators.mod_only
async def register(lrrbot, conn, event, respond_to, channel):
	"""
	Command: !live register CHANNEL

	Register CHANNEL as a fanstreamer channel.
	"""
	conn.privmsg(respond_to, "Currently the fanlist cannot be edited.")

@bot.command("live unregister (.*)")
@lrrbot.decorators.mod_only
async def unregister(lrrbot, conn, event, respond_to, channel):
	"""
	Command: !live unregister CHANNEL

	Unregister CHANNEL as a fanstreamer channel.
	"""
	conn.privmsg(respond_to, "Currently the fanlist cannot be edited.")
