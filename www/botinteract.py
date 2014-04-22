import flask.json
import socket
import login

@login.with_session
def send_bot_command(command, param, session, timeout=5):
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
                "user": session['user'],
	}
	conn.send((flask.json.dumps(data) + "\n").encode())
	buf = b""
	while b"\n" not in buf:
		buf += conn.recv(1024)
	return flask.json.loads(buf.decode())

def get_current_game():
	return send_bot_command("current_game", None)

def get_data(key):
	return send_bot_command("get_data", {
		'key': key,
	})

def set_data(key, value):
	"""
	Send a message to the bot, to update its storage.

	Will return after the data.json has been updated.
	"""
	send_bot_command("set_data", {
		'key': key,
		'value': value,
	})

def modify_commands(data):
	"""
	Send a message to the bot, to replace the static command responses.
	"""
	send_bot_command("modify_commands", data)

def get_commands():
	return send_bot_command("get_commands", None)
