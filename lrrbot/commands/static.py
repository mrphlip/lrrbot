import random
import re

from common import utils
from common.config import config
from lrrbot import bot, log

@utils.with_postgres
def load_commands(conn, cur):
	cur.execute("""
		SELECT historykey, jsondata
		FROM history
		WHERE
			historykey = (
				SELECT MAX(historykey)
				FROM history
				WHERE
					section = 'responses'
			)
	""")
	key, responses = cur.fetchone()
	inverse_responses = {}
	for command, data in responses.items():
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
	return "(%s)" % "|".join(re.escape(c).replace("\\ ", " ") for c in responses), \
		"\n--command\n".join(generator()), \
		key

@utils.throttle(30, params=[4], count=2, modoverride=True)
@utils.with_postgres
def static_response(pg_conn, pg_cur, lrrbot, conn, event, respond_to, command):
	global historykey
	command = " ".join(command.split()).lower()
	pg_cur.execute("""
		SELECT jsondata->%s
		FROM history
		WHERE
			historykey = %s
	""", (command, historykey))
	response_data, = pg_cur.fetchone()
	if response_data["access"] == "sub":
		if not lrrbot.is_sub(event) and not lrrbot.is_mod(event):
			utils.sub_complaint(conn, event, command)
			log.info("Refusing %s due to inadequate access" % command)
			return
	if response_data["access"] == "mod":
		if not lrrbot.is_mod(event):
			utils.mod_complaint(conn, event, command)
			log.info("Refusing %s due to inadequate access" % command)
			return
	response = response_data["response"]
	if isinstance(response, (tuple, list)):
		response = random.choice(response)
	conn.privmsg(respond_to, response)

command_expression = None
historykey = None
def reload_commands():
	global historykey, command_expression
	if command_expression is not None:
		bot.remove_handler(static_response)
	command_expression, static_response.__doc__, historykey = load_commands()
	bot.add_command(command_expression, static_response)

reload_commands()
