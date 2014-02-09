#!/usr/bin/env python
import sys
import os
import cgi
import cgitb
import json
import shutil
import pyratemp
import utils
import secrets
import time

# Enable debug errors
cgitb.enable()

request = cgi.parse()

STORAGE = "../upload.json"
STALE_TIME = 3600

if os.environ.get('REQUEST_METHOD') == "PUT":
	if request['apipass'][0] != secrets.apipass:
		utils.write_json({'error':'apipass'})
		sys.exit()
	with open(STORAGE, "w") as fp:
		shutil.copyfileobj(sys.stdin, fp)
	utils.write_json({'success': 'OK'})
	exit()

def ucfirst(s):
	return s[0].upper() + s[1:]

datastat = os.stat(STORAGE)
if time.time() - datastat.st_mtime > STALE_TIME:
	stale = utils.nice_duration(time.time() - datastat.st_mtime)
else:
	stale = None

with open(STORAGE, "r") as fp:
	data = json.load(fp)
# Make totals, for sorting
for statkey, stat in data['stats'].items():
	stat['total'] = sum(g.get('stats',{}).get(statkey,0) for g in data['games'].values())
# Make our lives easier in the template
for game in data['games'].values():
	game.setdefault('display', game['name'])
	game.setdefault('stats', {})
	for statkey in data['stats'].keys():
		game['stats'].setdefault(statkey, 0)

print "Content-type: text/html; charset=utf-8"
print
template = pyratemp.Template(filename="tpl/stats.html")
print template(data=data, ucfirst=ucfirst, json=json.dumps, stale=stale).encode("utf-8")
