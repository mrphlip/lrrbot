import random

from common import utils
from lrrbot import bot, log, storage

@bot.command("explain (.*?)")
@utils.throttle(30, params=[4], count=2, modoverride=True)
def explain_response(lrrbot, conn, event, respond_to, command):
	"""
	Command: !explain TOPIC
	Mod-Only: true
	Section: text
	
	Provide an explanation for a given topic.
	--command
	Command: !explain show
	Mod-Only: true
	Section: text

	Provide an explanation for the currently-live show.
	"""
	command = " ".join(command.split()).lower()
	if command == "show":
		command = lrrbot.show_override or lrrbot.show
		if command is None and lrrbot.is_mod(event):
			conn.privmsg(respond_to, "Current show not set.")
	response_data = storage.data["explanations"].get(command)
	if not response_data:
		return
	if response_data["access"] == "sub":
		if not lrrbot.is_sub(event) and not lrrbot.is_mod(event):
			utils.sub_complaint(conn, event, "explain "+command)
			log.info("Refusing explain %s due to inadequate access" % command)
			return
	if response_data["access"] == "mod":
		if not lrrbot.is_mod(event):
			utils.mod_complaint(conn, event, "explain "+command)
			log.info("Refusing explain %s due to inadequate access" % command)
			return
	response = response_data['response']
	if isinstance(response, (tuple, list)):
		response = random.choice(response)
	conn.privmsg(respond_to, response)

def modify_explanations(commands):
	storage.data["explanations"] = {k.lower(): v for k,v in commands.items()}
	storage.save()
