"""Enrich Congress-scoped committees with their official classification."""
from committee_meeting.committees import Committee, CommitteeTerm
from committee_meeting.common import DateRange, Identifier, Ref
from committee_meeting.provenance import AlternativeValue, FieldEvidence
from .meetings import chamber
from .committee_adjustments import ADJUSTMENTS
from .committees import committee_lookup

TYPES = {'Standing': 'standing', 'Select': 'select', 'Special': 'special', 'Joint': 'joint',
         'Subcommittee': 'subcommittee', 'Commission or Caucus': 'commission_or_caucus',
         'Task Force': 'task_force', 'Other': 'other'}


def adjustment_records(context, existing, *, congresses=None):
    """Apply the small reviewed corrections while retaining all source values.

    The caller supplies an input snapshot for committee_adjustments.py and merges
    these final values after native, official-list and GPO committee records.
    """
    from datetime import date

    lookup = committee_lookup(existing.values())
    scope = set(congresses) if congresses is not None else {congress for congress, _ in lookup}
    for decision in ADJUSTMENTS:
        code = decision['code']
        terms = {congress for congress, candidate in lookup if candidate == code}
        terms.update(decision.get('add_congresses', ()))
        for congress in sorted(terms):
            if congress < decision.get('first_congress', 1) or congress > decision.get('last_congress', congress):
                continue
            if congress not in scope:
                continue
            key = f'congress.gov|{congress}|{code}'
            committee_id = context.ids('committee', key)
            term_id = context.ids('committee_term', key)
            old = existing.get(('committee_term', term_id))
            old_committee = existing.get(('committee', committee_id))
            evidence_records = []
            for index, evidence in enumerate(decision['evidence']):
                source = context.source(f'{key}|review|{index}', {'congress': congress, **decision, 'cited_evidence': evidence}, evidence['url'])
                evidence_records.append(context.evidence(source, basis='curated', selector='/cited_evidence'))
                yield source
            provenance = evidence_records[0].model_copy(update={
                'citations': tuple(c for p in evidence_records for c in p.citations),
                'explanation': decision['explanation'],
            })
            values = dict(decision['values'])
            if decision.get('terminated'):
                end = date.fromisoformat(decision['terminated'])
                if congress == (end.year - 1789) // 2 + 1:
                    values['active'] = DateRange(start=old.active.start if old and old.active else None, end=end)
            fields = list(old.field_evidence) if old else []
            for field, value in values.items():
                path = f'/{field}'
                prior = next((item for item in fields if item.path == path), None)
                alternatives = list(prior.alternatives) if prior else []
                # A reviewed display/category transformation is not a source
                # disagreement. Exact source values remain in the original
                # payload and source_committee_type, with both sources cited.
                fields = [item for item in fields if item.path != path]
                fields.append(FieldEvidence(path=path, selected=provenance, alternatives=tuple(alternatives),
                                            selection_reason=decision['explanation']))
            if old:
                citations = {c.model_dump_json(): c for c in (*old.provenance.citations, *provenance.citations)}
                provenance = provenance.model_copy(update={'citations': tuple(citations.values())})
                term = old.model_copy(update={**values, 'provenance': provenance, 'field_evidence': tuple(fields)})
            else:
                term = CommitteeTerm(id=term_id, committee=Ref(kind='committee', id=committee_id), congress=congress,
                                     chamber={'h': 'house', 's': 'senate', 'j': 'joint'}[code[0]],
                                     identifiers=(Identifier(scheme='congress.gov:committee', value=code, scope=str(congress)),),
                                     provenance=provenance, field_evidence=tuple(fields), **values)
            yield old_committee or Committee(id=committee_id, label=term.name or code, provenance=provenance)
            yield term


def records(rows, context, existing):
    from congress_api.models.congress import CommitteeSnapshot
    for raw in rows:
        row = CommitteeSnapshot.model_validate(raw).source_dict()
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
