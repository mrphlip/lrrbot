import aiomas
import asyncio
import logging

import common.url
import common.spam
from common import utils
from lrrbot import storage
import irc.client

log = logging.getLogger('linkspam')

class LinkSpam:
	router = aiomas.rpc.Service()

	def __init__(self, lrrbot, loop):
		self.loop = loop
		self.lrrbot = lrrbot
		self.re_url = loop.run_until_complete(common.url.url_regex())
		self.rules = [
			{
				"re": common.spam.compile_rule(rule),
				"message": rule["message"],
				"type": rule.get('type', 'spam'),
			}
			for rule in storage.data.get("link_spam_rules", [])
		]
		self.lrrbot.rpc_server.link_spam = self
		self.lrrbot.reactor.add_global_handler("pubmsg", self.check_link_spam, 21)

	@aiomas.expose
	def modify_link_spam_rules(self, data):
		storage.data['link_spam_rules'] = data
		storage.save()
		self.rules = [
			{
				"re": common.spam.compile_rule(rule),
				"message": rule['message'],
				"type": rule.get('type', 'spam'),
			}
			for rule in storage.data['link_spam_rules']
		]

	def check_link_spam(self, conn, event):
		asyncio.ensure_future(self.check_urls(conn, event, event.arguments[0])).add_done_callback(utils.check_exception)

	async def check_urls(self, conn, event, message):
		urls = []
		for match in self.re_url.finditer(message):
			for url in match.groups():
				if url is not None:
					urls.append(url)
					break
		canonical_urls = await asyncio.gather(*map(common.url.canonical_url, urls))
		for original_url, url_chain in zip(urls, canonical_urls):
			for url in url_chain:
				for rule in self.rules:
					match = rule["re"].search(url)
					if match is not None:
						source = irc.client.NickMask(event.source)
						log.info("Detected link spam from %s - %r contains the URL %r which redirects to %r which matches %r",
							source.nick, message, original_url, url, rule["re"].pattern)
						await self.lrrbot.ban(conn, event, rule["message"] % {str(i+1): v for i, v in enumerate(match.groups())}, rule['type'])
						return
