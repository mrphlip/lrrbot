#!/usr/bin/env python3
import www.server
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
import www.secrets
import utils

www.server.app.secret_key = www.secrets.session_secret
www.server.app.add_template_filter(utils.nice_duration)
www.server.app.add_template_filter(utils.ucfirst)
www.server.app.add_template_filter(utils.timestamp)

app = www.server.app
__all__ = ['app']

if __name__ == '__main__':
	app.run(debug=True)
