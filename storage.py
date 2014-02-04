import json
import configparser

"""
Data structure:

data = {
	'stats': { # Different statistics that are tracked
		'<stat-name>': { # the name as used in commands
			'singular': '<stat-name>', # For display - defaults to the same as the command
			'plural': '<stat-names>', # For display
		},
	},
	'games': { # Games we have tracked stats for
		<id>: { # id is the Twitch game ID, or the game name for non-Twitch override games
			'name': '<name>', # Official game name as Twitch recognises it - to aid matching
			'display': '<display name>' # Display name, defaults to the same as name. For games with LRL nicknames
			'stats': {
				'<stat-name>': <count>,
			},
		},
	},
}

For example:
data = {
	'stats': {
		'death': {'plural': "deaths"},
	},
	'games': {
		12345: {
			'name': "Example game",
			'display': "Funny name for example game",
			'stats': {
				'death': 17,
			},
		},
	},
}
"""

def load():
	"""Read data from storage"""
	global data
	with open("data.json", "r") as fp:
		data = json.load(fp)

def save():
	"""Save data to storage"""
	with open("data.json", "w") as fp:
		# Save with pretty-printing enabled, as we probably want it to be editable
		json.dump(data, fp, indent=2)

def find_game(game):
	"""
	Look up a game by ID or by name, and keep game data up-to-date if names
	or IDs change in Twitch's database.
	"""
	if game is None:
		return None

	# Allow this to be called with just a string, for simplicity
	if isinstance(game, str):
		game = {'_id': game, 'name': game, 'is_override': True}

	# First try to find the game using the Twitch ID
	if str(game['_id']) in data['games']:
		gamedata = data['games'][str(game['_id'])]
		# Check if the name has changed
		if gamedata['name'] != game['name']:
			gamedata['name'] = game['name']
			save()
		return gamedata

	# Next try to find the game using the name
	for gameid, gamedata in data['games'].items():
		if gamedata['name'] == game['name']:
			# If this is from Twitch, fix the ID
			if not game.get('is_override'):
				del data['games'][gameid]
				data['games'][str(game['_id'])] = gamedata
				save()
			return gamedata

	# Look up the game by display name as a fallback
	for gameid, gamedata in data['games'].items():
		if 'display' in gamedata and gamedata['display'] == game['name']:
			# Don't try to keep things aligned here...
			return gamedata

	# This is a new game
	gamedata = {
		'name': game['name'],
		'stats': {},
	}
	data['games'][str(game['_id'])] = gamedata
	save()
	return gamedata

load()
