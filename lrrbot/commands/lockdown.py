import lrrbot.decorators
from lrrbot.command_parser import Blueprint

blueprint = Blueprint()

@blueprint.command(r"(mod|sub)only")
@lrrbot.decorators.mod_only
def mod_only(bot, conn, event, respond_to, level):
	"""
	Command: !modonly
	Command: !subonly
	Section: misc

	Ignore all subsequent commands from non-mods or non-subscribers.
	"""
	bot.access = level
	conn.privmsg(respond_to, "Commands from non-%ss are now ignored." % level)

@blueprint.command(r"(?:mod|sub)only off")
@lrrbot.decorators.mod_only
def mod_only_off(bot, conn, event, respond_to):
	"""
	Command: !modonly off
	Command: !subonly off
	Section: misc

	Disable lockdown.
	"""
	bot.access = "all"
	conn.privmsg(respond_to, "Lockdown disabled.")
