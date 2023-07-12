import sqlalchemy

TABLES = [
	"game_per_show_data",
	"games",
	"quotes",
]

def lock_tables(conn, metadata):
	" Lock all tables that reference the `games` table "
	conn.execute(sqlalchemy.text("LOCK TABLE " + ", ".join(TABLES) + " IN ACCESS EXCLUSIVE MODE"))

def merge_games(conn, metadata, old_id, new_id, result_id):
	"""
	NOT THREADSAFE. Use `lock_tables` before calling `merge_games`. `old_id`, `new_id` and
	`result_id` must already exist in the database.
	"""

	if old_id == result_id and new_id == result_id:
		return

	quotes = metadata.tables["quotes"]
	conn.execute(quotes.update().where(quotes.c.game_id.in_({old_id, new_id})), {
		"game_id": result_id,
	})

	game_per_show_data = metadata.tables["game_per_show_data"]
	try:
		with conn.begin_nested():
			conn.execute(game_per_show_data.update()
				.where(game_per_show_data.c.game_id.in_({old_id, new_id})), {
				"game_id": result_id,
			})
	except sqlalchemy.exc.IntegrityError:
		with conn.begin_nested():
			res = conn.execute(sqlalchemy.select(
				game_per_show_data.c.show_id, game_per_show_data.c.display_name,
				game_per_show_data.c.verified
			).where(game_per_show_data.c.game_id == old_id))

			data = {
				show_id: (display_name, verified)
				for show_id, display_name, verified in res
			}

			res = conn.execute(sqlalchemy.select(
				game_per_show_data.c.show_id, game_per_show_data.c.display_name,
				game_per_show_data.c.verifed
			).where(game_per_show_data.c.game_id == new_id))

			for show_id, new_display_name, new_verified in res:
				old_display_name, old_verified = data.get(show_id, (None, None))
				data[show_id] = (
					new_display_name or old_display_name,
					new_verified if new_verified is not None else old_verified
				)

			conn.execute(game_per_show_data.delete()
				.where(game_per_show_data.c.game_id.in_({old_id, new_id})))
			conn.execute(game_per_show_data.insert(), [
				{
					"game_id": result_id,
					"show_id": show_id,
					"display_name": display_name,
					"verified": verified,
				}
				for show_id, (display_name, verified) in data.items()
			])

	games = metadata.tables["games"]
	conn.execute(games.delete().where(games.c.id.in_({old_id, new_id} - {result_id})))
