import aiomas
import random
import logging

import sqlalchemy

import common.utils
import common.rpc
from common import utils
from common.config import config
from common import twitch
from lrrbot import storage
import lrrbot.docstring
from lrrbot.commands.static import get_response

log = logging.getLogger('serverevents')

class Server(common.rpc.Server):
	router = aiomas.rpc.Service(['cardviewer', 'link_spam', 'spam', 'static'])

	def __init__(self, lrrbot, loop):
		super().__init__()
		self.lrrbot = lrrbot
		self.loop = loop

		self.cardviewer = None
		self.link_spam = None
		self.spam = None
		self.static = None

	@aiomas.expose
	async def get_game_id(self):
		return await self.lrrbot.get_game_id()

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
		log.info("Setting storage %s to %r" % ('.'.join(key), value))
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
	async def get_header_info(self):
		live = await twitch.is_stream_live()
		game_id = await self.lrrbot.get_game_id()

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

		data['advice'] = get_response(self.lrrbot, "advice")

		return data

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
		while len(tweet) > 280:
			tweet = self.generate_tweet()
		return tweet

	def generate_tweet(self):
		import lrrbot.commands
		QUOTE = 1
		ADVICE = 2
		SECRET = 3
		SMASH = 4
		options = [(QUOTE, 5)]
		options.append((ADVICE, 10))
		options.append((SECRET, 2))
		#options.append((SMASH, 2))
		mode = utils.weighted_choice(options)
		if mode == ADVICE:
			return get_response(self.lrrbot, "advice")
		elif mode == SECRET:
			return get_response(self.lrrbot, "secret")
		elif mode == SMASH:
			return get_response(self.lrrbot, "smash")
		elif mode == QUOTE:
			quotes = self.lrrbot.metadata.tables["quotes"]
			with self.lrrbot.engine.connect() as conn:
				query = sqlalchemy.select(quotes.c.quote, quotes.c.attrib_name, quotes.c.context).where(~quotes.c.deleted)
				row = common.utils.pick_random_elements(conn.execute(query), 1)[0]
			if row is None:
				return None

			quote, name, context = row

			quote_msg = f'"{quote}"'
			if name:
				quote_msg += f" —{name}"
				if context:
					quote_msg += f", {context}"
			return quote_msg

	@aiomas.expose
	def disconnect_from_chat(self):
		self.lrrbot.disconnect()
