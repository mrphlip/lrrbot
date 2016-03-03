revision = '07ea7b63c8fc'
down_revision = '3cecf6a39f78'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.alter_column("cards", "cardid", new_column_name="id")
	alembic.op.alter_column("card_multiverse", "multiverseid", new_column_name="id")
	alembic.op.alter_column("history", "historykey", new_column_name="id")
	alembic.op.alter_column("notification", "notificationkey", new_column_name="id")
	alembic.op.alter_column("quotes", "qid", new_column_name="id")

def downgrade():
	alembic.op.alter_column("cards", "id", new_column_name="cardid")
	alembic.op.alter_column("card_multiverse", "id", new_column_name="multiverseid")
	alembic.op.alter_column("history", "id", new_column_name="historykey")
	alembic.op.alter_column("notification", "id", new_column_name="notificationkey")
	alembic.op.alter_column("quotes", "id", new_column_name="qid")
