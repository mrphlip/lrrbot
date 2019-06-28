#!/usr/bin/env python3
import argparse
import urllib.request
import html5lib
import json

# satisfy ST
if 0:
	FileNotFoundError = None

MTGS_URL = "http://www.mtgsalvation.com/spoilers/filter?SetID=%d&Page=0&IncludeUnconfirmed=false&CardsPerRequest=1000"

ICONS = {
	"chaos": "C",
	"mana-colorless-00": "0",
	"mana-colorless-01": "1",
	"mana-colorless-02": "2",
	"mana-colorless-03": "3",
	"mana-colorless-04": "4",
	"mana-colorless-05": "5",
	"mana-colorless-06": "6",
	"mana-colorless-07": "7",
	"mana-colorless-08": "8",
	"mana-colorless-09": "9",
	"mana-colorless-10": "10",
	"mana-colorless-11": "11",
	"mana-colorless-12": "12",
	"mana-colorless-13": "13",
	"mana-colorless-14": "14",
	"mana-colorless-15": "15",
	"mana-colorless-16": "16",
	"mana-colorless-17": "17",
	"mana-colorless-18": "18",
	"mana-colorless-19": "19",
	"mana-colorless-20": "20",
	"mana-qm": "Infinity",
	"mana-x": "X",
	"mana-y": "Y",
	"mana-white": "W",
	"mana-blue": "U",
	"mana-black": "B",
	"mana-red": "R",
	"mana-green": "G",
	"mana-generic": "C",  # grr
	"mana-white-blue": "W/U",
	"mana-white-black": "W/B",
	"mana-blue-black": "U/B",
	"mana-blue-red": "U/R",
	"mana-black-red": "B/R",
	"mana-black-green": "B/G",
	"mana-red-green": "R/G",
	"mana-red-white": "R/W",
	"mana-green-white": "G/W",
	"mana-green-blue": "G/U",
	"mana-colorless-white": "2/W",
	"mana-colorless-blue": "2/U",
	"mana-colorless-black": "2/B",
	"mana-colorless-red": "2/R",
	"mana-colorless-green": "2/G",
	"mana-white-special": "WP",
	"mana-blue-special": "UP",
	"mana-black-special": "BP",
	"mana-red-special": "RP",
	"mana-green-special": "GP",
	"mana-t": "T",  # tap
	"mana-q": "Q",  # untap
	"mana-snow": "S",
	"mana-energy": "E",
}

def getargs():
	parser = argparse.ArgumentParser(description="Scrape card spoilers from MTGSalvation")
	parser.add_argument('mtgsid', type=int, help="MTGSalvation's set ID for the set")
	parser.add_argument('setid', type=str, help="Standard three letter code ID for the set")
	return parser.parse_args()

def main(mtgsid, setid):
	doc = getspoiler(mtgsid)
	cards = getcards(doc)
	carddata = {
		setid: {
			'cards': cards,
			'releaseDate': "1970-01-01T00:00:00Z",  # make sure these are lower priority than anything from MTGJSON
		}
	}
	with open("extracards.json", "w") as fp:
		json.dump(carddata, fp, indent=2, sort_keys=True)

def getspoiler(mtgsid):
	try:
		fp = open("%d.html" % mtgsid, "rb")
		enc = None
	except FileNotFoundError:
		print("Downloading set %d..." % mtgsid)
		fp = urllib.request.urlopen(MTGS_URL % mtgsid)
		enc = fp.info().get_content_charset()
	parser = html5lib.HTMLParser(namespaceHTMLElements=False)
	return parser.parse(fp, encoding=enc)

def getcards(doc):
	cards = []
	for i in doc.iterfind(".//*[@class='t-spoiler-container']"):
		cards.append(getcarddetails(i))
	return cards

def getcarddetails(card):
	details = {}
	details['layout'] = 'normal'
	details['name'] = gettext(card.find(".//a[@class='j-search-html']"))
	details['manaCost'] = gettext(card.find(".//*[@class='t-spoiler-mana']"), trim=True)
	details['text'] = gettextlines(card.find(".//*[@class='t-spoiler-ability']"))
	details['type'] = gettext(card.find(".//*[@class='t-spoiler-type j-search-html']")).replace(' - ', ' \u2014 ')
	stat = gettext(card.find(".//*[@class='t-spoiler-stat']"))
	if stat and '/' in stat:
		details['power'], details['toughness'] = stat.split('/')
	else:
		details['loyalty'] = stat
	footer = gettext(card.find(".//*[@class='t-spoiler-edition']"))
	if footer and '#' in footer:
		details['number'] = footer.split('#')[-1].split('/')[0].strip().lstrip('0')
	return dict((k, v) for k, v in details.items() if v is not None and v != "")

def itertext(elm, withtail=False):
	cls = elm.get('class', '').split()
	if 'mana-icon' in cls:
		for c in cls:
			if c in ICONS:
				yield "{%s}" % ICONS[c]
				break
		else:
			cls = set(cls)
			# Weird symbols around ability words. I think they're meant to be italics tags.
			if cls != {"tip", "mana-icon"} and cls != {"mana-icon"}:
				raise ValueError("Unrecognised mana symbol: %s (%s)" % (elm.attrib['class'], elm.text))
	else:
		if elm.text:
			yield elm.text
		for i in elm:
			for j in itertext(i, True):
				yield j
	if withtail and elm.tail:
		yield elm.tail

def gettext(elm, trim=False):
	if elm is None:
		return None
	text = "".join(itertext(elm))
	text = text.split()
	if trim:
		return ''.join(text)
	else:
		return ' '.join(text)

def gettextlines(elm):
	if elm is None:
		return None
	text = (gettext(i) for i in elm.iterfind("p"))
	return "\n\n".join(i for i in text if i)

if __name__ == '__main__':
	main(**vars(getargs()))
