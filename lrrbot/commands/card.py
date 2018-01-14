import sqlalchemy

import lrrbot.decorators
from lrrbot.main import bot
import common.postgres
import common.time
from common.cardname import clean_text

@bot.command("cardview (on|off)")
@lrrbot.decorators.mod_only
def set_cardview(lrrbot, conn, event, respond_to, setting):
	"""
	Command: !cardview on
	Command: !cardview off
	Section: misc

	Toggle showing details of Magic cards in the chat when they are scanned by the card recogniser (for AFK Magic streams).
	"""
	lrrbot.cardview = (setting == "on")
	conn.privmsg(respond_to, "Card viewer %s" % ("enabled" if lrrbot.cardview else "disabled"))

@bot.command("card (.+)")
@lrrbot.decorators.throttle(60, count=3)
def card_lookup(lrrbot, conn, event, respond_to, search):
	"""
	Command: !card card-name
	Section: misc

	Show the details of a given Magic: the Gathering card.
	"""
	real_card_lookup(lrrbot, conn, event, respond_to, search)

def real_card_lookup(lrrbot, conn, event, respond_to, search, noerror=False, includehidden=False):
	cards = find_card(lrrbot, search, includehidden)

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

def find_card(lrrbot, search, includehidden=False):
	cards = lrrbot.metadata.tables["cards"]
	card_multiverse = lrrbot.metadata.tables["card_multiverse"]
	card_collector = lrrbot.metadata.tables["card_collector"]

	if isinstance(search, int):
		query = (sqlalchemy.select([cards.c.name, cards.c.text])
						.select_from(card_multiverse.join(cards, cards.c.id == card_multiverse.c.cardid))
						.where(card_multiverse.c.id == search))
		if not includehidden:
			query = query.where(cards.c.hidden == False)
		with lrrbot.engine.begin() as conn:
			return conn.execute(query).fetchall()

	if isinstance(search, tuple):
		query = (sqlalchemy.select([cards.c.name, cards.c.text])
						.select_from(card_collector.join(cards, cards.c.id == card_collector.c.cardid))
						.where((card_collector.c.setid == search[0].lower()) & (card_collector.c.collector == search[1])))
		if not includehidden:
			query = query.where(cards.c.hidden == False)
		with lrrbot.engine.begin() as conn:
			return conn.execute(query).fetchall()

	cleansearch = clean_text(search)
	with lrrbot.engine.begin() as conn:
		query = sqlalchemy.select([cards.c.name, cards.c.text]).where(cards.c.filteredname == cleansearch)
		if not includehidden:
			query = query.where(cards.c.hidden == False)
		rows = conn.execute(query).fetchall()
		if rows:
			return rows

		searchwords = search.split()
		searchwords = [clean_text(i) for i in searchwords]
		searchlike = "%" + "%".join(common.postgres.escape_like(i) for i in searchwords) + "%"
		query = sqlalchemy.select([cards.c.name, cards.c.text]).where(cards.c.filteredname.like(searchlike))
		if not includehidden:
			query = query.where(cards.c.hidden == False)
		return conn.execute(query).fetchall()
