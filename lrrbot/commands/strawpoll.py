import time
import json
import random
import html
import textwrap
import asyncio
import datetime

import common.http
import common.time
import common.rpc
import lrrbot.decorators
from common import space, utils
from common.config import config
from lrrbot.main import bot

DEFAULT_TIMEOUT = 180

def strawpoll_format(data):
	i, (name, count) = data
	return "%s: %s (%d vote%s)" % (i+1, html.unescape(name), count, '' if count == 1 else 's')

def check_polls(lrrbot, conn):
	now = time.time()
	for end, title, poll_id, respond_to, tag in lrrbot.polls:
		if end < now:
			asyncio.ensure_future(report_poll(conn, poll_id, respond_to, tag))
	lrrbot.polls = list(filter(lambda e: e[0] >= now, lrrbot.polls))

@utils.swallow_errors
async def report_poll(conn, poll_id, respond_to, tag):
	url = "https://www.strawpoll.me/api/v2/polls/%s" % poll_id
	data = json.loads(await common.http.request_coro(url))
	options = sorted(zip(data["options"], data["votes"]), key=lambda e: (e[1], random.random()), reverse=True)
	options = "; ".join(map(strawpoll_format, enumerate(options)))
	response = "Poll complete: %s: %s" % (html.unescape(data["title"]), options)
	response = utils.trim_length(response)
	conn.privmsg(respond_to, response)

	if tag is not None:
		data['tag'] = tag
	await common.rpc.eventserver.event('strawpoll-complete', data)

def get_polls_data(lrrbot):
	res = []
	for end, title, poll_id, respond_to, tag in lrrbot.polls:
		data = {'id': poll_id, 'title': title}
		if tag is not None:
			data['tag'] = tag
		res.append(data)
	return res

@bot.command("polls")
@lrrbot.decorators.throttle()
def polls(lrrbot, conn, event, respond_to):
	"""
	Command: !polls
	Section: misc

	List all currently active polls.
	"""
	if not lrrbot.polls:
		return conn.privmsg(respond_to, "No active polls.")
	now = time.time()
	messages = []
	for end, title, poll_id, respond_to, tag in lrrbot.polls:
		messages += ["%s (https://www.strawpoll.me/%s%s): %s from now" % (title, poll_id, space.SPACE, common.time.nice_duration(end - now, 1))]
	conn.privmsg(respond_to, utils.trim_length("Active polls: "+"; ".join(messages)))

@bot.command("(multi)?poll (?:(\d+) )?(?:(?:https?://)?(?:www\.)?strawpoll\.me/([^/]+)(?:/r?)?|(?:([^:]+) ?: ?)?(.*))")
@lrrbot.decorators.mod_only
async def new_poll(lrrbot, conn, event, respond_to, multi, timeout, poll_id, title, options, tag=None):
	"""
	Command: !poll N https://www.strawpoll.me/ID
	Command: !poll N TITLE: OPTION1; OPTION2
	Command: !multipoll N TITLE: OPTION1; OPTION2
	Section: misc

	Start a new Strawpoll poll. Post results in N seconds. Multiple polls can be active at the
	same time.
	"""
	if poll_id is not None:
		url = "https://www.strawpoll.me/api/v2/polls/%s" % poll_id
		data = json.loads(common.http.request(url))
		title = html.unescape(data["title"])
	else:
		if title is None:
			title = "LoadingReadyLive poll"
		if ';' in options:
			options = [option.strip() for option in options.split(';')]
		elif ',' in options:
			options = [option.strip() for option in options.split(',')]
		else:
			options = options.split()
		data = json.dumps({"options": options, "title": title, "multi": multi is not None})
		data = json.loads(common.http.request(
			"https://www.strawpoll.me/api/v2/polls", data, "POST", headers={"Content-Type": "application/json"}))
		poll_id = data["id"]

	if timeout is not None:
		timeout = int(timeout)
	else:
		timeout = DEFAULT_TIMEOUT
	end = time.time() + int(timeout)
	# NB: need to assign to lrrbot.polls, rather than using lrrbot.polls.append,
	# so that the state change gets saved properly
	lrrbot.polls = lrrbot.polls + [(end, title, poll_id, respond_to, tag)]
	conn.privmsg(respond_to, "New poll: %s (https://www.strawpoll.me/%s%s): %s from now" % (title, poll_id, space.SPACE, common.time.nice_duration(timeout, 1)))

	if tag is not None:
		data['tag'] = tag
	await common.rpc.eventserver.event('strawpoll-add', data)

@bot.command("pollsclear")
@lrrbot.decorators.mod_only
async def clear_polls(lrrbot, conn, event, respond_to):
	"""
	Command: !pollsclear
	Section: misc

	Stop tracking all active polls. The poll will still exist on strawpoll, but the bot
	will stop watching it for results.
	"""
	lrrbot.polls = []
	await common.rpc.eventserver.event('strawpoll-clear', {})
	conn.privmsg(respond_to, "No active polls.")

@bot.command("nowkiss")
@lrrbot.decorators.mod_only
async def nowkiss_poll(lrrbot, conn, event, respond_to):
	"""
	Command: !nowkiss
	Section: misc

	Start a new Strawpoll poll for the Now Kiss swipe left/right vote.
	"""
	game = lrrbot.get_game_name()
	now = datetime.datetime.now(config['timezone'])
	if game and game != 'Games + Demos':
		prompt = "Keep playing {}? [{:%Y-%m-%d}]".format(game, now)
	else:
		prompt = "Keep playing? [{:%Y-%m-%d}]".format(now)
	await new_poll(
		lrrbot, conn, event, respond_to,
		None, '300', None, prompt, 'Swipe Right (keep playing next week);Swipe Left (new game!)',
		tag="nowkiss")
