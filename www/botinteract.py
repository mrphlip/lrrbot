import flask
import server
import utils
import secrets
import threading
import contextlib
import uuid

event_server = utils.SSEServer()
@server.app.route('/bot/events')
def botevents():
	if flask.request.values['apipass'] != secrets.apipass:
		return flask.json.jsonify(error='apipass')
	return event_server.subscribe()

callback_lock = threading.Lock()
callbacks = {}
@contextlib.contextmanager
def callback_wait(timeout=5):
	"""
	Use to send a command to the bot, and then wait for it to acknowledge the command.

	Usage:
	with callback_wait() as callback_id:
		event_server.publish({'callback': callback_id}, 'event') # or whatnot
	"""
	with callback_lock:
		my_callback_id = uuid.uuid4().hex
		my_callback = threading.Condition()
		callbacks[my_callback_id] = my_callback
	try:
		yield my_callback_id
	finally:
		with my_callback:
			my_callback.wait(timeout)
		with callback_lock:
			if my_callback_id in callbacks:
				del callbacks[my_callback_id]

@server.app.route('/bot/callback', methods=['POST'])
def callback():
	if flask.request.values['apipass'] != secrets.apipass:
		return flask.json.jsonify(error='apipass')
	with callback_lock:
		callback = callbacks.get(flask.request.values['callback'])
	if callback is not None:
		with callback:
			callback.notify_all()
	return flask.json.jsonify(success="OK")

def set_data(key, value):
	"""
	Send a message to the bot, to update its storage.

	Will return after the data.json has been updated.
	"""
	with callback_wait() as callback_id:
		data = {
			'key': key,
			'value': value,
			'callback': callback_id,
		}
		event_server.publish(data, 'set_data')
