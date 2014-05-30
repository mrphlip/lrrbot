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

def generate_explain_docstring():
	return """
	Command: %sexplain TOPIC

	Provide an explanation for a given topic.
	
	Available topics: %s.
	""" % (config["commandprefix"], ','.join(sorted(storage.data["explanations"].keys())))

def generate_expression(node):
	return "(%s)" % "|".join(re.escape(c) for c in node)

@utils.throttle(5, params=[4])
def static_response(lrrbot, conn, event, respond_to, command):
	response = storage.data["responses"][command.lower()]
	if isinstance(response, (tuple, list)):
		response = random.choice(response)
	conn.privmsg(respond_to, response)

@utils.throttle(5, params=[4])
def explain_response(lrrbot, conn, event, respond_to, command):
	response = storage.data["explanations"][command.lower()]
	if isinstance(response, (tuple, list)):
		response = random.choice(response)
	conn.privmsg(respond_to, response)

def modify_commands(commands):
    bot.remove_command(generate_expression(storage.data["responses"]))
    storage.data["responses"] = {k.lower(): v for k,v in commands.items()}
    storage.save()
    static_response.__doc__ = generate_docstring()
    bot.add_command(generate_expression(storage.data["responses"]), static_response)

def modify_explanations(commands):
    bot.remove_command("explain " + generate_expression(storage.data["explanations"]))
    storage.data["explanations"] = {k.lower(): v for k,v in commands.items()}
    storage.save()
    explain_response.__doc__ = generate_explain_docstring()
    bot.add_command("explain " + generate_expression(storage.data["explanations"]), explain_response)

static_response.__doc__ = generate_docstring()
bot.add_command(generate_expression(storage.data["responses"]), static_response)
explain_response.__doc__ = generate_explain_docstring()
bot.add_command("explain " + generate_expression(storage.data["explanations"]), explain_response)
