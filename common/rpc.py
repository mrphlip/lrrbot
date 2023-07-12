import aiomas
import asyncio
import datetime
import logging
import pytz

from common.config import config

log = logging.getLogger('common.rpc')

#CODEC = aiomas.codecs.MsgPack
CODEC = aiomas.codecs.JSON
EXTRA_SERIALIZERS = [
	lambda: (datetime.datetime, lambda t: t.timestamp(), lambda t: datetime.datetime.fromtimestamp(t, pytz.utc))
]

class Server:
	def __init__(self):
		self.__server = None
		self.__clients = []

	async def start(self, path, port):
		try:
			self.__server = await aiomas.rpc.start_server(path, self, self.on_rpc_client_connect, codec=CODEC, extra_serializers=EXTRA_SERIALIZERS)
		except NotImplementedError:
			self.__server = await aiomas.rpc.start_server(('localhost', port), self, self.on_rpc_client_connect, codec=CODEC, extra_serializers=EXTRA_SERIALIZERS)

	def on_rpc_client_connect(self, client):
		client.on_connection_reset(lambda exc: self.__clients.remove(client))
		self.__clients.append(client)

	async def close(self):
		self.__server.close()
		await self.__server.wait_closed()
		for client in self.__clients:
			await client.close()

class Proxy:
	def __init__(self, client, path):
		self.__client = client
		self.__path = path

	def __getattr__(self, key):
		return Proxy(self.__client, self.__path + [key])

	async def __call__(self, *args, **kwargs):
		for _ in range(3):
			try:
				await self.__client.connect()
				node = self.__client._connection.remote
				for key in self.__path:
					node = getattr(node, key)
				return await node(*args, **kwargs)
			except ConnectionResetError:
				self.__client._connection = None
				await asyncio.sleep(1)
		raise ConnectionResetError

class Client:
	def __init__(self, path, port):
		self._connection = None
		self.__path = path
		self.__port = port

	def __unset_connection(self, exc):
		self._connection = None

	async def connect(self):
		if self._connection is None:
			service = aiomas.rpc.ServiceDict({})
			try:
				self._connection = await aiomas.rpc.open_connection(self.__path, rpc_service=service, codec=CODEC, extra_serializers=EXTRA_SERIALIZERS)
			except NotImplementedError:
				self._connection = await aiomas.rpc.open_connection(('localhost', self.__port), rpc_service=service, codec=CODEC, extra_serializers=EXTRA_SERIALIZERS)
			self._connection.on_connection_reset(self.__unset_connection)

	async def close(self):
		if self._connection is not None:
			await self._connection.close()

	def __getattr__(self, key):
		return Proxy(self, [key])

bot = Client(config['socket_filename'], config['socket_port'])
eventserver = Client(config['eventsocket'], config['event_port'])
eris = Client(config['eris_socket'], config['eris_port'])
