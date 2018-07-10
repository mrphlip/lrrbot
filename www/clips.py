import flask
import sqlalchemy
from collections import defaultdict
from www import server
from www import login
from www.archive import archive_feed_data, get_video_data
import common.rpc
from common.time import nice_duration
import dateutil.parser
import datetime

# TODO: move this somewhere easier to edit, like the DB or something?
EXTRA_VIDS = ('v282776393', )

@server.app.route('/clips')
@login.require_mod
async def clips_vidlist(session):
	videos = await archive_feed_data('loadingreadyrun', True, extravids=EXTRA_VIDS)
	# The archive still gives the ids as "v12345" but the clips use just "12345"
	videoids = [video['_id'].lstrip('v') for video in videos]

	clips = server.db.metadata.tables["clips"]
	clip_counts = defaultdict(lambda:{None: 0, False: 0, True: 0})
	with server.db.engine.begin() as conn:
		for vodid, rating, clipcount in conn.execute(
				sqlalchemy.select([clips.c.vodid, clips.c.rating, sqlalchemy.func.count()])
					.where(clips.c.vodid.in_(videoids))
					.where(clips.c.deleted == False)
					.group_by(clips.c.vodid, clips.c.rating)):
			clip_counts[vodid][rating] += clipcount
	for video in videos:
		video['clips'] = clip_counts[video['_id'].lstrip('v')]

	return flask.render_template("clips_vidlist.html", videos=videos, session=session)

@server.app.route('/clips/<videoid>')
@login.require_mod
async def clips_vid(session, videoid):
	video = await get_video_data(videoid)

	clips = server.db.metadata.tables["clips"]
	with server.db.engine.begin() as conn:
		clip_data = conn.execute(
			sqlalchemy.select([clips.c.data, clips.c.time, clips.c.rating])
				.where(clips.c.vodid == videoid.lstrip('v'))
				.where(clips.c.deleted == False)
				.order_by(clips.c.time.asc())).fetchall()

	if video is None and clip_data:
		video = {'start': clip_data[0][1], 'title': 'Unknown video'}

	clip_data = [
		{
			"slug": clip['slug'],
			"title": clip['title'],
			"curator": clip['curator']['display_name'],
			"starttime": time - video['start'],
			"endtime": time - video['start'] + datetime.timedelta(seconds=clip['duration']),
			"start": nice_duration(time - video['start'], 0),
			"duration": nice_duration(clip['duration'], 0),
			"embed_html": clip['embed_html'],
			"game": clip['game'],
			"thumbnail": clip['thumbnails']['small'],
			"rating": rating,
			"overlap": False,
		}
		for clip, time, rating in clip_data
	]
	lastend = None
	prevclip = None
	for clip in clip_data:
		if lastend is not None and clip['starttime'] <= lastend:
			clip['overlap'] = True
		if lastend is None or lastend < clip['endtime']:
			lastend = clip['endtime']

	return flask.render_template("clips_vid.html", video=video, clips=clip_data, session=session)

@server.app.route('/clips/submit', methods=['POST'])
@login.require_mod
def clip_submit(session):
	clips = server.db.metadata.tables["clips"]
	with server.db.engine.begin() as conn:
		conn.execute(clips.update()
			.values(rating=bool(int(flask.request.values['vote'])))
			.where(clips.c.slug == flask.request.values['slug'])
		)
	return flask.json.jsonify(success='OK', csrf_token=server.app.csrf_token())
