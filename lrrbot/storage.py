import json
import os

from common.config import config

"""
Data structure:

data = {
	'spam_rules': [
		{
			're': '<regular expression>',
			'message': '<ban description>',
		},
	],
}

For example:
data = {
	'spam_rules': [
		{
			're': '^I am a spambot!$',
			'message': "claims to be a spambot",
		},
	],
}
"""

data = {}

def load():
	"""Read data from storage"""
	global data
	try:
		with open(config['datafile'], "r") as fp:
			data = json.load(fp)
	except FileNotFoundError:
		data = {}

def save():
	"""Save data to storage"""
	realfile = config['datafile']
	tempfile = ".%s.tmp" % config['datafile']
	backupfile = "%s~" % config['datafile']

	with open(tempfile, "w") as fp:
		# Save with pretty-printing enabled, as we probably want it to be editable
		json.dump(data, fp, indent=2, sort_keys=True)

	os.replace(realfile, backupfile)
	os.replace(tempfile, realfile)

load()
