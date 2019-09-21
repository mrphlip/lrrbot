#!/usr/bin/env python3
import sys
import json
import csv
import regex  # not re, because we need .captures()

def get_data(filename):
	with open(filename, newline='') as fp:
		for row in csv.DictReader(fp):
			# Fix some inconsistent casing
			if 'Supertype' in row:
				row['SuperType'] = row.pop('Supertype')
			if 'Subtype' in row:
				row['SubType'] = row.pop('Subtype')
			yield row

re_cost = regex.compile(r"^\{?(?:o([WUBRGTXCQ]|\d+|Si|cT|\([wubrg]/[wubrg]\)))*\}?$")
code_map = {'cT': "T", 'Si': 'S'}
def cleancost(cost):
	parts = re_cost.match(cost)
	if not parts:
		raise ValueError("Could not parse cost: %r" % cost)
	parts = parts.captures(1)
	parts = (code_map.get(i, i.upper().replace('(','').replace(')','')) for i in parts)
	return "".join("{%s}" % i for i in parts)

re_italics = regex.compile(r"</?i>", regex.IGNORECASE)
re_textcost = regex.compile(r"\{([^{}]*)\}")
def cleantext(text):
	text = re_italics.sub('', text)
	text = re_textcost.sub(lambda match:cleancost(match.group(1)), text)
	return text

def cleantitle(text):
	return text.replace('\u2019', "'")

re_embalm = regex.compile(r"(?:^|\n|,)\s*(Embalm|Eternalize)\b", regex.IGNORECASE)
def getcard(row, setid):
	typeline = row['Card Type']
	if row.get('SuperType'):
		typeline = "%s %s" % (row['SuperType'], typeline)
	if row['SubType']:
		typeline = "%s \u2014 %s" % (typeline, row['SubType'])
	card = {
		'layout': 'normal',
		'name': cleantitle(row['Card Title']),
		'manaCost': cleancost(row['Mana']),
		'text': cleantext(row['Rules Text']),
		'type': typeline,
		'number': row['Collector Number'],
		'power': row['Power'],
		'toughness': row['Toughness'],
		'loyalty': row['Loyalty'],
	}
	card = dict((k, v.strip()) for k, v in card.items() if v is not None and v != "")
	yield card

def getsplitcard(row, setid):
	# Format:
	#  Card Title is set to "Lefthalf /// Righthalf"
	#  Rules Text is set to "Left half rules\n///\nRighthalf\nRightcost\nRighttype\nRight half rules"
	# Alternate format (for Adventures):
	#  Card Title is set to "Lefthalf"
	#  Rules Text is set to "Left half rules\n//ADV//\nRighthalf\nRightcost\nRighttype\nRight half rules"
	names = regex.split('//+(?:ADV//+)?', row['Card Title'])
	if len(names) > 2:
		raise ValueError("Card has more than 2 names: %r" % row['Card Title'])
	names = [i.strip() for i in names]
	text = regex.split('//+(?:ADV//+)?', row['Rules Text'])
	if len(text) != 2:
		raise ValueError("Card has more than 2 texts: %r" % row['Card Title'])

	subrow = dict(row)
	subrow['Card Title'] = names[0]
	subrow['Rules Text'] = text[0]
	left = next(getcard(subrow, setid))

	carddata = text[1].replace('\r\n', '\n').split("\n")
	if not carddata[0]:
		carddata = carddata[1:]
	if len(names) == 1:
		names.append(carddata[0])
	elif carddata[0] != names[1]:
		raise ValueError("Names don't match for %r vs %r" % (row['Card Title'], carddata[0]))
	subrow['Card Title'] = names[1]
	subrow['Mana'] = carddata[1]
	subrow['Card Type'] = carddata[2]
	subrow['SuperType'] = subrow['SubType'] = subrow['Power'] = subrow['Toughness'] = subrow['Loyalty'] = ''
	subrow['Rules Text'] = "\n".join(carddata[3:])
	right = next(getcard(subrow, setid))

	if setid in ('AKH', 'HOU'):
		left['layout'] = right['layout'] = "aftermath"
	elif setid in ('ELD'):
		left['layout'] = right['layout'] = "adventure"
	else:
		left['layout'] = right['layout'] = "split"
	left['names'] = right['names'] = [cleantitle(n) for n in names]
	return left, right

def getdfc(frontrow, backrow, setid):
	front = next(getcard(frontrow, setid))
	back = next(getcard(backrow, setid))
	front['layout'] = back['layout'] = 'double-faced'
	front['names'] = back['names'] = [front['name'], back['name']]
	front['number'] += 'a'
	back['number'] += 'b'
	return front, back

def match_dfcs(data):
	# For DFCs the front and back face have the same collector number
	numbers = {}
	for row in data:
		numbers.setdefault(row['Collector Number'], []).append(row)
	for rows in numbers.values():
		if len(rows) == 1:
			yield rows[0]
		elif len(rows) == 2:
			# There's no direct indication which card is the front face, we need to guess...
			# in Ixalan the back face has reminder text
			if "(Transforms from %s.)" % rows[0]['Card Title'] in rows[1]['Rules Text']:
				yield rows[0], rows[1]
			elif "(Transforms from %s.)" % rows[1]['Card Title'] in rows[0]['Rules Text']:
				yield rows[1], rows[0]
			# The back face doesn't have a mana cost
			elif rows[0]['Mana'] and not rows[1]['Mana']:
				yield rows[0], rows[1]
			elif rows[1]['Mana'] and not rows[0]['Mana']:
				yield rows[1], rows[0]
			# give up if we can't figure it out
			else:
				raise ValueError("Can't find front/back faces of %d (%s/%s)" %
					(rows[0]['Collector Number'], rows[0]['Card Title'], rows[1]['Card Title']))
		else:
			raise ValueError("Too many cards for collector number %d" % rows[0]['Collector Number'])

def getcards(data, setid):
	if setid in ('XLN', 'RIX', 'M19'):
		data = match_dfcs(data)
	for row in data:
		if isinstance(row, tuple):
			yield from getdfc(row[0], row[1], setid)
		elif '//' in row['Card Title'] or '//' in row['Rules Text']:
			yield from getsplitcard(row, setid)
		else:
			yield from getcard(row, setid)

def main(filenames):
	carddata = {}
	for filename in filenames:
		setid = filename.split('.')[0]
		data = get_data(filename)
		carddata[setid] = {
			'code': setid,
			'cards': list(getcards(data, setid)),
			# We're using this primarly for the PPR so the wording in this set is the
			# newest around. And it's straight from the source, so it's more likely to
			# be correct if there's a conflict.
			'releaseDate': '2038-01-18',
		}
	with open("extracards.json", "w") as fp:
		json.dump(carddata, fp, indent=2, sort_keys=True)

if __name__ == '__main__':
	main(sys.argv[1:])
