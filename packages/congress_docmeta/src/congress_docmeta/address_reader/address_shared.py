"""Shared address vocabulary and identity.

Narrow (publisher-boxed) and broad (page prose) readers import tokens and
geo helpers from here. The claim union lives in `address_extraction`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Literal

import pycountry
from msgspec_schemaorg.models import PostalAddress

from ._support import already_says, nkey
from ._support import load_schema_vocab
from ._support import strip_markup
from ._support import unescape_html_iteratively

# USPS street types, abbreviated and spelled out.
_STREET_TYPES = frozenset(
    """aly alley anx arc arcade ave av aven avenue byu bayou bch beach bnd bend blf bluff
    blvd boul boulevard br branch brg bridge brk brook bg burg byp bypass cp camp cyn canyon
    cpe cape cswy causeway ctr center centre cir circle clf cliff clb club cmn common cor
    corner ct cts court cv cove crk creek cres crescent crst crest xing crossing curv curve
    dl dale dm dam dv divide dr drive est estate expy expressway ext extension fls falls fry
    ferry fld field flt flat frd ford frst forest fwy freeway gdn garden gtwy gateway gln
    glen grn green grv grove hbr harbor hvn haven hts heights hwy highway hl hill hls hills
    holw hollow is island jct junction ky key knl knoll lk lake lndg landing ln lane lgt
    light loop mall mnr manor mdw meadow ml mill msn mission mt mount mtn mountain nck neck
    orch orchard oval park pkwy parkway pass path pike pne pine pl place pln plain plz plaza
    pt point prt port pr prairie radl radial rnch ranch rpds rapids rst rest rdg ridge riv
    river rd road rte route row rue run shr shore skwy skyway spg spring sq square st str
    street sta station stra strand smt summit ter terr terrace trce trace trak track trl
    trail tunl tunnel tpke turnpike un union vly valley via vw view vlg village vis vista
    walk way wls wells wy""".split()
)

# Streets whose name is the whole street: "1 Broadway".
_BARE_STREET_NAMES = frozenset({"broadway", "bowery", "boardwalk", "concourse", "esplanade"})

_DIRECTIONALS = frozenset(
    """n s e w ne nw se sw north south east west northeast northwest southeast
    southwest""".split()
)

_UNIT_WORDS = frozenset({"apt", "ste", "suite", "unit", "fl", "floor", "rm", "room"})

# ...and those that lead an address: "Shop 2, 100 Bourke Street".
_LEADING_UNIT_WORDS = _UNIT_WORDS | frozenset({"shop", "apartment", "level", "lvl", "lot", "office", "studio"})

# Sentence words; a street name is a name. Place names may still carry a
# handful of these as particles ("King of Prussia").
_PROSE_WORDS = frozenset(
    """a an and are as at am be been but by for from he her his how i if in is it its my no
    not of on or she so that the they these this those to was we what when who with you
    your""".split()
)

# Both particle sets describe lowercase words inside a Title Case name, but
# they answer different questions and are not interchangeable: a word in
# `_NAME_PARTICLES` is PART of the name ("Truth or Consequences" passes the
# place-name read with it), while a word in `_PLACE_NAME_PARTICLES` only lets
# the name CONTINUE past it and never ends one ("Kingdom of" is not a city) --
# merging them would let "Pizza in Chicago" read as a city.
_PLACE_NAME_PARTICLES = frozenset({"a", "an", "and", "by", "he", "in", "it", "no", "of", "on", "or", "she", "the"})

# Theme dummy addresses that shops forget to replace.
_PLACEHOLDER_TERMS = (
    "john doe",
    "jane doe",
    "your town",
    "your city",
    "your street",
    "your address",
    "your company",
    "your name",
    "anytown",
    "demo street",
    "example street",
    "lorem ipsum",
)


def _reads_as_a_placeholder(text: str) -> bool:
    flattened = nkey(text)
    return any(term in flattened for term in _PLACEHOLDER_TERMS)


# Postcode shapes, as fragments so every postcode regex is built from one definition.
_US_ZIP = r"\d{5}(?:-\d{4})?"

_CA_POSTCODE = r"[A-Za-z]\d[A-Za-z] ?\d[A-Za-z]\d"

_UK_POSTCODE = r"[A-Za-z]{1,2}\d[\dA-Za-z]? ?\d[A-Za-z]{2}"

# The two national shapes are named for the one country that writes them; a
# five-digit run is anyone's (Berlin, Paris, Madrid) and stays anonymous.
_ANY_POSTCODE = rf"(?:{_US_ZIP}|(?P<CA>{_CA_POSTCODE})|(?P<GB>{_UK_POSTCODE}))"

_ZIP = re.compile(rf"^{_US_ZIP}$")

_POSTCODE = re.compile(rf"\b{_ANY_POSTCODE}\b")

# ...and at the end of a run; a bare four-digit code only after a comma ("Cape
# Town, 8005"), or a unit number ("Suite 1140,") would pass for one.
_ENDS_WITH_POSTCODE = re.compile(rf"\b{_ANY_POSTCODE}[.,;:]*$|,\s*\d{{4}}[.,;:]*$")

_HOUSE_NUMBER = re.compile(r"^\d[\d\-/¼-¾⅐-⅞]*[A-Za-z]?$")

# An Open Location Code as written: "9HMC+7MH", "VJ2Q+R7". Letters that are
# vowels or easily confused with digits are not in the alphabet.
_PLUS_CODE = re.compile(r"\b[23456789CFGHJMPQRVWX]{4,8}\+[23456789CFGHJMPQRVWX]{2,7}\b", re.I)

# A boxed occupancy line is not a street: "Building 7", "Floor 2", "Suite 3".
# `fl` is in the unit list; "FL 33137" is still Florida and a ZIP.
_OCCUPANCY_LEAD = _LEADING_UNIT_WORDS | frozenset({"building", "bldg"})


def _is_occupancy_group(group: str) -> bool:
    """A comma-group that names a unit, not a place. Two-letter `FL` beside a
    postcode is the state; `Floor 2` and `Fl. 12` stay occupancy."""
    tokens = group.split()
    if not tokens:
        return False
    raw = tokens[0].strip(".#")
    if raw.lower() not in _OCCUPANCY_LEAD:
        return False
    rest = " ".join(t.strip(".,") for t in tokens[1:])
    if raw == "FL" and rest and _reads_as_a_postcode(rest):
        return False
    return True


def _reads_as_a_postcode(text: str) -> bool:
    """US/CA/UK shapes, or the four or five digits most of the world writes -- unless a year."""
    code = text.strip(" .,;:")
    if _POSTCODE.fullmatch(code):
        return True
    return code.isdigit() and len(code) in (4, 5) and not _is_a_year(code, _LEADING_YEARS)


# A street name is words, and words have accents: "Sainte-Émilie", "Straße".
_NAME_WORD = re.compile(r"^[^\W\d_][\w.'’\-]*$", re.UNICODE)  # noqa: RUF001 - curly apostrophes appear in street names

_NUMBERISH = re.compile(r"^[\d#]")

_ANY_DIGIT = re.compile(r"\d")


def _is_street_token(token: str) -> bool:
    """A word of a street name, a number in it, or the "&" of "Barnes & Noble Way"."""
    return token == "&" or bool(_NAME_WORD.match(token) or _NUMBERISH.match(token))


@lru_cache(maxsize=1)
def _us_state_tokens() -> frozenset[str]:
    tokens = set()
    for subdivision in pycountry.subdivisions.get(country_code="US") or ():
        tokens.add(subdivision.code.rsplit("-", 1)[-1].upper())
        tokens.add(subdivision.name.upper())
    return frozenset(tokens)


def _is_us_state(token: str) -> bool:
    return token.upper() in _us_state_tokens()


def _is_written_us_state_token(token: str) -> bool:
    """A US state as an address writes it: the code in capitals ("NV"), never "in" or "or"."""
    name = token.strip(".,")
    return bool(name) and _is_us_state(name) and (len(name) > 2 or name.isupper())


def _names_a_us_state(text: str) -> bool:
    return any(_is_written_us_state_token(w) for w in text.split())


@lru_cache(maxsize=1)
def _us_state_name_to_code() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for subdivision in pycountry.subdivisions.get(country_code="US") or ():
        code = subdivision.code.rsplit("-", 1)[-1].upper()
        mapping[code] = code
        mapping[subdivision.name.upper()] = code
    return mapping


@lru_cache(maxsize=1)
def _province_codes() -> frozenset[str]:
    """Canadian provinces and Australian states, the two countries whose region
    codes a page writes after a city the way it writes "Chicago, IL" ("Sydney,
    NSW 2000", "Halifax, NS B3H 4R2"). Other countries' codes are words ("TV"
    is Treviso, "BA" Bahia and a degree) and are read only with a country.
    SA and WA are excluded on purpose: WA is Washington first, and SA would
    read as one more state-shaped code a credential or a salutation could
    share ("Sam Smith, SA" is a person).
    """
    codes: set[str] = set()
    for country in ("CA", "AU"):
        for subdivision in pycountry.subdivisions.get(country_code=country) or ():
            codes.add(subdivision.code.rsplit("-", 1)[-1].upper())
    return frozenset(codes - {"SA", "WA"})


def _us_state_codes_in(text: str) -> set[str]:
    folded = _us_state_name_to_code()
    return {folded[w.strip(".,").upper()] for w in text.split() if _is_written_us_state_token(w)}


@lru_cache(maxsize=1)
def _region_tokens() -> frozenset[str]:
    """Every subdivision and country name and code the world uses, folded."""
    tokens: set[str] = set()
    for subdivision in pycountry.subdivisions:
        tokens.update((nkey(subdivision.name), subdivision.code.rsplit("-", 1)[-1].lower()))
    for country in pycountry.countries:
        tokens.update((nkey(country.name), country.alpha_2.lower(), country.alpha_3.lower()))
    return frozenset(tokens)


def _is_a_known_region(text: str) -> bool:
    """A region the world names ("Quebec", "VIC", "IL"), a code only in capitals: "La" is not Louisiana."""
    name = text.strip(" .,")
    return bool(name) and nkey(name) in _region_tokens() and (len(name) > 3 or name.isupper())


def _is_a_region_code(text: str) -> bool:
    """A region written as its code ("IL", "QC", "NSW"): never also a city's name, unlike "Paris" or "York"."""
    name = text.strip(" .,")
    return 2 <= len(name) <= 3 and name.isupper() and nkey(name) in _region_tokens()


