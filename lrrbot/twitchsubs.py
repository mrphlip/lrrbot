import time
import logging
import dateutil
import asyncio
import sqlalchemy
from common import utils
from common.config import config
from common import twitch

log = logging.getLogger('twitchsubs')

@asyncio.coroutine
def watch_subs(lrrbot):
	try:
		while True:
			yield from do_check(lrrbot)
			yield from asyncio.sleep(config['checksubstime'])
	except asyncio.CancelledError:
		pass

last_subs = None
@utils.swallow_errors
@asyncio.coroutine
def do_check(lrrbot):
	global last_subs

	users = lrrbot.metadata.tables["users"]
	with lrrbot.engine.begin() as conn:
		token = conn.execute(sqlalchemy.select([users.c.twitch_oauth])
			.where(users.c.name == config['channel'])).first()

	sublist = None
	if token is not None:
		sublist = yield from twitch.get_subscribers(config['channel'], token)
	if not sublist:
		log.info("Failed to get subscriber list from Twitch")
		last_subs = None
		return

	# If this is the first time we've gotten the sub list then don't notify for all of them
	# as all of them will appear "new" even if we saw them on a previous run
	# Just add them to the "seen" list
	if last_subs is not None:
		for user, logo, eventtime in sublist:
			if user.lower() not in last_subs:
				log.info("Found new subscriber via Twitch API: %s" % user)
				eventtime = dateutil.parser.parse(eventtime).timestamp()
				lrrbot.on_api_subscriber(user, logo, eventtime, config['channel'])
	else:
		log.debug("Got initial subscriber list from Twitch")

	last_subs = [i[0].lower() for i in sublist]
