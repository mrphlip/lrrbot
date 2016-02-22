import functools
import random

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

def pick_random_row(cur, query, params = ()):
	" Return a random row of a SELECT query. "
	# CSE - common subexpression elimination, an optimisation Postgres doesn't do
	cur.execute("CREATE TEMP TABLE cse AS " + query, params)
	if cur.rowcount <= 0:
		return None
	cur.execute("SELECT * FROM cse OFFSET %s LIMIT 1", (random.randrange(cur.rowcount), ))
	row = cur.fetchone()
	cur.execute("DROP TABLE cse")
	return row

def escape_like(s):
	return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