# Name particles that stay lowercase inside a proper name ("King of Prussia",
# "Rio de Janeiro", "Truth or Consequences", "Via del Corso", "Frankfurt am
# Main", "Monterosso al Mare").
_NAME_PARTICLES = frozenset(
    "de del della der den des du da do dos das la le les los las el il van von of or the upon on e y am al".split()
)

# Sentence punctuation a place name never carries.
_NOT_IN_A_PLACE_NAME = re.compile(r"[:;!?/\\|]|[A-Za-z]\.[A-Za-z]")  # "David.H." is a handle, not a town

# Titles a page puts before a person, never before a place.
_HONORIFICS = frozenset("dr mr mrs ms mx prof rev sen rep hon sir dame fr".split())

# Words that open a salutation, an answer, or a numbered part of a document.
# None of them opens a city, and each is followed by a comma often enough to be
# read as one ("Best Regards, ME", "Yes, OK", "Chapter One, IN", "Table 4, 2020").
_NOT_A_CITY_OPENER = frozenset(
    """dear hi hello hey thanks thank regards sincerely best love cheers yours kind warm
    yes no ok okay well sure sorry please congratulations welcome goodbye
    chapter page table figure fig vol volume step size version round track season episode
    grade model plan part section note item lot edition issue series level tier phase""".split()
)

# Title-cased words a promotion or a byline puts before a city, which no city
# name carries inside it: "Visit Beautiful Portland", "Grand Opening Austin",
# "Now Hiring Denver", "Ashley Garden City". A city keeps such words only at
# its ends -- Garden City, KS keeps Garden at the front, Kansas City keeps
# City at the back -- so they are judged away from the ends.
_NOT_A_CITY_WORD = frozenset("beautiful opening hiring garden bears".split())

_NOT_INSIDE_A_CITY = _PROSE_WORDS | _NOT_A_CITY_WORD


