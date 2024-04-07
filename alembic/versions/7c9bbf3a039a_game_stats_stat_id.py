revision = '7c9bbf3a039a'
down_revision = '89c5cb66426d'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	conn = alembic.context.get_context().bind
	meta = sqlalchemy.MetaData()
	meta.reflect(conn)
	game_stats = meta.tables["game_stats"]
	shows = meta.tables["shows"]

	constraint_name = None
	for fk in game_stats.c.stat_id.foreign_keys:
		if fk.column.table is shows and fk.column.name == "id":
			constraint_name = fk.name
			break
	else:
		raise Exception("Failed to find a foreign key on `game_stats.stat_id` that references `shows.id`")

	alembic.op.drop_constraint(constraint_name, 'game_stats')
	alembic.op.create_foreign_key(constraint_name, 'game_stats', 'stats', ["stat_id"], ["id"], onupdate="CASCADE", ondelete="CASCADE")

def downgrade():
	conn = alembic.context.get_context().bind
	meta = sqlalchemy.MetaData()
	meta.reflect(conn)
	game_stats = meta.tables["game_stats"]
	stats = meta.tables["stats"]

	constraint_name = None
	for fk in game_stats.c.stat_id.foreign_keys:
		if fk.column.table is stats and fk.column.name == "id":
			constraint_name = fk.name
			break
	else:
		raise Exception("Failed to find a foreign key on `game_stats.stat_id` that references `stats.id`")

	alembic.op.drop_constraint(constraint_name, 'game_stats')
	alembic.op.create_foreign_key(constraint_name, 'game_stats', 'shows', ["stat_id"], ["id"], onupdate="CASCADE", ondelete="CASCADE")
