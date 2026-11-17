"""Broad address path: find a postal address inside page prose.

Cleans once, then reads three ways — usaddress (number first), number-last
streets, and Japanese or Korean lines. The join applies this finder to page
text and to metadata prose.
"""

from __future__ import annotations

import re

import usaddress
from msgspec_schemaorg.models import PostalAddress

from ._support import nkey
from ._support import _LINK_TEXT_CONTENT
from .address_shared import (
    _ANY_DIGIT,
    _ANY_STREET_WORD,
    _BARE_STREET_NAMES,
    _CJK,
    _DIRECTIONALS,
    _ENDS_WITH_POSTCODE,
    _HOUSE_NUMBER,
    _LEADING_TYPES,
    _LEADING_UNIT_WORDS,
    _LEADING_YEARS,
    _NAME_PARTICLES,
    _NAME_WORD,
    _NOT_IN_A_PLACE_NAME,
    _NUMBERISH,
    _POSTCODE,
    _PROSE_WORDS,
    _STREET_TYPE_WORDS,
    _STREET_TYPES,
    _UK_POSTCODE,
    _UNIT_WORDS,
    _US_ZIP,
    PlaceParts,
    _closes_a_place,
    _country_from_token,
    _is_a_known_region,
    _is_a_year,
    _is_street_token,
    _is_us_state,
    _locality_reads_like_a_place,
    _names_a_us_state,
    _place_parts,
    _place_parts_from_text,
    _plain_text,
    _province_codes,
    _reads_as_a_place_name,
    _reads_as_a_placeholder,
    _reads_as_a_postcode,
    _split_region_and_country,
    _us_state_tokens,
)

# Tokens a US address runs to; a candidate nothing closed is cut here.
MAX_ADDRESS_TOKENS = 8

# One the page closed with a postal code may run this long (bounds the prefix scan).
_CLOSED_ADDRESS_TOKENS = 12

_MIN_ADDRESS_TOKENS = 2

# usaddress labels that open and close a candidate. Only a postal code closes:
# a unit ("Bldg 2") sits before the city.
_OPENING_TAG = "AddressNumber"

_CLOSING_TAGS = frozenset({"ZipCode"})

_CORE_TAGS = frozenset({"AddressNumber", "StreetName"})

# A US state as an address writes it after a city, derived from pycountry
# (shared) -- the strict list this module used to carry was its subset.
_STRICT_STATES = _us_state_tokens()


# Link text is the shared grammar; the target must admit whitespace and one
# level of parentheses: `[(212) 475-9531](tel:(212) 475-9531)`.
_MARKDOWN_LINK = re.compile(rf"!?\[({_LINK_TEXT_CONTENT})\]\((?:[^()\n]|\([^()\n]*\))*\)")

_BARE_URL = re.compile(r"<?\b(?:https?://|www\.)\S+>?")

_EMPHASIS = re.compile(r"\*\*|__|\\\*|\*")

_STRUCTURAL_LINE = re.compile(r"^[\s#*\-=_|>~`+.]*$")

_LINE_MARKER = re.compile(r"^[\s>#*\-+–—]+")  # a page's own dashes


# Phones, dates, times and hours ranges carry an address's digits; removed
# before tagging, where they would read as house numbers. A spaced range is
# hours only when a clock says so ("9am - 5pm", "10:00 - 6"); "12 - 14 High
# Street" is two house numbers.
_DATE_TIME = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b"
    r"|\b\d{1,2}:\d{2}(?::\d{2})?\s?(?i:[ap]\.?m\.?)?"
    r"|\b\d{1,2}:\d{2}(?::\d{2})?\s*(?i:[ap]\.?m\.?)?\s+[–—-]\s+\d{1,2}(?::\d{2})?\s*(?i:[ap]\.?m\.?)?(?![\d:])"
    r"|\b\d{1,2}(?::\d{2})?\s*(?i:[ap]\.?m\.?)\s+[–—-]\s+\d{1,2}(?::\d{2})?\s*(?i:[ap]\.?m\.?)?(?![\d:])"
    r"|\b\d{1,2}(?::\d{2})?\s*(?i:[ap]\.?m\.?)?\s+[–—-]\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?i:[ap]\.?m\.?)?(?![\d:])"
    r"|\b\d{1,2}(?::\d{2})?\s*(?i:[ap]\.?m\.?)?\s+[–—-]\s+\d{1,2}(?::\d{2})?\s*(?i:[ap]\.?m\.?)(?![\d:])"
    # unspaced, with am/pm on at least one side so "676-8" and "1044-14" stay house numbers
    r"|\b\d{1,2}(?::\d{2})?(?i:[ap]\.?m\.?)[–—-]\d{1,2}(?::\d{2})?(?i:[ap]\.?m\.?)?\b"
    r"|\b\d{1,2}(?::\d{2})?[–—-]\d{1,2}(?::\d{2})?(?i:[ap]\.?m\.?)\b"
)


_BRACKETS = re.compile(r"[()\[\]{}]")

# An uppercase state code and five digits, spaced or welded ("NY11937"), are a
# state and its ZIP and end the address: read on, the tagger takes "NY 11937
# Main Beach" for a house number on Main Street. Normalised, then a line break.
_STATE_ZIP = re.compile(rf"(?<![A-Za-z0-9])([A-Z]{{2}})[^\S\n]?({_US_ZIP})(?![0-9])")


def _end_line_after_state_zip(match: re.Match) -> str:
    state, postcode = match.group(1), match.group(2)
    return f"{state} {postcode}\n" if _is_us_state(state) else match.group(0)


# A page's inline separators -- a spaced dash, a bar, a bullet, the pin a
# caption puts before its address ("📍 2935 Pacific Avenue") -- read as line
# breaks. A digit on both sides is a house-number range ("12 - 14 High Street"),
# not a boundary; a label before a house number ("Beach – 219") still is.
_INLINE_SEPARATOR = re.compile(
    r"(?<!\d)[^\S\n][–—-][^\S\n]|[^\S\n][–—-][^\S\n](?!\d)|[|｜•·📍]"  # the page's own marks
)


_WHOLLY_PARENTHETICAL = re.compile(r"^[(\[][^()\[\]]*[)\]][\s.,;:]*$")

_EXTENSION = re.compile(r"(?i)\bext\.?\s*\d{2,6}\b")

