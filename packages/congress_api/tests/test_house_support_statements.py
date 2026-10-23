"""Retained cited statements must survive correction of witness-section leakage."""
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from congress_api.retention.body_files import content_bytes
from congress_api.parsers.committee_pages import parse_event_page

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory/house-sites/acceptance-support-statements'
SOURCES = json.loads((FIXTURES / 'manifest.json').read_text())


@pytest.mark.parametrize('source', SOURCES, ids=lambda s: s['file'])
def test_cited_statements_remain_support_documents(source):
    body = gzip.decompress((FIXTURES / source['file']).read_bytes())
    assert hashlib.sha256(body).hexdigest() == source['body_sha256']
    page = parse_event_page(body, source['url'])
    assert content_bytes(page['raw_html']) == body
    documents = {d[2]: d for d in page['documents']}
    for expected in source['expected']:
        assert documents.get(expected[2]) == expected
        assert page['document_metadata'][expected[2]]['occurrences']


@pytest.mark.parametrize('heading,label,expected', [
    ('Resources', 'Joint Statement on Human Rights', 'support document'),
    ('Submitted for the record', 'Statement of Concern', 'support document'),
    ('Resources', 'Statement by the High Commissioner', 'support document'),
    ('Resources', 'Organization home', None),
    ('Resources', 'To submit a statement', None),
    ('News', 'Joint Statement on Human Rights', None),
    ('Witnesses', 'Joint Statement on Human Rights', 'witness statement'),
])
def test_statement_designation_requires_its_own_bounded_section(heading, label, expected):
    body = f'<div class="evo-hearing__field-evo-witnesses"><h2>Witnesses</h2><section><h3>{heading}</h3><a href="https://example.org/article">{label}</a></section></div>'
    page = parse_event_page(body.encode(), 'https://example.house.gov/hearings/example')
    if expected is None:
        assert not page['documents']
        assert page['page_metadata']['links'][0]['attributes']['href'] == 'https://example.org/article'
    else:
        assert page['documents'] == [[expected, label, 'https://example.org/article']]
