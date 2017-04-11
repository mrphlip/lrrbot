import discord
from common.config import config

def register(bot):
	@bot.command("voice (.*?)")
	async def live(bot, command, desc):
		if command.server is None:
			await bot.eris.send_message(command.channel, "Can't create temporary voice channels over private messages.")
			return
		channel = await bot.eris.create_channel(command.server, config['discord_temp_channel_prefix'] + desc, type=discord.ChannelType.voice)
		await bot.eris.send_message(command.channel, "Created a temporary voice channel %r." % desc)
