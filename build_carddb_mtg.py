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
import contextlib
import time
import json
import re
import dateutil.parser
import psycopg2

from common import utils
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
	if not do_download_file(URL, ZIP_FILENAME) and not os.access(EXTRAS_FILENAME, os.F_OK) and not force_run:
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
		for setid, expansion in sorted(mtgjson.items(), key=lambda e: e[1]['releaseDate'], reverse=True):
			# Allow only importing individual sets for faster testing
			if len(sys.argv) > 1 and setid not in sys.argv[1:]:
				continue

			if progress:
				print("[%s]: %s - %s" % (expansion['releaseDate'], setid, expansion['name']))

			processed_multiverseids = set()

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
					cur.executemany("INSERT INTO card_multiverse (id, cardid) VALUES (%s, %s)", [
						(id, card_id)
						for id in multiverseids
					])
					processed_multiverseids.update(multiverseids)

def do_download_file(url, fn):
	"""
	Download a file, checking that there is a new version of the file on the
	server before doing so. Returns True if a download occurs.
	"""
	# Much of this code cribbed from urllib.request.urlretrieve, with If-Modified-Since logic added

	req = urllib.request.Request(url, headers={
		'User-Agent': "LRRbot/2.0 (https://lrrbot.com/)",
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
re_minuses = re.compile(r"(?:^|(?<=[\s/]))-(?=[\dXY])")
def process_card(card, expansion, include_reminder=False):
	if not patch_card(card, expansion):
		return
	if card['layout'] in ('token', ):  # don't care about these special cards for now
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

MISSING_OTHER_FACEID = {
	# aftermath: Mouth // Feed (AKH, normal)
	'6298d70e-4ecc-5cff-9221-aeb532c33e6a': 'e765058a-4a7c-513f-bb97-cb7d3aa56218',
	'e765058a-4a7c-513f-bb97-cb7d3aa56218': '6298d70e-4ecc-5cff-9221-aeb532c33e6a',
	# aftermath: Never // Return (AKH, normal)
	'875ba98c-721c-537b-b326-22d803fab7c0': '6acc8501-aa59-5777-a7d0-e3ef66a609ea',
	'6acc8501-aa59-5777-a7d0-e3ef66a609ea': '875ba98c-721c-537b-b326-22d803fab7c0',
	# aftermath: Start // Finish (AKH, normal)
	'17100b0d-3b74-5329-a832-dfad07d5c35b': '93de0571-9509-5933-b298-2660f5f97f7d',
	'93de0571-9509-5933-b298-2660f5f97f7d': '17100b0d-3b74-5329-a832-dfad07d5c35b',
	# flip: Budoka Gardener // Dokai, Weaver of Life (C18, normal)
	'd5f5bb29-5f35-56a5-a707-67ace1b9d22a': '5b9682b4-a2e6-586c-b479-6508264d992e',
	'5b9682b4-a2e6-586c-b479-6508264d992e': 'd5f5bb29-5f35-56a5-a707-67ace1b9d22a',
	# split: Incubation // Incongruity (C21, normal)
	'6d4a2767-3adb-5aaa-bb4a-43f1af57a205': 'cce7b490-8a6d-5224-a6f7-cb6a34e17acb',
	'cce7b490-8a6d-5224-a6f7-cb6a34e17acb': '6d4a2767-3adb-5aaa-bb4a-43f1af57a205',
	# adventure: Curious Pair // Treats to Share (ELD, normal)
	'5093bb6a-f20e-5079-b4d7-e7422d7601cb': '27045496-fb07-5260-8201-c98491e6ee31',
	'27045496-fb07-5260-8201-c98491e6ee31': '5093bb6a-f20e-5079-b4d7-e7422d7601cb',
	# adventure: Curious Pair // Treats to Share (ELD, showcase)
	'56933d43-1a1f-58ce-8c7b-557def831b83': '5e6369c8-d8c5-5877-8a26-6f7f5b021c09',
	'5e6369c8-d8c5-5877-8a26-6f7f5b021c09': '56933d43-1a1f-58ce-8c7b-557def831b83',
	# adventure: Flaxen Intruder // Welcome Home (ELD, normal)
	'136a943f-a2c0-5f1f-b6d3-5a55b3ad76c8': '8288d260-50a7-5c4d-a3fa-3855c5ec54fa',
	'8288d260-50a7-5c4d-a3fa-3855c5ec54fa': '136a943f-a2c0-5f1f-b6d3-5a55b3ad76c8',
	# adventure: Flaxen Intruder // Welcome Home (ELD, showcase)
	'73562a88-c8d7-5bd3-abc2-2c7961a5c634': '7938d306-5ffd-59fe-afdf-4360f7ca1316',
	'7938d306-5ffd-59fe-afdf-4360f7ca1316': '73562a88-c8d7-5bd3-abc2-2c7961a5c634',
	# adventure: Lonesome Unicorn // Rider in Need (ELD, normal)
	'5c7667ca-4006-532b-a8b5-eb9dcdd841f0': '56effca8-14d7-5489-8bf6-e308c1314c64',
	'56effca8-14d7-5489-8bf6-e308c1314c64': '5c7667ca-4006-532b-a8b5-eb9dcdd841f0',
	# adventure: Lonesome Unicorn // Rider in Need (ELD, showcase)
	'fef06068-703b-5c3d-8d91-b7e73c7b2f8a': '643ce08b-0dd1-59cb-a498-8a59da0bd5b0',
	'643ce08b-0dd1-59cb-a498-8a59da0bd5b0': 'fef06068-703b-5c3d-8d91-b7e73c7b2f8a',
	# adventure: Lovestruck Beast // Heart's Desire (ELD, normal)
	'89fd5608-1ece-5c6f-8428-828d599b9cad': '3a4b9941-f695-5a5d-9b46-990a967f2eba',
	'3a4b9941-f695-5a5d-9b46-990a967f2eba': '89fd5608-1ece-5c6f-8428-828d599b9cad',
	# adventure: Lovestruck Beast // Heart's Desire (ELD, showcase)
	'808aab9f-f353-598e-ae86-0099ad7b0da4': '55214f09-66df-5578-901e-56ca36ee5102',
	'55214f09-66df-5578-901e-56ca36ee5102': '808aab9f-f353-598e-ae86-0099ad7b0da4',
	# adventure: Oakhame Ranger // Bring Back (ELD, normal)
	'1945c138-c3fb-50cd-91f1-f9f92571365a': '1503d4db-926c-5fec-8a74-e6780d863683',
	'1503d4db-926c-5fec-8a74-e6780d863683': '1945c138-c3fb-50cd-91f1-f9f92571365a',
	# adventure: Oakhame Ranger // Bring Back (ELD, showcase)
	'08f5c431-3da6-5cd9-b633-27c84fe7150d': '2531e40e-3271-500e-ab5e-ed12df3588e0',
	'2531e40e-3271-500e-ab5e-ed12df3588e0': '08f5c431-3da6-5cd9-b633-27c84fe7150d',
	# transform: Docent of Perfection // Final Iteration (EMN, normal)
	'321ceb85-30d5-5e14-8a42-15136755080e': 'f5fd28b8-2ca9-5b9c-809e-b683b36f6295',
	'f5fd28b8-2ca9-5b9c-809e-b683b36f6295': '321ceb85-30d5-5e14-8a42-15136755080e',
	# transform: Extricator of Sin // Extricator of Flesh (EMN, normal)
	'5bd2cbe8-89c4-5742-9abf-23a40cb84d3d': 'e141f315-d86b-54dc-a5a3-ce4ba65395d3',
	'e141f315-d86b-54dc-a5a3-ce4ba65395d3': '5bd2cbe8-89c4-5742-9abf-23a40cb84d3d',
	# transform: Shrill Howler // Howling Chorus (EMN, normal)
	'1789cc6e-381d-5c70-9639-0a52b3123942': '77010854-7200-586c-b4d5-e6e0e069520f',
	'77010854-7200-586c-b4d5-e6e0e069520f': '1789cc6e-381d-5c70-9639-0a52b3123942',
	# split: Assure // Assemble (GRN, normal)
	'30151a21-89a0-5e95-9c50-18569875cdab': '67adb8d5-8077-5222-a0b5-e1e37ec7507a',
	'67adb8d5-8077-5222-a0b5-e1e37ec7507a': '30151a21-89a0-5e95-9c50-18569875cdab',
	# transform: Bloodline Keeper // Lord of Lineage (ISD, normal)
	'1c12ea60-ce46-594e-a588-cfe5b2ef44b1': '27453e61-7297-57fb-b0fe-e43557e96607',
	'27453e61-7297-57fb-b0fe-e43557e96607': '1c12ea60-ce46-594e-a588-cfe5b2ef44b1',
	# transform: Garruk Relentless // Garruk, the Veil-Cursed (ISD, normal)
	'd4254138-884d-5c33-a2fd-a5c86ccfdf34': 'd9116cba-0917-551f-bc20-c1a15659a173',
	'd9116cba-0917-551f-bc20-c1a15659a173': 'd4254138-884d-5c33-a2fd-a5c86ccfdf34',
	# transform: Mayor of Avabruck // Howlpack Alpha (ISD, normal)
	'3d534857-3daf-558b-a0ba-f0e231db7a72': 'cd567de0-8d69-58f6-823a-7dcfe5cbc65b',
	'cd567de0-8d69-58f6-823a-7dcfe5cbc65b': '3d534857-3daf-558b-a0ba-f0e231db7a72',
	# modal_dfc: Halvar, God of Battle // Sword of the Realms (KHM, normal)
	'4d175cbb-33c1-5e06-a9a5-bfd90cac55ee': 'c87e91b0-9117-538e-800f-f8c915aaea8a',
	'c87e91b0-9117-538e-800f-f8c915aaea8a': '4d175cbb-33c1-5e06-a9a5-bfd90cac55ee',
	# modal_dfc: Halvar, God of Battle // Sword of the Realms (KHM, showcase)
	'435e9aeb-7f95-51aa-8e18-bf324fe3187d': '52b1b2b0-0e53-5c80-b62b-de28b4582171',
	'52b1b2b0-0e53-5c80-b62b-de28b4582171': '435e9aeb-7f95-51aa-8e18-bf324fe3187d',
	# modal_dfc: Valki, God of Lies // Tibalt, Cosmic Impostor (KHM, borderless)
	'987b5b69-552c-5f3a-b7af-70a700817cfc': '88be86ce-90b6-5d9d-b132-044c41baf7f1',
	'88be86ce-90b6-5d9d-b132-044c41baf7f1': '987b5b69-552c-5f3a-b7af-70a700817cfc',
	# modal_dfc: Valki, God of Lies // Tibalt, Cosmic Impostor (KHM, normal)
	'6161b207-65da-513c-b322-c6c1c75ad21a': 'cd94f98e-85bb-5eea-b1c1-5d5b39e2e9e1',
	'cd94f98e-85bb-5eea-b1c1-5d5b39e2e9e1': '6161b207-65da-513c-b322-c6c1c75ad21a',
	# modal_dfc: Valki, God of Lies // Tibalt, Cosmic Impostor (KHM, showcase)
	'7d929665-72d1-578b-b2e2-c0695f343242': '98eb886b-7695-52c2-9cc7-b7017e62d44a',
	'98eb886b-7695-52c2-9cc7-b7017e62d44a': '7d929665-72d1-578b-b2e2-c0695f343242',
	# transform: Chandra, Fire of Kaladesh // Chandra, Roaring Flame (ORI, normal)
	'86f3ab5a-ab07-57c5-9388-f04eabdfdaf1': 'eb02a93c-ff6e-5746-a9d1-e597c5716b7f',
	'eb02a93c-ff6e-5746-a9d1-e597c5716b7f': '86f3ab5a-ab07-57c5-9388-f04eabdfdaf1',
	# transform: Jace, Vryn's Prodigy // Jace, Telepath Unbound (ORI, normal)
	'd3c62c41-549f-50f1-bc7c-7613df49367c': '683653a5-c730-5764-ab7e-8d9ee1dbed51',
	'683653a5-c730-5764-ab7e-8d9ee1dbed51': 'd3c62c41-549f-50f1-bc7c-7613df49367c',
	# transform: Liliana, Heretical Healer // Liliana, Defiant Necromancer (ORI, normal)
	'63ea84ce-bca0-5eb0-861d-b82e2aaf92de': '2bd840b5-e790-56fe-9f21-32ff880c49c2',
	'2bd840b5-e790-56fe-9f21-32ff880c49c2': '63ea84ce-bca0-5eb0-861d-b82e2aaf92de',
	# transform: Nissa, Vastwood Seer // Nissa, Sage Animist (ORI, normal)
	'cc3b7e29-d14d-59dc-92ea-33f825d407cc': 'a25b5d47-1b78-50de-9c1a-11cf6453a203',
	'a25b5d47-1b78-50de-9c1a-11cf6453a203': 'cc3b7e29-d14d-59dc-92ea-33f825d407cc',
	# aftermath: Mouth // Feed (PAKH, prerelease)
	'a78a9a09-632d-548d-ade0-823111852217': '1e539461-08c7-50e2-9f0e-95837e5520af',
	'1e539461-08c7-50e2-9f0e-95837e5520af': 'a78a9a09-632d-548d-ade0-823111852217',
	# aftermath: Never // Return (PAKH, prerelease)
	'a1b829e5-25f3-5488-a0b3-d4988ed0d29c': 'be050583-8a1f-5beb-8d0d-10be6989e80e',
	'be050583-8a1f-5beb-8d0d-10be6989e80e': 'a1b829e5-25f3-5488-a0b3-d4988ed0d29c',
	# adventure: Lovestruck Beast // Heart's Desire (PELD, normal)
	'023bc9ff-4257-591f-aeb4-7b038868c2be': 'fc9d75b1-0c19-5a03-b961-ef38486e0d48',
	'fc9d75b1-0c19-5a03-b961-ef38486e0d48': '023bc9ff-4257-591f-aeb4-7b038868c2be',
	# adventure: Lovestruck Beast // Heart's Desire (PELD, prerelease)
	'64804d5c-cdba-5083-a076-2e5174ab661f': '4f4579bf-50bb-57bb-89cf-197d5a7d604b',
	'4f4579bf-50bb-57bb-89cf-197d5a7d604b': '64804d5c-cdba-5083-a076-2e5174ab661f',
	# transform: Docent of Perfection // Final Iteration (PEMN, prerelease)
	'f24f3ca0-0a08-5818-b3a1-735dbc60e3fe': 'bdccd845-f6b1-5d84-9404-044bf38ed2ed',
	'bdccd845-f6b1-5d84-9404-044bf38ed2ed': 'f24f3ca0-0a08-5818-b3a1-735dbc60e3fe',
	# split: Assure // Assemble (PGRN, prerelease)
	'2219fec0-4786-5d78-98c4-849d5a147010': 'b22b6681-655d-5df6-9bab-3c20347ada60',
	'b22b6681-655d-5df6-9bab-3c20347ada60': '2219fec0-4786-5d78-98c4-849d5a147010',
	# transform: Mayor of Avabruck // Howlpack Alpha (PISD, prerelease)
	'8c12bf70-e73a-5228-8bd0-10b5ba2f405a': 'c4c2fb26-28d4-568f-8cc6-fbba89385dd0',
	'c4c2fb26-28d4-568f-8cc6-fbba89385dd0': '8c12bf70-e73a-5228-8bd0-10b5ba2f405a',
	# modal_dfc: Halvar, God of Battle // Sword of the Realms (PKHM, prerelease)
	'b09ae70d-b9ad-5115-8e72-3edf36849455': 'a56f9f8f-8f27-5f58-ab2f-2337da6c2395',
	'a56f9f8f-8f27-5f58-ab2f-2337da6c2395': 'b09ae70d-b9ad-5115-8e72-3edf36849455',
	# modal_dfc: Valki, God of Lies // Tibalt, Cosmic Impostor (PKHM, prerelease)
	'ae02c448-f999-5854-839a-c6a576da13d8': '453e0361-d8fe-53fe-9521-a87e714e152b',
	'453e0361-d8fe-53fe-9521-a87e714e152b': 'ae02c448-f999-5854-839a-c6a576da13d8',
	# transform: Chandra, Fire of Kaladesh // Chandra, Roaring Flame (PORI, prerelease)
	'e2f960c3-6188-504b-a667-7306f68e8141': '0307053a-1496-5df6-9ae1-d92190012e9b',
	'0307053a-1496-5df6-9ae1-d92190012e9b': 'e2f960c3-6188-504b-a667-7306f68e8141',
	# transform: Jace, Vryn's Prodigy // Jace, Telepath Unbound (PORI, prerelease)
	'3cf1e1c8-cf1c-58ed-9257-71a416ec0306': '4f515287-b092-5363-a6fa-3dd950f4537c',
	'4f515287-b092-5363-a6fa-3dd950f4537c': '3cf1e1c8-cf1c-58ed-9257-71a416ec0306',
	# transform: Liliana, Heretical Healer // Liliana, Defiant Necromancer (PORI, prerelease)
	'358d5b85-ab4e-5b9c-b2d4-c2227b944996': 'b978eb4f-6fb0-5cc3-ac0c-da867d5cdf1b',
	'b978eb4f-6fb0-5cc3-ac0c-da867d5cdf1b': '358d5b85-ab4e-5b9c-b2d4-c2227b944996',
	# transform: Nissa, Vastwood Seer // Nissa, Sage Animist (PORI, prerelease)
	'12212237-7007-5d66-a518-3cfd64a9f0ff': '67b85e66-429f-55f0-9473-7cf7879694a8',
	'67b85e66-429f-55f0-9473-7cf7879694a8': '12212237-7007-5d66-a518-3cfd64a9f0ff',
	# transform: Golden Guardian // Gold-Forge Garrison (PRIX, prerelease)
	'4171458e-2850-58d3-89db-fe3573fa6674': '8addea1d-710e-5836-8743-a08dc900aa95',
	'8addea1d-710e-5836-8743-a08dc900aa95': '4171458e-2850-58d3-89db-fe3573fa6674',
	# transform: Arlinn Kord // Arlinn, Embraced by the Moon (PSOI, prerelease)
	'95edfd06-e15a-5c43-9fc6-340262bfca8c': 'b3acc7e3-89c7-5b38-937a-a3d832a01bf9',
	'b3acc7e3-89c7-5b38-937a-a3d832a01bf9': '95edfd06-e15a-5c43-9fc6-340262bfca8c',
	# transform: Hanweir Militia Captain // Westvale Cult Leader (PSOI, prerelease)
	'd780327b-e424-50e0-a8a0-aa00f9fab7d7': 'dacc4e1a-aac0-5e17-b02d-7dae9f27ca66',
	'dacc4e1a-aac0-5e17-b02d-7dae9f27ca66': 'd780327b-e424-50e0-a8a0-aa00f9fab7d7',
	# transform: Westvale Abbey // Ormendahl, Profane Prince (PSOI, prerelease)
	'c4ab6e8b-7acd-5bb3-8ed2-69120846072b': '788ed66c-8567-5133-93f8-4e90cecf9bd7',
	'788ed66c-8567-5133-93f8-4e90cecf9bd7': 'c4ab6e8b-7acd-5bb3-8ed2-69120846072b',
	# modal_dfc: Extus, Oriq Overlord // Awaken the Blood Avatar (PSTX, normal)
	'3af4d27c-48f8-55b4-8f67-f4070d4a86b2': '15c643b7-5e98-5f11-ad3f-049610bcc083',
	'15c643b7-5e98-5f11-ad3f-049610bcc083': '3af4d27c-48f8-55b4-8f67-f4070d4a86b2',
	# modal_dfc: Extus, Oriq Overlord // Awaken the Blood Avatar (PSTX, prerelease)
	'b4c64240-d29d-5201-b91c-2ff9fd34c580': '6583c0ca-ca63-5fee-ad7b-e49d2e3ff232',
	'6583c0ca-ca63-5fee-ad7b-e49d2e3ff232': 'b4c64240-d29d-5201-b91c-2ff9fd34c580',
	# modal_dfc: Kianne, Dean of Substance // Imbraham, Dean of Theory (PSTX, normal)
	'2c41094b-6367-51c8-8e01-baf7e9e59d02': '761b7ea0-717d-5e31-8fd7-e1896fa4a21f',
	'761b7ea0-717d-5e31-8fd7-e1896fa4a21f': '2c41094b-6367-51c8-8e01-baf7e9e59d02',
	# modal_dfc: Kianne, Dean of Substance // Imbraham, Dean of Theory (PSTX, prerelease)
	'b8a2c6d5-4474-52ae-a105-d4bae84df200': 'bfa59551-333c-54ba-a9c8-a69d288bc73d',
	'bfa59551-333c-54ba-a9c8-a69d288bc73d': 'b8a2c6d5-4474-52ae-a105-d4bae84df200',
	# modal_dfc: Mila, Crafty Companion // Lukka, Wayward Bonder (PSTX, normal)
	'4ce3183a-6a64-5531-8188-4b0c255c59fd': 'f617e3cb-387d-553c-ac8b-e1d27c49f603',
	'f617e3cb-387d-553c-ac8b-e1d27c49f603': '4ce3183a-6a64-5531-8188-4b0c255c59fd',
	# modal_dfc: Mila, Crafty Companion // Lukka, Wayward Bonder (PSTX, prerelease)
	'cd38f1f0-aee1-5bc4-b455-0f64471c18a1': '9a490ab1-1112-5481-9351-6e2fee9a76a3',
	'9a490ab1-1112-5481-9351-6e2fee9a76a3': 'cd38f1f0-aee1-5bc4-b455-0f64471c18a1',
	# modal_dfc: Pestilent Cauldron // Restorative Burst (PSTX, normal)
	'c2107496-9250-55d6-8806-41a81fdc5b6a': 'f06ff62f-175d-559f-ad92-71ceea1e281e',
	'f06ff62f-175d-559f-ad92-71ceea1e281e': 'c2107496-9250-55d6-8806-41a81fdc5b6a',
	# modal_dfc: Pestilent Cauldron // Restorative Burst (PSTX, prerelease)
	'684e6c27-60e2-564f-bb8e-4206973bbad5': 'ca181d51-814e-5d7a-aaf2-a82f29e39804',
	'ca181d51-814e-5d7a-aaf2-a82f29e39804': '684e6c27-60e2-564f-bb8e-4206973bbad5',
	# modal_dfc: Rowan, Scholar of Sparks // Will, Scholar of Frost (PSTX, normal)
	'f270bcd2-64d7-559a-af72-336f4fb3745a': '6b8af415-1d76-5855-8a20-ef9e859fcbfc',
	'6b8af415-1d76-5855-8a20-ef9e859fcbfc': 'f270bcd2-64d7-559a-af72-336f4fb3745a',
	# modal_dfc: Rowan, Scholar of Sparks // Will, Scholar of Frost (PSTX, prerelease)
	'15f850cb-3278-5ca8-a2d8-5b512ae44cde': '8a458a3b-8ec4-5759-a396-0628fd0a6b46',
	'8a458a3b-8ec4-5759-a396-0628fd0a6b46': '15f850cb-3278-5ca8-a2d8-5b512ae44cde',
	# modal_dfc: Valentin, Dean of the Vein // Lisette, Dean of the Root (PSTX, normal)
	'62d7a581-00a8-55c0-a828-8ff3db9be8e2': '44bba0d2-5761-57fc-9efb-2c85139397ba',
	'44bba0d2-5761-57fc-9efb-2c85139397ba': '62d7a581-00a8-55c0-a828-8ff3db9be8e2',
	# modal_dfc: Valentin, Dean of the Vein // Lisette, Dean of the Root (PSTX, prerelease)
	'b3f79135-6dff-54b3-b511-2fa388411077': 'f505469a-dff1-59f6-ac96-2f65b706aa20',
	'f505469a-dff1-59f6-ac96-2f65b706aa20': 'b3f79135-6dff-54b3-b511-2fa388411077',
	# transform: Dowsing Dagger // Lost Vale (PXLN, prerelease)
	'425f0d68-b1b3-5512-b574-7bbfd31107ca': '2c085a29-20ff-5d07-a0d8-550d7cdb98fe',
	'2c085a29-20ff-5d07-a0d8-550d7cdb98fe': '425f0d68-b1b3-5512-b574-7bbfd31107ca',
	# transform: Legion's Landing // Adanto, the First Fort (PXLN, prerelease)
	'a2e81a33-3aae-5713-ac67-2074f3749b63': '6be98039-cc21-55e6-ae3f-f03383904ddb',
	'6be98039-cc21-55e6-ae3f-f03383904ddb': 'a2e81a33-3aae-5713-ac67-2074f3749b63',
	# transform: Treasure Map // Treasure Cove (PXLN, prerelease)
	'a6ca33d4-4bb1-5acf-9f6f-91602ffc6ebf': '46555873-2ef0-537c-bebe-c01b1fb4bd72',
	'46555873-2ef0-537c-bebe-c01b1fb4bd72': 'a6ca33d4-4bb1-5acf-9f6f-91602ffc6ebf',
	# transform: Dowsing Dagger // Lost Vale (PXTC, normal)
	'04baa88d-44a7-5549-8844-c401b1448459': 'e9a2d3bf-c356-560b-bc02-e57634c157d3',
	'e9a2d3bf-c356-560b-bc02-e57634c157d3': '04baa88d-44a7-5549-8844-c401b1448459',
	# transform: Legion's Landing // Adanto, the First Fort (PXTC, normal)
	'b6873a08-92a1-53cb-88ef-26dcfedf759f': 'a2d17b53-ec8b-55a6-a9be-50759995699d',
	'a2d17b53-ec8b-55a6-a9be-50759995699d': 'b6873a08-92a1-53cb-88ef-26dcfedf759f',
	# transform: Treasure Map // Treasure Cove (PXTC, normal)
	'8fb408fd-2473-5c5b-801c-a946aa41fd79': 'f9033d98-efc4-5a5b-93b5-1592b1117fde',
	'f9033d98-efc4-5a5b-93b5-1592b1117fde': '8fb408fd-2473-5c5b-801c-a946aa41fd79',
	# modal_dfc: Emeria's Call // Emeria, Shattered Skyclave (PZNR, prerelease)
	'ecab61ac-224f-5c9f-b369-76bd3a91b444': '0764f2ce-b771-52f6-a156-653a043e8a26',
	'0764f2ce-b771-52f6-a156-653a043e8a26': 'ecab61ac-224f-5c9f-b369-76bd3a91b444',
	# transform: Golden Guardian // Gold-Forge Garrison (RIX, normal)
	'b9d63a33-71cc-5824-a614-b511480cf3c1': '7cc06729-21e7-5cb0-822f-c88156a98eb4',
	'7cc06729-21e7-5cb0-822f-c88156a98eb4': 'b9d63a33-71cc-5824-a614-b511480cf3c1',
	# split: Depose // Deploy (RNA, normal)
	'd58a6df4-6066-5049-b705-10c1dd865084': '3a0dd57f-a855-570e-8cc3-a4a72c3d50f6',
	'3a0dd57f-a855-570e-8cc3-a4a72c3d50f6': 'd58a6df4-6066-5049-b705-10c1dd865084',
	# split: Incubation // Incongruity (RNA, normal)
	'b0506af8-075d-5629-85f4-c3860c02573c': '0c08602c-0d20-5ede-85d7-1e0f8458ba72',
	'0c08602c-0d20-5ede-85d7-1e0f8458ba72': 'b0506af8-075d-5629-85f4-c3860c02573c',
	# split: Thrash // Threat (RNA, normal)
	'da8df4d6-425c-5e3f-9d7f-182ff8b5aa26': '7d01cd4c-a6f8-5d88-acc3-d6ab76e8e884',
	'7d01cd4c-a6f8-5d88-acc3-d6ab76e8e884': 'da8df4d6-425c-5e3f-9d7f-182ff8b5aa26',
	# split: Warrant // Warden (RNA, normal)
	'3d5ceb46-ca7b-52b7-a0aa-0e1a5876b1e0': 'b5046154-a12d-56f1-8698-405c153932eb',
	'b5046154-a12d-56f1-8698-405c153932eb': '3d5ceb46-ca7b-52b7-a0aa-0e1a5876b1e0',
	# transform: Arlinn Kord // Arlinn, Embraced by the Moon (SOI, normal)
	'b7c09e3f-f692-5ed0-8919-6a2875c4ab29': 'a815a066-80c8-5913-b94a-866c8af561df',
	'a815a066-80c8-5913-b94a-866c8af561df': 'b7c09e3f-f692-5ed0-8919-6a2875c4ab29',
	# transform: Daring Sleuth // Bearer of Overwhelming Truths (SOI, normal)
	'bd7ebf46-cea6-5c33-b858-d765d5b1f4ab': '3fe4768e-b540-5381-923b-b2e685666ebb',
	'3fe4768e-b540-5381-923b-b2e685666ebb': 'bd7ebf46-cea6-5c33-b858-d765d5b1f4ab',
	# transform: Hanweir Militia Captain // Westvale Cult Leader (SOI, normal)
	'a3a82054-33c3-53b2-81f5-6bd5faa8add9': '4bb6738b-5e20-56f6-b82e-a8e821b9f6b8',
	'4bb6738b-5e20-56f6-b82e-a8e821b9f6b8': 'a3a82054-33c3-53b2-81f5-6bd5faa8add9',
	# transform: Westvale Abbey // Ormendahl, Profane Prince (SOI, normal)
	'85a80a8d-8f95-5b94-a56d-42e6a83674f1': '18539842-2be6-5a9f-ae62-d12f943c870e',
	'18539842-2be6-5a9f-ae62-d12f943c870e': '85a80a8d-8f95-5b94-a56d-42e6a83674f1',
	# modal_dfc: Extus, Oriq Overlord // Awaken the Blood Avatar (STX, extendedart)
	'47229f00-8426-5346-b41f-1d2c5b926197': 'b3ce0192-4259-50a2-8548-8be986fa454a',
	'b3ce0192-4259-50a2-8548-8be986fa454a': '47229f00-8426-5346-b41f-1d2c5b926197',
	# modal_dfc: Extus, Oriq Overlord // Awaken the Blood Avatar (STX, normal)
	'c3881b6c-fe9c-5fbf-bfcf-136795dd0e3c': '1585babb-53a5-5c2b-bcbc-e239fa209d2b',
	'1585babb-53a5-5c2b-bcbc-e239fa209d2b': 'c3881b6c-fe9c-5fbf-bfcf-136795dd0e3c',
	# modal_dfc: Kianne, Dean of Substance // Imbraham, Dean of Theory (STX, extendedart)
	'fdb0d757-1597-5a87-acb6-f7f997d3eb0d': '557b13f5-780e-530d-aa82-6135158089ae',
	'557b13f5-780e-530d-aa82-6135158089ae': 'fdb0d757-1597-5a87-acb6-f7f997d3eb0d',
	# modal_dfc: Kianne, Dean of Substance // Imbraham, Dean of Theory (STX, normal)
	'67c72f64-55f6-5699-9ee7-e6fa5bf3a456': '635efd48-a593-5ade-86ca-8b2ca6a17aed',
	'635efd48-a593-5ade-86ca-8b2ca6a17aed': '67c72f64-55f6-5699-9ee7-e6fa5bf3a456',
	# modal_dfc: Mila, Crafty Companion // Lukka, Wayward Bonder (STX, borderless)
	'90aea4cc-2057-5518-a41e-5d6d53d11e86': '0f9214dc-2fc9-5bee-95e2-51ebd262625e',
	'0f9214dc-2fc9-5bee-95e2-51ebd262625e': '90aea4cc-2057-5518-a41e-5d6d53d11e86',
	# modal_dfc: Mila, Crafty Companion // Lukka, Wayward Bonder (STX, normal)
	'8317df72-f217-529b-b3f3-33bac02d8971': 'a56db6de-2653-5737-b9b3-2b71592759d3',
	'a56db6de-2653-5737-b9b3-2b71592759d3': '8317df72-f217-529b-b3f3-33bac02d8971',
	# modal_dfc: Pestilent Cauldron // Restorative Burst (STX, extendedart)
	'77b6c21f-9e23-5f34-9895-6080a598bd3b': '239e98ea-8241-5860-88a1-43693287189b',
	'239e98ea-8241-5860-88a1-43693287189b': '77b6c21f-9e23-5f34-9895-6080a598bd3b',
	# modal_dfc: Pestilent Cauldron // Restorative Burst (STX, normal)
	'd07c3edc-397e-5a1a-aa15-3c212ca1dcfb': 'c82b54a3-005d-5985-bf04-83e2ce45ce79',
	'c82b54a3-005d-5985-bf04-83e2ce45ce79': 'd07c3edc-397e-5a1a-aa15-3c212ca1dcfb',
	# modal_dfc: Rowan, Scholar of Sparks // Will, Scholar of Frost (STX, borderless)
	'b842741f-5393-5c0c-89c5-67bbc3bf5f05': '9a44af27-5825-52f3-9b63-4412dc593176',
	'9a44af27-5825-52f3-9b63-4412dc593176': 'b842741f-5393-5c0c-89c5-67bbc3bf5f05',
	# modal_dfc: Rowan, Scholar of Sparks // Will, Scholar of Frost (STX, normal)
	'fabd03c7-6c79-552c-ae47-a907a2dd60b1': 'bec42168-2b9d-5bc6-815b-e4c120fc4f51',
	'bec42168-2b9d-5bc6-815b-e4c120fc4f51': 'fabd03c7-6c79-552c-ae47-a907a2dd60b1',
	# modal_dfc: Valentin, Dean of the Vein // Lisette, Dean of the Root (STX, extendedart)
	'870a8de3-0179-5d80-a776-5c495879268b': '783762f0-4049-5417-9378-76f563475f87',
	'783762f0-4049-5417-9378-76f563475f87': '870a8de3-0179-5d80-a776-5c495879268b',
	# modal_dfc: Valentin, Dean of the Vein // Lisette, Dean of the Root (STX, normal)
	'6eac70af-6c27-5b83-9514-0eb13f05ad48': 'c4983060-0fdf-5c60-9930-5db6683ab7eb',
	'c4983060-0fdf-5c60-9930-5db6683ab7eb': '6eac70af-6c27-5b83-9514-0eb13f05ad48',
	# transform: Dowsing Dagger // Lost Vale (XLN, normal)
	'040b2583-1896-585a-9a56-681e7597c304': '4194a0e5-6575-56a0-a841-569172c330ca',
	'4194a0e5-6575-56a0-a841-569172c330ca': '040b2583-1896-585a-9a56-681e7597c304',
	# transform: Legion's Landing // Adanto, the First Fort (XLN, normal)
	'b6db5d31-1ddf-5752-9d3e-24dac3911669': 'aa4d38d2-0eb8-5dd8-86ca-0fe28f6472f8',
	'aa4d38d2-0eb8-5dd8-86ca-0fe28f6472f8': 'b6db5d31-1ddf-5752-9d3e-24dac3911669',
	# transform: Treasure Map // Treasure Cove (XLN, normal)
	'27c48a7a-d2a2-5459-b13c-461fcea64473': '9df98469-8e7f-5e59-aae6-255b850cef43',
	'9df98469-8e7f-5e59-aae6-255b850cef43': '27c48a7a-d2a2-5459-b13c-461fcea64473',
	# modal_dfc: Emeria's Call // Emeria, Shattered Skyclave (ZNR, extendedart)
	'6d82730a-9c18-5030-9aa7-bb1eb590556a': 'b31428a0-3a18-54aa-82db-a4fa8e155e6b',
	'b31428a0-3a18-54aa-82db-a4fa8e155e6b': '6d82730a-9c18-5030-9aa7-bb1eb590556a',
	# modal_dfc: Emeria's Call // Emeria, Shattered Skyclave (ZNR, normal)
	'd1222c93-0aee-5d60-970a-7342b6f8cba4': 'dde525a3-231d-58c4-a49d-4d6b6d811f19',
	'dde525a3-231d-58c4-a49d-4d6b6d811f19': 'd1222c93-0aee-5d60-970a-7342b6f8cba4',
}
def patch_card(card, expansion):
	"""Temporary fixes for issues in mtgjson data.

	Remember to also report these upstream."""
	# bunch of multi-face cards are missing their other-side flags
	if card['layout'] in {'flip', 'transform', 'modal_dfc', 'split', 'aftermath', 'adventure'} and 'otherFaceIds' not in card:
		otherFaceId = MISSING_OTHER_FACEID[card['uuid']]
		card['otherFaceIds'] = [otherFaceId]
		return True
	# Meld cards are completely effed, just remove them
	elif card['layout'] == 'meld':
		return False
	else:
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

HOST_PREFIX = "When this creature enters the battlefield,"
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
