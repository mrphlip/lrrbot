import flask
import server
import login
import botinteract
import cgi

def command_format(cmd):
	cmd["aliases"] = "<code>" + "</code> or <code>".join(map(cgi.escape, sorted(cmd["aliases"]))) + "</code>"
	cmd["description"] = cmd["description"].split("\n\n")
	return cmd

@server.app.route('/')
@login.with_session
def index(session):
	commands = sorted(map(command_format, botinteract.get_commands()), key=lambda c: c["aliases"])
	return flask.render_template('index.html', commands=commands, session=session)

@server.app.route('/favicon.ico')
def favicon():
	return server.app.send_static_file("favicon.ico")
