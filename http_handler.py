import http.server
import urllib.parse
import os.path
from config import config
from bs4 import BeautifulSoup

# Cache responses for five minutes
CACHE_MAX_AGE = 5 * 60 

class HTTPHandler(http.server.BaseHTTPRequestHandler):
	def __init__(self, request, client_address, server):
		self.endpoints = {
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
	
	def inject_commands(self, html):
		html = BeautifulSoup(html)
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
		return str(html).encode("utf-8")

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
					if path == "/index.html":
						self.wfile.write(self.inject_commands(f.read()))
					else:
						self.wfile.write(f.read())
			else:
				self.wfile.write("<html><body><h1>{} {}</h1><p>{}</p></body></html>"
						.format(response, self.responses[response][0],
							self.responses[response][1]).encode("utf-8"))
