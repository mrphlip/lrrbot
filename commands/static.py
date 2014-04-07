from lrrbot import bot
import storage
import random
import utils

@utils.throttle(5, params=[4])
def static_response(lrrbot, conn, event, respond_to, command):
	response = storage.data["responses"][command]
	if isinstance(response, (tuple, list)):
		response = random.choice(response)
	conn.privmsg(respond_to, response)

bot.add_command("(%s)" % "|".join(storage.data["responses"]), static_response)
