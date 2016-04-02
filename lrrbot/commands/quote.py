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
from lrrbot.main import bot
from lrrbot.commands.game import game_name
from lrrbot.commands.show import show_name

import sqlalchemy

def format_quote(tag, qid, quote, name, date, context):
	quote_msg = "{tag} #{qid}: \"{quote}\"".format(tag=tag, qid=qid, quote=quote)
	if name:
		quote_msg += " —{name}".format(name=name)
	if context:
		quote_msg += ", {context}".format(context=context)
	if date:
		quote_msg += " [{date!s}]".format(date=date)
	return quote_msg

@bot.command("quote(?: (?:(\d+)|(.+)))?")
@lrrbot.decorators.sub_only
@lrrbot.decorators.throttle(60, count=2)
def quote(lrrbot, conn, event, respond_to, qid, attrib):
	"""
	Command: !quote
	Command: !quote ATTRIB
	Section: quotes

	Post a randomly selected quotation, optionally filtered by attribution.
	--command
	Command: !quote ID
	Section: quotes

	Post the quotation with the specified ID.
	"""
	quotes = lrrbot.metadata.tables["quotes"]
	query = sqlalchemy.select([quotes.c.id, quotes.c.quote, quotes.c.attrib_name, quotes.c.attrib_date, quotes.c.context])
	if qid:
		query = query.where(quotes.c.id == int(qid))
	elif attrib:
		query = query.where(quotes.c.attrib_name.ilike("%" + common.postgres.escape_like(attrib.lower()) + "%"))
	query = query.where(~quotes.c.deleted)
	with lrrbot.engine.begin() as pg_conn:
		row = common.utils.pick_random_elements(pg_conn.execute(query), 1)[0]
	if row is None:
		conn.privmsg(respond_to, "Could not find any matching quotes.")
		return

	qid, quote, name, date, context = row
	conn.privmsg(respond_to, format_quote("Quote", qid, quote, name, date, context))

@bot.command("addquote(?: \((.+?)\))?(?: \[(.+?)\])? ([^\|]+?)(?: ?\| ?([^\|]*))?")
@lrrbot.decorators.mod_only
def addquote(lrrbot, conn, event, respond_to, name, date, quote, context):
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
	quotes = lrrbot.metadata.tables["quotes"]
	game = game_name(lrrbot.get_current_game()) if lrrbot.get_current_game() else None;
	show = show_name(lrrbot.show_override) if lrrbot.show_override else show_name(lrrbot.show) if lrrbot.show else None
	with lrrbot.engine.begin() as pg_conn:
		qid, = pg_conn.execute(quotes.insert().returning(quotes.c.id), quote=quote, attrib_name=name, attrib_date=date, context=context, game=game, show=show).first()

	conn.privmsg(respond_to, format_quote("New quote", qid, quote, name, date, context))

@bot.command("modquote (\d+)(?: \((.+?)\))?(?: \[(.+?)\])? ([^\|]+?)(?: ?\| ?([^\|]*))?")
@lrrbot.decorators.mod_only
def modquote(lrrbot, conn, event, respond_to, qid, name, date, quote, context):
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

	quotes = lrrbot.metadata.tables["quotes"]
	with lrrbot.engine.begin() as pg_conn:
		res = pg_conn.execute(quotes.update().where((quotes.c.id == int(qid)) & (~quotes.c.deleted)),
			quote=quote, attrib_name=name, attrib_date=date, context=context)
	if res.rowcount == 1:
		conn.privmsg(respond_to, format_quote("Modified quote", qid, quote, name, date, context))
	else:
		conn.privmsg(respond_to, "Could not modify quote.")

@bot.command("delquote (\d+)")
@lrrbot.decorators.mod_only
def delquote(lrrbot, conn, event, respond_to, qid):
	"""
	Command: !delquote QID
	Section: quotes

	Remove the quotation with the specified ID from the quotation database.
	"""

	quotes = lrrbot.metadata.tables["quotes"]
	with lrrbot.engine.begin() as pg_conn:
		res = pg_conn.execute(quotes.update().where(quotes.c.id == int(qid)), deleted=True)
	if res.rowcount == 1:
		conn.privmsg(respond_to, "Marked quote #{qid} as deleted.".format(qid=qid))
	else:
		conn.privmsg(respond_to, "Could not find quote #{qid}.".format(qid=qid))

@bot.command("findquote (.*)")
@lrrbot.decorators.sub_only
@lrrbot.decorators.throttle(60, count=2)
def findquote(lrrbot, conn, event, respond_to, query):
	"""
	Command: !findquote QUERY
	Section: quotes

	Search for a quote in the quote database.
	""" 

	quotes = lrrbot.metadata.tables["quotes"]
	with lrrbot.engine.begin() as pg_conn:
		fts_column = sqlalchemy.func.to_tsvector('english', quotes.c.quote)
		query = sqlalchemy.select([
			quotes.c.id, quotes.c.quote, quotes.c.attrib_name, quotes.c.attrib_date, quotes.c.context
		]).where(
			(fts_column.op("@@")(sqlalchemy.func.plainto_tsquery('english', query))) & (~quotes.c.deleted)
		)
		row = common.utils.pick_random_elements(pg_conn.execute(query), 1)[0]
	if row is None:
		return conn.privmsg(respond_to, "Could not find any matching quotes.")
	qid, quote, name, date, context = row
	conn.privmsg(respond_to, format_quote("Quote", qid, quote, name, date, context))
