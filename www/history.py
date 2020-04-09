import datetime
import difflib

import flask
import flask.json
import sqlalchemy
import pytz

from www import server
from www import login

@server.app.route('/history')
@login.require_mod
def history(session):
	page = flask.request.values.get('page', 'all')
	assert page in ('responses', 'explanations', 'spam', 'link_spam', 'all')
	history = server.db.metadata.tables["history"]
	users = server.db.metadata.tables["users"]
	query = sqlalchemy.select([
			history.c.id, history.c.section, history.c.changetime, users.c.display_name,
			sqlalchemy.func.length(history.c.jsondata.cast(sqlalchemy.Text))
		]).select_from(history.join(users, history.c.changeuser == users.c.id, isouter=True)) \
		.order_by(history.c.changetime)
	if page != 'all':
		query = query.where(history.c.section == page)
	with server.db.engine.begin() as conn:
		data = [
			{'key': key, 'section': section, 'time': time, 'user': user, 'datalen': datalen}
			for key, section, time, user, datalen in conn.execute(query).fetchall()
		]
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
def history_show(session, historykey):
	history = server.db.metadata.tables["history"]
	users = server.db.metadata.tables["users"]
	with server.db.engine.begin() as conn:
		section, time, user, data = conn.execute(sqlalchemy.select([
				history.c.section, history.c.changetime, users.c.display_name, history.c.jsondata
			]).select_from(history.join(users, history.c.changeuser == users.c.id, isouter=True))
			.where(history.c.id == historykey)).first()
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
	headdata = build_headdata(historykey, historykey, section, user, time)
	return flask.render_template("historyshow.html", data=data, headdata=headdata, session=session)

@server.app.route('/history/<int:fromkey>/<int:tokey>')
@login.require_mod
def history_diff(session, fromkey, tokey):
	history = server.db.metadata.tables["history"]
	users = server.db.metadata.tables["users"]
	with server.db.engine.begin() as conn:
		fromsection, fromdata = conn.execute(sqlalchemy.select([
				history.c.section, history.c.jsondata
			]).where(history.c.id == fromkey)).first()

		tosection, totime, touser, todata = conn.execute(sqlalchemy.select([
				history.c.section, history.c.changetime, users.c.display_name, history.c.jsondata
			]).select_from(history.join(users, history.c.changeuser == users.c.id, isouter=True))
			.where(history.c.id == tokey)).first()
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
	headdata = build_headdata(fromkey, tokey, tosection, touser, totime)
	return flask.render_template("historyshow.html", data=data, headdata=headdata, session=session)

def build_headdata(fromkey, tokey, section, user, time):
	history = server.db.metadata.tables["history"]
	with server.db.engine.begin() as conn:
		prevkey = conn.execute(sqlalchemy.select([sqlalchemy.func.max(history.c.id)])
			.where((history.c.id < fromkey) & (history.c.section == section))).first()
		nextkey = conn.execute(sqlalchemy.select([sqlalchemy.func.min(history.c.id)])
			.where((history.c.id > tokey) & (history.c.section == section))).first()

	if prevkey is not None:
		prevkey = prevkey[0]

	if nextkey is not None:
		nextkey = nextkey[0]

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

def store(section, user, jsondata):
	with server.db.engine.begin() as conn:
		conn.execute(server.db.metadata.tables["history"].insert(),
			section=section,
			changetime=datetime.datetime.now(tz=pytz.utc),
			changeuser=user,
			jsondata=jsondata,
		)
