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

from common import utils
import common.postgres
from lrrbot.commands.card import clean_text

URL = 'http://mtgjson.com/json/AllSets.json.zip'
ZIP_FILENAME = 'AllSets.json.zip'
SOURCE_FILENAME = 'AllSets.json'
MAXLEN = 450

@common.postgres.with_postgres_transaction
def main(conn, cur):
	if not do_download_file(URL, ZIP_FILENAME):
		print("No new version of mtgjson data file")
		return

	print("Reading card data...")
	with zipfile.ZipFile(ZIP_FILENAME) as zfp:
		fp = io.TextIOWrapper(zfp.open(SOURCE_FILENAME))
		mtgjson = json.load(fp)

	print("Processing...")
	cur.execute("DELETE FROM card_multiverse")
	cur.execute("DELETE FROM cards")
	cardid = 0
	for expansion in mtgjson.values():
		release_date = dateutil.parser.parse(expansion['releaseDate']).date()
		for card in expansion['cards']:
			cardid += 1
			if card['layout'] in ('token', 'plane', 'scheme', 'phenomenon', 'vanguard'):  # don't care about these special cards for now
				continue
			if card['name'] == 'B.F.M. (Big Furry Monster)':  # do this card special
				continue

			cardname, description, multiverseids = process_card(card, expansion)
			if description is None:
				continue

			# Check if there's already a row for this card in the DB
			# (keep the one with the latest release date - it's more likely to have the accurate text in mtgjson)
			cur.execute("SELECT cardid, lastprinted FROM cards WHERE filteredname = %s", (cardname,))
			rows = cur.fetchall()
			if not rows:
				real_cardid = cardid
				cur.execute(
					"INSERT INTO cards(cardid, filteredname, name, text, lastprinted) VALUES (%s,%s,%s,%s,%s)",
					(real_cardid, cardname, card['name'], description, release_date))
			elif rows[0][1] < release_date:
				real_cardid = rows[0][0]
				cur.execute(
					"UPDATE cards SET name = %s, text = %s, lastprinted = %s where cardid = %s",
					(card['name'], description, release_date, real_cardid))
			else:
				real_cardid = rows[0][0]

			for mid in multiverseids:
				cur.execute("SELECT cardid FROM card_multiverse WHERE multiverseid = %s", (mid,))
				rows = cur.fetchall()
				if not rows:
					cur.execute(
						"INSERT INTO card_multiverse(multiverseid, cardid) VALUES (%s,%s)",
						(mid, real_cardid))
				elif rows[0][0] != real_cardid:
					cur.execute("SELECT name FROM cards WHERE cardid = %s", (rows[0][0],))
					rows2 = cur.fetchall()
					print("Different names for multiverseid %d: \"%s\" and \"%s\"" % (mid, card['name'], rows2[0][0]))
					print(card['layout'])

	cardid += 1
	cur.execute(
		"INSERT INTO cards(cardid, filteredname, name, text, lastprinted) VALUES (%s,%s,%s,%s,%s)",
		(cardid, "bfmbigfurrymonster", "B.F.M. (Big Furry Monster)", "B.F.M. (Big Furry Monster) (BBBBBBBBBBBBBBB) | Summon \u2014 The Biggest, Baddest, Nastiest, Scariest Creature You'll Ever See [99/99] | You must play both B.F.M. cards to put B.F.M. into play. If either B.F.M. card leaves play, sacrifice the other. / B.F.M. can only be blocked by three or more creatures.", datetime.date(1998, 8, 11)))
	cur.execute(
		"INSERT INTO card_multiverse(multiverseid, cardid) VALUES (%s,%s)",
		(9780, cardid))
	cur.execute(
		"INSERT INTO card_multiverse(multiverseid, cardid) VALUES (%s,%s)",
		(9844, cardid))

def do_download_file(url, fn):
	"""
	Download a file, checking that there is a new version of the file on the
	server before doing so. Returns True if a download occurs.
	"""
	# Much of this code cribbed from urllib.request.urlretrieve, with If-Modified-Since logic added

	req = urllib.request.Request(url)
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
			return None, None, None
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
		if card.get('layout') == 'double-faced':
			if card['name'] == card['names'][0]:
				yield ' (back: '
				yield card['names'][1]
				yield ')'
			else:
				yield ' (front: '
				yield card['names'][0]
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
			yield re_newlines.sub(' / ', re_remindertext.sub('', card['text']))

	desc = ''.join(build_description())
	desc = re_multiplespaces.sub(' ', desc).strip()
	if len(desc) > MAXLEN:
		desc = desc[:MAXLEN-1] + "\u2026"

	return name, desc, multiverseids

if __name__ == '__main__':
	main()
