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

from common import utils
from lrrbot import bot
import random
import datetime

@utils.throttle()
@bot.command("quote(?: (?:(\d+)|(.+)))?")
@utils.with_postgres
def quote(pg_conn, cur, lrrbot, conn, event, respond_to, qid, attrib):
	"""
	Handle !quote [id] command.
	Post either the specified or a random quote.
	"""
	if qid:
		qid = int(qid)

		(qid, quote, name, date) = yield from dbutils.get_quote(qid=qid, attrib=attrib)

	if not qid:
		no_quote_msg = "Could not find any matching quotes."
		yield from self.client.privmsg(target, no_quote_msg)
		return

	quote_msg = "Quote #{qid}: \"{quote}\"".format(qid=qid, quote=quote)
	if name:
		quote_msg += " —{name}".format(name=name)
	if date:
		quote_msg += " [{date!s}]".format(date=date)

	yield from self.client.privmsg(target, quote_msg)

def handle_command_addquote(self, target, nick, *, quote=None, attrib_name=None, attrib_date=None):
	"""
	Handle !addquote (<attrib_name>) [<attrib_date>] <quote> command.
	Add the provided quote to the database.
	Only moderators may add new quotes.
	"""
	if not quote:
		return

        if attrib_date:
		try:
			parsed = datetime.datetime.strptime(attrib_date, "%Y-%m-%d")
			attrib_date = parsed.date()
		except ValueError:
			self.logger.error("Got invalid date string {date}.", date=attrib_date)
		no_quote_msg = "Could not add quote due to invalid date."
		yield from self.client.privmsg(target, no_quote_msg)
		return

        if not (self.override == nick or (yield from twitch.is_moderator("loadingreadyrun", nick))):
		return

	(qid, quote, name, date) = yield from dbutils.add_quote(quote, attrib_name=attrib_name, attrib_date=attrib_date)

	quote_msg = "New quote #{qid}: \"{quote}\"".format(qid=qid, quote=quote)
	if name:
		quote_msg += " —{name}".format(name=name)
	if date:
		quote_msg += " [{date!s}]".format(date=date)

	yield from self.client.privmsg(target, quote_msg)

def handle_command_modquote(self, target, nick, *, qid=None, quote=None, attrib_name=None, attrib_date=None):
	"""
	Handle !modquote <qid> (<attrib_name>) [<attrib_date>] <quote> command.
	Update the provided quote in the database.
	Only moderators may modify quotes.
	"""
	if not qid or not quote:
		return
	qid = int(qid)

	if attrib_date:
		try:
			parsed = datetime.datetime.strptime(attrib_date, "%Y-%m-%d")
			attrib_date = parsed.date()
		except ValueError:
			self.logger.error("Got invalid date string {date}.", date=attrib_date)
		no_quote_msg = "Could not modify quote due to invalid date."
		yield from self.client.privmsg(target, no_quote_msg)
		return

	if not (self.override == nick or (yield from twitch.is_moderator("loadingreadyrun", nick))):
		return

	(qid, quote, name, date) = yield from dbutils.mod_quote(qid, quote, attrib_name=attrib_name, attrib_date=attrib_date)

	if not qid:
		no_quote_msg = "Could not modify quote."
		yield from self.client.privmsg(target, no_quote_msg)
		return

	quote_msg = "Modified quote #{qid}: \"{quote}\"".format(qid=qid, quote=quote)
	if name:
		quote_msg += " —{name}".format(name=name)
	if date:
		quote_msg += " [{date!s}]".format(date=date)

	yield from self.client.privmsg(target, quote_msg)

def handle_command_delquote(self, target, nick, *, qid=None):
	"""
	Handle !delquote <qid> command.
	Delete the provided quote ID from the database.
	Only moderators may delete quotes.
	"""
	if not qid:
		return
	qid = int(qid)

	if not (self.override == nick or (yield from twitch.is_moderator("loadingreadyrun", nick))):
		return

	success = yield from dbutils.del_quote(qid)
	if success:
		quote_msg = "Marked quote #{qid} as deleted.".format(qid=qid)
	else:
		quote_msg = "Could not find quote #{qid}.".format(qid=qid)

	yield from self.client.privmsg(target, quote_msg)

def handle_command_goodquote(self, target, nick, *, qid=None):
	"""
	Handle !goodquote <qid> command.
	Rate the provided quote ID from the database.
	"""
	if not qid:
		return
	qid = int(qid)

	yield from dbutils.rate_quote(qid, nick, True)

def handle_command_badquote(self, target, nick, *, qid=None):
	"""
	Handle !badquote <qid> command.
	Rate the provided quote ID from the database.
	"""
	if not qid:
		return
	qid = int(qid)

	yield from dbutils.rate_quote(qid, nick, False)