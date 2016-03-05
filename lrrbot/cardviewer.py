import asyncio
import pubnub
import logging
import time

from common import utils
from common.config import config


__all__ = ["CardViewer"]

REPEAT_TIMER = 60
ANNOUNCE_DELAY = 15

log = logging.getLogger('cardviewer')

class CardViewer:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop
		self.last_multiverseid = None
		self.last_time = 0
		if config['cardsubkey']:
			self.pubnub = pubnub.Pubnub(
				subscribe_key=config['cardsubkey'],
				publish_key='',
				ssl_on=True,  # For some reason not the defualt??? Also, the docs say this is "sslOn" but they lie.
				daemon=True,  # Automatically close the pubnub threads when the bot exists - undocumented, but necessary.
			)
		else:
			self.pubnub = None

	def start(self):
		if self.pubnub:
			self.pubnub.subscribe(
				channels=config['cardviewerchannel'],
				callback=self._callback,
				error=self._error,
				connect=self._connect,
				reconnect=self._reconnect,
				disconnect=self._disconnect,
			)

	def stop(self):
		if self.pubnub:
			self.pubnub.unsubscribe(channel=config['cardviewerchannel'])

	@utils.swallow_errors
	def _callback(self, message, channel):
		if channel != config['cardviewerchannel']:
			return
		match = config['cardviewerregex'].search(message)
		if match:
			multiverseid = int(match.group(1))
			# Pubnub is threaded, and asyncio doesn't play very nicely with threading
			# Call this to get back into the main thread
			self.loop.call_soon_threadsafe(asyncio.async, self._card(multiverseid))

	@utils.swallow_errors
	@asyncio.coroutine
	def _card(self, multiverseid):
		# Delayed import so this module can be imported before the bot object exists
		import lrrbot.commands.card

		if not self.lrrbot.cardview:
			return

		# Protect against bouncing - don't repeat the same card multiple times in
		# quick succession.
		# We should be running back in the main thread, being run by asyncio, so
		# don't need to worry about locking or suchlike here.
		if multiverseid == self.last_multiverseid and time.time() - self.last_time < REPEAT_TIMER:
			return
		self.last_multiverseid = multiverseid
		self.last_time = time.time()

		log.info("Got card from pubnub: %d" % multiverseid)

		yield from asyncio.sleep(ANNOUNCE_DELAY)

		lrrbot.commands.card.real_card_lookup(
			self.lrrbot,
			self.lrrbot.connection,
			None,
			"#" + config['channel'],
			multiverseid,
			noerror=True)

	def _error(self, message):
		log.error("Pubnub error: %s", message)

	def _connect(self, message):
		log.info("Pubnub connected: %s", message)

	def _reconnect(self, message):
		log.info("Pubnub reconnected: %s", message)

	def _disconnect(self, message):
		log.info("Pubnub disconnected: %s", message)
