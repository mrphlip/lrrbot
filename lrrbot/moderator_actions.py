import asyncio
import datetime
import sqlalchemy

from common import pubsub
from common import utils
from common import time
from common import slack
from common.config import config

class ModeratorActions:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop

		users = self.lrrbot.metadata.tables["users"]
		with self.lrrbot.engine.begin() as conn:
			channel_id, = conn.execute(sqlalchemy.select([users.c.id]).where(users.c.name == config['channel'])).first()

		self.lrrbot.pubsub.subscribe(["chat_moderator_actions.%s" % channel_id], config['channel'])

		pubsub.signals.signal("chat_moderator_actions.%s" % channel_id) .connect(self.on_message)

	def on_message(self, sender, message):
		action = message['data']['moderation_action']
		args = message['data']['args']
		mod = message['data']['created_by']

		if action == 'timeout':
			user = args[0]
			length = int(args[1])
			reason = args[2] if len(args) >= 3 else None
			include_chat_log = True

			text = "%s was timed out for %s by %s." % (slack.escape(user), slack.escape(time.nice_duration(length, 0)), slack.escape(mod))
			if reason is not None:
				text += " Reason: %s" % slack.escape(reason)
		elif action == 'ban':
			user = args[0]
			reason = args[1] if len(args) >= 2 else None
			include_chat_log = True

			text = "%s was banned by %s." % (slack.escape(user), slack.escape(mod))
			if reason is not None:
				text += " Reason: %s" % slack.escape(reason)
		elif action == 'unban':
			user = args[0]
			include_chat_log = False

			text = "%s was unbanned by %s." % (slack.escape(user), slack.escape(mod))
		
		attachments = []
		if include_chat_log:
			now = datetime.datetime.now(config["timezone"])

			log = self.lrrbot.metadata.tables["log"]
			with self.lrrbot.engine.begin() as conn:
				rows = conn.execute(sqlalchemy.select([log.c.time, log.c.message])
					.where(log.c.source == user.lower())
					.where(log.c.time > now - datetime.timedelta(days=1))
					.limit(3)
					.order_by(log.c.time.desc())).fetchall()

			for timestamp, message in rows[::-1]:
				timestamp = timestamp.astimezone(config["timezone"])
				attachments.append({
					'text': slack.escape("%s (%s ago): %s" % (timestamp.strftime("%H:%M"), time.nice_duration(now - timestamp), message))
				})

		asyncio.async(slack.send_message(text, attachments=attachments), loop=self.loop).add_done_callback(utils.check_exception)
