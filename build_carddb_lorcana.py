#!/usr/bin/env python3
"""
This script downloads the latest Disney Lorcana card data from https://lorcanajson.org/ and processes
it to turn the highly-structured data there into a flat list of card names to descriptions
formatted to send down the chat.
"""

import common
common.FRAMEWORK_ONLY = True

import json
import sys
import zipfile

import psycopg2

from common import http
from common.card import clean_text, CARD_GAME_LORCANA
from common.config import config

def main():
	forceRun = '-f' in sys.argv

	was_downloaded = http.download_file("https://lorcanajson.org/files/current/en/allCards.json.zip", "LorcanaCards.json.zip", True)
	if not was_downloaded and not forceRun:
		print("No Lorcana card update available, stopping update")
		return

	print("Loading card data")
	with zipfile.ZipFile(r"LorcanaCards.json.zip") as card_zip_file:
		with card_zip_file.open("allCards.json") as cardFile:
			carddata = json.load(cardFile)

	print("Processing and storing card data")
	with psycopg2.connect(config['postgres']) as conn, conn.cursor() as cur:
		cur.execute("DELETE FROM cards WHERE game = %s", (CARD_GAME_LORCANA, ))
		processed_cards = []
		for card in carddata['cards']:
			if card['fullName'] not in processed_cards:
				cur.execute("INSERT INTO cards (game, filteredname, name, text, hidden) VALUES (%s, %s, %s, %s, %s)", (
					CARD_GAME_LORCANA,
					clean_text(card['fullName']),
					card['fullName'],
					get_card_description(card),
					False,
				))
				processed_cards.append(card['fullName'])
	print("Finished updating Lorcana cards")

def get_card_description(card):
	parts = [f"{card['fullName']} [{card['cost']}, {card['color']}, {'Inkable' if card['inkwell'] else 'Non-inkable'}]"]
	if card['type'] == "Character":
		parts.append(f"Character [{card['strength']}/{card['willpower']}, {card['lore']} ◊]")
	else:
		parts.append(card['type'])
	if 'subtypes' in card:
		parts.append(", ".join(card['subtypes']))
	abilities_and_effects_parts = []
	if 'abilities' in card:
		abilities_and_effects_parts.extend(card['abilities'])
	if 'effects' in card:
		for effect in card['effects']:
			abilities_and_effects_parts.append(f"{effect['name']} {effect['text']}")
	if abilities_and_effects_parts:
		parts.append(" / ".join(abilities_and_effects_parts))

	return " | ".join(parts)


if __name__ == "__main__":
	main()
