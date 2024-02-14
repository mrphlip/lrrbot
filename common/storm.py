import datetime
import sqlalchemy
from sqlalchemy.dialects.postgresql import insert

from common.config import config

# All storm counters
COUNTERS = [
	'twitch-subscription',
	'twitch-resubscription',
	'twitch-follow',
	'twitch-message',
	'patreon-pledge',
	'twitch-cheer',
	'twitch-raid',
	'youtube-membership',
	'youtube-membership-milestone',
	'youtube-super-chat',
	'youtube-super-sticker',
]

# Counters that make up the combined storm counter
COMBINED_COUNTERS = [
	'twitch-subscription',
	'twitch-resubscription',
	'patreon-pledge',
	'youtube-membership',
	'youtube-membership-milestone',
]

def increment(engine, metadata, counter, by=1):
	storm = metadata.tables['storm']
	with engine.connect() as conn:
		query = insert(storm).returning(storm.c[counter])
		query = query.on_conflict_do_update(
			index_elements=[storm.c.date],
			set_={
				counter: storm.c[counter] + query.excluded[counter],
			}
		)
		count, = conn.execute(query, {
			'date': datetime.datetime.now(config['timezone']).date(),
			counter: by,
		}).first()
		conn.commit()
	return count

def get(engine, metadata, counter):
	storm = metadata.tables['storm']
	with engine.connect() as conn:
		row = conn.execute(sqlalchemy.select(storm.c[counter])
			.where(storm.c.date == datetime.datetime.now(config['timezone']).date())) \
			.first()
	if row is not None:
		return row[0]
	return 0

def get_combined(engine, metadata):
	combined_count = 0
	storm = metadata.tables['storm']
	with engine.connect() as conn:
		for counter in COMBINED_COUNTERS:
			row = conn.execute(sqlalchemy.select(storm.c[counter])
				.where(storm.c.date == datetime.datetime.now(config['timezone']).date())) \
				.first()
			if row is not None:
				combined_count += row[0]
	return combined_count
