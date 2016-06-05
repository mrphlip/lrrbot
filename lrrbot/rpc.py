import asyncio
import random
import re
import math
import logging
import json
import traceback

import sqlalchemy

import common.utils
from common import utils
from common.config import config
from common import game_data
from common import twitch
from lrrbot import googlecalendar, storage
import lrrbot.docstring

log = logging.getLogger('serverevents')

GLOBAL_FUNCTIONS = {}
def global_function(name=None):
	def wrapper(function):
		nonlocal name
		if name is None:
			name = function.__name__
		GLOBAL_FUNCTIONS[name] = function
		return function
	return wrapper

class Server:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop
		self.functions = dict(GLOBAL_FUNCTIONS)

	def add(self, name, function):
		self.functions[name] = function

	def remove(self, name):
		del self.functions[name]

	def function(self, name=None):
		def wrapper(function):
			nonlocal name
			if name is None:
				name = function.__name__
			self.add(name, function)
			return function
		return wrapper

	def __call__(self):
		return Protocol(self)

class Protocol(asyncio.Protocol):
	def __init__(self, server):
		self.server = server
		self.buffer = b""

	def connection_made(self, transport):
		self.transport = transport
		log.debug("Received event connection from server")

	def data_received(self, data):
		self.buffer += data
		if b"\n" in self.buffer:
			request = json.loads(self.buffer.decode())
			log.debug("Command from server (%s): %s(%r)", request['user'], request['command'], request['param'])
			try:
				response = self.server.functions[request['command']](self.server.lrrbot, request['user'], request['param'])
			except utils.PASSTHROUGH_EXCEPTIONS:
				raise
			except Exception:
				log.exception("Exception in on_server_event")
				response = {'success': False, 'result': ''.join(traceback.format_exc())}
			else:
				log.debug("Returning: %r", response)
				response = {'success': True, 'result': response}
			response = json.dumps(response).encode() + b"\n"
			self.transport.write(response)
			self.transport.close()

@global_function()
def get_game_id(lrrbot, user, data):
	return lrrbot.get_game_id()

@global_function()
def get_data(lrrbot, user, data):
	if not isinstance(data['key'], (list, tuple)):
		data['key'] = [data['key']]
	node = storage.data
	for subkey in data['key']:
		node = node.get(subkey, {})
	return node

@global_function()
def set_data(lrrbot, user, data):
	if not isinstance(data['key'], (list, tuple)):
		data['key'] = [data['key']]
	log.info("Setting storage (%s) %s to %r" % (user, '.'.join(data['key']), data['value']))
	# if key is, eg, ["a", "b", "c"]
	# then we want to effectively do:
	# storage.data["a"]["b"]["c"] = value
	# But in case one of those intermediate dicts doesn't exist:
	# storage.data.setdefault("a", {}).setdefault("b", {})["c"] = value
	node = storage.data
	for subkey in data['key'][:-1]:
		node = node.setdefault(subkey, {})
	node[data['key'][-1]] = data['value']
	storage.save()

@global_function()
def get_commands(bot, user, data):
	ret = []
	for command in bot.commands.commands.values():
		doc = lrrbot.docstring.parse_docstring(command['func'].__doc__)
		for cmd in doc.walk():
			if cmd.get_content_maintype() == "multipart":
				continue
			if cmd.get_all("command") is None:
				continue
			ret += [{
				"aliases": cmd.get_all("command"),
				"mod-only": cmd.get("mod-only") == "true",
				"sub-only": cmd.get("sub-only") == "true",
				"public-only": cmd.get("public-only") == "true",
				"throttled": (int(cmd.get("throttle-count", 1)), int(cmd.get("throttled"))) if "throttled" in cmd else None,
				"literal-response": cmd.get("literal-response") == "true",
				"section": cmd.get("section"),
				"description": cmd.get_payload(),
			}]
	return ret

@global_function()
def get_header_info(lrrbot, user, data):
	live = twitch.is_stream_live()
	game_id = lrrbot.get_game_id()

	data = {
		"is_live": live,
		"channel": config['channel'],
	}

	if live and game_id is not None:
		data['current_game'] = {
			"id": game_id,
			"is_override": lrrbot.game_override is not None,
		}
		data['current_show'] = {
			"id": lrrbot.get_show_id(),
			"is_override": lrrbot.show_override is not None,
		}
	elif not live:
		data['nextstream'] = googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL)

	if 'advice' in storage.data['responses']:
		data['advice'] = random.choice(storage.data['responses']['advice']['response'])

	return data

@global_function()
def nextstream(lrrbot, user, data):
	return googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL, verbose=False)

@global_function()
def set_show(bot, user, data):
	import lrrbot.commands
	lrrbot.commands.show.set_show(bot, data["show"])
	return {"status": "OK"}

@global_function()
def get_show_id(lrrbot, user, data):
	return lrrbot.get_show_id()

@global_function()
def get_tweet(bot, user, data):
	import lrrbot.commands
	mode = utils.weighted_choice([(0, 10), (1, 4), (2, 1)])
	if mode == 0: # get random !advice
		return random.choice(storage.data['responses']['advice']['response'])
	elif mode == 1: # get a random !quote
		quotes = bot.metadata.tables["quotes"]
		with bot.engine.begin() as conn:
			query = sqlalchemy.select([quotes.c.quote, quotes.c.attrib_name]).where(~quotes.c.deleted)
			row = common.utils.pick_random_elements(conn.execute(query), 1)[0]
		if row is None:
			return None

		quote, name = row

		quote_msg = "\"{quote}\"".format(quote=quote)
		if name:
			quote_msg += " —{name}".format(name=name)
		return quote_msg
	else: # get a random statistic
		game_per_show_data = bot.metadata.tables["game_per_show_data"]
		game_stats = bot.metadata.tables["game_stats"]
		games = bot.metadata.tables["games"]
		shows = bot.metadata.tables["shows"]
		stats = bot.metadata.tables["stats"]
		with bot.engine.begin() as conn:
			res = conn.execute(
				sqlalchemy.select([
					sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
					shows.name,
					game_data.stat_plural(stats, game_stats.c.count),
					game_stats.c.count,
					sqlalchemy.func.log(game_stats.c.count)
				]).select_from(
					game_stats
						.join(games, games.c.id == game_stats.c.game_id)
						.join(shows, shows.c.id == game_stats.c.show_id)
						.outerjoin(game_per_show_data, (game_per_show_data.c.game_id == game_stats.c.game_id) & (game_per_show_data.c.show_id == game_stats.c.show_id))
						.join(stats, stats.c.id == game_stats.c.stat_id)
				).where(game_stats.c.count > 1)
			)
			game, show, stat, count = utils.pick_weighted_random_elements((
				((game, show, stat, count), weight)
				for game, show, stat, count, weight in res
			), 1)[0]

		return "%d %s for %s on %s" % (count, stat, game, show)
