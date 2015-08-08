import time

import irc.client

from common import utils
from lrrbot import bot, storage, twitch


@bot.command("highlight (.*?)")
@utils.public_only
@utils.sub_only
@utils.throttle(60, notify=utils.Visibility.PUBLIC)
def highlight(lrrbot, conn, event, respond_to, description):
	"""
	Command: !highlight DESCRIPTION
	Section: misc

	For use when something particularly awesome happens onstream, adds an entry on the Highlight Reel spreadsheet: https://docs.google.com/spreadsheets/d/1yrf6d7dPyTiWksFkhISqEc-JR71dxZMkUoYrX4BR40Y

	Note that the highlights won't appear on the spreadsheet immediately, as the link won't be available until the stream finishes and the video is in the archive. It should appear within a day.
	"""
	if not twitch.get_info()["live"]:
		conn.privmsg(respond_to, "Not currently streaming.")
		return
	storage.data.setdefault("staged_highlights", [])
	storage.data["staged_highlights"] += [{
		"time": time.time(),
		"user": irc.client.NickMask(event.source).nick,
		"description": description,
	}]
	storage.save()
	conn.privmsg(respond_to, "Highlight added.")
