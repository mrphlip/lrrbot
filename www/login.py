import datetime
import functools
import secrets
import uuid

import flask
import flask.json
import pytz
import sqlalchemy
from sqlalchemy.dialects.postgresql import insert

import www.utils
from common.account_providers import ACCOUNT_PROVIDER_TWITCH, ACCOUNT_PROVIDER_YOUTUBE
from www import server
from common.config import config, from_apipass
from common import utils, youtube
from common import http
from common import googlecalendar
import common.rpc

# See https://dev.twitch.tv/docs/v5/guides/authentication/#scopes
# We don't actually need, or want, any at present
TWITCH_REQUEST_SCOPES = []

TWITCH_SPECIAL_USERS = {}
TWITCH_SPECIAL_USERS.setdefault(config["username"], list(TWITCH_REQUEST_SCOPES)).extend([
	'chat_login',
	'user_read',
	'user_follows_edit',
	'channel:moderate',
	'chat:edit',
	'chat:read',
	'moderator:manage:banned_users',
	'moderator:manage:blocked_terms',
	'moderator:manage:chat_messages',
	'moderator:manage:chat_settings',
	'moderator:manage:unban_requests',
	'moderator:manage:warnings',
	'moderator:read:chatters',
	'moderator:read:followers',
	'moderator:read:moderators',
	'moderator:read:vips',
	'user:read:follows',
	'user:manage:whispers',
	'whispers:edit',
	'whispers:read',
])
TWITCH_SPECIAL_USERS.setdefault(config["channel"], list(TWITCH_REQUEST_SCOPES)).extend([
	'channel_subscriptions',
	'channel:read:subscriptions',
])
# hard-coded user for accessing Desert Bus mod actions
# cf lrrbot.desertbus_moderator_actions
TWITCH_SPECIAL_USERS.setdefault('mrphlip', list(TWITCH_REQUEST_SCOPES)).extend([
	'moderator:read:blocked_terms',
	'moderator:read:chat_settings',
	'moderator:read:unban_requests',
	'moderator:read:banned_users',
	'moderator:read:chat_messages',
	'moderator:read:warnings',
	'moderator:read:moderators',
	'moderator:read:vips',
])

# See https://developers.google.com/identity/protocols/oauth2/scopes#youtube
YOUTUBE_DEFAULT_SCOPES = [
	# 'View your YouTube account'
	'https://www.googleapis.com/auth/youtube.readonly',
]
YOUTUBE_SPECIAL_USERS = {}
YOUTUBE_SPECIAL_USERS.setdefault(config['youtube_bot_id'], list(YOUTUBE_DEFAULT_SCOPES)).extend([
	# 'Manage your YouTube account'
	'https://www.googleapis.com/auth/youtube',
])
for channel_id in config['youtube_channels']:
	YOUTUBE_SPECIAL_USERS.setdefault(channel_id, list(YOUTUBE_DEFAULT_SCOPES)).extend([
		# 'See a list of your current active channel members, their current level, and when they became a member'
		'https://www.googleapis.com/auth/youtube.channel-memberships.creator',
	])

blueprint = flask.Blueprint('login', __name__)

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
	async def wrapper(*args, **kwargs):
		kwargs['session'] = await load_session()
		return await utils.wrap_as_coroutine(func)(*args, **kwargs)
	return wrapper

def with_minimal_session(func):
	"""
	Pass the current login session information to the function

	Do not include extra session information, intended for master.html. Useful for
	places that need the current user, but shouldn't (or don't need to) call
	botinteract.

	Usage:
	@server.app.route('/path')
	@with_minimal_session
	def handler(session):
		...
	"""
	@functools.wraps(func)
	async def wrapper(*args, **kwargs):
		kwargs['session'] = await load_session(include_url=False, include_header=False)
		return await utils.wrap_as_coroutine(func)(*args, **kwargs)
	return wrapper

def require_login(func):
	"""
	Like with_session, but if the user isn't logged in,
	send them via the login screen.
	"""
	@functools.wraps(func)
	async def wrapper(*args, **kwargs):
		session = await load_session()
		if session['user']['id'] is not None:
			kwargs['session'] = session
			return await utils.wrap_as_coroutine(func)(*args, **kwargs)
		else:
			return await login(session['url'])
	return wrapper

