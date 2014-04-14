from lrrbot import bot
import storage
import utils
from commands.game import completed, game_name

def stat_update(lrrbot, stat, n, set_=False):
	game = lrrbot.get_current_game()
	if game is None:
		return None
	game.setdefault("stats", {}).setdefault(stat, 0)
	if set_:
		game["stats"][stat] = n
	else:
		game["stats"][stat] += n
	storage.save()
	return game

@utils.throttle(30, notify=True, params=[4])
def increment(lrrbot, conn, event, respond_to, stat):
	stat = stat.lower()
	if stat == "completed":
		completed(lrrbot, conn, event, respond_to)
		return
	game = stat_update(lrrbot, stat, 1)
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	stat_print.__wrapped__(lrrbot, conn, event, respond_to, stat, game, with_emote=True)

@utils.mod_only
def add(lrrbot, conn, event, respond_to, stat, n):
	n = 1 if n is None else int(n)
	game = stat_update(lrrbot, stat, n)
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	stat_print.__wrapped__(lrrbot, conn, event, respond_to, stat, game)

@utils.mod_only
def remove(lrrbot, conn, event, respond_to, stat, n):
	n = 1 if n is None else int(n)
	game = stat_update(lrrbot, stat, -n)
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	stat_print.__wrapped__(lrrbot, conn, event, respond_to, stat, game)

@utils.mod_only
def stat_set(lrrbot, conn, event, respond_to, stat, n):
	n = 1 if n is None else int(n)
	game = stat_update(lrrbot, stat, n, True)
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	stat_print.__wrapped__(lrrbot, conn, event, respond_to, stat, game)

@utils.throttle(params=[4])
def stat_print(lrrbot, conn, event, respond_to, stat, game=None, with_emote=False):
	print("stat_print:", stat)
	if game is None:
		game = lrrbot.get_current_game()
		if game is None:
			conn.privmsg(respond_to, "Not currently playing any game")
			return
	count = game.get("stats", {}).get(stat, 0)
	countT = sum(game.get("stats", {}).get(stat, 0) for game in storage.data["games"].values())
	stat_details = storage.data["stats"][stat]
	display = stat_details.get("singular", stat) if count == 1 else stat_details.get("plural", stat + "s")
	if with_emote and stat_details.get("emote"):
		emote = stat_details["emote"] + " "
	else:
		emote = ""
	conn.privmsg(respond_to, "%s%d %s for %s" % (emote, count, display, game_name(game)))
	if countT == 1000:
		conn.privmsg(respond_to, "Watch and pray for another %d %s!" % (countT, display))

@utils.throttle(params=[4])
def printtotal(lrrbot, conn, event, respond_to, stat):
	count = sum(game.get("stats", {}).get(stat, 0) for game in storage.data["games"].values())
	display = storage.data["stats"][stat]
	display = display.get("singular", stat) if count == 1 else display.get("plural", stat + "s")
	conn.privmsg(respond_to, "%d total %s" % (count, display))

re_stats = "|".join(storage.data["stats"])

bot.add_command("(%s)" % re_stats, increment)
bot.add_command("(%s)\s+add(?:\s+(\d+))?" % re_stats, add)
bot.add_command("(%s)\s+remove(?:\s+(\d+))?" % re_stats, remove)
bot.add_command("(%s)\s+set\s+(\d+)" % re_stats, stat_set)
bot.add_command("(%s)count" % re_stats, stat_print)
bot.add_command("total(%s)" % re_stats, printtotal)
