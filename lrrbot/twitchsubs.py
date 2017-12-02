import time
import re
import logging
import datetime
import dateutil
import asyncio
import sqlalchemy
import urllib.error
import irc.client
import pytz
from common import utils
from common.config import config
from common import twitch
from common import http
from lrrbot import storage
from lrrbot import chatlog
import common.rpc
import common.storm

log = logging.getLogger('twitchsubs')

DELAY_FOR_SUBS_FROM_API = 60
DEBOUNCE_INTERVAL = 600

class TwitchSubs:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop
		self.last_subs = None
		self.recent_announced_subs = {}
		users = self.lrrbot.metadata.tables['users']

		self.lrrbot.reactor.add_global_handler('usernotice', self.on_usernotice, 90)

	def on_usernotice(self, conn, event):
		self.lrrbot.check_message_tags(conn, event)
		if event.tags.get('msg-id') in ('sub', 'resub', 'subgift'):
			if len(event.arguments) > 0:
				message = event.arguments[0]
			else:
				message = None

			monthcount = event.tags.get('msg-param-months')
			if monthcount is not None:
				monthcount = int(monthcount)
			else:
				monthcount = 1

			display_name = event.tags.get('display-name') or event.tags['login']

			recipient_display_name = event.tags.get('msg-param-recipient-user-name') or event.tags.get('msg-param-recipient-user-name')
			if recipient_display_name is not None:
				benefactor_display_name = display_name
				display_name = recipient_display_name
			else:
				benefactor_display_name = None

			systemmsg = event.tags.get('system-msg')
			if not systemmsg:
				if monthcount > 1:
					systemmsg = "%s has subscribed for %s months!" % (display_name, monthcount)
				else:
					systemmsg = "%s just subscribed!" % (display_name, )

			asyncio.ensure_future(self.on_subscriber(
				conn,
				"#" + config['channel'],
				display_name,
				datetime.datetime.now(tz=pytz.utc),
				monthcount=monthcount,
				message=message,
				emotes=event.tags.get('emotes'),
				benefactor=benefactor_display_name,
			)).add_done_callback(utils.check_exception)

			# Make fake chat messages for this resub in the chat log
			# This makes the resub message just show up as a normal message, which is close enough
			self.lrrbot.log_chat(conn, irc.client.Event(
				"pubmsg",
				"%s!%s@tmi.twitch.tv" % (config['notifyuser'], config['notifyuser']),
				event.target,
				[systemmsg],
				{},
			))
			if message:
				self.lrrbot.log_chat(conn, irc.client.Event(
					"pubmsg",
					event.source,
					event.target,
					[message],
					event.tags,
				))
			return "NO MORE"

	async def on_subscriber(self, conn, channel, user, eventtime, logo=None, monthcount=None, message=None, emotes=None, benefactor=None):
		log.info('New subscriber: %r at %r', user, eventtime)

		now = time.time()
		for k in [k for k, v in self.recent_announced_subs.items() if v < now - DEBOUNCE_INTERVAL]:
			del self.recent_announced_subs[k]
		if user.lower() in self.recent_announced_subs:
			log.info('Debouncing subscriber %r', user)
			return
		self.recent_announced_subs[user.lower()] = now

		data = {
			'name': user,
			'benefactor': benefactor,
		}
		if logo is None:
			try:
				channel_info = twitch.get_info_uncached(user)
			except utils.PASSTHROUGH_EXCEPTIONS:
				raise
			except Exception:
				pass
			else:
				if channel_info.get('logo'):
					data['avatar'] = channel_info['logo']
		else:
			data['avatar'] = logo

		users = self.lrrbot.metadata.tables["users"]
		with self.lrrbot.engine.begin() as pg_conn:
			pg_conn.execute(users.update().where(users.c.name == user), is_sub=True)

		if message is not None:
			data['message'] = message
			data['messagehtml'] = await chatlog.format_message(message, emotes, [], cheer=False)

		if monthcount > 1:
			event = "twitch-resubscription"
			data['monthcount'] = monthcount
			data['count'] = common.storm.increment(self.lrrbot.engine, self.lrrbot.metadata, event)
		else:
			event = "twitch-subscription"
			data['count'] = common.storm.increment(self.lrrbot.engine, self.lrrbot.metadata, event)

		storm_count = common.storm.get_combined(self.lrrbot.engine, self.lrrbot.metadata)
		conn.privmsg(channel, "lrrSPOT Thanks for subscribing, %s! (Today's storm count: %d)" % (data['name'], storm_count))

		await common.rpc.eventserver.event(event, data, eventtime)
