#!/usr/bin/env python3

import logging, logging.config
from common.config import config

logging.config.fileConfig("logging.conf")

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
