revision = '85037b8270b2'
down_revision = '10250cd94386'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy
from sqlalchemy.dialects import postgresql

def upgrade():
	clips = alembic.op.create_table("clips",
		sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
		sqlalchemy.Column("slug", sqlalchemy.String(255), nullable=False),
		sqlalchemy.Column("title", sqlalchemy.String(255), nullable=False),
		sqlalchemy.Column("vodid", sqlalchemy.String(16), nullable=True),
		sqlalchemy.Column("time", sqlalchemy.DateTime(timezone=True), nullable=False),
		sqlalchemy.Column("rating", sqlalchemy.Boolean, nullable=True),
		sqlalchemy.Column("data", postgresql.JSONB, nullable=False),
	)
	alembic.op.create_index("clips_slug", "clips", ["slug"], unique=True)
	alembic.op.create_index("clips_time", "clips", ["time"])
	alembic.op.create_index("clips_vodid", "clips", ["vodid", "time"])

def downgrade():
	alembic.op.drop_table("clips")
