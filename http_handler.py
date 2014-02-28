import http.server
import urllib.parse
import os.path

# Cache responses for five minutes
CACHE_MAX_AGE = 5 * 60 

class HTTPHandler(http.server.BaseHTTPRequestHandler):
	def do_GET(self):
		path = os.path.normpath("www/"+urllib.parse.urlparse(self.path).path)
		if path == "www":
			path = "www/index.html"
		response = 200 if os.path.exists(path) else 404
		self.send_response(response, self.responses[response][0])
		self.send_header("Cache-Control", "max-age={}".format(CACHE_MAX_AGE))
		self.send_header("Content-Type", "text/html; charset=utf-8")
		self.end_headers()
		if response == 200:
			with open(path, "rb") as f:
				self.wfile.write(f.read())
		else:
			self.wfile.write("<html><body><h1>{} {}</h1><p>{}</p></body></html>"
					.format(response, self.responses[response][0],
						self.responses[response][1]).encode("utf-8"))
