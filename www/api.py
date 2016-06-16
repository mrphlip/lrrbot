import sqlalchemy
from www import server
from www import login
from common.config import config
import common.rpc
import datetime

@server.app.route("/api/stats/<stat>")
async def api_stats(stat):
	await common.rpc.bot.connect()
	game_id = await common.rpc.bot.get_game_id()
	if game_id is None:
		return "-"
	show_id = await common.rpc.bot.get_show_id()

	game_stats = server.db.metadata.tables["game_stats"]
	stats = server.db.metadata.tables["stats"]
	with server.db.engine.begin() as conn:
		count = conn.execute(sqlalchemy.select([game_stats.c.count])
			.where(game_stats.c.game_id == game_id)
			.where(game_stats.c.show_id == show_id)
			.where(game_stats.c.stat_id == sqlalchemy.select([stats.c.id])
				.where(stats.c.string_id == stat))
		).first()
		if count is not None:
			count, = count
		else:
			count = 0

	return str(count)

@server.app.route("/api/stormcount")
async def stormcount():
	await common.rpc.bot.connect()
	today = datetime.datetime.now(config["timezone"]).date().toordinal()
	data = await common.rpc.bot.get_data("storm")
	if data.get("date") != today:
		return "0"
	return str(data.get("count", 0))

@server.app.route("/api/next")
async def nextstream():
	await common.rpc.bot.connect()
	return await common.rpc.bot.nextstream()

@server.app.route("/api/votes")
async def api_votes():
	await common.rpc.bot.connect()
	game_id = await common.rpc.bot.get_game_id()
	if game_id is None:
		return "-"
	show_id = await common.rpc.bot.get_show_id()

	game_votes = server.db.metadata.tables["game_votes"]
	with server.db.engine.begin() as conn:
		good = sqlalchemy.cast(
			sqlalchemy.func.sum(sqlalchemy.cast(game_votes.c.vote, sqlalchemy.Integer)),
			sqlalchemy.Numeric
		)
		rating = conn.execute(sqlalchemy.select([
			(100 * good / sqlalchemy.func.count(game_votes.c.vote)),
			good,
			sqlalchemy.func.count(game_votes.c.vote),
		]).where(game_votes.c.game_id == game_id).where(game_votes.c.show_id == show_id)).first()
		if rating is not None:
			return "%.0f%% (%d/%d)" % (float(rating[0]), rating[1], rating[2])
		else:
			return "-% (0/0)"

@server.app.route("/api/show/<show>")
@login.with_minimal_session
async def set_show(session, show):
	if not session['user']['is_mod']:
		return "%s is not a mod" % (session['user']['display_name'])
	if show == "off":
		show = ""
	await common.rpc.bot.connect()
	await common.rpc.bot.set_show(show)

@server.app.route("/api/game")
async def get_game():
	await common.rpc.bot.connect()
	game_id = await common.rpc.bot.get_game_id()
	if game_id is None:
		return "-"
	show_id = await common.rpc.bot.get_show_id()

	games = server.db.metadata.tables["games"]
	with server.db.engine.begin() as conn:
		return conn.execute(sqlalchemy.select([games.c.name]).where(games.c.id == game_id)).first()[0]

@server.app.route("/api/show")
async def get_show():
	await common.rpc.bot.connect()
	show_id = await common.rpc.bot.get_show_id()

	shows = server.db.metadata.tables["shows"]
	with server.db.engine.begin() as conn:
		show, = conn.execute(sqlalchemy.select([shows.c.string_id]).where(shows.c.id == show_id)).first()
		return show or "-"

@server.app.route("/api/tweet")
@login.with_minimal_session
async def get_tweet(session):
	tweet = None
	if session['user']['is_mod']:
		await common.rpc.bot.connect()
		tweet = await common.rpc.bot.get_tweet()
	return tweet or "-"
