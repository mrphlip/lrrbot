import json
import psycopg2

from common.card import clean_text, CARD_GAME_ALTERED
from common.config import config

sets = {
	# Beyond the Gates - KS Edition
	'COREKS': {
		'release_date': '2024-07-15',
	},
	# Beyond the Gates
	'CORE': {
		'release_date': '2024-09-13',
	},
	# Trial by Frost
	'ALIZE': {
		'release_date': '2025-01-31',
	},
}

def build_card_description(name, card):
	yield name
	if card['cardType']['reference'] != 'HERO' and card['cardType']['reference'] != 'TOKEN':
		yield ' [hand: '
		yield card['elements']['MAIN_COST'].strip('#')
		yield ', reserve: '
		yield card['elements']['RECALL_COST'].strip('#')
		yield ']'
	yield ' | '
	if card['cardType']['reference'] == 'HERO':
		yield card['mainFaction']['name']
		yield ' '
	yield card['cardType']['name']
	if card['cardSubTypes']:
		yield ' \u2014 '
		for i, subtype in enumerate(card['cardSubTypes']):
			if i != 0:
				yield ', '
			yield subtype['name']

	reserve = card['elements'].get('RESERVE', '').strip("#")
	landmarks = card['elements'].get('PERMANENT', '').strip("#")
	if reserve or landmarks:
		yield ' [reserve: '
		yield reserve or '?'
		yield ', landmarks: '
		yield landmarks or '?'
		yield ']'

	forest_power = card['elements'].get('FOREST_POWER', '').strip('#')
	mountain_power = card['elements'].get('MOUNTAIN_POWER', '').strip('#')
	ocean_power = card['elements'].get('OCEAN_POWER', '').strip('#')
	if forest_power or mountain_power or ocean_power:
		yield ' ['
		yield forest_power or '?'
		yield '/'
		yield mountain_power or '?'
		yield '/'
		yield ocean_power or '?'
		yield ']'

	main_ability = card['elements'].get('MAIN_EFFECT', '').replace('#', '').replace('\u00A0', ' ')
	support_ability = card['elements'].get('ECHO_EFFECT', '').replace('#', '').replace('\u00A0', ' ')
	if main_ability or support_ability:
		yield ' | '
		if main_ability:
			yield main_ability
		if main_ability and support_ability:
			yield ' / '
		if support_ability:
			yield support_ability

def build_card_name(card):
	if '-C-' in card['collectorNumberFormatted']:
		return f"{card['name']} (Common)"
	if '-R-' in card['collectorNumberFormatted']:
		return f"{card['name']} (Rare)"
	if '-F-' in card['collectorNumberFormatted']:
		return f"{card['name']} (Faction-shifted)"
	return card['name']

if __name__ == '__main__':
	print("Loading cards...")

	with open("carddb-altered.json") as f:
		cards = json.load(f)

	processed = {}
	codes = {}

	print("Processing cards...")

	for card in cards:
		if card['cardProduct']['reference'] == 'P':
			# Promo cards have broken card entries
			print(f"WARNING: Ignoring {card['cardSet']['name']} promo card {card['name']}")
			continue
		name = build_card_name(card)
		filtered_name = clean_text(name)
		release_date = sets[card['cardSet']['reference']]['release_date']
		codes.setdefault(filtered_name, []).append(card['reference'])
		if filtered_name not in processed or processed[filtered_name]['release_date'] < release_date:
			processed[filtered_name] = {
				'name': name,
				'text': ''.join(build_card_description(name, card)),
				'release_date': release_date,
			}

	print("Updating card database...")

	with psycopg2.connect(config['postgres']) as conn, conn.cursor() as cur:
		cur.execute("DELETE FROM cards WHERE game = %s", (CARD_GAME_ALTERED, ))
		for filtered_name, card in processed.items():
			cur.execute(
				"INSERT INTO cards (game, filteredname, name, text) VALUES (%s, %s, %s, %s) RETURNING id",
				(
					CARD_GAME_ALTERED,
					filtered_name,
					card['name'],
					card['text'],
				)
			)
			card_id, = cur.fetchone()
			for code in codes.get(filtered_name, []):
				cur.execute(
					"INSERT INTO card_codes (code, cardid, game) VALUES (%s, %s, %s)",
					(
						code,
						card_id,
						CARD_GAME_ALTERED,
					)
				)

	print("Done.")