def _reads_as_a_place_name(text: str) -> bool:
    """A city as a page writes one: at most five words, each capitalised or a
    particle, no digit, no sentence punctuation. "Deep Dish Pizza Restaurant in
    Chicago" and "logo Red Derby" are prose that happens to end in a city."""
    words = [w.strip(".,'\"") for w in text.split() if w.strip(".,'\"")]
    if not words or len(words) > 5 or _ANY_DIGIT.search(text) or _NOT_IN_A_PLACE_NAME.search(text):
        return False
    if not words[0][:1].isalpha() or words[0].islower():
        return False
    # "Dr. Fardows Salim" and "Daniel B. Block" are people: an honorific or an
    # initial in the words; "S." and "N." are directionals and stay.
    raw = text.split()
    if words[0].lower() in _NOT_A_CITY_OPENER or words[-1].lower() in _PLACE_NAME_PARTICLES:
        return False  # "Best Regards", "Chapter One", "Kingdom of"
    if raw[0].strip(".").lower() in _HONORIFICS or any(
        len(w) == 2 and w[1] == "." and w[0].isalpha() and w[0].lower() not in _DIRECTIONALS for w in raw
    ):
        return False
    # A capitalised English word inside the name is a headline, not a city:
    # cities lowercase their particles ("Truth or Consequences") and keep
    # these words, when they carry them at all, at their ends ("Garden City").
    for word in words[1:-1]:
        lowered = word.lower()
        if not word.islower() and lowered not in _NAME_PARTICLES and lowered in _NOT_INSIDE_A_CITY:
            return False  # "Live From New York", "Grand Opening Austin"
    return all(not w.islower() or w in _NAME_PARTICLES for w in words)


# The countries of the United Kingdom, which ISO does not list and pages write.
_HOME_NATIONS = frozenset({"england", "scotland", "wales", "northern ireland"})


def _country_from_token(token: str, *, us_state_wins: bool) -> str | None:
    """The alpha-2 code this token names. A lone token that is a US state ("GA")
    stays a region; a trailing one after a region ("QC, Canada") may be the country."""
    name = token.strip().rstrip(",")
    if not name or (us_state_wins and _is_us_state(name)):
        return None
    if len(name) <= 3 and not name.isupper():
        return None  # "at" is a preposition; "AT" is Austria, "in" India, "us" a pronoun
    if name.upper() == "UK" or name.lower() in _HOME_NATIONS:
        return "GB"
    try:
        return pycountry.countries.lookup(name).alpha_2
    except LookupError:
        return None


def _split_region_and_country(region: str) -> tuple[str, str]:
    """Separate the country `usaddress` merged into `StateName` ("QC, Canada").

    US is claimed only for an actual US state -- never from a state-shaped
    token ("Tokyo, JP") or five digits, which France and Germany write too.
    """
    parts = [part.strip() for part in (region or "").split(",") if part.strip()]
    country = None
    if parts:
        country = _country_from_token(parts[-1], us_state_wins=len(parts) == 1)
        if country:
            parts = parts[:-1]
    remaining = ", ".join(parts)
    # Written as a state: "IL", "Illinois" -- not a name particle the tagger
    # filed there ("Catacombes De Paris" is not in Delaware, "Rio In" not in Indiana).
    if not country and remaining and _is_written_us_state_token(remaining):
        country = "US"
    return remaining, country or ""


@dataclass(frozen=True)
class PlaceParts:
    """The postal roles a string or a PostalAddress already named.

    Two questions: `admits` -- is this worth reporting at all (a door, even
    unplaced, or a resolvable place); `resolvable` -- can a geocoder answer it
    as written: a door plus a region, postcode, or country; a Plus Code; or a
    city plus a region, a country, or a postcode written in a national shape.
    A city is a place worth pinning (decided 2026-09-19); a city beside a bare
    four-digit number is not ("Catacombes De Paris, 1861" is a year). Empty
    means the input did not name it.
    """

    door: str = ""
    locality: str = ""
    region: str = ""
    postcode: str = ""
    country: str = ""

    def resolvable(self) -> bool:
        if self.door and _PLUS_CODE.search(self.door):
            return True
        if self.door:
            return bool(self.postcode or self.region or self.country)
        return bool(self.locality) and bool(self.region or self.country or _POSTCODE.fullmatch(self.postcode))

    def admits(self) -> bool:
        return bool(self.door) or self.resolvable()


def _is_address_shaped_token(token: str) -> bool:
    """A particle, directional, region, or postcode -- still inside the address."""
    text = token.strip(".,")
    if not text:
        return False
    lowered = text.lower()
    if lowered in _PLACE_NAME_PARTICLES or lowered in _DIRECTIONALS:
        return True
    return _reads_as_a_postcode(text) or _is_written_us_state_token(text) or _is_a_known_region(text)


def _trimmed_place_name(locality: str, *, following: str = "") -> str:
    """The city words, stopping before a token that is no longer address-shaped.

    Extra Title Case is still the city while the next token is a particle,
    directional, region, or postcode; or while the first word is a directional
    ("North Redwood City Heights") or too short to be the city by itself
    ("Ann Arbor", "Glen Burnie", "San Francisco"). "Chicago Obama Foundation"
    stops at Chicago: Chicago is a city name, and Foundation is not address-shaped.
    """
    text = locality.strip()
    if not text or not text[0].isalpha() or _ANY_DIGIT.search(text):
        return ""
    if _NOT_IN_A_PLACE_NAME.search(text):
        return ""
    words = [w.strip(".,'\"") for w in text.split() if w.strip(".,'\"")]
    if not words:
        return ""
    if words[0].lower() in _PROSE_WORDS and len(words[0]) > 1:
        return ""
    first = words[0]
    first_low = first.lower()
    directional_head = first_low in _DIRECTIONALS
    short_head = len(first) <= 4
    follow = [w.strip(".,'\"") for w in following.split() if w.strip(".,'\"")]

    def nxt(index: int) -> str:
        if index + 1 < len(words):
            return words[index + 1]
        return follow[0] if follow else ""

    kept = [first]
    for index in range(1, len(words)):
        word = words[index]
        lowered = word.lower()
        if lowered in _PROSE_WORDS and lowered not in _PLACE_NAME_PARTICLES and lowered not in _NAME_PARTICLES:
            break
        if lowered in _NAME_PARTICLES or lowered in _DIRECTIONALS or _is_a_known_region(word):
            kept.append(word)
            continue
        if word.isupper() and len(word) <= 3:  # "Brigham Young University BA" -- a credential, not the city
            break
        # A region or postcode after the words vouches for all of them ("Marina
        # Del Rey, CA 90292", "Rancho Palos Verdes, CA"); open-ended, the next
        # token must still be address-shaped ("Chicago Obama Foundation").
        closed = bool(follow)
        if word[:1].isupper() and (closed or _is_address_shaped_token(nxt(index)) or directional_head or short_head):
            kept.append(word)
            continue
        break
    return " ".join(kept)