# A month-first date ("Oct 22", "July 4th, 2024") is closed by the month, so it
# strips whatever a capitalised word after it turns out to be (a tour list's
# "Oct 22 Toronto, ON" still must lose its date). A day-first date ("21 June
# 2024") is not: run the other way, "45 May" or "10 Jan" is a house number
# and the start of a month-named street ("45 May St", "10 Jan Smuts Avenue"),
# so it strips only when nothing but a year or the end of the clause follows —
# never a capitalised word, which is the street continuing.
_TEXT_DATE = re.compile(
    r"(?i:\b(?:july|sep|january|november|may|dec|aug|april|feb|september|march|oct|august|june|jan|nov|february|december|apr|jul|sept|jun|october|mar)\b\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{4})?\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:july|sep|january|november|may|dec|aug|april|feb|september|march|oct|august|june|jan|nov|february|december|apr|jul|sept|jun|october|mar)\b\.?(?:,?\s*\d{4})?\b(?!\s+[A-Z]))"
)

_PHONE_RUN = re.compile(
    r"(?:\+\d{1,3}[ .\-]?)?\(?\d{3}\)?[ .\-]\d{3}[ .\-]\d{4}\b"  # (312) 661-1434, 312.661.1434
    r"|(?<![\d\-])\d{3}[ .\-]\d{4}(?![\d\-])"  # 542-5140
    r"|\b\d{1,3}[ .\-]\d{1,4}[ .\-]\d{3,4}[ .\-]\d{3,4}\b"  # 81 3-3210-0077 (country + area)
    r"|\b\d{3}\s\d{3}[ .\-]\s?\d{4}\b"  # 470 351- 3866
)


# A unit leading the address ("Shop 2, 100 Bourke Street") stops usaddress
# tagging the house number; dropped, since it is not what geocodes.
_LEADING_UNIT = re.compile(
    r"^(?:" + "|".join(sorted(_LEADING_UNIT_WORDS, key=lambda w: (-len(w), w))) + r")\s*\.?\s*[\w-]{1,6}\s*,\s*(?=\S)",
    re.IGNORECASE,
)

_COMMA_STATE_COUNTRY = re.compile(r",\s+(?:[A-Z]{2,3}|[A-Z][a-z]+)\b")

_ANY_LETTER = re.compile(r"[^\W\d_]")

# A day of the week, on its own, is as often the start of a place name ("Sun
# Prairie", "Sun City", "Sun Valley", "Mon Ami Gabi") as it is a hint of hours.
# The two-letter forms stay case-restricted (capitalised-first or all-lower)
# so they never eat a state code ("MO" is Missouri, not Monday).
_DAY_TOKEN = (
    r"(?i:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)[.,s]?"
    r"|(?:Mo|Tu|We|Th|Fr|Sa|Su|mo|tu|we|th|fr|sa|su)"
)

# An hours line, not a place name: two or more day tokens in a row ("Mon -
# Fri", "Su Mo Tu We", "Mon–Sat", "Mon, Tue"), joined by the short connectors
# a hours line uses between them.
_DAYS_RUN = re.compile(rf"\b(?:{_DAY_TOKEN})(?:[\s,/&\-\u2013\u2014]+(?:{_DAY_TOKEN})){{1,}}\b")

# A single day immediately closed by a time or a colon ("Sat 10am", "Sun: 9-5")
# is still hours, not a place; a day followed by anything else (a capitalised
# word, digits with no clock marker) is left alone.
_DAY_BEFORE_HOURS = re.compile(rf"\b(?:{_DAY_TOKEN})(?=\s*(?::|\d{{1,2}}(?::\d{{2}})?\s*(?i:[ap]\.?m\.?)))")


def _strip_hours_day_names(line: str) -> str:
    """Day names read as hours, not a place a page names after one: strip a run
    of two or more, or a single day right before a time or a colon."""
    return _DAY_BEFORE_HOURS.sub(" ", _DAYS_RUN.sub(" ", line))


_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")

# A social handle: the tagger drops the "@" and reads the name as a city.
_HANDLE = re.compile(r"(?<!\w)@\w{2,30}\b")

# A post office box is a mailbox, not a place, and neither is the town line under
# it ("PO Box 509 / Utica, IL 61373"; a recipe channel's fan mail in Meridian, ID).
# A street with a door beside the box is still a place.
_PO_BOX = re.compile(
    r"\b(?:P\.?\s?O\.?\s*Box|Post\s+Office\s+Box|Postfach|Bo[iî]te\s+postale|Apartado(?:\s+postal)?|Casella\s+postale|Postbus)\s+\d+\b",
    re.IGNORECASE,
)

# A range of house numbers written with an en dash ("500 to 530 6th St."); the tagger and the door rules read a hyphen.
_RANGE_DASH = re.compile(r"(?<=\d)[\u2013\u2014](?=\d)")

# The tail of a link whose text began on an earlier line: an Apple Maps guide
# card is "[heading\n\nsummary](/place?address=4903 1/2 Rainier Ave S, …)", read
# line by line. The destination is not prose.
_ORPHAN_DESTINATION = re.compile(r"\]\((?:[^()\n]|\([^()\n]*\))*\)")

# A company's legal seat in a page footer is the publisher's place, not the page's.
_LEGAL_SEAT = re.compile(
    r"^(?:registered\s+(?:office|address|in\b)|sede\s+legale|si[èe]ge\s+social|sitz\s+der\s+gesellschaft|"
    r"handelsregister|domicilio\s+social|statutaire\s+zetel|company\s+(?:no|number|registration))",
    re.IGNORECASE,
)


def _opens_with_a_house_number(text: str) -> bool:
    return bool(text) and bool(_HOUSE_NUMBER.match(text.lstrip("([").split(" ")[0]))


