#!/usr/bin/env python
import flask
import flask.json
import server
import urllib.request, urllib.parse
import secrets

# See https://github.com/justintv/Twitch-API/blob/master/authentication.md#scopes
REQUEST_SCOPES = ['chat_login']

# Needs to be the URI of this script, and also the registered URI for the app
REDIRECT_URI = 'http://lrrbot.mrphlip.com/oauth'

@server.app.route('/oauth')
def oauth():
	if 'code' not in flask.request.values:
		return flask.render_template("oauth.html", clientid=secrets.twitch_clientid, scope=' '.join(REQUEST_SCOPES), redirect_uri=REDIRECT_URI)
	else:
		oauth_params = {
			'client_id': secrets.twitch_clientid,
			'client_secret': secrets.twitch_clientsecret,
			'grant_type': 'authorization_code',
			'redirect_uri': REDIRECT_URI,
			'code': flask.request.values['code'],
		}
		res = urllib.request.urlopen("https://api.twitch.tv/kraken/oauth2/token", urllib.parse.urlencode(oauth_params).encode()).read().decode()
		res = json.loads(res)
		return flask.render_template("oauth_response.html", token=res['access_token'], scopes=res['scope'])
