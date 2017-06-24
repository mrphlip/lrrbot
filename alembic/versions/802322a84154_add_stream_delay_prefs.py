revision = '802322a84154'
down_revision = '85037b8270b2'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.add_column('users',
		sqlalchemy.Column('stream_delay', sqlalchemy.Integer, nullable=False, server_default='10')
	)
	alembic.op.add_column('users',
		sqlalchemy.Column('chat_timestamps', sqlalchemy.Integer, nullable=False, server_default='0')
	)
	alembic.op.add_column('users',
		sqlalchemy.Column('chat_timestamps_24hr', sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.true())
	)
	alembic.op.add_column('users',
		sqlalchemy.Column('chat_timestamps_secs', sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.false())
	)

def downgrade():
	alembic.op.drop_column('users', 'stream_delay')
	alembic.op.drop_column('users', 'chat_timestamps')
	alembic.op.drop_column('users', 'chat_timestamps_24hr')
	alembic.op.drop_column('users', 'chat_timestamps_secs')
