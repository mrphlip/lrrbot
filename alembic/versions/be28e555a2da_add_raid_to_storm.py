revision = 'be28e555a2da'
down_revision = 'ee81e255ddc0'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.add_column('storm',
		sqlalchemy.Column('twitch-raid', sqlalchemy.Integer, nullable=False, server_default='0')
	)

def downgrade():
	alembic.op.drop_column('storm', 'twitch-raid')
