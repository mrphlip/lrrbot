import aiohttp
import asyncio
import blinker
import uuid
import logging
import json
import random

from common import http, twitch
from common import utils
from common.config import config

__all__ = ["PubSub", "signals"]

signals = blinker.Namespace()
log = logging.getLogger('common.pubsub')

class Topic:
	def __init__(self, as_user):
		self.as_user = as_user
		self.refcount = 1

class PubSub:
	def __init__(self, engine, metadata, loop):
		self.engine = engine
		self.metadata = metadata
		self.loop = loop
		self.topics = {}

		self.task = None
		self.stream = None
		self.ping_task = None
		self.disconnect_task = None

	async def _send(self, message):
		log.debug("Sending: %r", message)
		await self.stream.send_json(message)

	async def _listen(self, topics, user):
		message_id = uuid.uuid4().hex
		log.debug("Listening for topics %r as %r, message %s", topics, user, message_id)
		await self._send({
			'type': "LISTEN",
			'nonce': message_id,
			'data': {
				'topics': topics,
				'auth_token': await twitch.get_token(name=user),
			}
		})

	async def _unlisten(self, topics):
		message_id = uuid.uuid4().hex
		log.debug("Unlistening topics %r, message %s", topics, message_id)
		await self._send({
			'type': 'UNLISTEN',
			'nonce': message_id,
			'data': {
				'topics': topics,
			}
		})

	def subscribe(self, topics, as_user=None):
		if as_user is None:
			as_user = config['username']

		new_topics = []

		for topic in topics:
			if topic not in self.topics:
				self.topics[topic] = Topic(as_user)
				new_topics.append(topic)
			else:
				if self.topics[topic].as_user != as_user:
					raise Exception("Already listening for %r as %r", topic, self.topics[topic].as_user)
				self.topics[topic].refcount += 1

		if len(new_topics) > 0:
			if self.stream is not None:
				self.loop.run_until_complete(self._listen(new_topics, as_user))
			elif self.task is None:
				self.task = asyncio.ensure_future(self.message_pump(), loop=self.loop)

	def unsubscribe(self, topics):
		orphan_topics = []
		for topic in topics:
			self.topics[topic].refcount -= 1
			if self.topics[topic].refcount <= 0:
				del self.topics[topic]
				orphan_topics.append(topic)
		if len(orphan_topics) > 0 and self.stream is not None:
			self.loop.run_until_complete(self._unlisten(orphan_topics))

	def close(self):
		if self.task is not None:
			self.task.cancel()
		if self.ping_task is not None:
			self.ping_task.cancel()
		if self.disconnect_task is not None:
			self.disconnect_task.cancel()

	async def _ping(self):
		timeout = 5 * 60
		while True:
			next_timeout = random.gauss(3 * timeout / 4, timeout / 8)
			next_timeout = max(1, min(next_timeout, timeout))
			log.debug("Sending a PING in %f seconds", next_timeout)
			await asyncio.sleep(next_timeout)
			log.debug("Sending a PING.")
			await self._send({
				'type': 'PING',
			})
			self.disconnect_task = asyncio.ensure_future(self._disconnect(), loop=self.loop)
			self.disconnect_task.add_done_callback(utils.check_exception)

	async def _disconnect(self):
		try:
			await asyncio.sleep(10)
			log.debug("Disconnecting due to missed PONG.")
			if self.stream is not None:
				await self.stream.close()
			self.disconnect_task = None
		except asyncio.CancelledError:
			return

	async def message_pump(self):
		next_timeout = 1
		error = False
		while True:
			try:
				log.debug("Connecting to wss://pubsub-edge.twitch.tv")
				session = await http.get_http_request_session()
				async with session.ws_connect("wss://pubsub-edge.twitch.tv") as pubsub:
					log.debug("Connected to wss://pubsub-edge.twitch.tv")
					self.stream = pubsub
					self.ping_task = asyncio.ensure_future(self._ping(), loop=self.loop)
					self.ping_task.add_done_callback(utils.check_exception)

					# TODO: coalesce topics
					for_user = {}
					for topic, data in self.topics.items():
						for_user.setdefault(data.as_user, []).append(topic)
					for user, topics in for_user.items():
						await self._listen(topics, user)

					async for message in pubsub:
						if message.type == aiohttp.WSMsgType.TEXT:
							next_timeout = 1
							msg = json.loads(message.data)
							log.debug("New message: %r", msg)
							if msg['type'] == 'RESPONSE':
								if msg['error']:
									log.error("Error in response to message %s: %s", msg['nonce'], msg['error'])
							elif msg['type'] == 'MESSAGE':
								signals.signal(msg['data']['topic']).send(self, message=json.loads(msg['data']['message']))
							elif msg['type'] == 'RECONNECT':
								await pubsub.close()
								error = False
								break
							elif msg['type'] == 'PONG':
								log.debug("Received a PONG")
								self.disconnect_task.cancel()
								self.disconnect_task = None
						elif message.type == aiohttp.WSMsgType.CLOSED:
							error = True
							break
						elif message.type == aiohttp.WSMsgType.ERROR:
							raise Exception("Error reading message") from pubsub.exception()
			except utils.PASSTHROUGH_EXCEPTIONS:
				raise
			except Exception:
				log.exception("Exception in PubSub message task")
				error = True
			finally:
				if self.ping_task is not None:
					self.ping_task.cancel()
					self.ping_task = None
				if self.disconnect_task is not None:
					self.disconnect_task.cancel()
					self.disconnect_task = None
				self.stream = None

			jitter = random.gauss(0, next_timeout / 4)
			jitter = max(-next_timeout, min(jitter, next_timeout))

			await asyncio.sleep(max(1, next_timeout + jitter))

			if error:
				next_timeout = min(next_timeout * 2, 120)
