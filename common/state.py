import sqlalchemy
from sqlalchemy.dialects.postgresql import insert

def get(engine, metadata, key, default=None):
	state = metadata.tables['state']
	with engine.begin() as conn:
		row = conn.execute(sqlalchemy.select([state.c.value])
			.where(state.c.key == key)) \
			.first()
	if row is not None:
		return row[0]
	return default

def set(engine, metadata, key, value):
	state = metadata.tables['state']
	with engine.begin() as conn:
		query = insert(state)
		query = query.on_conflict_do_update(
			index_elements=[state.c.key],
			set_={
				'value': query.excluded.value,
			}
		)
		conn.execute(query, {
			'key': key,
			'value': value,
		})
