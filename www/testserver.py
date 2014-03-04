#!/usr/bin/env python3
import server
import index
import notifications
import stats
import oauth
import archive

server.app.run(debug=True, threaded=True)
