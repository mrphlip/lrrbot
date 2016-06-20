#!/usr/bin/env python3

import logging
from common.config import config

logging.basicConfig(level=config['loglevel'], format="[%(asctime)s] %(levelname)s:%(name)s:%(message)s")
if config['logfile'] is not None:
	fileHandler = logging.FileHandler(config['logfile'], 'a', 'utf-8')
	fileHandler.formatter = logging.root.handlers[0].formatter
	logging.root.addHandler(fileHandler)
logging.getLogger("requests").setLevel(logging.ERROR)

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
