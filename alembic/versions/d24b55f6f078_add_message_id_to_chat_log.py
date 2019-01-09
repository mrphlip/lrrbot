revision = 'd24b55f6f078'
down_revision = '291f6bc486eb'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy
from sqlalchemy.dialects.postgresql import UUID

def upgrade():
	alembic.op.add_column('log',
		sqlalchemy.Column('msgid', UUID, nullable=True)
	)
	alembic.op.create_index("log_msgid", "log", ["msgid"], unique=True)

def downgrade():
	alembic.op.drop_column('log', 'msgid')
	pass
