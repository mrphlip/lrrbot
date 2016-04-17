import sqlalchemy
from www import server
from www import botinteract
from www import login
from common.config import config
import datetime

@server.app.route("/api/stats/<stat>")
def api_stats(stat):
	game_id = botinteract.get_game_id()
	if game_id is None:
		return "-"
	show_id = botinteract.get_show_id()

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
def stormcount():
	today = datetime.datetime.now(config["timezone"]).date().toordinal()
	data = botinteract.get_data("storm")
	if data.get("date") != today:
		return "0"
	return str(data.get("count", 0))

@server.app.route("/api/next")
def nextstream():
	return botinteract.nextstream()

@server.app.route("/api/votes")
def api_votes():
	game_id = botinteract.get_game_id()
	if game_id is None:
		return "-"
	show_id = botinteract.get_show_id()

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
def set_show(session, show):
	if not session['user']['is_mod']:
		return "%s is not a mod" % (session['user']['display_name'])
	if show == "off":
		show = ""
	response = botinteract.set_show(show)
	if response["status"] == "OK":
		return ""
	return response["status"]

@server.app.route("/api/game")
def get_game():
	game_id = botinteract.get_game_id()
	if game_id is None:
		return "-"
	show_id = botinteract.get_show_id()

	games = server.db.metadata.tables["games"]
	with server.db.engine.begin() as conn:
		return conn.execute(sqlalchemy.select([games.c.name]).where(games.c.id == game_id)).first()[0]

@server.app.route("/api/show")
def get_show():
	show_id = botinteract.get_show_id()

	shows = server.db.metadata.tables["shows"]
	with server.db.engine.begin() as conn:
		show, = conn.execute(sqlalchemy.select([shows.c.string_id]).where(shows.c.id == show_id)).first()
		return show or "-"

@server.app.route("/api/tweet")
@login.with_minimal_session
def get_tweet(session):
	tweet = None
	if session['user']['is_mod']:
		tweet = botinteract.get_tweet()
	return tweet or "-"
