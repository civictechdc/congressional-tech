"""House naming conventions, backed directly by the supplied JSON package.

The package supplies naming conventions; historical identity lookup is unused.
Use HOUSE_NAMING.extract for literal filenames, including source errors and
partial names. filenames.py supplies a typed adapter over that same reader.
Use validate/render/parse for convention-valid naming records and lookup for
source definitions. There is one extraction rule catalog in house-naming.
"""
from __future__ import annotations

import functools
from functools import lru_cache
from typing import Any

from house_naming import Engine
from .catalog import strip_appropriation_prefix
from .extraction import HOUSE_NAMING_URL


@functools.cache
def get_engine() -> Engine:
    """Return a cached Engine instance, instantiated lazily on first access."""
    return Engine()


@lru_cache(maxsize=None)
def code_label(context: str, token: str) -> tuple[str, str] | None:
    """Cache only immutable display values; full definitions stay in the catalog."""
    entry = get_engine().lookup(context, token)
    if entry is None:
        return None
    page = entry['sources'][0]['page']
    return entry['label'], f'{HOUSE_NAMING_URL}#page={page}'


def __getattr__(name: str) -> Any:
    if name == 'HOUSE_NAMING':
        return get_engine()
    if name == 'COLLECTION_CODES':
        return tuple(get_engine().guide['codes']['collection'])
    if name == 'APPROPRIATION_SUBJECTS':
        return tuple(strip_appropriation_prefix(token)
                     for token in get_engine().guide['codes']['appropriation-subject'])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ['HOUSE_NAMING', 'COLLECTION_CODES', 'APPROPRIATION_SUBJECTS', 'code_label', 'get_engine', 'HOUSE_NAMING_URL']
