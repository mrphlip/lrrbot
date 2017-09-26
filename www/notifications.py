import datetime
import pytz

import flask
import flask.json
from flaskext.csrf import csrf_exempt
import sqlalchemy

import common.time
from common import utils
from common.config import config
from www import server
from www import login

MILESTONES = [
	("Twitch Prime", config["timezone"].localize(datetime.datetime(2016, 9, 30, 12, 0))),
	("LoadingReadyLive premiere", config["timezone"].localize(datetime.datetime(2016, 5, 14, 17, 0))),
	("Pre-PreRelease premiere", config["timezone"].localize(datetime.datetime(2016, 3, 26, 12, 0))),
	("YRR of LRR finale", config["timezone"].localize(datetime.datetime(2014, 12, 29, 18, 30))),
	("YRR of LRR launch", config["timezone"].localize(datetime.datetime(2014, 1, 7))),
	("Twitch partnership", config["timezone"].localize(datetime.datetime(2013, 8, 31, 10, 0))),
	("First Twitch stream", config["timezone"].localize(datetime.datetime(2012, 1, 14, 21, 0))),
	("LoadingReadyRun launch", config["timezone"].localize(datetime.datetime(2003, 10, 24))),
]

def get_events():
	events = server.db.metadata.tables['events']
	recent_events = []
	query = sqlalchemy.select([events.c.id, events.c.event, events.c.data, events.c.time, sqlalchemy.func.current_timestamp() - events.c.time]) \
		.where(events.c.time > sqlalchemy.func.current_timestamp() - datetime.timedelta(days=2)) \
		.where(events.c.event.in_({'twitch-subscription', 'twitch-resubscription', 'twitch-message', 'twitch-cheer', 'patreon-pledge'})) \
		.order_by(events.c.time.desc())
	with server.db.engine.begin() as conn:
		for id, event, data, time, duration in conn.execute(query):
			data['time'] = time
			recent_events.append({
				'id': id,
				'event': event,
				'data': data,
				'duration': common.time.nice_duration(duration, 2)
			})
		last_event_id = conn.execute(sqlalchemy.select([sqlalchemy.func.max(events.c.id)])).first()
		last_event_id = last_event_id[0] if last_event_id is not None else 0
	return last_event_id, recent_events

def get_milestones():
	now = datetime.datetime.now(config['timezone'])
	for name, dt in MILESTONES:
		months = (now.year - dt.year) * 12 + now.month - dt.month
		if (now.day, now.hour, now.minute, now.second) > (dt.day, dt.hour, dt.minute, dt.second):
			months += 1
		yield name, dt.strftime("%Y-%m-%d"), months

@server.app.route('/notifications')
@login.with_session
def notifications(session):
	last_event_id, events = get_events()

	if server.app.debug:
		eventserver_root = "http://localhost:8080"
	else:
		eventserver_root = ""

	patreon_users = server.db.metadata.tables['patreon_users']
	users = server.db.metadata.tables['users']
	with server.db.engine.begin() as conn:
		name = conn.execute(sqlalchemy.select([patreon_users.c.full_name])
			.select_from(users.join(patreon_users))
			.where(users.c.name == config['channel'])
		).first()
	if name:
		name = name[0]

	return flask.render_template('notifications.html', events=events, last_event_id=last_event_id, eventserver_root=eventserver_root, session=session, patreon_creator_name=name, milestones=get_milestones())
