revision = 'e966a3afd100'
down_revision = '954c3c4caf32'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy
import requests
import pytz
import dateutil.parser
import datetime

def upgrade():
	patreon_users = alembic.op.create_table("patreon_users",
		sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
		sqlalchemy.Column("patreon_id", sqlalchemy.Text, unique=True),
		sqlalchemy.Column("full_name", sqlalchemy.Text, nullable=False),
		
		sqlalchemy.Column("access_token", sqlalchemy.Text),
		sqlalchemy.Column("refresh_token", sqlalchemy.Text),
		sqlalchemy.Column("token_expires", sqlalchemy.DateTime(timezone=True)),

		sqlalchemy.Column("pledge_start", sqlalchemy.DateTime(timezone=True)),
		sqlalchemy.Column("last_announce_month", sqlalchemy.Integer),
	)

	alembic.op.add_column("users",
		sqlalchemy.Column("patreon_user",
			sqlalchemy.Integer, sqlalchemy.ForeignKey("patreon_users.id", onupdate="CASCADE", ondelete="SET NULL"),
			unique=True,
		)
	)

	# TODO: migrate
	conn = alembic.op.get_bind()
	meta = sqlalchemy.MetaData(bind=conn)
	meta.reflect()
	users = meta.tables["users"]
	existing_accounts = conn.execute(sqlalchemy.select([users.c.id, users.c.patreon_access_token, users.c.patreon_refresh_token, users.c.patreon_token_expires])
		.where(users.c.patreon_access_token.isnot(None)))
	all_patreon_users = []
	all_users = []
	clientid = alembic.context.config.get_section_option('lrrbot', 'patreon_clientid')
	clientsecret = alembic.context.config.get_section_option('lrrbot', 'patreon_clientsecret')
	with requests.Session() as session:
		for user_id, access_token, refresh_token, expires in existing_accounts:
			now = datetime.datetime.now(tz=pytz.utc)
			if expires < now:
				req = session.post("https://api.patreon.com/oauth2/token", data={
					'grant_type': 'refresh_token',
					'client_id': clientid,
					'client_secret': clientsecret,
					'refresh_token': refresh_token
				})
				req.raise_for_status()
				data = req.json()
				access_token = data["access_token"]
				refresh_token = data["refresh_token"]
				expires = datetime.datetime.now(pytz.utc) + datetime.timedelta(seconds=data["expires_in"])
			req = session.get("https://api.patreon.com/oauth2/api/current_user", headers={"Authorization": "Bearer %s" % access_token})
			req.raise_for_status()
			data = req.json()
			user = {
				"patreon_id": data["data"]["id"],
				"full_name": data["data"]["attributes"]["full_name"],
				
				"access_token": access_token,
				"refresh_token": refresh_token,
				"token_expires": expires,
			}
			if 'pledges' in data["data"].get("relationships", {}):
				for pledge in data["data"]["relationships"]["pledges"]["data"]:
					for obj in data["included"]:
						if obj["id"] == pledge["id"] and obj["type"] == pledge["type"]:
							user["pledge_start"] = dateutil.parser.parse(obj["attributes"]["created_at"])
			all_patreon_users.append(user)
			all_users.append((user_id, data["data"]["id"]))

	alembic.op.bulk_insert(patreon_users, all_patreon_users)
	for user_id, patreon_id in all_users:
		conn.execute(users.update()
			.values(patreon_user=patreon_users.c.id)
			.where(users.c.id == user_id)
			.where(patreon_users.c.patreon_id == patreon_id)
		)

	alembic.op.drop_column("users", "patreon_access_token")
	alembic.op.drop_column("users", "patreon_refresh_token")
	alembic.op.drop_column("users", "patreon_token_expires")

def downgrade():
	alembic.op.add_column("users", sqlalchemy.Column("patreon_access_token", sqlalchemy.Text))
	alembic.op.add_column("users", sqlalchemy.Column("patreon_refresh_token", sqlalchemy.Text))
	alembic.op.add_column("users", sqlalchemy.Column("patreon_token_expires", sqlalchemy.DateTime(timezone=True)))

	conn = alembic.op.get_bind()
	meta = sqlalchemy.MetaData(bind=conn)
	meta.reflect()
	users = meta.tables["users"]
	patreon_users = meta.tables["patreon_users"]
	alembic.op.execute(users.update().where(users.c.patreon_id == patreon_users.c.id)).values({
		"patreon_access_token": patreon_users.c.access_token,
		"patreon_refresh_token": patreon_users.c.refresh_token,
		"patreon_token_expires": patreon_users.c.token_expires,
	})

	alembic.op.drop_column("users", "patreon_id")
	alembic.op.drop_table("patreon_users")

