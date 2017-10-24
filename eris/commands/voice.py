import discord
from common.config import config
from common import http

def register(bot):
	@bot.command("voice (.*?)")
	async def live(bot, command, desc):
		if command.server is None:
			await bot.eris.send_message(command.channel, "Can't create temporary voice channels over private messages.")
			return

		channel_name = config['discord_temp_channel_prefix'] + desc
		headers = {
			"Authorization": "Bot " + config['discord_botsecret'],
		}
		await http.request_coro("https://discordapp.com/api/v6/guilds/%s/channels" % command.server.id, method="POST", asjson=True, headers=headers, data={
			"name": config['discord_temp_channel_prefix'] + desc,
			"type": discord.ChannelType.voice.value,
			"parent_id": config['discord_category_voice'],
		})

		await bot.eris.send_message(command.channel, "Created a temporary voice channel %r." % desc)
