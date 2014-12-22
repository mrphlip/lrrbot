from lrrbot import bot
import utils
import time
import json

def strawpoll_format(data):
    i, (name, count) = data
    return "%s: %s (%d vote%s)" % (i+1, name, count, '' if count == 1 else 's')

def check_polls(lrrbot, conn, event, respond_to):
	now = time.time()
	for end, title, poll_id in lrrbot.polls:
		if end < now:
			url = "http://strawpoll.me/api/v2/polls/%s" % poll_id
			data = json.loads(utils.http_request(url))
			options = sorted(zip(data["options"], data["votes"]), key=lambda e: e[1], reverse=True)
			options = "; ".join(map(strawpoll_format, enumerate(options)))
			conn.privmsg(respond_to, "Poll complete: %s: %s" % (data["title"], options))
	lrrbot.polls = list(filter(lambda e: e[0] >= now, lrrbot.polls))
bot.check_polls = check_polls

@bot.command("polls")
@utils.throttle()
def polls(lrrbot, conn, event, respond_to):
	"""
	Command: !polls

	List all currently active polls.
	"""
	if lrrbot.polls == []:
		return conn.privmsg(respond_to, "No active polls.")
	now = time.time()
	messages = []
	for end, title, poll_id in lrrbot.polls:
		messages += ["%s (http://strawpoll.me/%s\u200B): %s from now" % (title, poll_id, utils.nice_duration(end - now, 1))]
	conn.privmsg(respond_to, utils.shorten("Active polls: "+"; ".join(messages), 450))

@bot.command("(multi)?poll (\d+) (?:(?:(?:http://)?(?:www\.)?strawpoll\.me/([^/]+)(?:/(?:r)?)?)|(?:([^:]+): ?([^;]+(?:; ?[^;]+)*);?))")
@utils.mod_only
def new_poll(lrrbot, conn, event, respond_to, multi, timeout, poll_id, title, options):
	"""
	Command: !poll N http://strawpoll.me/ID
	Command: !poll N TITLE: OPTION1; OPTION2
	Command: !multipoll N TITLE: OPTION1; OPTION2

	Start a new Strawpoll poll. Post results in N seconds. Multiple polls can be active at the
	same time.
	"""
	timeout = int(timeout)
	end = time.time() + int(timeout)
	if poll_id is not None:
		url = "http://strawpoll.me/api/v2/polls/%s" % poll_id
		data = json.loads(utils.http_request(url))
		title = data["title"]
	else:
		options = [option.strip() for option in options.split(';')]
		data = json.dumps({"options": options, "title": title})
		response = utils.http_request("http://strawpoll.me/api/v2/polls", data, "POST", headers = {"Content-Type": "application/json"})
		poll_id = json.loads(response)["id"]
	lrrbot.polls += [(end, title, poll_id)]
	conn.privmsg(respond_to, "New poll: %s (http://strawpoll.me/%s\u200B): %s from now" % (title, poll_id, utils.nice_duration(timeout, 1)))
