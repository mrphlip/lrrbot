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
	session = request.environ.get("beaker.session")
	user_name = session.get("user_name")

	# we can't retrieve keys without user name
	if not user_name:
		return template("codefall", session=session, subtitle="Codefall")

	# get all codes for the user from the database
	codes_qry = """SELECT cid, description, code, code_type, claimed
			FROM codefall
			WHERE user_name = :user_name"""
	codes = db.execute(codes_qry, {"user_name": user_name})

	unclaimed, claimed = list(), list()
	for code in codes:
		entry = {"description": code.description, "code_type": code.code_type}

		if not code.claimed:
			# for unclaimed codes we need to generate our "random" link
			secret = int_to_codefall_key(code.cid)
			secret_url = CODEFALL_SHOW_URL.format(secret=secret)
			entry["secret_url"] = secret_url
			unclaimed.append(entry)
		else:
			claimed.append(entry)

	return template("codefall", session=session, subtitle="Codefall", unclaimed=unclaimed, claimed=claimed)


def handle_codefall_add(db):
	"""Add a new codefall page."""
	session = request.environ.get("beaker.session")
	# we require users to be logged in when adding new codes
	if not session.get("logged_in", False):
		redirect("/codefall")

	# get all mandatory items
	user_name = session.get("user_name")
	description = request.forms.getunicode("description")
	code = request.forms.getunicode("code")
	code_type = request.forms.getunicode("code_type")
	if not all((user_name, description, code, code_type)):
		redirect("/codefall")

	new_code_qry = """
		INSERT INTO codefall (description, code, code_type, user_name)
                      VALUES (:description,:code, :code_type, :user_name)"""
	try:
		db.execute(new_code_qry,
			{"description": description,
			"code": code,
			"code_type": code_type,
			"user_name": user_name})
	except IntegrityError:
		redirect("/codefall")

	# everything seems fine, store the data now
	db.commit()

	# now redirect back to codefall page
	redirect("/codefall")

def handle_codefall_claim(secret, db):
	"""Claim a codefall page."""
	session = request.environ.get("beaker.session")

	# first, try to parse the secret
	try:
		cid = codefall_key_to_int(secret)
	except:
		return template("codefall_claim", session=session, subtitle="Codefall")

	claim_code_qry = """
		UPDATE codefall
		SET claimed = True
		WHERE cid = :cid AND claimed = False
		RETURNING description, code, code_type
	"""

	code = db.execute(claim_code_qry, {"cid": cid})
	db.commit()
	code = code.first()
	if not code:
		return template("codefall_claim", session=session, subtitle="Codefall")

	entry = {"description": code.description, "code": code.code, "code_type": code.code_type}

	return template("codefall_claim", session=session, subtitle="Codefall", entry=entry)

def handle_codefall_show(secret, db):
	"""Show a codefall page (letting people claim it)."""
	session = request.environ.get("beaker.session")

	# first, try to parse the secret
	try:
		cid = codefall_key_to_int(secret)
	except:
		return template("codefall_show", session=session, subtitle="Codefall")

	show_code_qry = """
		SELECT description, code_type
		FROM codefall
		WHERE cid = :cid AND claimed = False
	"""

	code = db.execute(show_code_qry, {"cid": cid})
	code = code.first()
	if not code:
		return template("codefall_show", session=session, subtitle="Codefall")

	claim_url = CODEFALL_CLAIM_URL.format(secret=secret)

	entry = {"description": code.description, "claim_url": claim_url, "code_type": code.code_type}

	return template("codefall_show", session=session, subtitle="Codefall", entry=entry)