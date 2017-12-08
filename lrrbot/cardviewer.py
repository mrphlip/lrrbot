import asyncio
import logging
import time
import re
import urllib.parse

from pubnub.pnconfiguration import PNConfiguration
from pubnub.pnconfiguration import PNReconnectionPolicy
from pubnub.pubnub_asyncio import PubNubAsyncio
from pubnub.pubnub_asyncio import SubscribeListener

from common import utils
from common.config import config

__all__ = ["CardViewer"]

REPEAT_TIMER = 120
ANNOUNCE_DELAY = 10

log = logging.getLogger('cardviewer')

class CardViewer:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop
		self.task = None
		self.stop_future = None
		self.re_local = [
			re.compile("^/cards/(?P<set>[^_]+)_(?P<name>[^+]+)(?:\+(?P=set)_(?P<name2>[^+]+))?\.[^.]*$", re.I),
		]
		self.re_scryfall = re.compile("^/cards/multiverse/(\d+)", re.I)

	def start(self):
		if config['cardsubkey']:
			self.stop_future = asyncio.Future()
			self.task = asyncio.ensure_future(self.message_pump())

	@utils.log_errors
	async def stop(self):
		if self.task:
			self.stop_future.set_result(None)
			await self.task

	@utils.log_errors
	async def message_pump(self):
		pnconfig = PNConfiguration()
		pnconfig.subscribe_key = config['cardsubkey']
		# Why aren't these the default settings?
		pnconfig.ssl = True
		pnconfig.reconnect_policy = PNReconnectionPolicy.EXPONENTIAL

		pubnub = PubNubAsyncio(pnconfig)

		listener = SubscribeListener()
		pubnub.add_listener(listener)

		pubnub.subscribe().channels(config['cardviewerchannel']).execute()
		await listener.wait_for_connect()
		log.info("Connected to PubNub")

		message_future = asyncio.ensure_future(listener.wait_for_message_on(config['cardviewerchannel']))

		while True:
			await asyncio.wait([self.stop_future, message_future], return_when=asyncio.FIRST_COMPLETED)
			if message_future.done():
				message = message_future.result().message
				log.info("Message from PubNub: %r", message)

				card_id = self._extract(message)
				if card_id is not None:
					await self._card(card_id)

				message_future = asyncio.ensure_future(listener.wait_for_message_on(config['cardviewerchannel']))
			if self.stop_future.done():
				break
		if not message_future.done():
			message_future.cancel()

		pubnub.unsubscribe().channels(config['cardviewerchannel']).execute()
		await listener.wait_for_disconnect()
		pubnub.stop()
		log.info("Disconnected from PubNub")

	def _extract(self, message):
		url = urllib.parse.urlparse(message)

		# Image URL from Gatherer, extract multiverse ID
		if url.netloc == "gatherer.wizards.com":
			try:
				return int(urllib.parse.parse_qs(url.query)["multiverseid"][0])
			except (ValueError, KeyError, IndexError):
				log.exception("Failed to extract multiverse ID from %r", message)
				return None
		elif url.netloc == "api.scryfall.com":
			match = self.re_scryfall.match(url.path)
			if match is not None:
				try:
					return int(match.group(1))
				except (ValueError, KeyError, IndexError):
					log.exception("Failed to extract multiverse ID from %r", message)
					return None
			else:
				log.error("Failed to extract multiverse ID from %r", message)
		# Card images for the pre-prerelease, extract set and card name
		elif url.netloc == "localhost":
			for regex in self.re_local:
				match = regex.match(url.path)
				if match is not None:
					if match.group("name2") is not None:
						return "%s_%s" % (urllib.parse.unquote(match.group("name")),
							urllib.parse.unquote(match.group("name2")))
					else:
						return urllib.parse.unquote(match.group("name"))
			log.error("Failed to extract set and card name from %r", message)
			return None
		else:
			log.error("Unrecognised card image URL: %r", message)
			return None

	@utils.swallow_errors
	async def _card(self, card_id):
		if not self.lrrbot.cardview:
			return

		await self._card_debounce(card_id)

	@utils.swallow_errors
	@utils.cache(REPEAT_TIMER, params=['card_id'])
	async def _card_debounce(self, card_id):
		# Delayed import so this module can be imported before the bot object exists
		import lrrbot.commands.card

		log.info("Got card from pubnub: %r", card_id)

		await asyncio.sleep(ANNOUNCE_DELAY)

		lrrbot.commands.card.real_card_lookup(
			self.lrrbot,
			self.lrrbot.connection,
			None,
			"#" + config['channel'],
			card_id,
			noerror=True,
			includehidden=True)
