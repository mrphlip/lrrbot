from lrrbot import bot
import storage
import random
import utils
import re

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
    bot.add_command("(%s)" % "|".join(re.escape(c) for c in storage.data["responses"]), static_response)

bot.add_command("(%s)" % "|".join(re.escape(c) for c in storage.data["responses"]), static_response)
