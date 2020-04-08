revision = 'dd3efe83691d'
down_revision = '7f56063682aa'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.drop_table('card_collector')

def downgrade():
	alembic.op.create_table(
		"card_collector",
		sqlalchemy.Column("setid", sqlalchemy.String(10), nullable=False),
		sqlalchemy.Column("collector", sqlalchemy.String(10), nullable=False),
		sqlalchemy.Column("cardid", sqlalchemy.Integer, sqlalchemy.ForeignKey("cards.id", ondelete="CASCADE"), nullable=False),
	)
	alembic.op.create_primary_key(None, "card_collector", ["setid", "collector"])
	alembic.op.create_index('card_collector_cardid_idx', 'card_collector', ['cardid'])
