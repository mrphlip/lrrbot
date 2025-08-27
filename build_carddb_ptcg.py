#!/usr/bin/env python3
"""
This script downloads the latest PTCG card data from http://pokemontcg.io/ and processes
it to turn the highly-structured data there into a flat list of card names to descriptions
formatted to send down the chat.
"""

import common
common.FRAMEWORK_ONLY = True
import json
import os
import subprocess
import sys
import psycopg2
import re
from collections import defaultdict

from common.config import config
from common.card import clean_text, CARD_GAME_PTCG

TYPEABBR = {
	"Colorless": "C",
	"Darkness": "D",
	"Dragon": "N",
	"Grass": "G",
	"Fairy": "Y",
	"Fighting": "F",
	"Fire": "R",
	"Lightning": "L",
	"Metal": "M",
	"Psychic": "P",
	"Water": "W",
}

COMMON_RULES = [
	r"TAG TEAM rule: When your TAG TEAM is Knocked Out, your opponent takes 3 Prize cards\.",
	r"How to play a Pokémon V-UNION: Once per game during your turn, combine 4 different .* V-UNION from your discard pile and put them onto your Bench\.",
	r"V-UNION rule: When your Pokémon V-UNION is Knocked Out, your opponent takes 3 Prize cards\.",
	r"Put this card onto your Active .*\. .* LV.X can use any attack, Poké-Power, or Poké-Body from its previous level\.",
	r"Pokémon ex rule: When your Pokémon ex is Knocked Out, your opponent takes 2 Prize cards\.",
	r"Pokémon-EX rule: When a Pokémon-EX has been Knocked Out, your opponent takes 2 Prize cards\.",
	r"When Pokémon-ex has been Knocked Out, your opponent takes 2 Prize cards\.",
	r"Tera: As long as this Pokémon is on your Bench, prevent all damage done to this Pokémon by attacks \(both yours and your opponent's\)\.",
	r"As long as this Pokémon is on your Bench, prevent all damage done to this Pokémon by attacks \(both yours and your opponent's\)\.",
	r"Pokémon-GX rule: When your Pokémon-GX is Knocked Out, your opponent takes 2 Prize cards\.",
	r"VSTAR rule: When your Pokémon VSTAR is Knocked Out, your opponent takes 2 Prize cards\.",
	r"VMAX rule: When your Pokémon VMAX is Knocked Out, your opponent takes 3 Prize cards\.",
	r"V rule: When your Pokémon V is Knocked Out, your opponent takes 2 Prize cards\.",
	r"◇ \(Prism Star\) Rule: You can't have more than 1 ◇ card with the same name in your deck\. If a ◇ card would go to the discard pile, put it in the Lost Zone instead\.",
	r"Attach a Pokémon Tool to 1 of your Pokémon that doesn't already have a Pokémon Tool attached\.",
	r"Attach a Pokémon Tool to 1 of your Pokémon that doesn't already have a Pokémon Tool attached to it\.",
	r"You may attach any number of Pokémon Tools to your Pokémon during your turn\. You may attach only 1 Pokémon Tool to each Pokémon, and it stays attached\.",
	r"Attach this card to 1 of your .*Pokémon.* in play\. That Pokémon may use this card's attack instead of its own\. At the end of your turn, discard .*\.",
	r"Attach this card to 1 of your Pokémon SP in play\. That Pokémon may use this card's attack instead of its own\. When the Pokémon this card is attached to is no longer Pokémon SP, discard this card\.",
	r"The Pokémon this card is attached to can use the attack on this card. \(You still need the necessary Energy to use this attack.\) If this card is attached to 1 of your Pokémon, discard it at the end of your turn.",
	r"You may play as many Item cards as you like during your turn \(before your attack\)\.",
	r"You may play any number of Item cards during your turn\.",
	r"This Pokémon is both .* type.",
	r"Put this card from your hand onto your Bench only with the other half of .* LEGEND\.",
]
COMMON_RULES = re.compile(f"^(?:{'|'.join(COMMON_RULES)})$")

REPO = "https://github.com/PokemonTCG/pokemon-tcg-data"
CACHE_DIR = ".ptcgcache"

