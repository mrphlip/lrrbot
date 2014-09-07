from lrrbot import bot
import storage
import utils

def set_show(lrrbot, show):
    lrrbot.show = show.lower()

def show_name(show):
    return storage.data.get("shows", {}).get(show, {}).get("display", show)

@bot.command("show")
@utils.throttle()
def get_show(lrrbot, conn, event, respond_to):
    """
    Command: !show

    Post the current show.
    """
    if lrrbot.show == "":
        conn.privmsg(respond_to, "Current show not set.")
    else:
        conn.privmsg(respond_to, "Currently live: %s" % show_name(lrrbot.show))

@bot.command("show override (.*?)")
@utils.mod_only
def show_override(lrrbot, conn, event, respond_to, show):
    """
    Command: !show override ID

    Override the current show.
    --command
    Command: !show override off

    Disable the override.
    """
    set_show(lrrbot, show if show != "off" else "")
    return get_show.__wrapped__(lrrbot, conn, event, respond_to)

@bot.command("show display (.*?)")
@utils.mod_only
def show_display(lrrbot, conn, event, respond_to, name):
    """
    Command: !show display NAME

    eg. !show display IDDQDerp

    Change the display name of the current show to NAME
    """
    old_name = show_name(lrrbot.show)
    storage.data.setdefault("shows", {}).setdefault(lrrbot.show, {})["display"] = name
    storage.save()
    conn.privmsg(respond_to, "OK, I'll start calling %s \"%s\"" % (old_name, name))
