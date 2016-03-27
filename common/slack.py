import asyncio
import json

from common.config import config
from common import http

@asyncio.coroutine
def send_message(text, **keys):
	keys['text'] = text
	keys.setdefault('username', config['slack_username'])
	keys.setdefault('icon_url', config['slack_icon_url'])

	headers = {
		"Content-Type": "application/json",
	}

	if config['slack_webhook_url'] is not None:
		yield from http.request_coro(config['slack_webhook_url'], method="POST", data=json.dumps(keys), headers=headers)
