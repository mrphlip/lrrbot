import re

from common.postgres import escape_like

CARD_GAME_MTG = 1
CARD_GAME_KEYFORGE = 2
CARD_GAME_PTCG = 3
CARD_GAME_LORCANA = 4
CARD_GAME_ALTERED = 5

re_specialchars = re.compile(r"[ \-+'\",:;!?.()\u00ae&/\u2019\u201c\u201d\[\]~\u2026\u25b9#\u2014\uA789]")
LETTERS_MAP = {
	'\u00e0': 'a',
	'\u00e1': 'a',
	'\u00e2': 'a',
	'\u00e3': 'a',
	'\u00e4': 'a',
	'\u00e5': 'a',
	'\u00e6': 'ae',
	'\u00e7': 'c',
	'\u00e8': 'e',
	'\u00e9': 'e',
	'\u00ea': 'e',
	'\u00eb': 'e',
	'\u00ec': 'i',
	'\u00ed': 'i',
	'\u00ee': 'i',
	'\u00ef': 'i',
	'\u00f0': 'th',
	'\u00f1': 'n',
	'\u00f2': 'o',
	'\u00f3': 'o',
	'\u00f4': 'o',
	'\u00f5': 'o',
	'\u00f6': 'o',
	'\u00f8': 'o',
	'\u00f9': 'u',
	'\u00fa': 'u',
	'\u00fb': 'u',
	'\u00fc': 'u',
	'\u00fd': 'y',
	'\u00fe': 'th',
	'\u00ff': 'y',
	'\u0101': 'a',
}

def clean_text(text):
	"""Clean up the search text, by removing special characters and canonicalising letters with diacritics etc"""
	text = text.lower()
	text = re_specialchars.sub('', text)
	for k, v in LETTERS_MAP.items():
		text = text.replace(k, v)
	return text

def to_query(text):
	return "%" + "%".join(escape_like(clean_text(word)) for word in text.split()) + "%"
