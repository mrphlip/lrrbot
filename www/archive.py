import urllib.request
import urllib.parse
import urllib.error
import contextlib
import datetime
import copy
import logging

import flask
import flask.json
import dateutil.parser
import asyncio
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

@utils.cache(CACHE_TIMEOUT, params=[0, 1, 2])
async def archive_feed_data(channel, broadcasts, extravids=None):
	videos = await twitch.get_videos(channel, broadcasts=broadcasts, limit=100)
	if extravids:
		for vid in extravids:
			try:
				video = await twitch.get_video(vid)
			except urllib.error.HTTPError:
				pass
			else:
				videos.append(video)

	for video in videos:
		if video.get('created_at'):
			video["created_at"] = dateutil.parser.parse(video["created_at"])
		if video.get('delete_at'):
			video["delete_at"] = dateutil.parser.parse(video["delete_at"])
		if video.get('recorded_at'):
			video["recorded_at"] = dateutil.parser.parse(video["recorded_at"])

	videos.sort(key=lambda v:v.get('recorded_at'), reverse=True)
	return videos

async def archive_feed_data_html(channel, broadcasts, rss):
	# Deep copy so we don't modify the cached data
	data = copy.deepcopy(await archive_feed_data(channel, broadcasts))
	for vid in data:
		# For new vods, sometimes: vid['thumbnails'] == "https://www.twitch.tv/images/xarth/404_processing_320x240.png"
		if isinstance(vid['thumbnails'], dict) and isinstance(vid['thumbnails'].get('medium'), list):
			vid['thumbnails'] = [i for i in vid['thumbnails']['medium'] if i['url'] != vid['preview']['medium']]
		else:
			vid['thumbnails'] = []
		vid['html'] = flask.render_template("archive_video.html", vid=vid, rss=rss)
	return data

@server.app.route('/archive')
@login.with_session
async def archive(session):
	channel = flask.request.values.get('channel', 'loadingreadyrun')
	broadcasts = 'highlights' not in flask.request.values
	return flask.render_template("archive.html", videos=await archive_feed_data_html(channel, broadcasts, False), broadcasts=broadcasts, session=session)

@server.app.route('/archivefeed')
async def archive_feed():
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

def chat_data(starttime, endtime, vidstart, timestamp_mode, twentyfour, secs, target="#loadingreadyrun"):
	gen_timestamps = gen_timestamp_funcs[timestamp_mode]
	fmt = ("%H" if twentyfour else "%I") + ":%M" + (":%S" if secs else "") + ("" if twentyfour else " %p")
	log = server.db.metadata.tables["log"]
	with server.db.engine.begin() as conn:
		res = conn.execute(sqlalchemy.select([log.c.messagehtml, log.c.time])
			.where((log.c.target == target) & log.c.time.between(starttime, endtime))
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
		start = dateutil.parser.parse(video["recorded_at"])
		return {
			"start": start,
			"end": start + datetime.timedelta(seconds=video["length"]),
			"title": video["title"],
			"id": videoid,
			"channel": video["channel"]["name"]
		}
	except utils.PASSTHROUGH_EXCEPTIONS:
		raise
	except Exception:
		log.exception("Bad video: %r", videoid)
		return None

@server.app.route('/archive/<videoid>')
@login.with_session
async def archive_watch(videoid, session):
	starttime = common.time.parsetime(flask.request.values.get('t'))
	if starttime:
		starttime = int(starttime.total_seconds())
	video = await get_video_data(videoid)
	if video is None:
		return "Unrecognised video"
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
