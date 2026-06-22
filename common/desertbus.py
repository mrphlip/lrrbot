import datetime
from common.config import config

# When Desert Bus starts
DESERTBUS_START = config["timezone"].localize(datetime.datetime(2026, 10, 23, 15, 0))
# Has the official start time of Desert Bus been announced?
DESERTBUS_HASTIME = False
# Is the upcoming Desert Bus an "Express" event?
DESERTBUS_EXPRESS = False

# When !desertbus should stop claiming the run is still active
if DESERTBUS_EXPRESS:
	DESERTBUS_END = DESERTBUS_START + datetime.timedelta(hours=24)
else:
	DESERTBUS_END = DESERTBUS_START + datetime.timedelta(days=6)  # Six days of plugs should be long enough
