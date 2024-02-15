import sqlalchemy
from sqlalchemy.dialects.postgresql import insert

from common import postgres

def get(engine, metadata, key, default=None):
	state = metadata.tables['state']
	with engine.connect() as conn:
		row = conn.execute(sqlalchemy.select(state.c.value)
			.where(state.c.key == key)) \
			.first()
	if row is not None:
		return row[0]
	return default

def set(engine, metadata, key, value):
	state = metadata.tables['state']
	with engine.connect() as conn:
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
		conn.commit()

def delete(engine, metadata, key):
	state = metadata.tables['state']
	with engine.connect() as conn:
		conn.execute(state.delete().where(state.c.key == key))

class Property:
	"""
	Higher level interface over `state.get` and `state.set` using the descriptor protocol.

	## Example:
	```python
	class LRRbot:
		access = state.Property("lrrbot.main.access", "all")
	```
	"""

	def __init__(self, key, default=None):
		self._engine, self._metadata = postgres.get_engine_and_metadata()
		self._key = key
		self._default = default

	def __get__(self, obj, type=None):
		return get(self._engine, self._metadata, self._key, self._default)

	def __set__(self, obj, value):
		return set(self._engine, self._metadata, self._key, value)

	def __repr__(self):
		return "%(module)s.%(class)s(%(_key)r, %(_default)r)" % {
			"module": self.__class__.__module__,
			"class": self.__class__.__qualname__,
			"_key": self._key,
			"_default": self._default,
		}
