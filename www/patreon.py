import asyncio
import base64
import datetime
import dateutil.parser
import pytz
import flask
from flaskext.csrf import csrf_exempt
import hmac
import os
import sqlalchemy
import urllib.parse
from www import server
from www import login
from common.config import config
from common import patreon
from common import sqlalchemy_pg95_upsert
from common import utils
import common.rpc

PATREON_BASE_URL = "https://www.patreon.com/"

# Space separated list of scopes.
#  `users` - profile information
#  `pledges-to-me` - pledge amount
#  `my-campaign` - campaign information
SCOPE = "users pledges-to-me"

@server.app.route('/patreon/')
@login.require_login
@asyncio.coroutine
def patreon_index(session):
	patreon_users = server.db.metadata.tables['patreon_users']
	users = server.db.metadata.tables['users']
	with server.db.engine.begin() as conn:
		channel_patreon_name, = conn.execute(sqlalchemy.select([patreon_users.c.full_name])
			.select_from(users.join(patreon_users))
			.where(users.c.name == config['channel'])).first()

	if session['user']['patreon_user'] is None:
		state = base64.urlsafe_b64encode(os.urandom(18)).decode('ascii')
		flask.session['patreon_state'] = state
		pledge_url = None
		is_patron = False
	else:
		state = None
		is_patron = False

		token = yield from patreon.get_token(server.db.engine, server.db.metadata, session['user']['id'])
		user = yield from patreon.current_user(token)
		for pledge in user['data'].get('relationships', {}).get('pledges', {}).get('data', []):
			for obj in user['included']:
				if obj['type'] == pledge['type'] and obj['id'] == pledge['id'] and obj['attributes']['amount_cents'] > 0:
					is_patron = True
					with server.db.engine.begin() as conn:
						conn.execute(patreon_users.update().where(patreon_users.c.patreon_id == user['data']['id']),
							pledge_start=dateutil.parser.parse(obj['attributes']['created_at']))
					break
			else:
				continue
			break

		if not is_patron:
			token = yield from patreon.get_token(server.db.engine, server.db.metadata, config['channel'])
			campaigns = yield from patreon.get_campaigns(token, ["creator"])
			pledge_url = urllib.parse.urljoin(PATREON_BASE_URL, campaigns['data'][0]['attributes']['pledge_url'])
			pledge_url = urllib.parse.urlsplit(pledge_url)
			query_string = urllib.parse.parse_qs(pledge_url.query)
			query_string['patAmt'] = ["5.0"] # Set the default pledge amount to $5. Defaults to $1.
			query_string['redirect_uri'] = [flask.url_for('patreon_index', _external=True)]
			pledge_url = urllib.parse.urlunsplit(urllib.parse.SplitResult(pledge_url.scheme, pledge_url.netloc, pledge_url.path, '', '')), query_string
		else:
			pledge_url = None

	return flask.render_template('patreon.html',
		session=session,
		is_patron=is_patron,
		client_id=config['patreon_clientid'],
		channel_patreon_name=channel_patreon_name,
		redirect_url=flask.url_for('patreon_login', _external=True),
		state=state,
		scope=SCOPE,
		pledge_url=pledge_url,
	)

@server.app.route('/patreon/login')
@login.require_login
@asyncio.coroutine
def patreon_login(session):
	code = flask.request.args.get('code')
	state_param = flask.request.args.get('state')
	state_sess = flask.session.pop('patreon_state', None)
	if code is None or state_param is None or state_sess is None:
		flask.flash('OAuth parameters missing', 'error')
		return flask.redirect(flask.url_for('patreon_index'))

	if state_param != state_sess:
		flask.flash('Nonce mismatch: %r not equal to %r' % (state_param, state_sess), 'error')
		return flask.redirect(flask.url_for('patreon_index'))

	access_token, refresh_token, expiry = yield from patreon.request_token('authorization_code',
		code=code,
		redirect_uri=flask.url_for('patreon_login', _external=True),
	)

	user = yield from patreon.current_user(access_token)

	patreon_users = server.db.metadata.tables['patreon_users']
	users = server.db.metadata.tables['users']
	pledge_start = None
	for pledge in user['data'].get('relationships', {}).get('pledges', {}).get('data', []):
		for obj in user['included']:
			if obj['type'] == pledge['type'] and obj['id'] == pledge['id'] and obj['attributes']['amount_cents'] > 0:
				pledge_start = dateutil.parser.parse(obj['attributes']['created_at'])
				break
		else:
			continue
		break
	with server.db.engine.begin() as conn:
		do_update = sqlalchemy_pg95_upsert.DoUpdate(patreon_users.c.patreon_id)
		do_update.set_with_excluded('full_name', 'access_token', 'refresh_token', 'token_expires', 'pledge_start')
		patreon_user, = conn.execute(
			patreon_users.insert(postgresql_on_conflict=do_update)
				.returning(patreon_users.c.id),
			patreon_id=user['data']['id'],
			full_name=user['data']['attributes']['full_name'],
			access_token=access_token,
			refresh_token=refresh_token,
			token_expires=expiry,
			pledge_start=pledge_start,
		).first()
		conn.execute(users.update().where(users.c.id == session['user']['id']), patreon_user=patreon_user)

	flask.flash('Patreon account linked.', 'success')

	return flask.redirect(flask.url_for('patreon_index'))

