#!/usr/bin/env python3

import logging
from common import utils

utils.init_logging("lrrbot")

from lrrbot.main import bot, log
import lrrbot.commands

try:
	log.info("Bot startup")
	bot.start()
except (KeyboardInterrupt, SystemExit):
	pass
finally:
	log.info("Bot shutdown")
	logging.shutdown()
