"""
# Undocumented PubSub topic: `video-playback.<channel name>` or `video-playback-by-id.<channel ID>`

## `stream-up` message:
Sent when stream goes live.

Example: '{"play_delay": 0, "type": "stream-up", "server_time": 1497116829.584907}'

## `viewcount` message:
They seem to be sent every five seconds while stream is live.

Example: '{"type":"viewcount","server_time":1497148129.038571,"viewers":482}'

## `commercial` message:
Example: '{"type": "commercial", "length": 180, "server_time": 1497148003.553933}'

## `stream-down` message:
Sent when stream goes offline.

Example: '{"type": "stream-down", "server_time": 1497148117.77978}'
"""

import sqlalchemy
from common import pubsub
from common import twitch
from common import utils
from common.config import config
import logging

log = logging.getLogger(__name__)

class VideoPlayback:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop

		users = self.lrrbot.metadata.tables["users"]
		with self.lrrbot.engine.begin() as conn:
			row = conn.execute(sqlalchemy.select([users.c.id, users.c.name]).where(users.c.name == config['username'])).first()
		if row is not None:
			channel_id, channel_name = row

			topics = ["video-playback.%s" % channel_name, "video-playback-by-id.%s" % channel_id]

			self.lrrbot.pubsub.subscribe(topics)

			for topic in topics:
				pubsub.signals.signal(topic).connect(self.on_message)

	@utils.cache(period=20)
	def flush_caches(self):
		log.debug("Flushing stream data cache")
		twitch.get_info.reset_throttle()
		self.lrrbot.get_game_id.reset_throttle()
	
	def flush_caches_until(self, stream_is_live):
		self.flush_caches()

		log.debug("Checking stream status")
		try:
			retry = twitch.get_info()['live'] != stream_is_live
		except utils.PASSTHROUGH_EXCEPTIONS:
			raise
		except Exception:
			log.exception("Error while checking stream status")
			retry = True
		
		if retry:
			log.debug("Stream not in desired state, retrying in 30 seconds")
			self.loop.call_later(30, self.flush_caches_until, stream_is_live)
		else:
			log.debug("Stream is in the desired state")

	def on_message(self, sender, message):
		if message["type"] == "stream-up":
			self.flush_caches_until(stream_is_live=True)
		elif message["type"] == "stream-down":
			self.flush_caches_until(stream_is_live=False)
