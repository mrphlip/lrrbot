import http.server
import urllib.parse
import os.path
from config import config
from bs4 import BeautifulSoup
import storage
import json
import time
import utils

# Cache responses for five minutes
CACHE_MAX_AGE = 5 * 60

# Highcharts Javascript blob
chart = """
$(function (){{
	$('#chart-{stat}').highcharts({{
		title: {{
			text: "{name}"
		}},
		tooltip: {{
			pointFormat: '{{series.name}}: <b>{{point.y}}</b><br>Share: <b>{{point.percentage:.1f}}%</b>'
		}},
		plotOptions: {{
			pie: {{
				allowPointSelect: true,
				cursor: 'pointer',
				dataLabels: {{
					enabled: true,
					color: '#000000',
					connectorColor: '#000000',
					format: '<b>{{point.name}}</b>: {{point.y}}'
				}}
			}}
		}},
		series: [{{
			type: 'pie',
			name: "{name}",
			data: {data}
		}}]
	}});
}});
"""

class HTTPHandler(http.server.BaseHTTPRequestHandler):
	def __init__(self, request, client_address, server):
		self.endpoints = {
			"/index.html": self.index,
			"/stats.html": self.stats,
			"/stats": self.stats,
			"/notifications.html": self.notifications,
			"/notifications": self.notifications,
		}
		self.content_type = {
			"css": "text/css",
			"js": "text/javascript"
		}
		super().__init__(request, client_address, server)

	def send_headers(self, response, content_type = "text/html"):
		self.send_response(response, self.responses[response][0])
		self.send_header("Cache-Control", "max-age={}".format(CACHE_MAX_AGE))
		self.send_header("Content-Type", "{}; charset=utf-8".format(content_type))
		self.end_headers()
	
	def index(self):
		commands = {}
		for command in filter(lambda x: x[:11] == "on_command_", dir(self.server.bot)):
			name = (config["commandprefix"]+command[11:]).replace("_", " ")
			function = getattr(self.server.bot, command)
			desc = function.__doc__ if function.__doc__ else ""
			try:
				modonly = function.__closure__[1].cell_contents.__name__ == "mod_complaint"
			except:
				modonly = False
			try:
				period = function.__closure__[1].cell_contents.period
			except:
				period = 0
			if function in commands:
				commands[function]["name"] += [name]
			else:
				commands[function] = {
					"name": [name], 
					"desc": desc, 
					"modonly": modonly, 
					"period": period
				}

		with open("www/index.html") as f:
			html = BeautifulSoup(f.read())
		dl = html.find("dl", id="commands")
		for command in sorted(commands.values(), key=lambda x: x["name"][0]):
			dt = html.new_tag("dt")
			for name in command["name"]:
				if command["modonly"]:
					dt["class"] = "modonly"
				code = html.new_tag("code")
				code.string = name
				dt.append(code)
				if name != command["name"][-1]:
					dt.append(" or ")
			dl.append(dt)
			dd = html.new_tag("dd")
			if command["modonly"]:
				dd["class"] = "modonly"
			for elem in BeautifulSoup(command["desc"]).body.children:
				dd.append(elem)
			if command["period"] > 0:
				p = html.new_tag("p")
				p.string = "Can be used {} seconds after the last use.".format(command["period"])
				dd.append(p)
			dl.append(dd)
		ul = html.find("ul", id="stats")
		for stat in sorted(storage.data["stats"]):
			code = html.new_tag("code")
			code.string = stat
			li = html.new_tag("li")
			li.append(code)
			ul.append(li)
		self.send_headers(200, "text/html")
		self.wfile.write(html.encode("utf-8"))
	
	def stats(self):
		with open("www/stats.html") as f:
			html = BeautifulSoup(f.read())
		table = html.find("table", id="statstable")

		# Sort statistics by their total value. Result is a list of (name, total)-pairs 
		stats = sorted(map(lambda stat:	(stat, sum(map(lambda game: game["stats"][stat], storage.data["games"].values()))), storage.data["stats"]), key=lambda stat: stat[1], reverse=True)
		# Sort games by their displayed name. Result is a list of dictionaries
		games = sorted(storage.data["games"].values(), key=lambda game: game["display"] if "display" in game else game["name"])

		# header
		header = html.new_tag("thead")
		table.append(header)
		row = html.new_tag("tr")
		header.append(row)

		cell = html.new_tag("th")
		cell["class"] = "game"
		cell.string = "Game"
		row.append(cell)
		for stat, _ in stats:
			cell = html.new_tag("th")
			cell["class"] = "stat " + stat
			cell.string = storage.data["stats"][stat]["plural"].capitalize()
			row.append(cell)

		# stats
		for game in games:
			row = html.new_tag("tr")
			cell = html.new_tag("td")
			cell["class"] = "game"
			if "display" in game:
				alt = html.new_tag("span", title=game["name"])
				alt["class"] = "alias"
				alt.string = game["display"]
				cell.append(alt)
			else:
				cell.string = game["name"]
			row.append(cell)
			for stat, _ in stats:
				cell = html.new_tag("td")
				cell["class"] = "stat "+stat
				cell.string = str(game["stats"][stat])
				row.append(cell)
			table.append(row)

		# footer
		footer = html.new_tag("tfoot")
		table.append(footer)
		row = html.new_tag("tr")
		footer.append(row)
		cell = html.new_tag("th")
		cell["class"] = "total"
		cell.string = "Total"
		row.append(cell)

		for stat, total in stats:
			cell = html.new_tag("th")
			cell["class"] = "stat "+stat
			cell.string = str(total)
			row.append(cell)

		# charts
		body = html.body
		body.append(html.new_tag("script", type="text/javascript", src="js/jquery-1.10.2.js"))
		body.append(html.new_tag("script", type="text/javascript", src="js/highcharts.js"))
		for stat, _ in stats:
			div = html.new_tag("div", id="chart-{}".format(stat))
			div["class"]="highchart"
			body.append(div)
			script = html.new_tag("script", type="text/javascript")
			script.string = chart.format(
				name=storage.data["stats"][stat]["plural"].capitalize(),
				data=json.dumps(list(map(lambda g: [g["display"] if "display" in g else g["name"], g["stats"][stat]], games))),
				stat=stat
			)
			body.append(script)

		self.send_headers(200, "text/html")
		self.wfile.write(html.encode("utf-8"))
	
	def notifications(self):
		storage.data.setdefault("notifications", [])
		storage.data["notifications"] = list(filter(lambda e: e["eventtime"] - time.time() < 24*3600, storage.data["notifications"]))
		storage.save()

		with open("www/notifications.html") as f:
			html = BeautifulSoup(f.read())
		html.head.append(html.new_tag("meta", **{"http-equiv": "refresh", "content": str(CACHE_MAX_AGE+5)}))
		ol = html.find("ol", id="notificationlist")
		for event in sorted(storage.data["notifications"], key=lambda x: x["eventtime"], reverse=True):
			li = html.new_tag("li")
			ol.append(li)
			if "eventtime" in event:
				div = html.new_tag("div", **{"class": "duration"})
				div.string = str(utils.nice_duration(time.time()-event["eventtime"]))
				li.append(div)
			if "channel" in event:
				div = html.new_tag("div", **{"class": "channel"})
				div.string = event["channel"]
				li.append(div)
			if "subuser" in event:
				div = html.new_tag("div", **{"class": "user"})
				if "avatar" in event:
					a = html.new_tag("a")
					a["href"]="http://www.twitch.tv/{}".format(event["subuser"])
					a.append(html.new_tag("img", src=event["avatar"]))
					div.append(a)
				a = html.new_tag("a")
				a["href"]="http://www.twitch.tv/{}".format(event["subuser"])
				a.string = event["subuser"]
				div.append(a)
				div.append(" just subscribed!")
				li.append(div)
			else:
				div = html.new_tag("div", **{"class": "message"})
				div.string = event["message"]
				li.append(div)
		self.send_headers(200, "text/html")
		self.wfile.write(html.encode("utf-8"))

	def do_GET(self):
		path = os.path.normpath(urllib.parse.urlparse(self.path).path)
		
		if path == "/":
			path = "/index.html"
		if path in self.endpoints:
			self.endpoints[path]()
		else:
			response = 200 if os.path.exists("www"+path) else 404
			content_type = self.content_type.get(path[path.rfind(".")+1:], "text/html") \
				if response == 200 else "text/html"
			self.send_headers(response, content_type)
			if response == 200:
				with open("www"+path, "rb") as f:
					self.wfile.write(f.read())
			else:
				self.wfile.write("<html><body><h1>{} {}</h1><p>{}</p></body></html>"
						.format(response, self.responses[response][0],
							self.responses[response][1]).encode("utf-8"))