def require_mod(func):
	"""
	Like with_session, but if the user isn't logged in,
	send them via the login screen. If the user isn't
	a moderator, kick them out.
	"""
	@functools.wraps(func)
	async def wrapper(*args, **kwargs):
		session = await load_session()
		if session['user']['id'] is not None:
			kwargs['session'] = session
			if session['active_account']['is_mod']:
				return await utils.wrap_as_coroutine(func)(*args, **kwargs)
			else:
				mod_accounts = [account for account in session['accounts'] if account['is_mod']]
				return flask.render_template('require_mod.html', session=session, mod_accounts=mod_accounts)
		else:
			return await login(session['url'])
	return wrapper

async def load_session(include_url=True, include_header=True):
	"""
	Get the login session information from the cookies.

	Includes all the information needed by the master.html template.
	"""
	session = {}
	if include_url:
		session['url'] = flask.request.url
	else:
		session['url'] = None
	if include_header:
		try:
			session['header'] = await common.rpc.bot.get_header_info()
		except Exception:
			server.app.logger.exception("Failed to get the header info from the bot")
			session['header'] = {
				"is_live": False,
				"channel": config['channel'],
			}

		if 'current_game' in session['header']:
			games = server.db.metadata.tables["games"]
			shows = server.db.metadata.tables["shows"]
			game_per_show_data = server.db.metadata.tables["game_per_show_data"]
			with server.db.engine.connect() as conn:
				game_id = session['header']['current_game']['id']
				show_id = session['header']['current_show']['id']
				session['header']['current_game']['display'], = conn.execute(sqlalchemy.select(
					sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
				).select_from(games
					.outerjoin(game_per_show_data, (game_per_show_data.c.game_id == games.c.id) & (game_per_show_data.c.show_id == show_id))
				).where(games.c.id == game_id)).first()

				session['header']['current_show']['name'], = conn.execute(sqlalchemy.select(
					shows.c.name,
				).where(shows.c.id == show_id)).first()

		if not session['header']['is_live']:
			message, _ = await googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL)
			session['header']['nextstream'] = message

	users = server.db.metadata.tables["users"]
	accounts = server.db.metadata.tables["accounts"]
	with server.db.engine.connect() as conn:
		if 'apipass' in flask.request.values and (twitch_name := from_apipass[flask.request.values['apipass']]):
			account = conn.execute(
				sqlalchemy.select(accounts.c.id, accounts.c.user_id)
					.where(accounts.c.provider == ACCOUNT_PROVIDER_TWITCH)
					.where(accounts.c.name == twitch_name)
			).one_or_none()
			if account and account.user_id:
				user_id = account.user_id
				active_account_id = account.id
			else:
				user_id = None
				active_account_id = None
		else:
			user_id = flask.session.get('user_id')
			active_account_id = flask.session.get('active_account_id')

		user = conn.execute(sqlalchemy.select(
			users.c.id,
			users.c.stream_delay,
			users.c.chat_timestamps,
			users.c.chat_timestamps_24hr,
			users.c.chat_timestamps_secs,
		).where(users.c.id == user_id)).one_or_none()

		if user:
			session['user'] = {
				"id": user.id,
				"stream_delay": user.stream_delay,
				"chat_timestamps": user.chat_timestamps,
				"chat_timestamps_24hr": user.chat_timestamps_24hr,
				"chat_timestamps_secs": user.chat_timestamps_secs,
			}

			users_accounts = conn.execute(sqlalchemy.select(
				accounts.c.id,
				accounts.c.provider,
				accounts.c.provider_user_id,
				accounts.c.name,
				sqlalchemy.func.coalesce(accounts.c.display_name, accounts.c.name).label('display_name'),
				accounts.c.is_sub,
				accounts.c.is_mod,
				accounts.c.autostatus,
			).where(accounts.c.user_id == user.id)).all()
			session['accounts'] = [
				{
					"id": account.id,
					"provider": account.provider,
					"provider_user_id": account.provider_user_id,
					"name": account.name,
					"display_name": account.display_name,
					"is_sub": account.is_sub,
					"is_mod": account.is_mod,
					"autostatus": account.autostatus,
				}
				for account in users_accounts
			]
			session['active_account'] = next((account for account in session['accounts'] if account['id'] == active_account_id), None)
		if not user or not session.get('active_account'):
			session['user'] = {
				"id": None,
				"stream_delay": 10,
				"chat_timestamps": 0,
				"chat_timestamps_24hr": True,
				"chat_timestamps_secs": False,
			}
			session['accounts'] = []
			session['active_account'] = {
				"id": None,
				"provider": None,
				"provider_user_id": None,
				"name": None,
				"display_name": None,
				"is_sub": False,
				"is_mod": False,
				"autostatus": False,
			}

	return session

