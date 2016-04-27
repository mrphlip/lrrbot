import irc.client
import sqlalchemy

from common import game_data

from common.sqlalchemy_pg95_upsert import DoUpdate
import lrrbot.decorators
from lrrbot import storage
from lrrbot.main import bot

with bot.engine.begin() as conn:
	stats = [id for id, in conn.execute(sqlalchemy.select([bot.metadata.tables["stats"].c.string_id]))]
	re_stats = "|".join(stats)

def stat_increment(lrrbot, conn, game_id, show_id, stat_id, n):
	game_stats = lrrbot.metadata.tables["game_stats"]
	do_update = DoUpdate([game_stats.c.game_id, game_stats.c.show_id, game_stats.c.stat_id]) \
		.set(count=game_stats.c.count + sqlalchemy.literal_column("EXCLUDED.count"))
	conn.execute(game_stats.insert(postgresql_on_conflict=do_update), {
		"game_id": game_id,
		"show_id": show_id,
		"stat_id": stat_id,
		"count": n,
	})

def stat_set(lrrbot, conn, game_id, show_id, stat_id, n):
	game_stats = lrrbot.metadata.tables["game_stats"]
	conn.execute(game_stats.insert(postgresql_on_conflict="update"), {
		"game_id": game_id,
		"show_id": show_id,
		"stat_id": stat_id,
		"count": n,
	})

def stat_print(lrrbot, conn, respond_to, pg_conn, game_id, show_id, stat_id, with_emote=False):
	games = lrrbot.metadata.tables["games"]
	game_per_show_data = lrrbot.metadata.tables["game_per_show_data"]
	game_stats = lrrbot.metadata.tables["game_stats"]
	stats = lrrbot.metadata.tables["stats"]
	shows = lrrbot.metadata.tables["shows"]

	res = pg_conn.execute(
		sqlalchemy.select([
			sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
			game_data.stat_plural(stats, game_stats.c.count),
			game_stats.c.count,
			shows.c.name,
			stats.c.emote,
		]).select_from(
			game_stats
				.join(games, games.c.id == game_stats.c.game_id)
				.outerjoin(game_per_show_data, (game_per_show_data.c.game_id == game_stats.c.game_id)
					& (game_per_show_data.c.show_id == game_stats.c.show_id))
				.join(stats, stats.c.id == game_stats.c.stat_id)
				.join(shows, shows.c.id == game_stats.c.show_id)
		)
		.where(game_stats.c.game_id == game_id)
		.where(game_stats.c.show_id == show_id)
		.where(game_stats.c.stat_id == stat_id)
	).first()
	if res is None:
		res = pg_conn.execute(
			sqlalchemy.select([
				sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
				game_data.stat_plural(stats, 0),
				0,
				shows.c.name,
				stats.c.emote,
			]).select_from(
				games
					.join(shows, shows.c.id == show_id)
					.join(stats, stats.c.id == stat_id)
					.outerjoin(game_per_show_data, (game_per_show_data.c.game_id == games.c.id) & (game_per_show_data.c.show_id == shows.c.id))
			)
				.where(games.c.id == game_id)
				.where(shows.c.id == show_id)
				.where(stats.c.id == stat_id)
		).first()
	game, stat, count, show, emote = res
	if with_emote and emote is not None:
		emote = emote + " "
	else:
		emote = ""
	conn.privmsg(respond_to, "%s%d %s for %s on %s" % (emote, count, stat, game, show))

@bot.command("(%s)" % re_stats)
@lrrbot.decorators.public_only
@lrrbot.decorators.throttle(30, notify=lrrbot.decorators.Visibility.PUBLIC, params=[4], modoverride=False, allowprivate=False)
def increment(lrrbot, conn, event, respond_to, stat):
	stat = stat.lower()

	game_id = lrrbot.get_game_id()
	if game_id is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	show_id = lrrbot.get_show_id()

	stats = lrrbot.metadata.tables["stats"]
	disabled_stats = lrrbot.metadata.tables["disabled_stats"]
	with lrrbot.engine.begin() as pg_conn:
		stat_id, = pg_conn.execute(sqlalchemy.select([stats.c.id]).where(stats.c.string_id == stat)).first()
		disabled, = pg_conn.execute(sqlalchemy.select([sqlalchemy.exists(sqlalchemy.select([1])
			.where(disabled_stats.c.show_id == show_id)
			.where(disabled_stats.c.stat_id == stat_id)
		)])).first()
		if disabled:
			source = irc.client.NickMask(event.source)
			conn.privmsg(source.nick, "This stat has been disabled.")
			return

		stat_increment(lrrbot, pg_conn, game_id, show_id, stat_id, 1)
		stat_print(lrrbot, conn, respond_to, pg_conn, game_id, show_id, stat_id, with_emote=True)