# usaddress makes better decisions about numbers if it sees the shape of the
# whole paragraph, so these replacements keep line endings rather than splitting.
def _clean_for_segmentation(text: str) -> str:
    """Drop layout -- markup, links, phones, dates -- and honour the page's boundaries."""
    lines = []
    box_town_next = False
    for raw_line in text.split("\n"):
        line = _ORPHAN_DESTINATION.sub(" ", _MARKDOWN_LINK.sub(r"\1", _plain_text(raw_line)))
        line = _RANGE_DASH.sub("-", line)
        line = _BARE_URL.sub(" ", line)
        line = _HANDLE.sub(" ", _EMAIL.sub(" ", line))
        line = _strip_hours_day_names(line)
        if _ANY_DIGIT.search(line):  # every pattern below needs a digit
            line = _DATE_TIME.sub(" ", _TEXT_DATE.sub(" ", _PHONE_RUN.sub(" ", _EXTENSION.sub(" ", line))))
            line = _STATE_ZIP.sub(_end_line_after_state_zip, line)
        # Boundaries only after links and phones are gone: a separator inside one was not one.
        for entry in _INLINE_SEPARATOR.sub("\n", line).split("\n"):
            # A line that is only a parenthetical is an aside ("(bet. 86th and 87th
            # Streets)") unless it opens with a house number. Then brackets are layout.
            stripped = entry.strip()
            if _LEGAL_SEAT.match(stripped):
                continue
            if _WHOLLY_PARENTHETICAL.match(stripped) and not _opens_with_a_house_number(stripped):
                continue
            entry = _BRACKETS.sub(" ", entry)
            if _STRUCTURAL_LINE.match(entry):
                continue
            if _PO_BOX.search(entry):
                entry = _PO_BOX.sub(" ", entry).strip(" ,•|:-")
                box_town_next = not _opens_with_a_house_number(entry)
                if box_town_next:
                    continue
            elif box_town_next:
                box_town_next = False
                if not _opens_with_a_house_number(entry.strip()):
                    continue
            lines.append(_LEADING_UNIT.sub("", _EMPHASIS.sub("", _LINE_MARKER.sub("", entry))))
    return "\n".join(lines)


def _tag_line_by_line(cleaned: str) -> tuple[list[tuple[str, str]], set[int], set[int]]:
    """Tag per line -- the unit a page writes an address in -- and return the line
    ends, since a candidate may still span them (street, then city), and the
    breaks it may not span: a sentence the tagger skipped between two lines
    separates them ("14 OZ" and "Delivering to Chicago 60602" sit a page
    apart), while a blank line or a word or three ("Chicago") may be the city."""
    tagged: list[tuple[str, str]] = []
    line_ends: set[int] = set()
    breaks: set[int] = set()
    sentence_between = False
    previous_was_a_city_line = False
    lines = [line for line in cleaned.split("\n") if line.strip()]
    taggable_by_digit = [bool(_ANY_DIGIT.search(line)) for line in lines]
    taggable = [
        digit or bool(_COMMA_STATE_COUNTRY.search(line)) for digit, line in zip(taggable_by_digit, lines, strict=True)
    ]
    for index, line in enumerate(lines):
        if not _ANY_LETTER.search(line) and not _POSTCODE.fullmatch(line.strip()):
            # A number alone -- "1,710" available rentals, "608" square feet, a
            # "7/10" rating -- opens nothing, and the city on the next line is not
            # its city. A postcode alone ("84003") may still close the address above.
            sentence_between = True
            continue
        if not taggable[index]:
            # A city written on its own line between the street and the
            # postcode ("68 Fairmount Ouest / Montréal (Quebec) / H2T 2M2") has
            # no digit; it is still the address's line, not a skipped sentence.
            words = line.split()
            # ...but not a name in front of the NEXT address ("Rep. Jerry Carl
            # (R-AL)" above "1330 Longworth House Office Building"): the line
            # after a city is its region or postcode, never a house number.
            between = 0 < index < len(lines) - 1 and taggable[index - 1] and taggable[index + 1]
            opens_an_address = between and _HOUSE_NUMBER.match(lines[index + 1].split()[0].strip(",")) is not None
            if not (between and not opens_an_address and len(words) <= 4 and words[0][:1].isupper()):
                sentence_between = sentence_between or len(words) > 3
                continue
        try:
            part = usaddress.parse(line)
        except Exception:  # usaddress raises bare exceptions on odd input
            continue
        if not part:
            continue
        tags = {tag for _, tag in part}
        if not taggable_by_digit[index] and not (tags & _CORE_TAGS or tags & {"PlaceName", "StateName"}):
            # This branch is reached only by a line usaddress calls a pure
            # Recipient (no AddressNumber/StreetName, no PlaceName or StateName
            # of its own): "Phoenix, Arizona", "Auckland, New Zealand", "Hours,
            # Menu, Order". "Sam Smith, MD" and "Yes, OK" never land here --
            # usaddress already knows US state codes and tags them PlaceName +
            # StateName on its own, so a "Name, ST" line reads as a city
            # whatever this gate does; that is an accepted cost the spend guard
            # checks against the provider's answer, not something visible here.
            # A short recipient-tagged line closed by a state, province or
            # country written in full ("Phoenix, Arizona", "Auckland, New
            # Zealand") is re-tagged and the reader grades it. "Hours, Menu,
            # Order" and "Sparkling, France NV" fail `_closes_a_place` and stay
            # prose between addresses, not the city of the door above.
            tail = line.partition(",")[2].strip(" .")
            code = tail.split(" ")[0]
            written_out = not (len(code) <= 3 and code.isupper())
            if len(line.split()) <= 4 and written_out and _closes_a_place(tail):
                comma_at = next((i for i, (token, _) in enumerate(part) if token.endswith(",")), len(part) - 1)
                part = [(token, "PlaceName" if i <= comma_at else "StateName") for i, (token, _) in enumerate(part)]
                tags = {"PlaceName", "StateName"}
            else:
                sentence_between = True
                continue
        # A line that is a whole place without a street ("Chicago, IL") after
        # another such line is the next entry of a list of cities, not the city
        # of the line above; a street above it is still joined to it.
        city_line = not (tags & _CORE_TAGS) and "PlaceName" in tags and bool(tags & {"StateName", "ZipCode"})
        # A labelled field ends whatever ran above it: a Croatian shop's footer puts
        # "Bank account:" and "VAT:" under its city, and the run carried both in.
        labelled_field = ":" in line
        if tagged and (sentence_between or labelled_field or (city_line and previous_was_a_city_line)):
            breaks.add(len(tagged))
        sentence_between = False
        previous_was_a_city_line = city_line
        tagged.extend(part)
        line_ends.add(len(tagged) - 1)
    return tagged, line_ends, breaks


def extract_address_segments(text: str) -> list[str]:
    """Cut page text into address candidates. Candidates are not yet addresses."""
    return _segments_from_cleaned(_clean_for_segmentation(text))


