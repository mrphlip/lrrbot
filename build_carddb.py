#!/usr/bin/env python3
"""
This script downloads the latest MTG card data from http://mtgjson.com/ and processes
it to turn the highly-structured data there into a flat list of card names to descriptions
formatted to send down the chat.
"""

import sys
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

engine, metadata = common.postgres.new_engine_and_metadata()

def main():
	if not do_download_file(URL, ZIP_FILENAME) and not os.access(EXTRAS_FILENAME, os.F_OK):
		print("No new version of mtgjson data file")
		return

	print("Reading card data...")
	with zipfile.ZipFile(ZIP_FILENAME) as zfp:
		fp = io.TextIOWrapper(zfp.open(SOURCE_FILENAME))
		mtgjson = json.load(fp)

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
			release_date = dateutil.parser.parse(expansion.get('releaseDate', '1970-01-01')).date()
			for card in expansion['cards']:
				cardid += 1
				if card['layout'] in ('token', 'plane', 'scheme', 'phenomenon', 'vanguard'):  # don't care about these special cards for now
					continue
				if card['name'] == 'B.F.M. (Big Furry Monster)':  # do this card special
					continue

				cardname, description, multiverseids, collector = process_card(card, expansion)
				if description is None:
					continue

				# Check if there's already a row for this card in the DB
				# (keep the one with the latest release date - it's more likely to have the accurate text in mtgjson)
				rows = conn.execute(sqlalchemy.select([cards.c.id, cards.c.lastprinted])
					.where(cards.c.filteredname == cardname)).fetchall()
				if not rows:
					real_cardid = cardid
					conn.execute(cards.insert(),
						id=real_cardid,
						filteredname=cardname,
						name=card['name'],
						text=description,
						lastprinted=release_date,
					)
				elif rows[0][1] < release_date:
					real_cardid = rows[0][0]
					conn.execute(cards.update().where(cards.c.id == real_cardid),
						name=card["name"],
						text=description,
						lastprinted=release_date,
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
					elif rows[0][0] != real_cardid:
						rows2 = conn.execute(sqlalchemy.select([cards.c.name]).where(cards.c.id == rows[0][0])).fetchall()
						print("Different names for multiverseid %d: \"%s\" and \"%s\"" % (mid, card['name'], rows2[0][0]))

				if collector:
					rows = conn.execute(sqlalchemy.select([card_collector.c.cardid])
						.where((card_collector.c.setid == setid) & (card_collector.c.collector == collector))).fetchall()
					if not rows:
						conn.execute(card_collector.insert(),
							setid=setid,
							collector=collector,
							cardid=real_cardid,
						)
					elif rows[0][0] != real_cardid:
						rows2 = conn.execute(sqlalchemy.select([cards.c.name]).where(cards.c.id == rows[0][0])).fetchall()
						print("Different names for set %s collector number %s: \"%s\" and \"%s\"" % (setid, collector, card['name'], rows2[0][0]))

		cardid += 1
		conn.execute(cards.insert(),
			id=cardid,
			filteredname="bfmbigfurrymonster",
			name="B.F.M. (Big Furry Monster)""B.F.M. (Big Furry Monster)",
			text="B.F.M. (Big Furry Monster) (BBBBBBBBBBBBBBB) | Summon \u2014 The Biggest, Baddest, Nastiest, Scariest Creature You'll Ever See [99/99] | You must play both B.F.M. cards to put B.F.M. into play. If either B.F.M. card leaves play, sacrifice the other. / B.F.M. can only be blocked by three or more creatures.",
			lastprinted=datetime.date(1998, 8, 11),
		)
		conn.execute(card_multiverse.insert(), [
			{"id": 9780, "cardid": cardid},
			{"id": 9844, "cardid": cardid},
		])
		conn.execute(card_collector.insert(), [
			{"setid": "UGL", "collector": "28", "cardid": cardid},
			{"setid": "UGL", "collector": "29", "cardid": cardid},
		])

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
re_remindertext = re.compile(r"\([^()]*\)")
def process_card(card, expansion):
	if card.get('layout') == 'split':
		# Return split cards as a single card... for all the other pieces, return nothing
		if card['name'] != card['names'][0]:
			return None, None, None, None
		splits = []
		for splitname in card['names']:
			candidates = [i for i in expansion['cards'] if i['name'] == splitname]
			if not candidates:
				print("Can't find split card piece: %s" % splitname)
				sys.exit(1)
			splits.append(candidates[0])
		card = {}
		card['name'] = ' // '.join(s['name'] for s in splits)
		card['manaCost'] = ' // '.join(s['manaCost'] for s in splits)
		card['type'] = splits[0]['type'] # should be the same for all splits
		card['text'] = ' // '.join(s['text'] for s in splits)
		multiverseids = [s['multiverseid'] for s in splits if s.get('multiverseid')]
	elif card.get('layout') == 'flip':
		if card['name'] == card['names'][0] and card.get('multiverseid'):
			multiverseids = [card['multiverseid']]
		else:
			multiverseids = []
	else:
		if card.get('multiverseid'):
			multiverseids = [card['multiverseid']]
		else:
			multiverseids = []

	# sanitise card name
	name = clean_text(card["name"])
	if not re_check.match(name):
		print("Still some junk left in name %s (%s)" % (card['name'], json.dumps(name)))
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
			if card['name'] == card['names'][0]:
				# The names of what this melds with and into are in the card text
				pass
			elif card['name'] == card['names'][1]:
				yield ' (melds with: '
				yield card['names'][0]
				yield '; into: '
				yield card['names'][2]
				yield ')'
			elif card['name'] == card['names'][2]:
				yield ' (melds from: '
				yield card['names'][0]
				yield '; '
				yield card['names'][1]
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
			yield re_newlines.sub(' / ', re_remindertext.sub('', card['text']).strip())

	desc = ''.join(build_description())
	desc = re_multiplespaces.sub(' ', desc).strip()
	if len(desc) > MAXLEN:
		desc = desc[:MAXLEN-1] + "\u2026"

	return name, desc, multiverseids, card.get('number')

if __name__ == '__main__':
	main()
