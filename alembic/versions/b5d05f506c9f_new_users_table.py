revision = 'b5d05f506c9f'
down_revision = 'fbef4c1a84db'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

LOGIN_PROVIDER_TWITCH = 1
LOGIN_PROVIDER_PATREON = 2

def upgrade():
	alembic.op.rename_table('users', 'old_users')

	users = alembic.op.create_table(
		'users',
		sqlalchemy.Column('id', sqlalchemy.BigInteger, sqlalchemy.Identity(), primary_key=True),
		sqlalchemy.Column('stream_delay', sqlalchemy.Integer, nullable=False, server_default='10'),
		sqlalchemy.Column('chat_timestamps', sqlalchemy.Integer, nullable=False, server_default='0'),
		sqlalchemy.Column('chat_timestamps_24hr', sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.true()),
	  	sqlalchemy.Column('chat_timestamps_secs', sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.false()),
	)

	accounts = alembic.op.create_table(
		'accounts',
		sqlalchemy.Column('id', sqlalchemy.BigInteger, sqlalchemy.Identity(), primary_key=True),
		sqlalchemy.Column('provider', sqlalchemy.Integer, nullable=False),
		sqlalchemy.Column('provider_user_id', sqlalchemy.Text, nullable=False),
		sqlalchemy.Column('user_id', sqlalchemy.BigInteger, sqlalchemy.ForeignKey(users.c.id, onupdate='CASCADE', ondelete='SET NULL')),
		sqlalchemy.Column('name', sqlalchemy.Text, nullable=False),
		sqlalchemy.Column('display_name', sqlalchemy.Text),
		sqlalchemy.Column('access_token', sqlalchemy.Text),
		sqlalchemy.Column('refresh_token', sqlalchemy.Text),
		sqlalchemy.Column('token_expires_at', sqlalchemy.DateTime(timezone=True)),
		sqlalchemy.Column('is_sub', sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.false()),
		sqlalchemy.Column('is_mod', sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.false()),
		# Twitch only
		sqlalchemy.Column('autostatus', sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.false()),
	)
	alembic.op.create_index('accounts_user_id_idx', 'accounts', ['user_id'])
	alembic.op.create_index('accounts_provider_provider_user_id_idx', 'accounts', ['provider', 'provider_user_id'], unique=True)
	alembic.op.create_index('accounts_provider_name_idx', 'accounts', ['provider', 'name'])

	conn = alembic.op.get_bind()

	conn.execute(sqlalchemy.text("""
		INSERT INTO accounts(provider, provider_user_id, name, display_name, access_token, refresh_token, token_expires_at, is_sub, is_mod, autostatus)
		SELECT :provider_twitch, id::text, name, display_name, twitch_oauth, NULL, NULL, is_sub, is_mod, autostatus FROM old_users
		UNION ALL 
		SELECT :provider_patreon, patreon_id, full_name, NULL, access_token, refresh_token, token_expires, pledge_start IS NOT NULL, FALSE, FALSE FROM patreon_users
	"""), {'provider_twitch': LOGIN_PROVIDER_TWITCH, 'provider_patreon': LOGIN_PROVIDER_PATREON})

	apipass_users = list(alembic.context.config.get_section('apipass').keys())

	users_to_create = conn.execute(sqlalchemy.text("""
		SELECT
			old_users.id as id,
			patreon_users.patreon_id as patreon_id,
			old_users.stream_delay as stream_delay,
			old_users.chat_timestamps as chat_timestamps,
			old_users.chat_timestamps_24hr as chat_timestamps_24hr,
			old_users.chat_timestamps_secs as chat_timestamps_secs
		FROM old_users LEFT OUTER JOIN patreon_users ON old_users.patreon_user_id = patreon_users.id 
		WHERE
			old_users.name = ANY(:apipass_users)
				OR old_users.patreon_user_id IS NOT NULL
				OR old_users.stream_delay != 10
				OR old_users.chat_timestamps != 0
				OR old_users.chat_timestamps_24hr != TRUE
				OR old_users.chat_timestamps_secs != FALSE
	"""), {"apipass_users": apipass_users}).all()

	for row in users_to_create:
		user_id = conn.execute(users.insert().returning(users.c.id), {
			'stream_delay': row.stream_delay,
			'chat_timestamps': row.chat_timestamps,
			'chat_timestamps_24hr': row.chat_timestamps_24hr,
			'chat_timestamps_secs': row.chat_timestamps_secs,
		}).scalar_one()

		conn.execute(
			accounts.update()
				.where(
					((accounts.c.provider == LOGIN_PROVIDER_TWITCH) & (accounts.c.provider_user_id == str(row.id))) |
					((accounts.c.provider == LOGIN_PROVIDER_PATREON) & (accounts.c.provider_user_id == row.patreon_id))
				),
			{
				'user_id': user_id,
			}
		)

	alembic.op.add_column('clips', sqlalchemy.Column('rated_by', sqlalchemy.BigInteger, sqlalchemy.ForeignKey(accounts.c.id, onupdate='CASCADE', ondelete='SET NULL')))
	conn.execute(
		sqlalchemy.text("""
			UPDATE clips
			SET rated_by = accounts.id
			FROM accounts
			WHERE clips.rater IS NOT NULL AND accounts.provider = :provider_twitch AND clips.rater::text = accounts.provider_user_id
		"""),
		{
			'provider_twitch': LOGIN_PROVIDER_TWITCH,
		},
	)
	alembic.op.drop_column('clips', 'rater')

	alembic.op.add_column('history', sqlalchemy.Column('changed_by', sqlalchemy.BigInteger, sqlalchemy.ForeignKey(accounts.c.id, onupdate='CASCADE', ondelete='SET NULL')))
	conn.execute(
		sqlalchemy.text("""
			UPDATE history
			SET changed_by = accounts.id
			FROM accounts
			WHERE history.changeuser IS NOT NULL AND accounts.provider = :provider_twitch AND history.changeuser::text = accounts.provider_user_id
		"""),
		{
			'provider_twitch': LOGIN_PROVIDER_TWITCH,
		},
	)
	alembic.op.drop_column('history', 'changeuser')

	alembic.op.drop_table('old_users')
	alembic.op.drop_table('patreon_users')

