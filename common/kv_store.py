import lmdb
import msgpack

class Transaction:
	def __init__(self, transaction):
		self.transaction = transaction

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		if exc_type is not None:
			self.abort()
		else:
			self.commit()

	def abort(self):
		self.transaction.abort()

	def commit(self):
		self.transaction.commit()

	def get(self, key, default=None):
		if isinstance(key, str):
			key = key.encode("utf-8")
		value = self.transaction.get(key)
		if value is None:
			return default
		return msgpack.unpackb(value, encoding="utf-8")

	def __getitem__(self, key):
		value = self.get(key)
		if value is None:
			raise KeyError(key)
		return value

	def __setitem__(self, key, value):
		if isinstance(key, str):
			key = key.encode("utf-8")
		self.transaction.put(key, msgpack.packb(value, use_bin_type=True))

	def __delitem__(self, key):
		if isinstance(key, str):
			key = key.encode("utf-8")
		self.transaction.delete(key)

class Store:
	def __init__(self, path):
		self.db = lmdb.open(path)

	def begin(self, write=False):
		return Transaction(self.db.begin(write=write, buffers=True))
