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
		autostatus = flask.request.values['autostatus']
		if autostatus not in ('0', '1'):
			raise ValueError('autostatus')
		new_autostatus = bool(int(autostatus))
	else:
		new_autostatus = session['user']['autostatus']

	users = server.db.metadata.tables["users"]
	with server.db.engine.begin() as conn:
		conn.execute(users.update()
			           .where(users.c.id == session['user']['id']),
			           autostatus=new_autostatus)

	# also update the session object for this call
	session['user']['autostatus'] = new_autostatus

	return flask.render_template('prefs.html', session=session, saved=True)
