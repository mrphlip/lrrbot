revision = '10250cd94386'
down_revision = '0e33b11b0930'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.add_column('cards',
		sqlalchemy.Column('hidden', sqlalchemy.Boolean, nullable=False, server_default='false')
	)

def downgrade():
	alembic.op.drop_column('cards', 'hidden')
