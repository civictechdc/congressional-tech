"""Remaining null-kind cases: publisher records, collector files and bill forms."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from congress_api.parsers.document_cover import document_page_fields
from congress_api.retention.document_evidence import enrich_sources
from congress_api.retention.document_index import extract, fill_document_kind


@pytest.mark.parametrize('filename,url,record_type,identifier', [
    ('2026-09-21T13:51:33Z', 'https://api.govinfo.gov/collections/CHRG/2026-09-21T13:51:33Z?offsetMark=*&pageSize=100', 'collection-listing', 'CHRG'),
    (None, 'https://api.govinfo.gov/collections/CRPT/2026-09-22T12:36:07Z', 'collection-listing', 'CRPT'),
    ('summary', 'https://api.govinfo.gov/packages/CHRG-119hhrg64533/summary', 'package-summary', 'CHRG-119hhrg64533'),
    *[(name+'.xml', f'https://www.govinfo.gov/metadata/pkg/CHRG-119hhrg64533/{name}.xml', name, 'CHRG-119hhrg64533')
      for name in ('mods', 'premis', 'mets')],
])
def test_publisher_metadata_has_source_role_without_a_download(filename, url, record_type, identifier):
    original = dict(filename=filename, source_url=url, body_key=None)
    row = {**original, **extract((filename, url))}
    enrich_sources([row], extract=extract, read_body=lambda _: pytest.fail('No body was captured'))
    fill_document_kind(row)
    assert row['record_role'] == ['source-record']
    assert row['source_record_type'] == [record_type]
    assert row['source_record_identifier'] == [identifier]
    assert not row['document_kind']
    assert {key: row[key] for key in original} == original


@pytest.mark.parametrize('url', [
    'https://example.test/metadata/pkg/CHRG-119hhrg64533/mods.xml',
    'https://www.govinfo.gov.evil.test/metadata/pkg/CHRG-119hhrg64533/mods.xml',
    'https://www.govinfo.gov/content/pkg/CHRG-119hhrg64533/xml/mods.xml',
    'https://api.govinfo.gov/collections/CHRG/not-a-timestamp',
    'https://www.govinfo.gov/metadata/pkg/CHRG-119hhrg64533/hearing.xml',
    'https://api.govinfo.gov/packages/CHRG-119hhrg64533/summary.pdf',
])
def test_metadata_names_do_not_change_unrelated_document_roles(url):
    assert not extract((url.rsplit('/', 1)[-1], url)).get('source_record_type')


@pytest.mark.parametrize('filename', ['documents-acquire.py.before', 'linked-capture.py.before'])
def test_local_collector_backups_keep_capture_role_and_literal_provenance(filename):
    original = dict(filename=filename, source_url=None, body_key='saved',
        filename_origins=['retained_path'],
        source_paths=['raw-source-backfill-20260928/documents/metadata-review/'+filename])
    row = deepcopy(original)
    enrich_sources([row], extract=extract, read_body=lambda _: pytest.fail('Path proves collector backup'))
    assert row['record_role'] == ['capture-state']
    assert row['source_record_type'] == ['collector-artifact']
    assert {key: row[key] for key in original} == original
    # A publisher attachment with the same basename is not a collector artifact.
    public = {**original, 'source_url': 'https://example.test/'+filename}
    enrich_sources([public], extract=extract, read_body=lambda _: b'')
    assert public['record_role'] == ['document']
    unknown = {**original, 'source_paths': ['documents/'+filename]}
    enrich_sources([unknown], extract=extract, read_body=lambda _: b'')
    assert unknown['record_role'] == ['document']


FIXTURES = json.loads((Path(__file__).parent / 'fixtures/meeting_inventory/document-covers/remaining-legislative-text.json').read_text())


@pytest.mark.parametrize('case', FIXTURES, ids=lambda case: case['filename'])
def test_native_legislative_cover_variants(case):
    assert document_page_fields(case['text']) == case['expected']


@pytest.mark.parametrize('text', [
    'The committee discusses the draft below.\nS. ll\nA BILL\nBe it enacted',
    '118TH CONGRESS\nS. ll\nIN THE SENATE OF THE UNITED STATES\nLetter about a bill.\nBe it enacted',
    '118TH CONGRESS\nS. ll\nIN THE SENATE OF THE UNITED STATES\nA BILL\nSummary of proposed legislation.',
    '118TH CONGRESS\nH. RES. ll\nIN THE HOUSE OF REPRESENTATIVES\nRESOLUTION\nSummary of a proposed resolution.',
    'Dear Senators,\nPlease adopt an amendment to S. 123.\nAMENDMENT intended to be proposed by me.\nViz: New text.',
])
def test_references_and_partial_forms_do_not_establish_legislative_text(text):
    assert document_page_fields(text) == {}
