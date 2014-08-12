#!/usr/bin/env python
import flask
import flask.json
import server
import login
import botinteract
import history
import re

@server.app.route('/spam')
@login.require_mod
def spam(session):
	data = botinteract.get_data('spam_rules')
	return flask.render_template("spam.html", rules=data, session=session)

def verify_rules(rules):
	for ix, rule in enumerate(rules):
		# Test the regular expression is valid
		try:
			re_rule = re.compile(rule['re'])
		except re.error as ex:
			return {"msg": str(ex), "row": ix, "col": 0}
		# Test the response message uses the right groups
		try:
			rule['message'] % {str(i + 1): "" for i in range(re_rule.groups)}
		except KeyError as ex:
			return {"msg": "No group %s" % ex, "row": ix, "col": 1}
		except TypeError:
			return {"msg": "Must use named placeholders", "row": ix, "col": 1}

@server.app.route('/spam/submit', methods=['POST'])
@login.require_mod
def spam_submit(session):
	data = flask.json.loads(flask.request.values['data'])

	# Validation checks
	error = verify_rules(data)
	if error:
		return flask.json.jsonify(error=error)

	botinteract.modify_spam_rules(data)
	history.store("spam", session['user'], data)
	return flask.json.jsonify(success='OK')

@server.app.route('/spam/test', methods=['POST'])
@login.require_mod
def spam_test(session):
	data = flask.json.loads(flask.request.values['data'])
	message = flask.request.values['message']

	# Validation checks
	error = verify_rules(data)
	if error:
		return flask.json.jsonify(error=error)

	for rule in data:
		rule['re'] = re.compile(rule['re'])

	result = []

	def do_check(s, line):
		for rule in data:
			matches = rule['re'].search(s)
			if matches:
				groups = {str(i+1):v for i,v in enumerate(matches.groups())}
				result.append({
					'line': line,
					'spam': True,
					'message': rule['message'] % groups,
				})
				return True
		return False

	re_twitchchat = re.compile("^\w*:\s*(.*)$")
	re_irc = re.compile("<[^<>]*>\s*(.*)$")
	lines = message.split('\n')
	for line in lines:
		if do_check(line, line):
			continue
		match = re_twitchchat.search(line)
		if match and do_check(match.group(1), line):
			continue
		match = re_irc.search(line)
		if match and do_check(match.group(1), line):
			continue
		result.append({
			'line': line,
			'spam': False,
		})
	return flask.json.jsonify(result=result)
