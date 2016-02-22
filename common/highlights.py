import common.time
from common import utils

SPREADSHEET = "1yrf6d7dPyTiWksFkhISqEc-JR71dxZMkUoYrX4BR40Y"

def format_row(title, description, url, timestamp, nick):
	return [
		("SHOW", title),
		("QUOTE or MOMENT", description),
		("YOUTUBE VIDEO LINK", url),
		("ROUGH TIME THEREIN", "before " + common.time.nice_duration(timestamp, 0)),
		("NOTES", "from chat user '%s'" % nick),
	]
