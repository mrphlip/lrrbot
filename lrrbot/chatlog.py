import queue
import threading
import json
import re
import time
import pytz
import datetime
import logging

import irc.client
from jinja2.utils import Markup, escape, urlize

from common import utils
from common.config import config


__all__ = ["log_chat", "clear_chat_log", "exitthread"]

log = logging.getLogger('chatlog')

CACHE_EXPIRY = 7*24*60*60
PURGE_PERIOD = datetime.timedelta(minutes=15)

queue = queue.Queue()
thread = None

# Chat-log handling functions live in their own thread, so that functions that take
# a long time to run, like downloading the emote list, don't block the bot... but just
# one thread, with a message queue, so that things still happen in the right order.
def createthread():
	global thread
	thread = threading.Thread(target=run_thread, name="chatlog")
	thread.start()

def run_thread():
	while True:
		ev, params = queue.get()
		if ev == "log_chat":
			do_log_chat(*params)
		elif ev == "clear_chat_log":
			do_clear_chat_log(*params)
		elif ev == "rebuild_all":
			do_rebuild_all()
		elif ev == "exit":
			break


def log_chat(event, metadata):
	queue.put(("log_chat", (datetime.datetime.now(pytz.utc), event, metadata)))

def clear_chat_log(nick):
	queue.put(("clear_chat_log", (datetime.datetime.now(pytz.utc), nick)))

def rebuild_all():
	queue.put(("rebuild_all", ()))

def exitthread():
	queue.put(("exit", ()))
	thread.join()


@utils.swallow_errors
@utils.with_postgres
def do_log_chat(conn, cur, time, event, metadata):
	"""
	Add a new message to the chat log.
	"""
	# Don't log server commands like .timeout
	message = event.arguments[0]
	if message[0] in "./" and message[1:4].lower() != "me ":
		return

	source = irc.client.NickMask(event.source).nick
	cur.execute("INSERT INTO log (time, source, target, message, specialuser, usercolor, emoteset, messagehtml) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (
		time,
		source,
		event.target,
		event.arguments[0],
		list(metadata.get('specialuser', [])),
		metadata.get('usercolor'),
		list(metadata.get('emoteset', [])),
		build_message_html(time, source, event.target, event.arguments[0], metadata.get('specialuser', []), metadata.get('usercolor'), metadata.get('emoteset', [])),
	))

@utils.swallow_errors
@utils.with_postgres
def do_clear_chat_log(conn, cur, time, nick):
	"""
	Mark a user's earlier posts as "deleted" in the chat log, for when a user is banned/timed out.
	"""
	cur.execute("SELECT id, time, source, target, message, specialuser, usercolor, emoteset FROM log WHERE source=%s AND time>=%s", (
		nick,
		time - PURGE_PERIOD,
	))
	for i, (key, time, source, target, message, specialuser, usercolor, emoteset) in enumerate(cur):
		specialuser = set(specialuser) if specialuser else set()
		emoteset = set(emoteset) if emoteset else set()

		specialuser.add("cleared")

		cur.execute("UPDATE log SET specialuser=?, messagehtml=%s WHERE id=%s", (
			list(specialuser),
			build_message_html(time, source, target, message, specialuser, usercolor, emoteset),
			key,
		))

@utils.swallow_errors
@utils.with_postgres
def do_rebuild_all(conn, cur):
	"""
	Rebuild all the message HTML blobs in the database.
	"""
	count = None
	cur.execute("SELECT COUNT(*) FROM log")
	for count, in cur:
		pass
	cur.execute("SELECT id, time, source, target, message, specialuser, usercolor, emoteset FROM log")
	for i, (key, time, source, target, message, specialuser, usercolor, emoteset) in enumerate(cur):
		if i % 100 == 0:
			print("\r%d/%d" % (i, count), end='')
		specialuser = set(specialuser) if specialuser else set()
		emoteset = set(emoteset) if emoteset else set()
		cur.execute("UPDATE log SET messagehtml=%s WHERE id=%s", (
			build_message_html(time, source, target, message, specialuser, usercolor, emoteset),
			key,
		))
	print("\r%d/%d" % (count, count))

def format_message(message, emotes):
	ret = ""
	stack = [(message, "")]
	while len(stack) != 0:
		prefix, suffix = stack.pop()
		for emote in emotes:
			parts = emote["regex"].split(prefix, 1)
			if len(parts) >= 3:
				stack.append((parts[-1], suffix))
				stack.append((parts[0], Markup(emote["html"].format(escape(parts[1])))))
				break
		else:
			ret += Markup(urlize(prefix).replace('<a ', '<a target="_blank" ')) + suffix
	return ret

