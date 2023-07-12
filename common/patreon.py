import datetime
import json

import pytz
import sqlalchemy

from common.config import config
from common import http

async def request_token(grant_type, **data):
	data.update({
		"grant_type": grant_type,
		"client_id": config["patreon_clientid"],
		"client_secret": config["patreon_clientsecret"],
	})
	data = await http.request_coro("https://api.patreon.com/oauth2/token", data=data, method="POST")
	data = json.loads(data)
	expiry = datetime.datetime.now(pytz.utc) + datetime.timedelta(seconds=data["expires_in"])
	return data["access_token"], data["refresh_token"], expiry

async def get_token(engine, metadata, user):
	def filter_by_user(query, user):
		if isinstance(user, int):
			return query.where(users.c.id == user)
		elif isinstance(user, str):
			return query.where(users.c.name == user)
		else:
			raise Exception("`user` not an ID nor a name")

	users = metadata.tables["users"]
	patreon_users = metadata.tables["patreon_users"]
	with engine.connect() as conn:
		query = sqlalchemy.select(
			patreon_users.c.id,
			patreon_users.c.access_token,
			patreon_users.c.refresh_token,
			patreon_users.c.token_expires,
		)
		query = filter_by_user(query, user)
		row = conn.execute(query.select_from(users.join(patreon_users, users.c.patreon_user_id == patreon_users.c.id))).first()
		if row is None:
			raise Exception("User not logged in")
		patreon_id, access_token, refresh_token, expiry = row
		if access_token is None:
			raise Exception("User not logged in")
	if expiry < datetime.datetime.now(pytz.utc):
		access_token, refresh_token, expiry = await request_token("refresh_token", refresh_token=refresh_token)
		with engine.connect() as conn:
			conn.execute(patreon_users.update().where(patreon_users.c.id == patreon_id), {
				"access_token": access_token,
				"refresh_token": refresh_token,
				"token_expires": expiry,
			})
			conn.commit()

	return access_token

async def get_campaigns(token, include=["creator", "goals", "rewards"]):
	data = {"include": ",".join(include)}
	headers = {"Authorization": "Bearer %s" % token}
	data = await http.request_coro("https://api.patreon.com/oauth2/api/current_user/campaigns", data=data, headers=headers)
	return json.loads(data)

async def current_user(token):
	headers = {"Authorization": "Bearer %s" % token}
	data = await http.request_coro("https://api.patreon.com/oauth2/api/current_user", headers=headers)
	return json.loads(data)
