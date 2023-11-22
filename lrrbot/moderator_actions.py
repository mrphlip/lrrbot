import asyncio
import datetime
import sqlalchemy
import dateutil.parser
import json

from common import pubsub
from common import utils
from common import time
from common import slack
from common.config import config
import logging

log = logging.getLogger("moderator_actions")

class ModeratorActions:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop

		self.last_ban = None

		users = self.lrrbot.metadata.tables["users"]
		with self.lrrbot.engine.connect() as conn:
			selfrow = conn.execute(sqlalchemy.select(users.c.id).where(users.c.name == config['username'])).first()
			targetrow = conn.execute(sqlalchemy.select(users.c.id).where(users.c.name == config['channel'])).first()
		if selfrow is not None and targetrow is not None:
			self_channel_id, = selfrow
			target_channel_id, = targetrow
			topic = "chat_moderator_actions.%s.%s" % (self_channel_id, target_channel_id)

			self.lrrbot.pubsub.subscribe([topic])
			pubsub.signals.signal(topic).connect(self.on_message)

	def on_message(self, sender, message):
		log.info("Got a %s message: %r", message['type'], message['data'])

		if message['type'] == 'moderation_action':
			text, attachments = self.on_moderation_action(message)
		elif message['type'] == 'channel_terms_action':
			text, attachments = self.on_channel_terms_action(message)
		elif message['type'] in ('moderator_added', 'moderator_removed', 'vip_added'):
			text, attachments = self.on_role_action(message)
		elif message['type'] in ('approve_unban_request', 'deny_unban_request'):
			text, attachments = self.on_unban_request_action(message)
		else:
			user = message['data'].get('created_by') or message['data'].get('created_by_login') or 'someone'
			text = f"{slack.escape(user)} did a {slack.escape(message['type'])}."
			attachments = [
				{"text": slack.escape(json.dumps(message['data']))}
			]

		asyncio.ensure_future(slack.send_message(text, attachments=attachments), loop=self.loop).add_done_callback(utils.check_exception)

	def on_moderation_action(self, message):
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
			length = time.nice_duration(int(args[1]), 0) if args[1] != '' else '???'
			reason = args[2] if len(args) >= 3 else None
			text = "%s was%s timed out for %s by %s." % (slack.escape(user), " also" if same_user else "", slack.escape(length), slack.escape(mod))
			if reason:
				text += " Reason: %s" % slack.escape(reason)
		elif action == 'ban':
			user = args[0]
			reason = args[1] if len(args) >= 2 else None
			text = "%s was%s banned by %s." % (slack.escape(user), " also" if same_user else "", slack.escape(mod))
			if reason:
				text += " Reason: %s" % slack.escape(reason)
		elif action == 'unban':
			user = args[0]
			text = "%s was unbanned by %s." % (slack.escape(user), slack.escape(mod))
		elif action == 'untimeout':
			user = args[0]
			text = "%s was untimed-out by %s." % (slack.escape(user), slack.escape(mod))
		elif action == 'delete':
			user = args[0]
			message = args[1]
			text = "%s had a message deleted by %s." % (slack.escape(user), slack.escape(mod))
			attachments.append({
				'text': slack.escape(message)
			})

		elif action in ('twitchbot_rejected', 'automod_rejected'):
			msg_id = message['data']['msg_id']
			user = args[0]
			message = args[1]
			if not mod:
				mod = "the strange voices that lie beneath"
			text = "%s's message was rejected by %s." % (slack.escape(user), slack.escape(mod))
			attachments.append({
				'text': slack.escape(message)
			})
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
		elif action == 'emoteonly':
			text = "%s has enabled emote-only mode." % (slack.escape(mod), )
		elif action == 'emoteonlyoff':
			text = "%s has disabled emote-only mode." % (slack.escape(mod), )
		elif action == 'subscribers':
			text = "%s has enabled subscriber-only mode." % (slack.escape(mod), )
		elif action == 'subscribersoff':
			text = "%s has disabled subscriber-only mode." % (slack.escape(mod), )

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
			if args:
				text = "%s did a %s: %s" % (slack.escape(mod), slack.escape(action), slack.escape(repr(args)))
			else:
				text = "%s did a %s." % (slack.escape(mod), slack.escape(action))

		return text, attachments

	def on_channel_terms_action(self, message):
		user = message['data']['requester_login']
		term = message['data']['text']

		if message['data']['type'] == 'add_permitted_term':
			text = f"{slack.escape(user)} added '{slack.escape(term)}' as a permitted term"
		elif message['data']['type'] == 'delete_permitted_term':
			text = f"{slack.escape(user)} removed '{slack.escape(term)}' as a permitted term"
		elif message['data']['type'] == 'add_blocked_term':
			text = f"{slack.escape(user)} added {slack.escape(term)}' as a blocked term"
		elif message['data']['type'] == 'delete_blocked_term':
			text = f"{slack.escape(user)} removed '{slack.escape(term)}' as a blocked term"
		else:
			text = f"{slack.escape(user)} did a {slack.escape(message['data']['type'])} to '{slack.escape(term)}'"

		if expires_at := message['data'].get('expires_at'):
			expires_at = dateutil.parser.parse(expires_at).astimezone(config['timezone'])
			now = datetime.datetime.now(tz=config['timezone'])
			text += f" until {expires_at:%Y-%m-%d %H:%M:%S} ({slack.escape(time.nice_duration(expires_at - now))} from now)."
		else:
			text += "."

		return text, []

	def on_role_action(self, message):
		user = message['data']['created_by']
		target = message['data']['target_user_login']

		if message['type'] == 'moderator_added':
			text = f"{slack.escape(user)} added {slack.escape(target)} as a moderator."
		elif message['type'] == 'moderator_removed':
			text = f"{slack.escape(user)} removed {slack.escape(target)} as a moderator."
		elif message['type'] == 'vip_added':
			text = f"{slack.escape(user)} added {slack.escape(target)} as a VIP."
		else:
			text = f"{slack.escape(user)} did a {slack.escape(message['type'])} to {slack.escape(target)}."

		return text, []

	def on_unban_request_action(self, message):
		mod = message['data']['created_by_login']
		user = message['data']['target_user_login']

		if message['type'] == 'approve_unban_request':
			text = f"{slack.escape(mod)} approved {slack.escape(user)}'s unban request."
		elif message['type'] == 'deny_unban_request':
			text = f"{slack.escape(mod)} denied {slack.escape(user)}'s unban request."
		else:
			text = f"{slack.escape(mod)} did a {slack.escape(message['type'])} to {slack.escape(user)}'s unban request."

		if moderator_message := message['data'].get('moderator_message'):
			text += f" Message: {slack.escape(moderator_message)}"

		return text, []

	def get_chat_log(self, user):
		attachments = []
		now = datetime.datetime.now(config["timezone"])

		log = self.lrrbot.metadata.tables["log"]
		with self.lrrbot.engine.connect() as conn:
			rows = conn.execute(sqlalchemy.select(log.c.id, log.c.time, log.c.message)
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
