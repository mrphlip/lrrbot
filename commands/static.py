from lrrbot import bot
from config import config
import storage
import random
import utils
import re
import logging

def generate_docstring():
	inverse_responses = {}
	for command, data in storage.data["responses"].items():
		response = data["response"]
		if isinstance(response, (tuple, list)):
			response = tuple(response)
		inverse_responses.setdefault(response, [])
		inverse_responses[response] += [command]
	def generator():
		for response, command in inverse_responses.items():
			fragment = ""
			if isinstance(command, list):
				for cmd in command:
					fragment += "Command: %s%s\n" % (config["commandprefix"], cmd)
			else:
				fragment += "Command: %s%s\n" % (config["commandprefix"], cmd)
			fragment += "Throttled: 5\n"
			fragment += "Literal-Response: true\n"
			fragment += "\n"
			response = response if isinstance(response, str) else random.choice(response)
			fragment += response + "\n"
			yield fragment
	return "\n--command\n".join(generator())

def generate_expression(node):
	return "(%s)" % "|".join(re.escape(c).replace("\\ ", " ") for c in node)

@utils.throttle(5, params=[4])
def static_response(lrrbot, conn, event, respond_to, command):
	log = logging.getLogger('lrrbot')
	if storage.data["responses"][command.lower()]["access"] == "sub":
		if not lrrbot.is_sub(event) and not lrrbot.is_mod(event):0
			log.info("Refusing %s due to inadequate access" % command)
			return
	response = storage.data["responses"][" ".join(command.lower().split())]["response"]
	if isinstance(response, (tuple, list)):
		response = random.choice(response)
	conn.privmsg(respond_to, response)

def modify_commands(commands):
    bot.remove_command(generate_expression(storage.data["responses"]))
    storage.data["responses"] = {" ".join(k.lower().split()): v for k,v in commands.items()}
    storage.save()
    static_response.__doc__ = generate_docstring()
    bot.add_command(generate_expression(storage.data["responses"]), static_response)

static_response.__doc__ = generate_docstring()
bot.add_command(generate_expression(storage.data["responses"]), static_response)
