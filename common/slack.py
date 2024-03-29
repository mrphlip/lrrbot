import json

from common.config import config
from common import http

async def send_message(text, **keys):
	keys['text'] = text

	headers = {
		"Content-Type": "application/json",
	}

	if config['slack_webhook_url'] is not None:
		await http.request(config['slack_webhook_url'], method="POST", data=json.dumps(keys), headers=headers)

def escape(text):
	return text \
		.replace("&", "&amp;") \
		.replace("<", "&lt;") \
		.replace(">", "&gt;")
