import datetime
import sqlalchemy

from common.config import config
from common.sqlalchemy_pg95_upsert import DoUpdate

def increment(engine, metadata, counter, by=1):
	storm = metadata.tables['storm']
	excluded = sqlalchemy.table('excluded', sqlalchemy.column(counter))
	with engine.begin() as conn:
		do_update = DoUpdate([storm.c.date]).set(**{counter: storm.c[counter] + excluded.c[counter]})
		count, = conn.execute(storm.insert(postgresql_on_conflict=do_update).returning(storm.c[counter]), {
			'date': datetime.datetime.now(config['timezone']).date(),
			counter: by,
		}).first()
	return count

def get(engine, metadata, counter):
	storm = metadata.tables['storm']
	with engine.begin() as conn:
		row = conn.execute(sqlalchemy.select([storm.c[counter]])
			.where(storm.c.date == datetime.datetime.now(config['timezone']).date())) \
			.first()
	if row is not None:
		return row[0]
	return 0

COMBINED_COUNTERS = ['twitch-subscription', 'twitch-resubscription', 'patreon-pledge']
def get_combined(engine, metadata):
	combined_count = 0
	storm = metadata.tables['storm']
	with engine.begin() as conn:
		for counter in COMBINED_COUNTERS:
			row = conn.execute(sqlalchemy.select([storm.c[counter]])
				.where(storm.c.date == datetime.datetime.now(config['timezone']).date())) \
				.first()
			if row is not None:
				combined_count += row[0]
	return combined_count
