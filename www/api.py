from www import server
from www import botinteract
from common.config import config
import datetime

@server.app.route("/api/stats/<stat>")
def api_stats(stat):
	game_id = botinteract.get_current_game()
	if game_id is None:
		return "-"
	show = botinteract.get_show()
	count = botinteract.get_data(["shows", show, "games", game_id, "stats", stat])
	if not count:
		count = 0
	return str(count)

@server.app.route("/api/stormcount")
def stormcount():
	today = datetime.datetime.now(config["timezone"]).date().toordinal()
	data = botinteract.get_data("storm")
	if data.get("date") != today:
		return "0"
	return str(data.get("count", 0))

@server.app.route("/api/next")
def nextstream():
	return botinteract.nextstream()

@server.app.route("/api/votes")
def api_votes():
	game_id = botinteract.get_current_game()
	if game_id is None:
		return "-"
	show = botinteract.get_show()
	data = botinteract.get_data(["shows", show, "games", game_id, "votes"])
	count = len(data)
	good = sum(data.values())
	return "%.0f%% (%d/%d)" % (100*good/count, good, count)

@server.app.route("/api/show/<show>")
def set_show(show):
	if show == "off":
		show = ""
	response = botinteract.set_show(show)
	if response["status"] == "OK":
		return ""
	return response["status"]

@server.app.route("/api/game")
def get_game():
	return botinteract.get_current_game_name()

@server.app.route("/api/show")
def get_show():
	return botinteract.get_show()
