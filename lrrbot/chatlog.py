import json
import re
import pytz
import datetime
import logging
import asyncio
import urllib.parse

import irc.client
from jinja2.utils import urlize as real_urlize
from markupsafe import Markup, escape
import sqlalchemy

import common.http
import common.twitch
import common.url
from common import utils
from common.config import config

log = logging.getLogger('chatlog')

CACHE_EXPIRY = 7*24*60*60
PURGE_PERIOD = datetime.timedelta(minutes=5)

queue = asyncio.Queue()

def urlize(text):
	return real_urlize(text).replace('<a ', '<a target="_blank" rel="noopener nofollow" ')

class ChatLog:
	def __init__(self, engine, metadata):
		self.engine = engine
		self.metadata = metadata

		self.queue = asyncio.Queue()

	# Chat-log handling functions live in an asyncio task, so that functions that take
	# a long time to run, like downloading the emote list, don't block the bot... but
	# one master task, with a message queue, so that things still happen in the right order.
	async def run_task(self):
		while True:
			ev, params = await self.queue.get()
			if ev == "log_chat":
				await self.do_log_chat(*params)
			elif ev == "clear_chat_log":
				await self.do_clear_chat_log(*params)
			elif ev == "clear_chat_log_msg":
				await self.do_clear_chat_log_msg(*params)
			elif ev == "rebuild_all":
				await self.do_rebuild_all(*params)
			elif ev == "exit":
				break

	def log_chat(self, event, metadata):
		self.queue.put_nowait(("log_chat", (datetime.datetime.now(pytz.utc), event, metadata)))

	def clear_chat_log(self, nick):
		self.queue.put_nowait(("clear_chat_log", (datetime.datetime.now(pytz.utc), nick)))

	def clear_chat_log_msg(self, msgid):
		self.queue.put_nowait(("clear_chat_log_msg", (msgid,)))

	def rebuild_all(self, period=7):
		self.queue.put_nowait(("rebuild_all", (period,)))

	def stop_task(self):
		self.queue.put_nowait(("exit", ()))

	@utils.swallow_errors
	async def do_log_chat(self, time, event, metadata):
		"""
		Add a new message to the chat log.
		"""
		# Don't log blank lines or server commands like .timeout
		message = event.arguments[0]
		if not message or (message[0] in "./" and message[1:4].lower() != "me "):
			return

		source = irc.client.NickMask(event.source).nick
		html = await self.build_message_html(time, source, event.target, event.arguments[0], metadata.get('specialuser', []), metadata.get('usercolor'), metadata.get('emoteset', []), metadata.get('emotes'), metadata.get('display-name'))
		with self.engine.connect() as conn:
			conn.execute(self.metadata.tables["log"].insert(), {
				"time": time,
				"source": source,
				"target": event.target,
				"message": event.arguments[0],
				"specialuser": list(metadata.get('specialuser', [])),
				"usercolor": metadata.get('usercolor'),
				"emoteset": list(metadata.get('emoteset', [])),
				"emotes": metadata.get('emotes'),
				"displayname": metadata.get('display-name'),
				"messagehtml": html,
				"msgid": metadata.get('id'),
			})
			conn.commit()

	@utils.swallow_errors
	async def do_clear_chat_log(self, time, nick):
		"""
		Mark a user's earlier posts as "deleted" in the chat log, for when a user is banned/timed out.
		"""
		log = self.metadata.tables["log"]
		await self._delete_messages((log.c.source == nick) & (log.c.time >= time - PURGE_PERIOD))

	@utils.swallow_errors
	async def do_clear_chat_log_msg(self, msgid):
		"""
		Mark a user's earlier posts as "deleted" in the chat log, for when a user is banned/timed out.
		"""
		log = self.metadata.tables["log"]
		await self._delete_messages((log.c.msgid == msgid))

	async def _delete_messages(self, condition, undelete=False):
		log = self.metadata.tables["log"]
		with self.engine.connect() as conn:
			query = sqlalchemy.select(
				log.c.id, log.c.time, log.c.source, log.c.target, log.c.message, log.c.specialuser,
				log.c.usercolor, log.c.emoteset, log.c.emotes, log.c.displayname
			).where(condition)
			rows = conn.execute(query).fetchall()
		if len(rows) == 0:
			return
		new_rows = []
		for key, time, source, target, message, specialuser, usercolor, emoteset, emotes, displayname in rows:
			specialuser = set(specialuser) if specialuser else set()
			emoteset = set(emoteset) if emoteset else set()

			if undelete:
				specialuser.discard("cleared")
			else:
				specialuser.add("cleared")

			html = await self.build_message_html(time, source, target, message, specialuser, usercolor, emoteset, emotes, displayname)
			new_rows.append({
				"specialuser": list(specialuser),
				"messagehtml": html,
				"_key": key,
			})
		with self.engine.connect() as conn:
			conn.execute(log.update().where(log.c.id == sqlalchemy.bindparam("_key")), new_rows)
			conn.commit()

	@utils.swallow_errors
	async def do_rebuild_all(self, period):
		"""
		Rebuild all the message HTML blobs in the database.
		"""
		since = datetime.datetime.now(pytz.utc) - datetime.timedelta(days=period)
		log = self.metadata.tables["log"]
		conn_select = self.engine.connect()
		count, = conn_select.execute(sqlalchemy.select(sqlalchemy.func.count()).select_from(log).where(log.c.time >= since)).first()
		rows = conn_select.execute(sqlalchemy.select(
			log.c.id, log.c.time, log.c.source, log.c.target, log.c.message, log.c.specialuser,
			log.c.usercolor, log.c.emoteset, log.c.emotes, log.c.displayname
		).where(log.c.time >= since).execution_options(stream_results=True))

		conn_update = self.engine.connect()

		try:
			for i, (key, time, source, target, message, specialuser, usercolor, emoteset, emotes, displayname) in enumerate(rows):
				if i % 100 == 0:
					print("\r%d/%d" % (i, count), end='')
				specialuser = set(specialuser) if specialuser else set()
				emoteset = set(emoteset) if emoteset else set()
				html = await self.build_message_html(time, source, target, message, specialuser, usercolor, emoteset, emotes, displayname)
				conn_update.execute(log.update().where(log.c.id == key), {"messagehtml": html})
			print("\r%d/%d" % (count, count))
			conn_update.commit()
		except:
			conn_update.rollback()
			raise
		finally:
			conn_select.close()
			conn_update.close()

	async def format_message(self, message, emotes, emoteset, size="1", cheer=False):
		if emotes is not None:
			return await self.format_message_explicit_emotes(message, emotes, size=size, cheer=cheer)
		else:
			return await self.format_message_emoteset(message, (await get_filtered_emotes(emoteset)), cheer=cheer)

	async def format_message_emoteset(self, message, emotes, cheer=False):
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
				ret += Markup(await self.format_message_cheer(prefix, cheer=cheer)) + suffix
		return ret

	async def format_message_explicit_emotes(self, message, emotes, size="1", cheer=False):
		if not emotes:
			return Markup(await self.format_message_cheer(message, cheer=cheer))

		# emotes format is
		# <emoteid>:<start>-<end>[,<start>-<end>,...][/<emoteid>:<start>-<end>,.../...]
		# eg:
		# 123:0-2/456:3-6,7-10
		# means that chars 0-2 (inclusive, 0-based) are emote 123,
		# and chars 3-6 and 7-10 are two copies of emote 456
		parsed_emotes = []
		for emote in emotes.split('/'):
			emoteid, positions = emote.split(':')
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
				bits.append(await self.format_message_cheer(message[prev:start], cheer=cheer))
			url = escape("https://static-cdn.jtvnw.net/emoticons/v1/%s/%s.0" % (
				urllib.parse.quote(emoteid), size))
			command = escape(message[start:end])
			bits.append('<img src="%s" alt="%s" title="%s">' % (url, command, command))
			prev = end
		if prev < len(message):
			bits.append(await self.format_message_cheer(message[prev:], cheer=cheer))
		return Markup(''.join(bits))

	async def format_message_cheer(self, message, cheer=False):
		if not cheer:
			return urlize(message)
		else:
			re_cheer, cheermotes = await get_cheermotes_data()
			bits = []
			splits = re_cheer.split(message)
			for i in range(0, len(splits), 4):
				bits.append(urlize(splits[i]))
				if i + 1 < len(splits):
					cheermote = cheermotes[splits[i + 2].lower()]
					codeprefix = splits[i + 1]
					count = int(splits[i + 3])
					for tier in cheermote['tiers']:
						if tier['level'] <= count:
							break
					bits.append('<span class="cheer" style="color: %s"><img src="%s" alt="%s" title="%s %d">%d</span>' % (escape(tier['color']), escape(tier['image']), escape(codeprefix), escape(cheermote['prefix']), count, count))
			return ''.join(bits)

	async def build_message_html(self, time, source, target, message, specialuser, usercolor, emoteset, emotes, displayname):
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
		ret.append('>%s</span>' % escape(displayname or await get_display_name(source)))

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
			messagehtml = await self.format_message(message, emotes, emoteset, cheer='cheer' in specialuser)
			ret.append('<span class="message">%s</span>' % messagehtml)

		if is_action:
			ret.append('</span>')
		ret.append('</div>')
		return ''.join(ret)

