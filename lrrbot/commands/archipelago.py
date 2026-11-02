import lrrbot.decorators
from lrrbot.command_parser import Blueprint
from common.archipelago import ArchipelagoClient

blueprint = Blueprint()

current_archipelago = None

@blueprint.command(r"archipelago (\S+) (\d+) (\w+)(?: (\S+))?")
@lrrbot.decorators.mod_only
def archipelago_on(bot, conn, event, respond_to, host, port, name, password):
	"""
	Command: !archipelago host port username
	Command: !archipelago host port username password
	Section: misc

	Connect to an Archipelago server and report item unlocks in chat.
	"""
	global current_archipelago
	if current_archipelago:
		current_archipelago.stop()

	current_archipelago = ArchipelagoClient(bot, host, int(port), password, name, conn, respond_to)
	current_archipelago.start()

@blueprint.command(r"archipelago off")
@lrrbot.decorators.mod_only
def mod_only_off(bot, conn, event, respond_to):
	"""
	Command: !archipelago off
	Section: misc

	Disconnect from the Archipelago server.
	"""
	global current_archipelago
	if current_archipelago:
		current_archipelago.stop()
		current_archipelago = None
		conn.privmsg(respond_to, "Archipelago disabled.")
	else:
		conn.privmsg(respond_to, "Archipelago is not connected.")
