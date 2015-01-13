import flask
from www import server
from www import login
from www import botinteract
import html

def command_format(cmd):
	cmd["aliases"] = "<code>" + "</code> or <code>".join(map(html.escape, sorted(cmd["aliases"]))) + "</code>"
	cmd["description"] = cmd["description"].split("\n\n")
	return cmd

@server.app.route('/help')
@login.with_session
def help(session):
	commands = sorted(map(command_format, botinteract.get_commands()), key=lambda c: c["aliases"])
	return flask.render_template('help.html', commands=commands, session=session)
