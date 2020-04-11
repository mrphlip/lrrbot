revision = 'ee81e255ddc0'
down_revision = 'dd3efe83691d'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.drop_column('cards', 'lastprinted')

def downgrade():
	alembic.op.add_column('cards', sqlalchemy.Column("lastprinted", sqlalchemy.Date))
