from common.config import config
from common import patreon

from lrrbot.main import bot
import lrrbot.decorators

@bot.command("patreon")
@lrrbot.decorators.throttle()
async def get_patreon_info(lrrbot, conn, event, respond_to):
	"""
	Command: !patreon
	Section: info

	Post the Patreon total.
	"""
	token = await patreon.get_token(lrrbot.engine, lrrbot.metadata, config["channel"])
	campaigns = await patreon.get_campaigns(token, ["creator", "goals"])
	campaign = campaigns["data"][0]["attributes"]
	total = "%d %s for a total of %s per %s." % (
		campaign["patron_count"],
		"patrons" if campaign["patron_count"] != 1 else "patron",
		# `printf`-style formatting doesn't support thousands separators
		"${:,.2f}".format(campaign["pledge_sum"] / 100),
		campaign["pay_per_name"],
	)
	creator_id = campaigns["data"][0]["relationships"]["creator"]["data"]
	goal_ids = campaigns["data"][0]["relationships"]["goals"]["data"] or []
	creator = None
	goals = [None for goal_id in goal_ids]
	for resource in campaigns["included"]:
		if resource['type'] == creator_id['type'] and resource['id'] == creator_id['id']:
			creator = resource
		else:
			for i, goal_id in enumerate(goal_ids):
				if resource['type'] == goal_id['type'] and resource['id'] == goal_id['id']:
					goals[i] = resource

	next_goals = [
		goal
		for goal in goals
		if goal["attributes"]["amount_cents"] > campaign["pledge_sum"]
	]
	next_goals.sort(key=lambda goal: goal["attributes"]["amount_cents"])

	if len(next_goals) > 0:
		next_goal = " Next goal \"%s\" at %s per %s." % (
			next_goals[0]["attributes"]["title"],
			# `printf`-style formatting doesn't support thousands separators
			"${:,.2f}".format(next_goals[0]["attributes"]["amount_cents"] / 100),
			campaign["pay_per_name"]
		)
	else:
		next_goal = ""

	conn.privmsg(respond_to, total + next_goal + " %s" % creator["attributes"]["url"])
