import flask
import flask.json
from www import server
from www import login
from www import botinteract

@server.app.route('/stats')
@login.with_session
def stats(session):
	show_id = flask.request.values.get("show")
	shows = botinteract.get_data(["shows"])
	if show_id is not None:
		show_id = show_id.lower()
		entries = shows.get(show_id, {}).get("games", {})
		for game in entries.values():
			game["show_id"] = show_id
	else:
		entries = {}
		for show_id, show in shows.items():
			show_name = show.get("name", show_id)
			entry = {
				"id": show_id,
				"name": show_name,
				"stats": {
				},
			}
			for game in show['games'].values():
				for stat, value in game['stats'].items():
					try:
						entry["stats"][stat] += value
					except KeyError:
						entry["stats"][stat] = value
			entries[show_id] = entry
		show_id = None
	shows = [{"name": show.get("name", name), "id": name} for name, show in shows.items()]
	shows = sorted(shows, key=lambda show: show["name"].lower())
	stats = botinteract.get_data(["stats"])
	# Calculate totals
	for statkey, stat in stats.items():
		stat['total'] = sum(g.get('stats',{}).get(statkey,0) for g in entries.values())
	# Make our lives easier in the template - make sure all our defaults exist, and turn our major dicts into lists
	for gamekey, game in entries.items():
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
	entries = list(entries.values())
	entries.sort(key=lambda g: g['display'].upper())
	if show_id is not None:
		votegames = [g for g in entries if g['votecount']]
		votegames.sort(key=lambda g: -g['voteperc'])
	else:
		votegames = None
	stats = list(stats.values())
	stats.sort(key=lambda s: -s['total'])
	# Calculate graph datasets
	for stat in stats:
		stat['graphdata'] = [
			(game["display"], game['stats'][stat['statkey']])
			for game in entries
			if game['stats'][stat['statkey']]
		]
		stat['graphdata'].sort(key=lambda pt:-pt[1])

	return flask.render_template('stats.html', entries=entries, votegames=votegames, stats=stats, session=session, shows=shows, show_id=show_id)