def _locality_reads_like_a_place(locality: str, *, following: str = "") -> bool:
    """A city, not prose filed under a locality: no digits, no sentence
    punctuation, no opening preposition ("in Buffalo" -- which would point a
    geocoder at Buffalo, NY, for a street in Buffalo Grove, IL), no trailing
    proper noun after a one-word city unless a region or postcode still
    follows, and no prose in front of it ("Best in Arlington")."""
    text = locality.strip()
    words = [w.strip(".,'\"") for w in text.split() if w.strip(".,'\"")]  # "St. Louis" is St Louis
    return (
        bool(text) and _reads_as_a_place_name(text) and _trimmed_place_name(text, following=following).split() == words
    )


# A numbered highway as an address writes it: "US-51", "I-95", "IL-13", "SR-520".
_HIGHWAY = re.compile(r"^[A-Z]{1,3}-\d{1,4}[A-Z]?$")


def _names_a_street(group: str) -> bool:
    """A comma-group with a street word in it ("chemin Remembrance", "Spring St")."""
    return any(w.strip(".,").lower() in _ANY_STREET_WORD or _HIGHWAY.match(w.strip(".,")) for w in group.split())


def _is_a_door_group(group: str) -> bool:
    """A comma-group that names a door: Plus Code, house number then a name, or
    a capitalised name then a house number. A bare number is not a street."""
    if _PLUS_CODE.search(group):
        return True
    tokens = group.split()
    if len(tokens) < 2:
        return False
    first = tokens[0].strip(",")
    if _HOUSE_NUMBER.match(first) or _NUMBERISH.match(first):
        # A 4- or 5-digit number beside one name is a postcode and a city
        # ("2830 Willebroek"), not a house and a street -- unless the name is a
        # street word or a numbered highway ("14627 US-51").
        if _reads_as_a_postcode(first) and len(tokens) == 2:
            second = tokens[1].strip(".,")
            if second.lower() not in _ANY_STREET_WORD and not _HIGHWAY.match(second):
                return False
        return True
    last = tokens[-1].strip(",")
    first_name = tokens[0].strip(",")
    # "WA 98826" is a state and a ZIP, "Lajas 00667" a town and its code: a
    # number-last house number is never shaped like a postcode.
    if len(tokens) == 2 and _reads_as_a_postcode(last):
        return False
    # Nor is a region and the postcode written beside it ("NS B3H 4R2", "QC H2T 1S4").
    if len(tokens) == 3 and _reads_as_a_postcode(" ".join(tokens[-2:])) and _is_a_region_code(tokens[0].strip(",")):
        return False
    return bool(
        first_name[:1].isupper()
        and (_HOUSE_NUMBER.match(last) or _NUMBERISH.match(last))
        and not _is_a_year(last, _LEADING_YEARS)
    )


def _is_a_country_group(group: str) -> bool:
    return not _ANY_DIGIT.search(group) and _country_from_token(group, us_state_wins=True) is not None


def _closes_a_place(tail: str) -> bool:
    """Whether the words after a city's comma close it as an address writes
    them: a state code in capitals, alone or before a ZIP, a state or region in
    full, or a country by name. "Republic of", "Miranda", "RD" and "me" do not;
    nor does a bare code that is only a country's ("Movies, TV" is not Tuvalu).
    """
    text = tail.strip(" .")
    if not text:
        return False
    code, _, rest = text.partition(" ")
    if code.isupper() and (code in _us_state_tokens() or code in _province_codes()):
        return not rest or bool(_POSTCODE.fullmatch(rest.strip()))
    if text.upper() in _us_state_tokens() or _is_written_us_state_token(text):
        return True
    if (
        rest
        and _POSTCODE.fullmatch(rest.strip())
        and (code.upper() in _us_state_tokens() or _is_written_us_state_token(code))
    ):
        return True  # "California 90210"
    # A world subdivision list would admit "Miranda" (a Venezuelan state) and "TV" (Treviso);
    # a country by name may be two words ("New Zealand"), and "Republic of" is not one.
    return len(text) > 3 and _country_from_token(text, us_state_wins=False) is not None


def _peel_admin(group: str, *, placed: bool, city_read: bool, more: bool) -> tuple[str, str, str]:
    """Split a comma-group into (rest, region, postcode).

    A region written as a code ("IL", "QC") is peeled wherever it stands, and so
    is one that ends a group ("Chicago IL"). A region written as a NAME is also a
    city's name often enough (pycountry lists Paris, Berlin, Tokyo, York, New
    York, Washington) that it is peeled only after something was read (`placed`)
    and only when a city already was (`city_read`) or nothing but a country
    follows (not `more`): "Paris, France" is a city, "…, New York, NY 10012" is
    the city then the state, "…, Illinois" is the state.
    """
    tokens = group.split()
    postcode = region = ""
    if len(tokens) >= 2 and _reads_as_a_postcode(" ".join(tokens[-2:])):
        postcode = " ".join(tokens[-2:])
        tokens = tokens[:-2]
    elif tokens and _reads_as_a_postcode(tokens[-1]):
        postcode = tokens[-1]
        tokens = tokens[:-1]
    if tokens:
        whole, last = " ".join(tokens), tokens[-1]
        if _is_a_region_code(whole) or (placed and (city_read or not more) and _is_a_known_region(whole)):
            region, tokens = whole, []
        elif len(tokens) > 1 and (_is_a_region_code(last) or _is_written_us_state_token(last)):
            region, tokens = last, tokens[:-1]
    if tokens and _reads_as_a_postcode(tokens[0]):
        postcode = postcode or tokens[0]
        tokens = tokens[1:]
    return " ".join(tokens), region, postcode


