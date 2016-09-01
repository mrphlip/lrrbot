import common.time

SPREADSHEET = "1yrf6d7dPyTiWksFkhISqEc-JR71dxZMkUoYrX4BR40Y"

def format_row(title, description, video, timestamp, nick):
	if '_id' in video:
		# Allow roughly 15 seconds for chat delay, 10 seconds for chat reaction time,
		# 20 seconds for how long the actual event is...
		linkts = timestamp.total_seconds() - 45
		linkts = "%02dh%02dm%02ds" % (linkts//3600, linkts//60 % 60, linkts % 60)
		url = "https://www.twitch.tv/loadingreadyrun/manager/%s/highlight?t=%s" % (video['_id'], linkts)
	else:
		url = video['url']
	return [
		("SHOW", title),
		("QUOTE or MOMENT", description),
		("YOUTUBE VIDEO LINK", url),
		("ROUGH TIME THEREIN", "before " + common.time.nice_duration(timestamp, 0)),
		("NOTES", "from chat user '%s'" % nick),
	]
