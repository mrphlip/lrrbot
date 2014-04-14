import irc
from lrrbot import bot
import storage
import utils

def game_name(game):
    return game.get("display", game["name"])

@bot.command("game")
@utils.throttle()
def current_game(lrrbot, conn, event, respond_to):
	game = lrrbot.get_current_game()
	if game is None:
		message = "Not currently playing any game"
	else:
		message = "Currently playing: %s" % game_name(game)
		if game.get("votes"):
			good = sum(game["votes"].values())
			message += " (rating %.0f%%)" % (100*good/len(game["votes"]))
	if lrrbot.game_override is not None:
		message += " (overridden)"
	conn.privmsg(respond_to, message)

@bot.command("game\s+(good|bad)")
def vote(lrrbot, conn, event, respond_to, vote):
	game = lrrbot.get_current_game()
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	nick = irc.client.NickMask(event.source).nick
	game.setdefault("votes", {})
	game["votes"][nick.lower()] = (vote.lower() == "good")
	storage.save()
	lrrbot.vote_update = game
	vote_respond(lrrbot, conn, event, respond_to, game)

@utils.throttle(60)
def vote_respond(lrrbot, conn, event, respond_to, game):
	if game and game.get("votes"):
		good = sum(game["votes"].values())
		count = len(game["votes"])
		
		conn.privmsg(respond_to, "Rating for %s is now %.0f%% (%d/%d)" % (game_name(game), 100*good/count, good, count))
	lrrbot.vote_update = None
bot.vote_respond = vote_respond

@bot.command("game\s+display\s+(.*?)")
@utils.mod_only
def set_game_name(lrrbot, conn, event, respond_to, name):
	game = lrrbot.get_current_game()
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game, if they are yell at them to update the stream")
		return
	game["display"] = name
	storage.save()
	conn.privmsg(respond_to, "OK, I'll start calling %(name)s \"%(display)s\"" % game)

@bot.command("game\s+override(?:\s+(.*?))?")
@utils.mod_only
def override_game(lrrbot, conn, event, respond_to, game):
	if game == "" or game.lower() == "off":
		lrrbot.game_override = None
		operation = "disabled"
	else:
		lrrbot.game_override = game
		operation = "enabled"
	lrrbot.get_current_game_real.reset_throttle()
	current_game.reset_throttle()
	game = lrrbot.get_current_game()
	message = "Override %s." % operation
	if game is None:
		message += "Not currently playing any game"
	else:
		message += "Currently playing: %s" % game_name(game)
	conn.privmsg(respond_to, message)

@bot.command("game\s+refresh")
@utils.mod_only
def refresh(lrrbot, conn, event, respond_to):
	lrrbot.get_current_game_real.reset_throttle()
	current_game.reset_throttle()
	current_game(lrrbot, conn, event, respond_to)

@bot.command("game\s+completed")
@utils.mod_only
@utils.throttle(30, notify=True)
def completed(lrrbot, conn, event, respond_to):
	game = lrrbot.get_current_game()
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	game.setdefault("stats", {}).setdefault("completed", 0)
	game["stats"]["completed"] += 1
	storage.save()
	conn.privmsg(respond_to, "%s added to the completed list" % game_name(game))
