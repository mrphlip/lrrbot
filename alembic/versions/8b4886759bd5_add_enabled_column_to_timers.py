revision = '8b4886759bd5'
down_revision = 'df143fed1812'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.add_column('timers',
		sqlalchemy.Column('enabled', sqlalchemy.Boolean, nullable=False, server_default='true')
	)

def downgrade():
	alembic.op.drop_column('timers', 'enabled')
