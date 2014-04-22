import irc
from lrrbot import bot
import storage
import utils

def game_name(game):
    return game.get("display", game["name"])

@bot.command("game")
@utils.throttle()
def current_game(lrrbot, conn, event, respond_to):
	"""
	Command: !game

	Post the game currently being played.
	"""
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

@bot.command("game (good|bad)")
def vote(lrrbot, conn, event, respond_to, vote):
	"""
	Command: !game good
	Command: !game bad

	Declare whether you believe this game is entertaining to watch
	on-stream. Voting a second time replaces your existing vote. The
	host may heed this or ignore it at their choice. Probably ignore
	it.
	"""
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

@utils.throttle(60, log=False)
def vote_respond(lrrbot, conn, event, respond_to, game):
	if game and game.get("votes"):
		good = sum(game["votes"].values())
		count = len(game["votes"])
		
		conn.privmsg(respond_to, "Rating for %s is now %.0f%% (%d/%d)" % (game_name(game), 100*good/count, good, count))
	lrrbot.vote_update = None
bot.vote_respond = vote_respond

@bot.command("game display (.*?)")
@utils.mod_only
def set_game_name(lrrbot, conn, event, respond_to, name):
	"""
	Command: !game display NAME

	eg. !game display Resident Evil: Man Fellating Giraffe

	Change the display name of the current game to NAME.
	"""
	game = lrrbot.get_current_game()
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game, if they are yell at them to update the stream")
		return
	game["display"] = name
	storage.save()
	conn.privmsg(respond_to, "OK, I'll start calling %(name)s \"%(display)s\"" % game)

@bot.command("game override (.*?)")
@utils.mod_only
def override_game(lrrbot, conn, event, respond_to, game):
	"""
	Command: !game override NAME
	
	eg: !game override Prayer Warriors: A.O.F.G.
	
	Override what game is being played (eg when the current game isn't in the Twitch database)

	--command
	Command: !game override off
	
	Disable override, go back to getting current game from Twitch stream settings.
	Should the crew start regularly playing a game called "off", I'm sure we'll figure something out.
	"""
	if game == "" or game.lower() == "off":
		lrrbot.game_override = None
		operation = "disabled"
	else:
		lrrbot.game_override = game
		operation = "enabled"
	lrrbot.get_current_game_real.reset_throttle()
	current_game.reset_throttle()
	game = lrrbot.get_current_game()
	message = "Override %s. " % operation
	if game is None:
		message += "Not currently playing any game"
	else:
		message += "Currently playing: %s" % game_name(game)
	conn.privmsg(respond_to, message)

@bot.command("game refresh")
@utils.mod_only
def refresh(lrrbot, conn, event, respond_to):
	"""
	Command: !game refresh

	Force a refresh of the current Twitch game (normally this is updated at most once every 15 minutes)
	"""
	lrrbot.get_current_game_real.reset_throttle()
	current_game.reset_throttle()
	current_game(lrrbot, conn, event, respond_to)

@bot.command("game completed")
@utils.mod_only
@utils.throttle(30, notify=True)
def completed(lrrbot, conn, event, respond_to):
	"""
	Command: !game completed

	Mark a game as having been completed.
	"""
	game = lrrbot.get_current_game()
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	game.setdefault("stats", {}).setdefault("completed", 0)
	game["stats"]["completed"] += 1
	storage.save()
	conn.privmsg(respond_to, "%s added to the completed list" % game_name(game))
