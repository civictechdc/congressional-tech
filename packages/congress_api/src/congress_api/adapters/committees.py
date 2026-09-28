"""Congress.gov's documented committee-code hierarchy; no name matching."""
import re

HIERARCHY_SOURCE = 'https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/CommitteeEndpoint.md'


def hierarchy_from_code(code):
    """The last two digits are 00 for a full committee, otherwise a child."""
    if not isinstance(code, str) or not re.fullmatch(r'[a-z]{4}\d{2}', code, re.I):
        return 'unknown', None
    return ('full', None) if code.endswith('00') else ('subcommittee', code[:4] + '00')
