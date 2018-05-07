import csv
import datetime
import discord
import logging

from common.config import config

log = logging.getLogger("eris.voice_channel_tracker")

class VoiceChannelTracker:
	def __init__(self, eris, signals):
		self.eris = eris
		self.signals = signals

		signals.signal('ready').connect(self.enumerate_voice_channels)
		
		signals.signal('channel_create').connect(self.channel_create)
		signals.signal('channel_update').connect(self.channel_update)
		signals.signal('channel_delete').connect(self.channel_delete)

		signals.signal('voice_state_update').connect(self.voice_state_update)

		self.file = open("voice_channels.csv", "a")
		self.csv = csv.DictWriter(self.file, ["timestamp", "id", "channel name", "action", "user"])
		if self.file.tell() == 0:
			self.csv.writeheader()
			self.file.flush()

	def enumerate_voice_channels(self, eris):
		for channel in eris.get_server(config['discord_serverid']).channels:
			if channel.type == discord.ChannelType.voice:
				self.csv.writerow({
					"timestamp": datetime.datetime.now(config['timezone']).isoformat(),
					"id": channel.id,
					"channel name": channel.name,
					"action": "ENUMERATE",
					"user": None,
				})
		self.file.flush()

	def channel_create(self, eris, channel):
		if channel.type == discord.ChannelType.voice:
			self.csv.writerow({
				"timestamp": datetime.datetime.now(config['timezone']).isoformat(),
				"id": channel.id,
				"channel name": channel.name,
				"action": "CREATE",
				"user": None,
			})
			self.file.flush()

	def channel_update(self, eris, before, after):
		if after.type == discord.ChannelType.voice:
			self.csv.writerow({
				"timestamp": datetime.datetime.now(config['timezone']).isoformat(),
				"id": after.id,
				"channel name": after.name,
				"action": "UPDATE",
				"user": None,
			})
			self.file.flush()

	def channel_delete(self, eris, channel):
		if channel.type == discord.ChannelType.voice:
			self.csv.writerow({
				"timestamp": datetime.datetime.now(config['timezone']).isoformat(),
				"id": channel.id,
				"channel name": channel.name,
				"action": "DELETE",
				"user": None,
			})
			self.file.flush()

	def voice_state_update(self, eris, before, after):
		before_channel = before.voice.voice_channel
		after_channel = after.voice.voice_channel

		if before_channel is None and after_channel is None:
			log.error("voice_state_update but both channels are None")
			return
		elif before_channel is None and after_channel is not None:
			channel = after_channel
			action = "JOIN"
		elif before_channel is not None and after_channel is None:
			channel = before_channel
			action = "LEAVE"
		elif before_channel is not None and after_channel is not None:
			channel = after_channel
			action = "MOVE"
		else:
			log.error("Divide By Cucumber Error. Please Reinstall Universe And Reboot")
			return
		
		self.csv.writerow({
			"timestamp": datetime.datetime.now(config['timezone']).isoformat(),
			"id": channel.id,
			"channel name": channel.name,
			"action": action,
			"user": "%s#%s" % (after.name, after.discriminator),
		})
		self.file.flush()

