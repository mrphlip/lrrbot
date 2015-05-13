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

import flask

from common import utils

from www import server
from www import login

@server.app.route("/codefall/")
@login.require_login
@utils.with_postgres
def codefall(conn, cur, session):
	"""Show a list of all codefall pages and a form to add new ones."""

	# get all codes for the user from the database
	cur.execute("""
		SELECT cid, description, code, code_type, claimed
		FROM codefall
		WHERE user_name = %s
	""", (session["user"],))
	print(session["user"])
	unclaimed, claimed = list(), list()
	for cid, description, code, code_type, is_claimed in cur:
		entry = {"description": description, "code_type": code_type}

		if not is_claimed:
			# for unclaimed codes we need to generate our "random" link
			cid = utils.hmac_sign(str(cid).encode("utf-8")).decode("utf-8")
			entry["url"] = flask.url_for("codefall_show", code=cid, _external=True)
			unclaimed.append(entry)
		else:
			claimed.append(entry)

	return flask.render_template("codefall.html", session=session, unclaimed=unclaimed, claimed=claimed)

@server.app.route("/codefall/add", methods=["POST"])
@login.require_login
@utils.with_postgres
def codefall_add(conn, cur, session):
	cur.execute("""
		INSERT INTO codefall (description, code, code_type, user_name)
		VALUES (%s, %s, %s, %s)
	""", (
		flask.request.values["description"],
		flask.request.values["code"],
		flask.request.values["code_type"],
		session["user"]
	))

	return flask.redirect(flask.url_for("codefall"))

@server.app.route("/codefall/claim/<code>")
@login.require_login
@utils.with_postgres
def codefall_claim(conn, cur, session, code):
	"""Claim a codefall page."""

	# first, try to parse the secret
	cid = utils.hmac_verify(code.encode("utf-8"))
	if cid is None:
		return utils.error("Invalid codefall code")
	cid = int(cid)

	cur.execute("""
		UPDATE codefall
		SET claimed = TRUE
		WHERE cid = %s AND NOT claimed
	""", (cid, ))
	claimed = cur.rowcount == 0
	cur.execute("""
		SELECT description, code, code_type
		FROM codefall
		WHERE cid = %s
	""", (cid, ))

	for description, code, code_type in cur:
		return flask.render_template("codefall_claim.html",
			session=session,
			description=description,
			code=code,
			code_type=code_type,
			claimed=claimed
		)

@server.app.route("/codefall/<code>")
@login.require_login
@utils.with_postgres
def codefall_show(conn, cur, session, code):
	"""Show a codefall page (letting people claim it)."""
	# first, try to parse the secret
	cid = utils.hmac_verify(code.encode("utf-8"))
	if cid is None:
		return utils.error_page("Invalid codefall code")
	cid = int(cid)

	cur.execute("""
		SELECT description, code_type, claimed
		FROM codefall
		WHERE cid = %s AND NOT claimed
	""", (cid, ))

	for description, code_type, claimed in cur:
		url = flask.url_for("codefall_claim", code=code)
		return flask.render_template("codefall_show.html", session=session,
			       description=description,
			       code_type=code_type,
			       url=url,
			       claimed=claimed,
		)