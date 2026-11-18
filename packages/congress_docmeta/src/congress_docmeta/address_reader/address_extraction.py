"""Find the postal addresses a link states, and say each one once.

This module is the join: `get_address_claims`. Broad (page prose) and narrow
(publisher-boxed) readers live in sibling modules. Shared holds vocabulary and
identity; it does not import the readers. Extraction changes still need a
corpus diff on the restored snapshot (`CLAUDE.md`).
"""

from msgspec_schemaorg.models import PostalAddress

from .address_broad import (
    Reading,
    _find_addresses,
    get_address_from_text_usaddress,
)

# Re-exported for tests only (no production caller; see `__all__` below), so
# each is named explicitly as its own alias -- ruff's F401 otherwise reads a
# name `__all__` does not carry as unused, and these keep working as `from
# address_extraction import ...` because Python imports never depended on
# `__all__` in the first place.
from .address_broad import extract_address_segments as extract_address_segments
from .address_broad import get_address_from_text as get_address_from_text
from .address_broad import (
    get_address_from_text_as_schemaorg as get_address_from_text_as_schemaorg,
)
from .address_broad import number_last_segments as number_last_segments
from .address_narrow import (
    _declared_addresses,
    _iter_labelled_addresses,
    format_postal_address,
    is_postal_address_node,
)
from .address_narrow import get_addresses_from_metadata as get_addresses_from_metadata
from .address_shared import (
    AddressClaim,
    PlaceParts,
    Source,
    _already_said,
    _canonical,
    _city_word,
    _collapse_variants,
    _iter_metadata_text,
    _page_names,
    _place_parts,
    _reads_as_the_page_s_own_name,
    _region_key,
    _same_city,
    _same_place,
    country_code,
)


def get_address_claims(text: str | None = None, metadata=None) -> list[AddressClaim]:
    """Every address this link states -- declared, labelled, page text, metadata
    prose -- each place once, with its source, its parts, and whether it stands
    as-is. Declared addresses lead; the text passes add what only prose carries."""
    out: list[AddressClaim] = []
    canonical: list[str] = []

    def keep(
        address: str,
        source: Source,
        parts: PlaceParts,
        structured: PostalAddress | None = None,
        *,
        complete: bool = False,
    ) -> None:
        out.append(AddressClaim(address, source, complete or parts.resolvable(), structured, parts))
        canonical.append(_canonical(address))

    def already_stated(address: str, parts: PlaceParts) -> bool:
        # The same place rarely arrives identically from two sources: the
        # publisher writes "…, 91006, US" and the page shows "…, 91006". A
        # caller passes the same `parts` it is about to `keep`, so the two
        # agree on what "adds a part" means for this candidate -- except the
        # page/metadata pass below, which has its own reason to grade the two
        # differently.
        key = _canonical(address)
        return any(
            _already_said(key, other, new_parts=parts, said_parts=claim.parts)
            for claim, other in zip(out, canonical, strict=True)
        )

    for address, structured in _declared_addresses(metadata):
        keep(address, "declared", _place_parts(address, structured), structured)
    for address in _collapse_variants(_iter_labelled_addresses(metadata)):
        parts = _place_parts(address)
        if not already_stated(address, parts):
            keep(address, "labelled", parts)
    # A street a declared source already gave is not news, however the text
    # passes phrase it. Restatement alone misses this, because the text version
    # differs by having junk welded on rather than by being shorter: beside a
    # clean "816 W. Fullerton Ave, Chicago, IL, 60614" the prose pass offered
    # "816 W. Fullerton Ave Su Mo Tu We", and the restatement is always the
    # worse reading. The street alone is not enough: "100 Main St, Austin" is
    # not a restatement of Boston at the same number.
    names = _page_names(metadata)
    readings: dict[str, tuple[Source, PostalAddress | None, bool, PlaceParts]] = {}
    passes: list[tuple[Source, list[Reading]]] = [
        ("page", _find_addresses(text or "")),
        ("metadata", _find_addresses(" \n".join(_iter_metadata_text(metadata)))),
    ]
    for source, found in passes:
        for address, structured, complete, parts in found:
            readings.setdefault(address, (source, structured, complete, parts))
    for address in _collapse_variants(list(readings)):
        if any(
            _same_place(address, claim.text, b_parts=claim.parts) for claim in out
        ) or _reads_as_the_page_s_own_name(address, names):
            continue
        source, structured, complete, parts = readings[address]
        # The reader grades each reading itself -- the parts it stands behind
        # for exactly the text it returned, so a box cannot vouch for words
        # outside that text and a reading the reader demoted stays a guess.
        # `already_stated` and `keep` therefore judge the same parts, computed once.
        if not already_stated(address, parts):
            keep(address, source, parts, structured, complete=complete)
    # A city is not news beside a door in it: "Chicago, IL" next to "2207 N
    # Clybourn Ave, Chicago, IL 60614" is the same page saying less -- but only
    # the same city: "New York, NY" beside a New Haven door is a second place,
    # and a region named on both sides must agree ("Washington, DC" is dropped
    # beside a door in Washington DC, not beside one in Washington State). The
    # two sides do not always write the region the same way ("Chicago,
    # Illinois" beside a door in "Chicago, IL"), so both fold through
    # `_region_key` (a US state code regardless of notation) before comparing.
    # Only a doored claim naming a locality seeds the set, and only a doorless
    # claim naming one is ever dropped by it: a bare street with no city ("1600
    # 21st Street") neither seeds nor loses a locality-less guess.
    doored_localities = [claim.parts for claim in out if claim.parts.door and claim.parts.locality]

    def _named_by_a_door(parts: PlaceParts) -> bool:
        city = _city_word(parts)
        return any(
            _same_city(city, _city_word(door))
            and (not parts.region or not door.region or _region_key(parts.region) == _region_key(door.region))
            for door in doored_localities
        )

    return [
        claim for claim in out if claim.parts.door or not claim.parts.locality or not _named_by_a_door(claim.parts)
    ]


def get_addresses(text: str | None = None, metadata=None) -> list[str]:
    """The texts of `get_address_claims`."""
    return [claim.text for claim in get_address_claims(text, metadata)]


def stated_address_in(text: str) -> AddressClaim | None:
    """The address this text states outright: a claim with a door if one is
    stated, so a city line above a door never outranks it; else the first
    stated claim, or None."""
    stated = [claim for claim in get_address_claims(text) if claim.stated]
    with_a_door = next((claim for claim in stated if claim.parts.door), None)
    return with_a_door if with_a_door is not None else next(iter(stated), None)


# Only names with a production caller (`grep -rn --include='*.py' keeplist_io
# | grep -v tests`); a test imports whatever it needs directly, `__all__` or
# not.
__all__ = [
    "AddressClaim",
    "country_code",
    "format_postal_address",
    "get_address_claims",
    "get_address_from_text_usaddress",
    "is_postal_address_node",
    "stated_address_in",
]
