import irc
import sqlalchemy
from sqlalchemy.dialects.postgresql import insert


import lrrbot.decorators
from common import utils
from common import twitch
from lrrbot import storage
from lrrbot.main import bot
from lrrbot.commands.stats import stat_increment

@bot.command("game")
@lrrbot.decorators.throttle()
def current_game(lrrbot, conn, event, respond_to):
	"""
	Command: !game
	Section: info

	Post the game currently being played.
	"""
	game_id = lrrbot.get_game_id()
	if game_id is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	show_id = lrrbot.get_show_id()

	game_votes = lrrbot.metadata.tables["game_votes"]
	game_per_show_data = lrrbot.metadata.tables["game_per_show_data"]
	games = lrrbot.metadata.tables["games"]
	with lrrbot.engine.begin() as pg_conn:
		good = sqlalchemy.cast(
			sqlalchemy.func.sum(sqlalchemy.cast(game_votes.c.vote, sqlalchemy.Integer)),
			sqlalchemy.Numeric
		)
		votes_query = sqlalchemy.alias(sqlalchemy.select([
			(100 * good / sqlalchemy.func.count(game_votes.c.vote)).label("rating")
		]).where(game_votes.c.game_id == game_id).where(game_votes.c.show_id == show_id))
		game, rating = pg_conn.execute(
			sqlalchemy.select([
				sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
				votes_query.c.rating
			]).select_from(
				games.outerjoin(game_per_show_data,
					(game_per_show_data.c.game_id == games.c.id)
						& (game_per_show_data.c.show_id == show_id))
			).where(games.c.id == game_id)).first()

		conn.privmsg(respond_to, "Currently playing: %s%s%s" % (
			game,
			" (rating %0.0f%%)" % rating if rating is not None else "",
			" (overridden)" if lrrbot.game_override is not None else ""
		))

@bot.command("game display (.*?)")
@lrrbot.decorators.mod_only
def set_game_name(lrrbot, conn, event, respond_to, name):
	"""
	Command: !game display NAME
	Section: info

	eg. !game display Resident Evil: Man Fellating Giraffe

	Change the display name of the current game to NAME.
	"""
	game_id = lrrbot.get_game_id()
	if game_id is None:
		conn.privmsg(respond_to, "Not currently playing any game.")
		return
	show_id = lrrbot.get_show_id()

	games = lrrbot.metadata.tables["games"]
	game_per_show_data = lrrbot.metadata.tables["game_per_show_data"]
	with lrrbot.engine.begin() as pg_conn:
		name_query = sqlalchemy.select([games.c.name]).where(games.c.id == game_id)
		# NULLIF: https://www.postgresql.org/docs/9.6/static/functions-conditional.html#FUNCTIONS-NULLIF
		query = insert(game_per_show_data).values({
			"game_id": game_id,
			"show_id": show_id,
			'display_name': sqlalchemy.func.nullif(name, name_query),
		})
		query = query.on_conflict_do_update(
			index_elements=[game_per_show_data.c.game_id, game_per_show_data.c.show_id],
			set_={
				'display_name': query.excluded.display_name,
			}
		)
		pg_conn.execute(query)
		real_name, = pg_conn.execute(name_query).first()

		conn.privmsg(respond_to, "OK, I'll start calling %s \"%s\"" % (real_name, name))

@bot.command("game override (.*?)")
@lrrbot.decorators.mod_only
def override_game(lrrbot, conn, event, respond_to, game):
	"""
	Command: !game override NAME
	Section: info

	eg: !game override Prayer Warriors: A.O.F.G.

	Override what game is being played (eg when the current game isn't in the Twitch database)

	--command
	Command: !game override off
	Section: info

	Disable override, go back to getting current game from Twitch stream settings.
	Should the crew start regularly playing a game called "off", I'm sure we'll figure something out.
	"""
	if game == "" or game.lower() == "off":
		lrrbot.override_game(None)
		operation = "disabled"
	else:
		lrrbot.override_game(game)
		operation = "enabled"
	twitch.get_info.reset_throttle()
	current_game.reset_throttle()
	game_id = lrrbot.get_game_id()
	show_id = lrrbot.get_show_id()
	message = "Override %s. " % operation
	if game_id is None:
		message += "Not currently playing any game"
	else:
		games = lrrbot.metadata.tables["games"]
		game_per_show_data = lrrbot.metadata.tables["game_per_show_data"]
		with lrrbot.engine.begin() as pg_conn:
			name, = pg_conn.execute(sqlalchemy.select([games.c.name])
				.select_from(
					games
						.outerjoin(game_per_show_data,
							(games.c.id == game_per_show_data.c.game_id) & (game_per_show_data.c.show_id == show_id)
						)
				).where(games.c.id == game_id)).first()
		message += "Currently playing: %s" % name
	conn.privmsg(respond_to, message)

@bot.command("game refresh")
@lrrbot.decorators.mod_only
def refresh(lrrbot, conn, event, respond_to):
	"""
	Command: !game refresh
	Section: info

	Force a refresh of the current Twitch game (normally this is updated at most once every 15 minutes)
	"""
	twitch.get_info.reset_throttle()
	lrrbot.get_game_id.reset_throttle()
	current_game.reset_throttle()
	current_game(lrrbot, conn, event, respond_to)

@bot.command("game completed")
@lrrbot.decorators.throttle(30, notify=lrrbot.decorators.Visibility.PUBLIC, modoverride=False, allowprivate=False)
def completed(lrrbot, conn, event, respond_to):
	"""
	Command: !game completed
	Section: info

	Mark a game as having been completed.
	"""
	game_id = lrrbot.get_game_id()
	if game_id is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	show_id = lrrbot.get_show_id()
	games = lrrbot.metadata.tables["games"]
	game_per_show_data = lrrbot.metadata.tables["game_per_show_data"]
	stats = lrrbot.metadata.tables["stats"]
	with lrrbot.engine.begin() as pg_conn:
		name, = pg_conn.execute(sqlalchemy.select([
			sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
		]).select_from(games.outerjoin(
			game_per_show_data,
			(game_per_show_data.c.game_id == games.c.id) & (game_per_show_data.c.show_id == show_id)
		)).where(games.c.id == game_id)).first()
		stat_id, emote = pg_conn.execute(sqlalchemy.select([stats.c.id, stats.c.emote])
			.where(stats.c.string_id == "completed")).first()
		stat_increment(lrrbot, pg_conn, game_id, show_id, stat_id, 1)
	if emote:
		emote += " "
	conn.privmsg(respond_to, "%s%s added to the completed list" % (emote, name))
