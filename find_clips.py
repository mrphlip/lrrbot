#!/usr/bin/env python3

import sys
argv = sys.argv[1:]
sys.argv = sys.argv[:1]
import argparse
import json
import regex
import datetime
import dateutil.parser
import pytz
import common.http
import common.postgres
from common.config import config
from common.twitch import get_user, get_token
import sqlalchemy
from sqlalchemy.dialects import postgresql
import urllib.error

engine, metadata = common.postgres.get_engine_and_metadata()
TBL_CLIPS = metadata.tables['clips']
TBL_EXT_CHANNEL = metadata.tables['external_channel']

CLIPS_URL = "https://api.twitch.tv/helix/clips"

def get_clips_page(channel, period=1, limit=100, cursor=None):
	"""
	https://dev.twitch.tv/docs/api/reference#get-clips
	"""
	channel_id = get_user(name=channel).id
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {get_token()}",
	}
	start, end = get_period(period)
	params = {
		'broadcaster_id': channel_id,
		'first': str(limit),
		'started_at': start.isoformat(),
		'ended_at': end.isoformat(),
	}
	if cursor is not None:
		params['after'] = cursor
	data = common.http.request(CLIPS_URL, params, headers=headers)
	return json.loads(data)

def get_all_clips(channel, period=1, per_page=100):
	cursor = None
	while True:
		data = get_clips_page(channel, period, per_page, cursor)
		if not data['data']:
			break
		yield from data['data']
		cursor = data.get('pagination', {}).get('cursor')
		if not cursor:
			break

def get_clip_info(slug, check_missing=False):
	"""
	https://dev.twitch.tv/docs/api/reference#get-clips
	"""
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f"Bearer {get_token()}",
	}
	params = {
		'id': slug,
	}
	try:
		data = common.http.request(CLIPS_URL, params, headers=headers)
	except urllib.error.HTTPError as e:
		if e.code == 404 and check_missing:
			return None
		else:
			raise
	else:
		data = json.loads(data)
		if check_missing and not data.get('data'):
			return None
		return data['data'][0]

def process_clips(channel, period=1, per_page=100):
	slugs = []
	for clip in get_all_clips(channel, period, per_page):
		process_clip(clip)
		slugs.append(clip['id'])
	return slugs

def process_clip(clip):
	# With the new Twitch API they've gotten rid of even the janky way to know when a clip happened
	# all we have is clip['created_at'], which is the time it was clipped
	# which can be wildly different, especially if it's clipped from a vod
	data = {
		"slug": clip['id'],
		"title": clip['title'],
		"vodid": clip['video_id'],
		"time": dateutil.parser.parse(clip['created_at']),
		"data": clip,
		"deleted": False,
		"channel": clip['broadcaster_name'],
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
					'deleted': query.excluded.deleted,
					'channel': query.excluded.channel,
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
		badvods = conn.execute(sqlalchemy
			.select([TBL_CLIPS.c.id, TBL_CLIPS.c.time, TBL_CLIPS.c.channel])
			.where(TBL_CLIPS.c.vodid == None))
		# Get the updated vodids first, then update them all after, so that we don't
		# use the vods we're updating as a source for copying to others...
		updates = []
		for clipid, cliptime, channel in badvods:
			vodid = get_closest_vodid(conn, cliptime, channel)
			updates.append((clipid, vodid))
		for clipid, vodid in updates:
			conn.execute(TBL_CLIPS.update().values(vodid=vodid).where(TBL_CLIPS.c.id == clipid))

def get_closest_vodid(conn, cliptime, channel):
	prevclip = conn.execute(sqlalchemy.select([TBL_CLIPS.c.vodid, TBL_CLIPS.c.time])
		.where(TBL_CLIPS.c.vodid != None)
		.where(TBL_CLIPS.c.time < cliptime)
		.where(TBL_CLIPS.c.channel == channel)
		.limit(1)
		.order_by(TBL_CLIPS.c.time.desc())).first()
	nextclip = conn.execute(sqlalchemy.select([TBL_CLIPS.c.vodid, TBL_CLIPS.c.time])
		.where(TBL_CLIPS.c.vodid != None)
		.where(TBL_CLIPS.c.time > cliptime)
		.where(TBL_CLIPS.c.channel == channel)
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

def check_deleted_clips(period, slugs):
	"""
	Go through any clips we have in the DB that weren't returned from the Twitch
	query, and check if they actually exist (maybe they dropped out of the "last
	day" early) or if they've been deleted, in which case mark that in the DB.
	"""
	start, _ = get_period(period)
	with engine.begin() as conn:
		clips = conn.execute(sqlalchemy.select([TBL_CLIPS.c.id, TBL_CLIPS.c.slug])
			.where(TBL_CLIPS.c.time >= start)
			.where(TBL_CLIPS.c.slug.notin_(slugs))
			.where(TBL_CLIPS.c.deleted == False))
		for clipid, slug in clips:
			if get_clip_info(slug, check_missing=True) is None:
				conn.execute(TBL_CLIPS.update().values(deleted=True).where(TBL_CLIPS.c.id == clipid))

def get_period(period):
	end = datetime.datetime.now(pytz.UTC)
	start = end - datetime.timedelta(days=period)
	return start, end

def get_default_channels():
	channels = [config['channel']]
	with engine.begin() as conn:
		channels.extend(channel for channel, in conn.execute(
			sqlalchemy.select([TBL_EXT_CHANNEL.c.channel])))
	return channels

def parse_args():
	parser = argparse.ArgumentParser(description="Fetch clips from Twitch channel")
	parser.add_argument('-p', '--per_page', default=10, type=int)
	parser.add_argument('period', type=int, nargs='?', default=1)
	parser.add_argument('channel', nargs='*', default=get_default_channels())
	return parser.parse_args(argv)

def main():
	args = parse_args()
	for channel in args.channel:
		slugs = process_clips(channel, args.period, args.per_page)
	fix_null_vodids()
	check_deleted_clips(args.period, slugs)

if __name__ == '__main__':
	main()
