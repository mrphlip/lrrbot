import flask
from www import server
from www import login
from www import botinteract
import html
from collections import OrderedDict

SECTIONS = OrderedDict((
	("info", "Stream information"),
	("stats", "Stats tracking"),
	("quotes", "Quotes"),
	("text", "Simple text responses"),
	("misc", "Miscellaneous"),
))
DEFAULT_SECTION = "misc"

def command_format(cmd):
	cmd['raw-aliases'] = cmd["aliases"]
	cmd["aliases"] = "<code>" + "</code> or <code>".join(map(html.escape, cmd["aliases"])) + "</code>"
	cmd["description"] = cmd["description"].split("\n\n")
	return cmd

@server.app.route('/help')
@login.with_session
def help(session):
	commandlist = sorted(map(command_format, botinteract.get_commands()), key=lambda c: c["raw-aliases"])
	commands = {}
	for command in commandlist:
		section = command['section']
		if section not in SECTIONS:
			section = DEFAULT_SECTION
		commands.setdefault(section, {'list': []})['list'].append(command)
	for section in commands:
		commands[section]['mod-only'] = all(command['mod-only'] for command in commands[section]['list'])
	return flask.render_template('help.html', commands=commands, sections=SECTIONS, session=session)
