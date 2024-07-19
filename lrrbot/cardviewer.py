import asyncio
import aiomas
import logging
import sqlalchemy

from common import utils
from common.config import config

__all__ = ["CardViewer"]

REPEAT_TIMER = 120
ANNOUNCE_DELAY = 5

log = logging.getLogger('cardviewer')

class CardViewer:
	router = aiomas.rpc.Service()

	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop

		self.lrrbot.rpc_server.cardviewer = self

	@aiomas.expose
	@utils.cache(REPEAT_TIMER, params=['card_id'])
	def announce(self, card_id):
		cards = self.lrrbot.metadata.tables['cards']
		with self.lrrbot.engine.connect() as conn:
			card = conn.execute(sqlalchemy.select(cards.c.name, cards.c.text).where(cards.c.id == card_id)).first()
			if card is not None:
				name, text = card
			else:
				return

		log.info("Got a card from the API: [%d] %s", card_id, name)

		if self.lrrbot.cardview:
			asyncio.ensure_future(self.send_message(text), loop=self.loop).add_done_callback(utils.check_exception)

	async def send_message(self, text):
		await asyncio.sleep(ANNOUNCE_DELAY)

		self.lrrbot.connection.privmsg("#" + config['channel'], text)

		if self.lrrbot.youtube_chat and self.lrrbot.cardview_yt:
			await self.lrrbot.youtube_chat.broadcast_message(text)
