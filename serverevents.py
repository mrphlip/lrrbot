from lrrbot import bot, log
import utils
import storage
import commands.static, commands.explain, commands.show
import random
import re
import googlecalendar

@bot.server_event()
def current_game(lrrbot, user, data):
	game = lrrbot.get_current_game()
	if game:
		return game['id']
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
	bind = lambda maybe, f: f(maybe) if maybe is not None else None
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
				"throttled": bind(cmd.get("throttled"), int),
				"literal-response": cmd.get("literal-response") == "true",
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
