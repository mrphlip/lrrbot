import flask
import flask.json
import sqlalchemy
from common import game_data
from www import server
from www import login

import time

@server.app.route('/stats')
@login.with_session
def stats(session):
	shows = server.db.metadata.tables["shows"]
	stats = server.db.metadata.tables["stats"]
	game_stats = server.db.metadata.tables["game_stats"]
	game_per_show_data = server.db.metadata.tables["game_per_show_data"]
	games = server.db.metadata.tables["games"]
	game_votes = server.db.metadata.tables["game_votes"]
	disabled_stats = server.db.metadata.tables["disabled_stats"]

	string_id = flask.request.values.get("show")
	if string_id is not None:
		with server.db.engine.begin() as conn:
			id = conn.execute(sqlalchemy.select([shows.c.id]).where(shows.c.string_id == string_id)).first()
			if id is None:
				return flask.redirect(flask.url_for("stats"))
			else:
				return flask.redirect(flask.url_for("stats", id=id[0]), 301)

	show_id = flask.request.values.get("id")
	with server.db.engine.begin() as conn:
		shows_query = sqlalchemy.select([shows.c.id, shows.c.name]).order_by(shows.c.name)

		if show_id is None:
			graphdata_query = sqlalchemy.select([
				sqlalchemy.func.jsonb_build_array(shows.c.name, sqlalchemy.func.sum(game_stats.c.count))
			]).select_from(game_stats.join(shows, game_stats.c.show_id == shows.c.id)) \
				.where(game_stats.c.stat_id == stats.c.id) \
				.order_by(sqlalchemy.func.sum(game_stats.c.count).desc()) \
				.group_by(shows.c.name)

			votegames_query = None

			entries_subquery = sqlalchemy.alias(sqlalchemy.select([
				game_stats.c.show_id,
				game_stats.c.stat_id,
				sqlalchemy.func.sum(game_stats.c.count).label("count"),
			]).group_by(game_stats.c.show_id, game_stats.c.stat_id))

			entries_query = sqlalchemy.select([
				shows.c.id,
				shows.c.name,
				shows.c.name.concat(""), # SQLAlchemy removes duplicate columns
				entries_subquery.c.stat_id,
				entries_subquery.c.count,
				sqlalchemy.exists(sqlalchemy.select([1])
					.where(disabled_stats.c.show_id == shows.c.id)
					.where(disabled_stats.c.stat_id == entries_subquery.c.stat_id)
				).label("disabled"),
			]).select_from(entries_subquery
				.join(shows, shows.c.id == entries_subquery.c.show_id))

			missing_entries_query = None
		else:
			show_id = int(show_id)

			graphdata_query = sqlalchemy.select([
				sqlalchemy.func.jsonb_build_array(
					sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
					game_stats.c.count,
				)
			]).select_from(
				game_stats
					.join(games, games.c.id == game_stats.c.game_id)
					.outerjoin(game_per_show_data, (game_per_show_data.c.game_id == game_stats.c.game_id) & (game_per_show_data.c.show_id == show_id))
			) \
				.where(game_stats.c.show_id == show_id) \
				.where(game_stats.c.stat_id == stats.c.id) \
				.where(game_stats.c.count > 0) \
				.order_by(game_stats.c.count.desc())

			votegood = sqlalchemy.cast(
				sqlalchemy.func.sum(sqlalchemy.cast(game_votes.c.vote, sqlalchemy.Integer)),
				sqlalchemy.Numeric
			)
			ratings = sqlalchemy.alias(sqlalchemy.select([
				game_votes.c.game_id,
				votegood.label("votegood"),
				sqlalchemy.func.count(game_votes.c.vote).label("votecount"),
				(100 * votegood / sqlalchemy.func.count(game_votes.c.vote)).label("voteperc")
			]).where(game_votes.c.show_id == show_id).group_by(game_votes.c.game_id))

			votegames_query = sqlalchemy.select([
				games.c.name,
				sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
				ratings.c.votegood,
				ratings.c.votecount,
				ratings.c.voteperc,
			]).select_from(ratings
				.join(games, games.c.id == ratings.c.game_id)
				.outerjoin(game_per_show_data, (game_per_show_data.c.game_id == ratings.c.game_id) & (game_per_show_data.c.show_id == show_id))
			).order_by(ratings.c.voteperc.desc())

			entries_query = sqlalchemy.select([
				games.c.id,
				games.c.name,
				sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
				game_stats.c.stat_id,
				game_stats.c.count,
				sqlalchemy.exists(sqlalchemy.select([1])
					.where(disabled_stats.c.show_id == show_id)
					.where(disabled_stats.c.stat_id == game_stats.c.stat_id)
				).label("disabled"),
			]).select_from(game_stats
				.join(games, games.c.id == game_stats.c.game_id)
				.outerjoin(game_per_show_data, (game_per_show_data.c.game_id == game_stats.c.game_id) & (game_per_show_data.c.show_id == show_id))
			).where(game_stats.c.show_id == show_id)

			missing_entries_query = sqlalchemy.select([
				games.c.id,
				games.c.name,
				sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
			], distinct=True).select_from(game_votes
				.join(games, games.c.id == game_votes.c.game_id)
				.outerjoin(game_per_show_data, (game_per_show_data.c.game_id == game_votes.c.game_id) & (game_per_show_data.c.show_id == show_id))
			).where(game_votes.c.show_id == show_id) \
				.where(~sqlalchemy.exists(sqlalchemy.select([1]))
					.where(game_stats.c.game_id == game_votes.c.game_id)
					.where(game_stats.c.show_id == show_id)
				)

		stats_query = sqlalchemy.select([
			stats.c.id, game_data.stat_plural(stats, None),
			sqlalchemy.func.array(graphdata_query.as_scalar())
		])

		entries_query = sqlalchemy.alias(entries_query)
		totals_query = sqlalchemy.select([
			entries_query.c.stat_id,
			sqlalchemy.func.sum(entries_query.c.count),
			sqlalchemy.func.bool_and(entries_query.c.disabled),
		]).group_by(entries_query.c.stat_id)

		if show_id is None:
			# TODO: if stat is disabled on all shows, sort it to the right like on per-show pages.
			stats_query = stats_query.order_by(
				sqlalchemy.func.coalesce(
					sqlalchemy.select([sqlalchemy.func.sum(game_stats.c.count)])
						.where(game_stats.c.stat_id == stats.c.id)
						.as_scalar(),
					0
				).desc()
			)
		else:
			stats_query = stats_query.order_by(
				sqlalchemy.exists(sqlalchemy.select([1])
					.where(disabled_stats.c.show_id == show_id)
					.where(disabled_stats.c.stat_id == stats.c.id)
				),
				sqlalchemy.func.coalesce(
					sqlalchemy.select([sqlalchemy.func.sum(game_stats.c.count)])
						.where(game_stats.c.stat_id == stats.c.id)
						.where(game_stats.c.show_id == show_id)
						.as_scalar(),
					0
				).desc(),
			)

		stats = [
			{
				"statkey": id,
				"plural": plural,
				"graphdata": graphdata,
			}
			for id, plural, graphdata in conn.execute(stats_query)
		]

		all_shows = [
			{
				"id": id,
				"name": name,
			}
			for id, name in conn.execute(shows_query)
		]
		if votegames_query is not None:
			votegames = [
				{
					"name": name,
					"display": display_name,
					"voteperc": voteperc,
					"votegood": votegood,
					"votecount": votecount,
				}
				for name, display_name, votegood, votecount, voteperc in conn.execute(votegames_query)
			]
		else:
			votegames = None

		entries = {}
		for id, name, display, stat, count, disabled in conn.execute(entries_query):
			try:
				entries[id]['stats'][stat] = (count, disabled)
			except KeyError:
				entries[id] = {
					'name': name,
					'display': display,
					'stats': {
						stat: (count, disabled)
					}
				}
		if missing_entries_query is not None:
			for id, name, display in conn.execute(missing_entries_query):
				assert id not in entries
				entries[id] = {
					'name': name,
					'display': display,
					'stats': {}
				}
		entries = list(entries.values())

		totals = {
			id: (count, disabled)
			for id, count, disabled in conn.execute(totals_query)
		}

	return flask.render_template('stats.html', entries=entries, votegames=votegames, stats=stats, session=session, shows=all_shows, show_id=show_id, totals=totals)
