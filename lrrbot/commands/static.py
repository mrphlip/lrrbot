import itertools
import logging
import aiomas
import re
import irc.client
import sqlalchemy

import lrrbot.decorators
from common.config import config
import common.utils
from lrrbot.command_parser import Blueprint

blueprint = Blueprint()
log = logging.getLogger(__name__)

ACCESS_ANY = 0
ACCESS_SUB = 1
ACCESS_MOD = 2

def _get_command_id(bot, conn, command):
	if isinstance(command, int):
		return command
	else:
		command = " ".join(command.lower().split())
		aliases = bot.metadata.tables["commands_aliases"]
		query = sqlalchemy.select(aliases.c.command_id).where(aliases.c.alias == command)
		return conn.execute(query).scalar()

def get_response(bot, command):
	responses = bot.metadata.tables["commands_responses"]

	with bot.engine.connect() as conn:
		command_id = _get_command_id(bot, conn, command)
		if command_id is None:
			return None

		query = sqlalchemy.select(responses.c.response).where(responses.c.command_id == command_id)
		return common.utils.pick_random_elements(conn.execute(query).scalars(), 1)[0]

def generate_docstring(bot):
	commands = bot.metadata.tables["commands"]
	aliases = bot.metadata.tables["commands_aliases"]
	responses = bot.metadata.tables["commands_responses"]

	def generator():
		with bot.engine.connect() as conn:
			query = sqlalchemy.select(commands.c.id, commands.c.access, aliases.c.alias)
			query = query.select_from(commands.join(aliases, aliases.c.command_id == commands.c.id))
			query = query.order_by(commands.c.id, aliases.c.id)

			first = True
			for command_id, rows in itertools.groupby(conn.execute(query), key=lambda row:row[0]):
				if not first:
					yield "--command"
				first = False

				for _, access, alias in rows:
					yield f"Command: {config['commandprefix']}{alias}"
				yield "Throttled: 30"
				yield "Throttle-Count: 2"
				yield "Literal-Response: true"
				if access == ACCESS_SUB:
					yield "Sub-Only: true"
				elif access == ACCESS_MOD:
					yield "Mod-Only: true"
				yield "Section: text"
				yield ""

				resp_query = sqlalchemy.select(responses.c.response).where(responses.c.command_id == command_id)
				resp_query = resp_query.order_by(responses.c.id).limit(1)
				yield conn.execute(resp_query).scalar()

	return "\n".join(generator())

def generate_expression(bot):
	aliases = bot.metadata.tables["commands_aliases"]
	with bot.engine.connect() as conn:
		query = sqlalchemy.select(aliases.c.alias)
		aliases = conn.execute(query).scalars().all()
	return "(%s)" % "|".join(re.escape(c).replace("\\ ", " ") for c in aliases)

@lrrbot.decorators.throttle(30, params=[4], count=2)
def static_response(bot, conn, event, respond_to, command):
	commands = bot.metadata.tables["commands"]

	with bot.engine.connect() as dbconn:
		command_id = _get_command_id(bot, dbconn, command)
		if command_id is None:
			return

		query = sqlalchemy.select(commands.c.access).where(commands.c.id == command_id)
		access = dbconn.execute(query).scalar()
		source = irc.client.NickMask(event.source)
		if access == ACCESS_SUB:
			if not bot.is_sub(event) and not bot.is_mod(event):
				log.info("Refusing %s due to inadequate access" % command)
				conn.privmsg(source.nick, "That is a sub-only command.")
				return
		if access == ACCESS_MOD:
			if not bot.is_mod(event):
				log.info("Refusing %s due to inadequate access" % command)
				conn.privmsg(source.nick, "That is a mod-only command.")
				return

		response = get_response(bot, command_id)
		if response is None:
			return
	conn.privmsg(respond_to, response.format(user=event.tags.get('display-name') or source.nick))

command_expression = None
def generate_hook(bot):
	global command_expression
	if command_expression is not None:
		bot.commands.remove(command_expression)
	static_response.__doc__ = generate_docstring(bot)
	command_expression = generate_expression(bot)
	bot.commands.add(command_expression, static_response)

@blueprint.on_init
def register(bot):
	@aiomas.expose
	def modify_commands():
		log.info("Updating commands")
		generate_hook(bot)

	bot.rpc_server.static = aiomas.rpc.ServiceDict({
		'modify_commands': modify_commands,
	})

	generate_hook(bot)