@utils.cache(CACHE_EXPIRY, params=[0])
async def get_display_name(nick):
	try:
		return (await common.twitch.get_user(name=nick)).display_name
	except utils.PASSTHROUGH_EXCEPTIONS:
		raise
	except Exception:
		return nick

re_just_words = re.compile(r"^\w+$")
@utils.cache(CACHE_EXPIRY)
async def get_twitch_emotes():
	"""
	See:
	https://dev.twitch.tv/docs/api/reference#get-emote-sets
	"""
	headers = {
		"Client-ID": config['twitch_clientid'],
		"Authorization": f"Bearer {await common.twitch.get_token()}",
	}
	data = await common.http.request("https://api.twitch.tv/helix/chat/emotes/set", headers=headers, data=[
		('emote_set_id', '0'), # global emotes
		('emote_set_id', '317'), # LRR emotes
	])
	data = json.loads(data)["data"]
	emotesets = {}
	for emote in data:
		emoticon_set = int(emote['emote_set_id'])
		emotesets.setdefault(emoticon_set, {})[emote['name']] = {
			"regex": re.compile(r"(\b%s\b)" % re.escape(emote['name'])),
			"html": '<img src="%s" alt="{0}" title="{0}">' % emote["images"]['url_1x']
		}
	return emotesets

