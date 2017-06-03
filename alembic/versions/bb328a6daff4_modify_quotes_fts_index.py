revision = 'bb328a6daff4'
down_revision = '89c5cb66426d'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.drop_index("quotes_ftx_idx")
	alembic.op.create_index("quote_context_ftx_idx", "quotes", [sqlalchemy.text("TO_TSVECTOR('english', quote || ' ' || COALESCE(context, ''))")], postgresql_using="gin")

def downgrade():
	alembic.op.drop_index("quote_context_ftx_idx")
	alembic.op.create_index("quotes_ftx_idx", "quotes", [sqlalchemy.text("TO_TSVECTOR('english', quote)")], postgresql_using="gin")
