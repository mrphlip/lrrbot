#!/usr/bin/env python3

import aiohttp
import aiohttp.web
import aiomas
import asyncio
import mimeparse
import sqlalchemy
import sys
import json
import datetime
import pytz
import os

import common.rpc
import common.postgres
from common.config import config

class Poison:
	pass

class Server(common.rpc.Server):
	router = aiomas.rpc.Service()

	def __init__(self):
		super().__init__()
		self.engine, self.metadata = common.postgres.get_engine_and_metadata()
		self.queues = []

	async def negotiate(self, request):
		request.headers.getall('Accept', "*/*")
		mime_type = mimeparse.best_match(['application/json', 'text/event-stream'],
			",".join(request.headers.getall('Accept', "*/*")))
		if mime_type == 'text/event-stream':
			return await self.event_stream(request)
		elif mime_type == 'application/json':
			return await self.json(request)
		else:
			raise NotImplementedError(mime_type)

	def get_last_events(self, request):
		try:
			last_event_id = int(request.headers.get('Last-Event-Id', request.query.get('last-event-id')))
		except (ValueError, TypeError):
			last_event_id = None
		interval = request.query.get('interval')
		if interval is not None and last_event_id is None:
			last_event_id = 0
		if last_event_id is not None:
			events = self.metadata.tables['events']
			query = sqlalchemy.select(events.c.id, events.c.event, events.c.data, events.c.time)
			query = query.where(events.c.id > last_event_id)
			if interval is not None:
				query = query.where(events.c.time > sqlalchemy.func.current_timestamp() - sqlalchemy.cast(interval, sqlalchemy.Interval))
			query = query.order_by(events.c.id)
			try:
				with self.engine.connect() as conn:
					return [
						{'id': id, 'event': event, 'data': dict(data, time=time.isoformat())}
						for id, event, data, time in conn.execute(query)
					]
			except sqlalchemy.exc.DataError as e:
				raise aiohttp.web.HTTPBadRequest from e
		return []

	async def event_stream(self, request):
		queue = asyncio.Queue()
		for event in self.get_last_events(request):
			await queue.put(event)
		self.queues.append(queue)

		response = aiohttp.web.StreamResponse()
		response.enable_chunked_encoding()
		response.headers['Access-Control-Allow-Origin'] = '*'
		response.headers['Content-Type'] = 'text/event-stream; charset=utf-8'
		response.headers['Vary'] = "Accept"
		await response.prepare(request)

		while True:
			try:
				try:
					event = await asyncio.wait_for(queue.get(), 15)
					if event['event'] is Poison:
						break
					await response.write(b"id:%d\n" % event['id'])
					await response.write(b"event:%s\n" % event['event'].encode('utf-8'))
					await response.write(b"data:%s\n" % json.dumps(event['data']).encode('utf-8'))
					await response.write(b"\n")
					queue.task_done()
				except asyncio.TimeoutError:
					await response.write(b":keep-alive\n\n")
			except IOError:
				break

		self.queues.remove(queue)

		return response

	async def json(self, request):
		return aiohttp.web.json_response({
			'events': self.get_last_events(request),
		}, headers={"Vary": "Accept", 'Access-Control-Allow-Origin': request.headers.get('Origin', '*')})

	async def cors_preflight(self, request):
		return aiohttp.web.Response(headers={
			'Access-Control-Allow-Origin': request.headers.get('Origin', '*'),
		})

	@aiomas.expose
	async def event(self, event, data, time=None):
		if time is None:
			time = datetime.datetime.now(tz=pytz.utc)
		events = self.metadata.tables['events']
		with self.engine.connect() as conn:
			id, = conn.execute(events.insert().returning(events.c.id), {
				"event": event,
				"data": data,
				"time": time,
			}).first()
			conn.commit()
		event = {
			'id': id,
			'event': event,
			'data': dict(data, time=time.isoformat()),
		}
		for queue in self.queues:
			await queue.put(event)

	async def on_shutdown(self, app):
		for queue in self.queues:
			await queue.put({'event': Poison})

server = None
srv = None
handler = None
app = None

async def main(loop):
	global server, srv, app, handler

	try:
		os.unlink(config['eventsocket'])
	except FileNotFoundError:
		pass
	server = Server()
	await server.start(config['eventsocket'], config['event_port'])
	app = aiohttp.web.Application()
	app.router.add_route('GET', '/api/v2/events', server.negotiate)
	app.router.add_route('OPTIONS', '/api/v2/events', server.cors_preflight)
	app.on_shutdown.append(server.on_shutdown)

	handler = app.make_handler()
	srv = await loop.create_server(handler, 'localhost', 8080)
	if sys.platform == "win32":
		# On Windows Ctrl+C doesn't interrupt `select()`.
		def windows_is_butts():
			loop.call_later(5, windows_is_butts)
		windows_is_butts()

async def cleanup():
	global server, srv, app, handler

	srv.close()
	await server.close()
	await srv.wait_closed()
	await app.shutdown()
	await handler.finish_connections(60.0)
	await app.cleanup()

loop = asyncio.new_event_loop()
loop.run_until_complete(main(loop))
try:
	loop.run_forever()
except KeyboardInterrupt:
	pass
finally:
	loop.run_until_complete(cleanup())
loop.close()
