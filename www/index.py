import flask
from www import server
from www import login

blueprint = flask.Blueprint('index', __name__)

@blueprint.route('/')
@login.with_session
def index(session):
	return flask.render_template('index.html', session=session)

@blueprint.route('/favicon.ico')
def favicon():
	return server.app.send_static_file("favicon.ico")