@bot.command("(%s) add( \d+)?" % re_stats)
@lrrbot.decorators.mod_only
def add(lrrbot, conn, event, respond_to, stat, n):
	stat = stat.lower()
	n = 1 if n is None else int(n)

	game_id = lrrbot.get_game_id()
	if game_id is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	show_id = lrrbot.get_show_id()

	stats = lrrbot.metadata.tables["stats"]
	with lrrbot.engine.begin() as pg_conn:
		stat_id, = pg_conn.execute(sqlalchemy.select([stats.c.id]).where(stats.c.string_id == stat)).first()
		stat_increment(lrrbot, pg_conn, game_id, show_id, stat_id, n)
		stat_print(lrrbot, conn, respond_to, pg_conn, game_id, show_id, stat_id)

@bot.command("(%s) remove( \d+)?" % re_stats)
@lrrbot.decorators.mod_only
def remove(lrrbot, conn, event, respond_to, stat, n):
	stat = stat.lower()
	n = 1 if n is None else int(n)

	game_id = lrrbot.get_game_id()
	if game_id is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	show_id = lrrbot.get_show_id()

	stats = lrrbot.metadata.tables["stats"]
	with lrrbot.engine.begin() as pg_conn:
		stat_id, = pg_conn.execute(sqlalchemy.select([stats.c.id]).where(stats.c.string_id == stat)).first()
		stat_increment(lrrbot, pg_conn, game_id, show_id, stat_id, -n)
		stat_print(lrrbot, conn, respond_to, pg_conn, game_id, show_id, stat_id)

@bot.command("(%s) set (\d+)" % re_stats)
@lrrbot.decorators.mod_only
def stat_set_(lrrbot, conn, event, respond_to, stat, n):
	stat = stat.lower()
	n = 1 if n is None else int(n)

	game_id = lrrbot.get_game_id()
	if game_id is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	show_id = lrrbot.get_show_id()

	stats = lrrbot.metadata.tables["stats"]
	with lrrbot.engine.begin() as pg_conn:
		stat_id, = pg_conn.execute(sqlalchemy.select([stats.c.id]).where(stats.c.string_id == stat)).first()
		stat_set(lrrbot, pg_conn, game_id, show_id, stat_id, n)
		stat_print(lrrbot, conn, respond_to, pg_conn, game_id, show_id, stat_id)

@bot.command("(%s)count" % re_stats)
@lrrbot.decorators.throttle(params=[4])
def get_stat(lrrbot, conn, event, respond_to, stat):
	stat = stat.lower()
	game_id = lrrbot.get_game_id()
	if game_id is None:
		conn.privmsg(respond_to, "Not currently playing any game")
		return
	show_id = lrrbot.get_show_id()

	stats = lrrbot.metadata.tables["stats"]
	with lrrbot.engine.begin() as pg_conn:
		stat_print(lrrbot, conn, respond_to, pg_conn, game_id, show_id,
			sqlalchemy.select([stats.c.id]).where(stats.c.string_id == stat))

@bot.command("total(%s)s?" % re_stats)
@lrrbot.decorators.throttle(params=[4])
def printtotal(lrrbot, conn, event, respond_to, stat):
	stat = stat.lower()
	game_stats = lrrbot.metadata.tables["game_stats"]
	stats = lrrbot.metadata.tables["stats"]
	with lrrbot.engine.begin() as pg_conn:
		stat_id, = pg_conn.execute(sqlalchemy.select([stats.c.id]).where(stats.c.string_id == stat)).first()
		count_query = sqlalchemy.alias(sqlalchemy.select([sqlalchemy.func.sum(game_stats.c.count).label("count")])
			.where(game_stats.c.stat_id == stat_id))
		count, stat = pg_conn.execute(
			sqlalchemy.select([
				count_query.c.count,
				sqlalchemy.case(
					{1: sqlalchemy.func.coalesce(stats.c.singular, stats.c.string_id)},
					value=count_query.c.count,
					else_=sqlalchemy.func.coalesce(stats.c.plural,
						sqlalchemy.func.coalesce(stats.c.singular, stats.c.string_id).concat("s")
					)
				)
			])
			.where(stats.c.id == stat_id)
		).first()
		conn.privmsg(respond_to, "%d total %s" % (count, stat))
