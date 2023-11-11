import warnings

import sqlalchemy
import sqlalchemy.exc

from common.config import config

def new_engine_and_metadata():
	"""
	Create new SQLAlchemy engine and metadata.

	NOTE: Every process should have AT MOST one engine.
	"""
	engine = sqlalchemy.create_engine(config["postgres"], echo=config["debugsql"], execution_options={"autocommit": False}, pool_pre_ping=True)
	metadata = sqlalchemy.MetaData()
	with warnings.catch_warnings():
		# Yes, I know you can't understand FTS indexes.
		warnings.simplefilter("ignore", category=sqlalchemy.exc.SAWarning)
		metadata.reflect(engine)
	return engine, metadata

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
