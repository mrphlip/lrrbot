revision = '643aab2ac6ed'
down_revision = 'f63e1a13dfe5'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.add_column('storm',
		sqlalchemy.Column('team-james', sqlalchemy.Integer, nullable=False, server_default='0')
	)
	alembic.op.add_column('storm',
		sqlalchemy.Column('team-serge', sqlalchemy.Integer, nullable=False, server_default='0')
	)

def downgrade():
	alembic.op.drop_column('storm', 'team-james')
	alembic.op.drop_column('storm', 'team-serge')