def downgrade():
	alembic.op.rename_table('users', 'new_users')

	patreon_users = alembic.op.create_table(
		'patreon_users',
		sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
		sqlalchemy.Column("patreon_id", sqlalchemy.Text, unique=True),
		sqlalchemy.Column("full_name", sqlalchemy.Text, nullable=False),

		sqlalchemy.Column("access_token", sqlalchemy.Text),
		sqlalchemy.Column("refresh_token", sqlalchemy.Text),
		sqlalchemy.Column("token_expires", sqlalchemy.DateTime(timezone=True)),

		sqlalchemy.Column("pledge_start", sqlalchemy.DateTime(timezone=True)),
	)

	users = alembic.op.create_table(
		'users',
		sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=False),
		sqlalchemy.Column("name", sqlalchemy.Text, nullable=False),
		sqlalchemy.Column("display_name", sqlalchemy.Text),
		sqlalchemy.Column("twitch_oauth", sqlalchemy.Text),
		sqlalchemy.Column("is_sub", sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.false()),
		sqlalchemy.Column("is_mod", sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.false()),
		sqlalchemy.Column("autostatus", sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.false()),
		sqlalchemy.Column("patreon_user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey(patreon_users.c.id, onupdate="CASCADE", ondelete="SET NULL"), unique=True),
		sqlalchemy.Column('stream_delay', sqlalchemy.Integer, nullable=False, server_default='10'),
		sqlalchemy.Column('chat_timestamps', sqlalchemy.Integer, nullable=False, server_default='0'),
		sqlalchemy.Column('chat_timestamps_24hr', sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.true()),
		sqlalchemy.Column('chat_timestamps_secs', sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.false()),
	)

	conn = alembic.op.get_bind()

	conn.execute(sqlalchemy.text("""
		INSERT INTO patreon_users (patreon_id, full_name, access_token, refresh_token, token_expires, pledge_start)
		SELECT provider_user_id, name, access_token, refresh_token, token_expires_at, CASE WHEN is_sub THEN NOW() END
		FROM accounts
		WHERE provider = :provider_patreon
	"""), {'provider_patreon': LOGIN_PROVIDER_PATREON})

	conn.execute(sqlalchemy.text("""
		INSERT INTO users (
			id,
			name,
			display_name,
			twitch_oauth,
			is_sub,
			is_mod,
			autostatus,
			patreon_user_id,
			stream_delay,
			chat_timestamps,
			chat_timestamps_24hr,
			chat_timestamps_secs
		)
		SELECT
			accounts.provider_user_id::integer,
			accounts.name,
			accounts.display_name,
			accounts.access_token,
			accounts.is_sub,
			accounts.is_mod,
			accounts.autostatus,
			(SELECT id FROM patreon_users WHERE patreon_id = (
					SELECT provider_user_id
					FROM accounts AS patreon_accounts
					WHERE patreon_accounts.user_id = accounts.user_id AND patreon_accounts.provider = :provider_patreon 
			)),
			COALESCE(new_users.stream_delay, 10),
			COALESCE(new_users.chat_timestamps, 0),
			COALESCE(new_users.chat_timestamps_24hr, TRUE),
			COALESCE(new_users.chat_timestamps_secs, FALSE)
		FROM accounts LEFT OUTER JOIN new_users ON new_users.id = accounts.user_id
		WHERE accounts.provider = :provider_twitch 
	"""), {'provider_twitch': LOGIN_PROVIDER_TWITCH, 'provider_patreon': LOGIN_PROVIDER_PATREON})

	alembic.op.add_column('clips', sqlalchemy.Column('rater', sqlalchemy.Integer, sqlalchemy.ForeignKey(users.c.id, onupdate='CASCADE', ondelete='SET NULL')))
	conn.execute(
		sqlalchemy.text("""
			UPDATE clips
			SET rater = accounts.provider_user_id::integer
			FROM accounts
			WHERE clips.rated_by IS NOT NULL AND accounts.provider = :provider_twitch AND clips.rated_by = accounts.id
		"""),
		{
			'provider_twitch': LOGIN_PROVIDER_TWITCH,
		},
	)
	alembic.op.drop_column('clips', 'rated_by')

	alembic.op.add_column('history', sqlalchemy.Column('changeuser', sqlalchemy.Integer, sqlalchemy.ForeignKey(users.c.id, onupdate='CASCADE', ondelete='SET NULL')))
	conn.execute(
		sqlalchemy.text("""
			UPDATE history
			SET changeuser = accounts.provider_user_id::integer
			FROM accounts
			WHERE history.changed_by IS NOT NULL AND accounts.provider = :provider_twitch AND history.changed_by = accounts.id
		"""),
		{
			'provider_twitch': LOGIN_PROVIDER_TWITCH,
		},
	)
	alembic.op.create_index("history_changeuser_idx", "history", ["changeuser"])
	alembic.op.drop_column('history', 'changed_by')

	alembic.op.drop_table('accounts')
	alembic.op.drop_table('new_users')
