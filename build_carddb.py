#!/usr/bin/env python3
"""
This script downloads the latest MTG card data from http://mtgjson.com/ and processes
it to turn the highly-structured data there into a flat list of card names to descriptions
formatted to send down the chat.
"""

import sys
argv = sys.argv[1:]
sys.argv = sys.argv[:1]
import os
import urllib.request
import urllib.error
import contextlib
import time
import zipfile
import io
import json
import re
import datetime
import dateutil.parser
import sqlalchemy

from common import utils
import common.postgres
from common.cardname import clean_text

URL = 'http://mtgjson.com/json/AllSets.json.zip'
ZIP_FILENAME = 'AllSets.json.zip'
SOURCE_FILENAME = 'AllSets.json'
EXTRAS_FILENAME = 'extracards.json'
MAXLEN = 450

engine, metadata = common.postgres.get_engine_and_metadata()

def main():
	if not do_download_file(URL, ZIP_FILENAME) and not os.access(EXTRAS_FILENAME, os.F_OK):
		print("No new version of mtgjson data file")
		return

	print("Reading card data...")
	with zipfile.ZipFile(ZIP_FILENAME) as zfp:
		fp = io.TextIOWrapper(zfp.open(SOURCE_FILENAME))
		mtgjson = json.load(fp)

	get_scryfall_numbers(mtgjson)

	try:
		with open(EXTRAS_FILENAME) as fp:
			extracards = json.load(fp)
	except IOError:
		pass
	else:
		# If the set is in both mtgjson and the extra data, use the one from mtgjson
		extracards.update(mtgjson)
		mtgjson = extracards
		del extracards

	print("Processing...")
	cards = metadata.tables["cards"]
	card_multiverse = metadata.tables["card_multiverse"]
	card_collector = metadata.tables["card_collector"]
	with engine.begin() as conn:
		conn.execute(card_multiverse.delete())
		conn.execute(card_collector.delete())
		conn.execute(cards.delete())
		cardid = 0
		for setid, expansion in mtgjson.items():
			# Allow only importing individual sets for faster testing
			if argv and setid not in argv:
				continue

			release_date = dateutil.parser.parse(expansion.get('releaseDate', '1970-01-01')).date()
			for filteredname, cardname, description, multiverseids, collectors, hidden in process_set(setid, expansion):
				cardid += 1

				# Check if there's already a row for this card in the DB
				# (keep the one with the latest release date - it's more likely to have the accurate text in mtgjson)
				rows = conn.execute(sqlalchemy.select([cards.c.id, cards.c.lastprinted])
					.where(cards.c.filteredname == filteredname)).fetchall()
				if not rows:
					real_cardid = cardid
					conn.execute(cards.insert(),
						id=real_cardid,
						filteredname=filteredname,
						name=cardname,
						text=description,
						lastprinted=release_date,
						hidden=hidden,
					)
				elif rows[0][1] < release_date:
					real_cardid = rows[0][0]
					conn.execute(cards.update().where(cards.c.id == real_cardid),
						name=cardname,
						text=description,
						lastprinted=release_date,
						hidden=hidden,
					)
				else:
					real_cardid = rows[0][0]

				for mid in multiverseids:
					rows = conn.execute(sqlalchemy.select([card_multiverse.c.cardid])
						.where(card_multiverse.c.id == mid)).fetchall()
					if not rows:
						conn.execute(card_multiverse.insert(),
							id=mid,
							cardid=real_cardid,
						)
					elif rows[0][0] != real_cardid and setid not in ('CPK', 'UST'):
						rows2 = conn.execute(sqlalchemy.select([cards.c.name]).where(cards.c.id == rows[0][0])).fetchall()
						print("Different names for multiverseid %d: \"%s\" and \"%s\"" % (mid, cardname, rows2[0][0]))

				for csetid, collector in collectors:
					rows = conn.execute(sqlalchemy.select([card_collector.c.cardid])
						.where((card_collector.c.setid == csetid) & (card_collector.c.collector == collector))).fetchall()
					if not rows:
						conn.execute(card_collector.insert(),
							setid=csetid,
							collector=collector,
							cardid=real_cardid,
						)
					elif rows[0][0] != real_cardid and csetid not in ('CPK', 'UST'):
						rows2 = conn.execute(sqlalchemy.select([cards.c.name]).where(cards.c.id == rows[0][0])).fetchall()
						print("Different names for set %s collector number %s: \"%s\" and \"%s\"" % (csetid, collector, cardname, rows2[0][0]))

