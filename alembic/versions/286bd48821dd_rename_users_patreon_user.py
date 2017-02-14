revision = '286bd48821dd'
down_revision = '0dec7733925d'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.alter_column('users', 'patreon_user', new_column_name="patreon_user_id")

def downgrade():
	alembic.op.alter_column('users', 'patreon_user_id', new_column_name="patreon_user")
