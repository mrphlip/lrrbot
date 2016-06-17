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

def get_notifications(conn, after=None, test=False):
	notification = server.db.metadata.tables["notification"]
	query = sqlalchemy.select([
		notification.c.id, notification.c.message, notification.c.channel,
		notification.c.subuser, notification.c.useravatar, notification.c.eventtime,
		notification.c.monthcount, notification.c.test,
	]).where(notification.c.eventtime >= (sqlalchemy.func.current_timestamp() - datetime.timedelta(days=2)))
	if after is not None:
		query = query.where(notification.c.id > after)
	if not test:
		query = query.where(~notification.c.test)
	query = query.order_by(notification.c.id)
	return [
		{
			'key': key,
			'message': message,
			'channel': channel,
			'user': user,
			'avatar': avatar,
			'time': time,
			'monthcount': monthcount,
			'test': test,
		} for key, message, channel, user, avatar, time, monthcount, test in conn.execute(query)
	]

@server.app.route('/notifications')
@login.with_session
def notifications(session):
	notification = server.db.metadata.tables["notification"]
	with server.db.engine.begin() as conn:
		row_data = get_notifications(conn)
		row_data.reverse()
		if len(row_data) == 0:
			maxkey = conn.execute(sqlalchemy.select([sqlalchemy.func.max(notification.c.id)])).first()
			if maxkey is None:
				maxkey = -1
			else:
				maxkey = maxkey[0]
		else:
			maxkey = row_data[0]['key']

	for row in row_data:
		if row['time'] is None:
			row['duration'] = None
		else:
			row['duration'] = common.time.nice_duration(datetime.datetime.now(row['time'].tzinfo) - row['time'], 2)

	return flask.render_template('notifications.html', row_data=row_data, maxkey=maxkey, session=session)
