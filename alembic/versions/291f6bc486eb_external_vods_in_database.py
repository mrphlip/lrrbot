revision = '291f6bc486eb'
down_revision = '71efde332866'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	external_channel = alembic.op.create_table("external_channel",
		sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
		sqlalchemy.Column("channel", sqlalchemy.String(255), nullable=False),
	)
	alembic.op.create_index("external_channel_channel", "external_channel", ["channel"], unique=True)

	external_channel = alembic.op.create_table("external_video",
		sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
		sqlalchemy.Column("channel", sqlalchemy.Integer,
			sqlalchemy.ForeignKey("external_channel.id", ondelete="CASCADE")),
		sqlalchemy.Column("vodid", sqlalchemy.String(16), nullable=True),
	)
	alembic.op.create_index("external_video_vodid", "external_video", ["vodid"], unique=True)

def downgrade():
	alembic.op.drop_table("external_video")
	alembic.op.drop_table("external_channel")
