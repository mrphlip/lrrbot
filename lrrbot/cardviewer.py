import asyncio
import pubnub
import logging
import time
import re
import urllib.parse

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
		self.last_card_id = None
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
		self.re_local = [
			re.compile("^/cards/(?P<set>[^-]+)-(?P<number>[^.]+)\.", re.I),
			re.compile("^/cards/(?P<set>.+)_(?P<number>[^.]+)\.", re.I)
		]

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

	def _extract(self, message):
		url = urllib.parse.urlparse(message)

		# Image URL from Gatherer, extract multiverse ID
		if url.netloc == "gatherer.wizards.com":
			try:
				return int(urllib.parse.parse_qs(url.query)["multiverseid"][0])
			except (ValueError, KeyError, IndexError):
				log.exception("Failed to extract multiverse ID from %r", message)
				return None
		# Card images for the pre-prerelease, extract set and collector number
		elif url.netloc == "localhost":
			for regex in self.re_local:
				match = regex.match(url.path)
				if match is not None:
					return (match.group("set"), match.group("number"))
			log.error("Failed to extract set and collector number from %r", message)
			return None
		else:
			log.error("Unrecognised card image URL: %r", message)
			return None

	@utils.swallow_errors
	def _callback(self, message, channel):
		if channel != config['cardviewerchannel']:
			return
		card_id = self._extract(message)
		if card_id is not None:
			# Pubnub is threaded, and asyncio doesn't play very nicely with threading
			# Call this to get back into the main thread
			self.loop.call_soon_threadsafe(asyncio.async, self._card(card_id))

	@utils.swallow_errors
	@asyncio.coroutine
	def _card(self, card_id):
		# Delayed import so this module can be imported before the bot object exists
		import lrrbot.commands.card

		if not self.lrrbot.cardview:
			return

		# Protect against bouncing - don't repeat the same card multiple times in
		# quick succession.
		# We should be running back in the main thread, being run by asyncio, so
		# don't need to worry about locking or suchlike here.
		if card_id == self.last_card_id and time.time() - self.last_time < REPEAT_TIMER:
			return
		self.last_card_id = card_id
		self.last_time = time.time()

		log.info("Got card from pubnub: %r" % card_id)

		yield from asyncio.sleep(ANNOUNCE_DELAY)

		lrrbot.commands.card.real_card_lookup(
			self.lrrbot,
			self.lrrbot.connection,
			None,
			"#" + config['channel'],
			card_id,
			noerror=True)

	def _error(self, message):
		log.error("Pubnub error: %s", message)

	def _connect(self, message):
		log.info("Pubnub connected: %s", message)

	def _reconnect(self, message):
		log.info("Pubnub reconnected: %s", message)

	def _disconnect(self, message):
		log.info("Pubnub disconnected: %s", message)
