#!/usr/bin/env python
import flask
import flask.json
import server
import login
import botinteract

@server.app.route('/commands')
@login.require_mod
def commands(session):
	mode = flask.request.values.get('mode', 'responses')
	assert(mode in ('responses', 'explanations'))

	data = botinteract.get_data(mode)

	# Prepare the data, and group equivalent commands together
	data_reverse = {}
	for command, response in data.items():
		if isinstance(response, list):
			response = tuple(response)
		elif not isinstance(response, tuple):
			response = (response,)
		data_reverse.setdefault(response, []).append(command)
	# Sort some things
	for commands in data_reverse.values():
		commands.sort()
	data = [(commands, response) for response, commands in data_reverse.items()]
	data.sort()

	return flask.render_template("commands.html", commands=data, len=len, mode=mode, session=session)

@server.app.route('/commands/submit', methods=['POST'])
@login.require_mod
def commands_submit(session):
	mode = flask.request.values.get('mode', 'responses')
	assert(mode in ('responses', 'explanations'))
	data = flask.json.loads(flask.request.values['data'])
	# Server-side sanity checking
	for command, responses in data.items():
		if not isinstance(command, str):
			raise ValueError("Key is not a string")
		if command == '':
			raise ValueError("Command is blank")
		if ' ' in command:
			raise ValueError("Command contains spaces")
		if not isinstance(responses, (tuple, list)):
			reponses = [responses]
		for response in responses:
			if not isinstance(response, str):
				raise ValueError("Value is not a string or list of strings")
			if response == '':
				raise ValueError("Response is blank")
	if mode == 'responses':
		botinteract.modify_commands(data)
	elif mode == 'explanations':
		botinteract.modify_explanations(data)
	return flask.json.jsonify(success='OK')
