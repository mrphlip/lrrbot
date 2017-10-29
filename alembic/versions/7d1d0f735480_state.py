revision = '7d1d0f735480'
down_revision = '1d631d605d27'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy
from sqlalchemy.dialects import postgresql

def upgrade():
	alembic.op.create_table('state',
		sqlalchemy.Column('key', sqlalchemy.Text, primary_key=True),
		sqlalchemy.Column('value', postgresql.JSONB, nullable=False),
	)

def downgrade():
	alembic.op.drop_table('state')
