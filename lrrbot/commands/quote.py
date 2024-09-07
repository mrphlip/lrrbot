# This code was originally part of Pump19 (https://github.com/TwistedPear-AT/pump19)

# Copyright (c) 2015 Twisted Pear <pear at twistedpear dot at>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
import common.postgres
import common.time
import common.utils
import lrrbot.decorators

import sqlalchemy

from lrrbot.command_parser import Blueprint

blueprint = Blueprint()

def format_quote(tag, qid, quote, name, date, context):
	quote_msg = "{tag} #{qid}: \"{quote}\"".format(tag=tag, qid=qid, quote=quote)
	if name:
		quote_msg += " —{name}".format(name=name)
	if context:
		quote_msg += ", {context}".format(context=context)
	if date:
		quote_msg += " [{date!s}]".format(date=date)
	return quote_msg

@blueprint.command(r"quote(?: (?:(game|show) (.+)|(?:(\d+)|(.+))))?")
@lrrbot.decorators.sub_only
@lrrbot.decorators.throttle(60, count=2)
def quote(bot, conn, event, respond_to, meta_param, meta_value, qid, attrib):
	"""
	Command: !quote
	Command: !quote ATTRIB
	Command: !quote game GAME
	Command: !quote show SHOW
	Section: quotes

	Post a randomly selected quotation, optionally filtered by attribution, game or show.
	--command
	Command: !quote ID
	Section: quotes

	Post the quotation with the specified ID.
	"""
	quotes = bot.metadata.tables["quotes"]
	games = bot.metadata.tables["games"]
	shows = bot.metadata.tables["shows"]
	query = sqlalchemy.select(quotes.c.id, quotes.c.quote, quotes.c.attrib_name, quotes.c.attrib_date, quotes.c.context)
	source = quotes
	if qid:
		query = query.where(quotes.c.id == int(qid))
	elif meta_param:
		if meta_param == "game":
			query = query.where(games.c.name.ilike("%" + common.postgres.escape_like(meta_value.lower()) + "%"))
			source = source.join(games, games.c.id == quotes.c.game_id)
		elif meta_param == "show":
			query = query.where(shows.c.name.ilike("%" + common.postgres.escape_like(meta_value.lower()) + "%"))
			source = source.join(shows, shows.c.id == quotes.c.show_id)
	elif attrib:
		query = query.where(quotes.c.attrib_name.ilike("%" + common.postgres.escape_like(attrib.lower()) + "%"))
	query = query.select_from(source).where(~quotes.c.deleted)
	with bot.engine.connect() as pg_conn:
		row = common.utils.pick_random_elements(pg_conn.execute(query), 1)[0]
	if row is None:
		conn.privmsg(respond_to, "Could not find any matching quotes.")
		return

	qid, quote, name, date, context = row
	conn.privmsg(respond_to, format_quote("Quote", qid, quote, name, date, context))

@blueprint.command(r"addquote(?: \((.+?)\))?(?: \[(.+?)\])? ([^\|]+?)(?: ?\| ?([^\|]*))?")
@lrrbot.decorators.mod_only
async def addquote(bot, conn, event, respond_to, name, date, quote, context):
	"""
	Command: !addquote (NAME) [DATE] QUOTE | CONTEXT
	Command: !addquote (NAME) [DATE] QUOTE
	Command: !addquote (NAME) QUOTE
	Command: !addquote [DATE] QUOTE
	Command: !addquote QUOTE
	Section: quotes

	 Add a quotation with optional attribution, date and context to the quotation database.
	"""
	if date:
		try:
			date = common.time.strtodate(date)
		except ValueError:
			return conn.privmsg(respond_to, "Could not add quote due to invalid date.")
	quotes = bot.metadata.tables["quotes"]
	game_id = await bot.get_game_id()
	show_id = bot.get_show_id()
	with bot.engine.connect() as pg_conn:
		qid, = pg_conn.execute(quotes.insert().returning(quotes.c.id), {
			"quote": quote,
			"attrib_name": name,
			"attrib_date": date,
			"context": context,
			"game_id": game_id,
			"show_id": show_id,
		}).first()
		pg_conn.commit()

	conn.privmsg(respond_to, format_quote("New quote", qid, quote, name, date, context))

@blueprint.command(r"modquote (\d+)(?: \((.+?)\))?(?: \[(.+?)\])? ([^\|]+?)(?: ?\| ?([^\|]*))?")
@lrrbot.decorators.mod_only
def modquote(bot, conn, event, respond_to, qid, name, date, quote, context):
	"""
	Command: !modquote QID (NAME) [DATE] QUOTE | CONTEXT
	Command: !modquote QID (NAME) [DATE] QUOTE
	Command: !modquote QID (NAME) QUOTE
	Command: !modquote QID [DATE] QUOTE
	Command: !modquote QID QUOTE
	Section: quotes

	Modify an existing quotation with optional attribution. All fields are updated and/or deleted in case they're omitted.
	"""
	if date:
		try:
			date = common.time.strtodate(date)
		except ValueError:
			return conn.privmsg(respond_to, "Could not modify quote due to invalid date.")

	quotes = bot.metadata.tables["quotes"]
	with bot.engine.connect() as pg_conn:
		res = pg_conn.execute(quotes.update().where((quotes.c.id == int(qid)) & (~quotes.c.deleted)), {
			"quote": quote,
			"attrib_name": name,
			"attrib_date": date,
			"context": context,
		})
		pg_conn.commit()
	if res.rowcount == 1:
		conn.privmsg(respond_to, format_quote("Modified quote", qid, quote, name, date, context))
	else:
		conn.privmsg(respond_to, "Could not modify quote.")

@blueprint.command(r"delquote (\d+)")
@lrrbot.decorators.mod_only
def delquote(bot, conn, event, respond_to, qid):
	"""
	Command: !delquote QID
	Section: quotes

	Remove the quotation with the specified ID from the quotation database.
	"""

	quotes = bot.metadata.tables["quotes"]
	with bot.engine.connect() as pg_conn:
		res = pg_conn.execute(quotes.update().where(quotes.c.id == int(qid)), {"deleted": True})
		pg_conn.commit()
	if res.rowcount == 1:
		conn.privmsg(respond_to, "Marked quote #{qid} as deleted.".format(qid=qid))
	else:
		conn.privmsg(respond_to, "Could not find quote #{qid}.".format(qid=qid))

@blueprint.command(r"findquote (.*)")
@lrrbot.decorators.sub_only
@lrrbot.decorators.throttle(60, count=2)
def findquote(bot, conn, event, respond_to, query):
	"""
	Command: !findquote QUERY
	Section: quotes

	Search for a quote in the quote database.
	"""

	quotes = bot.metadata.tables["quotes"]
	with bot.engine.connect() as pg_conn:
		fts_column = sqlalchemy.func.to_tsvector('english', quotes.c.quote)
		query = sqlalchemy.select(
			quotes.c.id, quotes.c.quote, quotes.c.attrib_name, quotes.c.attrib_date, quotes.c.context
		).where(
			(fts_column.op("@@")(sqlalchemy.func.plainto_tsquery('english', query))) & (~quotes.c.deleted)
		)
		row = common.utils.pick_random_elements(pg_conn.execute(query), 1)[0]
	if row is None:
		return conn.privmsg(respond_to, "Could not find any matching quotes.")
	qid, quote, name, date, context = row
	conn.privmsg(respond_to, format_quote("Quote", qid, quote, name, date, context))
