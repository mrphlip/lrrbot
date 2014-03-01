import flask
import server

@server.app.route('/')
def index():
	return flask.render_template('index.html')