def build_message_html(time, source, target, message, specialuser, usercolor, emoteset):
	if source.lower() == config['notifyuser']:
		return '<div class="notification line" data-timestamp="%d">%s</div>' % (time.timestamp(), escape(message))

	if message[:4].lower() in (".me ", "/me "):
		is_action = True
		message = message[4:]
	else:
		is_action = False

	ret = []
	ret.append('<div class="line" data-timestamp="%d">' % time.timestamp())
	if 'staff' in specialuser:
		ret.append('<span class="badge staff"></span> ')
	if 'admin' in specialuser:
		ret.append('<span class="badge admin"></span> ')
	if "#" + source.lower() == target.lower():
		ret.append('<span class="badge broadcaster"></span> ')
	if 'mod' in specialuser:
		ret.append('<span class="badge mod"></span> ')
	if 'turbo' in specialuser:
		ret.append('<span class="badge turbo"></span> ')
	if 'subscriber' in specialuser:
		ret.append('<span class="badge subscriber"></span> ')
	ret.append('<span class="nick"')
	if usercolor:
		ret.append(' style="color:%s"' % escape(usercolor))
	ret.append('>%s</span>' % escape(get_display_name(source)))

	if is_action:
		ret.append(' <span class="action"')
		if usercolor:
			ret.append(' style="color:%s"' % escape(usercolor))
		ret.append('>')
	else:
		ret.append(": ")

	if 'cleared' in specialuser:
		ret.append('<span class="deleted">&lt;message deleted&gt;</span>')
		# Use escape() rather than urlize() so as not to have live spam links
		# either for users to accidentally click, or for Google to see
		ret.append('<span class="message cleared">%s</span>' % escape(message))
	else:
		messagehtml = format_message(message, get_filtered_emotes(emoteset))
		ret.append('<span class="message">%s</span>' % messagehtml)

	if is_action:
		ret.append('</span>')
	ret.append('</div>')
	return ''.join(ret)

@utils.throttle(CACHE_EXPIRY, params=[0], log=False)
def get_display_name(nick):
	try:
		data = utils.http_request("https://api.twitch.tv/kraken/users/%s" % nick)
		data = json.loads(data)
		return data['display_name']
	except:
		return nick

re_just_words = re.compile("^\w+$")
@utils.throttle(CACHE_EXPIRY, log=False)
def get_twitch_emotes():
	data = utils.http_request("https://api.twitch.tv/kraken/chat/emoticons")
	data = json.loads(data)['emoticons']
	emotesets = {}
	for emote in data:
		regex = emote['regex']
		regex = regex.replace(r"\&lt\;", "<").replace(r"\&gt\;", ">").replace(r"\&quot\;", '"').replace(r"\&amp\;", "&")
		if re_just_words.match(regex):
			regex = r"\b%s\b" % regex
		regex = re.compile("(%s)" % regex)
		for image in emote['images']:
			html = '<img src="%s" width="%d" height="%d" alt="{0}" title="{0}">' % (image['url'], image['width'], image['height'])
			emotesets.setdefault(image.get("emoticon_set"), {})[emote['regex']] = {
				"regex": regex,
				"html": html,
			}
	return emotesets

@utils.throttle(CACHE_EXPIRY, log=False)
def get_twitch_emotes_undocumented():
	# This endpoint is not documented, however `/chat/emoticons` might be deprecated soon.
	data = utils.http_request("https://api.twitch.tv/kraken/chat/emoticon_images")
	data = json.loads(data)["emoticons"]
	emotesets = {}
	for emote in data:
		regex = emote["code"]
		regex = regex.replace(r"\&lt\;", "<").replace(r"\&gt\;", ">").replace(r"\&quot\;", '"').replace(r"\&amp\;", "&")
		if re_just_words.match(regex):
			regex = r"\b%s\b" % regex
		emotesets.setdefault(emote["emoticon_set"], {})[emote["code"]] = {
			"regex": re.compile("(%s)" % regex),
			"html": '<img src="https://static-cdn.jtvnw.net/emoticons/v1/%s/1.0" alt="{0}" title="{0}">' % emote["id"]
		}
	return emotesets

def get_filtered_emotes(setids):
	try:
		try:
			emotesets = get_twitch_emotes()
		except:
			emotesets = get_twitch_emotes_undocumented()
		emotes = dict(emotesets[None])
		for setid in setids:
			emotes.update(emotesets.get(setid, {}))
		return emotes.values()
	except:
		log.exception("Error fetching emotes")
		return []
