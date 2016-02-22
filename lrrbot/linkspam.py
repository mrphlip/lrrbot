import asyncio
import re
import logging

import common.url
from common import utils
from lrrbot import storage
import irc.client

log = logging.getLogger('linkspam')

class LinkSpam:
	def __init__(self, loop):
		self._loop = loop
		self._re_url = loop.run_until_complete(common.url.url_regex())
		self._rules = [
			{
				"re": re.compile(rule["re"], re.IGNORECASE),
				"message": rule["message"],
			}
			for rule in storage.data.get("link_spam_rules", [])
		]
		self.add_server_event("modify_link_spam_rules", self.modify_link_spam_rules)

	def modify_link_spam_rules(self, lrrbot, user, data):
		storage.data['link_spam_rules'] = data
		storage.save()
		self._rules = [
			{
				"re": re.compile(rule['re'], re.IGNORECASE),
				"message": rule['message'],
			}
			for rule in storage.data['link_spam_rules']
		]

	@asyncio.coroutine
	def check_urls(self, conn, event, message):
		urls = []
		for match in self._re_url.finditer(message):
			for url in match.groups():
				if url is not None:
					urls.append(url)
					break
		canonical_urls = yield from asyncio.gather(*map(common.url.canonical_url, urls), loop=self._loop)
		for original_url, url_chain in zip(urls, canonical_urls):
			for url in url_chain:
				for rule in self._rules:
					match = rule["re"].search(url)
					if match is not None:
						source = irc.client.NickMask(event.source)
						log.info("Detected link spam from %s - %r contains the URL %r which redirects to %r which matches %r",
							source.nick, message, original_url, url, rule["re"].pattern)
						self.ban(conn, event, rule["message"] % {str(i+1): v for i, v in enumerate(match.groups())})
						return
