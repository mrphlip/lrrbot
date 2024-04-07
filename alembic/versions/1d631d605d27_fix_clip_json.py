revision = '1d631d605d27'
down_revision = '3b866be530cb'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy
import json

def upgrade():
	conn = alembic.context.get_context().bind
	meta = sqlalchemy.MetaData()
	meta.reflect(conn)
	clips = meta.tables["clips"]

	for clipid, clipjson in conn.execute(sqlalchemy.select(clips.c.id, clips.c.data)):
		conn.execute(clips.update()
			.values(data=json.loads(clipjson))
			.where(clips.c.id == clipid)
		)

def downgrade():
	conn = alembic.context.get_context().bind
	meta = sqlalchemy.MetaData()
	meta.reflect(conn)
	clips = meta.tables["clips"]

	for clipid, clipjson in conn.execute(sqlalchemy.select(clips.c.id, clips.c.data)):
		conn.execute(clips.update()
			.values(data=json.dumps(clipjson))
			.where(clips.c.id == clipid)
		)
