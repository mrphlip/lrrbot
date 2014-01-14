#!/usr/bin/env python
import sys
import cgi
import cgitb
import MySQLdb as mdb
import time
import json
import pyratemp
import utils
import secrets

# Enable debug errors
# cgitb.enable()

request = cgi.parse()

mode = request.get('mode', ['page'])[0]

with mdb.connect(**secrets.mysqlopts) as conn:
	def get_notifications(after=None):
		if after is None:
			conn.execute("""
				SELECT NOTIFICATIONKEY, MESSAGE, CHANNEL, SUBUSER, USERAVATAR, UNIX_TIMESTAMP(EVENTTIME)
				FROM NOTIFICATION
				WHERE EVENTTIME >= (UTC_TIMESTAMP() - INTERVAL 2 DAY)
				ORDER BY NOTIFICATIONKEY
			""")
		else:
			conn.execute("""
				SELECT NOTIFICATIONKEY, MESSAGE, CHANNEL, SUBUSER, USERAVATAR, UNIX_TIMESTAMP(EVENTTIME)
				FROM NOTIFICATION
				WHERE EVENTTIME >= (UTC_TIMESTAMP() - INTERVAL 2 DAY)
				AND NOTIFICATIONKEY > %s
				ORDER BY NOTIFICATIONKEY
			""", (after,))
		return [dict(zip(('key', 'message', 'channel', 'user', 'avatar', 'time'), row)) for row in conn.fetchall()]

	if mode == 'page':
		print "Content-type: text/html; charset=utf-8"
		print

		row_data = get_notifications()
		for row in row_data:
			if row['time'] is None:
				row['duration'] = None
			else:
				row['duration'] = utils.niceduration(time.time() - row['time'])
		row_data.reverse()

		if row_data:
			maxkey = row_data[0]['key']
		else:
			conn.execute("SELECT MAX(NOTIFICATIONKEY) FROM NOTIFICATION")
			maxkey = conn.fetchone()[0]
			if maxkey is None:
				maxkey = -1

		template = pyratemp.Template(filename="tpl/notifications.html")
		print template(row_data=row_data, maxkey=maxkey).encode("utf-8")
	elif mode == 'update':
		utils.writejson(get_notifications(int(request['after'][0])))
	elif mode == 'newmessage':
		if request['apipass'][0] != secrets.apipass:
			utils.writejson({'error':'apipass'})
			sys.exit()
		conn.execute("""
			INSERT INTO NOTIFICATION(MESSAGE, CHANNEL, SUBUSER, USERAVATAR, EVENTTIME)
			VALUES (%s, %s, %s, %s, FROM_UNIXTIME(%s))
			""", (
			request['message'][0],
			request.get('channel', [None])[0],
			request.get('subuser', [None])[0],
			request.get('avatar', [None])[0],
			request.get('eventtime', [None])[0],
		))
		utils.writejson({'success':'OK'})
