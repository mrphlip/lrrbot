#!/usr/bin/env python
import flask
import flask.json
import functools
import server
import urllib.request, urllib.parse
import secrets
import uuid
import utils
import botinteract

# See https://github.com/justintv/Twitch-API/blob/master/authentication.md#scopes
# We don't actually need, or want, any at present
REQUEST_SCOPES = []

# Needs to be the URI of this script, and also the registered URI for the app
REDIRECT_URI = 'http://lrrbot.mrphlip.com/login'
#REDIRECT_URI = 'http://localhost:5000/login'

def with_session(func):
	"""
	Pass the current login session information to the function

	Usage:
	@server.app.route('/path')
	@with_session
	def handler(session): # keyword argument must be "session"
		...
	"""
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		kwargs['session'] = load_session()
		return func(*args, **kwargs)
	return wrapper

def require_login(func):
	"""
	Like with_session, but if the user isn't logged in,
	send them via the login screen.
	"""
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		session = load_session()
		if session['user']:
			kwargs['session'] = session
			return func(*args, **kwargs)
		else:
			return login(session['url'])
	return wrapper

def require_mod(func):
	"""
	Like with_session, but if the user isn't logged in,
	send them via the login screen. If the user isn't
	a moderator, kick them out.
	"""
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		session = load_session()
		if session['user']:
			kwargs['session'] = session
			if session['header']['is_mod']:
				return func(*args, **kwargs)
			else:
				return flask.render_template('require_mod.html', session=session)
		else:
			return login(session['url'])
	return wrapper

def load_session(include_url=True, include_header=True):
	"""
	Get the login session information from the cookies.

	Includes all the information needed by the master.html template.
	"""
	# could potentially add other things here in the future...
	session = {
		"user": flask.session.get('user'),
	}
	if include_url:
		session['url'] = flask.request.url
	else:
		session['url'] = None
	if include_header:
		session['header'] = botinteract.get_header_info()
	return session

@server.app.route('/login')
def login(return_to=None):
	if 'code' not in flask.request.values:
		if return_to is None:
			return_to = flask.request.values.get('return_to')
		flask.session['login_return_to'] = return_to
		# Generate a random nonce so we can verify that the user who comes back is the same user we sent away
		flask.session['login_nonce'] = uuid.uuid4().hex
		return flask.render_template("login.html", clientid=secrets.twitch_clientid, scope=' '.join(REQUEST_SCOPES), redirect_uri=REDIRECT_URI, nonce=flask.session['login_nonce'], session=load_session(include_url=False))
	else:
		try:
			# Check that we're expecting the user to be logging in...
			expected_nonce = flask.session.pop('login_nonce', None)
			if not expected_nonce:
				raise Exception("Not expecting a login here")
			twitch_state = flask.request.values.get('state', '')
			# We have to pack the "remember me" flag into the state parameter we send via twitch, since that's where the form points... awkward
			if ':' in twitch_state:
				twitch_nonce, remember_me = twitch_state.split(':')
				remember_me = bool(int(remember_me))
			else:
				# User didn't have JS turned on, so remember me option not available
				twitch_nonce = twitch_state
				remember_me = False
			if expected_nonce != twitch_nonce:
				raise Exception("Nonce mismatch: %s vs %s" % (expected_nonce, twitch_nonce))
			# Call back to Twitch to get our access token
			oauth_params = {
				'client_id': secrets.twitch_clientid,
				'client_secret': secrets.twitch_clientsecret,
				'grant_type': 'authorization_code',
				'redirect_uri': REDIRECT_URI,
				'code': flask.request.values['code'],
			}
			res_json = urllib.request.urlopen("https://api.twitch.tv/kraken/oauth2/token", urllib.parse.urlencode(oauth_params).encode()).read().decode()
			res_object = flask.json.loads(res_json)
			if not res_object.get('access_token'):
				raise Exception("No access token from Twitch: %s" % res_json)
			access_token = res_object['access_token']
			# Use that access token to get basic information about the user
			req = urllib.request.Request("https://api.twitch.tv/kraken/")
			req.add_header("Authorization", "OAuth %s" % access_token)
			res_json = urllib.request.urlopen(req).read().decode()
			res_object = flask.json.loads(res_json)
			if not res_object.get('token', {}).get('valid'):
				raise Exception("User object not valid: %s" % res_json)
			if not res_object.get('token', {}).get('user_name'):
				raise Exception("No user name from Twitch: %s" % res_json)
			# Store the user name into the session
			# Note: we DON'T store the access_token in the session, as the session contents
			# are user-visible (for the default Flask implementation) and the token needs
			# to be kept secret. And we don't need it for anything other than verifying the
			# user name anyway.
			# Should we ever decide we need to keep the token around in the future, we'll need
			# to use an alternate session backend for Flask so we can keep it secret.
			flask.session['user'] = res_object['token']['user_name'].lower()
			flask.session.permanent = remember_me
			return_to = flask.session.pop('login_return_to', None)
			return flask.render_template("login_response.html", success=True, return_to=return_to, session=load_session(include_url=False))
		except:
			server.app.logger.exception("Exception in login")
			return flask.render_template("login_response.html", success=False, tmp="Error", session=load_session(include_url=False))

@server.app.route('/logout')
def logout():
	if 'user' in flask.session:
		del flask.session['user']
	session = load_session(include_url=False)
	return flask.render_template("logout.html", return_to=flask.request.values.get('return_to'), session=session)
