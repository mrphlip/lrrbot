import asyncio
import atexit
import json
import logging
import urllib.parse
import urllib.request

import aiohttp
import async_timeout

from common import config
from common import utils

log = logging.getLogger("common.http")

class Request(urllib.request.Request):
	"""Override the get_method method of Request, adding the "method" field that doesn't exist until Python 3.3"""
	def __init__(self, *args, method=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.method = method
	def get_method(self):
		if self.method is not None:
			return self.method
		else:
			return super().get_method()

def request(url, data=None, method='GET', maxtries=3, headers={}, timeout=5, **kwargs):
	"""Download a webpage, with retries on failure."""
	# Let's be nice.
	headers["User-Agent"] = "LRRbot/2.0 (https://lrrbot.mrphlip.com/)"
	if data:
		if isinstance(data, dict):
			data = urllib.parse.urlencode(data)
		if method == 'GET':
			url = '%s?%s' % (url, data)
			req = Request(url=url, method='GET', headers=headers, **kwargs)
		elif method == 'POST':
			req = Request(url=url, data=data.encode("utf-8"), method='POST', headers=headers, **kwargs)
		elif method == 'PUT':
			req = Request(url=url, data=data.encode("utf-8"), method='PUT', headers=headers, **kwargs)
	else:
		req = Request(url=url, method='GET', headers=headers, **kwargs)

	firstex = None
	while True:
		try:
			return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
		except utils.PASSTHROUGH_EXCEPTIONS:
			raise
		except Exception as e:
			maxtries -= 1
			if firstex is None:
				firstex = e
			if maxtries > 0:
				log.info("Downloading %s failed: %s: %s, retrying...", url, e.__class__.__name__, e)
			else:
				break
	raise firstex

# Limit the number of parallel HTTP connections to a server.
http_request_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=6))
atexit.register(lambda: asyncio.get_event_loop().run_until_complete(http_request_session.close()))
async def request_coro(url, data=None, method='GET', maxtries=3, headers={}, timeout=5, allow_redirects=True):
	headers["User-Agent"] = "LRRbot/2.0 (https://lrrbot.mrphlip.com/)"
	firstex = None

	if method == 'GET':
		params = data
		data = None
	else:
		params = None
	while True:
		try:
			with async_timeout.timeout(timeout):
				async with http_request_session.request(method, url, params=params, data=data, headers=headers, allow_redirects=allow_redirects) as res:
					if method == "HEAD":
						return res
					status_class = res.status // 100
					if status_class != 2:
						await res.read()
						if status_class == 4:
							maxtries = 1
						raise urllib.error.HTTPError(res.url, res.status, res.reason, res.headers, None)
					text = await res.text()
					return text
		except utils.PASSTHROUGH_EXCEPTIONS:
			raise
		except Exception as e:
			maxtries -= 1
			if firstex is None:
				firstex = e
			if maxtries > 0:
				log.info("Downloading %s failed: %s: %s, retrying...", url, e.__class__.__name__, e)
			else:
				break
	raise firstex
