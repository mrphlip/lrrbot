revision = '72a56f6f1148'
down_revision = 'be28e555a2da'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	# Remove cascading deletes from quote FKs
	alembic.op.drop_constraint("quotes_game_id_fkey", "quotes", "foreignkey")
	alembic.op.drop_constraint("quotes_show_id_fkey", "quotes", "foreignkey")
	alembic.op.create_foreign_key(
		None, 'quotes', 'games', ['game_id'], ['id'], onupdate="CASCADE", ondelete="SET NULL")
	alembic.op.create_foreign_key(
		None, 'quotes', 'shows', ['show_id'], ['id'], onupdate="CASCADE", ondelete="SET NULL")

def downgrade():
	alembic.op.drop_constraint("quotes_game_id_fkey", "quotes", "foreignkey")
	alembic.op.drop_constraint("quotes_show_id_fkey", "quotes", "foreignkey")
	alembic.op.create_foreign_key(
		None, 'quotes', 'games', ['game_id'], ['id'], onupdate="CASCADE", ondelete="CASCADE")
	alembic.op.create_foreign_key(
		None, 'quotes', 'shows', ['show_id'], ['id'], onupdate="CASCADE", ondelete="CASCADE")