def do_download_file(url, fn):
	"""
	Download a file, checking that there is a new version of the file on the
	server before doing so. Returns True if a download occurs.
	"""
	# Much of this code cribbed from urllib.request.urlretrieve, with If-Modified-Since logic added

	req = urllib.request.Request(url, headers={
		'User-Agent': "LRRbot/2.0 (https://lrrbot.mrphlip.com/)",
	})
	try:
		stat = os.stat(fn)
	except FileNotFoundError:
		pass
	else:
		mtime = time.strftime('%a, %d %b %Y %H:%M:%S %z', time.gmtime(stat.st_mtime))
		req.add_header('If-Modified-Since', mtime)

	try:
		fp = urllib.request.urlopen(req)
	except urllib.error.HTTPError as e:
		if e.code == 304: # Not Modified
			return False
		else:
			raise

	print("Downloading %s..." % url)
	with contextlib.closing(fp):
		headers = fp.info()

		with open(fn, 'wb') as tfp:
			bs = 1024*8
			size = None
			read = 0
			if "content-length" in headers:
				size = int(headers["Content-Length"])

			while True:
				block = fp.read(bs)
				if not block:
					break
				read += len(block)
				tfp.write(block)

	if size is not None and read < size:
		os.unlink(fn)
		raise urllib.error.ContentTooShortError(
			"retrieval incomplete: got only %i out of %i bytes"
			% (read, size), (fn, headers))

	if "last-modified" in headers:
		mtime = dateutil.parser.parse(headers['last-modified'])
		mtime = mtime.timestamp()
		os.utime(fn, (mtime, mtime))

	return True

re_check = re.compile(r"^[a-z0-9_]+$")
re_mana = re.compile(r"\{(.)\}")
re_newlines = re.compile(r"[\r\n]+")
re_multiplespaces = re.compile(r"\s{2,}")
re_remindertext = re.compile(r"( *)\([^()]*\)( *)")
def process_card(card, expansion, include_reminder=False):
	if card['layout'] in ('token', 'plane', 'scheme', 'phenomenon', 'vanguard'):  # don't care about these special cards for now
		return
	if card.get('layout') in ('split', 'aftermath'):
		# Return split cards as a single card... for all the other pieces, return nothing
		if card['name'] != card['names'][0]:
			return
		splits = []
		for splitname in card['names']:
			candidates = [i for i in expansion['cards'] if i['name'] == splitname]
			if not candidates:
				print("Can't find split card piece: %s" % splitname)
				sys.exit(1)
			splits.append(candidates[0])
		filteredparts = []
		nameparts = []
		descparts = []
		allmultiverseids = []
		allnumbers = []
		anyhidden = False
		for s in splits:
			filtered, name, desc, multiverseids, numbers, hidden = process_single_card(s, expansion, include_reminder)
			filteredparts.append(filtered)
			nameparts.append(name)
			descparts.append(desc)
			allmultiverseids.extend(multiverseids)
			allnumbers.extend(numbers)
			anyhidden = anyhidden or hidden

		filteredname = ''.join(filteredparts)
		cardname = " // ".join(nameparts)
		description = "%s | %s" % (" // ".join(card['names']), " // ".join(descparts))
		yield filteredname, cardname, description, allmultiverseids, allnumbers, anyhidden
	else:
		yield process_single_card(card, expansion, include_reminder)

