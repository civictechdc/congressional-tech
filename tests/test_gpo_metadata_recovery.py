"""Actual MODS layouts must preserve committee ownership and constituent files."""
from dataclasses import asdict
from pathlib import Path
import json

from committee_meeting.common import Ref
from congress_api.adapters import gpo
from congress_api.adapters.committees import hierarchy_from_code, source_committee_keys
from congress_api.gpo.fetch import parse_mods, clean_rows
from test_explorer_material_adapters import context, gpo_row

FIXTURES = Path(__file__).parent / 'fixtures' / 'gpo_metadata'


def load(package):
    return asdict(parse_mods(package, (FIXTURES / f'{package}.xml').read_bytes(), '2026-09-28T00:00:00Z'))


def test_y2k_joint_hearing_keeps_both_source_committees_and_alphanumeric_identity():
    row = load('CHRG-106shrg63941')
    assert row['committee_codes_gpo'] == 'sp2k00;ssap00'
    clean_rows({row['package_id']: row})
    assert row['committee_code'] == 'sp2k00'
    assert source_committee_keys(row) == ((106, 'sp2k00'), (106, 'ssap00'))
    assert hierarchy_from_code('sp2k00') == ('full', None)
    refs = {(106, c): Ref(kind='committee_term', id=c) for c in ('sp2k00','ssap00')}
    records = list(gpo.records([row], context(), committees=refs))
    assert {r.subject.id for r in records if r.kind == 'material_link'} == {'sp2k00','ssap00'}
    assert not any(r.kind == 'meeting' for r in records)
    assert next(r for r in records if r.kind == 'source_record').payload['committee_codes_gpo'] == 'sp2k00;ssap00'


def test_constituent_only_metadata_preserves_markup_and_errata_files():
    row = load('CHRG-110shrg41912')
    assert row['committee_code_gpo'] == 'ssva00'
    urls = set(row['html_urls'].split(';')) | set(row['pdf_urls'].split(';'))
    records = list(gpo.records([row], context()))
    assert {loc.url for r in records if r.kind == 'representation' for loc in r.locations} == urls
    assert len(urls) == 4
    labels = [r.format_label.lower() for r in records if r.kind == 'representation']
    assert any('markup' in label for label in labels)
    assert any('errata' in label for label in labels)
    assert sum(r.kind == 'material' for r in records) == 1


def test_multipart_package_uses_provided_urls_and_excludes_cited_related_items():
    row = load('CHRG-115hhrg24725')
    assert row['html_url'].endswith('-pt1.htm')
    assert row['pdf_url'].endswith('-pt1.pdf')
    assert len(row['html_urls'].split(';')) == 2
    data = b'''<mods xmlns="http://www.loc.gov/mods/v3"><titleInfo><title>Actual</title></titleInfo>
      <extension><congCommittee authorityId="ssap00"/></extension>
      <relatedItem type="constituent"><extension><congCommittee authorityId="sp2k00"/></extension></relatedItem>
      <relatedItem type="references"><extension><congCommittee authorityId="hsju00"/></extension></relatedItem>
    </mods>'''
    parsed = parse_mods('CHRG-106shrg12345', data, '')
    assert parsed.committee_codes_gpo == 'ssap00;sp2k00'
    assert parsed.html_url == parsed.pdf_url == ''  # never fabricate a download URL


def test_curated_assignments_keep_native_blank_and_have_separate_cited_source():
    row = gpo_row(package_id='CHRG-113hhrg85023', congress='113', committee_code='',
                  committee_code_gpo='', committee_name='', event_id='')
    clean_rows({row['package_id']: row})
    assert row['committee_code_gpo'] == ''
    assert row['committee_codes'] == 'hsap00;hsap18'
    refs = {(113, c): Ref(kind='committee_term', id=c) for c in ('hsap00','hsap18')}
    records = list(gpo.records([row], context(), committees=refs, review_context=context('gpo.committee-review')))
    review = next(r for r in records if r.kind == 'source_record' and r.provider == 'gpo.committee-review')
    assert any('EventID=100414' in u for u in review.payload['source_urls'])
    assert all(r.provenance.citations[0].source.id == review.id for r in records if r.kind == 'material_link')
    wrong_congress = dict(row, congress='114', committee_code='', committee_codes='')
    clean_rows({'different': wrong_congress})
    assert wrong_congress['committee_code'] == ''


def test_budget_justification_is_supporting_and_original_classification_remains():
    row = gpo_row(package_id='CHRG-109shrg25756', congress='109', chamber='senate',
                  committee_code='ssap00', committee_code_gpo='', event_id='')
    records = list(gpo.records([row], context(), review_context=context('gpo.committee-review'),
                              committees={(109,'ssap00'): Ref(kind='committee_term', id='appropriations')}))
    material = next(r for r in records if r.kind == 'material')
    assert material.details.category == 'supporting'
    assert 'Budget Justification' in material.provenance.explanation
    assert next(r for r in records if r.kind == 'material_link').role == 'supporting'
    native = next(r for r in records if r.kind == 'source_record' and r.provider == 'govinfo')
    assert native.payload['record_type'] == 'hearing'
    assert material.field_evidence[0].path == '/details/category'


def test_explicit_committee_print_keeps_its_source_label_and_is_not_a_transcript():
    row = gpo_row(package_id='CHRG-118hhrg55711', committee_code='hsgo00', event_id='')
    records = list(gpo.records([row], context(), review_context=context('gpo.committee-review'),
                              committees={(118,'hsgo00'): Ref(kind='committee_term', id='oversight')}))
    material = next(r for r in records if r.kind == 'material')
    assert material.details.category == 'committee_print'
    assert next(r for r in records if r.kind == 'material_link').role == 'supporting'
    review = next(r for r in records if r.kind == 'source_record' and r.provider == 'gpo.committee-review')
    assert review.payload['source_document_type'] == 'COMMITTEE PRINT'


def test_legacy_row_keeps_single_url_identity_and_code_cleaning_is_idempotent():
    row = gpo_row(committee_code='sp2k00', committee_code_gpo='sp2k00', committee_name='')
    clean_rows({row['package_id']: row})
    before = dict(row)
    clean_rows({row['package_id']: row})
    assert row == before and row['committee_code_gpo'] == row['committee_code'] == 'sp2k00'
    records = list(gpo.records([row], context()))
    files = [r for r in records if r.kind == 'representation']
    assert len(files) == 2
    assert files[0].id == context().ids('representation', f"govinfo:{row['package_id']}:html_url")


def test_printed_congress_error_keeps_cited_explanation_without_changing_identity():
    row = gpo_row(package_id='CHRG-111shrg86304', congress='111')
    records = list(gpo.records([row], context(), review_context=context('gpo.committee-review')))
    material = next(r for r in records if r.kind == 'material')
    assert material.congress == 111
    assert '113th Congress' in material.provenance.explanation
    assert len(material.provenance.citations) == 2
