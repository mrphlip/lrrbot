#!/usr/bin/env python3

import asyncio
import logging
from common import utils

utils.init_logging("lrrbot")

from lrrbot import LRRBot
import lrrbot.commands

log = logging.getLogger('lrrbot')

try:
	log.info("Bot startup")
	bot = LRRBot(asyncio.new_event_loop())

	bot.commands.register_blueprint(lrrbot.commands.card.blueprint)
	bot.commands.register_blueprint(lrrbot.commands.game.blueprint)
	bot.commands.register_blueprint(lrrbot.commands.live.blueprint)
	bot.commands.register_blueprint(lrrbot.commands.lockdown.blueprint)
	bot.commands.register_blueprint(lrrbot.commands.misc.blueprint)
	bot.commands.register_blueprint(lrrbot.commands.quote.blueprint)
	bot.commands.register_blueprint(lrrbot.commands.show.blueprint)
	bot.commands.register_blueprint(lrrbot.commands.static.blueprint)

	bot.start()
except (KeyboardInterrupt, SystemExit):
	pass
finally:
	log.info("Bot shutdown")
	logging.shutdown()
