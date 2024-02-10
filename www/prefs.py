import flask

from common.account_providers import ACCOUNT_PROVIDER_TWITCH
from www import server
from www import login

blueprint = flask.Blueprint('prefs', __name__)

@blueprint.route('/prefs')
@login.require_login
def prefs(session):
	twitch_accounts = [account for account in session['accounts'] if account['provider'] == ACCOUNT_PROVIDER_TWITCH]
	return flask.render_template('prefs.html', session=session, saved=False, twitch_accounts=twitch_accounts)

@blueprint.route('/prefs', methods=["POST"])
@login.require_login
def save(session):
	twitch_accounts = [account for account in session['accounts'] if account['provider'] == ACCOUNT_PROVIDER_TWITCH]

	for account in twitch_accounts:
		if (autostatus := flask.request.values.get(f"autostatus[{account['id']}]")) is not None:
			account['autostatus'] = bool(int(autostatus))

	if 'stream_delay' in flask.request.values:
		session['user']['stream_delay'] = int(flask.request.values['stream_delay'])
		if not -60 <= session['user']['stream_delay'] <= 60:
			raise ValueError("stream_delay")
	if 'chat_timestamps' in flask.request.values:
		session['user']['chat_timestamps'] = int(flask.request.values['chat_timestamps'])
		if session['user']['chat_timestamps'] not in (0, 1, 2, 3):
			raise ValueError("chat_timestamps")
	if 'chat_timestamps_24hr' in flask.request.values:
		session['user']['chat_timestamps_24hr'] = bool(int(flask.request.values['chat_timestamps_24hr']))
	if 'chat_timestamps_secs' in flask.request.values:
		session['user']['chat_timestamps_secs'] = bool(int(flask.request.values['chat_timestamps_secs']))

	accounts = server.db.metadata.tables["accounts"]
	users = server.db.metadata.tables["users"]
	with server.db.engine.connect() as conn:
		conn.execute(users.update().where(users.c.id == session['user']['id']), {
			"stream_delay": session['user']['stream_delay'],
			"chat_timestamps": session['user']['chat_timestamps'],
			"chat_timestamps_24hr": session['user']['chat_timestamps_24hr'],
			"chat_timestamps_secs": session['user']['chat_timestamps_secs'],
		})
		for account in twitch_accounts:
			conn.execute(accounts.update().where(accounts.c.id == account['id']), {
				"autostatus": account['autostatus'],
			})
		conn.commit()

	return flask.render_template('prefs.html', session=session, saved=True, twitch_accounts=twitch_accounts)
