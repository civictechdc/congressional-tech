"""Congress.gov's documented committee-code hierarchy; no name matching."""
import re

from committee_meeting.common import Identifier, Ref
from committee_meeting.committees import Committee, CommitteeTerm

HIERARCHY_SOURCE = 'https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/CommitteeEndpoint.md'


def committee_lookup(records):
    """Resolve explicit source identifiers in their Congress, never by a name."""
    lookup = {}
    for record in records:
        if record.kind != 'committee_term':
            continue
        for identifier in record.identifiers:
            if identifier.scheme == 'congress.gov:committee':
                key = (record.congress, identifier.value.lower())
                value = Ref(kind='committee_term', id=record.id)
                if key in lookup and lookup[key] != value:
                    raise ValueError(f'Ambiguous committee identifier: {key}')
                lookup[key] = value
    return lookup


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


def ensure_committee_term(congress, code, name, context, provenance, existing):
    """Fill an explicitly identified term absent from the official list.

    The caller retains the source used by provenance. Unknown classifications
    stay unknown; neither meeting dates nor similarly named committees merge.
    """
    identity = source_committee_key({'congress': congress, 'committee_code': code})
    if identity is None:
        return
    congress, code = identity
    key = f'congress.gov|{congress}|{code}'
    term_id = context.ids('committee_term', key)
    if ('committee_term', term_id) in existing:
        return
    committee_id = context.ids('committee', key)
    if ('committee', committee_id) not in existing:
        yield Committee(id=committee_id, label=name or code, provenance=provenance)
    yield CommitteeTerm(
        id=term_id, committee=Ref(kind='committee', id=committee_id), congress=congress,
        name=name or code, chamber={'h': 'house', 's': 'senate', 'j': 'joint'}[code[0]],
        identifiers=(Identifier(scheme='congress.gov:committee', value=code, scope=str(congress)),),
        provenance=provenance,
    )


def hierarchy_from_code(code):
    """The last two digits are 00 for a full committee, otherwise a child."""
    if not isinstance(code, str) or not re.fullmatch(r'[hsj][a-z0-9]{3}\d{2}', code, re.I):
        return 'unknown', None
    return ('full', None) if code.endswith('00') else ('subcommittee', code[:4] + '00')
