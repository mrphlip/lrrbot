#!/usr/bin/env python
import flask
import flask.json
import server
import login
import urllib.request, urllib.parse
import time
import os
import datetime
import dateutil.parser
import utils
import contextlib
import re
import jinja2.utils

CACHE_TIMEOUT = 15*60

BEFORE_BUFFER = 15*60
AFTER_BUFFER = 15*60

def archive_feed_data(channel, broadcasts):
	fn = "../twitchcache_%s_%s.json" % (channel, broadcasts)

	try:
		fileage = time.time() - os.stat(fn).st_mtime
	except IOError:
		fileage = CACHE_TIMEOUT

	if fileage < CACHE_TIMEOUT:
		with open(fn, "rb") as fp:
			data = fp.read()
	else:
		url = "https://api.twitch.tv/kraken/channels/%s/videos?broadcasts=%s&limit=%d" % (urllib.parse.quote(channel, safe=""), "true" if broadcasts else "false", 100)
		fp = urllib.request.urlopen(url)
		data = fp.read().decode()
		fp.close()
		with open(fn, "wb") as fp:
			fp.write(data.encode("utf-8"))

	# For broadcasts:
	# {'videos': [{'_id': 'a508090853',
	#              '_links': {'channel': 'https://api.twitch.tv/kraken/channels/loadingreadyrun',
	#                         'self': 'https://api.twitch.tv/kraken/videos/a508090853'},
	#              'broadcast_id': 8737631504,
	#              'channel': {'display_name': 'LoadingReadyRun',
	#                          'name': 'loadingreadyrun'},
	#              'description': None,
	#              'game': 'Prince of Persia: Warrior Within',
	#              'length': 9676,
	#              'preview': 'http://static-cdn.jtvnw.net/jtv.thumbs/archive-508090853-320x240.jpg',
	#              'recorded_at': '2014-03-04T02:40:58Z',
	#              'title': "Beej's Backlog - Playing PoP: WW",
	#              'url': 'http://www.twitch.tv/loadingreadyrun/b/508090853',
	#              'views': 0},
	#              ...]}
	# For highlights:
	# {'videos': [{'_id': 'c3518839',
	#              '_links': {'channel': 'https://api.twitch.tv/kraken/channels/loadingreadyrun',
	#                         'self': 'https://api.twitch.tv/kraken/videos/c3518839'},
	#              'broadcast_id': 8137157616,
	#              'channel': {'display_name': 'LoadingReadyRun',
	#                          'name': 'loadingreadyrun'},
	#              'description': "Beej's gets up to speed in Prince of Persia: Warrior Within",
	#              'game': 'Prince of Persia: Warrior Within',
	#              'length': 3557,
	#              'preview': 'http://static-cdn.jtvnw.net/jtv.thumbs/archive-493319305-320x240.jpg',
	#              'recorded_at': '2014-01-07T04:16:42Z',
	#              'title': "Beej's Backlog —2014-01-06 PT2",
	#              'url': 'http://www.twitch.tv/loadingreadyrun/c/3518839',
	#              'views': 466},
	#              ...]}

	videos = flask.json.loads(data)['videos']
	for video in videos:
		video["recorded_at"] = dateutil.parser.parse(video["recorded_at"])
	return videos

@server.app.route('/archive')
@login.with_session
def archive(session):
	channel = flask.request.values.get('channel', 'loadingreadyrun')
	broadcasts = 'highlights' not in flask.request.values
	return flask.render_template("archive.html", videos=archive_feed_data(channel, broadcasts), broadcasts=broadcasts, session=session)

@server.app.route('/archivefeed')
def archive_feed():
	channel = flask.request.values.get('channel', 'loadingreadyrun')
	broadcasts = 'highlights' not in flask.request.values
	rss = flask.render_template("archive_feed.xml", videos=archive_feed_data(channel, broadcasts), broadcasts=broadcasts)
	return flask.Response(rss, mimetype="application/xml")

def chat_data(conn, cur, starttime, endtime, target="#loadingreadyrun"):
	cur.execute("SELECT MESSAGEHTML FROM LOG WHERE TARGET=? AND TIME BETWEEN ? AND ? ORDER BY TIME ASC", (
		target,
		starttime,
		endtime
	))
	for message, in cur:
		yield message

@utils.throttle(24*60*60, params=[0])
def get_video_data(videoid):
	try:
		with contextlib.closing(urllib.request.urlopen("https://api.twitch.tv/kraken/videos/%s" % videoid)) as fp:
			video = flask.json.load(fp)
		start = dateutil.parser.parse(video["recorded_at"]).timestamp()
		return {
			"start": start,
			"end": start + video["length"],
			"title": video["title"],
			"type": {"a": "archive", "c": "chapter"}[videoid[0]],
			"id": videoid[1:],
			"channel": video["channel"]["name"]
		}
	except:
		return None

@server.app.route('/archive/<videoid>')
@utils.with_mysql
def archive_watch(conn, cur, videoid):
	starttime = utils.parsetime(flask.request.values.get('t'))
	if starttime:
		starttime = int(starttime.total_seconds())
	video = get_video_data(videoid)
	if video is None:
		return "Unrecognised video"
	chat = chat_data(conn, cur, video["start"] - BEFORE_BUFFER, video["end"] + AFTER_BUFFER)
	return flask.render_template("archive_watch.html", video=video, chat=chat, starttime=starttime)
