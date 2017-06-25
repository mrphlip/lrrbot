#!/usr/bin/python3
import sys
argv = sys.argv[1:]
sys.argv = sys.argv[:1]
import json
import regex
import datetime
import dateutil.parser
import common.http
import common.postgres
from common.config import config
import sqlalchemy
from sqlalchemy.dialects import postgresql
import urllib.error

engine, metadata = common.postgres.get_engine_and_metadata()
TBL_CLIPS = metadata.tables['clips']

CLIPS_URL = "https://api.twitch.tv/kraken/clips/top"
VIDEO_URL = "https://api.twitch.tv/kraken/videos/%s"

def get_clips_page(channel, period="day", limit=10, cursor=None):
	"""
	https://dev.twitch.tv/docs/v5/reference/clips/#get-top-clips
	"""
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Accept': 'application/vnd.twitchtv.v5+json',
	}
	params = {
		'channel': channel,
		'limit': str(limit),
		'period': period,
	}
	if cursor is not None:
		params['cursor'] = cursor
	data = common.http.request(CLIPS_URL, params, headers=headers)
	return json.loads(data)

def process_clips(channel, period="day", per_page=10):
	cursor = None
	while True:
		data = get_clips_page(channel, period, per_page, cursor)
		if not data['clips']:
			break
		for clip in data['clips']:
			process_clip(clip)
		cursor = data['_cursor']
		if not cursor:
			break

def get_video_info(vodid):
	"""
	https://dev.twitch.tv/docs/v5/reference/videos/#get-video
	"""
	if vodid not in get_video_info._cache:
		headers = {
			'Client-ID': config['twitch_clientid'],
			'Accept': 'application/vnd.twitchtv.v5+json',
		}
		try:
			data = common.http.request(VIDEO_URL % vodid, headers=headers)
			get_video_info._cache[vodid] = json.loads(data)
		except urllib.error.HTTPError as e:
			if e.code == 404:
				get_video_info._cache[vodid] = {'httperror': 404}
			else:
				raise
	return get_video_info._cache[vodid]
get_video_info._cache = {}

# match a URL like:
#   https://www.twitch.tv/videos/138124005?t=1h13m7s
RE_STARTTIME = regex.compile("^.*\?(?:.*&)?t=(\d+[hms])*(?:&.*)?$")
def process_clip(clip):
	# I wish there was a better way to get the clip "broadcast time"...
	# clip['created_at'] exists, but it's the time the clip was created not when
	# it was broadcast, so it's close when clipped live, but not useful when
	# clipped from a vod...
	if clip['vod']:
		voddata = get_video_info(clip['vod']['id'])
		if 'httperror' not in voddata:
			match = RE_STARTTIME.match(clip['vod']['url'])
			if not match:
				raise ValueError("Couldn't find start time in %r for %s" % (clip['vod']['url'], clip['slug']))
			offset = datetime.timedelta(0)
			for piece in match.captures(1):
				val, unit = int(piece[:-1]), piece[-1]
				if unit == 's':
					offset += datetime.timedelta(seconds=val)
				elif unit == 'm':
					offset += datetime.timedelta(minutes=val)
				elif unit == 'h':
					offset += datetime.timedelta(hours=val)
			vod_start = dateutil.parser.parse(voddata['created_at'])
			clip_start = vod_start + offset
		else:
			clip_start = dateutil.parser.parse(clip['created_at'])
	else:
		clip_start = dateutil.parser.parse(clip['created_at'])
	data = {
		"slug": clip['slug'],
		"title": clip['title'],
		"vodid": clip['vod']['id'] if clip['vod'] else None,
		"time": clip_start,
		"data": json.dumps(clip),
	}
	with engine.begin() as conn:
		query = postgresql.insert(TBL_CLIPS)
		query = query.on_conflict_do_update(
				index_elements=[TBL_CLIPS.c.slug],
				set_={
					'title': query.excluded.title,
					'vodid': query.excluded.vodid,
					'time': query.excluded.time,
					'data': query.excluded.data,
				}
			)
		conn.execute(query, data)

def fix_null_vodids():
	"""
	Occasionally a video won't have vod information... it's probably close to a
	clip from the same vod that does have the id, so find the closest-by-time clip
	that has a vodid, and use that.
	"""
	with engine.begin() as conn:
		badvods = conn.execute(sqlalchemy.select([TBL_CLIPS.c.id, TBL_CLIPS.c.time])
			.where(TBL_CLIPS.c.vodid == None))
		# Get the updated vodids first, then update them all after, so that we don't
		# use the vods we're updating as a source for copying to others...
		updates = []
		for clipid, cliptime in badvods:
			vodid = get_closest_vodid(conn, cliptime)
			updates.append((clipid, vodid))
		for clipid, vodid in updates:
			conn.execute(TBL_CLIPS.update().values(vodid=vodid).where(TBL_CLIPS.c.id == clipid))

def get_closest_vodid(conn, cliptime):
	prevclip = conn.execute(sqlalchemy.select([TBL_CLIPS.c.vodid, TBL_CLIPS.c.time])
		.where(TBL_CLIPS.c.vodid != None)
		.where(TBL_CLIPS.c.time < cliptime)
		.limit(1)
		.order_by(TBL_CLIPS.c.time.desc())).first()
	nextclip = conn.execute(sqlalchemy.select([TBL_CLIPS.c.vodid, TBL_CLIPS.c.time])
		.where(TBL_CLIPS.c.vodid != None)
		.where(TBL_CLIPS.c.time > cliptime)
		.limit(1)
		.order_by(TBL_CLIPS.c.time.asc())).first()

	if prevclip is not None and nextclip is not None:
		prevdiff = cliptime - prevclip[1]
		nextdiff = nextclip[1] - cliptime
		if prevdiff < nextdiff:
			return prevclip[0]
		else:
			return nextclip[0]
	elif prevclip is not None:
		return prevclip[0]
	elif nextclip is not None:
		return prevclip[1]
	else:
		raise ValueError("Can't find any non-null vodids in the DB...")

def main():
	if argv:
		period = argv[0]
		if period not in ('day', 'week', 'month'):
			print("Usage:\n  %s [day|week|month] [channel]" % sys.argv[0])
			sys.exit(1)
	else:
		period = "day"
	channel = argv[1] if len(argv) > 1 else config['channel']
	process_clips(channel, period)
	fix_null_vodids()

if __name__ == '__main__':
	main()
