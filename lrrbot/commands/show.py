from common import utils
from lrrbot import bot, storage


def set_show(lrrbot, show):
	if lrrbot.show != show.lower():
		lrrbot.show = show.lower()
		lrrbot.get_current_game_real.reset_throttle()

def show_name(show):
	return storage.data.get("shows", {}).get(show, {}).get("name", show)

@bot.command("show")
@utils.throttle(notify=utils.PRIVATE)
def get_show(lrrbot, conn, event, respond_to):
	"""
	Command: !show
	Section: info

	Post the current show.
	"""
	if lrrbot.show_override:
		conn.privmsg(respond_to, "Currently live: %s (overridden)" % show_name(lrrbot.show_override))
	elif lrrbot.show:
		conn.privmsg(respond_to, "Currently live: %s" % show_name(lrrbot.show))
	else:
		conn.privmsg(respond_to, "Current show not set.")

@bot.command("show override (.*?)")
@utils.mod_only
def show_override(lrrbot, conn, event, respond_to, show):
	"""
	Command: !show override ID
	Section: info

	Override the current show.
	--command
	Command: !show override off
	Section: info

	Disable the override.
	"""
	show = show.lower()
	if show == "off":
		lrrbot.show_override = None
	elif show not in storage.data.get("shows", {}):
		shows = sorted(storage.data.get("shows", {}).keys())
		shows = [s for s in shows if s]
		conn.privmsg(respond_to, "Recognised shows: %s" % ", ".join(shows))
		return
	else:
		lrrbot.show_override = show
	return get_show.__wrapped__(lrrbot, conn, event, respond_to)
