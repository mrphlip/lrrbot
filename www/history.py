import difflib

import flask
import flask.json

import common.postgres
from common import utils
from www import server
from www import login

from psycopg2.extras import Json

@server.app.route('/history')
@login.require_mod
@common.postgres.with_postgres
def history(conn, cur, session):
	page = flask.request.values.get('page', 'all')
	assert page in ('responses', 'explanations', 'spam', 'link_spam', 'all')
	if page == 'all':
		cur.execute("""
			SELECT historykey, section, changetime, changeuser, LENGTH(jsondata :: text)
			FROM history
			ORDER BY changetime
		""", ())
	else:
		cur.execute("""
			SELECT historykey, section, changetime, changeuser, LENGTH(jsondata :: text)
			FROM history
			WHERE section = %s
			ORDER BY changetime
		""", (page,))
	data = [dict(zip(('key', 'section', 'time', 'user', 'datalen'), row)) for row in cur.fetchall()]
	lastlen = {}
	lastkey = {}
	for i in data:
		i['lengthdiff'] = i['datalen'] - lastlen.get(i['section'], 0)
		lastlen[i['section']] = i['datalen']
		if i['user'] is None:
			i['user'] = "unknown"
		i['lastkey'], lastkey[i['section']] = lastkey.get(i['section']), i['key']
	data.reverse()
	return flask.render_template("historylist.html", page=page, data=data, session=session)

@server.app.route('/history/<int:historykey>')
@login.require_mod
@common.postgres.with_postgres
def history_show(conn, cur, session, historykey):
	cur.execute("""
		SELECT section, changetime, changeuser, jsondata
		FROM history
		WHERE historykey = %s
	""", (historykey,))
	section, time, user, data = cur.fetchone()
	assert cur.fetchone() is None
	if section in ('responses', 'explanations'):
		for row in data.values():
			if not isinstance(row['response'], (tuple, list)):
				row['response'] = [row['response']]
			row['response'] = [{"text": i, "mode": "both"} for i in row['response']]
			row['access'] = {"from": row['access'], "to": row['access']}
			row['mode'] = "both nochange"
		data = list(data.items())
		data.sort(key=lambda a:a[0].lower())
	elif section in ('spam', 'link_spam'):
		for row in data:
			row['mode'] = "both nochange"
	headdata = build_headdata(cur, historykey, historykey, section, user, time)
	return flask.render_template("historyshow.html", data=data, headdata=headdata, session=session)

@server.app.route('/history/<int:fromkey>/<int:tokey>')
@login.require_mod
@common.postgres.with_postgres
def history_diff(conn, cur, session, fromkey, tokey):
	cur.execute("""
		SELECT section, changetime, changeuser, jsondata
		FROM history
		WHERE historykey = %s
	""", (fromkey,))
	fromsection, fromtime, fromuser, fromdata = cur.fetchone()
	assert cur.fetchone() is None
	cur.execute("""
		SELECT section, changetime, changeuser, jsondata
		FROM history
		WHERE historykey = %s
	""", (tokey,))
	tosection, totime, touser, todata = cur.fetchone()
	assert cur.fetchone() is None
	assert fromsection == tosection

	if tosection in ('responses', 'explanations'):
		data = {}
		keys = set(fromdata.keys()) | set(todata.keys())
		for key in keys:
			fromrow = fromdata.get(key)
			torow = todata.get(key)
			row = {}
			if fromrow is None:
				if not isinstance(torow['response'], (tuple, list)):
					row['response'] = [torow['response']]
				else:
					row['response'] = torow['response']
				row['response'] = [{"text": i, "mode": "to"} for i in row['response']]
				row['access'] = {"from": torow['access'], "to": torow['access']}
				row['mode'] = "to"
			elif torow is None:
				if not isinstance(fromrow['response'], (tuple, list)):
					row['response'] = [fromrow['response']]
				else:
					row['response'] = fromrow['response']
				row['response'] = [{"text": i, "mode": "from"} for i in row['response']]
				row['access'] = {"from": fromrow['access'], "to": fromrow['access']}
				row['mode'] = "from"
			else:
				if not isinstance(fromrow['response'], (tuple, list)):
					fromrow['response'] = [fromrow['response']]
				if not isinstance(torow['response'], (tuple, list)):
					torow['response'] = [torow['response']]
				row['response'] = []
				differ = difflib.SequenceMatcher(a=fromrow['response'], b=torow['response'])
				for op, i1, j1, i2, j2 in differ.get_opcodes():
					if op == "equal":
						for i in range(i1, j1):
							row['response'].append({"text": fromrow['response'][i], "mode": "both"})
					else:
						for i in range(i1, j1):
							row['response'].append({"text": fromrow['response'][i], "mode": "from"})
						for i in range(i2, j2):
							row['response'].append({"text": torow['response'][i], "mode": "to"})
				row['access'] = {"from": fromrow['access'], "to": torow['access']}
				if all(i['mode'] == "both" for i in row['response']) and row['access']['from'] == row['access']['to']:
					row['mode'] = "both nochange"
				else:
					row['mode'] = "both"
			data[key] = row
		data = list(data.items())
		data.sort(key=lambda a:a[0].lower())
	elif tosection in ('spam', 'link_spam'):
		fromdata = [(i['re'], i['message']) for i in fromdata]
		todata = [(i['re'], i['message']) for i in todata]
		data = []
		differ = difflib.SequenceMatcher(a=fromdata, b=todata)
		for op, i1, j1, i2, j2 in differ.get_opcodes():
			if op == "equal":
				for i in range(i1, j1):
					data.append({'re': fromdata[i][0], 'message': fromdata[i][1], 'mode': 'both nochange'})
			else:
				for i in range(i1, j1):
					data.append({'re': fromdata[i][0], 'message': fromdata[i][1], 'mode': 'from'})
				for i in range(i2, j2):
					data.append({'re': todata[i][0], 'message': todata[i][1], 'mode': 'to'})
	headdata = build_headdata(cur, fromkey, tokey, tosection, touser, totime)
	return flask.render_template("historyshow.html", data=data, headdata=headdata, session=session)

def build_headdata(cur, fromkey, tokey, section, user, time):
	cur.execute("""
		SELECT MAX(historykey)
		FROM history
		WHERE historykey < %s AND section = %s
	""", (fromkey, section))
	prevkey = cur.fetchone()
	if prevkey is not None:
		prevkey = prevkey[0]
		assert cur.fetchone() is None

	cur.execute("""
		SELECT MIN(historykey)
		FROM history
		WHERE historykey > %s AND section = %s
	""", (tokey, section))
	nextkey = cur.fetchone()
	if nextkey is not None:
		nextkey = nextkey[0]
		assert cur.fetchone() is None

	return {
		"page": section,
		"user": user,
		"time": time,
		"fromkey": fromkey,
		"tokey": tokey,
		"prevkey": prevkey,
		"nextkey": nextkey,
		"isdiff": fromkey != tokey,
	}

@common.postgres.with_postgres
def store(conn, cur, section, user, jsondata):
	cur.execute("""
		INSERT INTO history(section, changetime, changeuser, jsondata)
		VALUES (%s, CURRENT_TIMESTAMP, %s, %s)
	""", (section, user, Json(jsondata)))
