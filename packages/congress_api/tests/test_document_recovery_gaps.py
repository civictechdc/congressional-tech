"""Regressions from the complete unavailable-outcome audit."""
from pathlib import Path
import pytest
from congress_api.parsers.document_links import document_links, response_kind
from congress_api.retention.capture_inspection import inspect_body
from congress_api.retention.document_evidence import document_body_fields

PAGE = 'https://www.congress.gov/bill/119th-congress/house-bill/1'
PREAMBLE = bytes.fromhex('75ab5afdaa6996271ab62a27fe975ffdb6ac7baeff')

@pytest.mark.parametrize('mime,suffix', [('application/pdf','pdf'), ('application/xml','xml'), ('text/xml','xml')])
def test_publisher_alternate_retains_exact_attributes(mime,suffix):
    href = f' /119/bills/hr1/BILLS-119hr1ih.{suffix} '
    raw = f'<html><head><link rel="alternate" type="{mime}" href="{href}" title="Introduced"/></head></html>'.encode()
    link, = document_links(raw, PAGE)
    assert link.url == 'https://www.congress.gov' + href.strip()
    assert link.basis == 'alternate_document'
    assert link.tag == 'link'
    assert link.attributes == {'rel':'alternate','type':mime,'href':href,'title':'Introduced'}

@pytest.mark.parametrize('tag', [
 '<link rel="alternate" type="application/rss+xml" href="/rss.xml">',
 '<link rel="alternate" type="application/atom+xml" href="/atom.xml">',
 '<link rel="search" type="application/opensearchdescription+xml" href="/search.xml">',
 '<link rel="stylesheet" type="application/pdf" href="/style.pdf">',
 '<link rel="alternate" type="text/html" href="/translated">',
 '<link rel="alternate" type="text/xml" href="/sitemap.xml">',
 '<link rel="alternate" type="application/pdf" href="#top">',
 '<link rel="alternate" type="application/pdf" href="javascript:alert(1)">',
 '<link rel="alternate" type="application/pdf" href="https://user:pass@example.gov/file.pdf">',
])
def test_non_document_alternates_and_circular_links_are_not_promoted(tag):
    assert document_links(('<html><head>'+tag+'</head></html>').encode(), PAGE) == []

def test_alternate_tokens_base_and_duplicate_target():
    raw = b'<html><head><base href="https://www.congress.gov/files/"><link rel="ALTERNATE enclosure" type="Application/PDF; charset=binary" href="a"></head><body><a href="https://www.congress.gov/files/a" download>PDF</a></body></html>'
    link, = document_links(raw, PAGE)
    assert link.url == 'https://www.congress.gov/files/a'
    assert link.tag == 'link'


def test_binary_preamble_pdf_is_recognized_by_capture_and_metadata():
    pdf = (Path(__file__).parent/'fixtures/meeting_inventory/document-covers/biography.pdf')
    if not pdf.exists():
        pdf = Path(__file__).parent/'fixtures/meeting_inventory/document-covers/opening.pdf'
    data = PREAMBLE + pdf.read_bytes()
    assert response_kind(data,'application/pdf') == 'pdf'
    assert inspect_body(data,'https://example.gov/file.pdf','application/pdf')[0] == 'saved'
    assert document_body_fields(data)['body_format'] == ['pdf']

@pytest.mark.parametrize('data', [
 b'<html><body>%PDF-1.3\n fake %%EOF</body></html>',
 b'<?xml version="1.0"?><x>%PDF-1.3\n fake %%EOF</x>',
 b'This text describes %PDF-1.3\n fake %%EOF',
 b'\xff'*1024 + b'%PDF-1.3\n fake %%EOF',
])
def test_header_mentions_are_not_pdfs(data):
    assert response_kind(data,'application/pdf') != 'pdf'


def test_binary_preamble_does_not_bypass_readability_validation():
    assert inspect_body(PREAMBLE+b'%PDF-1.3\nfake\n%%EOF','https://example.gov/a.pdf','application/pdf')[0] == 'invalid_document'
