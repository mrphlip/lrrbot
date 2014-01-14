#!/usr/bin/python
if __name__ == '__main__':
	import sys
	sys.stderr.write("utils.py accessed directly")
	sys.exit(1)

import sys
import json

def writejson(obj, pretty=False):
	"""Write a full JSON response, including HTTP headers"""
	print "Content-type: application/json"
	print
	json.dump(obj, sys.stdout,
		indent=2 if pretty else None,
		separators=(', ', ': ') if pretty else (',',':')
	)

def niceduration(duration):
	"""Convert a duration in seconds to a human-readable duration"""
	if duration < 0:
		return "-" + niceduration(-duration)
	if duration < 60:
		return "%ds" % duration
	duration //= 60
	if duration < 60:
		return "%dm" % duration
	duration //= 60
	if duration < 24:
		return "%dh" % duration
	return "%dd, %dh" % divmod(duration, 24)
