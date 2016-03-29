revision = '988883a6be1d'
down_revision = 'd88d63c07199'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.add_column('quotes',
 		sqlalchemy.Column('context', sqlalchemy.Text, nullable=True)
	)
	alembic.op.add_column('quotes',
 		sqlalchemy.Column('game', sqlalchemy.Text, nullable=True)
	)
	alembic.op.add_column('quotes',
 		sqlalchemy.Column('show', sqlalchemy.Text, nullable=True)
	)

def downgrade():
	alembic.op.drop_column('quotes', 'context')
	alembic.op.drop_column('quotes', 'game')
	alembic.op.drop_column('quotes', 'show')
