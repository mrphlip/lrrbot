import datetime
from common.config import config

# When Desert Bus starts
DESERTBUS_START = config["timezone"].localize(datetime.datetime(2025, 11, 14, 15, 0))
# Is the upcoming Desert Bus an "Express" event?
DESERTBUS_EXPRESS = False

# When !desertbus should stop claiming the run is still active
if DESERTBUS_EXPRESS:
	DESERTBUS_END = DESERTBUS_START + datetime.timedelta(hours=24)
else:
	DESERTBUS_END = DESERTBUS_START + datetime.timedelta(days=6)  # Six days of plugs should be long enough
