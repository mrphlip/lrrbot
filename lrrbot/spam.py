import asyncio
import re
import logging

import common.url
from common import utils
from lrrbot import storage
import irc.client

log = logging.getLogger('spam')

class Spam:
	def __init__(self, lrrbot, loop):
		self.loop = loop
		self.lrrbot = lrrbot
		self.rules = [
			(re.compile(rule["re"]), rule["message"], rule.get('type', 'spam'))
			for rule in storage.data.get("spam_rules", [])
		]
		self.lrrbot.rpc_server.add("modify_spam_rules", self.modify_spam_rules)
		self.lrrbot.reactor.add_global_handler("pubmsg", self.check_spam, 20)

	def modify_spam_rules(self, lrrbot, user, data):
		log.info("Setting spam rules (%s) to %r" % (user, data))
		storage.data['spam_rules'] = data
		storage.save()
		self.rules = [
			(re.compile(rule['re']), rule['message'], rule.get('type', 'spam'))
			for rule in storage.data['spam_rules']
		]

	def check_spam(self, conn, event):
		"""Check the message against spam detection rules"""
		message = event.arguments[0]
		source = irc.client.NickMask(event.source)

		for re, desc, type in self.rules:
			matches = re.search(message)
			if matches:
				log.info("Detected spam from %s - %r matches %s" % (source.nick, message, re.pattern))
				groups = {str(i+1):v for i,v in enumerate(matches.groups())}
				desc = desc % groups
				asyncio.async(self.lrrbot.ban(conn, event, desc, type), loop=self.loop).add_done_callback(utils.check_exception)
				# Halt message handling
				return "NO MORE"
