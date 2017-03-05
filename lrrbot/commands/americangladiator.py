import lrrbot.decorators
from lrrbot.main import bot

# Entered from https://en.wikipedia.org/wiki/American_Gladiators
GLADIATORS = {
    "Malibu": "Deron McBee",
    "Lace": "Marisa Pare and Natalie Lennox",
    "Zap": "Raye Hollitt",
    "Flame": "Nekole Hamrick",
    "Gemini": "Michael M. Horton",
    "Nitro": "Dan Clark",
    "Sunny": "Cheryl Baldinger",
    "Blaze": "Sha-ri Pendleton",
    "Bronco": "Robert Campbell",
    "Gold": "Tonya Knight",
    "Laser": "Jim Starr",
    "Jade": "T.C. Corrin",
    "Titan": "David Nelson",
    "Diamond": "Erika Andersch",
    "Ice": "Lori Fetrick",
    "Thunder": "Billy Smith",
    "Turbo": "Galen Tomlinson",
    "Storm": "Debbie Clark",
    "Tower": "Steve Henneberry",
    "Viper": "Scott Berlinger and Roger Stewart",
    "Atlas": "Philip Poteat",
    "Cyclone": "Barry Turner",
    "Elektra": "Salina Bartunek",
    "Havoc": "Matt Williams",
    "Sabre": "Lynn Williams",
    "Siren": "Shelley Beattie",
    "Sky": "Shirley Eson-Korito",
    "Dallas": "Shannon Hall",
    "Hawk": "Lee Reherman",
    "Jazz": "Victoria Gay",
    "Rebel": "Mark Tucker",
    "Tank": "Ed Radcliffe",
    "Nacho": "Drew Minns",
}


@bot.command("americangladiator (.+)")
@lrrbot.decorators.throttle(60, count=3)
def american_gladiator_lookup(lrrbot, conn, event, respond_to, search):
    """
    Command: !americangladiator gladiator-name
    Section: misc

    Show which actor(s) played a character in American Gladiators.
    """
    search_cleaned = search.strip().capitalize()

    if search_cleaned in GLADIATORS:
        conn.privmsg(respond_to, "%s was played by %s in American Gladiators" %
                                 (search_cleaned, GLADIATORS[search_cleaned]))
    else:
        conn.privmsg(respond_to, "Can't find any American Gladiator by that name")
