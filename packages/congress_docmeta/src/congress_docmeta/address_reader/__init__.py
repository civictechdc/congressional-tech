"""Postal addresses stated in prose: a straight copy of Keeplist's address reader.

Copied 2026-11-17 from keeplist-backend fb1245c2ca3e838d6ce896c9df76464a57b75714 (`keeplist_io/scrape/utils/address_*.py`) on the owner's decision
that the two projects stay unrelated: no shared package, no import from the Keeplist checkout. The four
`address_*.py` modules are verbatim apart from their import lines and the removal of `address_search` (a Google
Places query builder); `_support.py` holds the few Keeplist helpers they call. Their docstrings still speak of
Keeplist pages and its corpus diff. What congressional documents need differently (period-punctuated Washington
addresses, PO boxes, House and Senate office buildings) lives in `congressional.py`, outside the copied modules, so
a later re-copy overwrites nothing.

Needs `usaddress`, `pycountry` and `msgspec-schemaorg`, required dependencies of this package pinned to the
versions the copy was measured on. Nothing in `congress_docmeta` imports this at module load; rule R8 imports it
on first use.
"""

from __future__ import annotations

from .address_extraction import AddressClaim, get_address_claims, get_addresses

KEEPLIST_SOURCE_COMMIT = "fb1245c2ca3e838d6ce896c9df76464a57b75714"

__all__ = ["AddressClaim", "KEEPLIST_SOURCE_COMMIT", "get_address_claims", "get_addresses"]
