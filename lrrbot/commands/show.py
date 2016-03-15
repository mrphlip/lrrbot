import lrrbot.decorators
from lrrbot import storage
from lrrbot import twitch
from lrrbot.main import bot

def set_show(lrrbot, show):
	with lrrbot.state.begin(write=True) as state:
		if state.get("show", "") != show.lower():
			state["show"] = show.lower()
			twitch.get_game.reset_throttle()

def show_name(show):
	return storage.data.get("shows", {}).get(show, {}).get("name", show)

@bot.command("show")
@lrrbot.decorators.throttle()
def get_show(lrrbot, conn, event, respond_to):
	"""
	Command: !show
	Section: info

	Post the current show.
	"""
	print_show(lrrbot, conn, respond_to)

def print_show(lrrbot, conn, respond_to):
	with lrrbot.state.begin() as state:
		show_override = state.get("show-override", None)
		show = state.get("show", "")
	if show_override:
		conn.privmsg(respond_to, "Currently live: %s (overridden)" % show_name(show_override))
	elif show:
		conn.privmsg(respond_to, "Currently live: %s" % show_name(show))
	else:
		conn.privmsg(respond_to, "Current show not set.")

@bot.command("show override (.*?)")
@lrrbot.decorators.mod_only
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
	with lrrbot.state.begin(write=True) as state:
		if show == "off":
			del state["show-override"]
		elif show not in storage.data.get("shows", {}):
			shows = sorted(storage.data.get("shows", {}).keys())
			shows = [s for s in shows if s]
			conn.privmsg(respond_to, "Recognised shows: %s" % ", ".join(shows))
			return
		else:
			state["show-override"] = show
	print_show(lrrbot, conn, respond_to)
