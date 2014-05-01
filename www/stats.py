#!/usr/bin/env python
import flask
import flask.json
import server
import login
import botinteract

@server.app.route('/stats')
@login.with_session
def stats(session):
	data = botinteract.get_data([])

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

	return flask.render_template('stats.html', games=games, votegames=votegames, stats=stats, session=session)
