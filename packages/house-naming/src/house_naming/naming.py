"""House naming conventions, backed directly by the supplied JSON package.

The package supplies naming conventions; historical identity lookup is unused.
Use HOUSE_NAMING.extract for literal filenames, including source errors and
partial names. filenames.py supplies a typed adapter over that same reader.
Use validate/render/parse for convention-valid naming records and lookup for
source definitions. There is one extraction rule catalog in house-naming.
"""
from functools import lru_cache
import re

from house_naming import Engine
from .extraction import HOUSE_NAMING_URL

HOUSE_NAMING = Engine()
_codes = HOUSE_NAMING.guide['codes']
COLLECTION_CODES = tuple(_codes['collection'])
# Some subject entries include the example's fiscal year in their printed code.
APPROPRIATION_SUBJECTS = tuple(re.sub(r'^fy[0-9]{2,4}-', '', token)
                              for token in _codes['appropriation-subject'])
del _codes


@lru_cache(maxsize=None)
def code_label(context: str, token: str) -> tuple[str, str] | None:
    """Cache only immutable display values; full definitions stay in the catalog."""
    entry = HOUSE_NAMING.lookup(context, token)
    if entry is None:
        return None
    page = entry['sources'][0]['page']
    return entry['label'], f'{HOUSE_NAMING_URL}#page={page}'