async def get_filtered_emotes(setids):
	try:
		emotesets = await get_twitch_emotes()
		emotes = dict(emotesets[0])
		for setid in setids:
			emotes.update(emotesets.get(setid, {}))
		return emotes.values()
	except utils.PASSTHROUGH_EXCEPTIONS:
		raise
	except Exception:
		log.exception("Error fetching emotes")
		return []

@utils.cache(CACHE_EXPIRY)
async def get_cheermotes_data():
	# see: https://dev.twitch.tv/docs/api/reference#get-cheermotes
	headers = {
		'Client-ID': config['twitch_clientid'],
		'Authorization': f'Bearer {await common.twitch.get_token()}',
	}
	data = await common.http.request("https://api.twitch.tv/helix/bits/cheermotes", headers=headers)
	data = json.loads(data)
	cheermotes = {
		action['prefix'].lower(): {
			'prefix': action['prefix'],  # the original capitalisation
			'tiers': [
				{
					'color': tier['color'],
					'level': tier['min_bits'],
					'image': tier['images']['light']['static']['1'],
				}
				for tier in sorted(action['tiers'], key=lambda tier:tier['min_bits'], reverse=True)
			],
		}
		for action in data['data']
	}
	re_cheer = r"(?:^|(?<=\s))((%s)0*)([1-9][0-9]*)(?:$|(?=\s))" % "|".join(re.escape(i) for i in cheermotes.keys())
	re_cheer = re.compile(re_cheer, re.IGNORECASE)
	return re_cheer, cheermotes
