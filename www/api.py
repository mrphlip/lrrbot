import sqlalchemy
from www import server
from www import login
import common.rpc
import datetime
import pytz
import flask
import common.storm
from common import googlecalendar
from common.config import config

blueprint = flask.Blueprint("api", __name__)

@blueprint.route("/stormcount")
def stormcount():
	storm = server.db.metadata.tables['storm']
	with server.db.engine.connect() as conn:
		counts = conn.execute(sqlalchemy.select(*(storm.c[counter] for counter in common.storm.COUNTERS))
							  .where(storm.c.date == datetime.datetime.now(config['timezone']).date())) \
			.one_or_none()
	if counts is not None:
		return flask.jsonify(counts._asdict())
	else:
		return flask.jsonify({counter: 0 for counter in common.storm.COUNTERS})

@blueprint.route("/next")
async def nextstream():
	message, _ = await googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL, verbose=False)
	return message

@blueprint.route("/show/<show>")
@login.with_minimal_session
async def set_show(session, show):
	if not session['active_account']['is_mod']:
		return "%s is not a mod" % (session['active_account']['display_name'])
	if show == "off":
		show = ""
	await common.rpc.bot.set_show(show)
	return ""

@blueprint.route("/game")
async def get_game():
	game_id = await common.rpc.bot.get_game_id()
	if game_id is None:
		return "-"
	show_id = await common.rpc.bot.get_show_id()

	games = server.db.metadata.tables["games"]
	with server.db.engine.connect() as conn:
		return conn.execute(sqlalchemy.select(games.c.name).where(games.c.id == game_id)).first()[0]

@blueprint.route("/show")
async def get_show():
	show_id = await common.rpc.bot.get_show_id()

	shows = server.db.metadata.tables["shows"]
	with server.db.engine.connect() as conn:
		show, = conn.execute(sqlalchemy.select(shows.c.string_id).where(shows.c.id == show_id)).first()
		return show or "-"

@blueprint.route("/tweet")
@login.with_minimal_session
async def get_tweet(session):
	tweet = None
	if session['active_account']['is_mod']:
		tweet = await common.rpc.bot.get_tweet()
	return tweet or "-"

@blueprint.route("/disconnect")
@login.with_minimal_session
async def disconnect(session):
	if session['active_account']['is_mod']:
		await common.rpc.bot.disconnect_from_chat()
		return flask.jsonify(status="OK")
	else:
		return flask.jsonify(status="ERR")

CLIP_URL = "https://clips.twitch.tv/{}"
@blueprint.route("/clips")
@login.with_minimal_session
async def get_clips(session):
	if not session['active_account']['is_mod']:
		return flask.jsonify(status="ERR")
	days = float(flask.request.values.get('days', 14))
	startdt = datetime.datetime.now(pytz.UTC) - datetime.timedelta(days=days)
	full = int(flask.request.values.get('full', 0))
	clips = server.db.metadata.tables["clips"]
	with server.db.engine.connect() as conn:
		if full:
			clipdata = conn.execute(sqlalchemy.select(clips.c.slug, clips.c.title, clips.c.vodid, clips.c.rating)
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
			clipdata = conn.execute(sqlalchemy.select(clips.c.slug)
				.where(clips.c.rating == True)
				.where(clips.c.time >= startdt)
				.where(clips.c.deleted == False)
				.order_by(clips.c.time.asc())).fetchall()
			clipdata = "\n".join(CLIP_URL.format(slug) for slug, in clipdata)
			return flask.wrappers.Response(clipdata, mimetype="text/plain")
