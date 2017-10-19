import aiomas
import logging
import sqlalchemy

from common import rpc
from common import twitch
from common.config import config

log = logging.getLogger(__name__)

class Announcements:
	router = aiomas.rpc.Service()

	def __init__(self, eris, signals, engine, metadata):
		self.eris = eris
		self.signals = signals
		self.engine = engine
		self.metadata = metadata

	@aiomas.expose
	async def stream_up(self, data):
		channel = self.eris.get_server(config['discord_serverid']).get_channel(config['discord_channel_announcements'])
		if channel is None:
			log.error("No announcements channel")
			return

		game_id = await rpc.bot.get_game_id()
		show_id = await rpc.bot.get_show_id()

		games = self.metadata.tables['games']
		shows = self.metadata.tables['shows']
		game_per_show_data = self.metadata.tables['game_per_show_data']

		with self.engine.begin() as conn:
			show, = conn.execute(sqlalchemy.select([shows.c.name]).where(shows.c.id == show_id)).first()

			if game_id is not None:
				game, = conn.execute(sqlalchemy.select([games.c.name])
					.select_from(
						games
							.outerjoin(game_per_show_data,
								(games.c.id == game_per_show_data.c.game_id) & (game_per_show_data.c.show_id == show_id)
							)
					).where(games.c.id == game_id)).first()
				description = "%s on %s" % (game, show)
			else:
				description = show

		await self.eris.send_message(channel, "%s is live with %s (%s)! <%s>" % (data['display_name'], description, data['status'], data['url']))
