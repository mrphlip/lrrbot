import sqlalchemy

import lrrbot.decorators
from lrrbot.command_parser import Blueprint

blueprint = Blueprint()

def set_show(bot, show):
	bot.set_show(show.lower())
	bot.get_game_id.reset_throttle()

@blueprint.command(r"show")
@lrrbot.decorators.throttle()
def get_show(bot, conn, event, respond_to):
	"""
	Command: !show
	Section: info

	Post the current show.
	"""
	print_show(bot, conn, respond_to)

def print_show(bot, conn, respond_to):
	show_id = bot.get_show_id()
	shows = bot.metadata.tables["shows"]
	with bot.engine.connect() as pg_conn:
		name, string_id = pg_conn.execute(sqlalchemy.select(shows.c.name, shows.c.string_id)
			.where(shows.c.id == show_id)).first()
	if string_id == "":
		conn.privmsg(respond_to, "Current show not set.")
		return
	conn.privmsg(respond_to, "Currently live: %s%s" % (name, " (overriden)" if bot.show_override is not None else ""))


@blueprint.command(r"show override (.*?)")
@lrrbot.decorators.mod_only
def show_override(bot, conn, event, respond_to, show):
	"""
	Command: !show override ID
	Section: info

	Override the current show.
	--command
	Command: !show override off
	Section: info

	Disable the override.
	"""
	show = show.lower()
	if show == "off":
		bot.override_show(None)
	else:
		try:
			bot.override_show(show)
		except KeyError:
			shows = bot.metadata.tables["shows"]
			with bot.engine.connect() as pg_conn:
				all_shows = pg_conn.execute(sqlalchemy.select(shows.c.string_id)
					.where(shows.c.string_id != "")
					.order_by(shows.c.string_id))
				all_shows = [name for name, in all_shows]
				conn.privmsg(respond_to, "Recognised shows: %s" % ", ".join(all_shows))
				return
	print_show(bot, conn, respond_to)
