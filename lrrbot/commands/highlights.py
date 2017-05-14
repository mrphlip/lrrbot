import irc.client

import lrrbot.decorators
from common import utils, gdata
from common.highlights import SPREADSHEET, format_row
from common import twitch
from lrrbot.main import bot
import irc.client
import asyncio

import dateutil.parser
import datetime

@bot.command("highlight (.*?)")
@lrrbot.decorators.public_only
@lrrbot.decorators.sub_only
@asyncio.coroutine
def highlight(lrrbot, conn, event, respond_to, description):
	source = irc.client.NickMask(event.source)
	stream_info = twitch.get_info()
	if not stream_info["live"]:
		conn.privmsg(source.nick, "The highlights command has been discontinued, please use the \"Clip\" button instead.")
		return
	now = datetime.datetime.now(datetime.timezone.utc)

	for video in (yield from twitch.get_videos(broadcasts=True)):
		uptime = now - dateutil.parser.parse(video["recorded_at"])
		if video["status"] == "recording":
			break
	else:
		with lrrbot.engine.begin() as pg_conn:
			pg_conn.execute(lrrbot.metadata.tables["highlights"].insert(),
				title=stream_info["status"], description=description, time=now, user_id=event.tags["user-id"])
		conn.privmsg(source.nick, "The highlights command has been discontinued, please use the \"Clip\" button instead.")
		return

	yield from gdata.add_rows_to_spreadsheet(SPREADSHEET, [
		format_row(stream_info["status"], description, video, uptime, irc.client.NickMask(event.source).nick)
	])

	conn.privmsg(source.nick, "The highlights command has been discontinued, please use the \"Clip\" button instead.")
