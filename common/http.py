import asyncio
import atexit
import contextlib
import gc
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import aiohttp
import async_timeout
import dateutil.parser

from common import utils

log = logging.getLogger("common.http")

USER_AGENT = "LRRbot/2.0 (https://lrrbot.com/)"

_http_request_sessions = {}
async def get_http_request_session():
	loop = asyncio.get_running_loop()
	if loop not in _http_request_sessions:
		# clean up any closed event loops from the cache
		# just doing this when making new sessions, so we don't do it too much for performance
		# but still do it often enough that the cache can't just grow forever
		
		# first make sure any lingering network transports have been cleaned up
		# because apparently something in asyncio or aiohttp is leaking these things
		gc.collect()
		# now close down the sessions
		to_del = [(l, s) for l, s in _http_request_sessions.items() if l.is_closed()]
		for l, s in to_del:
			await s.close()
			del _http_request_sessions[l]
		# again for good measure
		gc.collect()

		_http_request_sessions[loop] = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=6, loop=loop))
	return _http_request_sessions[loop]
async def _cleanup_sessions():
	gc.collect()
	for l, s in _http_request_sessions.items():
		await s.close()
	_http_request_sessions.clear()
	gc.collect()
atexit.register(asyncio.run, _cleanup_sessions())

async def request(url, data=None, method='GET', maxtries=3, headers=None, timeout=30, allow_redirects=True, asjson=False):
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
				session = await get_http_request_session()
				async with session.request(method, url, params=params, data=data, headers=headers, allow_redirects=allow_redirects) as res:
					if method == "HEAD":
						return res
					status_class = res.status // 100
					if status_class != 2:
						log.debug('%s %s failed, response body: %s', method, url, await res.read())
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

def download_file(url, fn, only_if_newer=False):
	"""
	Download a file, optionally checking that there is a new version of the file on the
	server before doing so. Returns True if a download occurs.
	"""
	# Much of this code cribbed from urllib.request.urlretrieve, with If-Modified-Since logic added

	req = urllib.request.Request(url, headers={
		'User-Agent': USER_AGENT,
	})
	if only_if_newer:
		try:
			stat = os.stat(fn)
		except FileNotFoundError:
			pass
		else:
			mtime = time.strftime('%a, %d %b %Y %H:%M:%S %z', time.gmtime(stat.st_mtime))
			req.add_header('If-Modified-Since', mtime)

	try:
		fp = urllib.request.urlopen(req)
	except urllib.error.HTTPError as e:
		if e.code == 304:  # Not Modified
			return False
		else:
			raise

	log.info("Downloading %s..." % url)
	with contextlib.closing(fp):
		headers = fp.info()

		with open(fn, 'wb') as tfp:
			bs = 1024*8
			size = None
			read = 0
			if "content-length" in headers:
				size = int(headers["Content-Length"])

			while True:
				block = fp.read(bs)
				if not block:
					break
				read += len(block)
				tfp.write(block)

	if size is not None and read < size:
		os.unlink(fn)
		raise urllib.error.ContentTooShortError(
			"retrieval incomplete: got only %i out of %i bytes"
			% (read, size), (fn, headers))

	if "last-modified" in headers:
		mtime = dateutil.parser.parse(headers['last-modified'])
		mtime = mtime.timestamp()
		os.utime(fn, (mtime, mtime))

	return True