def _segments_from_cleaned(cleaned: str) -> list[str]:
    tagged, line_ends, breaks = _tag_line_by_line(cleaned)

    segments: list[str] = []

    def close(span: list[tuple[str, str]], *, closed_by_postcode: bool = False) -> None:
        if not span:
            return
        tags = {tag for _, tag in span}
        span = span[: _CLOSED_ADDRESS_TOKENS if closed_by_postcode else MAX_ADDRESS_TOKENS]
        candidate = " ".join(token for token, _ in span).strip()
        # A city with its state or its code is a whole place, whether usaddress called the
        # city a place or a landmark ("Ann Arbor, Michigan 48104"; "Beverly Hills, California 90210").
        # So is a name closed by a country as an address closes one ("Cape Town, South Africa");
        # the tagger has no country tag, and "Hours, Menu, Order" closes nothing.
        named_place = bool(tags & {"PlaceName", "LandmarkName", "Recipient"}) and (
            bool(tags & {"StateName", "ZipCode"}) or _closes_a_place(candidate.partition(",")[2])
        )
        if not (tags & _CORE_TAGS or named_place):
            return
        if candidate:
            segments.append(candidate)

    start = 0
    for index, (token, tag) in enumerate(tagged):
        if index in breaks:
            close(tagged[start:index])
            start = index
        if tag == _OPENING_TAG:
            # "12 Rue de Rivoli, 75004 Paris": a postcode after the street's comma is
            # the street's postcode, not the number of a new door.
            previous = tagged[index - 1][0] if index else ""
            follows = tagged[index + 1][0] if index + 1 < len(tagged) else ""
            if previous.endswith(",") and _POSTCODE.fullmatch(token) and follows[:1].isupper():
                continue
            close(tagged[start:index])
            # A house number ending a line is the end of something else; it opens nothing.
            start = index + 1 if index in line_ends else index
        elif tag in _CLOSING_TAGS:
            # Much of the world writes the code before the city ("…Paix, 75002
            # Paris"): a capitalised word after a code that follows a comma is
            # the city, and the address has not ended.
            follows = tagged[index + 1][0] if index + 1 < len(tagged) else ""
            previous = tagged[index - 1][0] if index else ""
            if previous.endswith(",") and follows[:1].isupper() and not _HOUSE_NUMBER.match(follows.strip(",")):
                continue
            close(tagged[start : index + 1], closed_by_postcode=True)
            start = index + 1
        elif tag == "Recipient" and len(token) > 1 and token.isupper() and token.isalpha():
            close(tagged[start:index])
            start = index + 1
    close(tagged[start:])
    return segments


_GLUED_TYPES = (
    "strasse",
    "straße",
    "gasse",
    "weg",
    "platz",
    "allee",
    "damm",
    "ufer",
    "steig",
    "straat",
    "laan",
    "plein",
    "gracht",
    "singel",
    "kade",
    "dijk",
    "gatan",
    "vagen",
    "vägen",
    "vej",
    "veien",
)

# A postcode beside a locality lets a typeless street ("Unter den Linden 5") stand.
_POSTCODE_LOCALITY = re.compile(
    r"^(?:"
    r"\d{4,5}\s+[^\W\d_][\w.\-]*"  # 10117 Berlin, 00186 Roma
    rf"|{_UK_POSTCODE}\s+[^\W\d_][\w.\-]*"  # NW1 6XE London
    r"|[^\W\d_][\w.\-]*\s+\d{4,5}"  # Berlin 10117
    r")",
    re.UNICODE,
)


# A month with a day after it has a street's shape: "June 21".
_MONTHS = frozenset(
    """january february march april may june july august september october november december
    jan feb mar apr jun jul aug sep sept oct nov dec""".split()
)


# A number-last house number; tighter than the leading form, it sits inside prose.
_TRAILING_NUMBER = re.compile(r"^\d{1,4}[A-Za-z]?(?:[-/]\d{1,4}[A-Za-z]?)?$")

_TRAILING_YEARS = range(1500, 2100)


def _reads_as_a_year(group: str) -> bool:
    """A month, a lowercase word where the locality should be ("aired 2021"), or a bare year."""
    tokens = [t.strip(".,") for t in group.split()]
    if any(t.lower() in _MONTHS for t in tokens):
        return True
    words = [t for t in tokens if not t.isdigit()]
    if words:
        return not all(t[:1].isupper() for t in words)
    return any(_is_a_year(t, _TRAILING_YEARS) for t in tokens)


def _name_before_number(tokens: list[str]) -> list[str] | None:
    """The name words of "<Name words> <number>", or None if not that shape."""
    if len(tokens) < 2:
        return None
    number = tokens[-1].strip(".,")
    if not _TRAILING_NUMBER.match(number) or _is_a_year(number, _TRAILING_YEARS):
        return None
    name = [t.strip(".,") for t in tokens[:-1]]
    if not all(_NAME_WORD.match(t) for t in name) or not name[0][:1].isupper():
        return None
    return name


def _is_capitalised_name_with_number(tokens: list[str]) -> bool:
    """ "<Proper name words> <number>", with no street type to vouch for it."""
    name = _name_before_number(tokens)
    if name is None or any(t.lower() in _MONTHS for t in name):
        return False
    return all(t[:1].isupper() for t in name if t.lower() not in _NAME_PARTICLES)


def _is_number_last_street(tokens: list[str]) -> bool:
    """ "<street words> <number>": a leading type and a capitalised name ("Via del
    Corso 12"), or one glued-type word ("Bahnhofstrasse 5"). Case matters --
    "place up to 90" is prose -- and a surname can end in -weg ("Matt Mullenweg 2")."""
    name = _name_before_number(tokens)
    if name is None:
        return False
    lowered = [t.lower() for t in name]
    if lowered[0] in _LEADING_TYPES:
        rest = [t for t in name[1:] if t.lower() not in _NAME_PARTICLES]
        return bool(rest) and all(t[:1].isupper() for t in rest)
    if len(name) != 1:
        return False
    return any(len(lowered[0]) > len(sfx) + 2 and lowered[0].endswith(sfx) for sfx in _GLUED_TYPES)


def number_last_segments(text: str) -> list[str]:
    """Candidates whose house number follows the street name, which the tagger never opens on."""
    return _number_last_from_cleaned(_clean_for_segmentation(text))


