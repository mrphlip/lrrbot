revision = 'f63e1a13dfe5'
down_revision = 'd24b55f6f078'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy
from sqlalchemy.schema import Sequence, CreateSequence, DropSequence

def upgrade():
	# Create an auto-increment sequence for cards.id
	conn = alembic.context.get_context().bind
	meta = sqlalchemy.MetaData()
	meta.reflect(conn)
	cards = meta.tables['cards']
	# This table already has a (not-previously-used) auto-increment sequence in
	# the production DB, but new DBs created from scratch via the alembic setup
	# won't have it, so check if it already exists and create if it's missing
	# to bring everything back into sync
	if not cards.c.id.server_default or 'cards_id_seq' not in cards.c.id.server_default.arg.text:
		maxid, = conn.execute(sqlalchemy.select(sqlalchemy.func.max(cards.c.id))).first()
		if maxid is None:
			maxid = 0
		alembic.op.execute(CreateSequence(Sequence('cards_id_seq', start=maxid + 1)))
		alembic.op.alter_column("cards", "id", nullable=False, server_default=sqlalchemy.text("nextval('cards_id_seq'::regclass)"))

	# Add cards.game column
	# create it with a default but then remove the default, to set the value on
	# all existing rows, but have the column mandatory in the future
	alembic.op.drop_index("cards_name_idx")
	alembic.op.add_column('cards',
		sqlalchemy.Column('game', sqlalchemy.Integer, nullable=False, server_default='1')
	)
	alembic.op.alter_column("cards", "game", server_default=None)
	alembic.op.create_index("cards_name_idx", "cards", ["game", "filteredname"], unique=True)

def downgrade():
	# Remove any non-MTG cards from the DB, and them drop game column
	alembic.op.execute("""
		DELETE FROM cards
			WHERE game != 1
	""")
	alembic.op.drop_index("cards_name_idx")
	alembic.op.drop_column('cards', 'game')
	alembic.op.create_index("cards_name_idx", "cards", ["filteredname"], unique=True)

	# Remove auto-increment sequence from cards.id
	alembic.op.alter_column("cards", "id", server_default=None)
	alembic.op.execute(DropSequence(Sequence('cards_id_seq')))
