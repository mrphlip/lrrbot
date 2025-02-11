import asyncio
import logging
from typing import Dict, Optional, Callable, Awaitable

import aiohttp
from blinker import Signal

from common import http, utils, twitch

log = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "wss://eventsub.wss.twitch.tv/ws"

# Timeout from connecting to the welcome message
CONNECT_TIMEOUT = 60

CLOSE_CODES = {
	4000: "Internal server error",
	4001: "Client sent inbound traffic",
	4002: "Client failed ping-pong",
	4003: "Connection unused",
	4004: "Reconnect grace time expired",
	4005: "Network timeout",
	4006: "Network error",
	4007: "Invalid reconnect",
}

class Session:
	def __init__(self, session_id: str, user: twitch.User) -> None:
		self.session_id = session_id
		self.user = user
		self.subscriptions: Dict[str, Callable[[dict], Awaitable[None]]] = {}

	async def listen(self, topic: str, version: str, condition: Dict[str, str], callback: Callable[[dict], Awaitable[None]]) -> None:
		subscription = await twitch.create_eventsub_subscription(topic, version, condition, {"method": "websocket", "session_id": self.session_id}, self.user.token)
		log.debug("Subscribed to %s version %s with condition %r as %s, received ID %s", topic, version, condition, self.user.name, subscription["id"])
		self.subscriptions[subscription["id"]] = callback

class Connection:
	def __init__(self, loop: asyncio.AbstractEventLoop, user: str):
		self.loop = loop

		self.user = user

		self.connected = Signal()

		self.keepalive_timeout = 0
		self.failure_count = 0

		self.previous_task: Optional[asyncio.Task] = None
		self.current_task: Optional[asyncio.Task] = None
		self.timeout_handle: Optional[asyncio.TimerHandle] = None

	def start(self) -> None:
		self.spawn_connect(DEFAULT_ENDPOINT, session=None)

	async def stop(self) -> None:
		if self.timeout_handle:
			self.timeout_handle.cancel()

		if self.previous_task:
			self.previous_task.cancel()
			try:
				await self.previous_task
			except asyncio.CancelledError:
				pass

		if self.current_task:
			self.current_task.cancel()
			try:
				await self.current_task
			except asyncio.CancelledError:
				pass

	def spawn_connect(self, endpoint: str, session: Optional[Session]) -> None:
		if self.previous_task:
			self.previous_task.cancel()
		self.previous_task = self.current_task

		task = self.loop.create_task(self.connect(endpoint, session))
		task.add_done_callback(self.reconnect_on_failure)
		self.current_task = task

	def reconnect_on_failure(self, task: asyncio.Task) -> None:
		try:
			task.result()
		except asyncio.CancelledError:
			raise
		except Exception:
			delay = min(2 ** self.failure_count, 128)
			self.failure_count += 1
			log.exception("connection task failed, reconnecting in %d second(s)", delay)
			self.loop.call_later(delay, self.spawn_connect, DEFAULT_ENDPOINT, None)

	def timeout_reset(self, timeout) -> None:
		if self.timeout_handle:
			self.timeout_handle.cancel()

		self.timeout_handle = self.loop.call_later(timeout, self.timed_out)

	def timed_out(self) -> None:
		log.warning("Connection timed out, reconnecting...")
		self.spawn_connect(DEFAULT_ENDPOINT, None)

	async def connect(self, endpoint: str, session: Optional[Session]) -> None:
		self.timeout_reset(CONNECT_TIMEOUT)

		http_session = await http.get_http_request_session()
		log.debug("Connecting to %s", endpoint)
		async with http_session.ws_connect(endpoint) as conn:
			while True:
				message = await conn.receive()
				if message.type == aiohttp.WSMsgType.TEXT:
					data = message.json()
					log.debug("Received message: %r", data)
					message_type = data["metadata"]["message_type"]
					if message_type == "session_welcome":
						self.failure_count = 0
						if self.previous_task:
							self.previous_task.cancel()
							self.previous_task = None

						if not session:
							session = Session(data["payload"]["session"]["id"], await twitch.get_user(name=self.user))
							await self.connected.send_async(session)

						# Add some slack to the keepalive timeout because otherwise we reconnect immediately before a
						# keepalive message arrives.
						self.keepalive_timeout = data["payload"]["session"]["keepalive_timeout_seconds"] + 2
						self.timeout_reset(self.keepalive_timeout)
					elif message_type == "session_keepalive":
						self.timeout_reset(self.keepalive_timeout)
					elif message_type == "notification":
						self.timeout_reset(self.keepalive_timeout)

						if callback := session.subscriptions.get(data["payload"]["subscription"]["id"]):
							self.loop.create_task(callback(data["payload"]["event"])).add_done_callback(utils.check_exception)
					elif message_type == "session_reconnect":
						self.spawn_connect(data["payload"]["session"]["reconnect_url"], session)
					elif message_type == "revocation":
						log.error("Subscription %s revoked", data["payload"]["subscription"]["id"])
					else:
						log.warning("Unknown message type: %s", message_type)
				elif message.type == aiohttp.WSMsgType.CLOSE:
					log.debug("Received close message: %d - %s", message.data, CLOSE_CODES.get(message.data, "Unknown"))
				elif message.type == aiohttp.WSMsgType.CLOSED:
					log.debug("Websocket closed, reconnecting...")
					self.spawn_connect(DEFAULT_ENDPOINT, None)
					break
				elif message.type == aiohttp.WSMsgType.ERROR:
					log.error("Error reading message, reconnecting...", exc_info=conn.exception())
					self.spawn_connect(DEFAULT_ENDPOINT, None)
					break

class EventSub:
	def __init__(self, loop: asyncio.AbstractEventLoop):
		self.loop = loop

		self.connections: Dict[str, Connection] = {}

	def start(self) -> None:
		for connection in self.connections.values():
			connection.start()

	async def stop(self) -> None:
		await asyncio.gather(connection.stop() for connection in self.connections.values())

	def __getitem__(self, user: str) -> Connection:
		try:
			return self.connections[user]
		except KeyError:
			connection = self.connections[user] = Connection(self.loop, user)
			return connection
