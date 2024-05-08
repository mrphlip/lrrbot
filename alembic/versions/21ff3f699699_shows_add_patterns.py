revision = '21ff3f699699'
down_revision = '0d4025daec6e'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy
import re

def upgrade():
	alembic.op.add_column("shows", sqlalchemy.Column("pattern", sqlalchemy.Text, nullable=True))

	conn = alembic.context.get_bind()

	patterns = {}
	for show_id, name in conn.execute(sqlalchemy.text("SELECT id, name FROM shows WHERE string_id != '' ORDER BY id DESC")):
		patterns[re.escape(name.lower())] = show_id

	conn.execute(sqlalchemy.text("UPDATE shows SET pattern = :pattern WHERE id = :id"), [
		{"id": show_id, "pattern": pattern}
		for pattern, show_id in patterns.items()
	])

def downgrade():
	alembic.op.drop_column("shows", "pattern")
