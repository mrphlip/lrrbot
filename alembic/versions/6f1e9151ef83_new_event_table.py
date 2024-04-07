revision = '6f1e9151ef83'
down_revision = 'e966a3afd100'
branch_labels = None
depends_on = None

import alembic
import dateutil.parser
import sqlalchemy
from sqlalchemy.dialects import postgresql

def upgrade():
	events = alembic.op.create_table('events',
		sqlalchemy.Column('id', sqlalchemy.Integer, primary_key=True),
		sqlalchemy.Column('event', sqlalchemy.Text, nullable=False),
		sqlalchemy.Column('data', postgresql.JSONB, nullable=False),
		sqlalchemy.Column('time', sqlalchemy.DateTime(timezone=True), nullable=False),
	)

	conn = alembic.context.get_context().bind
	meta = sqlalchemy.MetaData()
	meta.reflect(conn)
	notification = meta.tables['notification']

	notifications = conn.execute(sqlalchemy.select(
		notification.c.message, notification.c.subuser, notification.c.useravatar,
		notification.c.eventtime, notification.c.monthcount
	).where(~notification.c.test))

	all_events = []
	for message, subuser, useravatar, eventtime, monthcount in notifications:
		if eventtime is None:
			continue
		if subuser is not None:
			data = {'name': subuser}
			if useravatar is not None:
				data['avatar'] = useravatar
			if monthcount is not None:
				data['monthcount'] = monthcount
				all_events.append({
					'event': 'twitch-resubscription',
					'data': data,
					'time': eventtime,
				})
			else:
				all_events.append({
					'event': 'twitch-subscription',
					'data': data,
					'time': eventtime,
				})
		else:
			all_events.append({
				'event': 'twitch-message',
				'data': {
					'message': message,
				},
				'time': eventtime,
			})
	alembic.op.bulk_insert(events, all_events)

	alembic.op.drop_table('notification')

def downgrade():
	notification = alembic.op.create_table("notification",
		sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
		sqlalchemy.Column("message", sqlalchemy.Text(collation="en_US.utf8")),
		sqlalchemy.Column("channel", sqlalchemy.Text(collation="en_US.utf8")),
		sqlalchemy.Column("subuser", sqlalchemy.Text(collation="en_US.utf8")),
		sqlalchemy.Column("useravatar", sqlalchemy.Text(collation="en_US.utf8")),
		sqlalchemy.Column("eventtime", sqlalchemy.DateTime(timezone=True), nullable=True),
		sqlalchemy.Column("monthcount", sqlalchemy.Integer, nullable=True),
		sqlalchemy.Column("test", sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.false()),
	)
	alembic.op.create_index("notification_idx1", "notification", ["eventtime"])

	conn = alembic.context.get_context().bind
	meta = sqlalchemy.MetaData()
	meta.reflect(conn)
	events = meta.tables['events']

	all_events = conn.execute(sqlalchemy.select(events.c.event, events.c.data, events.c.time).where(events.c.event.in_({'notification', 'twitch-subscriber'})))
	notifications = []
	for event, data, time in all_events:
		if event in {'twitch-subscription', 'twitch-resubscription'}:
			message = '%(name)s just subscribed!' % data
			if data['monthcount'] is not None:
				message += ' %(monthcount)d months in a row!' % data
			notifications.append({
				'message': message,
				'channel': alembic.context.config.get_section_option("lrrbot", "channel", "loadingreadyrun"),
				'subuser': data['name'],
				'useravatar': data['avatar'],
				'eventtime': time,
				'monthcount': data['monthcount'],
				'test': False,
			})
		elif event == 'twitch-message':
			notifications.append({
				'message': data['message'],
				'channel': alembic.context.config.get_section_option("lrrbot", "channel", "loadingreadyrun"),
				'subuser': None,
				'useravatar': None,
				'eventtime': time,
				'monthcount': None,
				'test': False,
			})
	alembic.op.bulk_insert(notification, notifications)

	alembic.op.drop_table('events')
