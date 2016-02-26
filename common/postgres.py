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

def escape_like(s):
	return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
