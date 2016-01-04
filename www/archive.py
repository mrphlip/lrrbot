import urllib.parse
import datetime
import asyncio

import flask
import flask.json
import dateutil.parser
import asyncio

from common import utils
from www import server
from www import login


CACHE_TIMEOUT = 5*60

BEFORE_BUFFER = datetime.timedelta(minutes=15)
AFTER_BUFFER = datetime.timedelta(minutes=15)

@utils.cache(CACHE_TIMEOUT, params=[0, 1])
@asyncio.coroutine
def archive_feed_data(channel, broadcasts):
	params = {
		"broadcasts": "true" if broadcasts else "false",
		"limit": 100,
	}
	data = yield from utils.http_request("https://api.twitch.tv/kraken/channels/%s/videos" % urllib.parse.quote(channel, safe=""), data=params)

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
@asyncio.coroutine
def archive(session):
	channel = flask.request.values.get('channel', 'loadingreadyrun')
	broadcasts = 'highlights' not in flask.request.values
	videos = yield from archive_feed_data(channel, broadcasts)
	return flask.render_template("archive.html", videos=videos, broadcasts=broadcasts, session=session)

@server.app.route('/archivefeed')
@asyncio.coroutine
def archive_feed():
	channel = flask.request.values.get('channel', 'loadingreadyrun')
	broadcasts = 'highlights' not in flask.request.values
	videos = yield from archive_feed_data(channel, broadcasts)
	rss = flask.render_template("archive_feed.xml", videos=videos, broadcasts=broadcasts)
	return flask.Response(rss, mimetype="application/xml")

@utils.with_postgres
def chat_data(conn, cur, starttime, endtime, target="#loadingreadyrun"):
	cur.execute("SELECT messagehtml FROM log WHERE target = %s AND time BETWEEN %s AND %s ORDER BY time ASC", (
		target,
		starttime,
		endtime
	))
	return [message for (message,) in cur]

@utils.cache(CACHE_TIMEOUT, params=[0])
@asyncio.coroutine
def get_video_data(videoid):
	try:
		data = yield from utils.http_request("https://api.twitch.tv/kraken/videos/%s" % videoid)
		video = flask.json.loads(data)
		start = dateutil.parser.parse(video["recorded_at"])
		return {
			"start": start,
			"end": start + datetime.timedelta(seconds=video["length"]),
			"title": video["title"],
			"id": videoid,
			"channel": video["channel"]["name"]
		}
	except:
		return None

@utils.cache(86400)
@asyncio.coroutine
def get_player_url():
	"""
	The player URL sometimes redirects to a non-HTTPS url, but the CDN still supports HTTPS,
	so get the real URL so we can serve it over the right protocol
	"""
	urls = yield from utils.canonical_url("https://www-cdn.jtvnw.net/swflibs/TwitchPlayer.swf")
	return urls[-1]

@server.app.route('/archive/<videoid>')
@asyncio.coroutine
def archive_watch(videoid):
	starttime = utils.parsetime(flask.request.values.get('t'))
	if starttime:
		starttime = int(starttime.total_seconds())
	video = yield from get_video_data(videoid)
	if video is None:
		return "Unrecognised video"
	chat = chat_data(video["start"] - BEFORE_BUFFER, video["end"] + AFTER_BUFFER)
	player_url = yield from get_player_url()
	return flask.render_template("archive_watch.html", video=video, chat=chat, starttime=starttime, player_url=player_url)
