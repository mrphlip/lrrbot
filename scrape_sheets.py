#!/usr/bin/env python3
import sys
sys.argv, args = sys.argv[:1], sys.argv[1:]
from common import gdata, http
import asyncio
import argparse
import json

def getargs():
	parser = argparse.ArgumentParser(description="Scrape card spoilers from Google Sheets")
	parser.add_argument('sheetid', type=str, help="Sheet ID for the set")
	return parser.parse_args(args)

async def get_data(sheetid):
	token = await gdata.get_oauth_token(["https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/spreadsheets.readonly"])
	headers = {"Authorization": "%(token_type)s %(access_token)s" % token}
	url = "https://sheets.googleapis.com/v4/spreadsheets/%s/values/%s?majorDimension=ROWS" % (sheetid, "A:I")
	data = await http.request(url, headers=headers)
	return json.loads(data)

def getcards(data):
	cards = []
	for row in data['values'][1:]:
		row += [""] * (9 - len(row))
		number, name, cost, types, subtypes, power, toughness, loyalty, text = row
		if not name:
			continue
		card = {
			'layout': 'normal',
			'name': name,
			'manaCost': cost,
			'text': text,
			'type': "%s \u2014 %s" % (types, subtypes) if subtypes else types,
			'number': number,
			'power': power,
			'toughness': toughness,
			'loyalty': loyalty,
		}
		card = dict((k, v.strip()) for k, v in card.items() if v is not None and v != "")
		cards.append(card)
	return cards

async def main(sheetid):
	data = await get_data(sheetid)
	carddata = {
		data['values'][0][0]: {
			'cards': getcards(data),
			'releaseDate': "1970-01-01T00:00:00Z",  # make sure these are lower priority than anything from MTGJSON
		}
	}
	with open("extracards.json", "w") as fp:
		json.dump(carddata, fp, indent=2, sort_keys=True)

if __name__ == '__main__':
	asyncio.run(main(**vars(getargs())))
