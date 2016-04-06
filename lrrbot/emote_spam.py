import asyncio
import json

from common import http
from common import utils

MAXCOST = 40

@asyncio.coroutine
def emote_sets():
    data = yield from http.request_coro("https://api.twitch.tv/kraken/chat/emoticon_images")
    emotes = json.loads(data)["emoticons"]

    code_to_set = {}
    for emote in emotes:
        code_to_set[emote["id"]] = emote["emoticon_set"] or 0

    return code_to_set

class EmoteSpam:
    def __init__(self, lrrbot, loop):
        self.lrrbot = lrrbot
        self.loop = loop

        self.emote_sets = self.loop.run_until_complete(emote_sets())

        self.lrrbot.reactor.add_global_handler('pubmsg', self.check_emotes, 22)

    def emote_cost(self, emote_id):
        set_id = self.emote_sets[emote_id]
        if set_id == 0:
            return 8
        elif set_id == 317:
            return 3
        else:
            return 5

    def check_emotes(self, conn, event):
        emotes = event.tags.get('emotes') or ''
        if len(emotes) == 0:
            return

        cost = 0
        for emote in emotes.split('/'):
            emote_id, positions = emote.split(':')
            positions = positions.split(',')
            cost += self.emote_cost(int(emote_id)) * len(positions)

        if cost > MAXCOST:
            asyncio.async(self.lrrbot.ban(conn, event, "emote spam", "censor"), loop=self.loop).add_done_callback(utils.check_exception)
            return "NO MORE"
