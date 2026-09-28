"""Repeated publisher links reuse known records without merging distinct files."""
from dataclasses import asdict
from pathlib import Path

from committee_meeting.common import Ref
from committee_meeting.materials import DocumentDetails, RecordingDetails
from congress_api.adapters import gpo
from congress_api.adapters.common import material_records
from congress_api.gpo.fetch import parse_mods
from test_explorer_material_adapters import context

FIXTURES = Path(__file__).parent / 'fixtures' / 'gpo_metadata'


def known_records():
    package = 'CHRG-116shrg63315'
    row = asdict(parse_mods(package, (FIXTURES / f'{package}.xml').read_bytes(), '2026-09-28T00:00:00Z'))
    return list(gpo.records([row], context())), row


def test_known_primary_file_reuses_gpo_ids_fields_and_both_citations():
    records, row = known_records()
    ctx = context('senate.committees')
    ctx.known_materials = gpo.primary_rendition_index(records)
    source = ctx.source('page', {'label': 'Click here for printed transcript'})
    evidence = ctx.evidence(source, selector='/label')
    built = material_records(ctx, evidence, 'senate-page|document', title='Click here for printed transcript',
        urls=[row['pdf_url']], details=DocumentDetails(category='transcript'), subject=Ref(kind='meeting', id='one'), role='transcript')
    original = next(r for r in records if r.kind == 'material')
    edition = next(r for r in records if r.kind == 'material_version')
    assert built[0].id == original.id and built[0].title == original.title
    assert built[0].details == original.details
    assert built[1].id == edition.id and built[1].source_modified_at == edition.source_modified_at
    assert {c.source.id for c in built[0].provenance.citations} == {source.id, original.provenance.citations[0].source.id}
    assert [r.kind for r in built] == ['material', 'material_version', 'material_link']
    assert built[-1].material.id == original.id and built[-1].version.id == edition.id


def test_supplement_mixed_and_multiple_file_listings_do_not_become_whole_package():
    records, row = known_records()
    ctx = context('docs.house.gov')
    ctx.known_materials = gpo.primary_rendition_index(records)
    evidence = ctx.evidence(ctx.source('page', {}))
    original = next(r for r in records if r.kind == 'material')
    supplement = next(url for url in row['pdf_urls'].split(';') if '-add1' in url)
    assert supplement not in ctx.known_materials
    for urls in ([supplement], [row['pdf_url'], supplement], [row['pdf_url'], row['html_url']],
                 [row['pdf_url'], 'https://example.gov/other.pdf']):
        built = material_records(ctx, evidence, 'a-source-listing', urls=urls)
        assert built[0].id != original.id
        assert {loc.url for r in built if r.kind == 'representation' for loc in r.locations} == set(urls)
    recording = material_records(ctx, evidence, 'a-recording', urls=[row['pdf_url']], details=RecordingDetails())
    assert recording[0].id != original.id


def test_ambiguous_versions_are_not_admitted_to_known_file_lookup():
    records, row = known_records()
    version = next(r for r in records if r.kind == 'material_version')
    representation = next(r for r in records if r.kind == 'representation' and r.locations[0].url == row['pdf_url'])
    other_version = version.model_copy(update={'id': version.id + '-different-edition'})
    other_representation = representation.model_copy(update={'id': representation.id + '-different-edition',
        'version': Ref(kind='material_version', id=other_version.id)})
    index = gpo.primary_rendition_index([*records, other_version, other_representation])
    assert row['pdf_url'] not in index
    assert row['html_url'] in index
