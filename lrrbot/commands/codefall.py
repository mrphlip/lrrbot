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

from lrrbot import bot
from common import utils
from common.config import config
import random
import irc.client
import urllib.parse

@bot.command("codefall")
@utils.throttle()
@utils.with_postgres
def codefall(pg_conn, cur, lrrbot, conn, event, respond_to):
	"""
	Command: !codefall
	
	Post one of your unclaimed codefall entries. 
	"""
	source = irc.client.NickMask(event.source)
	nick = source.nick.lower()

	cur.execute("""
		SELECT cid, description, code_type
		FROM codefall
		WHERE user_name = %s AND NOT claimed
	""", (nick,))

	try:
		cid, description, code_type = random.choice(list(cur))
		cid = utils.hmac_sign(str(cid).encode("utf-8")).decode("utf-8")

		url = urllib.parse.urljoin(config["siteurl"], "codefall/"+cid)

		conn.privmsg(respond_to, "Codefall: {desc} ({ctype}) {url}".format(
			desc=description,
			ctype=code_type,
			url=url
		))
	except IndexError:
		conn.privmsg(respond_to, "Could not find any unclaimed codes.")
