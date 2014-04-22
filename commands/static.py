from lrrbot import bot
from config import config
import storage
import random
import utils
import re

def generate_docstring():
	inverse_responses = {}
	for command, response in storage.data["responses"].items():
		if isinstance(response, (tuple, list)):
			response = frozenset(response)
		inverse_responses.setdefault(response, [])
		inverse_responses[response] += [command]
	def generator():
		for response, command in sorted(inverse_responses.items(), key=lambda e: e[1]):
			fragment = ""
			if isinstance(command, list):
				for cmd in command:
					fragment += "Command: %s%s\n" % (config["commandprefix"], cmd)
			else:
				fragment += "Command: %s%s\n" % (config["commandprefix"], cmd)
			fragment += "Throttled: 5\n"
			fragment += "\n"
			response = response if isinstance(response, str) else "' or '".join(response)
			fragment += "Post '%s'\n" % response
			yield fragment
	return "\n--command\n".join(generator())

@utils.throttle(5, params=[4])
def static_response(lrrbot, conn, event, respond_to, command):
	response = storage.data["responses"][command]
	if isinstance(response, (tuple, list)):
		response = random.choice(response)
	conn.privmsg(respond_to, response)

def modify_commands(commands):
    bot.remove_command("(%s)" % "|".join(re.escape(c) for c in storage.data["responses"]))
    storage.data["responses"] = commands
    storage.save()
    static_response.__doc__ = generate_docstring()
    bot.add_command("(%s)" % "|".join(re.escape(c) for c in storage.data["responses"]), static_response)

static_response.__doc__ = generate_docstring()
bot.add_command("(%s)" % "|".join(re.escape(c) for c in storage.data["responses"]), static_response)
