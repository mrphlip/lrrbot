import http.server
import urllib.parse
import os.path
from config import config
from bs4 import BeautifulSoup
import storage
import json

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
			"/stats": self.stats
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
		self.send_headers(200, "text/html")
		with open("www/index.html") as f:
			html = BeautifulSoup(f.read())
		dl = html.find("dl", id="commands")
		commands = {}
		for command in filter(lambda x: x[:11] == "on_command_", dir(self.server.bot)):
			name = config["commandprefix"]+command[11:]
			function = getattr(self.server.bot, command)
			desc = function.__doc__ if function.__doc__ else ""
			try:
				modonly = function.__closure__[1].cell_contents.__name__ == "mod_complaint"
			except:
				modonly = False
			if function in commands:
				commands[function]["name"] += [name]
			else:
				commands[function] = {"name": [name], "desc": desc, "modonly": modonly}

		for command in sorted(commands.values(), key=lambda x: x["name"][0]):
			for name in command["name"]:
				dt = html.new_tag("dt")
				if command["modonly"]:
					dt["class"] = "modonly"
				code = html.new_tag("code")
				code.string = name
				dt.append(code)
				dl.append(dt)
			dd = html.new_tag("dd")
			if command["modonly"]:
				dd["class"] = "modonly"
			dd.append(BeautifulSoup(command["desc"]))
			dl.append(dd)
		self.wfile.write(str(html).encode("utf-8"))
	
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
			cell.string = storage.data["stats"][stat]["plural"]
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
				name=storage.data["stats"][stat]["plural"],
				data=json.dumps(list(map(lambda g: [g["display"] if "display" in g else g["name"], g["stats"][stat]], games))),
				stat=stat
			)
			body.append(script)

		self.send_headers(200, "text/html")
		self.wfile.write(str(html).encode("utf-8"))

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
