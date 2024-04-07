revision = 'cddcdf06d9f9'
down_revision = '6f1e9151ef83'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy
import logging
import datetime
import json

def upgrade():
	storm = alembic.op.create_table("storm",
		sqlalchemy.Column("date", sqlalchemy.Date, primary_key=True),
		sqlalchemy.Column("twitch-subscription", sqlalchemy.Integer, nullable=False, server_default='0'),
		sqlalchemy.Column("twitch-resubscription", sqlalchemy.Integer, nullable=False, server_default='0'),
		sqlalchemy.Column("twitch-follow", sqlalchemy.Integer, nullable=False, server_default='0'),
		sqlalchemy.Column("twitch-message", sqlalchemy.Integer, nullable=False, server_default='0'),
		sqlalchemy.Column("patreon-pledge", sqlalchemy.Integer, nullable=False, server_default='0'),
	)

	datafile = alembic.context.config.get_section_option("lrrbot", "datafile", "data.json")
	try:
		with open(datafile) as f:
			data = json.load(f)
	except FileNotFoundError:
		data = {}
	try:
		alembic.op.bulk_insert(storm, [
			{'date': datetime.date.fromordinal(data['storm']['date']), 'twitch-subscription': data['storm']['count']}
		])
		del data['storm']
		with open(datafile, 'w') as f:
			json.dump(data, f, indent=2, sort_keys=True)
	except KeyError:
		pass

def downgrade():
	conn = alembic.context.get_context().bind
	meta = sqlalchemy.MetaData()
	meta.reflect(conn)

	storm = meta.tables['storm']
	row = conn.execute(sqlalchemy.select(storm.c.date, storm.c['twitch-subscription'])).first()
	if row is not None:
		date, count = row

		datafile = alembic.context.config.get_section_option("lrrbot", "datafile", "data.json")
		try:
			with open(datafile) as f:
				data = json.load(f)
		except FileNotFoundError:
			data = {}
		data['storm'] = {
			'date': date.toordinal(),
			'count': count,
		}
		with open(datafile, 'w') as f:
			json.dump(data, f, indent=2, sort_keys=True)

	alembic.op.drop_table("storm")