def _number_last_from_cleaned(cleaned: str) -> list[str]:
    out: list[str] = []
    for line in cleaned.split("\n"):
        if not _ANY_DIGIT.search(line):
            continue
        groups = [g.strip() for g in line.split(",")]
        for index, part in enumerate(groups):
            if not _ANY_DIGIT.search(part):
                continue
            tokens = part.split()
            while tokens and tokens[0].endswith(":"):  # "Address: Via del Corso 12"
                tokens = tokens[1:]
            street = None
            # The street must open its group: "Distributed with Matt Mullenweg 2" is prose.
            for end in range(min(len(tokens), 5), 1, -1):
                if _is_number_last_street(tokens[:end]):
                    street = " ".join(tokens[:end])
                    break
            if not street:
                # No type word ("Unter den Linden 5"): a following postcode and locality stand in.
                following = groups[index + 1] if index + 1 < len(groups) else ""
                if _POSTCODE_LOCALITY.match(following) and not _reads_as_a_year(following):
                    if 2 <= len(tokens) <= 5 and _is_capitalised_name_with_number(tokens):
                        street = " ".join(tokens)
                if not street:
                    continue
            # Carry following groups that read as a place ("00186 Roma, Italia");
            # skip a POI ("Barnes & Noble") so a later locality can still attach.
            tail = []
            for following in groups[index + 1 : index + 4]:
                if "&" in following:
                    continue
                if not _reads_as_a_number_last_place(following):
                    break
                tail.append(following)
            out.append(", ".join([street, *tail]))
    return out


def _reads_as_a_number_last_place(group: str) -> bool:
    """A comma-group after a number-last street: a postcode, region, or locality.

    A shop name is not a place; "&" is still a street token ("Barnes & Noble Way").
    """
    words = [w.strip(".") for w in group.split()]
    if not words or len(words) > 4:
        return False
    if not all(_is_street_token(w) for w in words):
        return False
    if _POSTCODE_LOCALITY.match(group):
        return True
    if any(_reads_as_a_postcode(w) for w in words):
        return True
    if _is_a_known_region(group) or any(_is_a_known_region(w) for w in words):
        return True
    return any(w[:1].isupper() for w in words) and all(w[:1].isupper() or w.lower() in _NAME_PARTICLES for w in words)


# The types a street may carry when it is all the address has (see below).
_EVERYDAY_STREET_TYPES = frozenset(
    """ave av aven avenue blvd boul boulevard cir circle ct cts court dr drive
    expy expressway fwy freeway hwy highway ln lane loop pkwy parkway pl place plz plaza
    pike rd road rte route row rue sq square st str street ter terr terrace trl trail tpke
    turnpike way wy""".split()
)

_EVERYDAY_STREET_WORDS = _EVERYDAY_STREET_TYPES | _BARE_STREET_NAMES | _LEADING_TYPES


def _street_wants_corroboration(street: str, *, has_locality: bool) -> bool:
    """A street alone is doubtful when its type is landscape ("2008 Grand Canyon")
    or its number is a year and no city follows ("2013 Green Mountain Book
    Award"); a postal code settles either."""
    tokens = street.split()
    words = [t.strip(".,;:!?()[]{}\"'").lower() for t in tokens[1:]]
    if not any(w in _EVERYDAY_STREET_WORDS for w in words):
        return True
    return _is_a_year(tokens[0].strip(",."), _LEADING_YEARS) and not has_locality


# A Japanese division (prefecture, city, ward...) and the block after it ("神南1-22-7").
_JAPANESE_DIVISIONS = ("都", "県", "府", "市", "区", "町", "村", "郡")

_JAPANESE_BLOCK = re.compile(
    r"\d+[-‐−ー]\d+[-‐−ー]\d+|\d+丁目|\d+番地?|\d+号|〒\s*\d{3}[-]?\d{4}"  # a page writes its own dashes
)

# A Korean road suffix with its number: "테헤란로 152". "으로" is toward, not a road.
_KOREAN_ROAD = re.compile(r"[가-힣]+(?:(?<!으)로|길)\s*\d")

# The label before an address ("住所:") and the map link after it.
_CJK_LABEL = re.compile(r"^[^\d]{0,14}[:：]\s*|^〒\s*")  # a fullwidth colon labels a fullwidth line

_CJK_TRAILER = re.compile(r"\s*(?:MAP|Map|地図|map)\s*$")


def _reads_as_a_cjk_address(line: str) -> bool:
    if not _CJK.search(line):
        return False
    if any(division in line for division in _JAPANESE_DIVISIONS) and _JAPANESE_BLOCK.search(line):
        return True
    return bool(_KOREAN_ROAD.search(line))


def _cjk_from_cleaned(cleaned: str) -> list[str]:
    out = []
    for raw in cleaned.split("\n"):
        if not _CJK.search(raw):
            continue
        line = _CJK_TRAILER.sub("", _CJK_LABEL.sub("", raw.strip(" \t-–—"))).strip()
        if 6 <= len(line) <= 60 and _reads_as_a_cjk_address(line):
            out.append(line)
    return out


def _street_reads_like_a_street(street: str, has_postal_code: bool) -> bool:
    tokens = street.split()
    if len(tokens) < 2 or len(tokens) > MAX_ADDRESS_TOKENS - 2:
        return False
    if not _HOUSE_NUMBER.match(tokens[0].strip(",")):
        return False

    raw_tokens = tokens[1:]
    name_tokens = [token.strip(".,;:!?()[]{}\"'") for token in raw_tokens]  # "Avenue!" is an avenue
    # A comma inside the street is the page's boundary ("1282 Photos, ROSE AVE
    # BAKERY" is two things), unless a quadrant follows it ("Mississippi Ave, SE").
    for index, token in enumerate(raw_tokens[:-1]):
        if token.endswith(",") and name_tokens[index + 1].lower() not in _DIRECTIONALS:
            return False
    words = [token.lower() for token in name_tokens]
    # One-letter words are Washington streets ("455 I St NW"); longer prose words disqualify.
    if any(word in _PROSE_WORDS and len(word) > 1 for word in words):
        return False
    if not all(_is_street_token(token) for token in name_tokens if token):
        return False
    # With a postal code the street needs no type; otherwise it must name one,
    # leading ("Rue Sainte-Émilie") or trailing ("Amsterdam Avenue NW").
    if has_postal_code:
        return True
    type_positions = [i for i, word in enumerate(words) if word in _STREET_TYPE_WORDS]
    if not type_positions:
        return False
    if type_positions[0] == 0 and len(words) > 1:
        stripped = [token.strip(".,;:!?()[]{}\"'") for token in name_tokens[1:]]
        return all(not token or _is_street_token(token) for token in stripped)
    return all(
        word in _DIRECTIONALS or word in _UNIT_WORDS or _NUMBERISH.match(word)
        for word in words[type_positions[-1] + 1 :]
    )


