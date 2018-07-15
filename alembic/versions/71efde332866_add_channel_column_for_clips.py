revision = '71efde332866'
down_revision = '5eb5bcb0ecdd'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.add_column('clips',
		sqlalchemy.Column('channel', sqlalchemy.String(255, collation="en_US.utf8"), nullable=False, server_default="''")
	)
	alembic.op.execute("""
		UPDATE clips
			SET channel = data->'broadcaster'->>'name'
	""")

def downgrade():
	alembic.op.drop_column('storm', 'twitch-cheer')
