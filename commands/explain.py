from lrrbot import bot, log
import storage
import random
import utils

@bot.command("explain (.*?)")
@utils.throttle(5, params=[4])
def explain_response(lrrbot, conn, event, respond_to, command):
	"""
	Command: !explain TOPIC
	Mod-Only: true
	
	Provide an explanation for a given topic.
	"""
	command = " ".join(command.split())
	response_data = storage.data["explanations"].get(command.lower())
	if not response_data:
		return
	if response_data["access"] == "sub":
		if not lrrbot.is_sub(event) and not lrrbot.is_mod(event):
			log.info("Refusing explain %s due to inadequate access" % command)
			return
	if response_data["access"] == "mod":
		if not lrrbot.is_mod(event):
			log.info("Refusing explain %s due to inadequate access" % command)
			return
	response = response_data['response']
	if isinstance(response, (tuple, list)):
		response = random.choice(response)
	conn.privmsg(respond_to, response)

def modify_explanations(commands):
    storage.data["explanations"] = {k.lower(): v for k,v in commands.items()}
    storage.save()
