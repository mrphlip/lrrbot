import base64
import dateutil.parser
import flask
import hmac
import os
import sqlalchemy
from sqlalchemy.dialects.postgresql import insert
import urllib.parse
from www import server
from www import login
from common.config import config
from common import patreon
import common.rpc

PATREON_BASE_URL = "https://www.patreon.com/"

# Space separated list of scopes.
#  `users` - profile information
#  `pledges-to-me` - pledge amount
#  `my-campaign` - campaign information
SCOPE = "users pledges-to-me"

@server.app.route('/patreon/')
@login.require_login
async def patreon_index(session):
	patreon_users = server.db.metadata.tables['patreon_users']
	users = server.db.metadata.tables['users']
	with server.db.engine.connect() as conn:
		channel_patreon_name, = conn.execute(sqlalchemy.select(patreon_users.c.full_name)
			.select_from(users.join(patreon_users))
			.where(users.c.name == config['channel'])).first()

	if session['user']['patreon_user_id'] is None:
		state = base64.urlsafe_b64encode(os.urandom(18)).decode('ascii')
		flask.session['patreon_state'] = state
		pledge_url = None
		is_patron = False
	else:
		state = None
		is_patron = False

		token = await patreon.get_token(server.db.engine, server.db.metadata, session['user']['id'])
		user = await patreon.current_user(token)
		for pledge in user['data'].get('relationships', {}).get('pledges', {}).get('data', []):
			for obj in user['included']:
				if obj['type'] == pledge['type'] and obj['id'] == pledge['id'] and obj['attributes']['amount_cents'] > 0:
					is_patron = True
					with server.db.engine.connect() as conn:
						conn.execute(patreon_users.update().where(patreon_users.c.patreon_id == user['data']['id']), {
							"pledge_start": dateutil.parser.parse(obj['attributes']['created_at']),
						})
						conn.commit()
					break
			else:
				continue
			break

		if not is_patron:
			token = await patreon.get_token(server.db.engine, server.db.metadata, config['channel'])
			campaigns = await patreon.get_campaigns(token, ["creator"])
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
		redirect_url=config['patreon_redirect_uri'],
		state=state,
		scope=SCOPE,
		pledge_url=pledge_url,
	)

@server.app.route('/patreon/login')
@login.require_login
async def patreon_login(session):
	code = flask.request.args.get('code')
	state_param = flask.request.args.get('state')
	state_sess = flask.session.pop('patreon_state', None)
	if code is None or state_param is None or state_sess is None:
		flask.flash('OAuth parameters missing', 'error')
		return flask.redirect(flask.url_for('patreon_index'))

	if state_param != state_sess:
		flask.flash('Nonce mismatch: %r not equal to %r' % (state_param, state_sess), 'error')
		return flask.redirect(flask.url_for('patreon_index'))

	access_token, refresh_token, expiry = await patreon.request_token('authorization_code',
		code=code,
		redirect_uri=config['patreon_redirect_uri'],
	)

	user = await patreon.current_user(access_token)

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
	with server.db.engine.connect() as conn:
		query = insert(patreon_users).returning(patreon_users.c.id)
		query = query.on_conflict_do_update(
			index_elements=[patreon_users.c.patreon_id],
			set_={
				'full_name': query.excluded.full_name,
				'access_token': query.excluded.access_token,
				'refresh_token': query.excluded.refresh_token,
				'token_expires': query.excluded.token_expires,
				'pledge_start': query.excluded.pledge_start,
			}
		)
		patreon_user_id, = conn.execute(query, {
			"patreon_id": user['data']['id'],
			"full_name": user['data']['attributes']['full_name'],
			"access_token": access_token,
			"refresh_token": refresh_token,
			"token_expires": expiry,
			"pledge_start": pledge_start,
		}).first()
		row = conn.execute(
			users.update()
				.where(users.c.patreon_user_id == patreon_user_id)
				.returning(users.c.name, users.c.display_name),
			{"patreon_user_id": None},
		).first()
		if row is not None:
			name, display_name = row
			flask.flash('Unlinked the Patreon account from %s.' % (display_name or name))
		conn.execute(users.update().where(users.c.id == session['user']['id']), {"patreon_user_id": patreon_user_id})
		conn.commit()

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
@server.csrf.exempt
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
		with server.db.engine.connect() as conn:
			query = insert(patreon_users).returning(patreon_users.c.id)
			query = query.on_conflict_do_update(
				index_elements=[patreon_users.c.patreon_id],
				set_={
					'full_name': query.excluded.full_name,
					'pledge_start': query.excluded.pledge_start,
				}
			)
			conn.execute(query, {
				"patreon_id": patron['id'],
				"full_name": patron['attributes']['full_name'],
				"pledge_start": pledge_start,
			}).first()
			conn.commit()
		common.storm.increment(server.db.engine, server.db.metadata, 'patreon-pledge')
	elif event == 'pledges:update':
		with server.db.engine.connect() as conn:
			query = insert(patreon_users).returning(patreon_users.c.id)
			query = query.on_conflict_do_update(
				index_elements=[patreon_users.c.patreon_id],
				set_={
					'full_name': query.excluded.full_name,
					'pledge_start': query.excluded.pledge_start,
				}
			)
			conn.execute(query, {
				"patreon_id": patron['id'],
				"full_name": patron['attributes']['full_name'],
				"pledge_start": pledge_start,
			})
			conn.commit()
	elif event == 'pledges:delete':
		with server.db.engine.connect() as conn:
			query = insert(patreon_users).returning(patreon_users.c.id)
			query = query.on_conflict_do_update(
				index_elements=[patreon_users.c.patreon_id],
				set_={
					'full_name': query.excluded.full_name,
					'pledge_start': query.excluded.pledge_start,
				}
			)
			conn.execute(query, {
				"patreon_id": patron['id'],
				"full_name": patron['attributes']['full_name'],
				"pledge_start": None,
			})
			conn.commit()
	else:
		raise NotImplementedError(event)

	return ""
