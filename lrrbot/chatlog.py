import queue
import json
import re
import time
import pytz
import datetime
import logging
import asyncio

import irc.client
from jinja2.utils import Markup, escape, urlize

from common import utils
from common.config import config


__all__ = ["log_chat", "clear_chat_log", "exitthread"]

log = logging.getLogger('chatlog')

CACHE_EXPIRY = 7*24*60*60
PURGE_PERIOD = datetime.timedelta(minutes=5)

queue = asyncio.Queue()

# Chat-log handling functions live in an asyncio task, so that functions that take
# a long time to run, like downloading the emote list, don't block the bot... but
# one master task, with a message queue, so that things still happen in the right order.
@asyncio.coroutine
def run_task():
	while True:
		ev, params = yield from queue.get()
		if ev == "log_chat":
			yield from do_log_chat(*params)
		elif ev == "clear_chat_log":
			yield from do_clear_chat_log(*params)
		elif ev == "rebuild_all":
			yield from do_rebuild_all()
		elif ev == "exit":
			break


def log_chat(event, metadata):
	queue.put_nowait(("log_chat", (datetime.datetime.now(pytz.utc), event, metadata)))

def clear_chat_log(nick):
	queue.put_nowait(("clear_chat_log", (datetime.datetime.now(pytz.utc), nick)))

def rebuild_all():
	queue.put_nowait(("rebuild_all", ()))

def stop_task():
	queue.put_nowait(("exit", ()))


@utils.swallow_errors
@asyncio.coroutine
def do_log_chat(time, event, metadata):
	"""
	Add a new message to the chat log.
	"""
	# Don't log server commands like .timeout
	message = event.arguments[0]
	if message[0] in "./" and message[1:4].lower() != "me ":
		return

	source = irc.client.NickMask(event.source).nick
	html = yield from build_message_html(time, source, event.target, event.arguments[0], metadata.get('specialuser', []), metadata.get('usercolor'), metadata.get('emoteset', []), metadata.get('emotes'), metadata.get('display-name'))
	with utils.get_postgres() as conn, conn.cursor() as cur:
		cur.execute("INSERT INTO log (time, source, target, message, specialuser, usercolor, emoteset, emotes, displayname, messagehtml) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", (
			time,
			source,
			event.target,
			event.arguments[0],
			list(metadata.get('specialuser', [])),
			metadata.get('usercolor'),
			list(metadata.get('emoteset', [])),
			metadata.get('emotes'),
			metadata.get('display-name'),
			html,
		))

@utils.swallow_errors
@asyncio.coroutine
def do_clear_chat_log(time, nick):
	"""
	Mark a user's earlier posts as "deleted" in the chat log, for when a user is banned/timed out.
	"""
	with utils.get_postgres() as conn, conn.cursor() as cur:
		cur.execute("SELECT id, time, source, target, message, specialuser, usercolor, emoteset, emotes, displayname FROM log WHERE source=%s AND time>=%s", (
			nick,
			time - PURGE_PERIOD,
		))
		rows = list(cur)
	for i, (key, time, source, target, message, specialuser, usercolor, emoteset, emotes, displayname) in enumerate(rows):
		specialuser = set(specialuser) if specialuser else set()
		emoteset = set(emoteset) if emoteset else set()

		specialuser.add("cleared")

		html = yield from build_message_html(time, source, target, message, specialuser, usercolor, emoteset, emotes, displayname)
		with utils.get_postgres() as conn, conn.cursor() as cur:
			cur.execute("UPDATE log SET specialuser=%s, messagehtml=%s WHERE id=%s", (
				list(specialuser),
				html,
				key,
			))

@utils.swallow_errors
@asyncio.coroutine
def do_rebuild_all():
	"""
	Rebuild all the message HTML blobs in the database.
	"""
	with utils.get_postgres() as conn, conn.cursor() as cur:
		cur.execute("SELECT id, time, source, target, message, specialuser, usercolor, emoteset, emotes, displayname FROM log")
		rows = list(cur)
	for i, (key, time, source, target, message, specialuser, usercolor, emoteset, emotes, displayname) in enumerate(rows):
		if i % 100 == 0:
			print("\r%d/%d" % (i, len(rows)), end='')
		specialuser = set(specialuser) if specialuser else set()
		emoteset = set(emoteset) if emoteset else set()
		html = yield from build_message_html(time, source, target, message, specialuser, usercolor, emoteset, emotes, displayname)
		with utils.get_postgres() as conn, conn.cursor() as cur:
			cur.execute("UPDATE log SET messagehtml=%s WHERE id=%s", (
				html,
				key,
			))
	print("\r%d/%d" % (len(rows), len(rows)))

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

