"""Work addresses in congressional documents, read with the copied Keeplist reader.

The four `address_*.py` modules stay verbatim; what congressional text needs differently lives here:

* Washington addresses written with periods ("1615 H Street, N.W., Washington, D.C. 20062"). The tagger stops at
  "N.W.", so the reader returned the bare street. The periods are folded before reading.
* Post office boxes. Keeplist drops them on purpose (a mailbox is not a place to pin on a map); for a witness or
  a tribal office the box is the work address.
* House and Senate office buildings. A room in a named building has no street type, and the "Washington, DC 20515"
  line is often two committee lines below it, so the reader saw a bare city.

Offsets are into the folded text `read_work_addresses` returns, so a caller searches names in that same string.
"""

from __future__ import annotations

import re

import usaddress

from .address_broad import _PO_BOX
from .address_extraction import get_address_claims

__all__ = ["fold_washington_periods", "is_hill_office", "read_work_addresses"]

# "N.W." / "S. E." as a quadrant, "D.C." as the district; never the middle of an abbreviation run ("U.S.D.C.x").
_QUADRANT = re.compile(r"(?<![\w.])([NS])\.\s?([EW])\.(?!\w)")
_DISTRICT = re.compile(r"(?<![\w.])D\.\s?C\.(?!\w)")

_HOUSE_BUILDINGS = r"Rayburn|Longworth|Cannon|Ford|O['’]?Neill"
_SENATE_BUILDINGS = r"Russell|Dirksen|Hart"
# "2157 Rayburn House Office Building", "428A Russell Senate Office Bldg", "211 Russell Senate Office".
_HILL_ROOM = re.compile(
    rf"(?i)(?<![\w-])(?P<room>[A-Z]?\d{{2,4}}[A-Z]?)\s+(?P<name>{_HOUSE_BUILDINGS})\s+House\s+Office\s+B(?:uilding|ldg\.?)"
    rf"|(?<![\w-])(?P<sroom>[A-Z]?\d{{2,4}}[A-Z]?)\s+(?P<sname>{_SENATE_BUILDINGS})\s+Senate\s+Office(?:\s+B(?:uilding|ldg\.?))?"
)
_HILL_ANY = re.compile(rf"(?i)\b(?:{_HOUSE_BUILDINGS}|{_SENATE_BUILDINGS})\s+(?:House|Senate)\s+Office\b")
_HILL_ZIP = re.compile(r"(?i)\bWashington,?\s+DC\s+(205\d\d(?:-\d{4})?)")
_ZIP_END = re.compile(r"\b\d{5}(?:-\d{4})?\b")


def fold_washington_periods(text: str) -> str:
    """"N.W." -> "NW", "D.C." -> "DC"."""
    return _DISTRICT.sub("DC", _QUADRANT.sub(r"\1\2", text))


def is_hill_office(address: str) -> bool:
    """Whether the address is a room in a House or Senate office building."""
    return bool(_HILL_ANY.search(address))


def _hill_offices(text: str) -> list[tuple[int, int, str]]:
    out = []
    for m in _HILL_ROOM.finditer(text):
        house = m.group("room") is not None
        room, name = (m.group("room"), m.group("name")) if house else (m.group("sroom"), m.group("sname"))
        building = f"{room.upper()} {name.title()} {'House' if house else 'Senate'} Office Building"
        zip_code = _HILL_ZIP.search(text, m.end(), m.end() + 200)
        out.append((m.start(), m.end(), f"{building}, Washington, DC{' ' + zip_code.group(1) if zip_code else ''}"))
    return out


def _po_boxes(text: str) -> list[tuple[int, int, str]]:
    """A box line and the town line under it, kept only when the tagger reads box, town, state and ZIP."""
    out = []
    for m in _PO_BOX.finditer(text):
        zip_code = _ZIP_END.search(text, m.end(), m.end() + 70)
        if zip_code is None:
            continue
        run = " ".join(text[m.start() : zip_code.end()].split())
        try:
            tags, kind = usaddress.tag(run)
        except usaddress.RepeatedLabelError:
            continue
        if kind == "PO Box" and all(tags.get(k) for k in ("USPSBoxID", "PlaceName", "StateName", "ZipCode")):
            town = f"{tags['PlaceName'].rstrip(',')}, {tags['StateName']} {tags['ZipCode']}"
            out.append((m.start(), zip_code.end(), f"{' '.join(m.group(0).split())}, {town}"))
    return out


def _locate(text: str, address: str, taken: list[tuple[int, int]]) -> tuple[int, int] | None:
    """Where the reading starts in `text`: its first three words, however the page spaced them."""
    words = address.replace(",", " ").split()[:3]
    pattern = re.compile(r"[\s,]+".join(re.escape(w) for w in words))
    for m in pattern.finditer(text):
        if not any(start <= m.start() < end for start, end in taken):
            return m.start(), m.end()
    return None


def read_work_addresses(text: str) -> tuple[str, list[tuple[int, int, str]]]:
    """`(folded text, [(start, end, address), ...])` in page order: street doors, PO boxes and Hill office rooms.

    `end` closes the words that open the address on the page (a room and its building, a box, a door and the
    start of its street), not the whole address. City-only readings ("Washington, DC 20515") are left out: a
    city names nobody's office.
    """
    folded = fold_washington_periods(text or "")
    found = _hill_offices(folded) + _po_boxes(folded)
    taken = [(start, end) for start, end, _ in found]
    for claim in get_address_claims(folded):
        if not claim.parts.door or is_hill_office(claim.text):
            continue  # a Hill room the reader did read is already there in its canonical form
        span = _locate(folded, claim.text, taken)
        if span is not None:
            taken.append(span)
            found.append((*span, claim.text))
    return folded, sorted(found)
