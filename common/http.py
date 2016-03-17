import asyncio
import atexit
import json
import logging
import urllib.parse
import urllib.request

import aiohttp

from common import config

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
@asyncio.coroutine
def request_coro(url, data=None, method='GET', maxtries=3, headers={}, timeout=5, allow_redirects=True):
	headers["User-Agent"] = "LRRbot/2.0 (https://lrrbot.mrphlip.com/)"
	firstex = None

	# FIXME(#130): aiohttp fails to decode HEAD requests with Content-Encoding set. Do GET requests instead.
	real_method = method
	if method == 'HEAD':
		real_method = 'GET'

	if method == 'GET':
		params = data
		data = None
	else:
		params = None
	while True:
		try:
			res = yield from asyncio.wait_for(http_request_session.request(real_method, url, params=params, data=data, headers=headers, allow_redirects=allow_redirects), timeout)
			if method == "HEAD":
				yield from res.release()
				return res
			status_class = res.status // 100
			if status_class != 2:
				yield from res.read()
				if status_class == 4:
					maxtries = 1
				yield from res.release()
				raise urllib.error.HTTPError(res.url, res.status, res.reason, res.headers, None)
			text = yield from res.text()
			yield from res.release()
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

def api_request(uri, *args, **kwargs):
	# Send the information to the server
	try:
		res = request(config.config['siteurl'] + uri, *args, **kwargs)
	except utils.PASSTHROUGH_EXCEPTIONS:
		raise
	except:
		log.exception("Error at server in %s" % uri)
	else:
		try:
			res = json.loads(res)
		except ValueError:
			log.exception("Error parsing server response from %s: %s", uri, res)
		else:
			if 'success' not in res:
				log.error("Error at server in %s" % uri)
			return res

@asyncio.coroutine
def api_request_coro(uri, *args, **kwargs):
	try:
		res = yield from request_coro(config.config['siteurl'] + uri, *args, **kwargs)
	except utils.PASSTHROUGH_EXCEPTIONS:
		raise
	except:
		log.exception("Error at server in %s" % uri)
	else:
		try:
			res = json.loads(res)
		except ValueError:
			log.exception("Error parsing server response from %s: %s", uri, res)
		else:
			if 'success' not in res:
				log.error("Error at server in %s" % uri)
			return res