@blueprint.route('/login')
async def login(return_to=None):
	if 'code' not in flask.request.values:
		if return_to is None:
			return_to = flask.request.values.get('return_to')
		flask.session['login_return_to'] = return_to

		if 'as' in flask.request.values:
			if flask.request.values['as'] not in TWITCH_SPECIAL_USERS:
				return www.utils.error_page("Not a recognised user name: %s" % flask.request.values['as'])
			scope = TWITCH_SPECIAL_USERS[flask.request.values['as']]
		else:
			scope = TWITCH_REQUEST_SCOPES

		# Generate a random nonce so we can verify that the user who comes back is the same user we sent away
		flask.session['login_nonce'] = uuid.uuid4().hex

		return flask.render_template("login.html", clientid=config["twitch_clientid"], scope=' '.join(scope),
			redirect_uri=config['twitch_redirect_uri'], nonce=flask.session['login_nonce'], session=await load_session(include_url=False))
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
				'client_id': config["twitch_clientid"],
				'client_secret': config["twitch_clientsecret"],
				'grant_type': 'authorization_code',
				'redirect_uri': config['twitch_redirect_uri'],
				'code': flask.request.values['code'],
				'state': twitch_state,
			}
			headers = {
				'Client-ID': config['twitch_clientid'],
			}
			res_json = await http.request("https://id.twitch.tv/oauth2/token", method="POST", data=oauth_params, headers=headers)
			res_object = flask.json.loads(res_json)
			if not res_object.get('access_token'):
				raise Exception("No access token from Twitch: %s" % res_json)
			access_token = res_object['access_token']
			granted_scopes = res_object.get("scope", [])
			refresh_token = res_object.get("refresh_token")
			if expires_in := res_object.get("expires_in"):
				expiry = datetime.datetime.now(pytz.utc) + datetime.timedelta(seconds=expires_in)
			else:
				expiry = None

			# Use that access token to get basic information about the user
			headers['Authorization'] = f"Bearer {access_token}"
			res_json = await http.request("https://api.twitch.tv/helix/users", headers=headers)
			res_object = flask.json.loads(res_json)
			user_id = res_object['data'][0]['id']
			user_name = res_object['data'][0]['login'].lower()
			display_name = res_object['data'][0]['display_name']

			# If one of our special users logged in *without* using the "as" flag,
			# Twitch *might* remember them and give us the same permissions anyway
			# but if not, then we don't have the permissions we need to do our thing
			# so bounce them back to the login page with the appropriate scopes.
			if user_name in TWITCH_SPECIAL_USERS:
				if any(i not in granted_scopes for i in TWITCH_SPECIAL_USERS[user_name]):
					server.app.logger.error("User %s has not granted us the required permissions" % user_name)
					flask.session['login_nonce'] = uuid.uuid4().hex
					return flask.render_template(
						"login.html",
						clientid=config["twitch_clientid"],
						scope=' '.join(TWITCH_SPECIAL_USERS[user_name]),
						redirect_uri=config['twitch_redirect_uri'],
						nonce=flask.session['login_nonce'],
						session=await load_session(include_url=False),
						special_user=user_name,
						remember_me=remember_me,
					)

			# Store the user to the database
			account = {
				'provider': ACCOUNT_PROVIDER_TWITCH,
				'provider_user_id': user_id,
				'name': user_name,
				'display_name': display_name,
				'access_token': access_token,
				'refresh_token': refresh_token,
				'token_expires_at': expiry,
			}
			users = server.db.metadata.tables['users']
			accounts = server.db.metadata.tables["accounts"]
			with server.db.engine.connect() as conn:
				query = insert(accounts).returning(accounts.c.id, accounts.c.user_id)
				query = query.on_conflict_do_update(
					index_elements=[accounts.c.provider, accounts.c.provider_user_id],
					set_={
						'name': query.excluded.name,
						'display_name': query.excluded.display_name,
						'access_token': query.excluded.access_token,
						'refresh_token': query.excluded.refresh_token,
						'token_expires_at': query.excluded.token_expires_at,
					},
				)
				account_id, user_id = conn.execute(query, account).one()
				if user_id is None:
					user_id = conn.execute(users.insert().returning(users.c.id)).scalar_one()
					conn.execute(accounts.update().where(accounts.c.id == account_id), {'user_id': user_id})
				conn.commit()

			# Store the user ID into the session
			flask.session['user_id'] = user_id
			flask.session['active_account_id'] = account_id
			flask.session.permanent = remember_me

			return_to = flask.session.pop('login_return_to', None)
			return flask.render_template("login_response.html", success=True, return_to=return_to, session=await load_session(include_url=False))
		except utils.PASSTHROUGH_EXCEPTIONS:
			raise
		except Exception:
			server.app.logger.exception("Exception in login")
			return flask.render_template("login_response.html", success=False, session=await load_session(include_url=False))

