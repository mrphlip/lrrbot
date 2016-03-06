#!/usr/bin/env python3
import common.postgres
from lrrbot import twitch
from common.highlights import SPREADSHEET, format_row
from common import gdata

import dateutil.parser
import asyncio
import sqlalchemy

engine, metadata = common.postgres.new_engine_and_metadata()

def get_staged_highlights():
	highlights = metadata.tables["highlights"]
	with engine.begin() as conn:
		return [{
			"id": highlight[0],
			"title": highlight[1],
			"description": highlight[2],
			"time": highlight[3],
			"nick": highlight[4],
		} for highlight in conn.execute(sqlalchemy.select([
			highlights.c.id, highlights.c.title, highlights.c.description, highlights.c.time, highlights.c.nick
		])).fetchall()]

def delete_staged_highlights(highlights):
	if len(highlights) == 0:
		return
	highlights_tbl = metadata.tables["highlights"]
	with engine.begin() as conn:
		conn.execute(highlights_tbl.delete().where(highlights_tbl.c.id == sqlalchemy.bindparam("id")), [
			{"id": highlight["id"]}
			for highlight in highlights
		])

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
