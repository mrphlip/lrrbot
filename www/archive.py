#!/usr/bin/env python
# -*- coding: utf-8 -*-
import cgi
import cgitb
import json
import urllib, urllib2
import time
import os
import pyratemp
import utils

CACHE_TIMEOUT = 15*60

# Enable debug errors
# cgitb.enable()

request = cgi.parse()

def archive_feed():
	#channel = request.get('channel', ['loadingreadyrun'])[0]
	channel = "loadingreadyrun"
	broadcasts = 'highlights' not in request
	fn = "../twitchcache_%s_%s.json" % (channel, broadcasts)

	try:
		fileage = time.time() - os.stat(fn).st_mtime
	except OSError:
		fileage = CACHE_TIMEOUT

	if fileage < CACHE_TIMEOUT:
		with open(fn, "r") as fp:
			data = fp.read().decode("utf-8")
	else:
		url = "https://api.twitch.tv/kraken/channels/%s/videos?broadcasts=%s&limit=%d" % (urllib.quote(channel, safe=""), "true" if broadcasts else "false", 100)
		fp = urllib2.urlopen(url)
		data = fp.read().decode("utf-8")
		fp.close()
		with open(fn, "w") as fp:
			fp.write(data.encode("utf-8"))

	data = json.loads(data)

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

	print "Content-type: application/xml; charset=utf-8"
	print
	template = pyratemp.Template(filename="tpl/archive_feed.xml")
	print template(videos=data['videos'], broadcasts=broadcasts, nice_duration=utils.nice_duration).encode("utf-8")

archive_feed()
