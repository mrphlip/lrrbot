#!/usr/bin/env python
import flask
import server
import login
import botinteract

@server.app.route('/votes')
@login.require_login
def votes(session):
	data = botinteract.get_data('shows')
	current_game_id = botinteract.get_current_game()
	current_show_id = botinteract.get_show()

	if current_game_id not in data[current_show_id]["games"]:
		current_game_id = None
	shows = [{
		"id": show_id,
		"name": show.get("name", show_id),
		"games": sorted([{
				"id": game_id,
				"name": game["name"],
				"display": game.get("display", game["name"]),
				"vote": game.get("votes", {}).get(session["user"]),
			    } for game_id,game in show['games'].items()],
			key=lambda game: (1 if game['id'] == current_game_id and show_id == current_show_id else 2, game['display'].upper()))
	} for show_id, show in data.items()]
	shows.sort(key=lambda show: (1 if show["id"] == current_show_id and current_game_id is not None else 2, show["name"].upper()))

	return flask.render_template("votes.html", shows=shows, current_show_id=current_show_id, current_game_id=current_game_id, session=session)

@server.app.route('/votes/submit', methods=['POST'])
@login.require_login
def vote_submit(session):
	botinteract.set_data(['shows', flask.request.values['show'], 'games', flask.request.values['id'], 'votes', session['user']], bool(int(flask.request.values['vote'])))
	return flask.json.jsonify(success='OK')
