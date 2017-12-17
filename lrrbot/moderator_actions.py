import asyncio
import datetime
import sqlalchemy

from common import pubsub
from common import utils
from common import time
from common import slack
from common import twitch
from common.config import config
import logging

log = logging.getLogger("moderator_actions")

class ModeratorActions:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop

		self.last_ban = None

		users = self.lrrbot.metadata.tables["users"]
		with self.lrrbot.engine.begin() as conn:
			selfrow = conn.execute(sqlalchemy.select([users.c.id]).where(users.c.name == config['username'])).first()
			targetrow = conn.execute(sqlalchemy.select([users.c.id]).where(users.c.name == config['channel'])).first()
		if selfrow is not None and targetrow is not None:
			self_channel_id, = selfrow
			target_channel_id, = targetrow
			topic = "chat_moderator_actions.%s.%s" % (self_channel_id, target_channel_id)

			self.lrrbot.pubsub.subscribe([topic])
			pubsub.signals.signal(topic).connect(self.on_message)

	def on_message(self, sender, message):
		log.info("Got message: %r", message['data'])

		action = message['data']['moderation_action']
		args = message['data']['args']
		mod = message['data']['created_by']

		if action in ('timeout', 'ban'):
			user = args[0]
			logid, attachments = self.get_chat_log(user)
			same_user = (self.last_ban == (user.lower(), logid))
			if same_user:
				attachments = []
			self.last_ban = (user.lower(), logid)
		else:
			attachments = []
			self.last_ban = None

		if action == 'timeout':
			user = args[0]
			length = int(args[1])
			reason = args[2] if len(args) >= 3 else None
			text = "%s was%s timed out for %s by %s." % (slack.escape(user), " also" if same_user else "", slack.escape(time.nice_duration(length, 0)), slack.escape(mod))
			if reason is not None:
				text += " Reason: %s" % slack.escape(reason)
		elif action == 'ban':
			user = args[0]
			reason = args[1] if len(args) >= 2 else None
			text = "%s was%s banned by %s." % (slack.escape(user), " also" if same_user else "", slack.escape(mod))
			if reason is not None:
				text += " Reason: %s" % slack.escape(reason)
		elif action == 'unban':
			user = args[0]
			text = "%s was unbanned by %s." % (slack.escape(user), slack.escape(mod))
		elif action == 'untimeout':
			user = args[0]
			text = "%s was untimed-out by %s." % (slack.escape(user), slack.escape(mod))

		elif action in ('twitchbot_rejected', 'automod_rejected'):
			msg_id = message['data']['msg_id']
			user = args[0]
			message = args[1]
			# mod is always "automod", but still...
			text = "%s's message was rejected by %s." % (slack.escape(user), slack.escape(mod))
			attachments.append({
				'text': slack.escape(message)
			})

			# Approve the message because we're unable to turn off Automod.
			asyncio.ensure_future(twitch.twitchbot_approve(msg_id), loop=self.loop).add_done_callback(utils.check_exception)
		elif action in ('approved_twitchbot_message', 'approved_automod_message'):
			user = args[0]
			text = "%s approved %s's message." % (slack.escape(mod), slack.escape(user))
		elif action in ('denied_twitchbot_message', 'denied_automod_message'):
			user = args[0]
			text = "%s denied %s's message." % (slack.escape(mod), slack.escape(user))

		elif action == 'slow':
			duration = int(args[0])
			text = "%s has enabled slow mode: delay %s." % (slack.escape(mod), slack.escape(time.nice_duration(duration, 0)))
		elif action == 'slowoff':
			text = "%s has disabled slow mode." % (slack.escape(mod), )
		elif action == 'followers':
			duration = int(args[0])
			text = "%s has enabled follower-only mode: minimum age %s." % (slack.escape(mod), slack.escape(time.nice_duration(duration, 0)))
		elif action == 'followersoff':
			text = "%s has disabled follower-only mode." % (slack.escape(mod), )

		elif action == 'host':
			target = args[0]
			text = "%s has enabled hosting of %s." % (slack.escape(mod), slack.escape(target))
		elif action == 'unhost':
			text = "%s has disabled hosting." % (slack.escape(mod), )

		elif action == 'mod':
			target = args[0]
			text = "%s has made %s a moderator." % (slack.escape(mod), slack.escape(target))
		elif action == 'clear':
			text = "%s cleared the chat." % (slack.escape(mod), )
		elif action == 'recent_cheer_dismissal':
			cheerer = args[0]
			text = "%s has cleared %s's recent-cheer notice." % (slack.escape(mod), slack.escape(cheerer))

		else:
			text = "%s did a %s: %s" % (slack.escape(mod), slack.escape(action), slack.escape(repr(args)))

		asyncio.ensure_future(slack.send_message(text, attachments=attachments), loop=self.loop).add_done_callback(utils.check_exception)

	def get_chat_log(self, user):
		attachments = []
		now = datetime.datetime.now(config["timezone"])

		log = self.lrrbot.metadata.tables["log"]
		with self.lrrbot.engine.begin() as conn:
			rows = conn.execute(sqlalchemy.select([log.c.id, log.c.time, log.c.message])
				.where(log.c.source == user.lower())
				.where(log.c.time > now - datetime.timedelta(days=1))
				.limit(3)
				.order_by(log.c.time.desc())).fetchall()

		logid = -1
		for logid, timestamp, message in rows[::-1]:
			timestamp = timestamp.astimezone(config["timezone"])
			attachments.append({
				'text': slack.escape("%s (%s ago): %s" % (timestamp.strftime("%H:%M"), time.nice_duration(now - timestamp), message))
			})

		return logid, attachments
