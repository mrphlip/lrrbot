import flask
from www import login
import common.rpc
import html
from collections import OrderedDict

blueprint = flask.Blueprint('help', __name__)

SECTIONS = OrderedDict((
	("info", "Stream information"),
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

@blueprint.route('/help')
@login.with_session
async def help(session):
	commandlist = sorted(map(command_format, await common.rpc.bot.get_commands()), key=lambda c: c["raw-aliases"])
	commands = {}
	for command in commandlist:
		section = command['section']
		if section not in SECTIONS:
			section = DEFAULT_SECTION
		commands.setdefault(section, {'list': []})['list'].append(command)
	for section in commands:
		commands[section]['mod-only'] = all(command['mod-only'] for command in commands[section]['list'])
	return flask.render_template('help.html', commands=commands, sections=SECTIONS, session=session)
