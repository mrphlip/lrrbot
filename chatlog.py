#!/usr/bin/python3
import oursql
import www.secrets
import utils
import queue
import threading
import json
import re
import time
import irc.client
from jinja2.utils import escape, urlize
from config import config

__all__ = ["log_chat", "clear_chat_log", "exitthread"]

CACHE_EXPIRY = 7*24*60*60
PURGE_PERIOD = 15*60

queue = queue.Queue()
mysql_conn = oursql.connect(**www.secrets.mysqlopts)
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
	queue.put(("log_chat", (time.time(), event, metadata)))

def clear_chat_log(nick):
	queue.put(("clear_chat_log", (time.time(), nick)))

def rebuild_all():
	queue.put(("rebuild_all", ()))

def exitthread():
	queue.put(("exit", ()))
	thread.join()


def do_log_chat(time, event, metadata):
	"""
	Add a new message to the chat log.
	"""
	# Don't log server commands like .timeout
	message = event.arguments[0]
	if message[0] in "./" and message[1:4].lower() != "me ":
		return

	source = irc.client.NickMask(event.source).nick
	with mysql_conn as cur:
		cur.execute("INSERT INTO LOG (TIME, SOURCE, TARGET, MESSAGE, SPECIALUSER, USERCOLOR, EMOTESET, MESSAGEHTML) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
			time,
			source,
			event.target,
			event.arguments[0],
			','.join(metadata.get('specialuser',[])),
			metadata.get('usercolor'),
			','.join(str(i) for i in metadata.get('emoteset', [])),
			build_message_html(time, source, event.target, event.arguments[0], metadata.get('specialuser', []), metadata.get('usercolor'), metadata.get('emoteset', [])),
		))

def do_clear_chat_log(time, nick):
	"""
	Mark a user's earlier posts as "deleted" in the chat log, for when a user is banned/timed out.
	"""
	with mysql_conn as cur:
		cur.execute("SELECT ID, TIME, SOURCE, TARGET, MESSAGE, SPECIALUSER, USERCOLOR, EMOTESET FROM LOG  WHERE SOURCE=? AND TIME>=?", (
			nick,
			time - PURGE_PERIOD,
		))
		for i, (key, time, source, target, message, specialuser, usercolor, emoteset) in enumerate(cur):
			specialuser = set(specialuser.split(',')) if specialuser else set()
			emoteset = set(int(i) for i in emoteset.split(',')) if emoteset else set()

			specialuser.add("cleared")

			cur.execute("UPDATE LOG SET SPECIALUSER=?, MESSAGEHTML=? WHERE ID=?", (
				','.join(specialuser),
				build_message_html(time, source, target, message, specialuser, usercolor, emoteset),
				key,
			))

def do_rebuild_all():
	"""
	Rebuild all the message HTML blobs in the database.
	"""
	with mysql_conn as cur:
		count = None
		cur.execute("SELECT COUNT(*) FROM LOG")
		for count, in cur:
			pass
		cur.execute("SELECT ID, TIME, SOURCE, TARGET, MESSAGE, SPECIALUSER, USERCOLOR, EMOTESET FROM LOG")
		for i, (key, time, source, target, message, specialuser, usercolor, emoteset) in enumerate(cur):
			if i % 100 == 0:
				print("\r%d/%d" % (i, count), end='')
			specialuser = set(specialuser.split(',')) if specialuser else set()
			emoteset = set(int(i) for i in emoteset.split(',')) if emoteset else set()
			cur.execute("UPDATE LOG SET MESSAGEHTML=? WHERE ID=?", (
				build_message_html(time, source, target, message, specialuser, usercolor, emoteset),
				key,
			))
	print("\r%d/%d" % (count, count))


def build_message_html(time, source, target, message, specialuser, usercolor, emoteset):
	if source.lower() == config['notifyuser']:
		return '<div class="notification line" data-timestamp="%d">%s</div>' % (time, escape(message))

	if message[:4].lower() in (".me ", "/me "):
		is_action = True
		message = message[4:]
	else:
		is_action = False

	ret = []
	ret.append('<div class="line" data-timestamp="%d">' % time)
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
		messagehtml = urlize(message).replace('<a ', '<a target="_blank" ')
		for emote in get_filtered_emotes(emoteset):
			messagehtml = emote['regex'].sub(emote['html'], messagehtml)
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

@utils.throttle(CACHE_EXPIRY, log=False)
def get_twitch_emotes():
	data = utils.http_request("https://api.twitch.tv/kraken/chat/emoticons")
	data = json.loads(data)['emoticons']
	emotesets = {}
	for emote in data:
		regex = re.compile("(%s)" % emote['regex'])
		for image in emote['images']:
			html = '<img src="%s" width="%d" height="%d" alt="\\1" title="\\1">' % (image['url'], image['width'], image['height'])
			emotesets.setdefault(image.get("emoticon_set"), {})[emote['regex']] = {
				"regex": regex,
				"html": html,
			}
	return emotesets

def get_filtered_emotes(setids):
	emotesets = get_twitch_emotes()
	emotes = emotesets[None]
	for setid in setids:
		emotes.update(emotesets.get(setid, {}))
	return emotes.values()

if __name__ == "__main__":
	createthread()
	rebuild_all()
	exitthread()
