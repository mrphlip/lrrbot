#!/usr/bin/env python3
"""
Usage: scrape_scryfall.py <SCRYFALL QUERY>

Scrape Scryfall for cards.

Example: scrape_scryfall.py set:ECL
"""
import sys
import json
import requests

def extract_types(typeline: str) -> tuple[list[str], list[str]]:
	if '\u2014' in typeline:
		supertypes, subtypes = typeline.split(' \u2014 ')
		return supertypes.split(' '), subtypes.split(' ')
	return typeline.split(' '), []

def main(query: str) -> None:
	cards = []
	page = 1
	while True:
		r = requests.get("https://api.scryfall.com/cards/search", params={"q": query, "page": str(page)})
		r.raise_for_status()
		data = r.json()
		cards.extend(data['data'])
		if not data['has_more']:
			break
		page += 1

	expansions = {}

	for card in cards:
		set_cards = expansions.setdefault(card['set'].upper(), {
			'code': card['set'].upper(),
			'cards': [],
			'releaseDate': card['released_at'],
		})['cards']
			
		if card['layout'] == 'normal':
			supertypes, subtypes = extract_types(card['type_line'])

			set_cards.append({
				'defense': card.get('defense'),
				'hand': card.get('hand_modifier'),
				'identifiers': {},
				'keywords': card['keywords'],
				'layout': 'normal',
				'life': card.get('life_modifier'),
				'loyalty': card.get('loyalty'),
				'manaCost': card['mana_cost'],
				'name': card['name'],
				'otherFaceIds': [],
				'power': card.get('power'),
				'subtypes': subtypes,
				'supertypes': supertypes,
				'text': card.get('oracle_text'),
				'toughness': card.get('toughness'),
				'type': card['type_line'],
				'types': subtypes + supertypes,
				'uuid': card['id'],
			})
		elif card['layout'] == 'transform':
			for i, face in enumerate(card['card_faces']):
				supertypes, subtypes = extract_types(face['type_line'])

				set_cards.append({
					'defense': face.get('defense'),
					'faceName': face['name'],
					'hand': card.get('hand_modifier'),
					'identifiers': {},
					'keywords': card['keywords'],
					'layout': 'transform',
					'life': card.get('life_modifier'),
					'loyalty': face.get('loyalty'),
					'manaCost': face['mana_cost'],
					'name': card['name'],
					'otherFaceIds': [f'{card['id']}-{j}' for j in range(len(card['card_faces'])) if i != j],
					'power': face.get('power'),
					'side': chr(ord('a') + i),
					'subtypes': subtypes,
					'supertypes': supertypes,
					'text': face.get('oracle_text'),
					'toughness': face.get('toughness'),
					'type': face['type_line'],
					'types': supertypes + subtypes,
					'uuid': f'{card['id']}-{i}',
				})
		else:
			print(json.dumps(card, indent=2))
			raise NotImplementedError(f'layout: {card['layout']}')
	
	for expansion in expansions.values():
		for card in expansion['cards']:
			if card['manaCost'] == '':
				del card['manaCost']

			for key, value in list(card.items()):
				if value is None:
					del card[key]

	with open("extracards.json", "w") as fp:
		json.dump(expansions, fp, indent=2, sort_keys=True)

if __name__ == '__main__':
	main(sys.argv[1])
