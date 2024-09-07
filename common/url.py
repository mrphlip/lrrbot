import logging
import re

from common.http import request
from common import utils

log = logging.getLogger("common.url")

@utils.cache(60 * 60, params=[0])
async def canonical_url(url, depth=10):
	urls = []
	while depth > 0:
		if not url.startswith("http://") and not url.startswith("https://"):
			url = "http://" + url
		urls.append(url)
		try:
			res = await request(url, method="HEAD", allow_redirects=False)
			if res.status in range(300, 400) and "Location" in res.headers:
				url = res.headers["Location"]
				depth -= 1
			else:
				break
		except utils.PASSTHROUGH_EXCEPTIONS:
			raise
		except Exception:
			log.error("Error fetching %r", url)
			break
	return urls

@utils.cache(24 * 60 * 60)
async def get_tlds():
	tlds = set()
	data = await request("https://data.iana.org/TLD/tlds-alpha-by-domain.txt")
	for line in data.splitlines():
		if not line.startswith("#"):
			line = line.strip().lower()
			tlds.add(line)
			line = line.encode("ascii").decode("idna")
			tlds.add(line)
	return tlds

@utils.cache(24 * 60 * 60)
async def url_regex():
	parens = ["()", "[]", "{}", "<>", '""', "''"]

	# Sort TLDs in decreasing order by length to avoid incorrect matches.
	# For example: if 'co' is before 'com', 'example.com/path' is matched as 'example.co'.
	tlds = sorted((await get_tlds()), key=lambda e: len(e), reverse=True)
	re_tld = "(?:" + "|".join(map(re.escape, tlds)) + ")"
	re_hostname = r"(?:(?:(?:[\w-]+\.)+%s\.?)|(?:\d{,3}(?:\.\d{,3}){3})|(?:\[[0-9a-fA-F:.]+\]))" % re_tld
	re_url = r"((?:https?://)?%s(?::\d+)?(?:/[\x5E\s\u200b]*)?)" % re_hostname
	re_url = re_url + "|" + "|".join(map(lambda parens: re.escape(parens[0]) + re_url + re.escape(parens[1]), parens))
	return re.compile(re_url, re.IGNORECASE)

RE_PROTO = re.compile("^https?://")
def https(uri):
	return RE_PROTO.sub("https://", uri)
