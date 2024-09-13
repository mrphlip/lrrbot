import base64
import flask
import hmac
import os
import sqlalchemy
from sqlalchemy.dialects.postgresql import insert
import urllib.parse
from www import server
from www import login
from common.account_providers import ACCOUNT_PROVIDER_PATREON
from common.config import config
from common import patreon
import common.rpc

blueprint = flask.Blueprint('patreon', __name__)

PATREON_BASE_URL = "https://www.patreon.com/"

# Space separated list of scopes.
#  `users` - profile information
#  `pledges-to-me` - pledge amount
#  `my-campaign` - campaign information
SCOPE = "users pledges-to-me"

@blueprint.route('/')
@login.require_login
async def index(session):
	accounts = server.db.metadata.tables['accounts']
	with server.db.engine.connect() as conn:
		channel_patreon_name = conn.execute(sqlalchemy.select(accounts.c.name)
			.where(accounts.c.provider == ACCOUNT_PROVIDER_PATREON)
			.where(accounts.c.provider_user_id == config['patreon_creator_user_id'])).scalar_one()

	patreon_account = next((account for account in session['accounts'] if account['provider'] == ACCOUNT_PROVIDER_PATREON), None)

	if not patreon_account:
		state = base64.urlsafe_b64encode(os.urandom(18)).decode('ascii')
		flask.session['patreon_state'] = state
		pledge_url = None
	else:
		state = None
		is_patron = False

		token = await patreon.get_token(server.db.engine, server.db.metadata, patreon_account['provider_user_id'])
		user = await patreon.current_user(token)
		for pledge in user['data'].get('relationships', {}).get('pledges', {}).get('data', []):
			for obj in user['included']:
				if obj['type'] == pledge['type'] and obj['id'] == pledge['id'] and obj['attributes']['amount_cents'] > 0:
					is_patron = True
					break
			else:
				continue
			break

		with server.db.engine.connect() as conn:
			conn.execute(
				accounts.update()
					.where(accounts.c.provider == ACCOUNT_PROVIDER_PATREON)
					.where(accounts.c.provider_user_id == user['data']['id']),
				{"is_sub": is_patron},
			)
			patreon_account['is_sub'] = is_patron
			conn.commit()

		if not is_patron:
			token = await patreon.get_token(server.db.engine, server.db.metadata, config['patreon_creator_user_id'])
			campaigns = await patreon.get_campaigns(token, ["creator"])
			pledge_url = urllib.parse.urljoin(PATREON_BASE_URL, campaigns['data'][0]['attributes']['pledge_url'])
			pledge_url = urllib.parse.urlsplit(pledge_url)
			query_string = urllib.parse.parse_qs(pledge_url.query)
			query_string['patAmt'] = ["5.0"] # Set the default pledge amount to $5. Defaults to $1.
			query_string['redirect_uri'] = [flask.url_for('patreon.index', _external=True)]
			pledge_url = urllib.parse.urlunsplit(urllib.parse.SplitResult(pledge_url.scheme, pledge_url.netloc, pledge_url.path, '', '')), query_string
		else:
			pledge_url = None

	return flask.render_template('patreon.html',
		session=session,
		patreon_account=patreon_account,
		client_id=config['patreon_clientid'],
		channel_patreon_name=channel_patreon_name,
		redirect_url=config['patreon_redirect_uri'],
		state=state,
		scope=SCOPE,
		pledge_url=pledge_url,
	)

