revision = 'fbef4c1a84db'
down_revision = '72a56f6f1148'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.add_column('clips',
		sqlalchemy.Column('rater', sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id", onupdate="CASCADE", ondelete="SET NULL"))
	)

def downgrade():
	alembic.op.drop_column('clips', 'rater')
