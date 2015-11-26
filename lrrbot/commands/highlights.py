import time

import irc.client

from common import utils
from lrrbot import storage, twitch
from lrrbot.main import bot
import asyncio

from common.config import config
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5
from Crypto.Hash import SHA256
import json
import base64
import xml.dom
import xml.dom.minidom
import dateutil.parser
import logging
import datetime

SPREADSHEET = "1yrf6d7dPyTiWksFkhISqEc-JR71dxZMkUoYrX4BR40Y"

def base64_encode(data):
	return base64.urlsafe_b64encode(data).strip(b"=")

@asyncio.coroutine
def get_oauth_token(scopes):
	with open("keys.json") as f:
		keys = json.load(f)
	t = int(time.time())

	header = json.dumps({"alg":"RS256", "typ":"JWT"}).encode("utf-8")
	claim = json.dumps({
		"iss": keys["client_email"],
		"scope": " ".join(scopes),
		"aud": "https://accounts.google.com/o/oauth2/token",
		"iat": t,
		"exp": t+60*60,
	}).encode("utf-8")

	data = base64_encode(header) + b'.' + base64_encode(claim)

	key = RSA.importKey(keys["private_key"])
	h = SHA256.new(data)
	signer = PKCS1_v1_5.new(key)
	signature = signer.sign(h)

	jwt = (data + b'.' + base64_encode(signature)).decode("utf-8")

	data = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt}

	ret = json.loads((yield from utils.http_request_coro("https://accounts.google.com/o/oauth2/token", data, "POST")))
	if "error" in ret:
		raise Exception(ret["error"])
	return ret

def find_schema(root, schema):
	for link in root.getElementsByTagName("link"):
		if link.attributes["rel"].value == schema:
			return link.attributes["href"].value

def new_field(doc, name, value):
	name = "gsx:"+"".join(filter(str.isalnum, name)).lower()
	node = doc.createElement(name)
	node.appendChild(doc.createTextNode(value))
	return node

@bot.command("highlight (.*?)")
@utils.public_only
@utils.sub_only
@utils.throttle(60, notify=utils.Visibility.PUBLIC, modoverride=False, allowprivate=False)
@asyncio.coroutine
def highlight(lrrbot, conn, event, respond_to, description):
	"""
	Command: !highlight DESCRIPTION
	Section: misc

	For use when something particularly awesome happens onstream, adds an entry on the Highlight Reel spreadsheet: https://docs.google.com/spreadsheets/d/1yrf6d7dPyTiWksFkhISqEc-JR71dxZMkUoYrX4BR40Y
	"""

	stream_info = twitch.get_info()
	if not stream_info["live"]:
		conn.privmsg(respond_to, "Not currently streaming.")
		return
	now = datetime.datetime.now(datetime.timezone.utc)

	token = yield from get_oauth_token(["https://spreadsheets.google.com/feeds"])
	headers = {"Authorization": "%(token_type)s %(access_token)s" % token}
	url = "https://spreadsheets.google.com/feeds/worksheets/%s/private/full" % SPREADSHEET
	tree = xml.dom.minidom.parseString((yield from utils.http_request_coro(url, headers=headers)))
	worksheet = next(iter(tree.getElementsByTagName("entry")))
	list_feed = find_schema(worksheet, "http://schemas.google.com/spreadsheets/2006#listfeed")
	if list_feed is None:
		log.error("List feed missing.")
		conn.privmsg(respond_to, "Error adding highlight.")
		return
	list_feed = xml.dom.minidom.parseString((yield from utils.http_request_coro(list_feed, headers=headers)))
	post_url = find_schema(list_feed, "http://schemas.google.com/g/2005#post")
	if post_url is None:
		log.error("POST URL missing.")
		conn.privmsg(respond_to, "Error adding highlight.")
		return

	for video in (yield from twitch.get_videos(broadcasts=True)):
		if video["status"] == "recording":
			break
		uptime = now - dateutil.parser.parse(video["recorded_at"])
	else:
		log.error("Stream live but not being recorded.")
		conn.privmsg(respond_to, "Error adding highlight.")
		return

	doc = xml.dom.minidom.getDOMImplementation().createDocument(None, "entry", None)
	root = doc.documentElement
	root.setAttribute("xmlns", "http://www.w3.org/2005/Atom")
	root.setAttribute("xmlns:gsx", "http://schemas.google.com/spreadsheets/2006/extended")

	root.appendChild(new_field(doc, "SHOW", stream_info["status"]))
	root.appendChild(new_field(doc, "QUOTE or MOMENT", description))
	root.appendChild(new_field(doc, "YOUTUBE VIDEO LINK", video["url"]))
	root.appendChild(new_field(doc, "ROUGH TIME THEREIN", "before " + utils.nice_duration(uptime, 0)))
	root.appendChild(new_field(doc, "NOTES", "From chat user '%s'." % irc.client.NickMask(event.source).nick))

	headers["Content-Type"] = "application/atom+xml"
	yield from utils.http_request_coro(post_url, headers=headers, data=doc.toxml(), method="POST")
	conn.privmsg(respond_to, "Highlight added.")
