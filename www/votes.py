import flask
import sqlalchemy
from www import server
from www import login
import common.rpc

@server.app.route('/votes')
@login.require_login
async def votes(session):
	await common.rpc.bot.connect()
	current_game_id = await common.rpc.bot.get_game_id()
	current_show_id = await common.rpc.bot.get_show_id()

	game_votes = server.db.metadata.tables["game_votes"]
	game_stats = server.db.metadata.tables["game_stats"]
	games = server.db.metadata.tables["games"]
	shows = server.db.metadata.tables["shows"]
	game_per_show_data = server.db.metadata.tables["game_per_show_data"]
	with server.db.engine.begin() as conn:
		votes_query = sqlalchemy.select([game_votes.c.game_id, game_votes.c.show_id, game_votes.c.vote]) \
			.where(game_votes.c.user_id == session['user']['id'])
		votes = {
			(show_id, game_id): vote
			for game_id, show_id, vote in conn.execute(votes_query)
		}

		all_games_ids = sqlalchemy.alias(sqlalchemy.select([game_votes.c.game_id, game_votes.c.show_id])
			.union(sqlalchemy.select([game_stats.c.game_id, game_stats.c.show_id])))
		all_games_query = sqlalchemy.select([
			all_games_ids.c.game_id,
			games.c.name,
			sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
			all_games_ids.c.show_id,
			shows.c.name,
		]).select_from(all_games_ids
			.join(games, games.c.id == all_games_ids.c.game_id)
			.join(shows, shows.c.id == all_games_ids.c.show_id)
			.outerjoin(game_per_show_data, (game_per_show_data.c.game_id == all_games_ids.c.game_id) & (game_per_show_data.c.show_id == all_games_ids.c.show_id))
		)

		shows = {}
		for game_id, game_name, game_display, show_id, show_name in conn.execute(all_games_query):
			try:
				shows[show_id]["games"][game_id] = {
					"id": game_id,
					"name": game_name,
					"display": game_display,
					"vote": votes.get((show_id, game_id)),
				}
			except KeyError:
				shows[show_id] = {
					"id": show_id,
					"name": show_name,
					"games": {
						game_id: {
							"id": game_id,
							"name": game_name,
							"display": game_display,
							"vote": votes.get((show_id, game_id)),
						}
					}
				}
		for show in shows.values():
			show["games"] = sorted(
				show["games"].values(),
				key=lambda game: (-(game['id'] == current_game_id and show["id"] == current_show_id), game['display'].upper()),
			)
		shows = sorted(
			(show for show in shows.values()),
			key=lambda show: (-(show['id'] == current_show_id and current_game_id is not None), show['name'].upper()),
		)

	return flask.render_template("votes.html", shows=shows, current_show_id=current_show_id, current_game_id=current_game_id, session=session)

@server.app.route('/votes/submit', methods=['POST'])
@login.require_login
def vote_submit(session):
	game_votes = server.db.metadata.tables["game_votes"]
	with server.db.engine.begin() as conn:
		conn.execute(game_votes.insert(postgresql_on_conflict="update"), {
			"game_id": int(flask.request.values['id']),
			"show_id": int(flask.request.values['show']),
			"user_id": session["user"]["id"],
			"vote": bool(int(flask.request.values['vote'])),
		})
	return flask.json.jsonify(success='OK', csrf_token=server.app.csrf_token())
