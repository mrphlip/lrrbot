revision = '7f56063682aa'
down_revision = '643aab2ac6ed'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.drop_column('storm', 'team-james')
	alembic.op.drop_column('storm', 'team-serge')

def downgrade():
	alembic.op.add_column('storm',
		sqlalchemy.Column('team-james', sqlalchemy.Integer, nullable=False, server_default='0')
	)
	alembic.op.add_column('storm',
		sqlalchemy.Column('team-serge', sqlalchemy.Integer, nullable=False, server_default='0')
	)
