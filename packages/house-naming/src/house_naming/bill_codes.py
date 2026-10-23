"""Published bill type/version vocabularies; retain unlisted source tokens.

Source: https://www.govinfo.gov/help/bills (checked 2026-09-29).
The page calls its version table common versions, not an exhaustive validity list.
A version describes a text edition; its chamber need not be the bill origin.
"""

from __future__ import annotations

import functools
from typing import Any
from .catalog import load_guide

BILLS_HELP_URL = "https://www.govinfo.gov/help/bills"
BILLS_HELP_CHECKED_ON = "2026-09-29"


@functools.cache
def _get_vocabularies() -> dict[str, Any]:
    return load_guide()['extraction_vocabularies']


@functools.cache
def get_bill_types() -> dict[str, str]:
    return {key: value['label'] for key, value in _get_vocabularies()['govinfo-bill-types'].items()}


@functools.cache
def get_bill_versions() -> dict[str, str]:
    return {key: value['label'] for key, value in _get_vocabularies()['govinfo-bill-versions'].items()}


def __getattr__(name: str) -> Any:
    if name == 'BILL_TYPES':
        val = get_bill_types()
        globals()['BILL_TYPES'] = val
        return val
    if name == 'BILL_VERSIONS':
        val = get_bill_versions()
        globals()['BILL_VERSIONS'] = val
        return val
    if name == 'BILL_CODES':
        val = {'types': get_bill_types(), 'versions': get_bill_versions()}
        globals()['BILL_CODES'] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ['BILLS_HELP_URL', 'BILLS_HELP_CHECKED_ON', 'BILL_TYPES', 'BILL_VERSIONS', 'BILL_CODES', 'get_bill_types', 'get_bill_versions']
