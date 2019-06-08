#!/usr/bin/env python3

from common import utils

utils.init_logging("webserver")

import common.time
import common.url
import www.utils
from common.config import config
from www.server import app
import www.index
import www.help
import www.notifications
import www.login
import www.archive
import www.commands
import www.spam
import www.history
import www.api
import www.api_v2
import www.quotes
import www.patreon
import www.clips
import www.prefs

app.secret_key = config["session_secret"]
app.config["PREFERRED_URL_SCHEME"] = config["preferred_url_scheme"],
app.add_template_filter(common.time.nice_duration)
app.add_template_filter(utils.ucfirst)
app.add_template_filter(www.utils.timestamp)
app.add_template_filter(common.url.https)
app.add_template_filter(common.url.noproto)
app.csrf_token = app.jinja_env.globals["csrf_token"]
app.jinja_env.globals["min"] = min
app.jinja_env.globals["max"] = max
app.jinja_env.globals["static_url"] = www.utils.static_url
app.jinja_env.globals["cycler"] = www.utils.CyclerExt

app.register_blueprint(www.api_v2.blueprint, url_prefix="/api/v2")

__all__ = ['app']

if __name__ == '__main__':
	app.env = "development"
	app.run(debug=True, threaded=False, use_reloader=False)
