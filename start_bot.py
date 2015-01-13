#!/usr/bin/env python3

import logging
from lrrbot import bot, log, chatlog
from common.config import config

logging.basicConfig(level=config['loglevel'], format="[%(asctime)s] %(levelname)s:%(name)s:%(message)s")
if config['logfile'] is not None:
	fileHandler = logging.FileHandler(config['logfile'], 'a', 'utf-8')
	fileHandler.formatter = logging.root.handlers[0].formatter
	logging.root.addHandler(fileHandler)

import commands
bot.compile()

chatlog.createthread()

try:
	log.info("Bot startup")
	bot.start()
except (KeyboardInterrupt, SystemExit):
	pass
finally:
	log.info("Bot shutdown")
	logging.shutdown()
	chatlog.exitthread()
