import os
import datetime
import subprocess

import flask
import pytz
import jinja2.utils

from common import config
from common.utils import cache
from common.time import nice_duration
from www import login

def error_page(message):
	return flask.render_template("error.html", message=message, session=login.load_session(include_url=False))

def timestamp(ts, cls='timestamp', tag='span'):
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
	if cls == 'timestamp-duration':
		text = nice_duration(datetime.datetime.now(config.config['timezone']) - ts, 2)
	else:
		text = ts.strftime("%A, %d %B, %Y %H:%M:%S %Z")
	return flask.Markup("<{tag} class=\"{cls}\" data-timestamp=\"{timestamp}\">{text}</{tag}>".format(
		text=text,
		timestamp=ts.timestamp(),
		tag=tag,
		cls=cls,
	))

@cache(period=None, params=[0])
def static_url(filename):
	baseurl = flask.url_for("static", filename=filename)
	revision = subprocess.check_output([
		'git', 'log', '-n', '1', '--pretty=format:%h', '--',
		os.path.join('www', 'static', filename)]).decode()
	return "{}?_={}".format(baseurl, revision)

# Add a "last" to get the previous value returned, to complement the existing
# "current" prop which gets the upcoming value.
class CyclerExt(jinja2.utils.Cycler):
	@property
	def last(self):
		# self.pos is always positive or zero, so this will wrap cleanly
		return self.items[self.pos - 1]
