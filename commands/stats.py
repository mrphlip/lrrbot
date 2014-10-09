from lrrbot import bot
import storage
import utils
from commands.game import completed, game_name
from commands.show import show_name

re_stats = "|".join(storage.data["stats"])

def stat_update(lrrbot, stat, n, set_=False):
	game = lrrbot.get_current_game(readonly=False)
	if game is None:
		return None
	game.setdefault("stats", {}).setdefault(stat, 0)
	if set_:
		game["stats"][stat] = n
	else:
		game["stats"][stat] += n
	storage.save()
	return game

@bot.command("(%s)" % re_stats)
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

@bot.command("(%s) add( \d+)?" % re_stats)
@utils.mod_only
def add(lrrbot, conn, event, respond_to, stat, n):
	stat = stat.lower()
	n = 1 if n is None else int(n)
	game = stat_update(lrrbot, stat, n)
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	stat_print.__wrapped__(lrrbot, conn, event, respond_to, stat, game)

@bot.command("(%s) remove( \d+)?" % re_stats)
@utils.mod_only
def remove(lrrbot, conn, event, respond_to, stat, n):
	stat = stat.lower()
	n = 1 if n is None else int(n)
	game = stat_update(lrrbot, stat, -n)
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	stat_print.__wrapped__(lrrbot, conn, event, respond_to, stat, game)

@bot.command("(%s) set (\d+)" % re_stats)
@utils.mod_only
def stat_set(lrrbot, conn, event, respond_to, stat, n):
	stat = stat.lower()
	n = 1 if n is None else int(n)
	game = stat_update(lrrbot, stat, n, True)
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	stat_print.__wrapped__(lrrbot, conn, event, respond_to, stat, game)

@bot.command("(%s)count" % re_stats)
@utils.throttle(params=[4])
def stat_print(lrrbot, conn, event, respond_to, stat, game=None, with_emote=False):
	stat = stat.lower()
	if game is None:
		game = lrrbot.get_current_game()
		if game is None:
			conn.privmsg(respond_to, "Not currently playing any game")
			return
	count = game.get("stats", {}).get(stat, 0)
	show = lrrbot.show_override or lrrbot.show
	games = storage.data.get("shows", {}).get(show, {}).get("games", {})
	countT = sum(game.get("stats", {}).get(stat, 0) for game in games.values())
	stat_details = storage.data["stats"][stat]
	display = stat_details.get("singular", stat) if count == 1 else stat_details.get("plural", stat + "s")
	if with_emote and stat_details.get("emote"):
		emote = stat_details["emote"] + " "
	else:
		emote = ""
	conn.privmsg(respond_to, "%s%d %s for %s on %s" % (emote, count, display, game_name(game), show_name(show)))
	if countT == 1000:
		conn.privmsg(respond_to, "Watch and pray for another %d %s!" % (countT, display))
	if countT == 2500:
		conn.privmsg(respond_to, "For hitting this milestone here's some code drop, Fez: 63BT5-GQ72Z-6L068 Mark of the Ninja: C03YW-YX0CA-IYC85 FTL: 5539N-PAREC-J4YGM Bastion: TE4M2-A5V64-BITNV" % (countT, display))

@bot.command("total(%s)s?" % re_stats)
@utils.throttle(params=[4])
def printtotal(lrrbot, conn, event, respond_to, stat):
	stat = stat.lower()
	count = 0
	for show in storage.data.get("shows", {}).values():
	    count += sum(game.get("stats", {}).get(stat, 0) for game in show.get("games", {}).values())
	display = storage.data["stats"][stat]
	display = display.get("singular", stat) if count == 1 else display.get("plural", stat + "s")
	conn.privmsg(respond_to, "%d total %s" % (count, display))
