revision = '5befde5a4b5f'
down_revision = '21ff3f699699'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.execute("ALTER TABLE games DROP CONSTRAINT games_name_key")

def downgrade():
	alembic.op.execute("ALTER TABLE games ADD CONSTRAINT games_name_key UNIQUE (name)")
