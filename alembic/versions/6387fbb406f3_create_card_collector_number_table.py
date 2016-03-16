revision = '6387fbb406f3'
down_revision = '07ea7b63c8fc'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.create_table(
		"card_collector",
		sqlalchemy.Column("setid", sqlalchemy.String(10), nullable=False),
		sqlalchemy.Column("collector", sqlalchemy.String(10), nullable=False),
		sqlalchemy.Column("cardid", sqlalchemy.Integer, sqlalchemy.ForeignKey("cards.id", ondelete="CASCADE"), nullable=False),
	)
	alembic.op.create_primary_key(None, "card_collector", ["setid", "collector"])

def downgrade():
	alembic.op.drop_table("card_collector")
