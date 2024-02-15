import flask
import sqlalchemy
from sqlalchemy.dialects.postgresql import insert
from collections import defaultdict
from www import server
from www import login
from www.archive import archive_feed_data, get_video_data
from common.config import config
from common.time import nice_duration
from common.twitch import get_user, get_game
import datetime

blueprint = flask.Blueprint("clips", __name__)

@blueprint.route('/')
@login.require_mod
async def vidlist(session):
	clips = server.db.metadata.tables["clips"]
	ext_channel = server.db.metadata.tables["external_channel"]
	ext_vids = server.db.metadata.tables["external_video"]
	with server.db.engine.connect() as conn:
		extravids = set(vid for vid, in conn.execute(sqlalchemy.select(ext_vids.c.vodid)))

		# Start with an empty list we add to, so we don't accidentally append to
		# the list that's cached in archive_feed_data
		videos = []
		# Get all the videos from the main channel, and all the selected videos
		# from the external channels
		videos.extend(await archive_feed_data(config['channel'], True))
		for channel, in conn.execute(sqlalchemy.select(ext_channel.c.channel)):
			extvideos = await archive_feed_data(channel, True)
			videos.extend(v for v in extvideos if v['id'] in extravids)
		videos.sort(key=lambda v:v['created_at'], reverse=True)

		# The archive still gives the ids as "v12345" but the clips use just "12345"
		videoids = [video['id'].lstrip('v') for video in videos]

		clip_counts = defaultdict(lambda:{None: 0, False: 0, True: 0})
		for vodid, rating, clipcount in conn.execute(
				sqlalchemy.select(clips.c.vodid, clips.c.rating, sqlalchemy.func.count())
					.where(clips.c.vodid.in_(videoids))
					.where(clips.c.deleted == False)
					.group_by(clips.c.vodid, clips.c.rating)):
			clip_counts[vodid][rating] += clipcount
	for video in videos:
		video['clips'] = clip_counts[video['id'].lstrip('v')]

	return flask.render_template("clips_vidlist.html", videos=videos,
		main_channel=config['channel'], session=session)

@blueprint.route('/<videoid>')
@login.require_mod
async def vid(session, videoid):
	video = await get_video_data(videoid)

	clips = server.db.metadata.tables["clips"]
	with server.db.engine.connect() as conn:
		clip_data = conn.execute(
			sqlalchemy.select(clips.c.data, clips.c.time, clips.c.rating)
				.where(clips.c.vodid == videoid.lstrip('v'))
				.where(clips.c.deleted == False)
				.order_by(clips.c.time.asc())).fetchall()

	if video is None and clip_data:
		video = {'start': clip_data[0][1], 'title': 'Unknown video'}

	# Note: need to handle both the v5 and Helix data schemas as both are present
	# in the database
	clip_data = [
		{
			"slug": clip.get('id') or clip.get('slug'),
			"title": clip['title'],
			"curator": clip.get('creator_name') or clip.get('curator', {}).get('display_name'),
			"starttime": time - video['start'],
			"endtime": time - video['start'] + datetime.timedelta(seconds=clip['duration']),
			"start": nice_duration(time - video['start'], 0),
			"duration": nice_duration(clip['duration'], 0),
			"game": (await get_game(id=clip['game_id'])).name if clip.get('game_id') else clip.get('game'),
			"thumbnail": clip.get('thumbnail_url') or clip.get('thumbnails', {}).get('small'),
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

	parent = flask.request.host
	if ':' in parent:
		parent = parent.split(':', 1)[0]
	return flask.render_template("clips_vid.html", video=video, clips=clip_data, session=session, parent=parent)

@blueprint.route('/submit', methods=['POST'])
@login.require_mod
def submit(session):
	clips = server.db.metadata.tables["clips"]
	with server.db.engine.connect() as conn:
		conn.execute(clips.update()
			.values(
				rating=bool(int(flask.request.values['vote'])),
				rated_by=session['active_account']['id'],
			)
			.where(clips.c.slug == flask.request.values['slug'])
		)
		conn.commit()
	return flask.json.jsonify(success='OK')

@blueprint.route('/external')
@login.require_mod
async def external(session):
	ext_channel = server.db.metadata.tables["external_channel"]
	ext_vids = server.db.metadata.tables["external_video"]
	external_channels = []
	with server.db.engine.connect() as conn:
		for chanid, channel in conn.execute(sqlalchemy.select(ext_channel.c.id, ext_channel.c.channel)):
			external_channels.append({
				'id': chanid,
				'channel': await get_user(name=channel),
				'videos': await archive_feed_data(channel, True),
				'selected': set(vid for vid, in conn.execute(sqlalchemy.select(ext_vids.c.vodid).where(ext_vids.c.channel == chanid))),
			})

	return flask.render_template("clips_external.html", session=session, channels=external_channels)

@blueprint.route('/external', methods=['POST'])
@login.require_mod
async def external_save(session):
	ext_channel = server.db.metadata.tables["external_channel"]
	ext_vids = server.db.metadata.tables["external_video"]
	if flask.request.values['action'] == "videos":
		# Save video selection
		with server.db.engine.connect() as conn:
			videos = []
			for video in flask.request.values.getlist('selected'):
				chanid, vodid = video.split('-', 1)
				videos.append({
					"channel": int(chanid),
					"vodid": vodid,
				})
			query = insert(ext_vids).on_conflict_do_nothing(index_elements=[ext_vids.c.vodid])
			conn.execute(query, videos)

			conn.execute(ext_vids.delete().where(ext_vids.c.vodid.notin_(v['vodid'] for v in videos)))

			conn.commit()
		return flask.redirect(flask.url_for('clips.vidlist'), code=303)
	elif flask.request.values['action'] == "add":
		# Add a new channel
		channel = await get_user(name=flask.request.values['channel'])
		with server.db.engine.connect() as conn:
			conn.execute(ext_channel.insert(), {"channel": channel.name})
			conn.commit()
		return flask.redirect(flask.url_for('clips.external'), code=303)
	elif flask.request.values['action'] == "remove":
		channel = int(flask.request.values['channel'])
		with server.db.engine.connect() as conn:
			conn.execute(ext_channel.delete().where(ext_channel.c.id == channel))
			conn.commit()
		return flask.redirect(flask.url_for('clips.external'), code=303)
	else:
		raise ValueError("Unexpected mode %r" % flask.request.values['action'])