def _place_parts_from_text(text: str) -> PlaceParts:
    """Roles of a comma-separated address, left to right. Occupancy is skipped;
    a locality has to read as a place name, not as prose that ends in one."""
    door = locality = region = postcode = country = ""
    groups = [g.strip() for g in text.split(",") if g.strip()]
    skip = False
    for index, group in enumerate(groups):
        if skip:
            skip = False
            continue
        if _is_occupancy_group(group):
            continue
        if not country and _is_a_country_group(group):
            country = group
            continue
        if not door and _is_a_door_group(group):
            door = group
            continue
        # A house number set off by a comma, as French writes it: "2000, chemin Remembrance".
        if not door and _HOUSE_NUMBER.match(group) and index + 1 < len(groups) and _names_a_street(groups[index + 1]):
            door, skip = f"{group} {groups[index + 1]}", True
            continue
        rest, peeled_region, peeled_code = _peel_admin(
            group,
            placed=bool(door or locality),
            city_read=bool(locality),
            more=any(not _is_a_country_group(g) for g in groups[index + 1 :]),
        )
        if peeled_region or peeled_code:
            region = peeled_region or region
            postcode = peeled_code or postcode
            group = rest
            if not group:
                continue
        if not locality and _reads_as_a_place_name(group) and not _is_a_region_code(group):
            # Trimming the way the tagger path does, closed by whatever address
            # still follows: "Kansas City" keeps City before "MO", while
            # "75004 Paris Ouvert Tous" -- nothing follows the group -- trims
            # to Paris rather than stating the French footer as the city.
            locality = _trimmed_place_name(group, following=", ".join(groups[index + 1 :]))
    return PlaceParts(door=door, locality=locality, region=region, postcode=postcode, country=country)


def _place_parts_from_structured(structured: PostalAddress) -> PlaceParts:
    """The parts a box names. A region or postcode is kept only when shaped like
    one: usaddress files whatever follows a street under `StateName` ("645
    Florida Avenue NW Visa, Master" arrives with the region "Master"). The
    locality is gated too -- "Visit Beautiful Portland" filed under `PlaceName`
    is a headline, not a city, and is dropped -- but the publisher already
    labelled this field `addressLocality`, so a name that reads as a place at
    all (`_reads_as_a_place_name`, which is what refuses the headline words
    `_NOT_INSIDE_A_CITY` names) stands whole rather than also having to survive
    the open-ended trim unchanged: that trim keeps a short first word ("Ann
    Arbor") but cuts a real city whose first word is longer ("Kansas City",
    "Frankfurt am Main") unless a region, postcode, or country closes it."""
    street = (structured.streetAddress or "").strip()
    door = street if street and (_ANY_DIGIT.search(street) or _PLUS_CODE.search(street)) else ""
    region = (structured.addressRegion or "").strip()
    region = region if _is_a_known_region(region) or _is_written_us_state_token(region) else ""
    postcode = (structured.postalCode or "").strip()
    postcode = postcode if _reads_as_a_postcode(postcode) else ""
    country = (structured.addressCountry or "").strip()
    locality = (structured.addressLocality or "").strip()
    following = " ".join(p for p in (region, postcode, country) if p)
    if locality and not (
        _reads_as_a_place_name(locality) or _locality_reads_like_a_place(locality, following=following)
    ):
        locality = ""
    return PlaceParts(
        door=door,
        locality=locality,
        region=region,
        postcode=postcode,
        country=country,
    )


# Attribute residue of a tag whose "<" was lost upstream: `li class="info-state"`.

_MARKUP_RESIDUE = re.compile(r"\bdiv style=\"[^\"]*\"|\b[a-z]+ class=\"[^\"]*\"")


def _plain_text(value: str) -> str:
    """Tags out, entities decoded. `strip_markup` also normalises whitespace, so
    it runs only on a string that carries a tag."""
    if "<" in value:
        value = strip_markup(value)
    return _MARKUP_RESIDUE.sub(" ", unescape_html_iteratively(value))


# Street words that lead the name ("Via del Corso") and that glue onto its end
# ("Bahnhofstrasse"); usaddress has no model for either.
_LEADING_TYPES = frozenset(
    """via viale piazza piazzale corso vicolo largo strada rue avenue boulevard chemin place quai
    calle avenida plaza paseo carrera carrer ronda camino rua travessa praca alameda estrada""".split()
)

# A street type where English puts it (trailing), and in any position.
_STREET_TYPE_WORDS = _STREET_TYPES | _BARE_STREET_NAMES

_ANY_STREET_WORD = _STREET_TYPE_WORDS | _LEADING_TYPES

# Numbers that read as a year: leading, 1900-2030 ("1537 7th St" is a house
# number); trailing a name, inside prose, the wider range.
_LEADING_YEARS = range(1900, 2031)


def _is_a_year(token: str, years: range) -> bool:
    return token.isdigit() and int(token) in years


# Japanese and Korean lines: usaddress has no tags for them, so they are
# noticed, not parsed -- a short line naming a division or road suffix and a number.
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


# How deep the prose readers look; the structured reader is uncapped (a
# `PostalAddress` sits up to eight levels down on real pages).
_PROSE_WALK_DEPTH = 8


# schema.org's Organization subtypes that are not also a Place, read from the
# project's own schema vocabulary (`Vocab.is_a`, multiple inheritance included):
# every LocalBusiness is both (a restaurant's box stands), as are
# EducationalOrganization (a CivicStructure) and Hospital. A Corporation's
# `address` is its seat, and a poem page carries the Poetry Foundation's, a
# helmet page Ruroc's. Only the box is skipped: a church typed Organization
# keeps its footer address. (Derived, not hand-listed: the previous hand list
# also carried ArchiveOrganization, which the vocabulary says is a
# LocalBusiness and so a place, and missed the plain-Organization medical,
# government and marketplace types.)
_SEAT_KEYS = frozenset({"address", "location", "geo"})


@lru_cache(maxsize=1)
def _organisation_types() -> frozenset[str]:
    vocabulary = load_schema_vocab()
    return frozenset(
        kind
        for kind in vocabulary.classes
        if vocabulary.is_a(kind, "Organization") and not vocabulary.is_a(kind, "Place")
    )


