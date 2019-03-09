#!/usr/bin/env python3
"""
This script downloads the latest KeyForge card data from keyforgegame.com and processes
it to turn the highly-structured data there into a flat list of card names to descriptions
formatted to send down the chat.
"""

import common
common.FRAMEWORK_ONLY = True
import sys
import json
import re
import dateutil.parser
import sqlalchemy

from common import utils
import common.postgres
from common.card import clean_text, CARD_GAME_KEYFORGE
from common.http import request

URL = 'https://www.keyforgegame.com/api/decks/?page={page}&page_size=25&links=cards'

EXPANSIONS = {
	341: {
		'code': 'KF02',
		'name': 'Call of the Archons',
		'count': 370,
		'releaseDate': '2018-11-15',
	},
}

engine, metadata = common.postgres.get_engine_and_metadata()

def main():
	print("Downloading card data...")
	carddata, houses = fetch_card_data()

	print("Processing...")
	cards = metadata.tables["cards"]
	card_collector = metadata.tables["card_collector"]
	with engine.begin() as conn, conn.begin() as trans:
		conn.execute(cards.delete().where(cards.c.game == CARD_GAME_KEYFORGE))
		for setid, cardset in sorted(carddata.items()):
			expansion = EXPANSIONS[setid]
			# Allow only importing individual sets for faster testing
			if len(sys.argv) > 1 and expansion['code'] not in sys.argv[1:]:
				continue

			release_date = dateutil.parser.parse(expansion.get('releaseDate', '1970-01-01')).date()
			for filteredname, cardname, description, collectors, hidden in process_set(expansion, cardset, houses):
				# Check if there's already a row for this card in the DB
				# (keep the one with the latest release date - it's more likely to have the accurate text)
				rows = conn.execute(sqlalchemy.select([cards.c.id, cards.c.lastprinted])
					.where(cards.c.filteredname == filteredname)
					.where(cards.c.game == CARD_GAME_KEYFORGE)).fetchall()
				if not rows:
					cardid, = conn.execute(cards.insert().returning(cards.c.id),
						game=CARD_GAME_KEYFORGE,
						filteredname=filteredname,
						name=cardname,
						text=description,
						lastprinted=release_date,
						hidden=hidden,
					).first()
				elif rows[0][1] < release_date:
					cardid = rows[0][0]
					conn.execute(cards.update().where(cards.c.id == cardid),
						name=cardname,
						text=description,
						lastprinted=release_date,
						hidden=hidden,
					)
				else:
					cardid = rows[0][0]

				for csetid, collector in collectors:
					rows = conn.execute(sqlalchemy.select([card_collector.c.cardid])
						.where((card_collector.c.setid == csetid) & (card_collector.c.collector == collector))).fetchall()
					if not rows:
						conn.execute(card_collector.insert(),
							setid=csetid,
							collector=collector,
							cardid=cardid,
						)
					elif rows[0][0] != cardid:
						rows2 = conn.execute(sqlalchemy.select([cards.c.name]).where(cards.c.id == rows[0][0])).fetchall()
						print("Different names for set %s collector number %s: \"%s\" and \"%s\"" % (csetid, collector, cardname, rows2[0][0]))

def fetch_card_data():
	# KeyForge does not appear to have an API for directly downloading card data
	# however, it _does_ have an API for downloading _decks_, and then that has
	# an option for downloading the data for the cards that appear in those decks.
	# So we can just keep downloading until we see all the cards. Though this does
	# require hard-coding how many cards we expect to see.
	complete = False
	cards = {}
	houses = {}
	pagenum = 0
	lastcount = 0
	noopcount = 0
	while True:
		pagenum += 1
		page = request(URL.format(page=pagenum))
		page = json.loads(page)
		for card in page['_linked']['cards']:
			# Mavericks are copies of existing cards in a different house
			# Don't need them for the DB, and they're rare enough that it takes a lot
			# of pageloads to find them all
			if not card['is_maverick']:
				if card['expansion'] not in cards:
					cards[card['expansion']] = {}
				cards[card['expansion']][card['id']] = card
		for house in page['_linked']['houses']:
			houses[house['id']] = house

		# count our cards to see if we've gotten them all
		if all(len(cards[k]) >= v['count'] for k,v in EXPANSIONS.items()):
			break

		# as a safety catch, if we go a bunch of pages without seeing any new cards
		# then bail out, in case our expected count is incorrect
		count = sum(len(i) for i in cards.values())
		if count == lastcount:
			noopcount += 1
			if noopcount >= 10:
				break
		else:
			noopcount = 0
		lastcount = count
	return {k: list(v.values()) for k,v in cards.items()}, houses

re_check = re.compile(r"^[a-z0-9_]+$")
re_newlines = re.compile(r"[\r\n\x0b]+")
re_multiplespaces = re.compile(r"\s{2,}")
re_remindertext = re.compile(r"( *)\([^()]*\)( *)")
re_minuses = re.compile(r"(?:^|(?<=[\s/]))[-\u2013](?=[\dXY])")
def process_card(card, expansion, houses, include_reminder=False):
	# sanitise card name
	filtered = clean_text(card.get('internalname', card["card_title"]))
	if not re_check.match(filtered):
		print("Still some junk left in name %s (%s)" % (card.get('internalname', card["card_title"]), json.dumps(filtered)))
		print(json.dumps(card))
		sys.exit(1)

	def build_description():
		yield card['card_title']
		yield ' ['
		if card['house'] in houses:
			yield houses[card['house']]['name']
		else:
			yield card['house']
		if card.get('amber'):
			yield '\u2014'
			yield str(card['amber'])
			yield '<A>'
		yield '] | '
		yield card['card_type']
		if card.get('traits'):
			yield ' \u2014 '
			yield card['traits']
		if card.get('power') or card.get('armor') or card['card_type'] == "Creature":
			yield ' ['
			yield str(card['power'])
			if card.get('armor'):
				yield '/'
				yield str(card['armor'])
			yield ']'
		if card.get('card_text'):
			yield ' | '
			yield process_text(card['card_text'], include_reminder)

	desc = ''.join(build_description())
	desc = re_multiplespaces.sub(' ', desc).strip()
	desc = utils.trim_length(desc)

	numbers = card['card_number'] if card.get('card_number') else []
	if not isinstance(numbers, list):
		numbers = [numbers]
	numbers = [(expansion['code'].lower(), str(i)) for i in numbers]
	hidden = 'internalname' in card

	return filtered, card['card_title'], desc, numbers, hidden

def process_text(text, include_reminder):
	text = re_minuses.sub('\u2212', text) # replace hyphens with real minus signs
	if not include_reminder:
		text = re_remindertext.sub(lambda match: ' ' if match.group(1) and match.group(2) else '', text)
	text = re_newlines.sub(' / ', text.strip())
	return text

SPECIAL_SETS = {}
def special_set(setid):
	def decorator(func):
		SPECIAL_SETS[setid] = func
		return func
	return decorator

def process_set(expansion, cards, houses):
	handler = SPECIAL_SETS.get(expansion['code'], process_set_general)
	yield from handler(expansion, cards, houses)

def process_set_general(expansion, cards, houses):
	for card in cards:
		# Turn on include_reminder by default for now, since KF is newer than MTG
		# Can't assume watchers know all the basic abilities
		# Also, most KF card text is shorter than some of the lengthier MTG cards,
		# we can afford leaving in the reminder text
		yield process_card(card, expansion, houses, include_reminder=True)

if __name__ == '__main__':
	main()
