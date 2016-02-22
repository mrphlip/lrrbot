#!/usr/bin/env python3
import common.time
import common.url
from common import utils
from common.config import config
from www.server import app
import www.index
import www.help
import www.notifications
import www.stats
import www.login
import www.archive
import www.votes
import www.commands
import www.spam
import www.botinteract
import www.history
import www.api
import www.quotes

app.secret_key = config["session_secret"]
app.add_template_filter(common.time.nice_duration)
app.add_template_filter(utils.ucfirst)
app.add_template_filter(utils.timestamp)
app.add_template_filter(common.url.https)
app.add_template_filter(common.url.noproto)
app.csrf_token = app.jinja_env.globals["csrf_token"]
app.jinja_env.globals["min"] = min
app.jinja_env.globals["max"] = max

__all__ = ['app']

if __name__ == '__main__':
	app.run(debug=True, use_reloader=False)
else:
	import logging
	app.logger.addHandler(logging.StreamHandler())
