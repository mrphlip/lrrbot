"""
This module has basically nothing to do with actual lrrbot functionality...
It's just piggy-backing off it to share its code and steal its event loop.

Because that's easier than making this a separate process.
"""

import asyncio
import datetime
import dateutil.parser

from common import eventsub
from common import twitch
from common import utils
from common import time as ctime
from common import gdata
from common.config import config
import logging
import time
import irc.client

log = logging.getLogger("desertbus_moderator_actions")

SPREADSHEET = "1KEEcv-hGEIwkHARpK-X6TBWUT3x8HpgG0i4tk16_Ysw"
WATCHCHANNEL = 'desertbus'
WATCHAS = 'mrphlip'  # because lrrbot isn't a mod in the channel
DESERTBUS_START = config["timezone"].localize(datetime.datetime(2025, 5, 23, 16, 0))

class ModeratorActions:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop

		self.last_chat = {}

		if config['log_desertbus_moderator_actions']:
			self.lrrbot.reactor.add_global_handler("pubmsg", self.record_db_chat, -2)
			self.lrrbot.reactor.add_global_handler("all_events", self.drop_db_events, -1)
			self.lrrbot.reactor.add_global_handler("welcome", self.on_connect, 2)
			self.lrrbot.reactor.scheduler.execute_every(60, self.clear_chat)

			self.lrrbot.eventsub[WATCHAS].connected.connect(self.subscribe)

	async def subscribe(self, session: eventsub.Session):
		broadcaster = await twitch.get_user(name=WATCHCHANNEL)

		condition = {
			'broadcaster_user_id': broadcaster.id,
			'moderator_user_id': session.user.id,
		}
		await session.listen("channel.moderate", "2", condition, self.on_message)

	@utils.swallow_errors
	def on_message(self, message):
		log.info("Got message: %r", message)

		action = message['action']
		args = message[action]
		mod = message['moderator_user_name']

		if action == 'timeout':
			user = args['user_name']
			expires_at = dateutil.parser.parse(args['expires_at']).astimezone(config['timezone'])
			now = datetime.datetime.now(tz=config['timezone'])
			action = "Timeout: %s" % ctime.nice_duration(expires_at - now)
			reason = args['reason'] or ''
			last = self.last_chat.get(args['user_login'].lower(), [''])[0]
		elif action == 'ban':
			user = args['user_name']
			action = "Ban"
			reason = args['reason'] or ''
			last = self.last_chat.get(args['user_login'].lower(), [''])[0]
		elif action == 'unban':
			user = args['user_name']
			action = "Unban"
			reason = ''
			last = ''
		elif action == 'untimeout':
			user = args['user_name']
			action = "Untimeout"
			reason = ''
			last = ''
		elif action == 'delete':
			user = args['user_name']
			action = "Delete message"
			reason = ''
			last = args['message_body']
		else:
			user = ''
			reason = repr(args)
			last = ''

		now = datetime.datetime.now(config["timezone"])

		data = [
			now.strftime("%Y-%m-%d %H:%M:%S"),  # Timestamp
			self.nice_time(now - DESERTBUS_START),  # Timestamp (hours bussed)
			user,  # Offender's Username
			mod,  # Moderator
			action,  # Enforcement option/length
			reason,  # What was the cause of the enforcement action?
			last,  # Last Line
		]
		log.debug("Add row: %r", data)
		asyncio.ensure_future(gdata.add_rows_to_spreadsheet(SPREADSHEET, [data]), loop=self.loop).add_done_callback(utils.check_exception)

	def nice_time(self, s):
		if isinstance(s, datetime.timedelta):
			s = s.days * 86400 + s.seconds
		if s < 0:
			return "-" + self.nice_time(-s)
		return "%d:%02d:%02d" % (s // 3600, (s // 60) % 60, s % 60)

	@utils.swallow_errors
	def record_db_chat(self, conn, event):
		if event.target == "#" + WATCHCHANNEL:
			source = irc.client.NickMask(event.source)
			self.last_chat[source.nick.lower()] = (event.arguments[0], time.time())
			return "NO MORE"

	@utils.swallow_errors
	def drop_db_events(self, conn, event):
		if event.target == "#" + WATCHCHANNEL and event.type != "action":
			return "NO MORE"

	@utils.swallow_errors
	def clear_chat(self):
		cutoff = time.time() - 10*60
		to_remove = [k for k, v in self.last_chat.items() if v[1] < cutoff]
		for i in to_remove:
			del self.last_chat[i]

	def on_connect(self, conn, event):
		conn.join("#" + WATCHCHANNEL)
