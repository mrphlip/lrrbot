#!/usr/bin/env python
import flask
import flask.json
import server
import login
import botinteract

@server.app.route('/stats')
@login.with_session
def stats(session):
	show_id = flask.request.values.get("show")
	shows = botinteract.get_data(["shows"])
	if show_id is not None:
		show_id = show_id.lower()
		games = shows.get(show_id, {}).get("games", {})
		for game in games.values():
		    game["show_id"] = show_id
	else:
		games = {}
		for show_id, show in shows.items():
			show_name = show.get("display", show_id)
			for game_id, game in show['games'].items():
				game["show_id"] = show_id
				if "display" in game:
					game["display"] = "%s (%s)" % (game["display"], show_name)
				else:
					game["name"] = "%s (%s)" % (game["name"], show_name)
				games["%s-%s" % (show_id, game_id)] = game
		show_id = None
	shows = [{"name": show.get("display", name), "id": name} for name, show in shows.items()]
	shows = sorted(shows, key=lambda show: show["name"].lower())
	stats = botinteract.get_data(["stats"])
	# Calculate totals
	for statkey, stat in stats.items():
		stat['total'] = sum(g.get('stats',{}).get(statkey,0) for g in games.values())
	# Make our lives easier in the template - make sure all our defaults exist, and turn our major dicts into lists
	for gamekey, game in games.items():
		game.setdefault('display', game['name'])
		game.setdefault('stats', {})
		for statkey in stats.keys():
			game['stats'].setdefault(statkey, 0)
		game.setdefault('gamekey', gamekey)
		game.setdefault('votes', {})
		game['votecount'] = len(game['votes'])
		game['votegood'] = sum(game['votes'].values())
		if game['votecount']:
			game['voteperc'] = 100.0 * game['votegood'] / game['votecount']
		else:
			game['voteperc'] = 0.0
	for statkey, stat in stats.items():
		stat.setdefault('singular', statkey)
		stat.setdefault('statkey', statkey)
	games = list(games.values())
	games.sort(key=lambda g: g['display'].upper())
	votegames = [g for g in games if g['votecount']]
	votegames.sort(key=lambda g: -g['voteperc'])
	stats = list(stats.values())
	stats.sort(key=lambda s: -s['total'])
	# Calculate graph datasets
	for stat in stats:
		stat['graphdata'] = [(game['display'], game['stats'][stat['statkey']]) for game in games if game['stats'][stat['statkey']]]
		stat['graphdata'].sort(key=lambda pt:-pt[1])

	return flask.render_template('stats.html', games=games, votegames=votegames, stats=stats, session=session, shows=shows, show_id=show_id)
