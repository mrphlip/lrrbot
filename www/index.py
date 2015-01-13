import flask
from www import server
from www import login

@server.app.route('/')
@login.with_session
def index(session):
	return flask.render_template('index.html', session=session)

@server.app.route('/favicon.ico')
def favicon():
	return server.app.send_static_file("favicon.ico")
