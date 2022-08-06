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

USER_AGENT = "LRRbot/2.0 (https://lrrbot.com/)"

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

def request(url, data=None, method='GET', maxtries=3, headers=None, timeout=30, asjson=False, **kwargs):
	"""Download a webpage, with retries on failure."""
	if headers is None:
		headers = {}
	# Let's be nice.
	headers["User-Agent"] = USER_AGENT

	if headers.get('Accept') == 'application/vnd.twitchtv.v5+json':
		log.warning("v5 request to: %r", url)

	if data:
		if asjson and method != 'GET':
			headers['Content-Type'] = "application/json"
			data = json.dumps(data)
		elif isinstance(data, dict):
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
			log.debug("%s %r...", req.get_method(), req.get_full_url())
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

_http_request_sessions = {}
def get_http_request_session(loop):
	if loop not in _http_request_sessions:
		# clean up any closed event loops from the cache
		to_del = [l for l in _http_request_sessions.keys() if l.is_closed()]
		for l in to_del:
			del _http_request_sessions[l]

		_http_request_sessions[loop] = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=6, loop=loop))
	return _http_request_sessions[loop]

async def request_coro(url, data=None, method='GET', maxtries=3, headers=None, timeout=30, allow_redirects=True, asjson=False):
	if headers is None:
		headers = {}
	headers["User-Agent"] = USER_AGENT

	if headers.get('Accept') == 'application/vnd.twitchtv.v5+json':
		log.warning("v5 request to: %r", url)

	if method == 'GET':
		params = data
		data = None
	else:
		params = None
		if asjson:
			headers['Content-Type'] = "application/json"
			data = json.dumps(data)

	firstex = None
	while True:
		try:
			with async_timeout.timeout(timeout):
				log.debug("%s %r%s...", method, url, repr(params) if params else '')
				session = get_http_request_session(asyncio.get_running_loop())
				async with session.request(method, url, params=params, data=data, headers=headers, allow_redirects=allow_redirects) as res:
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
