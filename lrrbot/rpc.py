import asyncio
import aiomas
import random
import re
import math
import logging
import json
import traceback

import sqlalchemy

import common.utils
import common.rpc
from common import utils
from common.config import config
from common import game_data
from common import twitch
from lrrbot import googlecalendar, storage
import lrrbot.docstring

log = logging.getLogger('serverevents')

class Server(common.rpc.Server):
	router = aiomas.rpc.Service(['explain', 'link_spam', 'spam', 'static'])

	def __init__(self, lrrbot, loop):
		super().__init__()
		self.lrrbot = lrrbot
		self.loop = loop

		self.explain = None
		self.link_spam = None
		self.spam = None
		self.static = None

	@aiomas.expose
	def get_game_id(self):
		return self.lrrbot.get_game_id()

	@aiomas.expose
	def get_data(self, key):
		if not isinstance(key, (list, tuple)):
			key = [key]
		node = storage.data
		for subkey in key:
			node = node.get(subkey, {})
		return node

	@aiomas.expose
	def set_data(self, key, value):
		if not isinstance(key, (list, tuple)):
			key = [key]
		log.info("Setting storage %s to %r" % (user, '.'.join(key), value))
		# if key is, eg, ["a", "b", "c"]
		# then we want to effectively do:
		# storage.data["a"]["b"]["c"] = value
		# But in case one of those intermediate dicts doesn't exist:
		# storage.data.setdefault("a", {}).setdefault("b", {})["c"] = value
		node = storage.data
		for subkey in key[:-1]:
			node = node.setdefault(subkey, {})
		node[key[-1]] = value
		storage.save()

	@aiomas.expose
	def get_commands(self):
		ret = []
		for command in self.lrrbot.commands.commands.values():
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

	@aiomas.expose
	def get_header_info(self):
		live = twitch.is_stream_live()
		game_id = self.lrrbot.get_game_id()

		data = {
			"is_live": live,
			"channel": config['channel'],
		}

		if live and game_id is not None:
			data['current_game'] = {
				"id": game_id,
				"is_override": self.lrrbot.game_override is not None,
			}
			data['current_show'] = {
				"id": self.lrrbot.get_show_id(),
				"is_override": self.lrrbot.show_override is not None,
			}
		elif not live:
			data['nextstream'] = googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL)

		if 'advice' in storage.data['responses']:
			data['advice'] = random.choice(storage.data['responses']['advice']['response'])

		return data

	@aiomas.expose
	def nextstream(self):
		return googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL, verbose=False)

	@aiomas.expose
	def set_show(self, show):
		import lrrbot.commands
		lrrbot.commands.show.set_show(self.lrrbot, show)

	@aiomas.expose
	def get_show_id(self):
		return self.lrrbot.get_show_id()

	@aiomas.expose
	def get_tweet(self):
		tweet = self.generate_tweet()
		while len(tweet) > 140:
			tweet = self.generate_tweet()
		return tweet

	def generate_tweet(self):
		import lrrbot.commands
		mode = utils.weighted_choice([(0, 10), (1, 4), (2, 1)])
		if mode == 0: # get random !advice
			return random.choice(storage.data['responses']['advice']['response'])
		elif mode == 1: # get a random !quote
			quotes = self.lrrbot.metadata.tables["quotes"]
			with self.lrrbot.engine.begin() as conn:
				query = sqlalchemy.select([quotes.c.quote, quotes.c.attrib_name, quotes.c.context]).where(~quotes.c.deleted)
				row = common.utils.pick_random_elements(conn.execute(query), 1)[0]
			if row is None:
				return None

			quote, name, context = row

			quote_msg = "\"{quote}\"".format(quote=quote)
			if name:
				quote_msg += " —{name}".format(name=name)
				if context:
					quote_msg += ", {context}".format(context=context)
			return quote_msg
		else: # get a random statistic
			game_per_show_data = self.lrrbot.metadata.tables["game_per_show_data"]
			game_stats = self.lrrbot.metadata.tables["game_stats"]
			games = self.lrrbot.metadata.tables["games"]
			shows = self.lrrbot.metadata.tables["shows"]
			stats = self.lrrbot.metadata.tables["stats"]
			with self.lrrbot.engine.begin() as conn:
				res = conn.execute(
					sqlalchemy.select([
						sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
						shows.c.name,
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

	@aiomas.expose
	def patreon_pledge(self, data):
		patreon_users = self.lrrbot.metadata.tables['patreon_users']
		users = self.lrrbot.metadata.tables['users']
		with self.lrrbot.engine.begin() as conn:
			name = conn.execute(sqlalchemy.select([patreon_users.c.full_name])
				.select_from(users.join(patreon_users))
				.where(users.c.name == config['channel'])
			).first()
		print(name)
		if name:
			self.lrrbot.connection.privmsg("#" + config['channel'], "lrrSPOT Thanks for supporting %s on Patreon, %s ! (Today's %s count: %d)" % (name[0], data['twitch']['name'] if data['twitch'] is not None else data['patreon']['full_name'], utils.counter(), data['count']))
