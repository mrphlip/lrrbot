#!/usr/bin/env python
import flask
import server
import login
import botinteract

@server.app.route('/votes')
@login.require_login
def votes(session):
	data = botinteract.get_data('games')
	current_game_id = botinteract.get_current_game()

	if current_game_id not in data:
		current_game_id = None
	games = [{
		"id": game_id,
		"name": game["name"],
		"display": game.get("display", game["name"]),
		"vote": game.get("votes", {}).get(session["user"]),
	} for game_id,game in data.items()]
	games.sort(key=lambda game:(1 if game['id'] == current_game_id else 2, game['display'].upper()))

	return flask.render_template("votes.html", games=games, current_game_id=current_game_id, session=session)

@server.app.route('/votes/submit', methods=['POST'])
@login.require_login
def vote_submit(session):
	botinteract.set_data(['games', flask.request.values['id'], 'votes', session['user']], bool(int(flask.request.values['vote'])))
	return flask.json.jsonify(success='OK')
