import asyncio
import functools
import urllib.request
import urllib.parse
import uuid

import flask
import flask.json
import sqlalchemy
from sqlalchemy.dialects.postgresql import insert

import www.utils
from www import server
from common.config import config, from_apipass
from common import utils
from common import twitch
from common import game_data
from common import googlecalendar
import common.rpc

with server.db.engine.begin() as conn:
	users = server.db.metadata.tables["users"]
	for key, name in from_apipass.items():
		query = insert(users) \
			.values(id=sqlalchemy.bindparam("_id")) \
			.returning(users.c.id)
		query = query.on_conflict_do_update(
			index_elements=[users.c.id],
			set_={
				'name': query.excluded.name,
				'display_name': query.excluded.display_name,
			},
		)
		from_apipass[key], = conn.execute(query, twitch.get_user(name)).first()

# See https://github.com/justintv/Twitch-API/blob/master/authentication.md#scopes
# We don't actually need, or want, any at present
REQUEST_SCOPES = []

SPECIAL_USERS = {}
SPECIAL_USERS.setdefault(config["username"], []).extend(['chat_login', 'user_read', 'user_follows_edit'])
SPECIAL_USERS.setdefault(config["channel"], []).extend(['channel_subscriptions'])

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
		return await asyncio.coroutine(func)(*args, **kwargs)
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
		return await asyncio.coroutine(func)(*args, **kwargs)
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
			return await asyncio.coroutine(func)(*args, **kwargs)
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
			if session['user']['is_mod']:
				return await asyncio.coroutine(func)(*args, **kwargs)
			else:
				return flask.render_template('require_mod.html', session=session)
		else:
			return await login(session['url'])
	return wrapper

async def load_session(include_url=True, include_header=True):
	"""
	Get the login session information from the cookies.

	Includes all the information needed by the master.html template.
	"""
	user_id = flask.session.get('id')
	user_name = flask.session.get('user')
	if user_id is None and user_name is not None:
		# Upgrade old session
		with server.db.engine.begin() as conn:
			query = insert(users) \
				.values(id=sqlalchemy.bindparam("_id")) \
				.returning(users.c.id)
			query = query.on_conflict_do_update(
				index_elements=[users.c.id],
				set_={
					'name': query.excluded.name,
					'display_name': query.excluded.display_name,
				},
			)
			user_id, = conn.execute(query, twitch.get_user(user_name)).first()
		flask.session["id"] = user_id
	if 'user' in flask.session:
		del flask.session["user"]
	if 'apipass' in flask.request.values and flask.request.values['apipass'] in from_apipass:
		user_id = from_apipass[flask.request.values["apipass"]]

	session = {}
	if include_url:
		session['url'] = flask.request.url
	else:
		session['url'] = None
	if include_header:
		session['header'] = await common.rpc.bot.get_header_info()
		if 'current_game' in session['header']:
			games = server.db.metadata.tables["games"]
			shows = server.db.metadata.tables["shows"]
			stats = server.db.metadata.tables["stats"]
			game_per_show_data = server.db.metadata.tables["game_per_show_data"]
			game_stats = server.db.metadata.tables["game_stats"]
			game_votes = server.db.metadata.tables["game_votes"]
			disabled_stats = server.db.metadata.tables["disabled_stats"]
			with server.db.engine.begin() as conn:
				game_id = session['header']['current_game']['id']
				show_id = session['header']['current_show']['id']
				session['header']['current_game']['display'], = conn.execute(sqlalchemy.select([
					sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
				]).select_from(games
					.outerjoin(game_per_show_data, (game_per_show_data.c.game_id == games.c.id) & (game_per_show_data.c.show_id == show_id))
				).where(games.c.id == game_id)).first()

				session['header']['current_show']['name'], = conn.execute(sqlalchemy.select([
					shows.c.name,
				]).where(shows.c.id == show_id)).first()

				good = sqlalchemy.cast(
					sqlalchemy.func.sum(sqlalchemy.cast(game_votes.c.vote, sqlalchemy.Integer)),
					sqlalchemy.Numeric
				)
				rating = conn.execute(sqlalchemy.select([
					(100 * good / sqlalchemy.func.count(game_votes.c.vote)),
					good,
					sqlalchemy.func.count(game_votes.c.vote),
				]).where(game_votes.c.game_id == game_id).where(game_votes.c.show_id == show_id)).first()
				if rating[0] is not None and rating[1] is not None:
					session['header']['current_game']["rating"] = {
						'perc': rating[0],
						'good': rating[1],
						'total': rating[2],
					}
				stats_query = sqlalchemy.select([
					game_stats.c.count,
					game_data.stat_plural(stats, game_stats.c.count)
				]).select_from(game_stats
					.join(stats, stats.c.id == game_stats.c.stat_id)
				).where(game_stats.c.game_id == game_id) \
					.where(game_stats.c.show_id == show_id) \
					.where(~sqlalchemy.exists(sqlalchemy.select([1])
						.where(disabled_stats.c.stat_id == game_stats.c.stat_id)
						.where(disabled_stats.c.show_id == game_stats.c.show_id)
					)) \
					.order_by(game_stats.c.count.desc())
				session['header']['current_game']['stats'] = [
					{
						'count': count,
						'type': type,
					}
					for count, type in conn.execute(stats_query)
				]

		if not session['header']['is_live']:
			session['header']['nextstream'] = googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL)

	if user_id is not None:
		users = server.db.metadata.tables["users"]
		patreon_users = server.db.metadata.tables["patreon_users"]
		with server.db.engine.begin() as conn:
			query = sqlalchemy.select([
				users.c.name, sqlalchemy.func.coalesce(users.c.display_name, users.c.name), users.c.twitch_oauth,
				users.c.is_sub, users.c.is_mod, users.c.autostatus, users.c.patreon_user_id
			]).where(users.c.id == user_id)
			name, display_name, token, is_sub, is_mod, autostatus, patreon_user_id = conn.execute(query).first()
			session['user'] = {
				"id": user_id,
				"name": name,
				"display_name": display_name,
				"twitch_oauth": token,
				"is_sub": is_sub,
				"is_mod": is_mod,
				"autostatus": autostatus,
				"patreon_user_id": patreon_user_id,
			}
	else:
		session['user'] = {
			"id": None,
			"name": None,
			"display_name": None,
			"twitch_oauth": None,
			"is_sub": False,
			"is_mod": False,
			"autostatus": False,
		}
	return session