# A number then a lowercase unit is a quantity ("1 cup", "1 week"); the same
# words in Title Case are streets ("1500 Weeks Ave", "500 G St NW").
_UNIT_OF_MEASURE = frozenset(
    """cup cups ml g kg oz lb lbs tbsp tsp teaspoon teaspoons tablespoon tablespoons ounce
    ounces pound pounds pinch dash cloves grams litre liter litres liters
    pieces slices servings serving calorie calories cal kcal min mins hrs hour hours
    day days week weeks month months year years
    km mi mile miles inch inches ft foot feet sq sqft sqm
    comments votes likes views points""".split()
)

# Product words make a catalogue line wherever they sit ("155 Nike Vomero 18 Women's Road Running Shoes").
_PRODUCT_WORDS = frozenset("shoes shoe sneakers running racing women's men's kids size sizes".split())


def _reads_as_a_quantity(candidate: str) -> bool:
    words = [w.strip(".,;:") for w in candidate.split()]
    unit = next((w for w in words[1:] if not w.replace(",", "").isdigit()), "")  # "28, 000 sq"
    if unit.islower() and unit in _UNIT_OF_MEASURE:
        return True
    return any(w.lower() in _PRODUCT_WORDS for w in words)


# The facet a "streets in this ZIP" directory groups by, left dangling at the end.
_DIRECTORY_TAILS = frozenset(
    """county parish borough township district united states state province region
    area neighborhood neighbourhood city town""".split()
)

_ZIP_LED = re.compile(r"^\d{5}(?!\d)")


def _reads_as_a_zip_directory(candidate: str) -> bool:
    """A generated "streets in this ZIP" line: five digits, no comma, and a repeated
    facet ("Northwest Northwest") or a dangling one ("Lancaster County")."""
    if "," in candidate or not _ZIP_LED.match(candidate.strip()):
        return False
    lowered = [w.strip(".,").lower() for w in candidate.split()[1:]]
    meaningful = [w for w in lowered if len(w) > 1]
    if len(meaningful) != len(set(meaningful)):
        return True
    if lowered and lowered[-1] in _DIRECTORY_TAILS:
        return True
    return any(w in _PROSE_WORDS and len(w) > 1 for w in lowered)


# Given names after "St." that make it Saint: "14 Rhum St. James" is a rum.
_SAINT_NAMES = frozenset(
    """james john mary paul peter charles louis denis germain michel laurent martin george
    andrew patrick joseph anne catherine francis thomas nicholas stephen luke mark marks
    matthew clair claire tropez barth croix augustine ives helens albans andrews davids
    kitts lucia vincent moritz petersburg gallen emilie jean pierre antoine remy honore
    roch regis""".split()
)

_TRAILING_SAINT = re.compile(r"\bSt\.\s+([A-Z][a-z]+)")


def _reads_as_a_saint(candidate: str) -> bool:
    """ "<Name> St. <Saint>" with no street type after the saint ("26 St. John
    Street" is a street) and no postcode or state to overrule it."""
    if _POSTCODE.search(candidate) or _names_a_us_state(candidate):
        return False
    match = _TRAILING_SAINT.search(candidate)
    if not match or match.group(1).lower() not in _SAINT_NAMES:
        return False
    rest = candidate[match.end() :].split()
    return not (rest and rest[0].strip(".,").lower() in _STREET_TYPES)


# A street type with a word welded on ("avelogan"). Unlike `_STATE_ZIP` the
# split point must be guessed, so the token is refused rather than repaired.
_WELDED_STREET_TYPE = re.compile(r"^(?:ave|blvd|hwy|pkwy|rte)[a-z]{4,}$")


def _reads_as_welded(candidate: str) -> bool:
    """Judged on the street group alone: "Avellino" after the comma is a town."""
    words = [w.strip(".,;:").lower() for w in candidate.split(",")[0].split()]
    return any(_WELDED_STREET_TYPE.match(word) and word not in _ANY_STREET_WORD for word in words)


def _as_validated_address(segment: str) -> tuple[PostalAddress, bool] | None:
    """Tag one candidate and return it, with whether it carries a postcode,
    only if it is really an address. The flag is returned so the prefix scan
    can score on it without re-running the postcode regexes."""
    address = get_address_from_text_usaddress(segment)
    if address is None:
        return None

    street = (address.streetAddress or "").strip().rstrip(",")
    locality = (address.addressLocality or "").strip().rstrip(",")
    postal_code = (address.postalCode or "").strip().rstrip(",")
    # A postcode written in a national shape (ZIP, "H2T 2M2", "SW1A 1AA") vouches
    # for a street, read off the run's end when the tagger split it. A bare
    # four-digit number does not: "Edition of 1500" and "ca. 1785" are not codes.
    tail = _ENDS_WITH_POSTCODE.search(segment)
    regional = _REGION_THEN_POSTCODE.search(segment)
    has_postal_code = bool(
        _POSTCODE.fullmatch(postal_code)
        or (tail and _POSTCODE.fullmatch(tail.group(0).strip(" .,;:")))
        or (regional and _region_precedes(segment, regional))
    )

    if not street:
        region = (address.addressRegion or "").strip()
        # A state in a street-less run is set off as an address writes it -- the
        # name in full, a comma before the code, or a ZIP after it ("Baltimore,
        # Maryland", "Utica, IL 61373"). "FLOWING IN 2023" and "PACK DE 3" are headings.
        set_off = bool(region) and (
            len(region) > 2 or has_postal_code or bool(re.search(rf",\s*{re.escape(region)}\b", segment))
        )
        if " " in region and not (region.upper() in _STRICT_STATES or region in _province_codes()):
            region = region.split()[0]  # "NS B3H 4R2" is Nova Scotia and a postcode the tagger ran together
        has_valid_region = (
            (region.upper() in _STRICT_STATES or region in _province_codes())
            and set_off
            and (region.isupper() or len(region) > 2)
        )
        # A country in a street-less run is a name after a comma ("Paris, France");
        # a bare code is a word that happens to be one ("Movies, TV" is not Tuvalu,
        # "Moodisc HM 1482" not Heard Island, "Issued US 2010…" not America).
        named = re.search(r",\s*([A-Za-z][A-Za-z .'-]{3,}?)[.,;:]*$", segment)
        has_valid_country = (
            bool(address.addressCountry)
            and bool(named)
            and _country_from_token(named.group(1), us_state_wins=False) is not None
        )
        if not (locality and (has_valid_region or has_valid_country)):
            return None
    # Reject the run, not the locality: a shorter run then keeps the street.
    following = " ".join(part for part in ((address.addressRegion or "").strip(), postal_code) if part)
    if locality and not _locality_reads_like_a_place(locality, following=following):
        return None
    # A postal code vouches for a typeless street only beside a city ("50 books ... 10915").
    if street:
        if not _street_reads_like_a_street(street, has_postal_code and bool(locality)):
            return None
        if not has_postal_code and _street_wants_corroboration(street, has_locality=bool(locality)):
            return None
    return address, has_postal_code


