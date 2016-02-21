import flask.json
import socket
from www import login
from common.config import config

class APIError(Exception):
	"""
	Indicates an exception happened on the bot side of the RPC connection
	"""
	pass

@login.with_minimal_session
def send_bot_command(command, param, timeout=5, session=None):
	"""
	Send a message to the bot, and return the response

	Raises socket.timeout in the event of a timeout
	"""
	conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	conn.settimeout(timeout)
	conn.connect(config["socket_filename"])
	data = {
		"command": command,
		"param": param,
		"user": session['user'],
	}
	conn.send((flask.json.dumps(data) + "\n").encode())
	buf = b""
	while b"\n" not in buf:
		buf += conn.recv(1024)
	result = flask.json.loads(buf.decode())
	if result['success']:
		return result['result']
	else:
		raise APIError("Server error in %s:\n%s" % (command, result['result']))

def get_current_game():
	return send_bot_command("current_game", None)

def get_current_game_name():
	return send_bot_command("current_game_name", None)

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

def modify_explanations(data):
	"""
	Send a message to the bot, to replace the explain responses.
	"""
	send_bot_command("modify_explanations", data)

def modify_spam_rules(data):
	"""
	Send a message to the bot, to replace the spam rules.
	"""
	send_bot_command("modify_spam_rules", data)

def modify_link_spam_rules(data):
	send_bot_command("modify_link_spam_rules", data)

def get_commands():
	return send_bot_command("get_commands", None)

def get_header_info():
	return send_bot_command("get_header_info", None)

def nextstream():
	return send_bot_command("nextstream", None)

def set_show(show):
	return send_bot_command("set_show", {'show': show})

def get_show():
	return send_bot_command("get_show", None)

def get_tweet():
	return send_bot_command("get_tweet", None)
