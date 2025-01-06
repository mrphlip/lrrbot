import sqlalchemy

import lrrbot.decorators
from lrrbot.command_parser import Blueprint
import common.postgres
import common.time
from common.card import clean_text, CARD_GAME_MTG, CARD_GAME_KEYFORGE, CARD_GAME_PTCG, CARD_GAME_LORCANA, CARD_GAME_ALTERED

blueprint = Blueprint()

@blueprint.command(r"cardview (yt )?(on|off)")
@lrrbot.decorators.mod_only
def set_cardview(bot, conn, event, respond_to, youtube, setting):
	"""
	Command: !cardview on
	Command: !cardview off
	Command: !cardview yt on
	Command: !cardview yt off
	Section: misc

	Toggle showing details of Magic cards in the chat when they are scanned by the card recogniser (for AFK Magic streams).
	"""
	if not youtube:
		bot.cardview = (setting == "on")
	bot.cardview_yt = (setting == "on")

	conn.privmsg(respond_to, "Card viewer %s" % ("enabled" if bot.cardview else "disabled"))

@blueprint.command(r"(?:card|mtg) (.+)")
@lrrbot.decorators.throttle(60, count=3)
def mtg_card_lookup(bot, conn, event, respond_to, search):
	"""
	Command: !card card-name
	Command: !mtg card-name
	Section: misc

	Show the details of a given Magic: The Gathering card.
	"""
	real_card_lookup(bot, conn, event, respond_to, search, game=CARD_GAME_MTG)

@blueprint.command(r"(?:kf|keyforge) (.+)")
@lrrbot.decorators.throttle(60, count=3)
def keyforge_card_lookup(lrrbot, conn, event, respond_to, search):
	"""
	Command: !keyforge card-name
	Command: !kf card-name
	Section: misc

	Show the details of a given KeyForge card.
	"""
	real_card_lookup(lrrbot, conn, event, respond_to, search, game=CARD_GAME_KEYFORGE)

@blueprint.command(r"(?:pok[eé]mon|pok[eé]|pkmn|ptcg) (.+)")
@lrrbot.decorators.throttle(60, count=3)
def pokemon_card_lookup(lrrbot, conn, event, respond_to, search):
	"""
	Command: !pokemon card-name
	Command: !ptcg card-name
	Section: misc

	Show the details of a given Pokémon TCG card.
	"""
	real_card_lookup(lrrbot, conn, event, respond_to, search, game=CARD_GAME_PTCG)

@blueprint.command(r"(?:lorcana) (.+)")
@lrrbot.decorators.throttle(60, count=3)
def lorcana_card_lookup(bot, conn, event, respond_to, search):
	"""
	Command: !lorcana card-name
	Section: misc

	Show the details of a given Disney Lorcana TCG card.
	"""
	real_card_lookup(bot, conn, event, respond_to, search, game=CARD_GAME_LORCANA)

@blueprint.command(r"altered(?:tcg)? (.+)")
@lrrbot.decorators.throttle(60, count=3)
def altered_card_lookup(bot, conn, event, respond_to, search):
	"""
	Command: !altered card-name
	Command: !alteredtcg card-name
	Section: misc

	Show the details of a given Altered TCG card.
	"""
	real_card_lookup(bot, conn, event, respond_to, search, game=CARD_GAME_ALTERED)

def real_card_lookup(bot, conn, event, respond_to, search, noerror=False, includehidden=False, game=CARD_GAME_MTG):
	cards = find_card(bot, search, includehidden, game)

	if noerror and len(cards) != 1:
		return

	if len(cards) == 0:
		conn.privmsg(respond_to, "Can't find any card by that name")
	elif len(cards) == 1:
		conn.privmsg(respond_to, cards[0][1])
	elif len(cards) <= 5:
		conn.privmsg(respond_to, "Did you mean: %s" % '; '.join(card[0] for card in cards))
	else:
		conn.privmsg(respond_to, "Found %d cards you could be referring to - please enter more of the name" % len(cards))

def find_card(bot, search, includehidden=False, game=CARD_GAME_MTG):
	cards = bot.metadata.tables["cards"]

	cleansearch = clean_text(search)
	with bot.engine.connect() as conn:
		query = (sqlalchemy.select(cards.c.name, cards.c.text)
						.where(cards.c.filteredname == cleansearch))
		if game is not None:
			query = query.where(cards.c.game == game)
		rows = conn.execute(query).fetchall()
		if rows:
			return rows

		searchwords = search.split()
		searchwords = [clean_text(i) for i in searchwords]
		searchlike = "%" + "%".join(common.postgres.escape_like(i) for i in searchwords) + "%"
		query = (sqlalchemy.select(cards.c.name, cards.c.text)
						.where(cards.c.filteredname.like(searchlike)))
		if not includehidden:
			query = query.where(cards.c.hidden == False)
		if game is not None:
			query = query.where(cards.c.game == game)
		return conn.execute(query).fetchall()
