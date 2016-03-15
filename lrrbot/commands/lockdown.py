import lrrbot.decorators
from lrrbot.main import bot

@bot.command("(mod|sub)only")
@lrrbot.decorators.mod_only
def mod_only(lrrbot, conn, event, respond_to, level):
	"""
	Command: !modonly
	Command: !subonly
	Section: misc

	Ignore all subsequent commands from non-mods or non-subscribers.
	"""
	with lrrbot.state.begin(write=True) as state:
		state["access"] = level
	conn.privmsg(respond_to, "Commands from non-%ss are now ignored." % level)

@bot.command("(?:mod|sub)only off")
@lrrbot.decorators.mod_only
def mod_only_off(lrrbot, conn, event, respond_to):
	"""
	Command: !modonly off
	Command: !subonly off
	Section: misc

	Disable lockdown.
	"""
	with lrrbot.state.begin(write=True) as state:
		state["access"] = "all"
	conn.privmsg(respond_to, "Lockdown disabled.")
