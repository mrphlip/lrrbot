import asyncio
import re
import logging
from common import utils
from urllib.parse import urljoin
from lrrbot import storage
import irc.client

log = logging.getLogger('linkspam')

PARENS = ["()", "[]", "{}", "<>", '""', "''"]

class LinkSpam:
	def __init__(self, loop):
		self.loop = loop
		
		tlds = loop.run_until_complete(self.get_tlds())
		# Sort TLDs in decreasing order by length to avoid incorrect matches.
		# For example: if 'co' is before 'com', 'example.com/path' is matched as 'example.co'.
		tlds = sorted(tlds, key=lambda e: len(e), reverse=True)
		re_tld = "(?:" + "|".join(map(re.escape, tlds)) + ")"
		re_hostname = "(?:(?:(?:[\w-]+\.)+" + re_tld + "\.?)|(?:\d{,3}(?:\.\d{,3}){3})|(?:\[[0-9a-fA-F:.]+\]))"
		re_url = "((?:https?://)?" + re_hostname + "(?::\d+)?(?:/[\x5E\s\u200b]*)?)"
		re_url = re_url + "|" + "|".join(map(lambda parens: re.escape(parens[0]) + re_url + re.escape(parens[1]), PARENS))
		self._re_url = re.compile(re_url, re.IGNORECASE)
		self._spam_rules = [
			{
				"re": re.compile(rule["re"], re.IGNORECASE),
				"message": rule["message"]
			}
			for rule in storage.data.get("link_spam_rules", [])
		]

	@asyncio.coroutine
	def get_tlds(self):
		tlds = set()
		data = yield from utils.http_request_coro("https://data.iana.org/TLD/tlds-alpha-by-domain.txt")
		for line in data.splitlines():
			if not line.startswith("#"):
				line = line.strip().lower()
				tlds.add(line)
				line = line.encode("ascii").decode("idna")
				tlds.add(line)
		return tlds

	@utils.cache(60 * 60, params=[1])
	@asyncio.coroutine
	def canonical_url(self, url):
		if not url.startswith("http://") and not url.startswith("https://"):
			url = "http://" + url
		try:
			res = yield from utils.http_request_coro(url, method="HEAD", allow_redirects=False)
			if res.status in range(300, 400) and "Location" in res.headers:
				return [url] + (yield from self.canonical_url(urljoin(url, res.headers["Location"])))
		except Exception:
			log.exception("Error fetching %r:", url)
			pass
		return [url]

	@asyncio.coroutine
	def check_urls(self, conn, event, message):
		urls = []
		for match in self._re_url.finditer(message):
			for url in match.groups():
				if url is not None:
					urls.append(url)
					break
		canonical_urls = yield from asyncio.gather(*map(self.canonical_url, urls), loop=self.loop)
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