def process_single_card(card, expansion, include_reminder=False):
	# sanitise card name
	filtered = clean_text(card.get('internalname', card["name"]))
	if not re_check.match(filtered):
		print("Still some junk left in name %s (%s)" % (card.get('internalname', card["name"]), json.dumps(filtered)))
		print(json.dumps(card))
		sys.exit(1)

	def build_description():
		yield card['name']
		if 'manaCost' in card:
			yield ' ['
			yield re_mana.sub(r"\1", card['manaCost'])
			yield ']'
		if card.get('layout') == 'flip':
			if card['name'] == card['names'][0]:
				yield ' (flip: '
				yield card['names'][1]
				yield ')'
			else:
				yield ' (unflip: '
				yield card['names'][0]
				yield ')'
		elif card.get('layout') == 'double-faced':
			if card['name'] == card['names'][0]:
				yield ' (back: '
				yield card['names'][1]
				yield ')'
			else:
				yield ' (front: '
				yield card['names'][0]
				yield ')'
		elif card.get('layout') == 'meld':
			top_card, bottom_card, melded_card = card['names']
			if card['name'] == top_card:
				# The names of what this melds with and into are in the card text
				pass
			elif card['name'] == bottom_card:
				yield ' (melds with: '
				yield top_card
				yield '; into: '
				yield melded_card
				yield ')'
			elif card['name'] == melded_card:
				yield ' (melds from: '
				yield top_card
				yield '; '
				yield bottom_card
				yield ')'
		yield ' | '
		yield card.get('type', '?Type missing?')
		if 'power' in card or 'toughness' in card:
			yield ' ['
			yield card.get('power', '?')
			yield '/'
			yield card.get('toughness', '?')
			yield ']'
		if 'loyalty' in card:
			yield ' ['
			yield str(card['loyalty'])
			yield ']'
		if 'hand' in card or 'life' in card:
			yield ' [hand:'
			yield str(card.get('hand', '?'))
			yield '/life:'
			yield str(card.get('life', '?'))
			yield ']'
		if 'text' in card:
			yield ' | '
			text = card['text']
			# Let Un-set cards keep their reminder text, since there's joeks in there
			if not include_reminder:
				text = re_remindertext.sub(lambda match: ' ' if match.group(1) and match.group(2) else '', text)
			yield re_newlines.sub(' / ', text.strip())

	desc = ''.join(build_description())
	desc = re_multiplespaces.sub(' ', desc).strip()
	if len(desc) > MAXLEN:
		desc = desc[:MAXLEN-1] + "\u2026"

	if 'internalname' in card:
		hidden = True
		multiverseids = numbers = []
	elif card.get('layout') == 'flip' and card['name'] != card['names'][0]:
		hidden = False
		multiverseids = numbers = []
	else:
		hidden = False
		multiverseids = [card['multiverseid']] if card.get('multiverseid') else []
		if card.get('variations'):
			multiverseids.extend(card['variations'])
		numbers = card['number'] if card.get('number') else []
		if not isinstance(numbers, list):
			numbers = [numbers]

	# if a card has multiple variants, make "number" entries for the variants
	# to match what sort of thing we'd be seeing on scryfall
	if len(multiverseids) > 1 and len(numbers) == 1:
		orig_number = numbers[0]
		for i in range(len(multiverseids)):
			numbers.append(orig_number + chr(ord('a') + i))

	numbers = [(expansion['code'], i) for i in numbers]

	return filtered, card['name'], desc, multiverseids, numbers, hidden


SPECIAL_SETS = {}
def special_set(setid):
	def decorator(func):
		SPECIAL_SETS[setid] = func
		return func
	return decorator

def process_set(setid, expansion):
	handler = SPECIAL_SETS.get(setid, process_set_general)
	yield from handler(expansion)

def process_set_general(expansion):
	for card in expansion['cards']:
		yield from process_card(card, expansion)

