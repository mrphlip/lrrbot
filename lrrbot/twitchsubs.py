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

class TwitchSubs:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop
		self.last_subs = None
		self.last_announced_subs = []
		users = self.lrrbot.metadata.tables['users']

		# Precompile regular expressions
		self.re_subscription = re.compile(r"^(.*) just subscribed!$", re.IGNORECASE)
		self.re_resubscription = re.compile(r"^(.*) subscribed for (\d+) months? in a row!$", re.IGNORECASE)

		self.lrrbot.reactor.add_global_handler('privmsg', self.on_notification, 90)
		self.lrrbot.reactor.add_global_handler('pubmsg', self.on_notification, 90)
		self.lrrbot.reactor.add_global_handler('usernotice', self.on_usernotice, 90)

		self.watch_subs()

	def watch_subs(self):
		asyncio.ensure_future(self.do_check()).add_done_callback(utils.check_exception)
		self.loop.call_later(config['checksubstime'], self.watch_subs)

	@asyncio.coroutine
	def do_check(self):
		users = self.lrrbot.metadata.tables["users"]
		with self.lrrbot.engine.begin() as conn:
			token, = conn.execute(sqlalchemy.select([users.c.twitch_oauth])
				.where(users.c.name == config['channel'])).first()

		sublist = None
		if token is not None:
			try:
				sublist = yield from twitch.get_subscribers(config['channel'], token)
			except urllib.error.HTTPError as e:
				if e.code == 422: # Unprocessable Entity, channel not partnered
					return
		if not sublist:
			log.info("Failed to get subscriber list from Twitch")
			self.last_subs = None
			return

		# If this is the first time we've gotten the sub list then don't notify for all of them
		# as all of them will appear "new" even if we saw them on a previous run
		# Just add them to the "seen" list
		if self.last_subs is not None:
			for user, logo, sub_start, eventtime in sublist:
				if user.lower() not in self.last_subs:
					log.info("Found new subscriber via Twitch API: %s" % user)
					sub_start = dateutil.parser.parse(sub_start)
					eventtime = dateutil.parser.parse(eventtime)
					monthcount = round((eventtime - sub_start) / datetime.timedelta(days=30)) + 1
					self.on_subscriber_from_api(user, eventtime, logo, monthcount)
		else:
			log.debug("Got initial subscriber list from Twitch")

		self.last_subs = [i[0].lower() for i in sublist]

	def on_subscriber_from_api(self, user, eventtime, logo, monthcount):
		self.loop.call_later(DELAY_FOR_SUBS_FROM_API, lambda: asyncio.ensure_future(self.on_subscriber(self.lrrbot.connection, "#%s" % config['channel'], user, eventtime, logo, monthcount)).add_done_callback(utils.check_exception))

	def on_notification(self, conn, event):
		"""Handle notification messages from Twitch, sending the message up to the web"""
		source = irc.client.NickMask(event.source)
		if source.nick != config['notifyuser']:
			return

		eventtime = datetime.datetime.now(pytz.utc)

		respond_to = "#%s" % config["channel"]
		log.info("Notification: %s" % event.arguments[0])

		subscribe_match = self.re_subscription.match(event.arguments[0])
		if subscribe_match and irc.client.is_channel(event.target):
			# Don't highlight the same sub via both the chat and the API
			if subscribe_match.group(1).lower() not in self.last_announced_subs:
				asyncio.ensure_future(self.on_subscriber(conn, event.target, subscribe_match.group(1), eventtime)).add_done_callback(utils.check_exception)
			# Halt message processing
			return "NO MORE"

		subscribe_match = self.re_resubscription.match(event.arguments[0])
		if subscribe_match and irc.client.is_channel(event.target):
			if subscribe_match.group(1).lower() not in self.last_announced_subs:
				asyncio.ensure_future(self.on_subscriber(conn, event.target, subscribe_match.group(1), eventtime, monthcount=int(subscribe_match.group(2)))).add_done_callback(utils.check_exception)
			# Halt message processing
			return "NO MORE"
		asyncio.ensure_future(common.rpc.eventserver.event('twitch-message', {'message': event.arguments[0], 'count': common.storm.increment(self.lrrbot.engine, self.lrrbot.metadata, 'twitch-message')}, eventtime)).add_done_callback(utils.check_exception)

		# Halt message processing
		return "NO MORE"

	def on_usernotice(self, conn, event):
		self.lrrbot.check_message_tags(conn, event)
		if event.tags.get('msg-id') == 'resub':
				if len(event.arguments) > 0:
					message = event.arguments[0]
				else:
					message = None
				monthcount = event.tags.get('msg-param-months')
				if monthcount is not None:
					monthcount = int(monthcount)
				systemmsg = event.tags.get('system-msg')
				if not systemmsg:
					systemmsg = "%s has subscribed for %s months!" % (event.tags.get('display-name') or event.tags['login'], monthcount)
				asyncio.ensure_future(self.on_subscriber(conn, "#" + config['channel'], event.tags.get('display-name') or event.tags['login'], datetime.datetime.now(tz=pytz.utc), monthcount=monthcount, message=message, emotes=event.tags.get('emotes'))).add_done_callback(utils.check_exception)
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

	async def on_subscriber(self, conn, channel, user, eventtime, logo=None, monthcount=None, message=None, emotes=None):
		log.info('New subscriber: %r at %r', user, eventtime)
		if user.lower() in self.last_announced_subs:
			return
		data = {
			'name': user,
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

		self.last_announced_subs.append(user.lower())
		self.last_announced_subs = self.last_announced_subs[-10:]

		users = self.lrrbot.metadata.tables["users"]
		with self.lrrbot.engine.begin() as pg_conn:
			pg_conn.execute(users.update().where(users.c.name == user), is_sub=True)

		if message is not None:
			data['message'] = message
			data['messagehtml'] = await chatlog.format_message(message, emotes, [], cheer=False)

		if monthcount is not None and monthcount > 1:
			event = "twitch-resubscription"
			data['monthcount'] = monthcount
			data['count'] = common.storm.increment(self.lrrbot.engine, self.lrrbot.metadata, event)
		else:
			event = "twitch-subscription"
			data['count'] = common.storm.increment(self.lrrbot.engine, self.lrrbot.metadata, event)
		storm_count = common.storm.get_combined(self.lrrbot.engine, self.lrrbot.metadata)
		conn.privmsg(channel, "lrrSPOT Thanks for subscribing, %s! (Today's storm count: %d)" % (data['name'], storm_count))

		await common.rpc.eventserver.event(event, data, eventtime)
