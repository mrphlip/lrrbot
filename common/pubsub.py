import aiohttp
import asyncio
import blinker
import uuid
import logging
import sqlalchemy
import json
import random

from common import http
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
	def __init__(self, engine, metadata):
		self.engine = engine
		self.metadata = metadata
		self.topics = {}

		self.task = None
		self.stream = None
		self.ping_task = None
		self.disconnect_task = None

	def _token_for(self, user):
		users = self.metadata.tables["users"]
		with self.engine.begin() as conn:
			row = conn.execute(sqlalchemy.select([users.c.twitch_oauth]).where(users.c.name == user)).first()
			if row is not None:
				return row[0]
		raise Exception("User %r not found" % user)

	def _listen(self, topics, user):
		message_id = uuid.uuid4().hex
		log.debug("Listening for topics %r as %r, message %s", topics, user, message_id)
		self.stream.send_json({
			'type': "LISTEN",
			'nonce': message_id,
			'data': {
				'topics': topics,
				'auth_token': self._token_for(user),
			}
		})

	def _unlisten(self, topics):
		message_id = uuid.uuid4().hex
		log.debug("Unlistening topics %r, message %s", topics, message_id)
		self.stream.send_json({
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
				self._listen(new_topics, as_user)
			elif self.task is None:
				self.task = asyncio.ensure_future(self.message_pump())

	def unsubscribe(self, topics):
		orphan_topics = []
		for topic in topics:
			self.topics[topic].refcount -= 1
			if self.topics[topic].refcount <= 0:
				del self.topics[topic]
				orphan_topics.append(topic)
		if len(orphan_topics) > 0 and self.stream is not None:
			self._unlisten(orphan_topics)

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
			self.stream.send_json({
				'type': 'PING',
			})
			self.disconnect_task = asyncio.ensure_future(self._disconnect())
			self.disconnect_task.add_done_callback(utils.check_exception)

	async def _disconnect(self):
		await asyncio.sleep(10)
		log.debug("Disconnecting due to missed PONG.")
		if self.stream is not None:
			await self.stream.close()
		self.disconnect_task = None

	async def message_pump(self):
		next_timeout = 1
		error = False
		while True:
			try:
				log.debug("Connecting to wss://pubsub-edge.twitch.tv")
				async with http.http_request_session.ws_connect("wss://pubsub-edge.twitch.tv") as pubsub:
					log.debug("Connected to wss://pubsub-edge.twitch.tv")
					self.stream = pubsub
					self.ping_task = asyncio.ensure_future(self._ping())
					self.ping_task.add_done_callback(utils.check_exception)

					# TODO: coalesce topics
					for_user = {}
					for topic, data in self.topics.items():
						for_user.setdefault(data.as_user, []).append(topic)
					for user, topics in for_user.items():
						self._listen(topics, user)

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
