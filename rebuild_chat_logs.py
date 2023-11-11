#!/usr/bin/env python3
import common
common.FRAMEWORK_ONLY = True
from common import postgres
from lrrbot.chatlog import ChatLog
import asyncio

chatlog = ChatLog(*postgres.get_engine_and_metadata())
chatlog.rebuild_all()
chatlog.stop_task()
asyncio.run(chatlog.run_task())