@special_set('AKH')
@special_set('HOU')
def process_set_amonkhet(expansion):
	re_embalm = re.compile(r"(?:^|\n|,)\s*(Embalm|Eternalize)\b", re.IGNORECASE)
	for card in expansion['cards']:
		yield from process_card(card, expansion)

		match = re_embalm.search(card.get('text', ''))
		if match:
			card['internalname'] = card['name'] + "_TKN"
			card['name'] = card['name'] + " token"
			card['subtypes'] = ["Zombie"] + card['subtypes']
			make_type(card)
			del card['manaCost']
			del card['number']
			del card['multiverseid']
			if match.group(1) == "Eternalize":
				card['power'] = card['toughness'] = '4'
			yield from process_card(card, expansion)

@special_set('UGL')
def process_set_unglued(expansion):
	for card in expansion['cards']:
		if card['name'] == 'B.F.M. (Big Furry Monster)':  # do this card special
			continue
		yield from process_card(card, expansion, include_reminder=True)

	yield (
		"bfmbigfurrymonster",
		"B.F.M. (Big Furry Monster)",
		"B.F.M. (Big Furry Monster) (BBBBBBBBBBBBBBB) | Summon \u2014 The Biggest, Baddest, Nastiest, Scariest Creature You'll Ever See [99/99] | You must play both B.F.M. cards to put B.F.M. into play. If either B.F.M. card leaves play, sacrifice the other. / B.F.M. can only be blocked by three or more creatures.",
		[9780, 9844],
		['28', '29'],
		False,
	)

@special_set('UNH')
def process_set_unhinged(expansion):
	for card in expansion['cards']:
		yield from process_card(card, expansion, include_reminder=True)

@special_set('UST')
def process_set_unstable(expansion):
	# https://magic.wizards.com/en/articles/archive/news/unstable-variants-2017-12-06
	with open("UST_variants.json") as fp:
		variants = json.load(fp)
	variants_processed = set()

	hosts = []
	augments = []
	re_augment = re.compile(r"(?:^|\n|,)\s*Augment\b", re.IGNORECASE)
	for card in expansion['cards']:
		if card['name'] in variants:
			# Handle a potential future where these variants are in mtgjson
			if card['name'] in variants_processed:
				continue

			yield from process_card(card, expansion, include_reminder=True)

			variants_processed.add(card['name'])
			orig_name = card['name']
			orig_number = card['number']
			for ix, variant in enumerate(variants[card['name']]):
				card.update(variant)
				if 'name' not in variant:
					suffix = chr(ord('A') + ix)
					# include suffix on display-name for non-alt-art-only variants
					if variant.keys() - {'multiverseid'}:
						card['name'] = "%s (%s)" % (orig_name, suffix)
					card['number'] = orig_number + suffix.lower()
					card['internalname'] = "%s_%s" % (orig_name, suffix)
				if 'types' in variant or 'subtypes' in variant:
					make_type(card)
				yield from process_card(card, expansion, include_reminder=True)
		else:
			yield from process_card(card, expansion, include_reminder=True)

		if 'Host' in card['types']:
			hosts.append(card)
			# for the benefit of the overlay
			card['internalname'] = card['name'] + "_HOST"
			yield from process_card(card, expansion, include_reminder=True)
		elif re_augment.search(card.get('text', '')):
			augments.append(card)
			card['internalname'] = card['name'] + "_AUG"
			yield from process_card(card, expansion, include_reminder=True)

	if variants_processed != variants.keys():
		raise ValueError("Didn't find all variant cards: %r" % (variants.keys() - variants_processed,))

	for augment in augments:
		for host in hosts:
			yield gen_augment(augment, host, expansion)

