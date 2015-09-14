#!/usr/bin/env python3
from lrrbot.chatlog import run_task, rebuild_all, stop_task
import asyncio

loop = asyncio.get_event_loop()
task = asyncio.async(run_task(), loop=loop)
rebuild_all()
stop_task()
loop.run_until_complete(task)
loop.close()
