#!/usr/bin/env python
import flask
import flask.json
import server
import time
import utils
import secrets

def get_notifications(cur, after=None):
	if after is None:
		cur.execute("""
			SELECT NOTIFICATIONKEY, MESSAGE, CHANNEL, SUBUSER, USERAVATAR, UNIX_TIMESTAMP(EVENTTIME)
			FROM NOTIFICATION
			WHERE EVENTTIME >= (UTC_TIMESTAMP() - INTERVAL 2 DAY)
			ORDER BY NOTIFICATIONKEY
		""")
	else:
		cur.execute("""
			SELECT NOTIFICATIONKEY, MESSAGE, CHANNEL, SUBUSER, USERAVATAR, UNIX_TIMESTAMP(EVENTTIME)
			FROM NOTIFICATION
			WHERE EVENTTIME >= (UTC_TIMESTAMP() - INTERVAL 2 DAY)
			AND NOTIFICATIONKEY > ?
			ORDER BY NOTIFICATIONKEY
		""", (after,))
	return [dict(zip(('key', 'message', 'channel', 'user', 'avatar', 'time'), row)) for row in cur.fetchall()]

@server.app.route('/notifications')
@utils.with_mysql
def main_page(conn, cur):
	row_data = get_notifications(cur)
	for row in row_data:
		if row['time'] is None:
			row['duration'] = None
		else:
			row['duration'] = utils.nice_duration(time.time() - row['time'])
	row_data.reverse()

	if row_data:
		maxkey = row_data[0]['key']
	else:
		conn.execute("SELECT MAX(NOTIFICATIONKEY) FROM NOTIFICATION")
		maxkey = conn.fetchone()[0]
		if maxkey is None:
			maxkey = -1

	return flask.render_template('notifications.html', row_data=row_data, maxkey=maxkey)

@server.app.route('/notifications/updates', methods=['GET', 'POST'])
@utils.with_mysql
def updates(conn, cur):
	return flask.json.jsonify(notifications=get_notifications(cur, int(flask.request.values['after'])))

event_server = utils.SSEServer()
server.app.add_url_rule('/notifications/events', view_func=event_server.subscribe)

@server.app.route('/notifications/newmessage', methods=['POST'])
@utils.with_mysql
def new_message(conn, cur):
	if flask.request.values['apipass'] != secrets.apipass:
		return flask.json.jsonify(error='apipass')
	data = {
		'message': flask.request.values['message'],
		'channel': flask.request.values.get('channel'),
		'user': flask.request.values.get('subuser'),
		'avatar': flask.request.values.get('avatar'),
		'time': float(flask.request.values['eventtime']) if 'eventtime' in flask.request.values else None,
	}
	cur.execute("""
		INSERT INTO NOTIFICATION(MESSAGE, CHANNEL, SUBUSER, USERAVATAR, EVENTTIME)
		VALUES (?, ?, ?, ?, FROM_UNIXTIME(?))
		""", (
		data['message'],
		data['channel'],
		data['user'],
		data['avatar'],
		data['time'],
	))
	event_server.publish(data, 'newmessage')
	return flask.json.jsonify(success='OK')
