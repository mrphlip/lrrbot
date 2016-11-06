import time
import json
import random
import html

import common.http
import common.time
import lrrbot.decorators
from common import space
from common import utils
from lrrbot.main import bot

DEFAULT_TIMEOUT = 180

def strawpoll_format(data):
	i, (name, count) = data
	return "%s: %s (%d vote%s)" % (i+1, html.unescape(name), count, '' if count == 1 else 's')

def check_polls(lrrbot, conn):
	now = time.time()
	for end, title, poll_id, respond_to in lrrbot.polls:
		if end < now:
			url = "https://www.strawpoll.me/api/v2/polls/%s" % poll_id
			data = json.loads(common.http.request(url))
			options = sorted(zip(data["options"], data["votes"]), key=lambda e: (e[1], random.random()), reverse=True)
			options = "; ".join(map(strawpoll_format, enumerate(options)))
			response = "Poll complete: %s: %s" % (html.unescape(data["title"]), options)
			response = utils.shorten(response, 450)
			conn.privmsg(respond_to, response)
	lrrbot.polls = list(filter(lambda e: e[0] >= now, lrrbot.polls))

@bot.command("polls")
@lrrbot.decorators.throttle()
def polls(lrrbot, conn, event, respond_to):
	"""
	Command: !polls
	Section: misc

	List all currently active polls.
	"""
	if lrrbot.polls == []:
		return conn.privmsg(respond_to, "No active polls.")
	now = time.time()
	messages = []
	for end, title, poll_id, respond_to in lrrbot.polls:
		messages += ["%s (https://www.strawpoll.me/%s%s): %s from now" % (title, poll_id, space.SPACE, common.time.nice_duration(end - now, 1))]
	conn.privmsg(respond_to, utils.shorten("Active polls: "+"; ".join(messages), 450))

@bot.command("(multi)?poll (?:(\d+) )?(?:(?:https?://)?(?:www\.)?strawpoll\.me/([^/]+)(?:/r?)?|(?:([^:]+) ?: ?)?(.*))")
@lrrbot.decorators.mod_only
def new_poll(lrrbot, conn, event, respond_to, multi, timeout, poll_id, title, options):
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
		response = common.http.request("https://www.strawpoll.me/api/v2/polls", data, "POST", headers = {"Content-Type": "application/json"})
		poll_id = json.loads(response)["id"]
	if timeout is not None:
		timeout = int(timeout)
	else:
		timeout = DEFAULT_TIMEOUT
	end = time.time() + int(timeout)
	lrrbot.polls += [(end, title, poll_id, respond_to)]
	conn.privmsg(respond_to, "New poll: %s (https://www.strawpoll.me/%s%s): %s from now" % (title, poll_id, space.SPACE, common.time.nice_duration(timeout, 1)))

@bot.command("pollsclear")
@lrrbot.decorators.mod_only
def clear_polls(lrrbot, conn, event, respond_to):
	"""
	Command: !pollsclear
	Section: misc

	Stop tracking all active polls. The poll will still exist on strawpoll, but the bot
	will stop watching it for results.
	"""
	lrrbot.polls = []
	conn.privmsg(respond_to, "No active polls.")
