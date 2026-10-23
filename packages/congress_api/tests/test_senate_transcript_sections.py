"""Transcript types follow explicit publisher sections, not nearby topic words."""
from copy import deepcopy
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.parsers.senate import parsed
from congress_api.parsers.senate_page import documents
from congress_api.replay.senate import replay
from congress_api.retention.document_index import DocumentSources, fill_document_kind, read_document_sources
from congress_api.retention.senate import cached_html_path

PAGE = 'https://www.foreign.senate.gov/hearings/modernizing-us-alliances-and-partnerships-in-the-indo-pacific'
LINK = 'https://www.foreign.senate.gov/download/04-17-24__2024-modernizing-us-alliances'
RAW = (Path(__file__).parent / 'fixtures/meeting_inventory/senate-foreign-transcripts.html').read_text()


def test_real_nested_transcript_heading_classifies_the_link_and_survives_source_index():
    page = parsed(RAW, PAGE)
    assert page['documents'] == [('transcript', '04 17 24 -- 2024 Modernizing U.S. Alliances.pdf', LINK)]
    occurrence, = page['document_metadata'][LINK]['occurrences']
    assert occurrence['headings'] == ['Transcripts']
    assert documents(RAW, PAGE) == page['documents']
    sources = DocumentSources()
    sources.add_senate({'foreign.senate.gov': {'pages': {PAGE: page}}})
    row = sources.for_url(LINK)
    assert row['source_document_type_basis'] == ['publisher_section_heading']
    assert row['source_link_heading'] == ['Transcripts']
    fill_document_kind(row)
    assert row['document_kind'] == row['document_family'] == ['transcript']


@pytest.mark.parametrize('heading', ['Transcripts', 'Transcript', 'Hearing Transcripts', 'Related Transcripts'])
def test_direct_headings_and_single_quoted_links(heading):
    page = parsed(f"<section><h2>{heading}</h2><ul><li><a href='/download/opaque'>Download</a></li></ul></section>", PAGE)
    assert page['documents'][0][0] == 'transcript'


@pytest.mark.parametrize('raw', [
    '<section><h2>Related Files</h2><a href="/download/opaque">US Response to the Coup in Burma.pdf</a></section>',
    '<section><h2>Transcript requests</h2><a href="/download/opaque">Form</a></section>',
    '<h1>Transcripts</h1><section><a href="/download/opaque">An unheaded separate section</a></section>',
    '<section><h2>Transcripts</h2><section><a href="/download/opaque">Nested unheaded section</a></section></section>',
    '<section><h2>Transcripts</h2></section><section><a href="/download/opaque">Other</a></section>',
    '<nav><h2>Transcripts</h2></nav><main><a href="/download/opaque">Other</a></main>',
    '<div class="Hearing__section"><div class="Hearing__sectionHeading"><h2>Transcripts</h2></div></div><div class="Hearing__section"><a href="/download/opaque">Other</a></div>',
])
def test_section_words_do_not_leak_into_unrelated_links(raw):
    assert parsed(raw, PAGE)['documents'][0][0] == 'other'


def test_shared_url_keeps_its_separate_heading_claims():
    raw = '<section><h2>Transcripts</h2><a href="/download/shared">Proceedings</a></section><section><h2>Related Files</h2><a href="/download/shared">Attachment</a></section>'
    page = parsed(raw, PAGE)
    sources = DocumentSources()
    sources.add_senate({'foreign.senate.gov': {'pages': {PAGE: page}}})
    occurrences = sources.for_url('https://www.foreign.senate.gov/download/shared')['source_occurrences']
    assert {(tuple(o['source_link_heading']), tuple(o['source_document_type'])) for o in occurrences} == {
        (('Transcripts',), ('transcript',)), (('Related Files',), ('other',))}


def legacy_page():
    page = parsed(RAW, PAGE)
    page['documents'] = [['other', '04 17 24 -- 2024 Modernizing U.S. Alliances.pdf', LINK]]
    for field in ('document_metadata', 'raw_html'):
        page.pop(field, None)
    return page


def test_saved_state_replay_updates_other_but_preserves_label_url_and_input(tmp_path):
    path = cached_html_path(tmp_path, PAGE)
    path.parent.mkdir()
    path.write_text(RAW)
    state = {'foreign.senate.gov': {'pages': {PAGE: legacy_page()}}}
    before = deepcopy(state)
    result, report = replay(state, tmp_path, meetings=[])
    assert state == before
    document, = result['foreign.senate.gov']['pages'][PAGE]['documents']
    assert document == ['transcript', *before['foreign.senate.gov']['pages'][PAGE]['documents'][0][1:]]
    assert report['counts']['document_types_from_sections'] == 1


@pytest.mark.parametrize('available', [True, False])
def test_archive_refresh_replays_exact_html_and_follows_redirect(tmp_path, available):
    digest = sha256(RAW.encode()).hexdigest()
    key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
    if available:
        path = tmp_path / key
        path.parent.mkdir(parents=True)
        path.write_bytes(gzip.compress(RAW.encode()))
    page = legacy_page()
    state = {'foreign.senate.gov': {'pages': {PAGE: page}, 'workflow': {
        PAGE: {'cache_replay': {'raw_sha256': digest}}}}}
    final = 'https://www.foreign.senate.gov/imo/media/doc/opaque.pdf'
    records = [('senate/pages', 'old/senate.json.gz', state), ('documents', 'old/documents/receipts.jsonl',
        {'url': LINK, 'final_url': final, 'http_status': 200})]
    captures = []
    with gzip.open(tmp_path / 'receipts.jsonl.gz', 'wt') as f:
        for n, (family, source_file, record) in enumerate(records, 1):
            f.write(json.dumps({'record': record}) + '\n')
            captures.append(dict(family=family, source_file=source_file, receipt_key='receipts.jsonl.gz', receipt_line=n))
    (tmp_path / 'indexes').mkdir()
    pq.write_table(pa.Table.from_pylist(captures), tmp_path / 'indexes/captures.parquet')
    row = read_document_sources(tmp_path, {final}).for_url(final)
    fill_document_kind(row)
    assert row['document_kind'] == (['transcript'] if available else None)
    assert row['source_page_sha256'] == [digest]
    if available:
        assert row['source_link_heading'] == ['Transcripts']
        occurrence, = row['source_occurrences']
        assert occurrence['source_page_sha256'] == [digest]
        assert occurrence['source_link_url'] == [LINK]
        assert occurrence['source_association_basis'] == ['publisher_redirect']
