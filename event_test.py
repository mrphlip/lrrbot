import aiomas
import asyncio
import pprint
import json
import pytz
import datetime

import common.rpc
from common.config import config

async def main():
	client = common.rpc.Client(config['eventsocket'], config['event_port'])
	await client.connect()
	print(await client.event('twitch-subscriber', {
		'name': 'lrrbot',
	}, datetime.datetime.now(tz=pytz.utc)))
	await client.close()

asyncio.get_event_loop().run_until_complete(main())
