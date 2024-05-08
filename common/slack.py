import json
import logging

from common.config import config
from common import http

log = logging.getLogger(__name__)

async def send_message(text, **keys):
	keys['text'] = text

	headers = {
		"Content-Type": "application/json",
	}

	if config['slack_webhook_url'] is not None:
		await http.request(config['slack_webhook_url'], method="POST", data=json.dumps(keys), headers=headers)
	else:
		log.info("Not sending a message to Slack: %r", keys)

def escape(text):
	return text \
		.replace("&", "&amp;") \
		.replace("<", "&lt;") \
		.replace(">", "&gt;")
