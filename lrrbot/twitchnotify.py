import time
import logging
import datetime
import asyncio
import irc.client
import pytz
from common import utils
from common.config import config
from common import twitch
import common.rpc
import common.storm
from common.account_providers import ACCOUNT_PROVIDER_TWITCH

log = logging.getLogger('twitchnotify')

DEBOUNCE_INTERVAL = 600
MULTI_GIFT_CLEANUP_INTERVAL = 120

class TwitchNotify:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop
		self.last_subs = None
		self.recent_announced_subs = {}
		self.multi_gifts = {}

		self.lrrbot.reactor.add_global_handler('usernotice', self.on_usernotice, 90)

		self.cleanup_loop = asyncio.ensure_future(self.cleanup(), loop=loop)

	def stop_task(self):
		self.cleanup_loop.cancel()
		return self.cleanup_loop

	def on_usernotice(self, conn, event):
		self.lrrbot.check_message_tags(conn, event)
		if event.tags.get('msg-id') in ('sub', 'resub', 'subgift'):
			if len(event.arguments) > 0:
				message = event.arguments[0]
			else:
				message = None

			monthcount = event.tags.get('msg-param-cumulative-months')
			if monthcount is not None:
				monthcount = int(monthcount)
			else:
				monthcount = 1

			streak = event.tags.get('msg-param-streak-months')
			if streak:
				streak = int(streak)
			else:
				streak = None

			name = event.tags['login']
			display_name = event.tags.get('display-name') or name

			if event.tags.get('msg-param-recipient-user-name'):
				benefactor_name = name
				benefactor_display_name = display_name
				name = event.tags.get('msg-param-recipient-user-name')
				display_name = event.tags.get('msg-param-recipient-display-name') or name
			else:
				benefactor_name = benefactor_display_name = None

			systemmsg = event.tags.get('system-msg')
			if not systemmsg:
				if monthcount > 1:
					systemmsg = "%s has subscribed for %s months!" % (display_name, monthcount)
				else:
					systemmsg = "%s just subscribed!" % (display_name, )

			asyncio.ensure_future(self.on_subscriber(
				conn,
				"#" + config['channel'],
				name,
				display_name,
				datetime.datetime.now(tz=pytz.utc),
				monthcount=monthcount,
				message=message,
				emotes=event.tags.get('emotes'),
				benefactor_login=benefactor_name,
				benefactor=benefactor_display_name,
				streak=streak,
				tier=event.tags.get('msg-param-sub-plan'),
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
		elif event.tags.get('msg-id') == 'submysterygift':
			benefactor_name = event.tags['login']
			benefactor_display_name = event.tags.get('display-name') or benefactor_name
			subcount = int(event.tags.get('msg-param-mass-gift-count', 1))

			systemmsg = event.tags.get('system-msg')
			if not systemmsg:
				systemmsg = "%s is gifting %d sub%s!" % (benefactor_display_name, subcount, '' if subcount == 1 else 's')

			asyncio.ensure_future(self.on_multi_gift_start(
				benefactor_name,
				benefactor_display_name,
				datetime.datetime.now(tz=pytz.utc),
				subcount=subcount,
			)).add_done_callback(utils.check_exception)

			self.lrrbot.log_chat(conn, irc.client.Event(
				"pubmsg",
				"%s!%s@tmi.twitch.tv" % (config['notifyuser'], config['notifyuser']),
				event.target,
				[systemmsg],
				{},
			))
			return "NO MORE"
		elif event.tags.get('msg-id') == 'raid':
			raider_name = event.tags['msg-param-login']
			raider_display_name = event.tags.get('msg-param-displayName') or raider_name
			count = int(event.tags.get('msg-param-viewerCount', 1))
			logo = event.tags.get('msg-param-profileImageURL')

			systemmsg = event.tags.get('system-msg')
			if not systemmsg:
				systemmsg = "%d raider%s from %s have joined!" % (count, '' if count == 1 else 's', raider_display_name)

			asyncio.ensure_future(self.on_raid(
				raider_name,
				raider_display_name,
				datetime.datetime.now(tz=pytz.utc),
				count=count,
				logo=logo,
			)).add_done_callback(utils.check_exception)

			self.lrrbot.log_chat(conn, irc.client.Event(
				"pubmsg",
				"%s!%s@tmi.twitch.tv" % (config['notifyuser'], config['notifyuser']),
				event.target,
				[systemmsg],
				{},
			))
			return "NO MORE"
		else:
			logging.info("Unrecognised USERNOTICE: %s\n%r %r", event.tags.get('msg-id'), event.tags, event.arguments)

			messages = []
			if event.tags.get('system-msg'):
				messages.append(event.tags['system-msg'])
			if len(event.arguments) > 0:
				messages.append(event.arguments[0])

			for msg in messages:
				self.lrrbot.log_chat(conn, irc.client.Event(
					"pubmsg",
					"%s!%s@tmi.twitch.tv" % (config['notifyuser'], config['notifyuser']),
					event.target,
					[msg],
					{},
				))

			if messages:
				asyncio.ensure_future(self.on_unknown_message(
					conn,
					datetime.datetime.now(tz=pytz.utc),
					message="\u2014".join(messages),
				)).add_done_callback(utils.check_exception)

	async def on_subscriber(self, conn, channel, login, user, eventtime, logo=None, monthcount=None, message=None, emotes=None, benefactor_login=None, benefactor=None, streak=None, tier=None):
		log.info('New subscriber: %r at %r', user, eventtime)

		now = time.time()
		for k in [k for k, v in self.recent_announced_subs.items() if v < now - DEBOUNCE_INTERVAL]:
			del self.recent_announced_subs[k]
		if login in self.recent_announced_subs:
			log.info('Debouncing subscriber %r', user)
			return
		self.recent_announced_subs[login] = now

		data = {
			'name': user,
			'benefactor': benefactor,
			'streak': streak,
		}
		if logo is None:
			try:
				channel_info = await twitch.get_info_uncached(login)
			except utils.PASSTHROUGH_EXCEPTIONS:
				raise
			except Exception:
				pass
			else:
				if channel_info.get('profile_image_url'):
					data['avatar'] = channel_info['profile_image_url']
		else:
			data['avatar'] = logo

		accounts = self.lrrbot.metadata.tables["accounts"]
		with self.lrrbot.engine.connect() as pg_conn:
			pg_conn.execute(accounts.update().where(accounts.c.provider == ACCOUNT_PROVIDER_TWITCH).where(accounts.c.name == login), {"is_sub": True})
			pg_conn.commit()

		if message is not None:
			data['message'] = message
			data['messagehtml'] = await self.lrrbot.chatlog.format_message(message, emotes, [], cheer=False)

		if monthcount > 1:
			event = "twitch-resubscription"
			data['monthcount'] = monthcount
			data['count'] = common.storm.increment(self.lrrbot.engine, self.lrrbot.metadata, event)
		else:
			event = "twitch-subscription"
			data['count'] = common.storm.increment(self.lrrbot.engine, self.lrrbot.metadata, event)

		if tier is not None:
			data['tier'] = tier

		if benefactor_login in self.multi_gifts:
			multi_gift = self.multi_gifts[benefactor_login]
			data['ismulti'] = True
			multi_gift['subscribers'].append(data)
			multi_gift['remaining'] -= 1
			log.debug("Remaining gifts for %s: %d", benefactor, multi_gift['remaining'])
			if multi_gift['remaining'] <= 0:
				await self.on_multi_gift_end(conn, channel, multi_gift)
		else:
			data['ismulti'] = False
			storm_count = common.storm.get_combined(self.lrrbot.engine, self.lrrbot.metadata)
			conn.privmsg(channel, "lrrSPOT Thanks for subscribing, %s! (Today's storm count: %d)" % (data['name'], storm_count))

		await common.rpc.eventserver.event(event, data, eventtime)

	async def on_multi_gift_start(self, login, user, eventtime, subcount, logo=None):
		data = {
			'login': login,
			'name': user,
			'subcount': subcount,
			'remaining': subcount,
			'subscribers': [],
			'eventtime': eventtime,
			'avatar': None,
		}
		self.multi_gifts[login] = data

		if logo is None:
			try:
				channel_info = await twitch.get_info_uncached(login)
			except utils.PASSTHROUGH_EXCEPTIONS:
				raise
			except Exception:
				pass
			else:
				if channel_info.get('profile_image_url'):
					data['avatar'] = channel_info['profile_image_url']
		else:
			data['avatar'] = logo

	async def on_multi_gift_end(self, conn, channel, multi_gift):
		event = "twitch-subscription-mysterygift"
		eventtime = multi_gift.pop('eventtime')
		del multi_gift['remaining']

		del self.multi_gifts[multi_gift['login']]

		names = [i['name'] for i in multi_gift['subscribers']]
		if len(names) == 0:
			# fallback just in case, I guess?
			names = "all %d recipients" % multi_gift['subcount']
		elif len(names) == 1:
			names = names[0]
		elif len(names) == 2:
			names = " and ".join(names)
		else:
			names[-1] = "and " + names[-1]
			names = ", ".join(names)

		storm_count = common.storm.get_combined(self.lrrbot.engine, self.lrrbot.metadata)

		welcomemsg = "lrrSPOT Thanks for the gift%s, %s! Welcome to %s! (Today's storm count: %d)" % (
			'' if multi_gift['subcount'] == 1 else 's',
			multi_gift['name'],
			names,
			storm_count)
		if not utils.check_length(welcomemsg):
			names = "all %d recipients" % multi_gift['subcount']
			welcomemsg = "lrrSPOT Thanks for the gift%s, %s! Welcome to %s! (Today's storm count: %d)" % (
				'' if multi_gift['subcount'] == 1 else 's',
				multi_gift['name'],
				names,
				storm_count)
		conn.privmsg(channel, welcomemsg)
		await common.rpc.eventserver.event(event, multi_gift, eventtime)

	async def cleanup(self):
		# Sanity cleanup so that if a "gifted 5 subs" message is only followed up
		# by 4 sub messages, or whatever, then we still eventually send the notif
		while True:
			cutoff = datetime.datetime.now(tz=pytz.utc) - datetime.timedelta(seconds=MULTI_GIFT_CLEANUP_INTERVAL)
			to_clean = [k for k, v in self.multi_gifts.items() if v['eventtime'] <= cutoff]
			for k in to_clean:
				await self.on_multi_gift_end(
					self.lrrbot.connection,
					"#" + config['channel'],
					self.multi_gifts[k]
				)

			await asyncio.sleep(MULTI_GIFT_CLEANUP_INTERVAL)

	async def on_raid(self, login, user, eventtime, count, logo=None):
		event = "twitch-raid"
		data = {
			'login': login,
			'name': user,
			'count': count,
		}

		if logo is None:
			try:
				channel_info = await twitch.get_info_uncached(login)
			except utils.PASSTHROUGH_EXCEPTIONS:
				raise
			except Exception:
				pass
			else:
				if channel_info.get('profile_image_url'):
					data['avatar'] = channel_info['profile_image_url']
		else:
			data['avatar'] = logo

		await common.rpc.eventserver.event(event, data, eventtime)

		common.storm.increment(self.lrrbot.engine, self.lrrbot.metadata, event)

	async def on_unknown_message(self, conn, eventtime, message):
		event = "twitch-message"
		data = {
			'message': message,
		}
		await common.rpc.eventserver.event(event, data, eventtime)
