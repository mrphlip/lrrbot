#!/usr/bin/env python3
"""
This script downloads the latest MTG card data from http://mtgjson.com/ and processes
it to turn the highly-structured data there into a flat list of card names to descriptions
formatted to send down the chat.
"""

import common
common.FRAMEWORK_ONLY = True
import sys
import os
import urllib.request
import urllib.error
import urllib.parse
import json
import re
import psycopg2

from common import http, utils
from common.config import config
from common.card import clean_text, CARD_GAME_MTG

EXTRAS_FILENAME = 'extracards.json'

URLS = [
	('https://mtgjson.com/api/v5/AllPrintings.json.xz', lambda: __import__('lzma').open, lambda f: f),
	('https://mtgjson.com/api/v5/AllPrintings.json.bz2', lambda: __import__('bz2').open, lambda f: f),
	('https://mtgjson.com/api/v5/AllPrintings.json.gz', lambda: __import__('gzip').open, lambda f: f),
	('https://mtgjson.com/api/v5/AllPrintings.json.zip', lambda: __import__('zipfile').ZipFile, lambda zip: zip.open('AllPrintings.json')),
	('https://mtgjson.com/api/v5/AllPrintings.json', lambda: open, lambda f: f),
]

def determine_best_file_format():
	for url, loader_factory, member_loader in URLS:
		try:
			loader = loader_factory()

			filename = os.path.basename(urllib.parse.urlparse(url).path)

			def read_mtgjson():
				with loader(filename) as f:
					return json.load(member_loader(f))

			return url, filename, read_mtgjson
		except ImportError:
			continue
	else:
		raise Exception("failed to discover a working file format")
URL, ZIP_FILENAME, read_mtgjson = determine_best_file_format()

def main():
	force_run = False
	progress = False
	if '-f' in sys.argv:
		sys.argv.remove('-f')
		force_run = True
	if '-p' in sys.argv:
		sys.argv.remove('-p')
		progress = True
	if not http.download_file(URL, ZIP_FILENAME, True) and not os.access(EXTRAS_FILENAME, os.F_OK) and not force_run:
		print("No new version of mtgjson data file")
		return

	print("Reading card data...")
	mtgjson = read_mtgjson()['data']

	try:
		with open(EXTRAS_FILENAME) as fp:
			extracards = json.load(fp)
	except IOError:
		pass
	else:
		mtgjson.update(extracards)
		del extracards

	print("Processing...")

	processed_cards = {}

	# Use raw `psycopg2` because in this case SQLAlchemy has significant overhead (about 60% of the total script runtime)
	# without much of a benefit.
	with psycopg2.connect(config['postgres']) as conn, conn.cursor() as cur:
		cur.execute("DELETE FROM cards WHERE game = %s", (CARD_GAME_MTG, ))
		processed_multiverseids = set()
		for setid, expansion in sorted(mtgjson.items(), key=lambda e: e[1]['releaseDate'], reverse=True):
			# Allow only importing individual sets for faster testing
			if len(sys.argv) > 1 and setid not in sys.argv[1:]:
				continue

			if progress:
				print("[%s]: %s - %s" % (expansion['releaseDate'], setid, expansion['name']))

			for filteredname, cardname, description, multiverseids, hidden in process_set(setid, expansion):
				if filteredname not in processed_cards:
					cur.execute("INSERT INTO cards (game, filteredname, name, text, hidden) VALUES (%s, %s, %s, %s, %s) RETURNING id", (
						CARD_GAME_MTG,
						filteredname,
						cardname,
						description,
						hidden,
					))
					card_id, = cur.fetchone()
					processed_cards[filteredname] = card_id
				else:
					card_id = processed_cards[filteredname]

				multiverseids = set(multiverseids) - processed_multiverseids
				if multiverseids:
					cur.executemany("INSERT INTO card_codes (code, cardid, game) VALUES (%s, %s, %s)", [
						(id, card_id, CARD_GAME_MTG)
						for id in multiverseids
					])
					processed_multiverseids.update(multiverseids)

re_check = re.compile(r"^[a-z0-9_]*$")
re_mana = re.compile(r"\{(.)\}")
re_newlines = re.compile(r"[\r\n]+")
re_multiplespaces = re.compile(r"\s{2,}")
re_remindertext = re.compile(r"( *)\([^()]*\)( *)")
re_minuses = re.compile(r"(?:^|(?<=[\s/]))-(?=[\dXY])")
def process_card(card, expansion, include_reminder=False):
	if not patch_card(card, expansion):
		return
	if card['layout'] in ('token', ):  # don't care about these special cards for now
		return
	# Temporary bugfix for https://github.com/mtgjson/mtgjson/issues/933
	if card['layout'] == 'modal_dfc' and 'otherFaceIds' not in card:
		print("Warning: No otherFaceIds for %s [%s] %s" % (card['name'], expansion['code'], card['uuid']))
		return
	if card.get('layout') in ('split', 'aftermath', 'adventure'):
		# Return split cards as a single card... for all the other pieces, return nothing
		if card['side'] != 'a':
			return
		splits = [card]
		for faceid in card['otherFaceIds']:
			if faceid not in expansion['by_uuid']:
				print("Can't find split card piece: %s" % faceid)
				sys.exit(1)
			splits.append(expansion['by_uuid'][faceid])
		filteredparts = []
		nameparts = []
		descparts = []
		allmultiverseids = []
		anyhidden = False
		for s in splits:
			filtered, name, desc, multiverseids, hidden = process_single_card(s, expansion, include_reminder)
			filteredparts.append(filtered)
			nameparts.append(name)
			descparts.append(desc)
			allmultiverseids.extend(multiverseids)
			anyhidden = anyhidden or hidden

		filteredname = ''.join(filteredparts)
		cardname = " // ".join(nameparts)
		description = "%s | %s" % (card['name'], " // ".join(descparts))
		yield filteredname, cardname, description, allmultiverseids, anyhidden
	else:
		yield process_single_card(card, expansion, include_reminder)

