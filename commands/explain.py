from lrrbot import bot, log
from config import config
import storage
import random
import utils
import re
import json
from bs4 import BeautifulSoup, NavigableString, Tag

API_ENDPOINT = "http://wiki.loadingreadyrun.com/api.php"
PARAMS = {
	"format": "json",
	"action": "query",
	"rvprop": "content",
	"prop": "revisions|categories",
	"redirects": "",
	"rvparse": ""
}

def watch(page):
	for table in page.find_all("table"):
		tr = table.find("tr")
		for a in tr.find_all("a"):
			# Watch <a href="...">...</a>
			if isinstance(a.previous_sibling, NavigableString) and \
				a.previous_sibling.strip().startswith("Watch"):
			    return a["href"]
			# <b>Watch:</b> <b><a href="...">..</a></b>
			if isinstance(a.parent.previous_sibling, NavigableString) and \
				isinstance(a.parent.previous_sibling.previous_sibling, Tag) and \
				a.parent.previous_sibling.previous_sibling.get_text().strip()\
				    .startswith("Watch"):
			    return a["href"]
	return ""

def wiki(topic):
	params = {"titles": "_".join(topic.strip().split())}
	params.update(PARAMS)
	data = json.loads(utils.http_request(API_ENDPOINT, data=params))
	for page in data["query"]["pages"].values():
		try:
			categories = set(map(lambda c: c["title"][len("Category:"):], page["categories"]))
		except:
			categories = set()
		suffix = ""
		try:
			page = page["revisions"][0]["*"]
			page = BeautifulSoup(page)
		except:
			return None
		if "Videos" in categories:
			for p in page.find_all("p"):
				text = p.get_text().strip()
				if text.startswith("Date: ") or text.startswith("Upload Date") or \
					    text.startswith("Date released"):
					suffix += " "+text+". "
			suffix += " " + watch(page)
		
		for tag in page.find_all(["p", "h2"]):
			if tag.name == "h2":
				if tag.get_text().strip() == "Vital Statistics":
					return utils.shorten(suffix, 450)
				continue
			text = tag.get_text().strip()
			i = tag.find("i")
			if text == '' or i is not None and i.get_text().strip() == text:
				continue
			return utils.shorten(text+suffix, 450)

@bot.command("explain (.*?)")
@utils.throttle(5, params=[4])
def explain_response(lrrbot, conn, event, respond_to, command):
	"""
	Command: !explain TOPIC
	Mod-Only: true
	
	Provide an explanation for a given topic.
	"""
	command = " ".join(command.split())
	response_data = storage.data["explanations"].get(command.lower())
	if not response_data:
		return
	if response_data["access"] == "sub":
		if not lrrbot.is_sub(event) and not lrrbot.is_mod(event):
			log.info("Refusing explain %s due to inadequate access" % command)
			return
	if response_data["access"] == "mod":
		if not lrrbot.is_mod(event):
			log.info("Refusing explain %s due to inadequate access" % command)
			return
	response = response_data['response']
	if isinstance(response, (tuple, list)):
		response = random.choice(response)
	conn.privmsg(respond_to, response)

@bot.command("wiki (.*?)")
@utils.spammable()
@utils.throttle(5, params=[4])
def wiki_response(lrrbot, conn, event, respond_to, topic):
	"""
	Command: !wiki TOPIC

	Post the first paragraph of the LoadingReadyWiki page for that topic.
	"""
	response = wiki(topic)
	if response is not None and response != "":
		conn.privmsg(respond_to, response)

def modify_explanations(commands):
    storage.data["explanations"] = {k.lower(): v for k,v in commands.items()}
    storage.save()
