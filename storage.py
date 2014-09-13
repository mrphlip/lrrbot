import json
from config import config

"""
Data structure:

data = {
	'stats': { # Different statistics that are tracked
		'<stat-name>': { # the name as used in commands
			'singular': '<stat-name>', # For display - defaults to the same as the command
			'plural': '<stat-names>', # For display
		},
	},
	'shows': { # Shows we have tracked stats for
		'<id>': { # Show ID or '' for unknown show
                        'name': '<name>', # Name of this show
			'games': { # Games we have tracked stats for
				<id>: { # id is the Twitch game ID, or the game name for non-Twitch override games
				'name': '<name>', # Official game name as Twitch recognises it - to aid matching
				'display': '<display name>' # Display name, defaults to the same as name. For games with LRL nicknames
				'stats': {
					'<stat-name>': <count>,
				},
			},
		},
	},
	'spam_rules': [
		{
			're': '<regular expression>',
			'message': '<ban description>',
		},
	],
}

For example:
data = {
	'stats': {
		'death': {'plural': "deaths"},
	},
	'shows': {
		'': {
			'name': "Unknown",
			'games': {
				12345: {
					'name': "Example game",
					'display': "Funny name for example game",
					'stats': {
						'death': 17,
					},
				},
			},
		},
	},
	'spam_rules': [
		{
			're': '^I am a spambot!$',
			'message': "claims to be a spambot",
		},
	],
}
"""

def load():
	"""Read data from storage"""
	global data
	with open(config['datafile'], "r") as fp:
		data = json.load(fp)

def save():
	"""Save data to storage"""
	with open(config['datafile'], "w") as fp:
		# Save with pretty-printing enabled, as we probably want it to be editable
		json.dump(data, fp, indent=2, sort_keys=True)

def find_game(show, game):
	"""
	Look up a game by ID or by name, and keep game data up-to-date if names
	or IDs change in Twitch's database.
	"""
	if game is None:
		return None

	# Allow this to be called with just a string, for simplicity
	if isinstance(game, str):
		game = {'_id': game, 'name': game, 'is_override': True}

	games = data.setdefault('shows', {}).setdefault(show, {"name":show}).setdefault('games', {})

	# First try to find the game using the Twitch ID
	if str(game['_id']) in games:
		gamedata = games[str(game['_id'])]
		# Check if the name has changed
		if gamedata['name'] != game['name']:
			gamedata['name'] = game['name']
			save()
		gamedata['id'] = str(game['_id'])
		return gamedata

	# Next try to find the game using the name
	for gameid, gamedata in games.items():
		if gamedata['name'] == game['name']:
			# If this is from Twitch, fix the ID
			if not game.get('is_override'):
				del games[gameid]
				games[str(game['_id'])] = gamedata
				gamedata['id'] = str(game['_id'])
				save()
			else:
				gamedata['id'] = gameid
			return gamedata

	# Look up the game by display name as a fallback
	for gameid, gamedata in games.items():
		if 'display' in gamedata and gamedata['display'] == game['name']:
			# Don't try to keep things aligned here...
			gamedata['id'] = gameid
			return gamedata

	# This is a new game
	gamedata = {
		'id': str(game['_id']),
		'name': game['name'],
		'stats': {},
	}
	games[str(game['_id'])] = gamedata
	save()
	return gamedata

load()
