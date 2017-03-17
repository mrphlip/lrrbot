import sqlalchemy

from common.config import config
from common import twitch

def markdown_escape(text):
	def escape_char(c):
		if c == '_' or c == '*' or c == '<' or c == '`':
			return '\\' + c
		elif c == '#' or c == '@':
			return c + '\u200B'
		return c
	return "".join(escape_char(c) for c in text)

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
				markdown_escape(data["channel"]["display_name"]),
				data["channel"]["url"],
				" is playing %s" % markdown_escape(data["game"]) if data.get("game") is not None else "",
				" (%s)" % markdown_escape(data["channel"]["status"]) if data["channel"].get("status") not in [None, ""] else ""
			) for data in streams
		])

		await bot.eris.send_message(command.channel, message)
