import json
import requests
import urllib.parse

cards = []

with requests.Session() as session:
	url = "https://api.altered.gg/cards"
	total_cards = 0
	cards_listing = []
	while True:
		print(f"Downloading {url}")
		with session.get(url) as response:
			response.raise_for_status()
			data = response.json()

			total_cards = data['hydra:totalItems']
			cards_listing.extend(data['hydra:member'])

			if next_url := data['hydra:view'].get('hydra:next'):
				url = urllib.parse.urljoin(url, next_url)
			else:
				break

	print(f"Got {len(cards_listing)} out of {total_cards} cards")

	for card in cards_listing:
		print(f'Downloading card {card["reference"]} {card["name"]}')
		with session.get(f'https://api.altered.gg/cards/{card["reference"]}') as response:
			response.raise_for_status()
			# merge the card entries because there are fields in one that are missing in the other.
			cards.append(card | response.json())

with open("carddb-altered.json", "w") as f:
	json.dump(cards, f, indent=2)
