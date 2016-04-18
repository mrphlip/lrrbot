revision = '695afc7a0e54'
down_revision = 'affc03cb46f5'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy

def upgrade():
	alembic.op.create_index('card_collector_cardid_idx', 'card_collector', ['cardid'])
	alembic.op.create_index('card_multiverse_cardid_idx', 'card_multiverse', ['cardid'])
	alembic.op.create_index('disabled_stats_show_id_idx', 'disabled_stats', ['show_id'])
	alembic.op.create_index('disabled_stats_stat_id_idx', 'disabled_stats', ['stat_id'])
	alembic.op.create_index('game_per_show_data_game_id_idx', 'game_per_show_data', ['game_id'])
	alembic.op.create_index('game_per_show_data_show_id_idx', 'game_per_show_data', ['show_id'])
	alembic.op.create_index('game_stats_game_id_idx', 'game_stats', ['game_id'])
	alembic.op.create_index('game_stats_show_id_idx', 'game_stats', ['show_id'])
	alembic.op.create_index('game_stats_stat_id_idx', 'game_stats', ['stat_id'])
	alembic.op.create_index('game_votes_game_id_idx', 'game_votes', ['game_id'])
	alembic.op.create_index('game_votes_show_id_idx', 'game_votes', ['show_id'])
	alembic.op.create_index('game_votes_user_id_idx', 'game_votes', ['user_id'])
	alembic.op.create_index('highlights_user_idx', 'highlights', ['user'])
	alembic.op.create_index('history_changeuser_idx', 'history', ['changeuser'])
	alembic.op.create_index('quotes_game_id_idx', 'quotes', ['game_id'])
	alembic.op.create_index('quotes_show_id_idx', 'quotes', ['show_id'])

def downgrade():
	alembic.op.drop_index('card_collector_cardid_idx')
	alembic.op.drop_index('card_multiverse_cardid_idx')
	alembic.op.drop_index('disabled_stats_show_id_idx')
	alembic.op.drop_index('disabled_stats_stat_id_idx')
	alembic.op.drop_index('game_per_show_data_game_id_idx')
	alembic.op.drop_index('game_per_show_data_show_id_idx')
	alembic.op.drop_index('game_stats_game_id_idx')
	alembic.op.drop_index('game_stats_show_id_idx')
	alembic.op.drop_index('game_stats_stat_id_idx')
	alembic.op.drop_index('game_votes_game_id_idx')
	alembic.op.drop_index('game_votes_show_id_idx')
	alembic.op.drop_index('game_votes_user_id_idx')
	alembic.op.drop_index('highlights_user_idx')
	alembic.op.drop_index('history_changeuser_idx')
	alembic.op.drop_index('quotes_game_id_idx')
	alembic.op.drop_index('quotes_show_id_idx')
