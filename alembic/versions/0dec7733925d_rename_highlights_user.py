revision = '0dec7733925d'
down_revision = '7c9bbf3a039a'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.alter_column('highlights', 'user', new_column_name="user_id")

def downgrade():
	alembic.op.alter_column('highlights', 'user_id', new_column_name="user")
