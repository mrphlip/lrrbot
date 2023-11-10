import datetime
import functools
import logging
import urllib.parse

import flask
import pytz
import sqlalchemy

from common import card
import common.rpc
import common.storm
from common import utils
from common.postgres import escape_like
from www import login
from www import server

log = logging.getLogger("api_v2")

def require_mod(func):
	@functools.wraps(func)
	async def wrapper(*args, **kwargs):
		session = await login.load_session(include_url=False, include_header=False)
		kwargs['session'] = session
		if session['user']['is_mod']:
			return await utils.wrap_as_coroutine(func)(*args, **kwargs)
		else:
			return flask.jsonify(message="%s is not a mod" % (session['user']['display_name'], )), 403
	return wrapper

blueprint = flask.Blueprint("api_v2", __name__)

@blueprint.after_request
def add_cors_headers(request):
	request.access_control_allow_origin = '*'
	request.access_control_allow_methods = flask.request.url_rule.methods
	request.access_control_allow_headers = ['Content-Type']
	return request

@blueprint.route("/")
@login.with_session
async def docs(session):
	shows = server.db.metadata.tables["shows"]
	with server.db.engine.connect() as conn:
		shows = list(conn.execute(sqlalchemy.select(shows.c.string_id, shows.c.name).where(shows.c.string_id != "").order_by(shows.c.string_id)))

	return flask.render_template("api_v2_docs.html", session=session,
		stormcount=stormcount().get_data().decode(),
		tweet=await get_tweet(),
		shows=shows,
	)

@blueprint.route("/stormcount")
def stormcount():
	return flask.jsonify({
		'twitch-message': common.storm.get(server.db.engine, server.db.metadata, 'twitch-message'),
		'twitch-subscription': common.storm.get(server.db.engine, server.db.metadata, 'twitch-subscription'),
		'twitch-resubscription': common.storm.get(server.db.engine, server.db.metadata, 'twitch-resubscription'),
		'twitch-follow': common.storm.get(server.db.engine, server.db.metadata, 'twitch-follow'),
		'twitch-cheer': common.storm.get(server.db.engine, server.db.metadata, 'twitch-cheer'),
		'twitch-raid': common.storm.get(server.db.engine, server.db.metadata, 'twitch-raid'),
		'patreon-pledge': common.storm.get(server.db.engine, server.db.metadata, 'patreon-pledge'),
	})

@blueprint.route("/stormcount/all")
def stormcount_all():
	storm = server.db.metadata.tables["storm"]
	with server.db.engine.connect() as conn:
		res = conn.execute(sqlalchemy.select(
			storm.c.date,
			storm.c["twitch-subscription"],
			storm.c["twitch-resubscription"],
			storm.c["twitch-follow"],
			storm.c["twitch-message"],
			storm.c["patreon-pledge"],
			storm.c["twitch-cheer"],
			storm.c["twitch-raid"],
		).order_by(storm.c.date.desc()))

		return flask.jsonify([
			{
				"date": date.isoformat(),
				"twitch-subscription": twitch_subscription,
				"twitch-resubscription": twitch_resubscription,
				"twitch-follow": twitch_follow,
				"twitch-message": twitch_message,
				"patreon-pledge": patreon_pledge,
				"twitch-cheer": twitch_cheer,
				"twitch-raid": twitch_raid,
			}
			for date, twitch_subscription, twitch_resubscription, twitch_follow, twitch_message, patreon_pledge, twitch_cheer, twitch_raid in res
		])


@blueprint.route("/show", methods=["PUT"])
@require_mod
async def set_show(session):
	if not flask.request.is_json or 'code' not in flask.request.get_json():
		return flask.jsonify(message="Request not JSON"), 400
	show = flask.request.get_json()['code']
	await common.rpc.bot.set_show(show)
	show_id = await common.rpc.bot.get_show_id()

	shows = server.db.metadata.tables["shows"]
	with server.db.engine.connect() as conn:
		code, name = conn.execute(sqlalchemy.select(shows.c.string_id, shows.c.name).where(shows.c.id == show_id)).first()
		return flask.jsonify(
			code=code,
			name=name,
		)

@blueprint.route("/tweet")
async def get_tweet():
	return await common.rpc.bot.get_tweet()

@blueprint.route("/disconnect", methods=["POST"])
@server.csrf.exempt
@require_mod
async def disconnect(session):
	await common.rpc.bot.disconnect_from_chat()
	return '', 204

# Implemented in `eventserver.py`
@blueprint.route("/events")
async def events():
	if server.app.debug:
		return flask.redirect("http://localhost:8080/api/v2/events?" + urllib.parse.urlencode(flask.request.args))
	else:
		return flask.jsonify(message="Server not set up correctly."), 500

CLIP_URL = "https://clips.twitch.tv/{}"
@blueprint.route("/clips")
@require_mod
async def get_clips(session):
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

CARD_GAME_CODE_MAPPING = {
	'mtg': 1,
	'keyforge': 2,
	'ptcg': 3,
	'lorcana': 4,
}
@blueprint.route("/cardviewer", methods=["POST"])
@server.csrf.exempt
@require_mod
async def cardviewer_announce(session):
	if not flask.request.is_json:
		return flask.jsonify(message="Request not JSON"), 400
	
	req = flask.request.get_json()
	log.debug("Received cardviewer: %r", req)

	cards = server.db.metadata.tables['cards']
	card_multiverse = server.db.metadata.tables['card_multiverse']

	try:
		game = CARD_GAME_CODE_MAPPING[req.get('game', 'mtg')]
	except KeyError:
		return flask.jsonify(message="Unrecognised game code"), 400
	query = sqlalchemy.select(cards.c.id, cards.c.name, cards.c.text).where(cards.c.game == game)

	if 'multiverseid' in req:
		query = query.select_from(cards.join(card_multiverse)).where(card_multiverse.c.id == req['multiverseid'])
	elif 'name' in req:
		name = card.to_query(req['name'])
		exact = card.clean_text(req['name'])
		hidden = False

		exact_query = sqlalchemy.exists().where(cards.c.filteredname == exact)
		if not hidden:
			exact_query = exact_query.where(~cards.c.hidden)

		query = query.where(
			(exact_query & (cards.c.filteredname == exact))
				| (~exact_query & cards.c.filteredname.ilike(name)))
		if not hidden:
			query = query.where(~cards.c.hidden)
	elif 'host' in req or 'augment' in req:
		name = ""
		if 'augment' in req:
			name += card.to_query(req['augment']) + escape_like("_aug")
		if 'host' in req:
			name += ("_" if name != "" else "") + card.to_query(req['host']) + escape_like("_host")
		query = query.where(cards.c.filteredname.ilike(name))
	else:
		return flask.jsonify(message=""), 400

	with server.db.engine.connect() as conn:
		cards = conn.execute(query).fetchall()

	if len(cards) == 0:
		return flask.jsonify(message="No such card"), 400
	elif len(cards) > 1:
		return flask.jsonify(message="Matched multiple cards"), 400

	card_id, name, text = cards[0]

	await common.rpc.bot.cardviewer.announce(card_id)

	return flask.jsonify(
		name=name,
		text=text,
	)
