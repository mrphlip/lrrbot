#!/usr/bin/env python3

from lrrbot import twitch
from common.highlights import SPREADSHEET, format_row
from common import utils, gdata

import dateutil.parser
import asyncio

@utils.with_postgres
def get_staged_highlights(conn, cur):
	cur.execute("SELECT id, title, description, time, nick FROM highlights")
	return [{
		"id": highlight[0],
		"title": highlight[1],
		"description": highlight[2],
		"time": highlight[3],
		"nick": highlight[4],
	} for highlight in cur]

@utils.with_postgres
def delete_staged_highlights(conn, cur, highlights):
	cur.executemany("DELETE FROM highlights WHERE id = %s", [(highlight["id"], ) for highlight in highlights])

@asyncio.coroutine
def get_videos(*args, **kwargs):
	videos = yield from twitch.get_videos(*args, **kwargs)
	for video in videos:
		video["recorded_at"] = dateutil.parser.parse(video["recorded_at"])
	return videos

@asyncio.coroutine
def lookup_video(highlight, videos):
	while True:
		for video in videos:
			if video["recorded_at"] <= highlight["time"]:
				if (highlight["time"] - video["recorded_at"]).total_seconds() <= video["length"]:
					return video
				raise Exception("No video found for highlight %r" % highlight)
		more_videos = yield from get_videos(broadcasts=True, offset=len(videos))
		if len(more_videos) == 0:
			raise Exception("Out of videos for highlight %r" % highlight)
		videos += more_videos

@asyncio.coroutine
def main():
	if twitch.get_info()["live"]:
		print("Stream is live.")
		return

	highlights = get_staged_highlights()
	videos = []
	for highlight in highlights:
		highlight["video"] = yield from lookup_video(highlight, videos)

	yield from gdata.add_rows_to_spreadsheet(SPREADSHEET, [
		format_row(highlight["title"], highlight["description"], highlight["video"]["url"],
			 highlight["time"] - highlight["video"]["recorded_at"], highlight["nick"])
		for highlight in highlights
	])
	delete_staged_highlights(highlights)

if __name__ == '__main__':
	asyncio.get_event_loop().run_until_complete(main())