class HmacRequestStream:
	def __init__(self, stream):
		self.stream = stream
		self.hmac = hmac.new(config['patreon_clientsecret'].encode('utf-8'), None, 'md5')

	def read(self, n):
		data = self.stream.read(n)
		self.hmac.update(data)
		return data

	def readline(self, hint):
		data = self.stream.readline(hint)
		self.hmac.update(data)
		return data

@server.app.route('/patreon/webhooks', methods=["POST"])
@csrf_exempt
async def patreon_webhooks():
	stream = HmacRequestStream(flask.request.environ['wsgi.input'])
	flask.request.environ['wsgi.input'] = stream

	pledge = flask.request.get_json()
	if not hmac.compare_digest(stream.hmac.hexdigest(), flask.request.headers['X-Patreon-Signature']):
		return flask.abort(400)

	if pledge['data']['attributes']['created_at']:
		pledge_start = dateutil.parser.parse(pledge['data']['attributes']['created_at'])
	else:
		pledge_start = None
	patron_ref = pledge['data']['relationships']['patron']['data']
	for obj in pledge['included']:
		if obj['id'] == patron_ref['id'] and obj['type'] == patron_ref['type']:
			patron = obj
			break
	else:
		raise Exception("user %r not included" % patron_ref)

	patreon_users = server.db.metadata.tables['patreon_users']
	users = server.db.metadata.tables['users']

	event = flask.request.headers['X-Patreon-Event']
	if event == 'pledges:create':
		with server.db.engine.begin() as conn:
			do_update = sqlalchemy_pg95_upsert.DoUpdate(patreon_users.c.patreon_id)
			do_update.set_with_excluded('full_name', 'pledge_start')
			patron_id, = conn.execute(
				patreon_users.insert(postgresql_on_conflict=do_update)
						.returning(patreon_users.c.id),
					patreon_id=patron['id'],
					full_name=patron['attributes']['full_name'],
					pledge_start=pledge_start,
			).first()
			twitch_user = conn.execute(sqlalchemy.select([users.c.name]).where(users.c.patreon_user == patron_id)).first()
			if twitch_user is not None:
				twitch_user = {
					'name': twitch_user[0]
				}
			data = {
				'patreon': {
					'full_name': patron['attributes']['full_name'],
					'avatar': patron['attributes']['image_url'],
					'url': patron['attributes']['url']
				},
				'twitch': twitch_user,
			}
		data["count"] = common.storm.increment(server.db.engine, server.db.metadata, 'patreon-pledge')
		results = await asyncio.gather(common.rpc.bot.patreon_pledge(data), common.rpc.eventserver.event('patreon-pledge', data, datetime.datetime.now(tz=pytz.utc)), return_exceptions=True)
		for result in results:
			if isinstance(result, BaseException):
				raise result
	elif event == 'pledges:update':
		with server.db.engine.begin() as conn:
			do_update = sqlalchemy_pg95_upsert.DoUpdate(patreon_users.c.patreon_id)
			do_update.set_with_excluded('full_name', 'pledge_start')
			conn.execute(
				patreon_users.insert(postgresql_on_conflict=do_update),
					patreon_id=patron['id'],
					full_name=patron['attributes']['full_name'],
					pledge_start=pledge_start,
			)
	elif event == 'pledges:delete':
		with server.db.engine.begin() as conn:
			do_update = sqlalchemy_pg95_upsert.DoUpdate(patreon_users.c.patreon_id)
			do_update.set_with_excluded('full_name', 'pledge_start')
			conn.execute(
				patreon_users.insert(postgresql_on_conflict=do_update),
					patreon_id=patron['id'],
					full_name=patron['attributes']['full_name'],
					pledge_start=None,
			)
	else:
		raise NotImplementedError(event)

	return ""
