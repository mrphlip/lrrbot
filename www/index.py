import flask
import server
import login

@server.app.route('/')
@login.with_session
def index(session):
	return flask.render_template('index.html', session=session)
