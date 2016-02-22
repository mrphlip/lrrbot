import flask
import flask.json

import common.url
from www import server
from www import login
from www import botinteract
from www import history
from common import utils
import re
import datetime
import pytz
import asyncio

@server.app.route('/spam')
@login.require_mod
def spam(session):
	link_spam = "link_spam" in flask.request.values
	data = botinteract.get_data('link_spam_rules' if link_spam else 'spam_rules')
	return flask.render_template("spam.html", rules=data, link_spam=link_spam, session=session)

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
	link_spam = "link_spam" in flask.request.values
	data = flask.json.loads(flask.request.values['data'])

	# Validation checks
	error = verify_rules(data)
	if error:
		return flask.json.jsonify(error=error, csrf_token=server.app.csrf_token())

	if link_spam:
		botinteract.modify_link_spam_rules(data)
	else:
		botinteract.modify_spam_rules(data)
	history.store("link_spam" if link_spam else "spam", session['user'], data)
	return flask.json.jsonify(success='OK', csrf_token=server.app.csrf_token())

def do_check(line, rules):
	for rule in rules:
		matches = rule['re'].search(line)
		if matches:
			groups = {str(i+1):v for i,v in enumerate(matches.groups())}
			return rule['message'] % groups
	return None

def do_check_links(message, rules):
	loop = asyncio.get_event_loop()
	re_url = loop.run_until_complete(common.url.url_regex())
	urls = []
	for match in re_url.finditer(message):
		for url in match.groups():
			if url is not None:
				urls.append(url)
				break
	canonical_urls = loop.run_until_complete(asyncio.gather(*map(common.url.canonical_url, urls), loop=loop))
	for url_chain in canonical_urls:
		for url in url_chain:
			for rule in rules:
				match = rule["re"].search(url)
				if match is not None:
					return rule["message"] % {str(i+1): v for i, v in enumerate(match.groups())}

@server.app.route('/spam/redirects')
@login.require_mod
def spam_redirects(session):
	loop = asyncio.get_event_loop()
	redirects = loop.run_until_complete(common.url.canonical_url(flask.request.values["url"].strip()))
	return flask.json.jsonify(redirects=redirects, csrf_token=server.app.csrf_token())

@server.app.route('/spam/test', methods=['POST'])
@login.require_mod
def spam_test(session):
	link_spam = "link_spam" in flask.request.values
	rules = flask.json.loads(flask.request.values['data'])
	message = flask.request.values['message']

	# Validation checks
	error = verify_rules(rules)
	if error:
		return flask.json.jsonify(error=error, csrf_token=server.app.csrf_token())

	for rule in rules:
		rule['re'] = re.compile(rule['re'])

	result = []

	check = do_check_links if link_spam else do_check

	re_twitchchat = re.compile("^\w*:\s*(.*)$")
	re_irc = re.compile("<[^<>]*>\s*(.*)$")
	lines = message.split('\n')
	for line in lines:
		res = check(line, rules)
		if res is None:
			match = re_twitchchat.search(line)
			if match:
				res = check(match.group(1), rules)
		if res is None:
			match = re_irc.search(line)
			if match:
				res = check(match.group(1), rules)
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
		rule['re'] = re.compile(rule['re'])

	starttime = datetime.datetime.now(tz=pytz.utc) - datetime.timedelta(days=14)
	cur.execute("SELECT source, message, time FROM log WHERE time >= %s AND 'cleared' = ANY(specialuser) ORDER BY time ASC", (
		starttime,
	))
	data = [row + (do_check(row[1], rules),) for row in cur]

	return flask.render_template("spam_find.html", data=data, session=session)
