import functools

import psycopg2

from common import config

def get_postgres():
	return psycopg2.connect(config.config["postgres"])

def with_postgres(func):
	"""Decorator to pass a PostgreSQL connection and cursor to a function"""
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		with get_postgres() as conn, conn.cursor() as cur:
			return func(conn, cur, *args, **kwargs)
	return wrapper

def with_postgres_transaction(func):
	"""Decorator to pass a PostgreSQL connection and cursor to a function, with
	an isolated transaction active.

	If the function returns normally, the transaction will be committed, if the
	function raises an exception, it will be rolled back. The function can call
	conn.commit() or conn.rollback() to override this."""
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		with get_postgres() as conn:
			# turn off auto-commit
			conn.set_isolation_level(1)
			try:
				with conn.cursor() as cur:
					return func(conn, cur, *args, **kwargs)
			except:
				conn.rollback()
				raise
			else:
				conn.commit()
	return wrapper

def escape_like(s):
	return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
