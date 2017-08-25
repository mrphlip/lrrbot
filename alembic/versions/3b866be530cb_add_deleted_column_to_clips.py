revision = '3b866be530cb'
down_revision = '802322a84154'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.add_column('clips',
		sqlalchemy.Column('deleted', sqlalchemy.Boolean, nullable=False, server_default='false')
	)

def downgrade():
	alembic.op.drop_column('clips', 'deleted')
