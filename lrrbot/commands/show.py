import sqlalchemy

import lrrbot.decorators
from lrrbot.main import bot

def set_show(lrrbot, show):
	lrrbot.set_show(show.lower())
	lrrbot.get_game_id.reset_throttle()

@bot.command("show")
@lrrbot.decorators.throttle()
def get_show(lrrbot, conn, event, respond_to):
	"""
	Command: !show
	Section: info

	Post the current show.
	"""
	print_show(lrrbot, conn, respond_to)

def print_show(lrrbot, conn, respond_to):
	show_id = lrrbot.get_show_id()
	shows = lrrbot.metadata.tables["shows"]
	with lrrbot.engine.connect() as pg_conn:
		name, string_id = pg_conn.execute(sqlalchemy.select(shows.c.name, shows.c.string_id)
			.where(shows.c.id == show_id)).first()
	if string_id == "":
		conn.privmsg(respond_to, "Current show not set.")
		return
	conn.privmsg(respond_to, "Currently live: %s%s" % (name, " (overriden)" if lrrbot.show_override is not None else ""))


@bot.command("show override (.*?)")
@lrrbot.decorators.mod_only
def show_override(lrrbot, conn, event, respond_to, show):
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
		lrrbot.override_show(None)
	else:
		try:
			lrrbot.override_show(show)
		except KeyError:
			shows = lrrbot.metadata.tables["shows"]
			with lrrbot.engine.connect() as pg_conn:
				all_shows = pg_conn.execute(sqlalchemy.select(shows.c.string_id)
					.where(shows.c.string_id != "")
					.order_by(shows.c.string_id))
				all_shows = [name for name, in all_shows]
				conn.privmsg(respond_to, "Recognised shows: %s" % ", ".join(all_shows))
				return
	print_show(lrrbot, conn, respond_to)
