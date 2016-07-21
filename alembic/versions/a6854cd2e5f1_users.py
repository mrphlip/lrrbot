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
	with open(datafile) as f:
		data = json.load(f)

	names = set()
	names.update(data.get("autostatus", []))
	names.update(data.get("subs", []))
	names.update(data.get("mods", []))
	names.update(data.get("twitch_oauth", {}).keys())
	users = []
	with requests.Session() as session:
		for i, nick in enumerate(names):
			log.info("Fetching %d/%d: %r", i + 1, len(names), nick)
			try:
				req = session.get("https://api.twitch.tv/kraken/users/%s" % urllib.parse.quote(nick), headers={'Client-ID': clientid})
				req.raise_for_status()
				user = req.json()
				users.append({
					"id": user["_id"],
					"name": user["name"],
					"display_name": user.get("display_name"),
					"twitch_oauth": data.get("twitch_oauth", {}).get(nick),
					"is_sub": nick in data.get("subs", []),
					"is_mod": nick in data.get("mods", []),
					"autostatus": nick in data.get("autostatus", []),
				})
			except Exception:
				log.exception("Failed to fetch data for %r", nick)
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
	meta = sqlalchemy.MetaData(bind=conn)
	meta.reflect()
	users = meta.tables["users"]

	datafile = alembic.context.config.get_section_option("lrrbot", "datafile", "data.json")
	with open(datafile) as f:
		data = json.load(f)
	data["autostatus"] = [nick for nick, in conn.execute(sqlalchemy.select([users.c.name]).where(users.c.autostatus))]
	data["subs"] = [nick for nick, in conn.execute(sqlalchemy.select([users.c.name]).where(users.c.is_sub))]
	data["mods"] = [nick for nick, in conn.execute(sqlalchemy.select([users.c.name]).where(users.c.is_mod))]
	data["twitch_oauth"] = {
		name: key
		for name, key in conn.execute(sqlalchemy.select([users.c.name, users.c.twitch_oauth]).where(users.c.twitch_oauth != None))
	}
	with open(datafile, "w") as f:
		json.dump(data, f, indent=2, sort_keys=True)
	alembic.op.drop_table("users")
