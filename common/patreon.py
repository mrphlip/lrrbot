import asyncio
import datetime
import json

import pytz
import sqlalchemy

from common.config import config
from common import http

@asyncio.coroutine
def request_token(grant_type, **data):
	data.update({
		"grant_type": grant_type,
		"client_id": config["patreon_clientid"],
		"client_secret": config["patreon_clientsecret"],
	})
	data = yield from http.request_coro("https://api.patreon.com/oauth2/token", data=data, method="POST")
	data = json.loads(data)
	expiry = datetime.datetime.now(pytz.utc) + datetime.timedelta(seconds=data["expires_in"])
	return data["access_token"], data["refresh_token"], expiry

@asyncio.coroutine
def get_token(engine, metadata, user):
	def filter_by_user(query, user):
		if isinstance(user, int):
			return query.where(users.c.id == user)
		elif isinstance(user, str):
			return query.where(users.c.name == user)
		else:
			raise Exception("`user` not an ID nor a name")

	users = metadata.tables["users"]
	with engine.begin() as conn:
		query = sqlalchemy.select([
			users.c.patreon_access_token,
			users.c.patreon_refresh_token,
			users.c.patreon_token_expires
		])
		query = filter_by_user(query, user)
		row = conn.execute(query).first()
		if row is None:
			raise Exception("User not logged in")
		access_token, refresh_token, expiry = row
		if access_token is None:
			raise Exception("User not logged in")
	if expiry < datetime.datetime.now(pytz.utc):
		access_token, refresh_token, expiry = yield from request_token("refresh_token", refresh_token=refresh_token)
		with engine.begin() as conn:
			query = users.update()
			query = filter_by_user(query, user)
			conn.execute(query,
				patreon_access_token=access_token,
				patreon_refresh_token=refresh_token,
				patreon_token_expires=expiry,
			)

	return access_token

@asyncio.coroutine
def get_campaigns(token, include=["creator", "goals", "rewards"]):
	data = {"include": ",".join(include)}
	headers = {"Authorization": "Bearer %s" % token}
	data = yield from http.request_coro("https://api.patreon.com/oauth2/api/current_user/campaigns", data=data, headers=headers)
	return json.loads(data)