@blueprint.route('/login')
@login.require_login
async def login(session):
	code = flask.request.args.get('code')
	state_param = flask.request.args.get('state')
	state_sess = flask.session.pop('patreon_state', None)
	if code is None or state_param is None or state_sess is None:
		flask.flash('OAuth parameters missing', 'error')
		return flask.redirect(flask.url_for('patreon.index'))

	if state_param != state_sess:
		flask.flash('Nonce mismatch: %r not equal to %r' % (state_param, state_sess), 'error')
		return flask.redirect(flask.url_for('patreon.index'))

	access_token, refresh_token, expiry = await patreon.request_token('authorization_code',
		code=code,
		redirect_uri=config['patreon_redirect_uri'],
	)

	user = await patreon.current_user(access_token)

	accounts = server.db.metadata.tables['accounts']
	is_sub = None
	for pledge in user['data'].get('relationships', {}).get('pledges', {}).get('data', []):
		for obj in user['included']:
			if obj['type'] == pledge['type'] and obj['id'] == pledge['id'] and obj['attributes']['amount_cents'] > 0:
				is_sub = True
				break
		else:
			continue
		break
	with server.db.engine.connect() as conn:
		query = insert(accounts)
		query = query.on_conflict_do_update(
			index_elements=[accounts.c.provider, accounts.c.provider_user_id],
			set_={
				"user_id": query.excluded.user_id,
				"name": query.excluded.name,
				"access_token": query.excluded.access_token,
				"refresh_token": query.excluded.refresh_token,
				"token_expires_at": query.excluded.token_expires_at,
				"is_sub": query.excluded.is_sub,
			}
		)
		conn.execute(query, {
			"provider": ACCOUNT_PROVIDER_PATREON,
			"provider_user_id": user['data']['id'],
			"user_id": session['user']['id'],
			"name": user['data']['attributes']['full_name'],
			"access_token": access_token,
			"refresh_token": refresh_token,
			"token_expires_at": expiry,
			"is_sub": is_sub,
		}).first()
		conn.commit()

	flask.flash('Patreon account linked.', 'success')

	return flask.redirect(flask.url_for('patreon.index'))

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

@blueprint.route('/webhooks', methods=["POST"])
@server.csrf.exempt
async def webhooks():
	stream = HmacRequestStream(flask.request.environ['wsgi.input'])
	flask.request.environ['wsgi.input'] = stream

	pledge = flask.request.get_json()
	if not hmac.compare_digest(stream.hmac.hexdigest(), flask.request.headers['X-Patreon-Signature']):
		return flask.abort(400)

	is_sub = bool(pledge['data']['attributes']['created_at'])
	patron_ref = pledge['data']['relationships']['patron']['data']
	for obj in pledge['included']:
		if obj['id'] == patron_ref['id'] and obj['type'] == patron_ref['type']:
			patron = obj
			break
	else:
		raise Exception("user %r not included" % patron_ref)

	accounts = server.db.metadata.tables['accounts']

	event = flask.request.headers['X-Patreon-Event']
	if event == 'pledges:create':
		with server.db.engine.connect() as conn:
			query = insert(accounts)
			query = query.on_conflict_do_update(
				index_elements=[accounts.c.provider, accounts.c.provider_user_id],
				set_={
					'name': query.excluded.name,
					'is_sub': query.excluded.is_sub,
				}
			)
			conn.execute(query, {
				"provider": ACCOUNT_PROVIDER_PATREON,
				"provider_user_id": patron['id'],
				"name": patron['attributes']['full_name'],
				"is_sub": is_sub,
			}).first()
			conn.commit()
		common.storm.increment(server.db.engine, server.db.metadata, 'patreon-pledge')
	elif event == 'pledges:update':
		with server.db.engine.connect() as conn:
			query = insert(accounts)
			query = query.on_conflict_do_update(
				index_elements=[accounts.c.provider, accounts.c.provider_user_id],
				set_={
					'name': query.excluded.name,
					'is_sub': query.excluded.pledge_start,
				}
			)
			conn.execute(query, {
				"provider": ACCOUNT_PROVIDER_PATREON,
				"provider_user_id": patron['id'],
				"name": patron['attributes']['full_name'],
				"is_sub": is_sub,
			})
			conn.commit()
	elif event == 'pledges:delete':
		with server.db.engine.connect() as conn:
			query = insert(accounts)
			query = query.on_conflict_do_update(
				index_elements=[accounts.c.provider, accounts.c.provider_user_id],
				set_={
					'name': query.excluded.full_name,
					'is_sub': query.excluded.is_sub,
				}
			)
			conn.execute(query, {
				"provider": ACCOUNT_PROVIDER_PATREON,
				"provider_user_id": patron['id'],
				"name": patron['attributes']['full_name'],
				"is_sub": False,
			})
			conn.commit()
	else:
		raise NotImplementedError(event)

	return ""
