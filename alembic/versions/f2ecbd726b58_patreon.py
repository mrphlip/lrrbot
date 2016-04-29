revision = 'f2ecbd726b58'
down_revision = 'd88d63c07199'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.add_column("users", sqlalchemy.Column("patreon_access_token", sqlalchemy.Text))
	alembic.op.add_column("users", sqlalchemy.Column("patreon_refresh_token", sqlalchemy.Text))
	alembic.op.add_column("users", sqlalchemy.Column("patreon_token_expires", sqlalchemy.DateTime(timezone=True)))

def downgrade():
	alembic.op.drop_column("users", "patreon_access_token")
	alembic.op.drop_column("users", "patreon_refresh_token")
	alembic.op.drop_column("users", "patreon_token_expires")
