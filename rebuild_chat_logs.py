#!/usr/bin/env python3
import common
common.FRAMEWORK_ONLY = True
from lrrbot.chatlog import run_task, rebuild_all, stop_task
import asyncio

loop = asyncio.new_event_loop()
task = asyncio.ensure_future(run_task(), loop=loop)
rebuild_all()
stop_task()
loop.run_until_complete(task)
loop.close()
