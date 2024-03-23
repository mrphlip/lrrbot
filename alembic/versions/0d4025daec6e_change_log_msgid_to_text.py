revision = '0d4025daec6e'
down_revision = 'b74cc308b1ec'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.alter_column('log', 'msgid', type_=sqlalchemy.Text)

def downgrade():
	alembic.op.execute("DELETE FROM log WHERE starts_with(target, '&youtube:')")
	alembic.op.alter_column('log', 'msgid', type_=sqlalchemy.UUID, postgresql_using='msgid::uuid')
