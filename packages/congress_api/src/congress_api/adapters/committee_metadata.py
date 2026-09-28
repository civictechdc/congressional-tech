"""Enrich Congress-scoped committees with their official classification."""
from committee_meeting.committees import Committee, CommitteeTerm
from committee_meeting.common import Identifier, Ref
from committee_meeting.provenance import AlternativeValue, FieldEvidence
from .meetings import chamber

TYPES = {'Standing': 'standing', 'Select': 'select', 'Special': 'special', 'Joint': 'joint',
         'Subcommittee': 'subcommittee', 'Commission or Caucus': 'commission_or_caucus',
         'Task Force': 'task_force', 'Other': 'other'}


def records(rows, context, existing):
    for row in rows:
        congress, native = int(row['congress']), row['committee']
        code = native['systemCode']
        key = f'congress.gov|{congress}|{code}'
        source = context.source(key, row, row.get('_url'))
        if row.get('retrieved_at'):
            source = source.model_copy(update={'retrieved_at': row['retrieved_at']})
        yield source
        evidence = context.evidence(source, selector='/committee')
        committee_id, term_id = context.ids('committee', key), context.ids('committee_term', key)
        old_committee = existing.get(('committee', committee_id))
        old = existing.get(('committee_term', term_id))
        name = native.get('name') or code
        yield old_committee if old_committee and old_committee.label != code else Committee(id=committee_id, label=name, provenance=evidence)
        selected = context.evidence(source, selector='/committee/committeeTypeCode') if native.get('committeeTypeCode') else evidence
        kind = TYPES.get(native.get('committeeTypeCode'), 'unknown')
        parent_code = (native.get('parent') or {}).get('systemCode')
        parent = Ref(kind='committee_term', id=context.ids('committee_term', f'congress.gov|{congress}|{parent_code}')) if parent_code else None
        values = dict(committee_type=kind, source_committee_type=native.get('committeeTypeCode'), parent=parent)
        if old:
            citations = {c.model_dump_json(): c for c in (*old.provenance.citations, *evidence.citations)}
            provenance = evidence.model_copy(update={'citations': tuple(citations.values())})
            fields = [f for f in old.field_evidence if f.path != '/committee_type']
            alternatives = (AlternativeValue(value=old.committee_type, provenance=old.provenance),) if old.committee_type not in ('unknown', kind) else ()
            fields.append(FieldEvidence(path='/committee_type', selected=selected, alternatives=alternatives,
                                        selection_reason='Official Congress-scoped committee metadata.'))
            yield old.model_copy(update={**values, 'name': old.name or native.get('name'),
                                         'provenance': provenance, 'field_evidence': tuple(fields)})
        else:
            committee = Ref(kind='committee', id=committee_id)
            yield CommitteeTerm(id=term_id, committee=committee, congress=congress, name=native.get('name'),
                                chamber=chamber(native.get('chamber')), provenance=evidence, **values,
                                identifiers=(Identifier(scheme='congress.gov:committee', value=code, scope=str(congress)),))
