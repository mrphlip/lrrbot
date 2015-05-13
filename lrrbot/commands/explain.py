import random

from common import utils
from lrrbot import bot, log

@bot.command("explain (.*?)")
@utils.throttle(30, params=[4], count=2, modoverride=True)
@utils.with_postgres
def explain_response(pg_conn, pg_cur, lrrbot, conn, event, respond_to, command):
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
	pg_cur.execute("""
		SELECT jsondata->%s
		FROM history
		WHERE
			historykey = (
				SELECT MAX(historykey)
				FROM history
				WHERE
					section = 'explanations'
			)
	""", (command,))
	response_data, = pg_cur.fetchone()

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