def _is_an_organisation(node: dict) -> bool:
    """Whether every type the node declares is an organisation and not a place."""
    types = node.get("@type") or node.get("type")
    names = types if isinstance(types, list) else [types]
    return bool(types) and all(isinstance(n, str) and n.rsplit("/", 1)[-1] in _organisation_types() for n in names)


def _walk(
    node, *, max_depth: int | None, skip: frozenset[str] = frozenset(), depth: int = 0
) -> Iterator[tuple[str | None, object]]:
    """Every (key, value) in a nested payload, top-down; key is None for list items.
    Keys in `skip` are not entered, nor is the seat of a node typed as an organisation."""
    if max_depth is not None and depth > max_depth:
        return
    if isinstance(node, dict):
        seat = _SEAT_KEYS if _is_an_organisation(node) else frozenset()
        for key, value in node.items():
            if key in skip or key in seat:
                continue
            yield key, value
            yield from _walk(value, max_depth=max_depth, skip=skip, depth=depth + 1)
    elif isinstance(node, list):
        for value in node:
            yield None, value
            yield from _walk(value, max_depth=max_depth, skip=skip, depth=depth + 1)


# The people and organisations beside a page's subject are not its place: a
# recipe's JSON-LD carries Hearst Tower under `publisher`, an article its
# `author`'s office, a club's footer its parent company, a review the town it
# was written in, a profile the employer's city, a brand where it was founded
# (Tiger Balm in Rangoon). No reader looks under these.
_BYSTANDER_KEYS = frozenset(
    {
        "publisher",
        "parentOrganization",
        "author",
        "creator",
        "copyrightHolder",
        "sourceOrganization",
        "brand",
        "manufacturer",
        "funder",
        "sponsor",
        "locationCreated",
        "worksFor",
        "affiliation",
        "alumniOf",
        "memberOf",
        "foundingLocation",
        "birthPlace",
        "deathPlace",
    }
)


def _labelled_strings(data, keys: frozenset[str]) -> Iterator[str]:
    """String values sitting under one of `keys`, anywhere in the payload."""
    for key, value in _walk(data, max_depth=_PROSE_WALK_DEPTH, skip=_BYSTANDER_KEYS):
        if isinstance(key, str) and isinstance(value, str) and key.strip().lower() in keys:
            yield value


# Keys whose values are never prose: URLs, ids, images, and a provider's own
# structure -- its Plus Code, which restates the address it already labelled
# ("V9H5+3P Chicago, IL"), its address components, which read back joined as
# "USA The Meadowlark Chicago, Illinois", its reviewers and photo captions.
_NON_PROSE_KEYS = frozenset(
    {
        "@id",
        "@context",
        "@type",
        "url",
        "image",
        "logo",
        "sameAs",
        "thumbnail",
        "icon",
        "id",
        "src",
        "href",
        "plus_code",
        "compound_code",
        "global_code",
        "address_components",
        "addressComponents",
        "author_attributions",
        "photos",
    }
)


def _iter_metadata_text(data) -> list[str]:
    """Every human-written string in a scraped payload, in reading order."""
    strings = (
        [data]
        if isinstance(data, str)
        else [
            v
            for _, v in _walk(data, max_depth=_PROSE_WALK_DEPTH, skip=_NON_PROSE_KEYS | _BYSTANDER_KEYS)
            if isinstance(v, str)
        ]
    )
    out: list[str] = []
    for text in (value.strip() for value in strings):
        if len(text) > 12 and " " in text and not text.startswith(("http", "data:", "//")):
            out.append(text)
    return out


# One address written two ways is one address ("12 Fourth Street", "12 4th St").
_SAME_WORD = {
    "street": "st",
    "avenue": "ave",
    "aven": "ave",
    "boulevard": "blvd",
    "road": "rd",
    "drive": "dr",
    "lane": "ln",
    "court": "ct",
    "place": "pl",
    "square": "sq",
    "terrace": "ter",
    "terr": "ter",
    "parkway": "pkwy",
    "highway": "hwy",
    "route": "rte",
    "circle": "cir",
    "trail": "trl",
    "turnpike": "tpke",
    "expressway": "expy",
    "freeway": "fwy",
    "suite": "ste",
    "apartment": "apt",
    "floor": "fl",
    "north": "n",
    "south": "s",
    "east": "e",
    "west": "w",
    "northeast": "ne",
    "northwest": "nw",
    "southeast": "se",
    "southwest": "sw",
    "first": "1st",
    "second": "2nd",
    "third": "3rd",
    "fourth": "4th",
    "fifth": "5th",
    "sixth": "6th",
    "seventh": "7th",
    "eighth": "8th",
    "ninth": "9th",
    "tenth": "10th",
    "eleventh": "11th",
    "twelfth": "12th",
    "thirteenth": "13th",
    "fourteenth": "14th",
    "fifteenth": "15th",
    "sixteenth": "16th",
    "seventeenth": "17th",
    "eighteenth": "18th",
    "nineteenth": "19th",
    "twentieth": "20th",
    "usa": "us",
    "canada": "ca",
}

# Words that say nothing about which address this is.
_DROPPED_WORDS = frozenset({"united", "states"})


def _canonical(address: str) -> str:
    """The address with its spellings folded, for comparing two of them."""
    return " ".join(_SAME_WORD.get(w, w) for w in nkey(address).split() if w not in _DROPPED_WORDS)


def _variant_key(address: str) -> str:
    """The street and house number this variant names: cut at the street type, or
    the whole first comma-group when the number comes last ("Via del Corso 12").
    "St" / "Saint" before another street type is the name, not the type."""
    words = _canonical(address).split()
    if not words:
        return ""
    if not _NUMBERISH.match(words[0]):
        return _canonical(address.split(",")[0])
    for index, word in enumerate(words):
        if index and (word in _STREET_TYPE_WORDS or word == "saint"):
            if word in {"st", "saint"}:
                rest = words[index + 1 :]
                nxt = rest[0] if rest else ""
                if any(w in _STREET_TYPE_WORDS for w in rest) and nxt not in _DIRECTIONALS and nxt not in _UNIT_WORDS:
                    continue
            return " ".join(words[: index + 1])
    return " ".join(words[:4])


