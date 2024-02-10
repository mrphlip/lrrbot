import datetime
import json

import pytz
import sqlalchemy

from common.config import config
from common import http
from common.account_providers import ACCOUNT_PROVIDER_PATREON

async def request_token(grant_type, **data):
	data.update({
		"grant_type": grant_type,
		"client_id": config["patreon_clientid"],
		"client_secret": config["patreon_clientsecret"],
	})
	data = await http.request("https://api.patreon.com/oauth2/token", data=data, method="POST")
	data = json.loads(data)
	expiry = datetime.datetime.now(pytz.utc) + datetime.timedelta(seconds=data["expires_in"])
	return data["access_token"], data["refresh_token"], expiry

async def get_token(engine, metadata, patreon_id):
	accounts = metadata.tables["accounts"]
	with engine.connect() as conn:
		row = conn.execute(
			sqlalchemy.select(
				accounts.c.id,
				accounts.c.access_token,
				accounts.c.refresh_token,
				accounts.c.token_expires_at,
			).where(accounts.c.provider == ACCOUNT_PROVIDER_PATREON)
			.where(accounts.c.provider_user_id == patreon_id)
		).first()
		if row is None:
			raise Exception("User not logged in")
		account_id, access_token, refresh_token, expiry = row
		if access_token is None:
			raise Exception("User not logged in")
	if expiry < datetime.datetime.now(pytz.utc):
		access_token, refresh_token, expiry = await request_token("refresh_token", refresh_token=refresh_token)
		with engine.connect() as conn:
			conn.execute(accounts.update().where(accounts.c.id == account_id), {
				"access_token": access_token,
				"refresh_token": refresh_token,
				"token_expires_at": expiry,
			})
			conn.commit()

	return access_token

async def get_campaigns(token, include=["creator", "goals", "rewards"]):
	data = {"include": ",".join(include)}
	headers = {"Authorization": "Bearer %s" % token}
	data = await http.request("https://api.patreon.com/oauth2/api/current_user/campaigns", data=data, headers=headers)
	return json.loads(data)

async def current_user(token):
	headers = {"Authorization": "Bearer %s" % token}
	data = await http.request("https://api.patreon.com/oauth2/api/current_user", headers=headers)
	return json.loads(data)
