import asyncio

from common import utils
from lrrbot import storage
from lrrbot.main import bot
from lrrbot.commands.game import completed, game_name
from lrrbot.commands.show import show_name

re_stats = "|".join(storage.data["stats"])

@asyncio.coroutine
def stat_update(lrrbot, stat, n, set_=False):
	game = yield from lrrbot.get_current_game(readonly=False)
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
@utils.public_only
@utils.throttle(30, notify=utils.Visibility.PUBLIC, params=[4], modoverride=False, allowprivate=False)
@asyncio.coroutine
def increment(lrrbot, conn, event, respond_to, stat):
	stat = stat.lower()
	if stat == "completed":
		yield from completed(lrrbot, conn, event, respond_to)
		return
	game = yield from stat_update(lrrbot, stat, 1)
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	yield from stat_print(lrrbot, conn, event, respond_to, stat, game, with_emote=True)

@bot.command("(%s) add( \d+)?" % re_stats)
@utils.mod_only
@asyncio.coroutine
def add(lrrbot, conn, event, respond_to, stat, n):
	stat = stat.lower()
	n = 1 if n is None else int(n)
	game = yield from stat_update(lrrbot, stat, n)
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	yield from stat_print(lrrbot, conn, event, respond_to, stat, game)

@bot.command("(%s) remove( \d+)?" % re_stats)
@utils.mod_only
@asyncio.coroutine
def remove(lrrbot, conn, event, respond_to, stat, n):
	stat = stat.lower()
	n = 1 if n is None else int(n)
	game = yield from stat_update(lrrbot, stat, -n)
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	yield from stat_print(lrrbot, conn, event, respond_to, stat, game)

@bot.command("(%s) set (\d+)" % re_stats)
@utils.mod_only
@asyncio.coroutine
def stat_set(lrrbot, conn, event, respond_to, stat, n):
	stat = stat.lower()
	n = 1 if n is None else int(n)
	game = yield from stat_update(lrrbot, stat, n, True)
	if game is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	yield from stat_print(lrrbot, conn, event, respond_to, stat, game)

@bot.command("(%s)count" % re_stats)
@utils.throttle(params=[4])
@asyncio.coroutine
def get_stat(lrrbot, conn, event, respond_to, stat):
	yield from stat_print(lrrbot, conn, event, respond_to, stat)

@asyncio.coroutine
def stat_print(lrrbot, conn, event, respond_to, stat, game=None, with_emote=False):
	stat = stat.lower()
	if game is None:
		game = yield from lrrbot.get_current_game()
		if game is None:
			conn.privmsg(respond_to, "Not currently playing any game")
			return
	count = game.get("stats", {}).get(stat, 0)
	show = lrrbot.show_override or lrrbot.show
	stat_details = storage.data["stats"][stat]
	display = stat_details.get("singular", stat) if count == 1 else stat_details.get("plural", stat + "s")
	if with_emote and stat_details.get("emote"):
		emote = stat_details["emote"] + " "
	else:
		emote = ""
	conn.privmsg(respond_to, "%s%d %s for %s on %s" % (emote, count, display, game_name(game), show_name(show)))

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