@server.app.route('/login')
async def login(return_to=None):
	if 'code' not in flask.request.values:
		if return_to is None:
			return_to = flask.request.values.get('return_to')
		flask.session['login_return_to'] = return_to

		if 'as' in flask.request.values:
			if flask.request.values['as'] not in SPECIAL_USERS:
				return www.utils.error_page("Not a recognised user name: %s" % flask.request.values['as'])
			scope = SPECIAL_USERS[flask.request.values['as']]
		else:
			scope = REQUEST_SCOPES

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
			}
			res_json = urllib.request.urlopen("https://api.twitch.tv/kraken/oauth2/token", urllib.parse.urlencode(oauth_params).encode()).read().decode()
			res_object = flask.json.loads(res_json)
			if not res_object.get('access_token'):
				raise Exception("No access token from Twitch: %s" % res_json)
			access_token = res_object['access_token']
			granted_scopes = res_object["scope"]

			# Use that access token to get basic information about the user
			req = urllib.request.Request("https://api.twitch.tv/kraken/")
			req.add_header("Authorization", "OAuth %s" % access_token)
			req.add_header("Client-ID", config['twitch_clientid'])
			res_json = urllib.request.urlopen(req).read().decode()
			res_object = flask.json.loads(res_json)
			if not res_object.get('token', {}).get('valid'):
				raise Exception("User object not valid: %s" % res_json)
			if not res_object.get('token', {}).get('user_name'):
				raise Exception("No user name from Twitch: %s" % res_json)
			user_name = res_object['token']['user_name'].lower()

			# If one of our special users logged in *without* using the "as" flag,
			# Twitch *might* remember them and give us the same permissions anyway
			# but if not, then we don't have the permissions we need to do our thing
			# so bounce them back to the login page with the appropriate scopes.
			if user_name in SPECIAL_USERS:
				if any(i not in granted_scopes for i in SPECIAL_USERS[user_name]):
					server.app.logger.error("User %s has not granted us the required permissions" % user_name)
					flask.session['login_nonce'] = uuid.uuid4().hex
					return flask.render_template("login.html", clientid=config["twitch_clientid"], scope=' '.join(SPECIAL_USERS[user_name]),
						redirect_uri=config['twitch_redirect_uri'], nonce=flask.session['login_nonce'], session=await load_session(include_url=False),
						special_user=user_name, remember_me=remember_me)

			# Store the user to the database
			user = twitch.get_user(user_name)
			user["id"] = user["_id"]
			user["twitch_oauth"] = access_token
			with server.db.engine.begin() as conn:
				query = insert(users)
				query = query.on_conflict_do_update(
					index_elements=[users.c.id],
					set_={
						'name': query.excluded.name,
						'display_name': query.excluded.display_name,
						'twitch_oauth': query.excluded.twitch_oauth,
					},
				)
				conn.execute(query, user)

			# Store the user ID into the session
			flask.session['id'] = user["_id"]
			flask.session.permanent = remember_me

			return_to = flask.session.pop('login_return_to', None)
			return flask.render_template("login_response.html", success=True, return_to=return_to, session=await load_session(include_url=False))
		except utils.PASSTHROUGH_EXCEPTIONS:
			raise
		except Exception:
			server.app.logger.exception("Exception in login")
			return flask.render_template("login_response.html", success=False, session=await load_session(include_url=False))

@server.app.route('/logout')
async def logout():
	if 'id' in flask.session:
		del flask.session['id']
	session = await load_session(include_url=False)
	return flask.render_template("logout.html", return_to=flask.request.values.get('return_to'), session=session)
