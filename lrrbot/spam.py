import aiomas
import asyncio
import logging

import common.spam
from common import utils
from lrrbot import storage
import irc.client

log = logging.getLogger('spam')

class Spam:
	router = aiomas.rpc.Service()

	def __init__(self, lrrbot, loop):
		self.loop = loop
		self.lrrbot = lrrbot
		self.rules = [
			(common.spam.compile_rule(rule), rule["message"], rule.get('type', 'spam'))
			for rule in storage.data.get("spam_rules", [])
		]
		self.lrrbot.rpc_server.spam = self
		self.lrrbot.reactor.add_global_handler("pubmsg", self.check_spam, 20)

	@aiomas.expose
	def modify_spam_rules(self, data):
		log.info("Setting spam rules to %r" % (data,))
		storage.data['spam_rules'] = data
		storage.save()
		self.rules = [
			(common.spam.compile_rule(rule), rule['message'], rule.get('type', 'spam'))
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
				asyncio.ensure_future(self.lrrbot.ban(conn, event, desc, type), loop=self.loop).add_done_callback(utils.check_exception)
				# Halt message handling
				return "NO MORE"
