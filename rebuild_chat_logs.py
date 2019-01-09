#!/usr/bin/env python3
import common
common.FRAMEWORK_ONLY = True
import lrrbot.main
from lrrbot.chatlog import run_task, rebuild_all, stop_task
import asyncio

loop = asyncio.get_event_loop()
task = asyncio.ensure_future(run_task(), loop=loop)
rebuild_all()
stop_task()
loop.run_until_complete(task)
loop.close()
