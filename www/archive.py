import urllib.request
import urllib.parse
import contextlib
import datetime
import copy

import flask
import flask.json
import dateutil.parser
import asyncio
import sqlalchemy

import common.time
import common.url
from common import utils
from common.config import config
from www import server
from www import login

CACHE_TIMEOUT = 5*60

BEFORE_BUFFER = datetime.timedelta(minutes=15)
AFTER_BUFFER = datetime.timedelta(minutes=15)

@utils.cache(CACHE_TIMEOUT, params=[0, 1, 2])
def archive_feed_data(channel, broadcasts, extravids=None):
	url = "https://api.twitch.tv/kraken/channels/%s/videos?broadcasts=%s&limit=%d" % (urllib.parse.quote(channel, safe=""), "true" if broadcasts else "false", 100)
	req = urllib.request.Request(url)
	req.add_header('Client-ID', config['twitch_clientid'])
	fp = urllib.request.urlopen(req)
	data = fp.read()
	fp.close()
	data = data.decode()
	videos = flask.json.loads(data)['videos']

	if extravids:
		for vid in extravids:
			url = "https://api.twitch.tv/kraken/videos/%s" % vid
			req = urllib.request.Request(url)
			req.add_header('Client-ID', config['twitch_clientid'])
			fp = urllib.request.urlopen(req)
			data = fp.read()
			fp.close()
			data = data.decode()
			videos.append(flask.json.loads(data))

	# {u'_id': u'v40431562',
	#  u'_links': {u'channel': u'https://api.twitch.tv/kraken/channels/loadingreadyrun',
	#              u'self': u'https://api.twitch.tv/kraken/videos/v40431562'},
	#  u'broadcast_id': 19364042672,
	#  u'broadcast_type': u'archive',
	#  u'channel': {u'display_name': u'LoadingReadyRun',
	#               u'name': u'loadingreadyrun'},
	#  u'created_at': u'2016-02-04T23:09:08Z',
	#  u'delete_at': u'2016-04-04T23:08:48Z',
	#  u'description': None,
	#  u'fps': {u'audio_only': 0.0,
	#           u'chunked': 29.9998810184294,
	#           u'high': 29.9998810184294,
	#           u'low': 29.9998810184294,
	#           u'medium': 29.9998810184294,
	#           u'mobile': 29.9998810184294},
	#  u'game': u'Magic: The Gathering',
	#  u'is_muted': False,
	#  u'length': 13615,
	#  u'preview': u'https://static-cdn.jtvnw.net/v1/AUTH_system/vods_f4a3/loadingreadyrun_19364042672_395185311/thumb/thumb0-320x240.jpg',
	#  u'recorded_at': u'2016-02-04T23:08:48Z',
	#  u'resolutions': {u'chunked': u'1920x1080',
	#                   u'high': u'1280x720',
	#                   u'low': u'640x360',
	#                   u'medium': u'852x480',
	#                   u'mobile': u'400x226'},
	#  u'status': u'recorded',
	#  u'tag_list': u'',
	#  u'thumbnails': [{u'type': u'generated',
	#                   u'url': u'https://static-cdn.jtvnw.net/v1/AUTH_system/vods_f4a3/loadingreadyrun_19364042672_395185311/thumb/thumb0-320x240.jpg'},
	#                  {u'type': u'generated',
	#                   u'url': u'https://static-cdn.jtvnw.net/v1/AUTH_system/vods_f4a3/loadingreadyrun_19364042672_395185311/thumb/thumb1-320x240.jpg'},
	#                  {u'type': u'generated',
	#                   u'url': u'https://static-cdn.jtvnw.net/v1/AUTH_system/vods_f4a3/loadingreadyrun_19364042672_395185311/thumb/thumb2-320x240.jpg'},
	#                  {u'type': u'generated',
	#                   u'url': u'https://static-cdn.jtvnw.net/v1/AUTH_system/vods_f4a3/loadingreadyrun_19364042672_395185311/thumb/thumb3-320x240.jpg'}],
	#  u'title': u'LRRMtG || Thursday Afternoon Draft-O!!!',
	#  u'url': u'http://www.twitch.tv/loadingreadyrun/v/40431562',
	#  u'views': 46,
	#  u'vod_type': u'archive'}

	for video in videos:
		if video.get('created_at'):
			video["created_at"] = dateutil.parser.parse(video["created_at"])
		if video.get('delete_at'):
			video["delete_at"] = dateutil.parser.parse(video["delete_at"])
		if video.get('recorded_at'):
			video["recorded_at"] = dateutil.parser.parse(video["recorded_at"])

	videos.sort(key=lambda v:v.get('recorded_at'), reverse=True)
	return videos

def archive_feed_data_html(channel, broadcasts, rss):
	# Deep copy so we don't modify the cached data
	data = copy.deepcopy(archive_feed_data(channel, broadcasts))
	for vid in data:
		# For new clips, sometimes: vid['thumbnails'] == "https://www.twitch.tv/images/xarth/404_processing_320x240.png"
		if isinstance(vid['thumbnails'], list):
			vid['thumbnails'] = [i for i in vid['thumbnails'] if i['url'] != vid['preview']]
		else:
			vid['thumbnails'] = []
		vid['html'] = flask.render_template("archive_video.html", vid=vid, rss=rss)
	return data

@server.app.route('/archive')
@login.with_session
def archive(session):
	channel = flask.request.values.get('channel', 'loadingreadyrun')
	broadcasts = 'highlights' not in flask.request.values
	return flask.render_template("archive.html", videos=archive_feed_data_html(channel, broadcasts, False), broadcasts=broadcasts, session=session)

@server.app.route('/archivefeed')
def archive_feed():
	channel = flask.request.values.get('channel', 'loadingreadyrun')
	broadcasts = 'highlights' not in flask.request.values
	rss = flask.render_template("archive_feed.xml", videos=archive_feed_data_html(channel, broadcasts, True), broadcasts=broadcasts)
	return flask.Response(rss, mimetype="application/xml")

def chat_data(starttime, endtime, target="#loadingreadyrun"):
	log = server.db.metadata.tables["log"]
	with server.db.engine.begin() as conn:
		res = conn.execute(sqlalchemy.select([log.c.messagehtml])
			.where((log.c.target == target) & log.c.time.between(starttime, endtime))
			.order_by(log.c.time.asc()))
		return [message for (message,) in res]

@utils.cache(CACHE_TIMEOUT, params=[0])
def get_video_data(videoid):
	try:
		url = "https://api.twitch.tv/kraken/videos/%s" % (videoid, )
		req = urllib.request.Request(url)
		req.add_header('Client-ID', config['twitch_clientid'])
		with contextlib.closing(urllib.request.urlopen(req)) as fp:
			video = flask.json.load(fp)
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
		return None

@server.app.route('/archive/<videoid>')
def archive_watch(videoid):
	starttime = common.time.parsetime(flask.request.values.get('t'))
	if starttime:
		starttime = int(starttime.total_seconds())
	video = get_video_data(videoid)
	if video is None:
		return "Unrecognised video"
	chat = chat_data(video["start"] - BEFORE_BUFFER, video["end"] + AFTER_BUFFER)
	return flask.render_template("archive_watch.html", video=video, chat=chat, starttime=starttime)
