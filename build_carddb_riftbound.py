#!/usr/bin/env python3

import psycopg2
import common
common.FRAMEWORK_ONLY = True

import asyncio
import json
from html.parser import HTMLParser
from typing import NotRequired, TypedDict

from html2text import HTML2Text

from common import http
from common.config import config
import common.card

class CardGalleryParser(HTMLParser):
	def __init__(self):
		super().__init__()
		self.in_app_state = False
		self.app_state = None

	def handle_starttag(self, tag, attrs):
		for attr, value in attrs:
			if attr == 'id' and value == '__NEXT_DATA__':
				self.in_app_state = True
	
	def handle_data(self, data):
		if self.in_app_state:
			self.app_state = json.loads(data)

	def handle_endtag(self, tag):
		self.in_app_state = False

class CardTextParser(HTML2Text):
	def __init__(self):
		super().__init__(bodywidth=0)
		self.emphasis_mark = ''
	
	def handle(self, data: str) -> str:
		text = super().handle(data)
		
		text = text.replace(':rb_exhaust:', '[E]')
		text = text.replace(':rb_might:', '[M]')
		text = text.replace(':rb_rune_body:', '[O]')
		text = text.replace(':rb_rune_calm:', '[G]')
		text = text.replace(':rb_rune_chaos:', '[P]')
		text = text.replace(':rb_rune_fury:', '[R]')
		text = text.replace(':rb_rune_mind:', '[B]')
		text = text.replace(':rb_rune_order:', '[Y]')
		text = text.replace(':rb_rune_rainbow:', '[A]')

		for n in range(0, 10):
			text = text.replace(f':rb_energy_{n}:', f'[{n}]')
		
		return ' / '.join(line.strip() for line in text.splitlines())

class Label(TypedDict):
	id: str
	label: str

class LabelledValue(TypedDict):
	label: str
	value: Label

class LabelledTags(TypedDict):
	label: str
	tags: list[str]

class LabelledLabels(TypedDict):
	label: str
	values: list[Label]

class LabelledCardType(TypedDict):
	label: str
	type: list[Label]
	superType: list[Label]

class Card(TypedDict):
	collectorNumber: int
	id: str
	name: str
	set: LabelledValue
	domain: LabelledLabels
	rarity: dict
	cardType: LabelledCardType
	cardImage: dict
	illustrator: dict
	text: dict
	energy: NotRequired[LabelledValue]
	might: NotRequired[LabelledValue]
	power: NotRequired[LabelledValue]
	tags: NotRequired[LabelledTags]
	orientation: str
	publicCode: str

def process_card(card: Card):
	yield card['name']

	if 'energy' in card:
		yield ' ['
		yield card['energy']['value']['label']
		yield ']'

	yield ' ['
	for i, domain in enumerate(card['domain']['values']):
		if i != 0:
			yield ' '
		yield domain['label']

	if 'power' in card:
		yield ' '
		yield card['power']['value']['label']
	yield ']'

	yield ' |'
	if 'superType' in card['cardType']:
		for type in card['cardType']['superType']:
			yield ' '
			yield type['label']
	if 'type' in card['cardType']:
		for type in card['cardType']['type']:
			yield ' '
			yield type['label']

	if 'tags' in card:
		yield ' \u2212'
		for i, tag in enumerate(card['tags']['tags']):
			if i == 0:
				yield ' '
			else:
				yield ', '
			yield tag
	
	if 'might' in card:
		yield ' ['
		yield card['might']['value']['label']
		yield ']'

	text = CardTextParser().handle(card['text']['richText']['body'])
	if text:
		yield ' | '
		yield text

SETS = ['OGN', 'OGS', 'SFD']

async def main() -> None:
	parser = CardGalleryParser()

	print('Downloading card gallery...')
	parser.feed(await http.request("https://riftbound.leagueoflegends.com/en-us/card-gallery/"))

	blades = parser.app_state['props']['pageProps']['page']['blades']
	gallery = next(blade for blade in blades if blade['type'] == 'riftboundCardGallery')
	cards: list[Card] = gallery['cards']['items']
	print(f'Found {len(cards)} cards out of {gallery['cards']['async']['metadata']['totalItems']}')

	print('Processing cards...')
	cards.sort(key=lambda card: (SETS.index(card['set']['value']['id']), card['publicCode']))

	processed: dict[str, tuple[str, str]] = {}
	codes: dict[str, str] = {}

	for card in cards:
		if card['publicCode'] == "SFD-227/221" or card['publicCode'] == "SFD-227*/221":
			# Ahri, Inquisitive: tags on card say Ahri and Ionia, card data says only Ahri.
			# Also previously printed with both.
			card['tags'] = {
				'label': 'Tags',
				'tags': ['Ahri', 'Ionia'],
			}

		clean_name = common.card.clean_text(card['name'])
		text = ''.join(process_card(card))

		if clean_name in processed and processed[clean_name] != (card['name'], text):
			print('ERROR: card conflict:')
			print(f'\tOLD: {processed[clean_name]}')
			print(f'\tNEW: {text}')
			print(json.dumps(card, indent=2))
			exit(1)
		else:
			processed[clean_name] = card['name'], text
			codes[card['publicCode']] = clean_name

	print("Uploading cards...")

	uploaded: dict[str, int] = {}

	with psycopg2.connect(config['postgres']) as conn, conn.cursor() as cur:
		cur.execute("DELETE FROM cards WHERE game = %s", (common.card.CARD_GAME_RIFTBOUND, ))

		for clean_name, (name, text) in processed.items():
			cur.execute("INSERT INTO cards (filteredname, name, text, hidden, game) VALUES (%s, %s, %s, %s, %s) RETURNING id", (
				clean_name,
				name,
				text,
				False,
				common.card.CARD_GAME_RIFTBOUND,
			))
			uploaded[clean_name], = cur.fetchone()
		
		cur.executemany("INSERT INTO card_codes(code, cardid, game) VALUES (%s, %s, %s)", [
			(code, uploaded[clean_name], common.card.CARD_GAME_RIFTBOUND)
			for code, clean_name in codes.items()
		])
	
	print('Cards uploaded.')

if __name__ == '__main__':
	asyncio.run(main())
