from lrrbot import bot
import twitch
import utils
import time
import storage

@bot.command("highlight (.*?)")
@utils.sub_only()
@utils.throttle(60)
def highlight(lrrbot, conn, event, respond_to, description):
    if not twitch.get_info()["live"]:
        conn.privmsg(respond_to, "Not currently streaming.")
        return
    storage.data.setdefault("staged_highlights", [])
    storage.data["staged_highlights"] += [{
        "time": time.time(),
        "user": irc.client.NickMask(event.source).nick,
        "description": description,
    }]
    storage.save()
    conn.privmsg(respond_to, "Highlight added.")