def _locality_hint(address: str, parts: PlaceParts | None = None) -> str:
    """The city this address names, folded, skipping units, regions and
    postcodes.

    "100 Main St, Suite 1, Boston" is Boston, not Suite. "Chicago, IL 60647"
    is Chicago, not IL. The whole name is kept, not just its first word, so
    "San Jose" and "San Francisco" are never read as the same city.
    """
    return _city_word(parts if parts is not None else _place_parts_from_text(address))


def _city_word(parts: PlaceParts) -> str:
    """The city these parts name, folded ("chicago", "new york", "washington dc")."""
    return nkey(parts.locality)


def _region_key(region: str) -> str:
    """A region folded for comparing two claims' notation: a US state folds to
    its code regardless of which way it is written ("Illinois" and "IL" both
    become "IL", via `_us_state_name_to_code()`); anything else -- a province,
    a country's own code -- has no such table and falls back to a plain fold."""
    return _us_state_name_to_code().get(region.strip().upper(), nkey(region))


def _same_city(hint_a: str, hint_b: str) -> bool:
    """Two folded localities (`_city_word`) name the same city: equal, or one
    is the other plus one trailing region token ("washington dc" is
    "washington"; "san jose" is not "san francisco")."""
    if not hint_a or not hint_b:
        return False
    if hint_a == hint_b:
        return True
    words_a, words_b = hint_a.split(), hint_b.split()
    shorter, longer = (words_a, words_b) if len(words_a) < len(words_b) else (words_b, words_a)
    return len(longer) == len(shorter) + 1 and longer[: len(shorter)] == shorter


def _after_house_number(text: str) -> str | None:
    """The remainder after the first token, or None when there is no remainder.

    None (not empty string) is a bare house number: "10123 Colvin Run Road"
    must not treat 10123 as a postcode.
    """
    if " " not in text:
        return None
    return text.split(maxsplit=1)[1]


def _postcode_key(code: str) -> str:
    """A postcode for comparing two addresses: a ZIP+4 names its ZIP ("97141-8312"
    is 97141), a UK or Canadian code its outward half."""
    words = nkey(code).split()
    return words[0] if words else ""


def _postcode_in_rest(rest: str) -> str:
    """The postcode this run names: an ending one first, else the last shaped code."""
    tail = _ENDS_WITH_POSTCODE.search(rest)
    if tail and _reads_as_a_postcode(tail.group(0)):
        return _postcode_key(tail.group(0))
    codes = [match.group(0) for match in _POSTCODE.finditer(rest)]
    return _postcode_key(codes[-1]) if codes else ""


def _postcode_hint(address: str, parts: PlaceParts | None = None) -> str:
    """The postcode this address names, skipping a leading house number."""
    code = (parts.postcode if parts is not None else _place_parts_from_text(address).postcode) or ""
    if code:
        return _postcode_key(code)
    rest = _after_house_number(address)
    return _postcode_in_rest(address if rest is None else rest)


def _streets_name_the_same_run(a: str, b: str) -> bool:
    """Same house and street, even when a venue name leads one of the strings."""
    street_a, street_b = _variant_key(a), _variant_key(b)
    if not street_a or not street_b:
        return False
    if street_a == street_b:
        return True
    # Containment is for a street inside a longer string ("4400 nw 87th ave" in
    # "trump national doral 4400 nw 87th ave ..."). A city's key ("chicago")
    # carries no digit, sits inside every address in that city, and names no run.
    return (bool(_ANY_DIGIT.search(street_a)) and already_says(street_a.split(), _canonical(b).split())) or (
        bool(_ANY_DIGIT.search(street_b)) and already_says(street_b.split(), _canonical(a).split())
    )


def _same_place(a: str, b: str, *, a_parts: PlaceParts | None = None, b_parts: PlaceParts | None = None) -> bool:
    """Same street, and the same place: matching postcodes join even when the
    city is spelled two ways; differing postcodes or cities do not. A missing
    city still joins when postcodes do not conflict. Springfield IL is not
    Springfield MA, even at the same number. Parts already computed by a
    caller are read rather than re-parsing the text.
    """
    if not _streets_name_the_same_run(a, b):
        return False
    hint_a, hint_b = _locality_hint(a, a_parts), _locality_hint(b, b_parts)
    code_a, code_b = _postcode_hint(a, a_parts), _postcode_hint(b, b_parts)
    if code_a and code_b:
        return code_a == code_b
    if hint_a and hint_b and not _same_city(hint_a, hint_b):
        return False
    if hint_a and hint_b:
        states_a, states_b = _us_state_codes_in(a), _us_state_codes_in(b)
        if states_a and states_b and states_a.isdisjoint(states_b):
            return False
    return True


def _collapse_variants(addresses: list[str]) -> list[str]:
    """One place stated many times is one address: the fullest reading of each
    street wins. A differing city splits the group ("100 Main St, Boston" is not
    "100 Main St, Austin"); a variant naming no city joins only when exactly
    one city already owns that street."""
    best: dict[tuple[str, str], tuple[tuple[int, int, int], str]] = {}
    hints_by_street: dict[str, list[str]] = {}

    def consider(address: str, hint: str) -> None:
        street = _variant_key(address)
        hints = hints_by_street.setdefault(street, [])
        matched = next(
            (h for h in hints if _same_place(address, best[(street, h)][1])),
            None,
        )
        slot = matched if matched is not None else hint
        if matched is None and (street, slot) in best:
            slot = "|".join((hint, _postcode_hint(address), "".join(sorted(_us_state_codes_in(address)))))
        key = (street, slot)
        completeness = _address_completeness(address)
        if key not in best:
            best[key] = (completeness, address)
            hints.append(key[1])
        elif completeness > best[key][0]:
            best[key] = (completeness, address)

    located, bare = [], []
    for address in addresses:
        if not _variant_key(address):
            continue
        (located if _locality_hint(address) else bare).append(address)
    for address in located:
        consider(address, _locality_hint(address))
    for address in bare:
        cities = [h for h in hints_by_street.get(_variant_key(address), []) if h]
        if len(cities) == 1:
            consider(address, cities[0])
        elif not cities:
            consider(address, "")

    return [address for _, address in best.values()]


