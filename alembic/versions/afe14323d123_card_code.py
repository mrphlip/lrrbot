revision = 'afe14323d123'
down_revision = '5befde5a4b5f'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.rename_table("card_multiverse", "card_codes")
	alembic.op.alter_column("card_codes", "id", new_column_name="code", type_=sqlalchemy.Text, nullable=False)
	alembic.op.add_column("card_codes", sqlalchemy.Column("game", sqlalchemy.Integer, nullable=False, server_default='1'))
	alembic.op.alter_column("card_codes", "game", server_default=None)

def downgrade():
	alembic.op.execute("DELETE FROM card_codes WHERE game != 1")
	alembic.op.drop_column("card_codes", "game")
	alembic.op.alter_column("card_codes", "code", new_column_name="id", type_=sqlalchemy.Integer, nullable=False, postgresql_using="code::integer")
	alembic.op.rename_table("card_codes", "card_multiverse")
