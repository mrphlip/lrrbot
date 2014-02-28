import http.server

# Cache responses for five minutes
CACHE_MAX_AGE = 5 * 60 

class HTTPHandler(http.server.BaseHTTPRequestHandler):
	def do_GET(self):
		self.send_response(200, self.responses[200][0])
		self.send_header("Cache-Control", "max-age={}".format(CACHE_MAX_AGE))
		self.send_header("Content-Type", "text/html")
		self.end_headers()
		self.wfile.write(
				"<html><body><p>Listening on {}</p></body>".
				format(list(self.server.bot.channels.keys())[0]).encode("utf-8"))
