#!/usr/bin/env python
import sys
import subprocess
sys.stdout.write("Content-type: text/html; charset=utf-8\n\n")

print("<!DOCTYPE html>")
print("<title>Updating LRRbot</title>")
print("<pre>")
sys.stdout.flush()
ret = subprocess.Popen(['git', 'pull', '-r'], stderr=1).wait()
sys.stdout.flush()
print("</pre>")
if ret == 0:
	print("<p>Update successful</p>")
else:
	print("<p>Update failed (%d)</p>" % ret)
