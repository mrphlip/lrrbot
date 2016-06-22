revision = '5aa73ff113c3'
down_revision = 'cddcdf06d9f9'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.execute("""
		UPDATE events
			SET data = JSONB_SET(data, '{name}', COALESCE(data->'twitch'->'name', data->'patreon'->'full_name'))
			WHERE event = 'patreon-pledge'
	""")

def downgrade():
	alembic.op.execute("""
		UPDATE events
			SET data = data - 'name'
			WHERE event = 'patreon-pledge'
	""")
