import common.time

SPREADSHEET = "1yrf6d7dPyTiWksFkhISqEc-JR71dxZMkUoYrX4BR40Y"

def format_row(title, description, video, timestamp, nick):
	if '_id' in video:
		url = "https://www.twitch.tv/loadingreadyrun/manager/%s/highlight" % video['_id']
	else:
		url = video['url']
	return [
		("SHOW", title),
		("QUOTE or MOMENT", description),
		("YOUTUBE VIDEO LINK", url),
		("ROUGH TIME THEREIN", "before " + common.time.nice_duration(timestamp, 0)),
		("NOTES", "from chat user '%s'" % nick),
	]
