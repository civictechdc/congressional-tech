"""Congress.gov parent committee codes and the aliases used for committee recordings."""


import re

HIERARCHY_SOURCE = 'https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/CommitteeEndpoint.md'

ALIAS = {"jjec00": "jsec00", "hlvc00": "hsgo00", "hlfd00": "hsju00", "hlqj00": "hsju00"}


def native_parent(code):
    """Full-committee systemCode with no recording-channel alias applied."""
    return code[:4] + "00"


def parent_code(code):
    """Parent code for channel/catalog mapping (select committees share a tracked channel)."""
    parent = native_parent(code)
    return ALIAS.get(parent, parent)


def codes_of(meeting):
    """Aliased parent codes for YouTube/Senate channel lookup and cross-source catalog keys."""
    return list(dict.fromkeys(parent_code(c["systemCode"]) for c in meeting.get("committees", [])))


def occupancy_codes_of(meeting):
    """Native parent codes for day-occupancy and uniqueness (aliases must not collide)."""
    return list(dict.fromkeys(native_parent(c["systemCode"]) for c in meeting.get("committees", [])))


def source_committee_key(row):
    """A retained GPO committee code is independent of its print's chamber."""
    code = str(row.get('committee_code') or '').strip().lower()
    if not re.fullmatch(r'[hsj][a-z0-9]{3}\d{2}', code):
        return None
    try:
        congress = int(row.get('congress'))
    except (ValueError, TypeError):
        return None
    if isinstance(row.get('congress'), bool) or congress <= 0:
        return None
    return congress, code


def source_committee_keys(row):
    """Every explicit body, with the legacy single-code field as a fallback."""
    codes = [str(row.get('committee_code') or '')] + str(row.get('committee_codes') or '').split(';')
    return tuple(dict.fromkeys(key for code in codes
                              if (key := source_committee_key({**row, 'committee_code': code}))))


def hierarchy_from_code(code):
    """The last two digits are 00 for a full committee, otherwise a child."""
    if not isinstance(code, str) or not re.fullmatch(r'[hsj][a-z0-9]{3}\d{2}', code, re.I):
        return 'unknown', None
    return ('full', None) if code.endswith('00') else ('subcommittee', native_parent(code))