@blueprint.route('/logout')
async def logout():
	if 'user_id' in flask.session:
		del flask.session['user_id']
	if 'active_account_id' in flask.session:
		del flask.session['active_account_id']
	session = await load_session(include_url=False)
	return flask.render_template("logout.html", return_to=flask.request.values.get('return_to'), session=session)

@blueprint.route('/login/youtube')
async def youtube_login():
	if 'code' not in flask.request.args:
		flask.session['youtube_state'] = secrets.token_urlsafe()

		return flask.render_template(
			"login_youtube.html",
			session=await load_session(include_url=False),
			client_id=config['youtube_client_id'],
			redirect_uri=config['youtube_redirect_uri'],
			scope=' '.join(YOUTUBE_DEFAULT_SCOPES),
			nonce=flask.session['youtube_state'],
		)
	elif 'error' in flask.request.args:
		return flask.render_template("login_response.html", success=False, session=await load_session(include_url=False))
	else:
		try:
			expected_state = flask.session.pop('youtube_state', None)
			if not expected_state:
				raise Exception("Not expecting a login here")
			actual_state = flask.request.args.get('state')

			if expected_state != actual_state:
				raise Exception("State mismatch: %s vs %s" % (expected_state, actual_state))

			access_token, refresh_token, expiry = await youtube.request_token('authorization_code', code=flask.request.args['code'], redirect_uri=config['youtube_redirect_uri'])

			channel = await youtube.get_my_channel(access_token)

			granted_scopes = flask.request.args['scope'].split(' ')
			if channel['id'] in YOUTUBE_SPECIAL_USERS:
				required_scopes = YOUTUBE_SPECIAL_USERS[channel['id']]
			else:
				required_scopes = YOUTUBE_DEFAULT_SCOPES

			if any([scope not in granted_scopes for scope in required_scopes]):
				flask.session['youtube_state'] = secrets.token_urlsafe()

				return flask.render_template(
					"login_youtube.html",
					session=await load_session(include_url=False),
					client_id=config['youtube_client_id'],
					redirect_uri=config['youtube_redirect_uri'],
					scope=' '.join(required_scopes),
					nonce=flask.session['youtube_state'],
					special_user=channel['snippet']['title'],
				)

			account = {
				'provider': ACCOUNT_PROVIDER_YOUTUBE,
				'provider_user_id': channel['id'],
				'name': channel['snippet']['title'],
				'access_token': access_token,
				'refresh_token': refresh_token,
				'token_expires_at': expiry,
			}
			accounts = server.db.metadata.tables["accounts"]
			with server.db.engine.connect() as conn:
				query = insert(accounts)
				query = query.on_conflict_do_update(
					index_elements=[accounts.c.provider, accounts.c.provider_user_id],
					set_={
						'name': query.excluded.name,
						'access_token': query.excluded.access_token,
						'refresh_token': query.excluded.refresh_token,
						'token_expires_at': query.excluded.token_expires_at,
					},
				)
				conn.execute(query, account)
				conn.commit()

			return flask.render_template("login_response.html", success=True, session=await load_session(include_url=False))
		except utils.PASSTHROUGH_EXCEPTIONS:
			raise
		except Exception:
			server.app.logger.exception("Exception in login")
			return flask.render_template("login_response.html", success=False, session=await load_session(include_url=False))
