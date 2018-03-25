revision = 'a933db158324'
down_revision = '7d1d0f735480'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.drop_table("game_stats")
	alembic.op.drop_table("game_votes")
	alembic.op.drop_table("disabled_stats")
	alembic.op.drop_table("stats")

def downgrade():
	alembic.op.create_table(
		"stats",
		sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
		sqlalchemy.Column("string_id", sqlalchemy.Text, nullable=False, unique=True),
		sqlalchemy.Column("singular", sqlalchemy.Text),
		sqlalchemy.Column("plural", sqlalchemy.Text),
		sqlalchemy.Column("emote", sqlalchemy.Text),
	)

	alembic.op.create_table(
		"disabled_stats",
		sqlalchemy.Column("show_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("shows.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("stat_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("stats.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
	)
	alembic.op.create_primary_key("disabled_stats_pk", "disabled_stats", ["show_id", "stat_id"])
	alembic.op.create_index('disabled_stats_show_id_idx', 'disabled_stats', ['show_id'])
	alembic.op.create_index('disabled_stats_stat_id_idx', 'disabled_stats', ['stat_id'])

	game_votes = alembic.op.create_table(
		"game_votes",
		sqlalchemy.Column("game_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("games.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("show_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("shows.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("vote", sqlalchemy.Boolean, nullable=False),
	)
	alembic.op.create_primary_key("game_votes_pk", "game_votes", ["game_id", "show_id", "user_id"])
	alembic.op.create_index('game_votes_game_id_idx', 'game_votes', ['game_id'])
	alembic.op.create_index('game_votes_show_id_idx', 'game_votes', ['show_id'])
	alembic.op.create_index('game_votes_user_id_idx', 'game_votes', ['user_id'])

	game_stats = alembic.op.create_table(
		"game_stats",
		sqlalchemy.Column("game_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("games.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("show_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("shows.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("stat_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("shows.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("count", sqlalchemy.Integer, nullable=False),
	)
	alembic.op.create_primary_key("game_stats_pk", "game_stats", ["game_id", "show_id", "stat_id"])
	alembic.op.create_index('game_stats_game_id_idx', 'game_stats', ['game_id'])
	alembic.op.create_index('game_stats_show_id_idx', 'game_stats', ['show_id'])
	alembic.op.create_index('game_stats_stat_id_idx', 'game_stats', ['stat_id'])
