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
import os
import math
import time
import requests

from common import utils
import common.postgres
from common.card import clean_text, CARD_GAME_KEYFORGE
from common.http import USER_AGENT

PAGE_SIZE = 25
URL = 'https://www.keyforgegame.com/api/decks/'
THROTTLED_ADDITIONAL_WAIT_TIME = 5.0
SUCCESSFUL_REQUEST_WAIT_TIME = 2.0
CACHE_DIR = ".kfcache"

session = requests.Session()
session.headers['User-Agent'] = USER_AGENT

EXPANSIONS = {
	# KF01 = CotA Starter Set
	341: {
		'code': 'KF02',
		'name': 'Call of the Archons',
		'releaseDate': '2018-11-15',
	},
	435: {
		'code': 'KF03',
		'name': 'Age of Ascension',
		'releaseDate': '2019-05-30',
	},
	# KF04 = AoA Starter Set
	452: {
		'code': 'KF05',
		'name': 'Worlds Collide',
		'releaseDate': '2019-11-08',
	},
	453: {
		'code': 'KF05A',
		'name': 'Worlds Collide Anomolies',
		'releaseDate': '2019-11-08',
	},
	# KF06 = WC Deluxe Deck
	# KF07 = WC Starter Set
	# KF08 = WC Premium Box
}

engine, metadata = common.postgres.get_engine_and_metadata()

def main():
	try:
		os.mkdir(CACHE_DIR)
	except FileExistsError:
		pass

	print("Downloading card data...")
	carddata, houses = fetch_card_data()

	print("Processing...")
	cards = metadata.tables["cards"]
	processed_cards = set()
	with engine.connect() as conn:
		conn.execute(cards.delete().where(cards.c.game == CARD_GAME_KEYFORGE))
		for setid, cardset in sorted(carddata.items(), key=lambda e: EXPANSIONS[e[0]]['releaseDate'], reverse=True):
			expansion = EXPANSIONS[setid]
			# Allow only importing individual sets for faster testing
			if len(sys.argv) > 1 and expansion['code'] not in sys.argv[1:]:
				continue

			for filteredname, cardname, description, hidden in process_set(expansion, cardset, houses):
				if filteredname not in processed_cards:
					conn.execute(cards.insert(), {
						"game": CARD_GAME_KEYFORGE,
						"filteredname": filteredname,
						"name": cardname,
						"text": description,
						"hidden": hidden,
					})
					processed_cards.add(filteredname)
		conn.commit()

re_429_detail = re.compile(r"This endpoint is currently disabled due to too many requests\. Please, try again in (\d+) seconds\.")
def getpage(page):
	fn = f"{CACHE_DIR}/{page}.json"
	if os.path.exists(fn):
		with open(fn, 'r') as fp:
			return fp.read()
	else:
		while True:
			print("Fetching page", page)
			res = session.get(URL, params={'page': page, 'page_size': PAGE_SIZE, 'links': 'cards'})
			if res.status_code == 429:
				error = res.json()
				match = re_429_detail.fullmatch(error['detail'])
				if match:
					wait_time = float(match.group(1)) + THROTTLED_ADDITIONAL_WAIT_TIME
					print("Request was throttled. Waiting %.2f seconds before retrying..." % wait_time)
					time.sleep(wait_time)
					continue
			res.raise_for_status()

			dat = res.text
			with open(fn, 'w') as fp:
				fp.write(dat)
			time.sleep(SUCCESSFUL_REQUEST_WAIT_TIME)
			return dat

def fetch_card_data():
	# KeyForge does not appear to have an API for directly downloading card data
	# however, it _does_ have an API for downloading _decks_, and then that has
	# an option for downloading the data for the cards that appear in those decks.
	# So we can just keep downloading until we see all the cards. Though this does
	# require hard-coding how many cards we expect to see.
	cards = {}
	houses = {}
	pagenum = 1
	pagetotal = 1
	pagestep = 1.0
	while pagenum <= pagetotal:
		#print("%d/%d (+%.02f)" % (pagenum, pagetotal, pagestep))
		page = getpage(pagenum)
		page = json.loads(page)

		pagetotal = math.ceil(page['count'] / PAGE_SIZE)

		foundnew = False
		for card in page['_linked']['cards']:
			# Mavericks are copies of existing cards in a different house
			# Don't need them for the DB, and they're rare enough that it takes a lot
			# of pageloads to find them all
			if card['is_maverick']:
				continue
			if card['expansion'] not in cards:
				cards[card['expansion']] = {}
			if card['id'] not in cards[card['expansion']]:
				foundnew = True
			cards[card['expansion']][card['id']] = card
		for house in page['_linked']['houses']:
			houses[house['id']] = house

		# The decks are grouped by expansion, so there'll be a bunch of new cards
		# at the start, then a long run of duplicates, then a bunch of new cards at
		# the next expansion, etc. So load every page while we're still seeing new
		# cards, but then jump forward to try to find the next section.
		if foundnew:
			pagestep = 1.0
		else:
			pagestep *= 1.2
		pagenum += math.floor(pagestep)

	#print({k:len(v) for k,v in cards.items()})

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
		if card.get('is_anomaly'):
			yield "Anomaly"
		elif card['house'] in houses:
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
		if card['card_type'] == "Creature":
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

	hidden = 'internalname' in card

	return filtered, card['card_title'], desc, hidden

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
