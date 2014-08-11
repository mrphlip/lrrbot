from lrrbot import bot
import utils
import storage
import commands.static, commands.explain

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
		doc = utils.parse_docstring(command.__doc__)
		for cmd in doc.walk():
			if cmd.get_content_maintype() == "multipart":
				continue
			if cmd.get_all("command") is None:
				continue
			ret += [{
				"aliases": cmd.get_all("command"),
				"mod-only": cmd.get("mod-only") == "true",
				"throttled": bind(cmd.get("throttled"), int),
				"literal-response": cmd.get("literal-response") == "true",
				"description": cmd.get_payload(),
			}]
	return ret
