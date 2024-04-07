revision = 'affc03cb46f5'
down_revision = '988883a6be1d'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy
import json
import itertools
import requests
import logging
import urllib.parse

log = logging.getLogger("affc03cb46f5_game_data")

def upgrade():
	conn = alembic.context.get_context().bind
	meta = sqlalchemy.MetaData()
	meta.reflect(conn)
	users = meta.tables["users"]
	all_users = dict(conn.execute(sqlalchemy.select(users.c.name, users.c.id)).fetchall())

	shows = alembic.op.create_table(
		"shows",
		sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
		sqlalchemy.Column("string_id", sqlalchemy.Text, nullable=False, unique=True),
		sqlalchemy.Column("name", sqlalchemy.Text, nullable=False),
	)

	alembic.op.execute(sqlalchemy.schema.CreateSequence(sqlalchemy.Sequence("games_id_seq", start=-1, increment=-1)))
	games = alembic.op.create_table(
		"games",
		sqlalchemy.Column("id", sqlalchemy.Integer, sqlalchemy.Sequence("game_id_seq"), primary_key=True, server_default=sqlalchemy.func.nextval('games_id_seq')),
		sqlalchemy.Column("name", sqlalchemy.Text, unique=True, nullable=False),
	)
	alembic.op.execute("ALTER SEQUENCE games_id_seq OWNED BY games.id")

	game_per_show_data = alembic.op.create_table(
		"game_per_show_data",
		sqlalchemy.Column("game_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("games.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("show_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("shows.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("display_name", sqlalchemy.Text),
		sqlalchemy.Column("verified", sqlalchemy.Boolean),
	)
	alembic.op.create_primary_key("game_per_show_data_pk", "game_per_show_data", ["game_id", "show_id"])

	stats = alembic.op.create_table(
		"stats",
		sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
		sqlalchemy.Column("string_id", sqlalchemy.Text, nullable=False, unique=True),
		sqlalchemy.Column("singular", sqlalchemy.Text),
		sqlalchemy.Column("plural", sqlalchemy.Text),
		sqlalchemy.Column("emote", sqlalchemy.Text),
	)

	game_stats = alembic.op.create_table(
		"game_stats",
		sqlalchemy.Column("game_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("games.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("show_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("shows.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("stat_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("shows.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("count", sqlalchemy.Integer, nullable=False),
	)
	alembic.op.create_primary_key("game_stats_pk", "game_stats", ["game_id", "show_id", "stat_id"])

	game_votes = alembic.op.create_table(
		"game_votes",
		sqlalchemy.Column("game_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("games.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("show_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("shows.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("vote", sqlalchemy.Boolean, nullable=False),
	)
	alembic.op.create_primary_key("game_votes_pk", "game_votes", ["game_id", "show_id", "user_id"])

	disabled_stats = alembic.op.create_table(
		"disabled_stats",
		sqlalchemy.Column("show_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("shows.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
		sqlalchemy.Column("stat_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("stats.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False),
	)
	alembic.op.create_primary_key("disabled_stats_pk", "disabled_stats", ["show_id", "stat_id"])

	# Move data
	datafile = alembic.context.config.get_section_option("lrrbot", "datafile", "data.json")
	clientid = alembic.context.config.get_section_option("lrrbot", "twitch_clientid")
	clientsecret = alembic.context.config.get_section_option("lrrbot", "twitch_clientsecret")
	try:
		with open(datafile) as f:
			data = json.load(f)
	except FileNotFoundError:
		data = {}

	# stats
	alembic.op.bulk_insert(stats, [{
		"string_id": string_id,
		"emote": values.get("emote"),
		"plural": values.get("plural"),
		"singular": values.get("singular"),
	} for string_id, values in data.get("stats", {}).items()])
	all_stats = dict(conn.execute(sqlalchemy.select(stats.c.string_id, stats.c.id)).fetchall())

	# shows
	alembic.op.bulk_insert(shows, [{
		"string_id": show,
		"name": values["name"],
	} for show, values in data.get("shows", {}).items()])
	all_shows = dict(conn.execute(sqlalchemy.select(shows.c.string_id, shows.c.id)).fetchall())

	# games
	def parse_id(id):
		if id is None:
			return None
		try:
			return int(id)
		except ValueError:
			return None
	for show in data.get("shows", {}).values():
		for game_id, game in show.get("games", {}).items():
			game_id = parse_id(game_id) or parse_id(game.get("id"))
			if game_id is None:
				conn.execute(sqlalchemy.text("INSERT INTO games (name) VALUES (:name) ON CONFLICT (name) DO NOTHING"), {"name": game["name"]})
			else:
				conn.execute(sqlalchemy.text("""
					INSERT INTO games (
						id,
						name
					) VALUES (
						%(id)s,
						%(name)s
					) ON CONFLICT (name) DO UPDATE SET
						id = EXCLUDED.id
				"""), {"id": game_id, "name": game["name"]})
	all_games = dict(conn.execute(sqlalchemy.select(games.c.name, games.c.id)).fetchall())

	# game_per_show_data
	display_names = []
	for show_id, show in data.get("shows", {}).items():
		for game in show.get("games", {}).values():
			if "display" in game:
				display_names.append({
					"show_id": all_shows[show_id],
					"game_id": parse_id(game.get("id")) or all_games[game["name"]],
					"display_name": game["display"],
				})
	alembic.op.bulk_insert(game_per_show_data, display_names)

	# game_stats
	all_game_stats = []
	for show_id, show in data.get("shows", {}).items():
		for game in show.get("games", {}).values():
			game_id = parse_id(game.get("id")) or all_games[game["name"]]
			for stat, count in game.get("stats", {}).items():
				all_game_stats.append({
					"show_id": all_shows[show_id],
					"game_id": game_id,
					"stat_id": all_stats[stat],
					"count": count,
				})
	alembic.op.bulk_insert(game_stats, all_game_stats)

	# game_votes
	all_votes = []
	with requests.Session() as session:
		req = session.post('https://id.twitch.tv/oauth2/token', params={
			'client_id': clientid,
			'client_secret': clientsecret,
			'grant_type': 'client_credentials',
		})
		req.raise_for_status()
		token = req.json()['access_token']

		for show_id, show in data.get("shows", {}).items():
			for game in show.get("games", {}).values():
				game_id = parse_id(game.get("id")) or all_games[game["name"]]
				for nick, vote in game.get("votes", {}).items():
					if nick not in all_users:
						try:
							req = session.get(
								"https://api.twitch.tv/helix/users?login=%s" % urllib.parse.quote(nick),
								headers={'Client-ID': clientid, 'Authorization': f'Bearer {token}'})
							req.raise_for_status()
							user = req.json()['data'][0]
							all_users[nick] = user["id"]
							alembic.op.bulk_insert(users, [{
								"id": user["id"],
								"name": user["login"],
								"display_name": user.get("display_name"),
							}])
						except Exception:
							log.exception("Failed to fetch data for %r", nick)
							all_users[nick] = None
					if all_users[nick] is None:
						continue
					all_votes.append({
						"show_id": all_shows[show_id],
						"game_id": game_id,
						"user_id": all_users[nick],
						"vote": vote,
					})
	alembic.op.bulk_insert(game_votes, all_votes)

	# disabled_stats
	if "swiftlycam" in all_shows:
		for_cameron = []
		if "death" in all_stats:
			for_cameron.append({
				"show_id": all_shows["swiftlycam"],
				"stat_id": all_stats["death"]
			})
		if "tilt" in all_stats:
			for_cameron.append({
				"show_id": all_shows["swiftlycam"],
				"stat_id": all_stats["tilt"]
			})
		if "pave" in all_stats:
			for_cameron.append({
				"show_id": all_shows["swiftlycam"],
				"stat_id": all_stats["pave"],
			})
		alembic.op.bulk_insert(disabled_stats, for_cameron)

	alembic.op.add_column("quotes", sqlalchemy.Column("game_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("games.id", ondelete="CASCADE", onupdate="CASCADE")))
	alembic.op.add_column("quotes", sqlalchemy.Column("show_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("shows.id", ondelete="CASCADE", onupdate="CASCADE")))
	alembic.op.execute("""
		UPDATE quotes
		SET
			show_id = shows.id
		FROM shows
		WHERE quotes.show = shows.name
	""")
	alembic.op.execute("""
		UPDATE quotes
		SET
			game_id = game_per_show_data.game_id
		FROM game_per_show_data
		WHERE quotes.game = game_per_show_data.display_name AND game_per_show_data.show_id = quotes.show_id
	""")
	alembic.op.execute("""
		UPDATE quotes
		SET
			game_id = games.id
		FROM games
		WHERE quotes.game = games.name
	""")
	alembic.op.drop_column("quotes", "game")
	alembic.op.drop_column("quotes", "show")

	data.pop("shows", None)
	data.pop("stats", None)
	with open(datafile, "w") as f:
		json.dump(data, f, indent=2, sort_keys=True)

def downgrade():
	conn = alembic.context.get_context().bind
	meta = sqlalchemy.MetaData()
	meta.reflect(conn)

	datafile = alembic.context.config.get_section_option("lrrbot", "datafile", "data.json")
	try:
		with open(datafile) as f:
			data = json.load(f)
	except FileNotFoundError:
		data = {}

	data["stats"] = {}
	stats = meta.tables["stats"]
	for id, singular, plural, emote in conn.execute(sqlalchemy.select(stats.c.string_id, stats.c.singular, stats.c.plural, stats.c.emote)):
		data["stats"][id] = {}
		if singular is not None:
			data["stats"][id]["singular"] = singular
		if plural is not None:
			data["stats"][id]["plural"] = plural
		if emote is not None:
			data["stats"][id]["emote"] = emote

	data["shows"] = {}
	shows = meta.tables["shows"]
	games = meta.tables["games"]
	game_per_show_data = meta.tables["game_per_show_data"]
	game_votes = meta.tables["game_votes"]
	game_stats = meta.tables["game_stats"]
	users = meta.tables["users"]
	for fkey, id, name in conn.execute(sqlalchemy.select(shows.c.id, shows.c.string_id, shows.c.name)).fetchall():
		data["shows"][id] = {"name": name, "games": {}}
		query = sqlalchemy.select(games.c.id, games.c.name, stats.c.string_id, game_stats.c.count)
		query = query.select_from(
			game_stats
				.join(games, game_stats.c.game_id == games.c.id)
				.join(stats, game_stats.c.stat_id == stats.c.id)
		)
		query = query.where(game_stats.c.show_id == fkey)
		for game_id, name, stat_id, count in conn.execute(query).fetchall():
			if game_id < 0:
				game_id = name
			else:
				game_id = str(game_id)
			data["shows"][id]["games"].setdefault(game_id, {"id": game_id, "name": name, "stats": {}, "votes": {}})["stats"][stat_id] = count
		query = sqlalchemy.select(games.c.id, games.c.name, users.c.name, game_votes.c.vote)
		query = query.select_from(
			game_votes
				.join(games, game_votes.c.game_id == games.c.id)
				.join(users, game_votes.c.user_id == users.c.id)
		)
		query = query.where(game_votes.c.show_id == fkey)
		for game_id, name, user, vote in conn.execute(query).fetchall():
			if game_id < 0:
				game_id = name
			else:
				game_id = str(game_id)
			data["shows"][id]["games"].setdefault(game_id, {"id": game_id, "name": name, "stats": {}, "votes": {}})["votes"][user] = vote
		query = sqlalchemy.select(games.c.id, games.c.name, game_per_show_data.c.display_name)
		query = query.select_from(
			game_per_show_data.join(games, game_per_show_data.c.game_id == games.c.id)
		)
		query = query.where(game_per_show_data.c.show_id == fkey)
		for game_id, name, display_name in conn.execute(query).fetchall():
			if game_id < 0:
				game_id = name
			else:
				game_id = str(game_id)
			if display_name is not None:
				data["shows"][id]["games"].setdefault(game_id, {"id": game_id, "name": name, "stats": {}, "votes": {}})["display"] = display_name

	alembic.op.add_column("quotes", sqlalchemy.Column("game", sqlalchemy.Text))
	alembic.op.add_column("quotes", sqlalchemy.Column("show", sqlalchemy.Text))
	alembic.op.execute("""
		UPDATE quotes
		SET
			show = shows.name
		FROM shows
		WHERE quotes.show_id = shows.id
	""")
	alembic.op.execute("""
		UPDATE quotes
		SET
			game = games.name
		FROM games
		WHERE quotes.game_id = games.id
	""")
	alembic.op.execute("""
		UPDATE quotes
		SET
			game = game_per_show_data.display_name
		FROM game_per_show_data
		WHERE quotes.game_id = game_per_show_data.game_id AND game_per_show_data.show_id = quotes.show_id
	""")
	alembic.op.drop_column("quotes", "game_id")
	alembic.op.drop_column("quotes", "show_id")

	alembic.op.drop_table("disabled_stats")
	alembic.op.drop_table("game_votes")
	alembic.op.drop_table("game_stats")
	alembic.op.drop_table("stats")
	alembic.op.drop_table("game_per_show_data")
	alembic.op.drop_table("games")
	alembic.op.drop_table("shows")

	with open(datafile, "w") as f:
		json.dump(data, f, indent=2, sort_keys=True)
