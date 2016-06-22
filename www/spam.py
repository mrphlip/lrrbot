import flask
import flask.json

import common.url
import common.rpc
from www import server
from www import login
from www import history
import re
import datetime
import pytz
import asyncio
import sqlalchemy

@server.app.route('/spam')
@login.require_mod
async def spam(session):
	link_spam = "link_spam" in flask.request.values
	data = await common.rpc.bot.get_data('link_spam_rules' if link_spam else 'spam_rules')
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
		# Check the type setting
		if rule['type'] not in ('spam', 'censor'):
			return {"msg": "Incorrect type", "row": ix, "col": 2}

@server.app.route('/spam/submit', methods=['POST'])
@login.require_mod
async def spam_submit(session):
	link_spam = "link_spam" in flask.request.values
	data = flask.json.loads(flask.request.values['data'])

	# Validation checks
	error = verify_rules(data)
	if error:
		return flask.json.jsonify(error=error, csrf_token=server.app.csrf_token())

	if link_spam:
		await common.rpc.bot.link_spam.modify_link_spam_rules(data)
	else:
		await common.rpc.bot.spam.modify_spam_rules(data)
	history.store("link_spam" if link_spam else "spam", session['user']['id'], data)
	return flask.json.jsonify(success='OK', csrf_token=server.app.csrf_token())

def do_check(line, rules):
	for rule in rules:
		matches = rule['re'].search(line)
		if matches:
			groups = {str(i+1):v for i,v in enumerate(matches.groups())}
			return rule['message'] % groups
	return None

async def do_check_links(message, rules):
	re_url = await common.url.url_regex()
	urls = []
	for match in re_url.finditer(message):
		for url in match.groups():
			if url is not None:
				urls.append(url)
				break
	canonical_urls = await asyncio.gather(*map(common.url.canonical_url, urls))
	for url_chain in canonical_urls:
		for url in url_chain:
			for rule in rules:
				match = rule["re"].search(url)
				if match is not None:
					return rule["message"] % {str(i+1): v for i, v in enumerate(match.groups())}

@server.app.route('/spam/redirects')
@login.require_mod
async def spam_redirects(session):
	redirects = await common.url.canonical_url(flask.request.values["url"].strip())
	return flask.json.jsonify(redirects=redirects, csrf_token=server.app.csrf_token())

@server.app.route('/spam/test', methods=['POST'])
@login.require_mod
async def spam_test(session):
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

	check = do_check_links if link_spam else asyncio.coroutine(do_check)

	re_twitchchat = re.compile("^\w*:\s*(.*)$")
	re_irc = re.compile("<[^<>]*>\s*(.*)$")
	lines = message.split('\n')
	for line in lines:
		res = await check(line, rules)
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
async def spam_find(session):
	rules = await common.rpc.bot.get_data('spam_rules')
	for rule in rules:
		rule['re'] = re.compile(rule['re'])

	starttime = datetime.datetime.now(tz=pytz.utc) - datetime.timedelta(days=14)
	log = server.db.metadata.tables["log"]
	with server.db.engine.begin() as conn:
		res = conn.execute(sqlalchemy.select([log.c.source, log.c.message, log.c.time])
			.where((log.c.time >= starttime) & log.c.specialuser.any('cleared'))
			.order_by(log.c.time.asc()))
		data = [tuple(row) + (do_check(row[1], rules),) for row in res]

	return flask.render_template("spam_find.html", data=data, session=session)
