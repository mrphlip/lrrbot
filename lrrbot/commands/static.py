import random
import re

from common import utils
from common.config import config
from lrrbot import storage
from lrrbot.main import bot, log


def generate_docstring():
	inverse_responses = {}
	for command, data in storage.data["responses"].items():
		response = data["response"]
		if isinstance(response, (tuple, list)):
			response = tuple(response)
		inverse_responses.setdefault((response, data["access"]), [])
		inverse_responses[(response, data["access"])] += [command]
	def generator():
		for (response, access), command in inverse_responses.items():
			fragment = ""
			if isinstance(command, list):
				for cmd in sorted(command):
					fragment += "Command: %s%s\n" % (config["commandprefix"], cmd)
			else:
				fragment += "Command: %s%s\n" % (config["commandprefix"], cmd)
			fragment += "Throttled: 30\n"
			fragment += "Throttle-Count: 2\n"
			fragment += "Literal-Response: true\n"
			if access == "sub":
				fragment += "Sub-Only: true\n"
			elif access == "mod":
				fragment += "Mod-Only: true\n"
			fragment += "Section: text\n"
			fragment += "\n"
			response = response if isinstance(response, str) else response[0]
			fragment += response + "\n"
			yield fragment
	return "\n--command\n".join(generator())

def generate_expression():
	return "(%s)" % "|".join(re.escape(c).replace("\\ ", " ") for c in storage.data["responses"])

@utils.throttle(30, params=[4], count=2)
def static_response(lrrbot, conn, event, respond_to, command):
	command = " ".join(command.split())
	response_data = storage.data["responses"][command.lower()]
	if response_data["access"] == "sub":
		if not lrrbot.is_sub(event) and not lrrbot.is_mod(event):
			log.info("Refusing %s due to inadequate access" % command)
			return
	if response_data["access"] == "mod":
		if not lrrbot.is_mod(event):
			log.info("Refusing %s due to inadequate access" % command)
			return
	response = response_data["response"]
	if isinstance(response, (tuple, list)):
		response = random.choice(response)
	conn.privmsg(respond_to, response)

def modify_commands(commands):
	storage.data["responses"] = {" ".join(k.lower().split()): v for k,v in commands.items()}
	storage.save()
	generate_hook()

command_expression = None
def generate_hook():
	global command_expression
	if command_expression is not None:
		bot.remove_command(command_expression)
	static_response.__doc__ = generate_docstring()
	command_expression = generate_expression()
	bot.add_command(command_expression, static_response)

generate_hook()
