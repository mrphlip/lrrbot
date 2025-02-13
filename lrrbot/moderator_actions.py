import datetime
import sqlalchemy
import dateutil.parser
import json
import logging

from common import eventsub
from common import time
from common import slack
from common import twitch
from common.config import config

log = logging.getLogger("moderator_actions")

class ModeratorActions:
	def __init__(self, lrrbot, loop):
		self.lrrbot = lrrbot
		self.loop = loop

		self.last_ban = None

		self.lrrbot.eventsub[config['username']].connected.connect(self.subscribe)

	async def subscribe(self, session: eventsub.Session):
		broadcaster = await twitch.get_user(name=config['channel'])

		condition = {
			'broadcaster_user_id': broadcaster.id,
			'moderator_user_id': session.user.id,
		}
		await session.listen("channel.moderate", "2", condition, self._on_message)

	async def _on_message(self, event):
		log.info("Got a message: %r", event)

		action = event['action']
		payload = event.get(action)

		text, attachments = getattr(self, f'on_{action}', self._on_unknown_action)(event, payload)

		await slack.send_message(text, attachments=attachments)

	def _on_unknown_action(self, event, payload):
		text = f'{slack.escape(event['moderator_user_name'])} did a {slack.escape(event['action'])}.'
		attachments = [
			{'text': slack.escape(json.dumps(payload))}
		]
		return text, attachments

	def on_ban(self, event, payload):
		attachments, same_user = self.get_chat_log(payload['user_login'])
		text = f'{slack.escape(payload['user_name'])} was{' also' if same_user else ''} banned by {slack.escape(event['moderator_user_name'])}.'
		if reason := payload.get('reason'):
			text += f' Reason: {slack.escape(reason)}'
		return text, attachments

	def on_timeout(self, event, payload):
		attachments, same_user = self.get_chat_log(payload['user_login'])
		expires_at = dateutil.parser.parse(payload['expires_at']).astimezone(config['timezone'])
		now = datetime.datetime.now(tz=config['timezone'])
		text = f'{slack.escape(payload['user_name'])} was{' also' if same_user else ''} timed out until {expires_at:%Y-%m-%d %H:%M:%S} ({slack.escape(time.nice_duration(expires_at - now))} from now) by {slack.escape(event['moderator_user_name'])}.'
		if reason := payload.get('reason'):
			text += f' Reason: {slack.escape(reason)}'
		return text, attachments

	def on_unban(self, event, payload):
		return f'{slack.escape(payload['user_name'])} was unbanned by {slack.escape(event['moderator_user_name'])}.', []

	def on_untimeout(self, event, payload):
		return f'{slack.escape(payload['user_name'])} was untimed-out by {slack.escape(event['moderator_user_name'])}.', []

	def on_clear(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} cleared the chat.', []

	def on_emoteonly(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} has enabled emote-only mode.', []

	def on_emoteonlyoff(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} has disabled emote-only mode.', []

	def on_followers(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} has enabled follower-only mode: minimum age {slack.escape(time.nice_duration(datetime.timedelta(minutes=payload['follow_duration_minutes'])))}.', []

	def on_followersoff(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} has disabled follower-only mode.', []

	def on_uniquechat(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} has enabled unique-chat mode.', []

	def on_uniquechatoff(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} has disabled unique-chat mode.', []

	def on_slow(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} has enabled slow mode: delay {slack.escape(time.nice_duration(payload['wait_time_seconds'], 0))}.', []

	def on_slowoff(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} has disabled slow mode.', []

	def on_subscribers(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} has enabled subscriber-only mode.', []

	def on_subscribersoff(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} has disabled subscriber-only mode.', []

	def on_unraid(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} cancelled a raid to {slack.escape(payload['user_name'])}.', []

	def on_delete(self, event, payload):
		return f'{slack.escape(payload['user_name'])} had a message deleted by {slack.escape(event['moderator_user_name'])}.', [{'text': slack.escape(payload['message_body'])}]

	def on_unvip(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} removed {slack.escape(payload['user_name'])} as a VIP.', []

	def on_vip(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} added {slack.escape(payload['user_name'])} as a VIP.', []

	def on_raid(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} started a raid to {slack.escape(payload['user_name'])}.', []

	def _on_automod_terms_update(self, event, payload, action, category):
		payload = event['automod_terms']
		text = f'{slack.escape(event['moderator_user_name'])} {slack.escape(action)} '
		terms = payload['terms']
		for i, term in enumerate(terms):
			if i != 0:
				text += ', '
				if i == len(terms) - 1:
					text += 'and '
			text += f"'{slack.escape(term)}' "

		if len(terms := payload['terms']) == 1:
			text += f'as a {slack.escape(category)} term'
		else:
			text += f'as {slack.escape(category)} terms'

		if payload['from_automod']:
			text += ' from an Automod action'

		text += '.'

		return text, []

	def on_add_blocked_term(self, event, payload):
		return self._on_automod_terms_update(event, event['automod_terms'], 'added', 'blocked')

	def on_add_permitted_term(self, event, payload):
		return self._on_automod_terms_update(event, event['automod_terms'], 'added', 'permitted')

	def on_remove_blocked_term(self, event, payload):
		return self._on_automod_terms_update(event, event['automod_terms'], 'removed', 'blocked')

	def on_remove_permitted_term(self, event, payload):
		return self._on_automod_terms_update(event, event['automod_terms'], 'removed', 'permitted')

	def on_mod(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} added {slack.escape(payload['user_name'])} as a moderator.', []

	def on_unmod(self, event, payload):
		return f'{slack.escape(event['moderator_user_name'])} removed {slack.escape(payload['user_name'])} as a moderator.', []

	def on_approve_unban_request(self, event, payload):
		payload = event['unban_request']
		text = f"{slack.escape(event['moderator_user_name'])} approved {slack.escape(payload['user_name'])}'s unban request."
		if message := payload.get('message'):
			text += f' Message: {slack.escape(message)}'
		return text, []

	def on_deny_unban_request(self, event, payload):
		payload = event['unban_request']
		text = f"{slack.escape(event['moderator_user_name'])} denied {slack.escape(payload['user_name'])}'s unban request."
		if message := payload.get('message'):
			text += f' Message: {slack.escape(message)}'
		return text, []

	def on_warn(self, event, payload):
		text = f'{slack.escape(payload['user_name'])} was warned by {slack.escape(event['moderator_user_name'])}.'

		if rules := payload.get('chat_rules_cited'):
			if len(rules) == 1:
				text += ' Rule cited: '
			else:
				text += ' Rules cited: '
			for i, rule in enumerate(rules):
				if i != 0:
					text += ', '
					if i == len(rules) - 1:
						text += 'and '
				text += f"'{slack.escape(rule)}' "

		if reason := payload.get('reason'):
			text += f' Reason: {slack.escape(reason)}'

		return text, []

	def on_shared_chat_ban(self, event, payload):
		attachments, same_user = self.get_chat_log(payload['user_login'])
		text = f"{slack.escape(payload['user_name'])} was{' also' if same_user else ''} banned in {slack.escape(event['source_broadcaster_user_name'])}'s chat by {slack.escape(event['moderator_user_name'])}."
		if reason := payload.get('reason'):
			text += f' Reason: {slack.escape(reason)}'
		return text, attachments

	def on_shared_chat_timeout(self, event, payload):
		attachments, same_user = self.get_chat_log(payload['user_login'])
		expires_at = dateutil.parser.parse(payload['expires_at']).astimezone(config['timezone'])
		now = datetime.datetime.now(tz=config['timezone'])
		text = f"{slack.escape(payload['user_name'])} was{' also' if same_user else ''} timed out in {slack.escape(event['source_broadcaster_user_name'])}'s chat until {expires_at:%Y-%m-%d %H:%M:%S} ({slack.escape(time.nice_duration(expires_at - now))} from now) by {slack.escape(event['moderator_user_name'])}."
		if reason := payload.get('reason'):
			text += f' Reason: {slack.escape(reason)}'
		return text, attachments

	def on_shared_chat_unban(self, event, payload):
		return f"{slack.escape(payload['user_name'])} was unbanned in {slack.escape(event['source_broadcaster_user_name'])}'s chat by {slack.escape(event['moderator_user_name'])}.", []

	def on_shared_chat_untimeout(self, event, payload):
		return f"{slack.escape(payload['user_name'])} was untimed-out in {slack.escape(event['source_broadcaster_user_name'])}'s chat by {slack.escape(event['moderator_user_name'])}.", []

	def on_shared_chat_delete(self, event, payload):
		return f"{slack.escape(payload['user_name'])} had a message deleted in {slack.escape(event['source_broadcaster_user_name'])}'s chat by {slack.escape(event['moderator_user_name'])}.", [{'text': slack.escape(payload['message_body'])}]

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

		same_user = (self.last_ban == (user.lower(), logid))
		if same_user:
			attachments = []
		self.last_ban = (user.lower(), logid)

		return attachments, same_user
