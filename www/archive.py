import datetime
import copy
import logging
from urllib.error import HTTPError

import flask
import flask.json
import dateutil.parser
import sqlalchemy

import common.time
import common.url
from common import utils
from common import twitch
from common.config import config
from www import server
from www import login

log = logging.getLogger("archive")

CACHE_TIMEOUT = 5*60

BEFORE_BUFFER = datetime.timedelta(minutes=15)
AFTER_BUFFER = datetime.timedelta(minutes=15)

TIMESTAMPS_OFF = 0
TIMESTAMPS_RELATIVE = 1
TIMESTAMPS_MOONBASE = 2
TIMESTAMPS_LOCAL = 3

blueprint = flask.Blueprint("archive", __name__)

@utils.cache(CACHE_TIMEOUT, params=[0, 1])
async def archive_feed_data(channel, broadcasts):
	videos = await twitch.get_videos(channel, broadcasts=broadcasts, limit=100)

	for video in videos:
		if video.get('created_at'):
			video["created_at"] = dateutil.parser.parse(video["created_at"])
		if video.get('duration'):
			try:
				video['duration'] = utils.parse_duration(video['duration'])
			except ValueError:
				video['duration'] = None

	videos.sort(key=lambda v:v.get('created_at'), reverse=True)
	return videos

async def archive_feed_data_html(channel, broadcasts, rss):
	# Deep copy so we don't modify the cached data
	data = copy.deepcopy(await archive_feed_data(channel, broadcasts))
	for vid in data:
		vid['html'] = flask.render_template("archive_video.html", vid=vid, rss=rss)
	return data

@blueprint.route('/archive')
@login.with_session
async def archive(session):
	channel = flask.request.values.get('channel', 'loadingreadyrun')
	broadcasts = 'highlights' not in flask.request.values
	return flask.render_template("archive.html", videos=await archive_feed_data_html(channel, broadcasts, False), broadcasts=broadcasts, session=session)

@blueprint.route('/archivefeed')
async def feed():
	channel = flask.request.values.get('channel', 'loadingreadyrun')
	broadcasts = 'highlights' not in flask.request.values
	rss = flask.render_template("archive_feed.xml", videos=await archive_feed_data_html(channel, broadcasts, True), broadcasts=broadcasts)
	return flask.Response(rss, mimetype="application/xml")

def gen_timestamp_relative(ts, vidstart, fmt, secs):
	time = (ts - vidstart).total_seconds()
	sign = ''
	if time < 0:
		sign = '\u2212'
		time = -time
	time, s = divmod(int(time), 60)
	h, m = divmod(time, 60)
	if secs:
		return '<span class="chat-timestamp">{}{}:{:02}:{:02}</span>'.format(sign, h, m, s)
	else:
		return '<span class="chat-timestamp">{}{}:{:02}</span>'.format(sign, h, m)

def gen_timestamp_moonbase(ts, vidstart, fmt, secs):
	ts = ts.astimezone(config['timezone'])
	return ('<span class="chat-timestamp">{:' + fmt + '}</span>').format(ts)

def gen_timestamp_local(ts, vidstart, fmt, secs):
	ts = ts.astimezone(config['timezone'])
	return ('<span class="chat-timestamp timestamp-time" data-timestamp="{}">{:' + fmt + '}</span>').format(ts.timestamp(), ts)

gen_timestamp_funcs = {
	TIMESTAMPS_OFF: None,
	TIMESTAMPS_RELATIVE: gen_timestamp_relative,
	TIMESTAMPS_MOONBASE: gen_timestamp_moonbase,
	TIMESTAMPS_LOCAL: gen_timestamp_local,
}

def chat_data(starttime, endtime, vidstart, timestamp_mode, twentyfour, secs):
	gen_timestamps = gen_timestamp_funcs[timestamp_mode]
	fmt = ("%H" if twentyfour else "%I") + ":%M" + (":%S" if secs else "") + ("" if twentyfour else " %p")
	log = server.db.metadata.tables["log"]
	with server.db.engine.connect() as conn:
		res = conn.execute(sqlalchemy.select(log.c.messagehtml, log.c.time)
			.where(log.c.time.between(starttime, endtime))
			.order_by(log.c.time.asc()))
		if gen_timestamps:
			return [
				'<div class="line-wrapper">{} {}</div>'.format(
					gen_timestamps(ts, vidstart, fmt, secs), message)
				for (message, ts) in res]
		else:
			return [message for (message, time) in res]

@utils.cache(CACHE_TIMEOUT, params=[0])
async def get_video_data(videoid):
	try:
		video = await twitch.get_video(videoid)
		start = dateutil.parser.parse(video["created_at"])
		return {
			"start": start,
			"end": start + datetime.timedelta(seconds=utils.parse_duration(video['duration'])),
			"title": video["title"],
			"id": video["id"],
			"channel": video["user_login"]
		}
	except utils.PASSTHROUGH_EXCEPTIONS:
		raise
	except HTTPError as e:
		log.error("Bad video: %r: %r", videoid, e)
	except Exception:
		log.exception("Bad video: %r", videoid)
	return None

@blueprint.route('/archive/<videoid>')
@login.with_session
async def watch(videoid, session):
	starttime = common.time.parsetime(flask.request.values.get('t'))
	if starttime:
		starttime = int(starttime.total_seconds())
	video = await get_video_data(videoid)
	if video is None:
		return "Unrecognised video", 404
	vidstart = video["start"] + datetime.timedelta(seconds=session['user']['stream_delay'])
	chat = chat_data(
		video["start"] - BEFORE_BUFFER,
		video["end"] + AFTER_BUFFER,
		vidstart,
		session['user']['chat_timestamps'],
		session['user']['chat_timestamps_24hr'],
		session['user']['chat_timestamps_secs'],
	)
	return flask.render_template("archive_watch.html", session=session, video=video, vidstart=vidstart, chat=chat, starttime=starttime)
