import sqlalchemy
from sqlalchemy.dialects.postgresql import insert

import lrrbot.decorators
from common import twitch
from lrrbot.command_parser import Blueprint

blueprint = Blueprint()

@blueprint.command(r"game")
@lrrbot.decorators.throttle()
async def current_game(bot, conn, event, respond_to):
	"""
	Command: !game
	Section: info

	Post the game currently being played.
	"""
	game_id = await bot.get_game_id()
	if game_id is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	show_id = bot.get_show_id()

	game_per_show_data = bot.metadata.tables["game_per_show_data"]
	games = bot.metadata.tables["games"]
	with bot.engine.connect() as pg_conn:
		game, = pg_conn.execute(
			sqlalchemy.select(
				sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
			).select_from(
				games.outerjoin(game_per_show_data,
					(game_per_show_data.c.game_id == games.c.id)
						& (game_per_show_data.c.show_id == show_id))
			).where(games.c.id == game_id)).first()

		conn.privmsg(respond_to, "Currently playing: %s%s" % (
			game,
			" (overridden)" if bot.game_override is not None else ""
		))

@blueprint.command(r"game display (.*?)")
@lrrbot.decorators.mod_only
async def set_game_name(bot, conn, event, respond_to, name):
	"""
	Command: !game display NAME
	Section: info

	eg. !game display Resident Evil: Man Fellating Giraffe

	Change the display name of the current game to NAME.
	"""
	game_id = await bot.get_game_id()
	if game_id is None:
		conn.privmsg(respond_to, "Not currently playing any game.")
		return
	show_id = bot.get_show_id()

	games = bot.metadata.tables["games"]
	game_per_show_data = bot.metadata.tables["game_per_show_data"]
	with bot.engine.connect() as pg_conn:
		name_query = sqlalchemy.select(games.c.name).where(games.c.id == game_id)
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
		pg_conn.commit()

		conn.privmsg(respond_to, "OK, I'll start calling %s \"%s\"" % (real_name, name))

@blueprint.command(r"game override (.*?)")
@lrrbot.decorators.mod_only
async def override_game(bot, conn, event, respond_to, game):
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
		bot.override_game(None)
		operation = "disabled"
	else:
		bot.override_game(game)
		operation = "enabled"
	twitch.get_info.reset_throttle()
	current_game.reset_throttle()
	game_id = await bot.get_game_id()
	show_id = bot.get_show_id()
	message = "Override %s. " % operation
	if game_id is None:
		message += "Not currently playing any game"
	else:
		games = bot.metadata.tables["games"]
		game_per_show_data = bot.metadata.tables["game_per_show_data"]
		with bot.engine.connect() as pg_conn:
			name, = pg_conn.execute(sqlalchemy.select(games.c.name)
				.select_from(
					games
						.outerjoin(game_per_show_data,
							(games.c.id == game_per_show_data.c.game_id) & (game_per_show_data.c.show_id == show_id)
						)
				).where(games.c.id == game_id)).first()
		message += "Currently playing: %s" % name
	conn.privmsg(respond_to, message)

@blueprint.command(r"game refresh")
@lrrbot.decorators.mod_only
async def refresh(bot, conn, event, respond_to):
	"""
	Command: !game refresh
	Section: info

	Force a refresh of the current Twitch game (normally this is updated at most once every 15 minutes)
	"""
	twitch.get_info.reset_throttle()
	bot.get_game_id.reset_throttle()
	current_game.reset_throttle()
	await current_game(bot, conn, event, respond_to)
