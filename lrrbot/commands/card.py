import json
import re

import lrrbot.decorators
from lrrbot.main import bot
import common.postgres

@bot.command("card (.+)")
@lrrbot.decorators.throttle(60, count=3)
def card_lookup(lrrbot, conn, event, respond_to, search):
	"""
	Command: !card card-name
	Section: misc

	Show the details of a given Magic: the Gathering card.
	"""
	real_card_lookup(lrrbot, conn, event, respond_to, search)

def real_card_lookup(lrrbot, conn, event, respond_to, search, noerror=False):
	cards = find_card(search)

	if noerror and len(cards) != 1:
		return

	if len(cards) == 0:
		conn.privmsg(respond_to, "Can't find any card by that name")
	elif len(cards) == 1:
		conn.privmsg(respond_to, cards[0][1])
	elif len(cards) <= 5:
		conn.privmsg(respond_to, "Did you mean: %s" % '; '.join(card[0] for card in cards))
	else:
		conn.privmsg(respond_to, "Found %d cards you could be referring to - please enter more of the name" % len(cards))

@common.postgres.with_postgres
def find_card(conn, cur, search):
	if isinstance(search, int):
		cur.execute("SELECT c.name, c.text FROM card_multiverse m JOIN cards c ON c.cardid = m.cardid WHERE m.multiverseid = %s", (search,))
		return cur.fetchall()

	cleansearch = clean_text(search)
	cur.execute("SELECT name, text FROM cards WHERE filteredname = %s", (cleansearch,))
	rows = cur.fetchall()
	if rows:
		return rows

	searchwords = search.split()
	searchwords = [clean_text(i) for i in searchwords]
	searchlike = "%" + "%".join(utils.escape_like(i) for i in searchwords) + "%"
	cur.execute("SELECT name, text FROM cards WHERE filteredname LIKE %s", (searchlike,))
	return cur.fetchall()

re_specialchars = re.compile(r"[ \-'\",:!?.()\u00ae&/]")
LETTERS_MAP = {
	'\u00e0': 'a',
	'\u00e1': 'a',
	'\u00e2': 'a',
	'\u00e3': 'a',
	'\u00e4': 'a',
	'\u00e5': 'a',
	'\u00e6': 'ae',
	'\u00e7': 'c',
	'\u00e8': 'e',
	'\u00e9': 'e',
	'\u00ea': 'e',
	'\u00eb': 'e',
	'\u00ec': 'i',
	'\u00ed': 'i',
	'\u00ee': 'i',
	'\u00ef': 'i',
	'\u00f0': 'th',
	'\u00f1': 'n',
	'\u00f2': 'o',
	'\u00f3': 'o',
	'\u00f4': 'o',
	'\u00f5': 'o',
	'\u00f6': 'o',
	'\u00f8': 'o',
	'\u00f9': 'u',
	'\u00fa': 'u',
	'\u00fb': 'u',
	'\u00fc': 'u',
	'\u00fd': 'y',
	'\u00fe': 'th',
	'\u00ff': 'y',
}
def clean_text(text):
	"""Clean up the search text, by removing special characters and canonicalising letters with diacritics etc"""
	text = text.lower()
	text = re_specialchars.sub('', text)
	for k, v in LETTERS_MAP.items():
		text = text.replace(k, v)
	return text
