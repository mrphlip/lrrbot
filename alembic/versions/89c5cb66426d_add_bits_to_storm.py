revision = '89c5cb66426d'
down_revision = '5aa73ff113c3'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.add_column('storm',
		sqlalchemy.Column('twitch-cheer', sqlalchemy.Integer, nullable=False, server_default='0')
	)

def downgrade():
	alembic.op.drop_column('storm', 'twitch-cheer')
