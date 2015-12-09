import time

from common import utils

import asyncio

from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5
from Crypto.Hash import SHA256

import json
import base64
import xml.dom
import xml.dom.minidom


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

	ret = json.loads((yield from utils.http_request("https://accounts.google.com/o/oauth2/token", data, "POST")))
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

@asyncio.coroutine
def add_rows_to_spreadsheet(spreadsheet, rows):
	token = yield from get_oauth_token(["https://spreadsheets.google.com/feeds"])
	headers = {"Authorization": "%(token_type)s %(access_token)s" % token}
	url = "https://spreadsheets.google.com/feeds/worksheets/%s/private/full" % spreadsheet
	tree = xml.dom.minidom.parseString((yield from utils.http_request(url, headers=headers)))
	worksheet = next(iter(tree.getElementsByTagName("entry")))
	list_feed = find_schema(worksheet, "http://schemas.google.com/spreadsheets/2006#listfeed")
	if list_feed is None:
		raise Exception("List feed missing.")
	list_feed = xml.dom.minidom.parseString((yield from utils.http_request(list_feed, headers=headers)))
	post_url = find_schema(list_feed, "http://schemas.google.com/g/2005#post")
	if post_url is None:
		raise Exception("POST URL missing.")

	for row in rows:
		doc = xml.dom.minidom.getDOMImplementation().createDocument(None, "entry", None)
		root = doc.documentElement
		root.setAttribute("xmlns", "http://www.w3.org/2005/Atom")
		root.setAttribute("xmlns:gsx", "http://schemas.google.com/spreadsheets/2006/extended")
		for column, value in row:
			root.appendChild(new_field(doc, column, value))

		headers["Content-Type"] = "application/atom+xml"
		yield from utils.http_request(post_url, headers=headers, data=doc.toxml(), method="POST")
