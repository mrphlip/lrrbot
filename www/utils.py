import datetime

import flask
import pytz

from common import config
from www import login

def error_page(message):
	return flask.render_template("error.html", message=message, session=login.load_session(include_url=False))

def timestamp(ts):
	"""
	Outputs a given time (either unix timestamp or datetime instance) as a human-readable time
	and includes tags so that common.js will convert the time on page-load to the user's
	timezone and preferred date/time format.
	"""
	if isinstance(ts, (int, float)):
		ts = datetime.datetime.fromtimestamp(ts, tz=pytz.utc)
	elif ts.tzinfo is None:
		ts = ts.replace(tzinfo=datetime.timezone.utc)
	ts = ts.astimezone(config.config['timezone'])
	return flask.Markup("<span class=\"timestamp\" data-timestamp=\"{}\">{:%A, %-d %B, %Y %H:%M:%S %Z}</span>".format(ts.timestamp(), ts))