def _best_address_in(segment: str) -> tuple[str, PostalAddress] | None:
    """The leading run of this candidate that carries the most address: more
    parts (postcode, city, region), then more street, then shorter -- so a menu
    heading after the address loses and a city and code after it win."""
    tokens = segment.split()
    parsed: dict[int, tuple[str, PostalAddress, bool]] = {}
    for end in range(_MIN_ADDRESS_TOKENS, len(tokens) + 1):
        candidate = " ".join(tokens[:end])
        # Junk is judged per prefix, and once a prefix reads as junk every longer one does.
        if _reads_as_junk(candidate):
            break
        validated = _as_validated_address(candidate)
        if validated is not None:
            parsed[end] = (candidate, *validated)

    best: tuple[tuple[int, ...], str, PostalAddress] | None = None
    for end, (candidate, address, postal_flag) in parsed.items():
        locality = (address.addressLocality or "").strip()
        # A part counts when it is shaped like one ("Obama" is no region); the
        # postcode flag is the one the validator already computed for this run.
        postal = 1 if postal_flag else 0
        region = 1 if _is_a_known_region(address.addressRegion or "") else 0
        # A run may not end inside its city ("...APT 11F, San"): it stops where the page
        # did -- a comma, the end, a postcode, a region -- or, for a city the page set
        # off with a comma, wherever the next word does not lengthen the city
        # ("..., Montréal La Courtepointe").
        city_words = len(locality.split())
        comma_before_city = 0 < city_words < end and tokens[end - city_words - 1].endswith(",")
        following = parsed.get(end + 1)
        next_locality = (following[1].addressLocality or "").strip() if following else ""
        city_continues = len(next_locality) > len(locality) and next_locality.startswith(locality)
        stops_where_the_page_did = (
            end == len(tokens)
            or tokens[end - 1].rstrip(".").endswith(",")
            or bool(postal)
            or bool(region)
            or (comma_before_city and not city_continues)
        )
        if locality and not stops_where_the_page_did:
            continue
        # A place followed by a bare year or a two-letter code is a dated or labelled
        # line, not a place ("Garnacha, Spain 2022" and "Sparkling, France NV" are wines).
        after = tokens[end].strip(".,;:)") if end < len(tokens) else ""
        if (
            not (address.streetAddress or "").strip()
            and after
            and (_is_a_year(after, _LEADING_YEARS) or (len(after) == 2 and after.isupper() and after.isalpha()))
        ):
            continue
        # A US state takes a five-digit ZIP; a four-digit number after it is a year
        # the tagger filed as the code ("Beverly Hills, California, 1958").
        if (
            not (address.streetAddress or "").strip()
            and _is_us_state((address.addressRegion or "").strip())
            and _is_a_year(tokens[end - 1].strip(".,;:)"), _LEADING_YEARS)
        ):
            continue
        # The budget past MAX_ADDRESS_TOKENS is for a unit and a city; a long run naming no city is not using it.
        if end > MAX_ADDRESS_TOKENS and not locality:
            continue
        score = (
            postal + (1 if locality else 0) + region,  # parts reached, before which parts
            postal,
            len((address.streetAddress or "").split()),  # more street is never junk
            -end,
        )
        if best is None or score > best[0]:
            best = (score, candidate, address)
    return (best[1], best[2]) if best else None


# A four-digit postcode written after its region code ("Sydney, NSW 2000",
# "Melbourne VIC 3000"). Year-shaped on its own, so it is read only in this company.
_REGION_THEN_POSTCODE = re.compile(r"\b(?:[A-Z]{2,3})\s+(\d{4})[.,;:]*$")


def _region_precedes(text: str, match: re.Match) -> bool:
    """Whether the code before this four-digit number is a region that writes its
    postcode that way -- an Australian state, a Canadian province -- never a US state,
    whose codes are five digits ("Nashville, TN 2020" is a year beside a state)."""
    before = text[: match.start(1)].split()
    return bool(before) and before[-1] in _province_codes() and before[-1] not in _STRICT_STATES


def _reads_as_junk(candidate: str) -> bool:
    """A placeholder, a product listing, or a street type with a word welded on."""
    return _reads_as_a_placeholder(candidate) or _reads_as_a_quantity(candidate) or _reads_as_welded(candidate)


# One reading of the prose: the text, the tagger's box when it vouches for
# that text, whether the reader shaped the whole line (CJK), and the parts the
# reader stands behind FOR THAT TEXT -- the grade the join spends, computed
# once so nothing outside the returned text can leak into it.
Reading = tuple[str, PostalAddress | None, bool, PlaceParts]


def _through_the_place(segment: str, parts: PlaceParts) -> str:
    """The segment up to the end of the place its parts name -- door, postcode,
    city, region, country -- so the French footer after the city is not stated
    as the address ("12 Rue de Rivoli, 75004 Paris Ouvert Tous Les Jours"
    ends at Paris). Each part is searched after the one before it, so a
    country named inside the city ("Mexico City, Mexico") still ends the place,
    and the cut never crosses a comma: a group the page set off after the
    place ("10000 Zagreb, Hrvatska") is the page's, not trailing prose."""
    end = 0
    for run in (parts.door, parts.postcode, parts.locality, parts.region, parts.country):
        if not run:
            continue
        found = segment.find(run, end)
        if found >= 0:
            end = found + len(run)
    if not end:
        return segment
    if segment[end:].lstrip(" ").startswith(","):
        return segment  # whole groups follow the place; the comma is the page's boundary
    return segment[:end].rstrip(" ,;:!?\"'")