def try_process_card(card, expansion, include_reminder=False):
	try:
		yield from process_card(card, expansion, include_reminder)
	except:
		print("Error processing card %s [%s] %s" % (card['name'], expansion['code'], card['uuid']))
		raise

def patch_card(card, expansion):
	"""Temporary fixes for issues in mtgjson data.

	Remember to also report these upstream."""
	return True

def process_single_card(card, expansion, include_reminder=False):
	# sanitise card name
	cardname = card.get('faceName', card['name'])
	filtered = clean_text(card.get('internalname', cardname))
	if not re_check.match(filtered):
		print("Still some junk left in name %s (%s)" % (card.get('internalname', cardname), json.dumps(filtered)))
		print(json.dumps(card))
		sys.exit(1)

	def build_description():
		yield cardname
		if 'manaCost' in card:
			yield ' ['
			yield re_mana.sub(r"\1", card['manaCost'])
			yield ']'
		if card.get('layout') == 'flip':
			if card['side'] == 'a':
				yield ' (flip: '
			else:
				yield ' (unflip: '
			yield expansion['by_uuid'][card['otherFaceIds'][0]]['faceName']
			yield ')'
		elif card.get('layout') in {'transform', 'modal_dfc'}:
			if card['side'] == 'a':
				yield ' (back: '
			else:
				yield ' (front: '
			yield expansion['by_uuid'][card['otherFaceIds'][0]]['faceName']
			yield ')'
		elif card.get('layout') == 'meld':
			# otherFaceIds on front faces points only to the back face
			# otherFaceIds on the back face points to both front faces
			if card['side'] == 'a':
				melded_card = expansion['by_uuid'][card['otherFaceIds'][0]]
			else:
				melded_card = card
			card_a = expansion['by_uuid'][melded_card['otherFaceIds'][0]]
			card_b = expansion['by_uuid'][melded_card['otherFaceIds'][1]]
			if card['side'] == 'a':
				# mtgjson is inconsistent as to which of these is which
				# check if "melds with cardname" is in the card text
				if card is card_a:
					other_card = card_b
				else:
					other_card = card_a
				if '(Melds with %s.)' % other_card['faceName'] in card['text']:
					yield ' (melds with: '
					yield other_card['faceName']
					yield '; into: '
					yield melded_card['faceName']
					yield ')'
				else:
					# The names of what this melds with and into are in the rules text
					pass
			elif card is melded_card:
				yield ' (melds from: '
				yield card_a['faceName']
				yield '; '
				yield card_b['faceName']
				yield ')'
		yield ' | '
		yield card.get('type', '?Type missing?')
		if 'power' in card or 'toughness' in card:
			yield ' ['
			yield shownum(card.get('power', '?'))
			yield '/'
			yield shownum(card.get('toughness', '?'))
			yield ']'
		if 'defense' in card:
			yield ' ['
			yield str(card['defense'])
			yield ']'
		if 'loyalty' in card:
			yield ' ['
			yield str(card['loyalty'])
			yield ']'
		if 'hand' in card or 'life' in card:
			yield ' [hand: '
			if 'hand' in card:
				yield card['hand']
			else:
				yield "?"
			yield ', life: '
			if 'life' in card:
				yield card['life']
			else:
				yield "?"
			yield ']'
		if 'text' in card:
			yield ' | '
			yield process_text(card['text'], include_reminder)

	desc = ''.join(build_description())
	desc = re_multiplespaces.sub(' ', desc).strip()
	desc = utils.trim_length(desc)

	if card.get('layout') == 'flip' and card['side'] != 'a':
		multiverseids = []
	else:
		if card.get('layout') in {'transform', 'modal_dfc'}:
			if card['side'] == 'b':
				card['foreignData'] = []  # mtgjson doesn't seem to have accurate foreign multiverse ids for back faces
		multiverseids = [card['identifiers']['multiverseId']] if card.get('identifiers', {}).get('multiverseId') else []
		# disabling adding foreign multiverse ids unless we decide we want them for some reason
		# they add a lot of time to the running of this script
		#for lang in card.get('foreignData', []):
		#	if lang.get('multiverseId'):
		#		multiverseids.append(lang['multiverseId'])
	hidden = 'internalname' in card

	return filtered, cardname, desc, multiverseids, hidden

