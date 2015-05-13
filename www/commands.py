import flask
import flask.json
from www import server
from www import login
from www import botinteract
from www import history
from common import utils

@server.app.route('/commands')
@login.require_mod
@utils.with_postgres
def commands(conn, cur, session):
	mode = flask.request.values.get('mode', 'responses')
	assert(mode in ('responses', 'explanations'))

	cur.execute("""
		SELECT jsondata
		FROM history
		WHERE
			historykey = (
				SELECT MAX(historykey)
				FROM history
				WHERE
					section = %s
			)
	""", (mode,))
	data, = cur.fetchone()

	# Prepare the data, and group equivalent commands together
	data_reverse = {}
	for command, response_data in data.items():
		if isinstance(response_data['response'], list):
			response_data['response'] = tuple(response_data['response'])
		elif not isinstance(response_data['response'], tuple):
			response_data['response'] = (response_data['response'],)
		response_data = (response_data['response'], response_data['access'])
		data_reverse.setdefault(response_data, []).append(command)
	# Sort some things
	for commands in data_reverse.values():
		commands.sort()
	data = [(commands, response[0], response[1]) for response, commands in data_reverse.items()]
	data.sort()

	return flask.render_template("commands.html", commands=data, len=len, mode=mode, session=session)

@server.app.route('/commands/submit', methods=['POST'])
@login.require_mod
def commands_submit(session):
	mode = flask.request.values.get('mode', 'responses')
	assert(mode in ('responses', 'explanations'))
	data = flask.json.loads(flask.request.values['data'])
	# Server-side sanity checking
	for command, response_data in data.items():
		if not isinstance(command, str):
			raise ValueError("Key is not a string")
		if command == '':
			raise ValueError("Command is blank")
		if not isinstance(response_data, dict):
			raise ValueError("Response data is not a dict")
		if set(response_data.keys()) != set(('response', 'access')):
			raise ValueError("Incorrect keys for response_data")
		if not isinstance(response_data['response'], (tuple, list)):
			response_data['response'] = [response_data['response']]
		for response in response_data['response']:
			if not isinstance(response, str):
				raise ValueError("Value is not a string or list of strings")
			if response == '':
				raise ValueError("Response is blank")
			if len(response) > 450:
				raise ValueError("Response is too long")
		if len(response_data['response']) == 1:
			response_data['response'] = response_data['response'][0]
		if response_data['access'] not in ('any', 'sub', 'mod'):
			raise ValueError("Invalid access level")
	data = {command.lower(): response_data for command, response_data in data.items()}
	history.store(mode, session['user'], data)
	if mode == 'responses':
		botinteract.reload_commands()
	return flask.json.jsonify(success='OK', csrf_token=server.app.csrf_token())
