"""Document ownership does not require or manufacture a meeting match."""
import csv

import pytest

from committee_meeting import Catalog
from committee_meeting.common import Ref
from congress_api import committee_metadata as collector
from congress_api.adapters import committee_metadata, gpo
from congress_api.adapters.committees import committee_lookup, ensure_committee_term
from test_committee_metadata import metadata, save
from test_explorer_export import native, write_meetings
from test_explorer_material_adapters import context, gpo_row


def indexed(records):
    return {(item.kind, item.id): item for item in records}


def validate(records):
    values = list(records.values())
    return Catalog(sources=tuple(r for r in values if r.kind == 'source_record'),
                   records=tuple(r for r in values if r.kind != 'source_record'))


def test_direct_committee_link_preserves_document_identity_and_joint_body():
    row = gpo_row(package_id='CHRG-112shrg65276', congress='112', chamber='senate', event_id='',
                  committee_code='jocp00', committee_code_gpo='JOCP00', committee_name='Congressional Oversight Panel')
    ctx = context()
    old_material = next(r for r in gpo.records([row], ctx) if r.kind == 'material')
    base = indexed(gpo.committee_records([row], ctx, existing={}))
    lookup = committee_lookup(base.values())
    base.update(indexed(gpo.records([row], ctx, committees=lookup)))
    catalog = validate(base)
    term = next(r for r in catalog.records if r.kind == 'committee_term')
    material = next(r for r in catalog.records if r.kind == 'material')
    assert term.chamber == 'joint'
    assert material.chamber == 'senate' and material.id == old_material.id
    assert term.committee_type == 'unknown'
    link = next(r for r in catalog.records if r.kind == 'material_link')
    assert link.subject == Ref(kind='committee_term', id=term.id)
    assert link.provenance.citations[0].selector == '/committee_code'
    assert link.provenance.basis == 'derived'
    assert not any(r.kind == 'meeting' for r in catalog.records)
    assert any(r.kind == 'data_issue' and r.category == 'unlinked' for r in catalog.records)
    assert catalog.sources[0].payload == row


def test_existing_terms_are_reused_and_congresses_remain_distinct():
    ctx = context()
    official = indexed(committee_metadata.records([metadata(112, 'slia00', 'Other')], ctx, {}))
    rows = [gpo_row(congress=str(c), committee_code='slia00', committee_name='Indian Affairs', event_id='') for c in (111, 112)]
    missing = list(gpo.committee_records(rows * 2, ctx, existing=official))
    assert [r.congress for r in missing if r.kind == 'committee_term'] == [111]
    official.update(indexed(missing))
    terms = committee_lookup(official.values())
    assert terms[111, 'slia00'] != terms[112, 'slia00']
    linked = list(gpo.records([rows[1]], ctx, committees=terms))
    assert next(r for r in linked if r.kind == 'material_link').subject == terms[112, 'slia00']


@pytest.mark.parametrize('changes', [{'committee_code': ''}, {'committee_code': 'unknown'}, {'congress': 'bad'}, {'congress': 0}])
def test_missing_or_invalid_identifier_does_not_fabricate_a_term(changes):
    assert not list(gpo.committee_records([gpo_row(**changes)], context(), existing={}))


def test_unrelated_lookup_and_invalid_reference_are_not_silent_matches():
    row = gpo_row(committee_code='hsvr00', event_id='')
    other = {(117, 'hsvr00'): Ref(kind='committee_term', id='another-congress')}
    assert not any(r.kind == 'material_link' for r in gpo.records([row], context(), committees=other))
    with pytest.raises(ValueError, match='committee_term'):
        list(gpo.records([row], context(), committees={(118, 'hsvr00'): Ref(kind='meeting', id='wrong-kind')}))


def test_official_event_fallback_uses_the_same_committee_identity():
    ctx = context('senate.committees')
    source = ctx.source('senate-page|drugcaucus.senate.gov|https://example.gov/hearing', {'event': {'title': 'Hearing'}})
    evidence = ctx.evidence(source, selector='/event')
    fallback = list(ensure_committee_term(117, 'scnc00', 'Drug Caucus', ctx, evidence, {}))
    assert next(r.id for r in fallback if r.kind == 'committee_term') == ctx.ids('committee_term', 'congress.gov|117|scnc00')
    assert not list(ensure_committee_term(117, 'scnc00', 'Drug Caucus', ctx, evidence, indexed(fallback)))