def format_message_explicit_emotes(message, emotes, size="1.0"):
	if not emotes:
		return Markup(urlize(message).replace('<a ', '<a target="_blank" '))

	# emotes format is
	# <emoteid>:<start>-<end>[,<start>-<end>,...][/<emoteid>:<start>-<end>,.../...]
	# eg:
	# 123:0-2/456:3-6,7-10
	# means that chars 0-2 (inclusive, 0-based) are emote 123,
	# and chars 3-6 and 7-10 are two copies of emote 456
	parsed_emotes = []
	for emote in emotes.split('/'):
		emoteid, positions = emote.split(':')
		emoteid = int(emoteid)
		for position in positions.split(','):
			start, end = position.split('-')
			start = int(start)
			end = int(end) + 1 # make it left-inclusive, to be more consistent with how Python does things
			parsed_emotes.append((start, end, emoteid))
	parsed_emotes.sort(key=lambda x:x[0])

	bits = []
	prev = 0
	for start, end, emoteid in parsed_emotes:
		if prev < start:
			bits.append(urlize(message[prev:start]).replace('<a ', '<a target="_blank" '))
		url = escape("http://static-cdn.jtvnw.net/emoticons/v1/%d/%s" % (emoteid, size))
		command = escape(message[start:end])
		bits.append('<img src="%s" alt="%s" title="%s">' % (url, command, command))
		prev = end
	if prev < len(message):
		bits.append(urlize(message[prev:]).replace('<a ', '<a target="_blank" '))
	return Markup(''.join(bits))

@asyncio.coroutine
def build_message_html(time, source, target, message, specialuser, usercolor, emoteset, emotes, displayname):
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
	ret.append('>%s</span>' % escape(displayname or (yield from get_display_name(source))))

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
	elif emotes is not None:
		messagehtml = format_message_explicit_emotes(message, emotes)
		ret.append('<span class="message">%s</span>' % messagehtml)
	else:
		messagehtml = format_message(message, (yield from get_filtered_emotes(emoteset)))
		ret.append('<span class="message">%s</span>' % messagehtml)

	if is_action:
		ret.append('</span>')
	ret.append('</div>')
	return ''.join(ret)

@utils.cache(CACHE_EXPIRY, params=[0])
@asyncio.coroutine
def get_display_name(nick):
	try:
		data = yield from utils.http_request_coro("https://api.twitch.tv/kraken/users/%s" % nick)
		data = json.loads(data)
		return data['display_name']
	except:
		return nick

re_just_words = re.compile("^\w+$")
@utils.cache(CACHE_EXPIRY)
@asyncio.coroutine
def get_twitch_emotes():
	data = yield from utils.http_request_coro("https://api.twitch.tv/kraken/chat/emoticons")
	data = json.loads(data)['emoticons']
	emotesets = {}
	for emote in data:
		regex = emote['regex']
		if regex == r"\:-?[\\/]": # Don't match :/ inside URLs
			regex = r"\:-?[\\/](?![\\/])"
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

@utils.cache(CACHE_EXPIRY)
@asyncio.coroutine
def get_twitch_emotes_undocumented():
	# This endpoint is not documented, however `/chat/emoticons` might be deprecated soon.
	data = yield from utils.http_request_coro("https://api.twitch.tv/kraken/chat/emoticon_images")
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

@asyncio.coroutine
def get_filtered_emotes(setids):
	try:
		try:
			emotesets = yield from get_twitch_emotes()
		except:
			emotesets = yield from get_twitch_emotes_undocumented()
		emotes = dict(emotesets[None])
		for setid in setids:
			emotes.update(emotesets.get(setid, {}))
		return emotes.values()
	except:
		log.exception("Error fetching emotes")
		return []
