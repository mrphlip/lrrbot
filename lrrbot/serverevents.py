import random
import re
import math

from common import utils
from lrrbot import bot, log, googlecalendar, storage, commands


@bot.server_event()
def current_game(lrrbot, user, data):
	game = lrrbot.get_current_game()
	if game:
		return game['id']
	else:
		return None

@bot.server_event()
def current_game_name(lrrbot, user, data):
	game = lrrbot.get_current_game()
	if game:
		return game['name']
	else:
		return None

@bot.server_event()
def get_data(lrrbot, user, data):
	if not isinstance(data['key'], (list, tuple)):
		data['key'] = [data['key']]
	node = storage.data
	for subkey in data['key']:
		node = node.get(subkey, {})
	return node

@bot.server_event()
def set_data(lrrbot, user, data):
	if not isinstance(data['key'], (list, tuple)):
		data['key'] = [data['key']]
	log.info("Setting storage %s to %r" % ('.'.join(data['key']), data['value']))
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

@bot.server_event()
def modify_commands(lrrbot, user, data):
	commands.static.modify_commands(data)
	bot.compile()

@bot.server_event()
def modify_explanations(lrrbot, user, data):
	commands.explain.modify_explanations(data)
	bot.compile()

@bot.server_event()
def modify_spam_rules(lrrbot, user, data):
	storage.data['spam_rules'] = data
	storage.save()
	lrrbot.spam_rules = [(re.compile(i['re']), i['message']) for i in storage.data['spam_rules']]

@bot.server_event()
def get_commands(lrrbot, user, data):
	ret = []
	for command in lrrbot.commands.values():
		doc = utils.parse_docstring(command['func'].__doc__)
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

@bot.server_event()
def get_header_info(lrrbot, user, data):
	game = lrrbot.get_current_game()
	data = {}
	if game is not None:
		data['current_game'] = {
			"name": game['name'],
			"display": game.get("display", game["name"]),
			"id": game["id"],
			"is_override": lrrbot.game_override is not None,
		}
		show = lrrbot.show_override or lrrbot.show
		data['current_show'] = {
			"id": show,
			"name": storage.data.get("shows", {}).get(show, {}).get("name", show),
		}
		stats = [{
			"count": v,
			"type": storage.data['stats'][k].get("singular" if v == 1 else "plural", k)
		} for (k,v) in game['stats'].items() if v]
		stats.sort(key=lambda i: (-i['count'], i['type']))
		data['current_game']['stats'] = stats
		if game.get("votes"):
			good = sum(game['votes'].values())
			total = len(game['votes'])
			data["current_game"]["rating"] = {
				"good": good,
				"total": total,
				"perc": 100.0 * good / total,
			}
		if user is not None:
			data["current_game"]["my_rating"] = game.get("votes", {}).get(user.lower())
	if 'advice' in storage.data['responses']:
		data['advice'] = random.choice(storage.data['responses']['advice']['response'])
	if user is not None:
		data['is_mod'] = lrrbot.is_mod_nick(user)
		data['is_sub'] = lrrbot.is_sub_nick(user)
	else:
		data['is_mod'] = data['is_sub'] = False
	return data

@bot.server_event()
def nextstream(lrrbot, user, data):
	return googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL, verbose=False)

@bot.server_event()
def set_show(lrrbot, user, data):
	if user is not None and lrrbot.is_mod_nick(user):
		commands.show.set_show(lrrbot, data["show"])
		return {"status": "OK"}
	return {"status": "error: %s is not a mod" % user}

@bot.server_event()
def get_show(lrrbot, user, data):
	return lrrbot.show_override or lrrbot.show

@bot.server_event()
@utils.with_postgres
def get_tweet(conn, cur, lrrbot, user, data):
	if user is not None and lrrbot.is_mod_nick(user):
		mode = utils.weighted_choice([(0, 10), (1, 4), (2, 1)])
		if mode == 0: # get random !advice
			return random.choice(storage.data['responses']['advice']['response'])
		elif mode == 1: # get a random !quote
			row = utils.pick_random_row(cur, """
				SELECT qid, quote, attrib_name, attrib_date
				FROM quotes
				WHERE NOT deleted
			""")
			if row is None:
				return None

			qid, quote, name, date = row

			quote_msg = "\"{quote}\"".format(quote=quote)
			if name:
				quote_msg += " —{name}".format(name=name)
			return quote_msg
		else: # get a random statistic
			show, game_id, stat = utils.weighted_choice(
				((show, game_id, stat), math.log(count))
				for show in storage.data['shows']
				for game_id in storage.data['shows'][show]['games']
				for stat in storage.data['stats']
				for count in [storage.data['shows'][show]['games'][game_id]['stats'].get(stat)]
				if count
			)
			game = storage.data['shows'][show]['games'][game_id]
			count = game['stats'][stat]
			display = storage.data['stats'][stat].get("singular", stat) if count == 1 else storage.data['stats'][stat].get("plural", stat + "s")
			return "%d %s for %s on %s" % (count, display, commands.game.game_name(game), commands.show.show_name(show))
	return None
