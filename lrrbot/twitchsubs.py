import time
import re
import logging
import datetime
import dateutil
import asyncio
import sqlalchemy
import irc.client
from common import utils
from common.config import config
from common import twitch
from common import http
from lrrbot import storage

log = logging.getLogger('twitchsubs')

class TwitchSubs:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop
		self.last_subs = None
		self.last_announced_subs = []

		# Precompile regular expressions
		self.re_subscription = re.compile(r"^(.*) just subscribed!$", re.IGNORECASE)
		self.re_resubscription = re.compile(r"^(.*) subscribed for (\d+) months? in a row!$", re.IGNORECASE)

		self.lrrbot.reactor.add_global_handler('privmsg', self.on_notification, 90)
		self.lrrbot.reactor.add_global_handler('pubmsg', self.on_notification, 90)

	@asyncio.coroutine
	def watch_subs(self):
		try:
			while True:
				yield from self.do_check()
				yield from asyncio.sleep(config['checksubstime'])
		except asyncio.CancelledError:
			pass

	@utils.swallow_errors
	@asyncio.coroutine
	def do_check(self):
		users = self.lrrbot.metadata.tables["users"]
		with self.lrrbot.engine.begin() as conn:
			token, = conn.execute(sqlalchemy.select([users.c.twitch_oauth])
				.where(users.c.name == config['channel'])).first()

		sublist = None
		if token is not None:
			sublist = yield from twitch.get_subscribers(config['channel'], token)
		if not sublist:
			log.info("Failed to get subscriber list from Twitch")
			self.last_subs = None
			return

		# If this is the first time we've gotten the sub list then don't notify for all of them
		# as all of them will appear "new" even if we saw them on a previous run
		# Just add them to the "seen" list
		if self.last_subs is not None:
			for user, logo, eventtime in sublist:
				if user.lower() not in self.last_subs:
					log.info("Found new subscriber via Twitch API: %s" % user)
					eventtime = dateutil.parser.parse(eventtime).timestamp()
					if user.lower() not in self.last_announced_subs:
						self.on_subscriber(self.lrrbot.connection, "#%s" % config['channel'], user, eventtime, logo)
		else:
			log.debug("Got initial subscriber list from Twitch")

		self.last_subs = [i[0].lower() for i in sublist]

	def on_notification(self, conn, event):
		"""Handle notification messages from Twitch, sending the message up to the web"""
		source = irc.client.NickMask(event.source)
		if source.nick != config['notifyuser']:
			return

		respond_to = "#%s" % config["channel"]
		log.info("Notification: %s" % event.arguments[0])
		subscribe_match = self.re_subscription.match(event.arguments[0])
		if subscribe_match and irc.client.is_channel(event.target):
			# Don't highlight the same sub via both the chat and the API
			if subscribe_match.group(1).lower() not in self.last_announced_subs:
				self.on_subscriber(conn, event.target, subscribe_match.group(1), time.time())
			# Halt message processing
			return "NO MORE"

		subscribe_match = self.re_resubscription.match(event.arguments[0])
		if subscribe_match and irc.client.is_channel(event.target):
			if subscribe_match.group(1).lower() not in self.last_announced_subs:
				self.on_subscriber(conn, event.target, subscribe_match.group(1), time.time(), monthcount=int(subscribe_match.group(2)))
			# Halt message processing
			return "NO MORE"

		notifyparams = {
			'apipass': config['apipass'],
			'message': event.arguments[0],
			'eventtime': time.time(),
		}
		if irc.client.is_channel(event.target):
			notifyparams['channel'] = event.target[1:]
		http.api_request('notifications/newmessage', notifyparams, 'POST')
		# Halt message processing
		return "NO MORE"

	def on_subscriber(self, conn, channel, user, eventtime, logo=None, monthcount=None):
		notifyparams = {
			'apipass': config['apipass'],
			'message': "%s just subscribed!" % user,
			'eventtime': eventtime,
			'subuser': user,
			'channel': channel,
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
					notifyparams['avatar'] = channel_info['logo']
		else:
			notifyparams['avatar'] = logo

		if monthcount is not None:
			notifyparams['monthcount'] = monthcount

		# have to get this in a roundabout way as datetime.date.today doesn't take a timezone argument
		today = datetime.datetime.now(config['timezone']).date().toordinal()
		if today != storage.data.get("storm",{}).get("date"):
			storage.data["storm"] = {
				"date": today,
				"count": 0,
			}
		storage.data["storm"]["count"] += 1
		self.last_announced_subs.append(user.lower())
		self.last_announced_subs = self.last_announced_subs[-10:]
		storage.save()
		conn.privmsg(channel, "lrrSPOT Thanks for subscribing, %s! (Today's storm count: %d)" % (notifyparams['subuser'], storage.data["storm"]["count"]))
		http.api_request('notifications/newmessage', notifyparams, 'POST')

		users = self.lrrbot.metadata.tables["users"]
		with self.lrrbot.engine.begin() as conn:
			conn.execute(users.update().where(users.c.name == user), is_sub=True)