def main():
	force_run = False
	if '-f' in sys.argv:
		sys.argv.remove('-f')
		force_run = True

	if not download_data() and not force_run:
		print("No new version of pokemon-tcg-data")
		return

	with psycopg2.connect(config['postgres']) as conn, conn.cursor() as cur:
		cur.execute("DELETE FROM cards WHERE game = %s", (CARD_GAME_PTCG, ))

		for cardname, filteredname, description, hidden, card, codes in iter_cards():
			cardname, filteredname, codes, skip = get_hacks(cardname, filteredname, codes, card)
			if skip:
				continue

			#print(cardname, filteredname)
			cur.execute("INSERT INTO cards (game, filteredname, name, text, hidden) VALUES (%s, %s, %s, %s, %s) RETURNING id", (
				CARD_GAME_PTCG,
				filteredname,
				cardname,
				description,
				hidden,
			))
			cardid, = cur.fetchone()

			if not hidden:
				for code in codes:
					cur.execute("INSERT INTO card_codes (game, code, cardid) VALUES (%s, %s, %s)", (
						CARD_GAME_PTCG,
						code,
						cardid
					))

def download_data():
	if os.path.isdir(CACHE_DIR):
		old_revision = subprocess.check_output(['git', '-C', CACHE_DIR, 'rev-parse', 'HEAD'])
		subprocess.check_call(['git', '-C', CACHE_DIR, 'pull', '-q'])
		new_revision = subprocess.check_output(['git', '-C', CACHE_DIR, 'rev-parse', 'HEAD'])
		return old_revision != new_revision
	else:
		subprocess.check_call(['git', 'clone', '-q', REPO, CACHE_DIR])
		return True

def iter_cards():
	for group in group_cards():
		yield from process_group(group)

def load_cards():
	with open(os.path.join(CACHE_DIR, 'sets', 'en.json'), 'r') as f:
		sets = {set['id']: set for set in json.load(f)}

	for entry in os.scandir(os.path.join(CACHE_DIR, 'cards', 'en')):
		if not entry.is_file():
			continue
		(set_id, ext) = os.path.splitext(entry.name)
		if ext == '.json':
			with open(entry.path, 'r') as f:
				for card in json.load(f):
					card['set'] = sets[set_id]
					yield card

def group_cards():
	pkmn_cards = []
	other_cards = []
	for card in load_cards():
		if card['supertype'] == 'Pokémon':
			pkmn_cards.append(card)
		else:
			other_cards.append(card)
	yield from group_pkmn_cards(pkmn_cards)
	yield from group_other_cards(other_cards)

def group_pkmn_cards(cards):
	"""
	There can be multiple Pokemon cards with the same name... group them by name
	so that we know if a given card name is a unique or not.
	"""
	names = defaultdict(list)
	for card in cards:
		names[clean_text(card['name'])].append(card)
	return list(names.values())

def group_other_cards(cards):
	"""
	There can not be multiple non-Pokemon cards with the same name... if there are
	multiple cards with the same name, pick up only the most recent printing, as
	it is the authoritative one.
	"""
	names = defaultdict(list)
	for card in cards:
		names[clean_text(card['name'])].append(card)
	for group in names.values():
		latest = max(group, key=lambda card:card['set']['releaseDate'])
		latest["reprints"] = group
		yield [latest]

def process_group(group):
	for card in group:
		card['fullname'] = ''.join(gen_fullname(card))
		card['description'] = ''.join(gen_text(card))
	for card in group:
		def equiv(c):
			if c['set']['id'] != card['set']['id']:
				return False
			if c['description'] != card['description']:
				return False
			if c['id'] < card['id']:
				return False
			return True
		def identical(c):
			if not equiv(c):
				return False
			if c['number'] != card['number']:
				return False
			return True
		if any(identical(c) for c in group if c is not card):
			continue
		unique = all(equiv(c) for c in group)
		setunique = all(equiv(c) for c in group if setcode(c) == setcode(card))
		description = f"{card['fullname']} | {card['description']}"
		if "reprints" in card:
			codes = {gen_code(c) for c in card["reprints"]}
		else:
			codes = [gen_code(card)]
		for cardname, hidden in gen_cardnames(card, unique, setunique):
			filteredname = clean_text(cardname)
			yield cardname, filteredname, description, hidden, card, codes

def gen_cardnames(card, unique, setunique):
	"""
	For non-Pokemon cards, just generate the card name, since that's enough to
	identify the card.
	For Pokemon:
	  * If it's the only Pokemon with that name, generate "Name" as visible
	    but also "Name (set)" and "Name (set num)" as hidden.
	  * If it's the only Pokemon with that name in the set, generate "Name (set)"
	    but also "Name (set num)" as hidden.
	  * Otherwise, only generate "Name (set num)" as visible.
	"""
	if card['supertype'] == 'Pokémon':
		yield f"{card['name']} ({setcode(card)} {card['number']})", unique or setunique
		if setunique:
			yield f"{card['name']} ({setcode(card)})", unique
		if unique:
			yield f"{card['name']}", False
	else:
		yield f"{card['name']}", False

