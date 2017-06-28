#!/usr/bin/python3
import sys
import json
import csv
import regex  # not re, because we need .captures()

def get_data(filename):
	with open(filename, newline='') as fp:
		yield from csv.DictReader(fp)

re_cost = regex.compile(r"^(?:o([WUBRGTXC]|\d+|cT))*$")
code_map = {'cT': "T"}
def cleancost(cost):
	parts = re_cost.match(cost)
	if not parts:
		raise ValueError("Could not parse cost: %r" % cost)
	parts = parts.captures(1)
	parts = (code_map.get(i, i) for i in parts)
	return "".join("{%s}" % i for i in parts)

re_italics = regex.compile(r"</?i>", regex.IGNORECASE)
re_textcost = regex.compile(r"\{([^{}]*)\}")
def cleantext(text):
	text = re_italics.sub('', text)
	text = re_textcost.sub(lambda match:cleancost(match.group(1)), text)
	return text

re_embalm = regex.compile(r"(?:^|\n|,)\s*(Embalm|Eternalize)\b", regex.IGNORECASE)
def getcard(row, setid):
	typeline = row['Card Type']
	if row['SuperType']:
		typeline = "%s %s" % (row['SuperType'], typeline)
	if row['SubType']:
		typeline = "%s \u2014 %s" % (typeline, row['SubType'])
	card = {
		'layout': 'normal',
		'name': row['Card Title'].replace('\u2019', "'"),
		'manaCost': cleancost(row['Mana']),
		'text': cleantext(row['Rules Text']),
		'type': typeline,
		'number': row['Collector Number'],
		'power': row['Power'],
		'toughness': row['Toughness'],
		'loyalty': row['Loyalty'],
	}
	card = dict((k, v.strip()) for k, v in card.items() if v is not None and v != "")
	yield card, setid

	# Create tokens for Embalm and Eternalize creatures for AKH/HOU preprere
	match = re_embalm.search(card.get('text', ''))
	if match:
		card = dict(card)
		card['internalname'] = card['name'] + "_TKN"
		card['name'] = card['name'] + " token"
		typeline = row['Card Type']
		if row['SuperType']:
			typeline = "%s %s" % (row['SuperType'], typeline)
		typeline = "%s \u2014 Zombie %s" % (typeline, row['SubType'])
		card['type'] = typeline
		del card['manaCost']
		del card['number']
		if match.group(1) == "Eternalize":
			card['power'] = card['toughness'] = '4'
		yield card, setid + "_TKN"

def getsplitcard(row, setid):
	# Format:
	#  Card Title is set to "Lefthalf /// Righthalf"
	#  Rules Text is set to "Left half rules///\nRighthalf\nRightcost\nRighttype\nRight half rules"
	names = row['Card Title'].split('///')
	if len(names) != 2:
		raise ValueError("Card has more than 2 names: %r" % row['Card Title'])
	names = [i.strip() for i in names]
	text = row['Rules Text'].split('///')
	if len(names) != 2:
		raise ValueError("Card has more than 2 texts: %r" % row['Card Title'])

	# We don't know where these would come from for the second card
	# Shouldn't exist anyway, these are all instants/sorceries
	if row['Power'] or row['Toughness'] or row['Loyalty']:
		raise ValueError("Split card has P/T or Loyalty box: %r" % row['Card Title'])

	subrow = dict(row)
	subrow['Card Title'] = names[0]
	subrow['Rules Text'] = text[0]
	left = next(getcard(subrow, setid))

	carddata = text[1].split("\n")
	if not carddata[0]:
		carddata = carddata[1:]
	if carddata[0] != names[1]:
		raise ValueError("Names don't match for %r" % row['Card Title'])
	subrow['Card Title'] = names[1]
	subrow['Mana'] = carddata[1]
	subrow['Card Type'] = carddata[2]
	subrow['Rules Text'] = "\n".join(carddata[3:])
	right = next(getcard(subrow, setid))

	left[0]['layout'] = right[0]['layout'] = "aftermath"
	left[0]['names'] = right[0]['names'] = names
	return [left, right]

def getcards(data, setid):
	for row in data:
		if '///' in row['Card Title']:
			yield from getsplitcard(row, setid)
		else:
			yield from getcard(row, setid)

def main(filenames):
	carddata = {}
	for filename in filenames:
		setid = filename.split('.')[0]
		data = get_data(filename)
		for card, cardsetid in getcards(data, setid):
			carddata.setdefault(cardsetid, {'cards':[]})['cards'].append(card)
	with open("extracards.json", "w") as fp:
		json.dump(carddata, fp, indent=2, sort_keys=True)

if __name__ == '__main__':
	main(sys.argv[1:])
