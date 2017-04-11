import discord
import blinker
import logging

from common.config import config
from common import postgres
from common import utils
from eris.autotopic import Autotopic
from eris.channel_reaper import ChannelReaper
from eris.command_parser import CommandParser
from eris.commands import register as register_commands

utils.init_logging("eris")
log = logging.getLogger("eris")

eris = discord.Client()
engine, metadata = postgres.new_engine_and_metadata()

# `discord.py`'s event handling is pretty poor. There can only be a single handler for an event.
# Convert `discord.py`'s events into `blinker` signals to get around that.

signals = blinker.Namespace()

@eris.event
async def on_ready():
	log.info("Connected to the server.")
	signals.signal('ready').send(eris)

@eris.event
async def on_resumed():
	signals.signal('resumed').send(eris)

@eris.event
async def on_error(event, *args, **kwargs):
	log.exception("Error in `discord.py`: args = %r; kwargs = %r", args, kwargs)

@eris.event
async def on_message(message):
	signals.signal('message').send(eris, message=message)

@eris.event
async def on_socket_raw_receive(msg):
	signals.signal('on_socket_raw_receive').send(eris, message=msg)

@eris.event
async def on_socket_raw_send(payload):
	signals.signal('socket_raw_send').send(eris, message=payload)

@eris.event
async def on_message_delete(message):
	signals.signal('message_delete').send(eris, message=message)

@eris.event
async def on_message_edit(before, after):
	signals.signal('message_edit').send(eris, before=before, after=after)

@eris.event
async def on_reaction_add(reaction, user):
	signals.signal('reaction_add').send(eris, reaction=reaction, user=user)

@eris.event
async def on_reaction_remove(reaction, user):
	signals.signal('reaction_remove').send(eris, reaction=reaction, user=user)

@eris.event
async def on_reaction_clear(message, reactions):
	signals.signal('reaction_clear').send(eris, message=message, reactions=reactions)

@eris.event
async def on_channel_delete(channel):
	signals.signal('channel_delete').send(eris, channel=channel)

@eris.event
async def on_channel_create(channel):
	signals.signal('channel_create').send(eris, channel=channel)

@eris.event
async def on_channel_update(before, after):
	signals.signal('channel_update').send(eris, before=before, after=after)

@eris.event
async def on_member_join(member):
	signals.signal('member_join').send(eris, member=member)

@eris.event
async def on_member_remove(member):
	signals.signal('member_remove').send(eris, member=member)

@eris.event
async def on_member_update(before, after):
	signals.signal('member_update').send(eris, before=before, after=after)

@eris.event
async def on_server_join(server):
	signals.signal('server_join').send(eris, server=server)

@eris.event
async def on_server_remove(server):
	signals.signal('server_remove').send(eris, server=server)

@eris.event
async def on_server_update(before, after):
	signals.signal('server_update').send(eris, before=before, after=after)

@eris.event
async def on_server_role_create(role):
	signals.signal('server_role_create').send(eris, role=role)

@eris.event
async def on_server_role_delete(role):
	signals.signal('server_role_delete').send(eris, role=role)

@eris.event
async def on_server_role_update(before, after):
	signals.signal('server_role_update').send(eris, role=role)

@eris.event
async def on_server_emojis_update(before, after):
	signals.signal('server_emojis_update').send(eris, before=before, after=after)

@eris.event
async def on_server_available(server):
	signals.signal('server_available').send(eris, server=server)

@eris.event
async def on_server_unavailable(server):
	signals.signal('server_unavailable').send(eris, server=server)

@eris.event
async def on_voice_state_update(before, after):
	signals.signal('voice_state_update').send(eris, before=before, after=after)

@eris.event
async def on_member_ban(member):
	signals.signal('member_ban').send(eris, member=member)

@eris.event
async def on_member_unban(server, user):
	signals.signal('member_unban').send(eris, member=user)

@eris.event
async def on_typing(channel, user, when):
	signals.signal('typing').send(eris, channel=channel, member=user, when=when)

@eris.event
async def on_group_join(channel, user):
	signals.signal('group_join').send(eris, channel=channel, user=user)

@eris.event
async def on_group_remove(channel, user):
	signals.signal('group_remove').send(eris, channel=channel, user=user)

autotopic = Autotopic(eris, signals, engine, metadata)
channel_reaper = ChannelReaper(eris, signals)
command_parser = CommandParser(eris, signals, engine, metadata)
register_commands(command_parser)

eris.run(config['discord_botsecret'])
