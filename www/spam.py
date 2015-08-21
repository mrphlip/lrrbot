import flask
import flask.json
from www import server
from www import login
from www import botinteract
from www import history
from common import utils
import regex
import datetime
import pytz

@server.app.route('/spam')
@login.require_mod
def spam(session):
	data = botinteract.get_data('spam_rules')
	return flask.render_template("spam.html", rules=data, session=session)

def verify_rules(rules):
	for ix, rule in enumerate(rules):
		# Test the regular expression is valid
		try:
			re_rule = regex.compile(rule['re'])
		except regex.error as ex:
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
		return flask.json.jsonify(error=error, csrf_token=server.app.csrf_token())

	botinteract.modify_spam_rules(data)
	history.store("spam", session['user'], data)
	return flask.json.jsonify(success='OK', csrf_token=server.app.csrf_token())

def do_check(line, rules):
	for rule in rules:
		matches = rule['re'].search(line)
		if matches:
			groups = {str(i+1):v for i,v in enumerate(matches.groups())}
			return rule['message'] % groups
	return None

@server.app.route('/spam/test', methods=['POST'])
@login.require_mod
def spam_test(session):
	rules = flask.json.loads(flask.request.values['data'])
	message = flask.request.values['message']

	# Validation checks
	error = verify_rules(rules)
	if error:
		return flask.json.jsonify(error=error, csrf_token=server.app.csrf_token())

	for rule in rules:
		rule['re'] = regex.compile(rule['re'])

	result = []

	re_twitchchat = re.compile("^\w*:\s*(.*)$")
	re_irc = re.compile("<[^<>]*>\s*(.*)$")
	lines = message.split('\n')
	for line in lines:
		res = do_check(line, rules)
		if res is None:
			match = re_twitchchat.search(line)
			if match:
				res = do_check(match.group(1), rules)
		if res is None:
			match = re_irc.search(line)
			if match:
				res = do_check(match.group(1), rules)
		if res is not None:
			result.append({
				'line': line,
				'spam': True,
				'message': res,
			})
		else:
			result.append({
				'line': line,
				'spam': False,
			})
	return flask.json.jsonify(result=result, csrf_token=server.app.csrf_token())

@server.app.route('/spam/find')
@login.require_mod
@utils.with_postgres
def spam_find(conn, cur, session):
	rules = botinteract.get_data('spam_rules')
	for rule in rules:
		rule['re'] = regex.compile(rule['re'])

	starttime = datetime.datetime.now(tz=pytz.utc) - datetime.timedelta(days=14)
	cur.execute("SELECT source, message, time FROM log WHERE time >= %s AND 'cleared' = ANY(specialuser) ORDER BY time ASC", (
		starttime,
	))
	data = [row + (do_check(row[1], rules),) for row in cur]

	return flask.render_template("spam_find.html", data=data, session=session)
