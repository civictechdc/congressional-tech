"""Published bill type/version vocabularies; retain unlisted source tokens.

Source: https://www.govinfo.gov/help/bills (checked 2026-09-29).
The page calls its version table common versions, not an exhaustive validity list.
A version describes a text edition; its chamber need not be the bill origin.
"""

from importlib.resources import files
from .io import loads

BILLS_HELP_URL = "https://www.govinfo.gov/help/bills"
BILLS_HELP_CHECKED_ON = "2026-09-29"

_vocabularies = loads(files('house_naming').joinpath('data/guide.json').read_bytes())['extraction_vocabularies']
BILL_TYPES = {key: value['label'] for key, value in _vocabularies['govinfo-bill-types'].items()}
BILL_VERSIONS = {key: value['label'] for key, value in _vocabularies['govinfo-bill-versions'].items()}
del _vocabularies