def process_text(text, include_reminder):
	text = re_minuses.sub('\u2212', text) # replace hyphens with real minus signs
	# Let Un-set cards keep their reminder text, since there's joeks in there
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

def process_set(setid, expansion):
	expansion['by_uuid'] = {
		card['uuid']: card
		for card in expansion['cards']
		if card.get('uuid')
	}

	handler = SPECIAL_SETS.get(setid, process_set_general)
	yield from handler(expansion)

def process_set_general(expansion):
	for card in expansion['cards']:
		yield from try_process_card(card, expansion)

@special_set('AKH')
@special_set('HOU')
def process_set_amonkhet(expansion):
	for card in expansion['cards']:
		yield from try_process_card(card, expansion)

		if {'Embalm', 'Eternalize'}.intersection(card.get('keywords', [])):
			card['internalname'] = card['name'] + "_TKN"
			card['name'] = card['name'] + " token"
			card['subtypes'] = ["Zombie"] + card['subtypes']
			make_type(card)
			del card['manaCost']
			del card['number']
			del card['identifiers']
			del card['foreignData']
			if "Eternalize" in card['keywords']:
				card['power'] = card['toughness'] = '4'
			yield from try_process_card(card, expansion)

@special_set('UGL')
def process_set_unglued(expansion):
	for card in expansion['cards']:
		if card['name'] in {'B.F.M. (Big Furry Monster)', 'B.F.M. (Big Furry Monster) (b)'}:  # do this card special
			continue
		yield from try_process_card(card, expansion, include_reminder=True)

	yield (
		"bfmbigfurrymonster",
		"B.F.M. (Big Furry Monster)",
		"B.F.M. (Big Furry Monster) (BBBBBBBBBBBBBBB) | Creature \u2014 The Biggest, Baddest, Nastiest, Scariest Creature You'll Ever See [99/99] | You must cast both B.F.M. cards to put B.F.M. onto the battlefield. If one B.F.M. card leaves the battlefield, sacrifice the other. / B.F.M. can’t be blocked except by three or more creatures.",
		[9780, 9844],
		False,
	)

@special_set('UNH')
def process_set_unhinged(expansion):
	for card in expansion['cards']:
		yield from try_process_card(card, expansion, include_reminder=True)

@special_set('UST')
@special_set('UND')
def process_set_unstable(expansion):
	hosts = []
	augments = []
	for card in expansion['cards']:
		yield from try_process_card(card, expansion, include_reminder=True)

		if card['layout'] == 'host':
			hosts.append(card)
			# for the benefit of the overlay
			card['internalname'] = card['name'] + "_HOST"
			card.pop('identifiers', None)
			card.pop('number', None)
			yield from try_process_card(card, expansion, include_reminder=True)
		elif card['layout'] == 'augment':
			augments.append(card)
			card['internalname'] = card['name'] + "_AUG"
			card.pop('identifiers', None)
			card.pop('number', None)
			yield from try_process_card(card, expansion, include_reminder=True)

	for augment in augments:
		for host in hosts:
			yield gen_augment(augment, host, expansion)

HOST_PREFIX = "When this creature enters,"
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

	combined['supertypes'] = [i for i in host.get('supertypes', []) if i != 'Host'] + augment.get('supertypes', [])
	combined['types'] = [i for i in host['types'] if i != 'Creature'] + augment['types']
	combined['subtypes'] = augment['subtypes'] + host['subtypes']
	make_type(combined)

	host_lines = host['text'].split("\n")
	for host_ix, host_line in enumerate(host_lines):
		if host_line.startswith(HOST_PREFIX):
			break
	else:
		raise ValueError("Card text for host %r not expected" % host['name'])
	host_line = host_line[len(HOST_PREFIX):].strip()
	if host_line:
		del host_lines[host_ix]
	else:
		# for some cards, the text is formatted as:
		#   "When this creature ETB, effect"
		# but for others it's formatted as:
		#   "When this creature ETB,\neffect"
		# for the latter, host_line will be empty at this point, and we need to grab
		# the following line
		host_line = host_lines[host_ix + 1]
		del host_lines[host_ix:host_ix + 2]

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

	# don't include reminder text on the merged augment - the main reminder text
	# on these cards is the reminder for Augment, which isn't relevent any more
	return process_single_card(combined, expansion, include_reminder=False)

def make_type(card):
	types = card['types']
	if card.get('supertypes'):
		types = card['supertypes'] + types
	if card.get('subtypes'):
		types = types + ["\u2014"] + card['subtypes']
	typeline = ' '.join(types)
	card['type'] = typeline
	return typeline

def shownum(val):
	# mtgjson gives the power/toughness of Unhinged cards as eg "3.5" rather than "3½"
	# but it uses the "½" symbol in the rules text, so fix it here to match
	if val.endswith('.5'):
		val = val[:-2] + '½'
	return val

if __name__ == '__main__':
	main()
