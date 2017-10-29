import aiomas
import asyncio
import logging
import peony
import sqlalchemy

from common import rpc
from common import state
from common import twitch
from common import utils
from common.config import config

log = logging.getLogger(__name__)

STATE_TWITTER_LAST_TWEET_ID_KEY = 'eris.announcements.twitter.%s.last_tweet_id'

class Announcements:
	router = aiomas.rpc.Service()

	def __init__(self, eris, signals, engine, metadata):
		self.eris = eris
		self.signals = signals
		self.engine = engine
		self.metadata = metadata
		self.tweet_task = None

		self.signals.signal('ready').connect(self.start_tweet_task)

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

	def start_tweet_task(self, eris):
		if self.tweet_task is None:
			self.tweet_task = asyncio.ensure_future(self.post_tweets())
			self.tweet_task.add_done_callback(utils.check_exception)

	async def post_tweets(self):
		channel = self.eris.get_server(config['discord_serverid']).get_channel(config['discord_channel_announcements'])
		if channel is None:
			log.error("No announcements channel")
			return

		twitter = peony.PeonyClient(consumer_key=config['twitter_api_key'], consumer_secret=config['twitter_api_secret'])

		users = await twitter.api.users.lookup.get(screen_name=",".join(config["twitter_users"]))
		user_ids = {user.id for user in users}

		while True:
			try:
				for user in users:
					since_id_key = STATE_TWITTER_LAST_TWEET_ID_KEY % user.id
					since_id = state.get(self.engine, self.metadata, since_id_key)
					if since_id is None:
						try:
							last_tweet_id = list(await twitter.api.statuses.user_timeline.get(user_id=user.id, include_rts=True))[0].id
						except IndexError:
							last_tweet_id = 1
					else:
						last_tweet_id = since_id
						for tweet in list(await twitter.api.statuses.user_timeline.get(user_id=user.id, since_id=since_id, include_rts=True))[::-1]:
							last_tweet_id = tweet.id
							if tweet.in_reply_to_user_id is None or tweet.in_reply_to_user_id in user_ids:
								await self.eris.send_message(channel, "New tweet from %(name)s: https://twitter.com/%(screen_name)s/status/%(tweet_id)s" % {
									"name": tweet.user.name,
									"screen_name": tweet.user.screen_name,
									"tweet_id": tweet.id,
								})
					state.set(self.engine, self.metadata, since_id_key, last_tweet_id)
			except utils.PASSTHROUGH_EXCEPTIONS:
				raise
			except Exception:
				log.exception("Exception in Twitter announcement task")
				continue
			await asyncio.sleep(15)
