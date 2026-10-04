"""Congress.gov's documented committee-code hierarchy; no name matching."""

from committee_meeting.committees import Committee, CommitteeTerm
from committee_meeting.common import Identifier, Ref

from congress_api.matching.committees import (
    HIERARCHY_SOURCE as HIERARCHY_SOURCE,
    hierarchy_from_code as hierarchy_from_code,
    source_committee_key as source_committee_key,
    source_committee_keys as source_committee_keys,
)


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
