import asyncio
import dateutil
import datetime
import sqlalchemy

from common.config import config
from common import rpc
from common import googlecalendar
from common import time
from common import utils
from common import twitch

import logging
log = logging.getLogger('eris.autotopic')

class Autotopic:
	def __init__(self, eris, signals, engine, metadata):
		self.eris = eris
		self.signals = signals
		self.engine = engine
		self.metadata = metadata

		self.timer_scheduled = False
		self.signals.signal('ready').connect(self.schedule_timer)

	# Simplified copy of `lrrbot.commands.misc.uptime_msg`.
	def uptime_msg(self):
		stream_info = twitch.get_info()
		if stream_info and stream_info.get("stream_created_at"):
			start = dateutil.parser.parse(stream_info["stream_created_at"])
			now = datetime.datetime.now(datetime.timezone.utc)
			return "The stream has been live for %s." % time.nice_duration(now - start, 0)
		elif stream_info and stream_info.get('live'):
			return "Twitch won't tell me when the stream went live."
		else:
			return "The stream is not live."

	@utils.swallow_errors
	async def update_topic(self):
		channel = self.eris.get_server(config['discord_serverid']).default_channel
		header = await rpc.bot.get_header_info()
		messages = []

		if header['is_live']:
			shows = self.metadata.tables["shows"]
			games = self.metadata.tables["games"]
			game_per_show_data = self.metadata.tables["game_per_show_data"]
			with self.engine.begin() as conn:
				if header.get('current_game'):
					game = conn.execute(sqlalchemy.select([
						sqlalchemy.func.coalesce(game_per_show_data.c.display_name, games.c.name)
					]).select_from(
						games.outerjoin(game_per_show_data,
							(game_per_show_data.c.game_id == games.c.id) &
								(game_per_show_data.c.show_id == header['current_show']['id']))
					).where(games.c.id == header['current_game']['id'])).first()
					if game is not None:
						game, = game
				else:
					game = None
				
				if header.get('current_show'):
					show = conn.execute(sqlalchemy.select([shows.c.name])
						.where(shows.c.id == header['current_show']['id'])
						.where(shows.c.string_id != "")).first()
					if show is not None:
						show, = show
				else:
					show = None

			if game and show:
				messages.append("Stream currently live: playing %s on %s." % (game, show))
			elif game:
				messages.append("Stream currently live: playing %s." % game)
			elif show:
				messages.append("Stream currently live: showing %s." % show)
			messages.append(self.uptime_msg())
		else:
			messages.append(googlecalendar.get_next_event_text(googlecalendar.CALENDAR_LRL))
		if header.get('advice'):
			messages.append(header['advice'])
		await self.eris.edit_channel(channel, topic=" ".join(messages))


	def schedule_update_topic(self):
		asyncio.ensure_future(self.update_topic(), loop=self.eris.loop).add_done_callback(utils.check_exception)
		self.eris.loop.call_later(60, self.schedule_update_topic)

	def schedule_timer(self, eris):
		if not self.timer_scheduled:
			self.timer_scheduled = True
			self.schedule_update_topic()
