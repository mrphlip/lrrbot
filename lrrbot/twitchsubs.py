import queue
import threading
import time
import logging
import dateutil
from common import utils
from common.config import config
from lrrbot import twitch

log = logging.getLogger('twitchsubs')

new_subs = queue.Queue()

# Twitch API subscriber polling lives in its own thread, as sometimes this API
# call hangs or locks, and we don't want to kill the bot while we wait for timeout.
def createthread():
	thread = threading.Thread(target=run_thread, name="twitchsubs")
	thread.setDaemon(True)
	thread.start()

def run_thread():
	while True:
		do_check()
		time.sleep(config['checksubstime'])

last_subs = None
@utils.swallow_errors
def do_check():
	global last_subs

	sublist = twitch.get_subscribers(config['channel'])
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
				new_subs.put((user, logo, eventtime, config['channel']))
	else:
		log.debug("Got initial subscriber list from Twitch")

	last_subs = [i[0].lower() for i in sublist]