def _address_completeness(address: str) -> tuple[int, int, int]:
    """A postcode first, then fields separated, then length -- not length alone."""
    has_postcode = 1 if _carries_a_postcode(address) else 0
    return (has_postcode, address.count(","), len(address))


# Where a payload states what the page is called (`publisher` holds a domain).
_PAGE_NAME_KEYS = frozenset({"title", "name", "og:title", "headline", "legalname"})


def _page_names(data) -> set[str]:
    """What this page calls itself, normalised."""
    return {nkey(value) for value in _labelled_strings(data, _PAGE_NAME_KEYS) if 2 < len(value) < 120}


def _reads_as_the_page_s_own_name(address: str, names: set[str]) -> bool:
    """Whether this "address" is what the page calls itself: "Proper 21 K Street"
    is a bar, and its prose reading "21 K Street Christopher O'Connor Proper"
    geocodes cleanly to the wrong place. Only a claim with no postcode, comma
    or state is judged; a venue may be named for its address ("230 Fifth")."""
    if not names or _POSTCODE.search(address) or "," in address or _names_a_us_state(address):
        return False
    words = [w.strip(".,").lower() for w in address.split()]
    street = _variant_key(address)
    if not street or not any(street in name for name in names):
        return False
    # What gives a name away is the words riding along that no address has, appearing in the name too.
    extras = [
        w
        for w in words[len(street.split()) :]
        if w and w not in _DIRECTIONALS and w not in _UNIT_WORDS and not _NUMBERISH.match(w)
    ]
    return bool(extras) and any(any(e in name for e in extras) for name in names)


def _already_said(new: str, said: str, *, new_parts: PlaceParts, said_parts: PlaceParts) -> bool:
    """Whether a claim already kept (`said`, canonical) covers `new` -- whole
    words, so "1 Main St" is not inside "11 Main St". It does when it says all
    of `new`, or when `new` says all of it and adds no part: "USA Vail, CO
    81657" beside "Vail, CO 81657" is longer, not news. "2207 N Clybourn Ave,
    Chicago, IL 60614" beside "Chicago, IL" adds a door and is."""
    wn, ws = new.split(), said.split()
    if not (wn and ws):
        return False
    if already_says(wn, ws):
        return True
    return already_says(ws, wn) and not any(
        getattr(new_parts, part) and not getattr(said_parts, part)
        for part in ("door", "locality", "region", "postcode", "country")
    )


Source = Literal["declared", "labelled", "page", "metadata"]


@dataclass(frozen=True)
class AddressClaim:
    """One address a link states, and what backs it.

    `stated` records syntactic completeness under `PlaceParts.resolvable`
    (or the CJK prose reader). It establishes neither relevance to the saved
    subject nor provider identity. Consumers authorize those separately.
    `parts` contain only roles the source supplied; `source` records how the
    observation was found. Unselected observations remain suggestions.
    """

    text: str
    source: Source  # publisher JSON-LD, a provider's address field, page text, metadata prose
    stated: bool
    structured: PostalAddress | None = None
    parts: PlaceParts = field(default_factory=PlaceParts)


def _carries_a_postcode(text: str) -> bool:
    """A postcode after the house number -- "10123 Colvin Run Road" carries none."""
    rest = _after_house_number(text)
    return bool(rest is not None and _postcode_in_rest(rest))


def _place_parts(text: str, structured: PostalAddress | None = None, *, complete: bool = False) -> PlaceParts:
    """The parts a claim names: the box first, the text when the box is not
    enough. A CJK line the prose reader shaped (`complete`) is its own door: the
    reader proved a block or road number inside it, which no Latin parse sees.
    A country the box inferred but the text's own words never wrote is dropped
    ("USA Vail, CO 81657" beside "Vail, CO 81657" is a restatement, not news),
    so the box cannot add a part the reading does not say."""
    if complete:
        return PlaceParts(door=text)
    from_text = _place_parts_from_text(text)
    if not structured:
        return from_text
    parts = _place_parts_from_structured(structured)
    if not parts.resolvable():
        return from_text
    if parts.country and not from_text.country:
        parts = replace(parts, country="")
    return parts


def _has_a_us_zip(text: str) -> bool:
    return any(_ZIP.fullmatch(match.group(0).strip(" .,;:")) for match in _POSTCODE.finditer(text))


def _has_a_four_digit_postcode(text: str) -> bool:
    """A trailing four-digit group ("WA, 6000" / "WA 6000"), not a unit ("Suite 1140")."""
    groups = [g.strip().strip(".") for g in text.split(",") if g.strip()]
    last = groups[-1] if groups else text.strip().strip(".")
    if last.isdigit() and len(last) == 4:
        return True
    tokens = last.split()
    return bool(tokens) and tokens[-1].isdigit() and len(tokens[-1]) == 4


def _written_us_state_in(text: str) -> bool:
    """A US state as an address writes it: the code in capitals ("NV"), never "in" or "or".

    Four digits beside WA are Perth, not a US ZIP; a five-digit code still lets
    "Vancouver, WA 98665" say United States.
    """
    if _has_a_four_digit_postcode(text) and not _has_a_us_zip(text):
        return False
    return _names_a_us_state(text)


def country_code(claim: AddressClaim) -> str | None:
    """The ISO alpha-2 country a claim names, for a provider's `region_code`.

    Only what the address itself says: a declared or trailing country ("USA",
    "Belgium"), a country name standing alone in a comma-group ("Japan"), a
    postcode whose FORMAT is national ("H2W 1X9", "SW1A 1AA"), or a written US
    state. Never inferred from a city or a province -- "CA" after a city is
    California, and "QC" alone names no country.
    """
    if claim.structured and claim.structured.addressCountry:
        return _country_from_token(claim.structured.addressCountry, us_state_wins=False)
    parts = claim.parts if claim.parts != PlaceParts() else _place_parts_from_text(claim.text)
    if parts.country:
        return _country_from_token(parts.country, us_state_wins=False)
    return _postcode_country(claim.text) or ("US" if _written_us_state_in(claim.text) else None)


def _postcode_country(text: str) -> str | None:
    """The country a postcode's format names -- see `_ANY_POSTCODE`."""
    return next((match.lastgroup for match in _POSTCODE.finditer(text) if match.lastgroup), None)

