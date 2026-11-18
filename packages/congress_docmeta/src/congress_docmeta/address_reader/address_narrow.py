"""Narrow address path: the publisher already boxed the place.

JSON-LD `PostalAddress` nodes and fields labelled `address` / `formatted_address`.
No usaddress -- a box is provenance, not prose to tag. Both are read into the
same `PlaceParts`; what each must name to be reported differs by who wrote it.
A JSON-LD box the publisher left without a door is usually not the page's place
-- a publisher's office, a job's region, a ward -- so it needs a door. A
provider's labelled address is the place itself, so a doorless one that still
resolves ("Destin, FL 32541") is kept as a query. Shared already holds
pycountry; this file reads places, it does not look up ISO names.
"""

from __future__ import annotations

import re

from msgspec_schemaorg.models import PostalAddress

from ._support import is_placeholder, nkey
from .address_shared import (
    _ANY_DIGIT,
    _BYSTANDER_KEYS,
    _country_from_token,
    _labelled_strings,
    _place_parts_from_structured,
    _place_parts_from_text,
    _plain_text,
    _reads_as_a_placeholder,
    _us_state_name_to_code,
    _walk,
)

# In the order a person writes an address; a missing part is dropped, never filled.
_POSTAL_PARTS = ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")


def _postal_value(node: dict, key: str) -> str:
    value = node.get(key)
    if isinstance(value, dict):  # {"@type": "Country", "name": "US"}; a URL @id is not a name
        value = value.get("name") or ""
    items = value if isinstance(value, list) else [value]
    parts = []
    for item in items:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            part = str(item)
        elif isinstance(item, float):
            part = str(int(item)) if item.is_integer() else ""
        elif isinstance(item, str):
            part = item
        else:
            continue
        if part:
            parts.append(part)
    if not parts:
        return ""
    text = " ".join(_plain_text(", ".join(parts)).split()).rstrip(",")
    if not text or is_placeholder(text) or _reads_as_a_placeholder(text):  # "none", "Your Town"
        return ""
    return text


# ZIP regions whose codes begin with 0. WA is 98xxx; treating it like MA turns
# Perth's 6000 into 06000.
_ZERO_PREFIX_ZIP_STATES = frozenset({"CT", "MA", "ME", "NH", "NJ", "RI", "VT"})


def _restored_postal_code(postal_code: str, region: str, country: str = "") -> str:
    """A New England ZIP that lost its leading zero upstream ("1608" for
    Worcester's 01608). Four digits beside WA stay 6000: that is Perth, not
    a fabricated 06000. A country that is not the US is never padded."""
    code = _us_state_name_to_code().get(region.strip().upper(), "")
    if not (len(postal_code) == 4 and postal_code.isdigit() and code in _ZERO_PREFIX_ZIP_STATES):
        return postal_code
    named = country.strip()
    if named and _country_from_token(named, us_state_wins=False) != "US":
        return postal_code
    return "0" + postal_code


def _postal_values(node: dict) -> dict[str, str] | None:
    """The parts of a JSON-LD `PostalAddress`, or None when it has neither street nor code."""
    values = {key: _postal_value(node, key) for key in _POSTAL_PARTS}
    if not (values["streetAddress"] or values["postalCode"]):  # a city alone is not an address
        return None
    values["postalCode"] = _restored_postal_code(
        values["postalCode"], values["addressRegion"], values["addressCountry"]
    )
    return values


def _render_postal(values: dict[str, str]) -> str:
    return ", ".join(values[key] for key in _POSTAL_PARTS if values[key])


def format_postal_address(node: dict) -> str:
    """One JSON-LD `PostalAddress` as a person writes it; missing parts omitted, never filled.
    A box without a door (no street number) is not rendered: type coercion uses this."""
    values = _postal_values(node)
    if not values:
        return ""
    street = values["streetAddress"]
    if not street or not _ANY_DIGIT.search(street):
        return ""
    return _render_postal(values)


def is_postal_address_node(node) -> bool:
    """Whether this is a `PostalAddress`, by declared type or by shape."""
    if not isinstance(node, dict):
        return False
    types = node.get("@type") or node.get("type")
    return "PostalAddress" in (types if isinstance(types, list) else [types]) or "streetAddress" in node


def _iter_postal_addresses(data) -> list[dict]:
    """Every `PostalAddress`-shaped node in a scraped payload, except those that
    box a bystander or an organisation's seat rather than the page's place."""
    return [
        value
        for _, value in ((None, data), *_walk(data, max_depth=None, skip=_BYSTANDER_KEYS))
        if is_postal_address_node(value)
    ]


def _postcodes_claimed_for_two_cities(nodes: list[dict]) -> set[str]:
    """Postal codes a page gives to more than one city: a templated field, not two
    places (every BLT branch carried Manhattan's 10021 NY). The code and its
    region are then dropped from all of them."""
    cities: dict[str, set[str]] = {}
    for node in nodes:
        code = _postal_value(node, "postalCode")
        locality = nkey(_postal_value(node, "addressLocality").split(",")[0])  # "Washington, DC" is Washington
        if code and locality:
            cities.setdefault(code, set()).add(locality)
    return {code for code, seen in cities.items() if len(seen) > 1}


def _declared_addresses(data) -> list[tuple[str, PostalAddress]]:
    """Every address the publisher structured, as text and as parts, deduplicated."""
    seen: set[str] = set()
    out: list[tuple[str, PostalAddress]] = []
    nodes = _iter_postal_addresses(data)
    templated = _postcodes_claimed_for_two_cities(nodes)
    for node in nodes:
        if templated and _postal_value(node, "postalCode") in templated:
            node = {k: v for k, v in node.items() if k not in ("postalCode", "addressRegion")}
        values = _postal_values(node)
        if not values:
            continue
        structured = PostalAddress(**values)
        if not _place_parts_from_structured(structured).door:
            continue
        rendered = _render_postal(values)
        key = nkey(rendered)
        if key in seen:
            continue
        seen.add(key)
        out.append((rendered, structured))
    return out


def get_addresses_from_metadata(data) -> list[str]:
    """Every address the publisher structured, as text, deduplicated."""
    return [text for text, _ in _declared_addresses(data)]


# Keys under which a payload states an address as one finished string.
# `streetAddress` is absent on purpose: it is one field of a `PostalAddress`.
_LABELLED_ADDRESS_KEYS = frozenset({"address", "formatted_address", "full_address"})

_MAC_ADDRESS = re.compile(r"\b(?:[0-9a-f]{2}[:-]){4,}[0-9a-f]{2}\b")


def _reads_as_a_postal_address(text: str) -> bool:
    """Whether a string labelled `address` is postal: not an email or MAC address.
    A door, a Plus Code, or a city with a region, postcode, or country stands.
    Occupancy lines and a postcode beside a country do not."""
    if not (8 <= len(text) <= 200):
        return False
    lowered = text.lower()
    if "@" in text or "://" in text or lowered.startswith(("http", "www.", "mailto")):
        return False
    if _MAC_ADDRESS.search(lowered):
        return False
    return _place_parts_from_text(text).admits()


def _iter_labelled_addresses(data) -> list[str]:
    """Addresses a payload has already isolated and labelled, read as written."""
    out: list[str] = []
    for value in _labelled_strings(data, _LABELLED_ADDRESS_KEYS):
        text = " ".join(_plain_text(value).replace("\n", ", ").split()).strip(",")
        if _reads_as_a_postal_address(text):
            out.append(text)
    return out
