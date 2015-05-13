from common import utils
from lrrbot import bot


@bot.command("(mod|sub)only")
@utils.mod_only
def mod_only(lrrbot, conn, event, respond_to, level):
	"""
	Command: !modonly
	Command: !subonly
	Section: misc

	Ignore all subsequent commands from non-mods or non-subscribers.
	"""
	lrrbot.access = level
	conn.privmsg(respond_to, "Commands from non-%ss are now ignored." % level)

@bot.command("(?:mod|sub)only off")
@utils.mod_only
def mod_only_off(lrrbot, conn, event, respond_to):
	"""
	Command: !modonly off
	Command: !subonly off
	Section: misc

	Disable lockdown.
	"""
	lrrbot.access = "all"
	conn.privmsg(respond_to, "Lockdown disabled.")
