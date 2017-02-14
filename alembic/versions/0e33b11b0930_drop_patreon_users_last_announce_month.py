revision = '0e33b11b0930'
down_revision = '286bd48821dd'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.drop_column('patreon_users', 'last_announce_month')

def downgrade():
	alembic.op.add_column('patreon_users', sqlalchemy.Column("last_announce_month", sqlalchemy.Integer))
