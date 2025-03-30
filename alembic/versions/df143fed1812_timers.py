revision = 'df143fed1812'
down_revision = 'afe14323d123'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.create_table("timers",
		sqlalchemy.Column("id", sqlalchemy.Integer, sqlalchemy.Identity(), primary_key=True),
		sqlalchemy.Column("name", sqlalchemy.Text, nullable=False),
		sqlalchemy.Column("interval", sqlalchemy.Interval, nullable=False),
		sqlalchemy.Column("mode", sqlalchemy.Text, nullable=False),
		sqlalchemy.Column("message", sqlalchemy.Text, nullable=False),
		sqlalchemy.Column("last_run", sqlalchemy.DateTime(timezone=True)),
	)

def downgrade():
	alembic.op.drop_table("timers")
