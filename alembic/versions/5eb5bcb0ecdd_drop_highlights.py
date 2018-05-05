revision = '5eb5bcb0ecdd'
down_revision = 'a933db158324'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.drop_table('highlights')

def downgrade():
	alembic.op.create_table("highlights",
		sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
		sqlalchemy.Column("title", sqlalchemy.Text, nullable=False),
		sqlalchemy.Column("description", sqlalchemy.Text, nullable=False),
		sqlalchemy.Column("time", sqlalchemy.DateTime(timezone=True), nullable=False),
		sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey('users.id'), nullable=False),
	)
	alembic.op.create_index('highlights_user_idx', 'highlights', ['user_id'])
