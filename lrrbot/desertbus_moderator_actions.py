"""
This module has basically nothing to do with actual lrrbot functionality...
It's just piggy-backing off it to share its code and steal its event loop.

Because that's easier than making this a separate process.
"""

import asyncio
import datetime
import sqlalchemy

from common import pubsub
from common import utils
from common import time
from common import gdata
from common.config import config
import logging

log = logging.getLogger("desertbus_moderator_actions")

SPREADSHEET = "1KEEcv-hGEIwkHARpK-X6TBWUT3x8HpgG0i4tk16_Ysw"
WATCHCHANNEL = 'desertbus'
WATCHAS = 'mrphlip'  # because lrrbot isn't a mod in the channel
DESERTBUS_START = config["timezone"].localize(datetime.datetime(2016, 11, 12, 10, 0))

class ModeratorActions:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop

		users = self.lrrbot.metadata.tables["users"]
		with self.lrrbot.engine.begin() as conn:
			selfrow = conn.execute(sqlalchemy.select([users.c.id]).where(users.c.name == WATCHAS)).first()
			targetrow = conn.execute(sqlalchemy.select([users.c.id]).where(users.c.name == WATCHCHANNEL)).first()
		if selfrow is not None and targetrow is not None:
			self_channel_id, = selfrow
			target_channel_id, = targetrow
			topic = "chat_moderator_actions.%s.%s" % (self_channel_id, target_channel_id)

			self.lrrbot.pubsub.subscribe([topic], WATCHAS)
			pubsub.signals.signal(topic).connect(self.on_message)

	def on_message(self, sender, message):
		action = message['data']['moderation_action']
		args = message['data']['args']
		mod = message['data']['created_by']

		if action == 'timeout':
			user = args[0]
			action = "Timeout: %s" % time.nice_duration(int(args[1]))
			reason = args[2] if len(args) >= 3 else ''
		elif action == 'ban':
			user = args[0]
			action = "Ban"
			reason = args[1] if len(args) >= 2 else ''
		elif action == 'unban':
			user = args[0]
			action = "Unban"
			reason = ''
		elif action == 'untimeout':
			user = args[0]
			action = "Untimeout"
			reason = ''
		else:
			user = ''
			reason = repr(args)

		now = datetime.datetime.now(config["timezone"])

		data = [
			("Timestamp", now.strftime("%Y-%m-%d %H:%M:%S")),
			("Timestamp (hours bussed)", self.nice_time(now - DESERTBUS_START)),
			("Offender's Username", user),
			("Moderator", mod),
			("Enforcement option/length", action),
			("What was the cause of the enforcement action?", reason),
		]
		asyncio.async(gdata.add_rows_to_spreadsheet(SPREADSHEET, [data]), loop=self.loop).add_done_callback(utils.check_exception)

	def nice_time(self, s):
		if isinstance(s, datetime.timedelta):
			s = s.days * 86400 + s.seconds
		if s < 0:
			return "-" + self.nice_time(-s)
		return "%d:%02d:%02d" % (s // 3600, (s // 60) % 60, s % 60)
