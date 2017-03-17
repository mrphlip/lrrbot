import sqlalchemy

from common.config import config
from common import twitch

def register(bot):
	@bot.command("live")
	async def live(bot, command):
		users = bot.metadata.tables["users"]
		with bot.engine.begin() as pg_conn:
			token, = pg_conn.execute(sqlalchemy.select([users.c.twitch_oauth])
				.where(users.c.name == config["username"])).first()

		streams = await twitch.get_streams_followed(token)
		if len(streams) == 0:
			return conn.privmsg(respond_to, "No fanstreamers currently live.")

		streams.sort(key=lambda e: e["channel"]["display_name"])

		tag = "Currently live fanstreamers: "

		message = tag + ", ".join([
			"%s (<%s>)%s%s" % (
				data["channel"]["display_name"],
				data["channel"]["url"],
				" is playing %s" % data["game"] if data.get("game") is not None else "",
				" (%s)" % data["channel"]["status"] if data["channel"].get("status") not in [None, ""] else ""
			) for data in streams
		])

		await bot.eris.send_message(command.channel, message)
