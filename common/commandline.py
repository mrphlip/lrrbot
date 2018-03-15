import argparse
from common import FRAMEWORK_ONLY

DEFAULT_CONFIG_FILENAME = 'lrrbot.conf'

parser = argparse.ArgumentParser(description="LRRbot - LoadingReadyLive stream chatbot")
parser.add_argument('-c', '--conf', type=str, help="Config file (default: %s)" % DEFAULT_CONFIG_FILENAME, default=DEFAULT_CONFIG_FILENAME)
if FRAMEWORK_ONLY:
	argv = parser.parse_args([])
else:
	argv = parser.parse_args()
del parser

if __name__ == "__main__":
	print(argv)
