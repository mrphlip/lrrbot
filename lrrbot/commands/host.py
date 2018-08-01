from common.config import config

from lrrbot.main import bot
import lrrbot.decorators

@bot.command("host (.*?)")
@lrrbot.decorators.mod_only
def host(lrrbot, conn, event, respond_to, host_target):
	"""
	Command: !host CHANNEL
	Section: misc

	Host CHANNEL. Basically the same as `/host CHANNEL`.
	"""
	conn.privmsg("#" + config['channel'], ".host %s" % host_target)
	conn.privmsg(respond_to, "Enabled hosting of %s" % host_target)

@bot.command("unhost")
@lrrbot.decorators.mod_only
def unhost(lrrbot, conn, event, respond_to):
	"""
	Command: !unhost
	Section: misc

	Disable hosting. Basically the same as `/unhost`.
	"""
	conn.privmsg("#" + config['channel'], ".unhost")
	conn.privmsg(respond_to, "Disabled hosting.")
