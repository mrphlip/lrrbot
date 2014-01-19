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
	try:
		fp = open("data.json", "r")
	except IOError:
		load_fallback()
	else:
		with fp:
			data = json.load(fp)

def save():
	"""Save data to storage"""
	with open("data.json", "w") as fp:
		# Save with pretty-printing enabled, as we probably want it to be editable
		json.dump(data, fp, indent=2)

def load_fallback():
	"""
	Load data from old Game.ini storage

	More data and logic can be added here to facilitate loading data from the old
	lrrbot, but once the new bot is established, this function will no longer need
	to be maintained, and can probably be deleted.
	"""
	global data

	# First, set up some basic structure, and map names back to the ini file
	data = {
		'stats': {
			'death': {
				'plural': "deaths",
				'ininame': "deaths",
			},
			'diamond': {
				'plural': "diamonds",
				'ininame': "diamonds",
			},
			'flunge': {
				'plural': "flunges",
				'ininame': "flunge",
			},
		},
		'games': {
			'15921': {
				'name': "Prince of Persia: Warrior Within",
				'ininame': "PoP:WarriorWithin",
			},
			'15442': {
				'name': "Shin Megami Tensei: Nocturne",
				'ininame': "SMT:Nocturne",
			},
			'313553': {
				'name': "XCOM: Enemy Within",
				'ininame': "XCOM",
			},
			'27471': {
				'name': "Minecraft",
				'ininame': "minecraft",
			},
			'2748': {
				'name': "Magic: The Gathering",
				'ininame': "MTG",
			},
			'33437': {
				'name': "Resident Evil 6",
				'display': "Resident Evil: Man Fellating Giraffe",
				'ininame': "RE6-Man_Fellating_Giraffe",
			},
			'Dark': { # Dark still doesn't appear to be in the Twitch game list
				'name': "Dark",
				'ininame': "dark",
			},
			'10775': {
				'name': "S.T.A.L.K.E.R.: Shadow of Chernobyl",
				'ininame': "STALKER_ShadowsOfChernobyl",
			},
			'666': {
				'name': "Metal Gear 2: Solid Snake",
				'ininame': "MG2:SS",
			},
			"Prayer Warriors: A.o.f.G.": { # This game is not now, and probably will never be, in the Twitch game list
				'name': "Prayer Warriors: A.o.f.G.",
				'ininame': "Prayer_Warriors",
			},
		},
	}

	# Next, load data from Game.ini
	ini = configparser.ConfigParser()
	ini.read("Game.ini")
	# Group them by title
	inisections = {ini.get(sect, 'Title'): dict(ini.items(sect)) for sect in ini.sections()}

	# Now populate the stats across
	for game in data['games'].values():
		inigame = inisections.get(game['ininame'], {})
		game['stats'] = {}
		for statkey, statvals in data['stats'].items():
			if statvals['ininame'] in inigame:
				game['stats'][statkey] = int(inigame[statvals['ininame']])

	# Finally, trim out all the ininame values that we don't need any more
	for game in data['games'].values():
		del game['ininame']
	for stat in data['stats'].values():
		del stat['ininame']

	# Save the completed data, so we don't need to do this again
	save()

load()
