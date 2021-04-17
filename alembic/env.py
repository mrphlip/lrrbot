from __future__ import with_statement
from alembic import context
import sqlalchemy
import logging

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s:%(name)s:%(message)s")

target_metadata = None

def run_migrations_offline():
	"""Run migrations in 'offline' mode.

	This configures the context with just a URL
	and not an Engine, though an Engine is acceptable
	here as well.  By skipping the Engine creation
	we don't even need a DBAPI to be available.

	Calls to context.execute() here emit the given string to the
	script output.

	"""
	context.configure(url=context.config.get_section_option("lrrbot", "postgres", 'postgresql:///lrrbot'),
		target_metadata=target_metadata, literal_binds=True)

	with context.begin_transaction():
		context.run_migrations()

def run_migrations_online():
	"""Run migrations in 'online' mode.

	In this scenario we need to create an Engine
	and associate a connection with the context.

	"""
	connectable = sqlalchemy.create_engine(context.config.get_section_option("lrrbot", "postgres", 'postgresql:///lrrbot'))

	with connectable.connect() as connection:
		context.configure(connection=connection, target_metadata=target_metadata)

		with context.begin_transaction():
			context.run_migrations()

if context.is_offline_mode():
	run_migrations_offline()
else:
	run_migrations_online()
