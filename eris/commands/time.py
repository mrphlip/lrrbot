import datetime
import discord
from common.config import config

def register(bot):
	@bot.command("time")
	async def time(bot, command):
		now = datetime.datetime.now(config["timezone"])
		await bot.eris.send_message(command.channel, "Current moonbase time: %s" % now.strftime("%l:%M %p"))

	@bot.command("time 24")
	async def time_24(bot, command):
		now = datetime.datetime.now(config["timezone"])
		await bot.eris.send_message(command.channel, "Current moonbase time: %s" % now.strftime("%H:%M"))
