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
import lrrbot.decorators
from common import utils
from lrrbot.main import bot
import datetime

def format_quote(tag, qid, quote, name, date):
	quote_msg = "{tag} #{qid}: \"{quote}\"".format(tag=tag, qid=qid, quote=quote)
	if name:
		quote_msg += " —{name}".format(name=name)
	if date:
		quote_msg += " [{date!s}]".format(date=date)
	return quote_msg

@bot.command("quote(?: (?:(\d+)|(.+)))?")
@lrrbot.decorators.sub_only
@lrrbot.decorators.throttle(60, count=2)
@common.postgres.with_postgres
def quote(pg_conn, cur, lrrbot, conn, event, respond_to, qid, attrib):
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
	if qid:
		where, params = """
			WHERE qid = %s AND NOT deleted
		""", (int(qid),)
	elif attrib:
		where, params = """
			WHERE LOWER(attrib_name) LIKE %s AND NOT deleted
		""", ("%" + common.postgres.escape_like(attrib.lower()) + "%",)
	else:
		where, params = """
			WHERE NOT deleted
		""", ()

	row = common.postgres.pick_random_row(cur, """
		SELECT qid, quote, attrib_name, attrib_date
		FROM quotes
		%s
	""" % where, params)
	if row is None:
		conn.privmsg(respond_to, "Could not find any matching quotes.")
		return

	qid, quote, name, date = row
	conn.privmsg(respond_to, format_quote("Quote", qid, quote, name, date))

@bot.command("addquote(?: \((.+?)\))?(?: \[(.+?)\])? (.+)")
@lrrbot.decorators.mod_only
@common.postgres.with_postgres
def addquote(pg_conn, cur, lrrbot, conn, event, respond_to, name, date, quote):
	"""
	Command: !addquote (NAME) [DATE] QUOTE
	Command: !addquote (NAME) QUOTE
	Command: !addquote [DATE] QUOTE
	Command: !addquote QUOTE
	Section: quotes

	 Add a quotation with optional attribution to the quotation database. 
	"""
	if date:
		try:
			date = common.time.strtodate(date)
		except ValueError:
			return conn.privmsg(respond_to, "Could not add quote due to invalid date.")

	cur.execute("""
		INSERT INTO quotes
		(quote, attrib_name, attrib_date) VALUES (%s, %s, %s)
		RETURNING qid
	""", (quote, name, date))
	qid, = next(cur)

	conn.privmsg(respond_to, format_quote("New quote", qid, quote, name, date))

@bot.command("modquote (\d+)(?: \((.+?)\))?(?: \[(.+?)\])? (.+)")
@lrrbot.decorators.mod_only
@common.postgres.with_postgres
def modquote(pg_conn, cur, lrrbot, conn, event, respond_to, qid, name, date, quote):
	"""
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

	cur.execute("""
		UPDATE quotes
		SET quote = %s, attrib_name = %s, attrib_date = %s
		WHERE qid = %s AND NOT deleted
	""", (quote, name, date, qid))
	if cur.rowcount == 1:
		conn.privmsg(respond_to, format_quote("Modified quote", qid, quote, name, date))
	else:
		conn.privmsg(respond_to, "Could not modify quote.")

@bot.command("delquote (\d+)")
@lrrbot.decorators.mod_only
@common.postgres.with_postgres
def delquote(pg_conn, cur, lrrbot, conn, event, respond_to, qid):
	"""
	Command: !delquote QID
	Section: quotes
	
	Remove the quotation with the specified ID from the quotation database. 
	"""
	qid = int(qid)

	cur.execute("""
		UPDATE quotes
		SET deleted = TRUE
		WHERE qid = %s
	""", (qid,))
	if cur.rowcount == 1:
		conn.privmsg(respond_to, "Marked quote #{qid} as deleted.".format(qid=qid))
	else:
		conn.privmsg(respond_to, "Could not find quote #{qid}.".format(qid=qid))

@bot.command("findquote (.*)")
@lrrbot.decorators.sub_only
@lrrbot.decorators.throttle(60, count=2)
@common.postgres.with_postgres
def findquote(pg_conn, cur, lrrbot, conn, event, respond_to, query):
	"""
	Command: !findquote QUERY
	Section: quotes
	
	Search for a quote in the quote database.
	"""

	row = common.postgres.pick_random_row(cur, """
		SELECT qid, quote, attrib_name, attrib_date
		FROM quotes
		WHERE
			TO_TSVECTOR('english', quote) @@ PLAINTO_TSQUERY('english', %s)
			AND NOT deleted
	""", (query, ))
	if row is None:
		return conn.privmsg(respond_to, "Could not find any matching quotes.")
	qid, quote, name, date = row
	conn.privmsg(respond_to, format_quote("Quote", qid, quote, name, date))
