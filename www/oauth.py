#!/usr/bin/env python
import cgi
import cgitb
import pyratemp
import urllib, urllib2
import json
import utils
import secrets

# Enable debug errors
# cgitb.enable()

# See https://github.com/justintv/Twitch-API/blob/master/authentication.md#scopes
REQUEST_SCOPES = ['chat_login']

# Needs to be the URI of this script, and also the registered URI for the app
REDIRECT_URI = 'http://lrrbot.mrphlip.com/oauth'

request = cgi.parse()

if 'code' not in request:
	print "Content-type: text/html; charset=utf-8"
	print
	template = pyratemp.Template(filename="tpl/oauth.html")
	print template(clientid=secrets.twitch_clientid, scope=' '.join(REQUEST_SCOPES), redirect_uri=REDIRECT_URI).encode("utf-8")
else:
	oauth_params = {
		'client_id': secrets.twitch_clientid,
		'client_secret': secrets.twitch_clientsecret,
		'grant_type': 'authorization_code',
		'redirect_uri': REDIRECT_URI,
		'code': request['code'][0],
	}
	res = urllib2.urlopen("https://api.twitch.tv/kraken/oauth2/token", urllib.urlencode(oauth_params)).read().decode()
	res = json.loads(res)
	print "Content-type: text/html; charset=utf-8"
	print
	template = pyratemp.Template(filename="tpl/oauth_response.html")
	print template(token=res['access_token'], scopes=res['scope']).encode("utf-8")
