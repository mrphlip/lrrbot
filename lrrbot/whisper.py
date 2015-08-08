import irc.bot, irc.client
from common import utils
from common.config import config
from lrrbot import twitch, storage, asyncreactor
import logging
import select

log = logging.getLogger('whisper')

class TwitchWhisper(irc.bot.SingleServerIRCBot):
	def __init__(self, loop):
		self.loop = loop
		servers = [irc.bot.ServerSpec(
			host=host,
			port=port,
			password="oauth:%s" % storage.data['twitch_oauth'][config['username']] if config['password'] == "oauth" else config['password'],
		) for host, port in twitch.get_group_servers()]
		super(TwitchWhisper, self).__init__(
			server_list=servers,
			realname=config['username'],
			nickname=config['username'],
			reconnection_interval=config['reconnecttime'],
		)

		self.reactor.execute_every(period=config['keepalivetime'], function=self.do_keepalive)
		self.reactor.add_global_handler('welcome', self.on_connect)

	def reactor_class(self):
		return asyncreactor.AsyncReactor(self.loop)

	@utils.swallow_errors
	def do_keepalive(self):
		"""Send a ping to the server, to ensure our connection stays alive, or to detect when it drops out."""
		try:
			self.connection.ping("keep-alive")
		except irc.client.ServerNotConnectedError:
			pass

	def on_connect(self, conn, event):
		"""On connecting to the server, set up the connection"""
		log.info("Connected to group chat server")
		conn.cap("REQ", "twitch.tv/tags") # get metadata tags
		conn.cap("REQ", "twitch.tv/commands") # get special commands

	def add_whisper_handler(self, handler):
		self.reactor.add_global_handler('whisper', handler)

	def whisper(self, target, text):
		if self.connection:
			self.connection.privmsg("#jtv", "/w %s %s" % (target, text))
