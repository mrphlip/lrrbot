#!/usr/bin/env python
import flask
import flask.json
import server

STORAGE = "../data.json"

@server.app.route('/stats')
def stats():
	with open(STORAGE, "r") as fp:
		data = flask.json.load(fp)

	games = data['games']
	stats = data['stats']
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
	for statkey, stat in stats.items():
		stat.setdefault('singular', statkey)
		stat.setdefault('statkey', statkey)
	games = list(games.values())
	games.sort(key=lambda g: g['display'].upper())
	stats = list(stats.values())
	stats.sort(key=lambda s: -s['total'])
	# Calculate graph datasets
	for stat in stats:
		stat['graphdata'] = [(game['display'], game['stats'][stat['statkey']]) for game in games if game['stats'][stat['statkey']]]
		stat['graphdata'].sort(key=lambda pt:-pt[1])

	return flask.render_template('stats.html', games=games, stats=stats)
