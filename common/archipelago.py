import asyncio
import aiohttp
import json
import logging
from common import http, rpc, utils
from common.config import config

log = logging.getLogger("archipelago")

# AFAICT the Archipelago server doesn't actually do anything with this UUID
# but we do have to have one
UUID = "a6f5066f-2965-40b6-af04-c29c334ae9a7"

# See https://github.com/ArchipelagoMW/Archipelago/blob/main/docs/network%20protocol.md

class ArchipelagoClient:
	def __init__(self, lrrbot, host, port, password, name, respconn, respond_to):
		self.lrrbot = lrrbot
		self.loop = lrrbot.loop
		self.host = host
		self.port = port
		self.password = password
		self.name = name
		self.respconn = respconn
		self.respond_to = respond_to

		self.connected = False
		self.closed = False
		self.task = None
		self.conn = None

		self.roominfo = None
		self.datapackage = None
		self.slots = None
		self.roominfo_event = asyncio.Event()
		self.datapackage_event = asyncio.Event()
		self.connected_event = asyncio.Event()

	def start(self):
		log.debug("Starting Archipelago")
		self.task = self.loop.create_task(self.connect())
		self.task.add_done_callback(utils.check_exception)

	def stop(self):
		log.debug("Stop Archipelago")
		self.connected = False
		self.closed = True
		if self.task:
			self.task.cancel()

	async def connect(self):
		# the official client tries ws:// first, then falls back to wss://
		# but here at LRRbot we are security-first in all situations
		try:
			await self.try_connect("wss:")
		except aiohttp.client_exceptions.ClientConnectorSSLError:
			await self.try_connect("ws:")

	async def try_connect(self, proto):
		self.reset()

		endpoint = f"{proto}//{self.host}:{self.port}/"
		http_session = await http.get_http_request_session()
		log.debug("Connecting to %s", endpoint)
		async with http_session.ws_connect(endpoint, heartbeat=30, compress=15) as conn:
			self.conn = conn

			message_loop = self.loop.create_task(self.message_loop())
			try:
				await self.handshake()
			except Exception:
				self.respconn.privmsg(self.respond_to, "Archipelago connection failed")
				raise
			else:
				self.respconn.privmsg(self.respond_to, "Archipelago connection successful")
			await message_loop

	def reset(self):
		self.connected = False
		self.closed = False
		self.roominfo = None
		self.datapackage = None
		self.slots = None
		self.roominfo_event.clear()
		self.datapackage_event.clear()
		self.connected_event.clear()

	async def send_packet(self, packet):
		log.debug("tx: %r", packet)
		await self.conn.send_json([packet])

	async def handshake(self):
		try:
			await asyncio.wait_for(self.roominfo_event.wait(), 30)
		except TimeoutError:
			raise Exception("Timed out waiting for RoomInfo packet")

		password_required = self.roominfo.get("password")
		if password_required and not self.password:
			raise ValueError("Password required")

		await self.send_packet({
			"cmd": "GetDataPackage",
			"games": self.roominfo.get("games"),
		})
		try:
			await asyncio.wait_for(self.datapackage_event.wait(), 30)
		except TimeoutError:
			raise Exception("Timed out waiting for DataPackage packet")

		await self.send_packet({
			"cmd": "Connect",
			"password": self.password if password_required else None,
			"game": None,
			"name": self.name,
			"uuid": UUID,
			"version": {"class": "Version", "major": 0, "minor": 6, "build": 7},
			"items_handling": 0,
			"tags": ["TextOnly"],
			"slot_data": False,
		})

		try:
			await asyncio.wait_for(self.connected_event.wait(), 30)
		except TimeoutError:
			raise Exception("Timed out waiting for Connected packet")

	async def message_loop(self):
		while True:
			packets = await self.conn.receive_json()
			if not isinstance(packets, list):
				log.warning("Received value is not a list: %r", packets)
				continue
			for packet in packets:
				if not isinstance(packet, dict):
					log.warning("Received packet is not a dict: %r", packet)
					continue

				if packet.get("cmd") == "DataPackage":
					# Don't log the entire data package, it's multiple megabytes of miscellaneous json
					log.debug("rx: [...DataPackage...]")
				else:
					log.debug("rx: %r", packet)

				cmd = packet.get("cmd", "UNSET")
				handler = self.HANDLERS.get(cmd)
				if handler:
					await handler(self, packet)

	async def handle_roominfo(self, packet):
		self.roominfo = packet
		self.roominfo_event.set()

	async def handle_datapackage(self, packet):
		self.datapackage = packet["data"]
		# datapackage contains:
		# {
		#   "games":
		#   {
		#     "game name": {
		#       "item_name_to_id": {"name": id, ...},
		#       "location_name_to_id": {"name": id, ...},
		#     },
		#     ...
		#   }
		# }
		# but we really want the reverse, id-to-name maps
		for game in self.datapackage["games"].values():
			game["item_id_to_name"] = {v:k for k,v in game["item_name_to_id"].items()}
			game["location_id_to_name"] = {v:k for k,v in game["location_name_to_id"].items()}
		self.datapackage_event.set()

	async def handle_connected(self, packet):
		self.connected = True
		# convert keys back to ints (because json can only have string keys)
		self.slots = {int(k): v for k, v in packet["slot_info"].items()}
		self.connected_event.set()

	async def handle_connrefused(self, packet):
		self.connected_event.set()  # let the handshake method stop waiting
		raise Exception(f"Connection refused: {packet.get('errors')!r}")

	async def handle_print(self, packet):
		if packet.get("type") == "ItemSend":
			await self.handle_itemsend(packet)

	async def handle_itemsend(self, packet):
		try:
			sender = self.slots[packet["item"]["player"]]
			recipient = self.slots[packet["receiving"]]
			sender_name = sender["name"]
			recip_name = recipient["name"]
			item = self.datapackage["games"][recipient["game"]]["item_id_to_name"][packet["item"]["item"]]
			location = self.datapackage["games"][sender["game"]]["location_id_to_name"][packet["item"]["location"]]
			flags = []
			if packet["item"]["flags"] & 1:
				flags.append("progression")
			if packet["item"]["flags"] & 2:
				flags.append("useful")
			if packet["item"]["flags"] & 4:
				flags.append("trap")
		except KeyError:
			# I'm too lazy to code in failsafes for all of those dict lookups
			# this will be enough
			log.exception("Couldn't find something with %r", packet)
		else:
			log.info("ItemSend: from=%r to=%r item=%r loc=%r flags=%r", sender["name"], recipient["name"], item, location, flags)
			if sender_name == recip_name:
				message = f"{sender_name} found their own {item} ({location})"
			else:
				message = f"{sender_name} sent {item} to {recip_name} ({location})"
			self.lrrbot.connection.privmsg("#" + config['channel'], message)

			data = {
				"sender": sender_name,
				"recipient": recip_name,
				"item": item,
				"location": location,
				"flags": flags,
			}
			await rpc.eventserver.event("archipelago-itemsend", data)


	HANDLERS = {
		"RoomInfo": handle_roominfo,
		"DataPackage": handle_datapackage,
		"Connected": handle_connected,
		"ConnectionRefused": handle_connrefused,
		"PrintJSON": handle_print,
	}
