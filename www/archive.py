#!/usr/bin/env python
import flask
import flask.json
import server
import urllib.request, urllib.parse
import time
import os
import dateutil.parser

CACHE_TIMEOUT = 15*60

def format_time(video):
    recorded_at = dateutil.parser.parse(video["recorded_at"])
    video["recorded_at"] = "{:%a, %d %b %Y %H:%M:%S %z}".format(recorded_at)
    return video

@server.app.route('/archivefeed')
def archive_feed():
	channel = flask.request.values.get('channel', 'loadingreadyrun')
	broadcasts = 'highlights' not in flask.request.values
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

	videos = flask.json.loads(data)['videos']
	videos = [format_time(video) for video in videos]

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

	rss = flask.render_template("archive_feed.xml", videos=videos, broadcasts=broadcasts)
	return flask.Response(rss, mimetype="application/xml")