def _find_addresses(text: str) -> list[Reading]:
    cleaned = _clean_for_segmentation(text)
    cjk = set(_cjk_from_cleaned(cleaned))
    untagged = set(_number_last_from_cleaned(cleaned)) | cjk

    def read(segment: str) -> Reading | None:
        if segment in untagged:
            # Whole-string screens only: a later prefix scan would not apply.
            if _reads_as_junk(segment) or _reads_as_a_saint(segment):
                return None
            # CJK already passed the JP/KR shape check; number-last still needs parts.
            if segment in cjk:
                return segment, None, True, PlaceParts(door=segment)
            return segment, None, False, _place_parts_from_text(segment)
        # A brand is not an address at any length ("14 Rhum St. James"), so these judge the whole segment.
        if _reads_as_a_zip_directory(segment) or _reads_as_a_saint(segment):
            return None
        best = _best_address_in(segment)
        # The tagger is American: given "12 Rue de Rivoli, 75004 Paris, France" it
        # reads the door and stops, and "75002 Paris" it reads as a street. A run
        # the words grade as a door with its postcode and city, or as a postcode
        # and a city alone, stands on that grade.
        tagger_read_only_a_door = best is not None and not (best[1].addressLocality or "").strip()
        # A run that carries a label ("… Bank account: 2360000 VAT: 82831811090")
        # has left the address; the tagger's own reading is the safer one there.
        parts = None
        if (
            (best is None or tagger_read_only_a_door)
            and len(segment.split()) <= 9
            and not _reads_as_junk(segment)
            and not _NOT_IN_A_PLACE_NAME.search(segment)
        ):
            parts = _place_parts_from_text(segment)
            if parts.locality and _POSTCODE.fullmatch(parts.postcode) and (parts.door or len(segment.split()) <= 3):
                return _through_the_place(segment, parts).rstrip(" ,;:!?'\""), None, False, parts
        if best is None:
            # usaddress files "Isle of Palms", "Land O Lakes", "La Cañada Flintridge"
            # as a landmark and a one-word city. A short line that is a place name,
            # a comma, and a region or postcode is graded from its words instead.
            head, comma, tail = segment.partition(",")
            if (
                comma
                and "," not in tail
                and len(segment.split()) <= 5
                and _reads_as_a_place_name(head)
                and _closes_a_place(tail)
            ):
                parts = parts if parts is not None else _place_parts_from_text(segment)
                if parts.locality and not parts.door and parts.resolvable():
                    return _through_the_place(segment, parts).rstrip(" ,;:!?'\""), None, False, parts
            return None
        reading = best[0].rstrip(" ,;:!?'\"")  # trailing punctuation is not address...
        if _ENDS_WITH_POSTCODE.search(reading):
            reading = reading.rstrip(".")  # ...and neither is the sentence's period after a postcode
        # A run with no street is a city and its region, led at most by a
        # neighbourhood the page set off with a comma ("West Loop, Chicago IL").
        # With anything else in front ("logo Red Derby Washington, DC", "Live
        # From New York, NY") the tagger's box is not trusted: the words grade
        # it, and they grade a guess.
        locality = (best[1].addressLocality or "").strip()
        if not (best[1].streetAddress or "").strip() and locality:
            head, _, tail = reading.partition(",")
            led_by_a_place = "," in reading and _reads_as_a_place_name(head) and nkey(tail).startswith(nkey(locality))
            if not (nkey(reading).startswith(nkey(locality)) or led_by_a_place):
                return reading, None, False, _place_parts_from_text(reading)
        return reading, best[1], False, _place_parts(reading, best[1])

    found: list[Reading] = []
    seen: set[str] = set()
    for segment in _segments_from_cleaned(cleaned) + sorted(untagged):
        result = read(segment)
        if result is None or (key := nkey(result[0])) in seen:
            continue
        seen.add(key)
        found.append(result)
    return found


def get_address_from_text(text: str) -> list[str]:
    """Addresses found in the text as written, including guesses."""
    return [segment for segment, _, _, _ in _find_addresses(text)]


def get_address_from_text_as_schemaorg(text: str) -> list[PostalAddress]:
    """The addresses of `get_address_from_text` a tagger could structure; the rest
    are omitted rather than reported as a `PostalAddress` with an empty street."""
    return [address for _, address, _, _ in _find_addresses(text) if address is not None]


# usaddress labels folded to the fields a `PostalAddress` carries.
_USADDRESS_TAG_MAPPING = {
    # A recipient ("Attn: John Smith") is not the address. Its own bucket, never
    # read: folded into `address2` it collides with a unit after the street and
    # `usaddress.tag` raises RepeatedLabelError on the whole string.
    "Recipient": "recipient",
    "AddressNumber": "address1",
    "AddressNumberPrefix": "address1",
    "AddressNumberSuffix": "address1",
    "StreetName": "address1",
    "StreetNamePreDirectional": "address1",
    "StreetNamePreModifier": "address1",
    "StreetNamePreType": "address1",
    "StreetNamePostDirectional": "address1",
    "StreetNamePostModifier": "address1",
    "StreetNamePostType": "address1",
    "CornerOf": "address1",
    "IntersectionSeparator": "address1",
    # after an "&" usaddress relabels the street `Second*`: "5th & Main"
    "SecondStreetName": "address1",
    "SecondStreetNamePreDirectional": "address1",
    "SecondStreetNamePreModifier": "address1",
    "SecondStreetNamePreType": "address1",
    "SecondStreetNamePostDirectional": "address1",
    "SecondStreetNamePostModifier": "address1",
    "SecondStreetNamePostType": "address1",
    "LandmarkName": "address1",
    "USPSBoxGroupID": "address1",
    "USPSBoxGroupType": "address1",
    "USPSBoxID": "address1",
    "USPSBoxType": "address1",
    "BuildingName": "address2",
    "OccupancyType": "address2",
    "OccupancyIdentifier": "address2",
    "SubaddressIdentifier": "address2",
    "SubaddressType": "address2",
    "PlaceName": "city",
    "StateName": "state",
    "ZipCode": "zip_code",
}


def get_address_from_text_usaddress(address: str) -> PostalAddress | None:
    """Structure one isolated address string (also used by the SerpAPI events
    schema); None when usaddress cannot tag it, as on most non-US input."""
    try:
        mapped_address, _ = usaddress.tag(address, tag_mapping=_USADDRESS_TAG_MAPPING)
    except Exception:  # usaddress raises RepeatedLabelError
        return None
    name = mapped_address.get("address2", "")
    postalCode = mapped_address.get("zip_code", "")
    addressLocality = mapped_address.get("city", "")
    addressRegion = mapped_address.get("state", "")
    streetAddress = mapped_address.get("address1", "")
    addressRegion, addressCountry = _split_region_and_country(addressRegion)

    if not any([name, postalCode, addressLocality, addressRegion, streetAddress]):
        return None
    return PostalAddress(
        name=name,
        postalCode=postalCode,
        addressLocality=addressLocality,
        addressRegion=addressRegion,
        streetAddress=streetAddress,
        addressCountry=addressCountry,
    )
