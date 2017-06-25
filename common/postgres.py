import functools
import warnings

import sqlalchemy

from common.config import config

def new_engine_and_metadata():
	"""
	Create new SQLAlchemy engine and metadata.

	NOTE: Every process should have AT MOST one engine.
	"""
	engine = sqlalchemy.create_engine(config["postgres"], echo=config["debugsql"], execution_options={"autocommit": False})
	metadata = sqlalchemy.MetaData(bind=engine)
	with warnings.catch_warnings():
		# Yes, I know you can't understand FTS indexes.
		warnings.simplefilter("ignore", category=sqlalchemy.exc.SAWarning)
		metadata.reflect()
	sqlalchemy.event.listen(engine, "engine_connect", ping_connection)
	return engine, metadata

def ping_connection(connection, branch):
	if branch:
		# "branch" refers to a sub-connection of a connection, don't ping those
		return

	# Check if connection is valid
	try:
		connection.scalar(sqlalchemy.select([1]))
	except sqlalchemy.exc.DBAPIError as err:
		if err.connection_invalidated:
			# connection not valid, force reconnect.
			connection.scalar(sqlalchemy.select([1]))
		else:
			raise

_engine_and_metadata = None
def get_engine_and_metadata():
	"""
	Return the SQLAlchemy engine and metadata for this process, creating one if
	there isn't one already.
	"""
	if _engine_and_metadata is None:
		set_engine_and_metadata(*new_engine_and_metadata())
	return _engine_and_metadata

def set_engine_and_metadata(engine, metadata):
	"""
	Set the SQLAlchemy engine and metadata for this process, for
	get_engine_and_metadata to return, if they are created by another source
	(eg flask_sqlalchemy).
	"""
	global _engine_and_metadata
	_engine_and_metadata = engine, metadata

def escape_like(s):
	return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
