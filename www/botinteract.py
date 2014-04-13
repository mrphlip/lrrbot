import flask.json
import socket

def send_bot_command(command, param, timeout=5):
	"""
	Send a message to the bot, and return the response

	Raises socket.timeout in the event of a timeout
	"""
	conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	conn.settimeout(timeout)
	conn.connect("../lrrbot.sock")
	data = {
		"command": command,
		"param": param,
	}
	conn.send((flask.json.dumps(data) + "\n").encode())
	buf = b""
	while b"\n" not in buf:
		buf += conn.recv(1024)
	return flask.json.loads(buf.decode())

def set_data(key, value):
	"""
	Send a message to the bot, to update its storage.

	Will return after the data.json has been updated.
	"""
	data = {
		'key': key,
		'value': value,
	}
	send_bot_command("set_data", data)