def gen_fullname(card):
	yield card['name']
	if card['supertype'] == 'Pokémon':
		yield ' ('
		yield setcode(card)
		yield ' '
		yield str(card['number'])
		yield ')'

def gen_text(card):
	yield card['supertype']
	if card.get('types'):
		yield ' {'
		yield '/'.join(card['types'])
		yield '}'
	if card.get('hp'):
		yield ' ['
		yield card['hp']
		yield 'HP]'
	if card.get('subtypes'):
		yield ' \u2014 '
		yield ' '.join(card['subtypes'])
	if card.get('evolvesFrom'):
		yield ' [evolves from: '
		yield card['evolvesFrom']
		yield ']'
	rules = [rule for rule in card.get('rules', ()) if not COMMON_RULES.match(rule)]
	if rules:
		yield ' | '
		for i, rule in enumerate(rules):
			if i:
				yield ' / '
			yield rule
	rules = []
	if card.get('ancientTrait'):
		card['ancientTrait']['type'] = 'Ancient Trait'
		rules.append(card['ancientTrait'])
	if card.get('abilities'):
		rules.extend(card['abilities'])
	if card.get('attacks'):
		rules.extend(card['attacks'])
	if rules:
		yield ' | '
		for i, rule in enumerate(rules):
			if i:
				yield ' / '
			if rule.get('type') and rule['type'] != 'Ability':
				yield '['
				yield rule['type']
				yield '] '
			if 'cost' in rule:
				yield '{'
				yield cost(rule['cost'])
				yield '} '
			yield rule['name']
			if rule.get('damage'):
				yield ' ('
				yield rule['damage']
				yield ')'
			if rule.get('text'):
				yield ': '
				yield rule['text']
		if card.get('weaknesses'):
			yield ' | weak: '
			for i, typeeff in enumerate(card.get('weaknesses')):
				if i:
					yield ', '
				yield typeeff['type']
				yield typeeff['value']
		if card.get('resistances'):
			yield ' | resist: '
			for i, typeeff in enumerate(card.get('resistances')):
				if i:
					yield ', '
				yield typeeff['type']
				yield typeeff['value']
		if 'retreatCost' in card:
			yield ' | retreat: {'
			yield cost(card['retreatCost'])
			yield '}'

def setcode(card):
	return card['set'].get('ptcgoCode') or card['set']['id'].upper()

def cost(costs, colorlesscount=True):
	res = []
	if colorlesscount:
		costs = [i for i in costs if i != 'Free']
		count = len([i for i in costs if i == 'Colorless'])
		if count or not costs:
			res.append(str(count))
			costs = [i for i in costs if i != 'Colorless']
	for cost in costs:
		res.append(TYPEABBR[cost])
	return ''.join(res)

def gen_code(card):
	return f"{setcode(card).lower()}_{card['number']}"

EX_NAMES = {
	'Arbok ex',
	'Chansey ex',
	'Clefable ex',
	'Electabuzz ex',
	'Jynx ex',
	'Magmar ex',
	'Vileplume ex',
	'Alakazam-EX',
	'Pidgeot-EX',
}
CODE_FIXES = {
	("blk_60", "Antique Cover Fossil"): "blk_80",
}
def get_hacks(cardname, filteredname, codes, card):
	skip = False

	# Diddle with the Unowns so that these don't have the same filtered name
	if card['name'] == 'Unown' and card['number'] == '!':
		filteredname += 'exclamation'
	if card['name'] == 'Unown' and card['number'] == '?':
		filteredname += 'question'

	# Don't generate the un-disambiged names for these "ex" pokemon
	# that have the same name as pokemon from the "EX" expansion
	if card['name'] in EX_NAMES and cardname == card['name']:
		skip = True

	# This set has a bunch of duplicate collector numbers... not worth the effort
	codes = [c for c in codes if not c.startswith("cel_")]
	# Fix cards that have typos in the source data
	codes = [CODE_FIXES.get((c, cardname), c) for c in codes]

	return cardname, filteredname, codes, skip

if __name__ == '__main__':
	main()
