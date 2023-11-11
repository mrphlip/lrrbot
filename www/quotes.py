import flask

import sqlalchemy
import www.utils
from www import server
from www import login
import common.postgres

QUOTES_PER_PAGE = 25

blueprint = flask.Blueprint('quotes', __name__)

@blueprint.route('/')
@blueprint.route('/<int:page>')
@login.with_session
def quotes(session, page=1):
	quotes = server.db.metadata.tables["quotes"]
	games = server.db.metadata.tables["games"]
	shows = server.db.metadata.tables["shows"]
	game_per_show_data = server.db.metadata.tables["game_per_show_data"]
	with server.db.engine.connect() as conn:
		count_query = sqlalchemy.select(sqlalchemy.func.count()).select_from(quotes).where(~quotes.c.deleted)
		count, = conn.execute(count_query).first()
		pages = (count - 1) // QUOTES_PER_PAGE + 1

		page = max(1, min(page, pages))

		quotes = conn.execute(sqlalchemy.select(
			quotes.c.id, quotes.c.quote, quotes.c.attrib_name, quotes.c.attrib_date, quotes.c.context,
			sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
			shows.c.name,
		).select_from(quotes
			.outerjoin(games, games.c.id == quotes.c.game_id)
			.outerjoin(shows, shows.c.id == quotes.c.show_id)
			.outerjoin(game_per_show_data, (game_per_show_data.c.game_id == quotes.c.game_id) & (game_per_show_data.c.show_id == quotes.c.show_id))
		).where(~quotes.c.deleted)
			.order_by(quotes.c.id.desc()).offset((page-1) * QUOTES_PER_PAGE)
			.limit(QUOTES_PER_PAGE)).fetchall()

	return flask.render_template('quotes.html', session=session, quotes=quotes, page=page, pages=pages)

@blueprint.route('/search')
@login.with_session
def search(session):
	query = flask.request.values["q"]
	mode = flask.request.values.get('mode', 'text')
	page = int(flask.request.values.get("page", 1))
	quotes = server.db.metadata.tables["quotes"]
	games = server.db.metadata.tables["games"]
	shows = server.db.metadata.tables["shows"]
	game_per_show_data = server.db.metadata.tables["game_per_show_data"]
	sql = sqlalchemy.select(
		quotes.c.id, quotes.c.quote, quotes.c.attrib_name, quotes.c.attrib_date, quotes.c.context,
		sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name),
		shows.c.name,
	).select_from(quotes
		.outerjoin(games, games.c.id == quotes.c.game_id)
		.outerjoin(shows, shows.c.id == quotes.c.show_id)
		.outerjoin(game_per_show_data, (game_per_show_data.c.game_id == quotes.c.game_id) & (game_per_show_data.c.show_id == quotes.c.show_id))
	).where(~quotes.c.deleted).order_by(quotes.c.id.desc())
	if mode == 'text':
		fts_column = sqlalchemy.func.to_tsvector('english', quotes.c.quote)
		sql = sql.where(fts_column.op("@@")(sqlalchemy.func.plainto_tsquery('english', query)))
	elif mode == 'name':
		sql = sql.where(quotes.c.attrib_name.ilike("%" + common.postgres.escape_like(query.lower()) + "%"))
	else:
		return www.utils.error_page("Unrecognised mode")
	with server.db.engine.connect() as conn:
		quotes = conn.execute(sql).fetchall()
	pages = (len(quotes) - 1) // QUOTES_PER_PAGE + 1
	page = max(1, min(page, pages))

	quotes = quotes[(page - 1) * QUOTES_PER_PAGE : page * QUOTES_PER_PAGE]

	return flask.render_template('quotes.html', session=session, quotes=quotes, page=page, pages=pages, args={'q': query, 'mode': mode})