def test_curated_changes_preserve_source_type_name_ids_and_lifecycle():
    ctx = context('congress.gov:committees')
    rows = [metadata(112, 'scnc00', 'Other'), metadata(112, 'jocp00', 'Other'),
            metadata(118, 'hshf00', 'Other'), metadata(118, 'sowg00', 'Other'), metadata(112, 'slia00', 'Other')]
    records = indexed(committee_metadata.records(rows, ctx, {}))
    old_ids = set(records)
    adjusted = list(committee_metadata.adjustment_records(context('committee-review'), records, congresses={112, 118, 119}))
    records.update(indexed(adjusted))
    catalog = validate(records)
    assert old_ids <= set(records)
    terms = {(r.congress, r.identifiers[0].value): r for r in catalog.records if r.kind == 'committee_term'}
    caucus = terms[112, 'scnc00']
    assert caucus.committee_type == 'commission_or_caucus'
    assert caucus.source_committee_type == 'Other'
    assert all(not f.alternatives for r in terms.values() for f in r.field_evidence)
    assert all(r.committee_type == 'other' for key, r in terms.items() if key[1] != 'scnc00')
    assert terms[112, 'jocp00'].active.end.isoformat() == '2011-04-03'
    assert terms[112, 'jocp00'].website.endswith('/COP_redirect.htm')
    assert terms[119, 'hshf00'].name == 'Committee of the Whole House on the State of the Union'
    assert terms[119, 'sowg00'].chamber == 'senate'
    assert terms[119, 'hshf00'].source_committee_type is None  # no invented Congress.gov row
    assert {(r.congress, r.identifiers[0].value) for r in terms.values()} - {(r['congress'], r['committee']['systemCode']) for r in rows} == {(119, 'hshf00'), (119, 'sowg00')}
    assert next(s for s in catalog.sources if s.provider == 'congress.gov:committees' and s.payload['committee']['systemCode'] == 'hshf00').payload == rows[2]
    assert 'outside' in terms[119, 'hshf00'].provenance.explanation
    assert any(s.url.startswith('https://home.treasury.gov/') for s in catalog.sources)


def test_curated_additions_respect_limited_congress_scope():
    values = list(committee_metadata.adjustment_records(context('committee-review'), {}, congresses={115}))
    assert values == []


def test_historical_medicare_commission_keeps_native_classification_and_term_scope():
    ctx = context('congress.gov:committees')
    rows = [metadata(c, 'jcfm00', 'Other') for c in (106, 107)]
    records = indexed(committee_metadata.records(rows, ctx, {}))
    records.update(indexed(committee_metadata.adjustment_records(context('committee-review'), records)))
    terms = {r.congress: r for r in validate(records).records if r.kind == 'committee_term'}
    assert terms[106].committee_type == 'commission_or_caucus'
    assert terms[106].source_committee_type == 'Other'
    assert terms[106].active is None or terms[106].active.end is None
    assert terms[107].committee_type == 'other'


def test_collector_includes_document_only_historical_congresses(tmp_path, monkeypatch):
    meetings = write_meetings(tmp_path, [native()])
    output = save(tmp_path / 'committees.jsonl.gz', [metadata(115)])
    gpo_path = tmp_path / 'gpo.csv'
    with gpo_path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['congress'])
        writer.writeheader()
        writer.writerows([{'congress': 106}, {'congress': 111}])
    calls = []

    def get(session, url, api_key, params):
        congress = int(url.rsplit('/', 1)[1])
        calls.append(congress)
        return {'committees': [metadata(congress)['committee']], 'pagination': {}}

    monkeypatch.setattr(collector, 'get', get)
    rows = collector.collect(meetings, output, api_key='test', gpo_path=gpo_path)
    assert calls == [106, 111, 115]
    assert {row['congress'] for row in rows.values()} == {106, 111, 115}
