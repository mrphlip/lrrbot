import sqlalchemy
from www import server
from www import login
from common.config import config
import common.rpc
import datetime
import pytz
import flask
import common.storm
from common import googlecalendar

@server.app.route("/api/stats/<stat>")
async def api_stats(stat):
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
def stormcount():
	return flask.jsonify({
		'twitch-subscription': common.storm.get(server.db.engine, server.db.metadata, 'twitch-subscription'),
		'twitch-resubscription': common.storm.get(server.db.engine, server.db.metadata, 'twitch-resubscription'),
		'twitch-follow': common.storm.get(server.db.engine, server.db.metadata, 'twitch-follow'),
		'twitch-cheer': common.storm.get(server.db.engine, server.db.metadata, 'twitch-cheer'),
		'patreon-pledge': common.storm.get(server.db.engine, server.db.metadata, 'patreon-pledge'),
	})

@server.app.route("/api/next")
async def nextstream():
	return await googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL, verbose=False)

@server.app.route("/api/votes")
async def api_votes():
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
	await common.rpc.bot.set_show(show)
	return ""

@server.app.route("/api/game")
async def get_game():
	game_id = await common.rpc.bot.get_game_id()
	if game_id is None:
		return "-"
	show_id = await common.rpc.bot.get_show_id()

	games = server.db.metadata.tables["games"]
	with server.db.engine.begin() as conn:
		return conn.execute(sqlalchemy.select([games.c.name]).where(games.c.id == game_id)).first()[0]

@server.app.route("/api/show")
async def get_show():
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
		tweet = await common.rpc.bot.get_tweet()
	return tweet or "-"

@server.app.route("/api/disconnect")
@login.with_minimal_session
async def disconnect(session):
	if session['user']['is_mod']:
		await common.rpc.bot.disconnect_from_chat()
		return flask.jsonify(status="OK")
	else:
		return flask.jsonify(status="ERR")

CLIP_URL = "https://clips.twitch.tv/{}"
@server.app.route("/api/clips")
@login.with_minimal_session
async def get_clips(session):
	if not session['user']['is_mod']:
		return flask.jsonify(status="ERR")
	days = float(flask.request.values.get('days', 14))
	startdt = datetime.datetime.now(pytz.UTC) - datetime.timedelta(days=days)
	full = int(flask.request.values.get('full', 0))
	clips = server.db.metadata.tables["clips"]
	with server.db.engine.begin() as conn:
		if full:
			clipdata = conn.execute(sqlalchemy.select(
				[clips.c.slug, clips.c.title, clips.c.vodid, clips.c.rating])
				.where(clips.c.time >= startdt)
				.where(clips.c.deleted == False)
				.order_by(clips.c.time.asc())).fetchall()
			clipdata = [
				{
					'slug': slug, 'title': title, 'vodid': vodid, 'rating': rating,
					'url': CLIP_URL.format(slug),
				}
				for slug, title, vodid, rating in clipdata
			]
			return flask.jsonify(clipdata)
		else:
			clipdata = conn.execute(sqlalchemy.select([clips.c.slug])
				.where(clips.c.rating == True)
				.where(clips.c.time >= startdt)
				.where(clips.c.deleted == False)
				.order_by(clips.c.time.asc())).fetchall()
			clipdata = "\n".join(CLIP_URL.format(slug) for slug, in clipdata)
			return flask.wrappers.Response(clipdata, mimetype="text/plain")

@server.app.route("/api/polls")
async def get_polls():
	data = await common.rpc.bot.get_polls()
	return flask.jsonify(data)
