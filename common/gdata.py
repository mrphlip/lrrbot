import time

import common.http
from urllib.parse import quote, urlencode

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.backends import openssl
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.hashes import SHA256

import json
import base64

def base64_encode(data):
	return base64.urlsafe_b64encode(data).strip(b"=")

async def get_oauth_token(scopes):
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

	key = load_pem_private_key(keys["private_key"].encode("utf-8"), None, openssl.backend)
	signature = key.sign(data, PKCS1v15(), SHA256())

	jwt = (data + b'.' + base64_encode(signature)).decode("utf-8")

	data = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt}

	ret = json.loads((await common.http.request("https://oauth2.googleapis.com/token", data, "POST")))
	if "error" in ret:
		raise Exception(ret["error"])
	return ret

async def add_rows_to_spreadsheet(spreadsheet, rows, sheetindex=0):
	token = await get_oauth_token(["https://spreadsheets.google.com/feeds"])
	headers = {"Authorization": "%(token_type)s %(access_token)s" % token}

	url = "https://sheets.googleapis.com/v4/spreadsheets/%s?includeGridData=false" % quote(spreadsheet)
	sheetdata = json.loads((await common.http.request(url, headers=headers)))
	# weird it uses title, not sheetId, but /shrug
	sheet = sheetdata['sheets'][sheetindex]['properties']['title']

	post_url = "https://sheets.googleapis.com/v4/spreadsheets/%s/values/%s:append?%s" % (
		quote(spreadsheet), quote(sheet), urlencode({
			'valueInputOption': 'USER_ENTERED',
			'insertDataOption': 'INSERT_ROWS',
			'includeValuesInResponse': 'false',
		})
	)
	data = {"values": rows}
	await common.http.request(post_url, headers=headers, data=data, method="POST", asjson=True)
