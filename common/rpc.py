import aiomas
import asyncio
import datetime
import logging
import pytz

from common import utils
from common.config import config

log = logging.getLogger('common.rpc')

try:
	CODEC = aiomas.codecs.MsgPack()
	CODEC = aiomas.codecs.MsgPack
except ImportError:
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
		await asyncio.gather(client.close() for client in self.__clients)

class Client:
	def __init__(self, path, port):
		self.__connection = None
		self.__path = path
		self.__port = port

	def __unset_connection(self, exc):
		self.__connection = None

	async def connect(self):
		if self.__connection is None:
			service = aiomas.rpc.ServiceDict({})
			try:
				self.__connection = await aiomas.rpc.open_connection(self.__path, rpc_service=service, codec=CODEC, extra_serializers=EXTRA_SERIALIZERS)
			except NotImplementedError:
				self.__connection = await aiomas.rpc.open_connection(('localhost', self.__port), rpc_service=service, codec=CODEC, extra_serializers=EXTRA_SERIALIZERS)
			self.__connection.on_connection_reset(self.__unset_connection)

	async def close(self):
		if self.__connection is not None:
			await self.__connection.close()

	def __getattr__(self, key):
		if self.__connection is None:
			raise ConnectionResetError()
		return getattr(self.__connection.remote, key)

bot = Client(config['socket_filename'], config['socket_port'])
eventserver = Client(config['eventsocket'], config['event_port'])
