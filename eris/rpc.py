import aiomas

from common import rpc

class Server(rpc.Server):
	router = aiomas.rpc.Service(['announcements'])

	def __init__(self):
		self.announcements = None
