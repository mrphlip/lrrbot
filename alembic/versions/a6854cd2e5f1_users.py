revision = 'a6854cd2e5f1'
down_revision = '07ea7b63c8fc'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy
import json
import urllib.parse
import requests
import logging

log = logging.getLogger("a6854cd2e5f1_users")

CHUNK_SIZE = 100

def upgrade():
	users_table = alembic.op.create_table("users",
		sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=False),
		sqlalchemy.Column("name", sqlalchemy.Text, nullable=False),
		sqlalchemy.Column("display_name", sqlalchemy.Text),
		sqlalchemy.Column("twitch_oauth", sqlalchemy.Text),
		sqlalchemy.Column("is_sub", sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.false()),
		sqlalchemy.Column("is_mod", sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.false()),
		sqlalchemy.Column("autostatus", sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.false()),
	)

	datafile = alembic.context.config.get_section_option("lrrbot", "datafile", "data.json")
	clientid = alembic.context.config.get_section_option("lrrbot", "twitch_clientid")
	clientsecret = alembic.context.config.get_section_option("lrrbot", "twitch_clientsecret")
	try:
		with open(datafile) as f:
			data = json.load(f)
	except FileNotFoundError:
		data = {}

	names = set()
	names.update(data.get("autostatus", []))
	names.update(data.get("subs", []))
	names.update(data.get("mods", []))
	names.update(data.get("twitch_oauth", {}).keys())
	names = list(names)
	users = []
	with requests.Session() as session:
		req = session.post('https://id.twitch.tv/oauth2/token', params={
			'client_id': clientid,
			'client_secret': clientsecret,
			'grant_type': 'client_credentials',
		})
		req.raise_for_status()
		token = req.json()['access_token']

		for i in range(0, len(names), CHUNK_SIZE):
			chunk = names[i:i+CHUNK_SIZE]
			log.info("Fetching %d-%d/%d", i + 1, i + len(chunk), len(names))
			try:
				req = session.get(
					"https://api.twitch.tv/helix/users", params={'login': chunk},
					headers={'Client-ID': clientid, 'Authentication': f'Bearer {token}'})
				req.raise_for_status()
				for user in req.json()['users']:
					nick = user['name'].lower()
					users.append({
						"id": user["id"],
						"name": user["login"],
						"display_name": user.get("display_name"),
						"twitch_oauth": data.get("twitch_oauth", {}).get(nick),
						"is_sub": nick in data.get("subs", []),
						"is_mod": nick in data.get("mods", []),
						"autostatus": nick in data.get("autostatus", []),
					})
			except Exception:
				log.exception("Failed to fetch data for %r", chunk)
	alembic.op.bulk_insert(users_table, users)

	for key in ["autostatus", "subs", "mods", "twitch_oauth"]:
		try:
			del data[key]
		except KeyError:
			pass
	with open(datafile, "w") as f:
		json.dump(data, f, indent=2, sort_keys=True)


def downgrade():
	conn = alembic.context.get_context().bind
	meta = sqlalchemy.MetaData()
	meta.reflect(conn)
	users = meta.tables["users"]

	datafile = alembic.context.config.get_section_option("lrrbot", "datafile", "data.json")
	try:
		with open(datafile) as f:
			data = json.load(f)
	except FileNotFoundError:
		data = {}
	data["autostatus"] = [nick for nick, in conn.execute(sqlalchemy.select(users.c.name).where(users.c.autostatus))]
	data["subs"] = [nick for nick, in conn.execute(sqlalchemy.select(users.c.name).where(users.c.is_sub))]
	data["mods"] = [nick for nick, in conn.execute(sqlalchemy.select(users.c.name).where(users.c.is_mod))]
	data["twitch_oauth"] = {
		name: key
		for name, key in conn.execute(sqlalchemy.select(users.c.name, users.c.twitch_oauth).where(users.c.twitch_oauth != None))
	}
	with open(datafile, "w") as f:
		json.dump(data, f, indent=2, sort_keys=True)
	alembic.op.drop_table("users")