HOST_PREFIX = "When this creature enters the battlefield, "
def gen_augment(augment, host, expansion):
	combined = {
		'layout': 'normal',
		'internalname': "%s_%s" % (augment['internalname'], host['internalname']),
		'manaCost': host['manaCost'],
		'power': str(int(host['power']) + int(augment['power'])),
		'toughness': str(int(host['toughness']) + int(augment['toughness'])),
	}

	host_part = host['name'].split()[-1]
	augment_part = augment['name']
	if augment_part[-1] != '-':
		augment_part += ' '
	combined['name'] = augment_part + host_part

	combined['supertypes'] = host.get('supertypes', []) + augment.get('supertypes', [])
	combined['types'] = [i for i in host['types'] if i not in {'Host', 'Creature'}] + augment['types']
	combined['subtypes'] = augment['subtypes'] + host['subtypes']
	make_type(combined)

	host_lines = host['text'].split("\n")
	for host_ix, host_line in enumerate(host_lines):
		if host_line.startswith(HOST_PREFIX):
			break
	else:
		raise ValueError("Card text for host %r not expected" % host['name'])
	del host_lines[host_ix]
	host_line = host_line[len(HOST_PREFIX):]

	augment_lines = augment['text'].split("\n")
	for augment_ix, augment_line in enumerate(augment_lines):
		if augment_line[-1] in {',', ':'}:
			break
	else:
		raise ValueError("Card text for augment %r not expected" % augment['name'])
	del augment_lines[augment_ix]
	if augment_line[-1] == ':':
		host_line = host_line[:1].upper() + host_line[1:]

	combined_lines = host_lines + [augment_line + ' ' + host_line] + augment_lines
	combined['text'] = "\n".join(combined_lines)

	return process_single_card(combined, expansion, include_reminder=True)

@special_set('VAN')
def skip_set(expansion):
	if False:
		yield

@special_set('PO2')
def process_set_portal2(expansion):
	# This set is PO2 in mtgjson but P02 in Scryfall...
	for filtered, name, desc, multiverseids, numbers, hidden in process_set_general(expansion):
		numbers.extend([('P02', i[1]) for i in numbers])
		yield filtered, name, desc, multiverseids, numbers, hidden

def get_scryfall_numbers(mtgjson):
	"""
	Find sets that don't have collector numbers, and get the numbers that scryfall uses.
	"""
	try:
		with open("scryfall.json") as fp:
			scryfall = json.load(fp)
	except IOError:
		scryfall = {}
	for setid, expansion in mtgjson.items():
		if argv and setid not in argv:
			continue
		if any('number' in card for card in expansion['cards']):
			continue

		if setid not in scryfall:
			scryfall[setid] = download_scryfall_numbers(setid)
			# Save after downloading each set, so if we have an error we've still saved
			# all the downloading we've done already
			with open("scryfall.json", "w") as fp:
				json.dump(scryfall, fp, indent=2, sort_keys=True)

		for card in expansion['cards']:
			if card['name'] not in scryfall[setid]:
				raise ValueError("Couldn't find any matching scryfall cards for %s (%s)" % (card['name'], setid))
			card['number'] = scryfall[setid][card['name']]

def download_scryfall_numbers(setid):
	print("Downloading scryfall data for %s..." % setid)
	if setid == 'PO2': # scryfall uses a slightly different code here
		setid = 'P02'
	url = "https://api.scryfall.com/cards/search?q=%s" % urllib.parse.quote("++e:%s" % setid)
	mapping = {}
	while url is not None:
		fp = io.TextIOWrapper(urllib.request.urlopen(url))
		data = json.load(fp)
		fp.close()
		time.sleep(0.1) # rate limit
		for card in data['data']:
			mapping.setdefault(card['name'], []).append(card['collector_number'])
		if data['has_more']:
			url = data['next_page']
		else:
			url = None
	return mapping

def make_type(card):
	types = card['types']
	if card.get('supertypes'):
		types = card['supertypes'] + types
	if card.get('subtypes'):
		types = types + ["\u2014"] + card['subtypes']
	typeline = ' '.join(types)
	card['type'] = typeline
	return typeline

if __name__ == '__main__':
	main()
