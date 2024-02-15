revision = '66d78d1a29ee'
down_revision = 'b5d05f506c9f'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	for column in ['youtube-membership', 'youtube-membership-milestone', 'youtube-super-chat', 'youtube-super-sticker']:
		alembic.op.add_column('storm', sqlalchemy.Column(column, sqlalchemy.Integer, nullable=False, server_default='0'))

def downgrade():
	for column in ['youtube-membership', 'youtube-membership-milestone', 'youtube-super-chat', 'youtube-super-sticker']:
		alembic.op.drop_column('storm', column)
