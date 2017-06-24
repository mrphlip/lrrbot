import flask
from www import server
from www import login

@server.app.route('/prefs')
@login.require_login
def prefs(session):
	return flask.render_template('prefs.html', session=session, saved=False)

@server.app.route('/prefs', methods=["POST"])
@login.require_login
def prefs_save(session):
	if 'autostatus' in flask.request.values:
		session['user']['autostatus'] = bool(int(flask.request.values['autostatus']))
	if 'stream_delay' in flask.request.values:
		session['user']['stream_delay'] = int(flask.request.values['stream_delay'])
		if not -60 <= session['user']['stream_delay'] <= 60:
			raise ValueError("stream_delay")
	if 'chat_timestamps' in flask.request.values:
		session['user']['chat_timestamps'] = int(flask.request.values['chat_timestamps'])
		if session['user']['chat_timestamps'] not in (0, 1, 2, 3):
			raise ValueError("chat_timestamps")
	if 'chat_timestamps_24hr' in flask.request.values:
		session['user']['chat_timestamps_24hr'] = bool(int(flask.request.values['chat_timestamps_24hr']))
	if 'chat_timestamps_secs' in flask.request.values:
		session['user']['chat_timestamps_secs'] = bool(int(flask.request.values['chat_timestamps_secs']))

	users = server.db.metadata.tables["users"]
	with server.db.engine.begin() as conn:
		conn.execute(users.update()
			           .where(users.c.id == session['user']['id']),
			           autostatus=session['user']['autostatus'],
			           stream_delay=session['user']['stream_delay'],
			           chat_timestamps=session['user']['chat_timestamps'],
			           chat_timestamps_24hr=session['user']['chat_timestamps_24hr'],
			           chat_timestamps_secs=session['user']['chat_timestamps_secs'])

	return flask.render_template('prefs.html', session=session, saved=True)
