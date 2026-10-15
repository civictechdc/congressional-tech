"""Video destinations override document-like labels without losing evidence."""
import pytest

from congress_api.parsers.committee_pages import parse_event_page, document_groups
from congress_api.retention.document_index import apply_capture_record_role, fill_document_kind


@pytest.mark.parametrize('url', [
    'https://youtu.be/-oNSVIeynzI',
    'https://www.youtube.com/watch?v=-oNSVIeynzI&feature=shared',
    'https://www.youtube.com/live/-oNSVIeynzI',
    'https://www.youtube-nocookie.com/embed/-oNSVIeynzI',
])
def test_statement_label_keeps_video_in_page_evidence_not_download_queue(url):
    parent = 'https://smallbusiness.house.gov/calendar/eventsingle.aspx?EventID=398957'
    label = 'Opening Statement (As Prepared for Delivery)'
    body = f'<main><h1>Markup</h1><a href="{url}">{label}</a><a href="/statement.pdf">Statement</a></main>'.encode()
    parsed = parse_event_page(body, parent)
    assert [row[2] for row in parsed['documents']] == ['https://smallbusiness.house.gov/statement.pdf']
    assert [row['files'][0]['url'] for row in document_groups(body, parent, '/committee_page')] == ['https://smallbusiness.house.gov/statement.pdf']
    link, = parsed['page_metadata']['links']
    assert link['text'] == label
    assert link['attributes']['href'] == url
    assert link['related_page'] == {'url': url, 'role': 'media', 'basis': 'youtube_video_url'}
    assert parsed['raw_html']


def test_rebuild_corrects_legacy_video_role_and_kind_without_removing_context():
    observation = {'source_original_page_url': ['https://committee.test/hearing'],
                   'source_link_label': ['Opening Statement']}
    row = {'source_url': 'https://youtu.be/-oNSVIeynzI', 'record_role': ['document'],
           'body_key': 'retained-html', 'document_kind': ['opening-statement'],
           'document_kind_source': ['filename'], 'source_occurrences': [observation]}
    apply_capture_record_role(row)
    fill_document_kind(row)
    assert row['record_role'] == ['source-record']
    assert row['source_record_type'] == ['youtube-video']
    assert row['document_kind'] is None
    assert row['document_family'] is None
    assert row['source_occurrences'] == [observation]
    assert row['body_key'] == 'retained-html'


@pytest.mark.parametrize('url', ['https://youtube.com.evil.test/watch?v=-oNSVIeynzI',
                                'https://committee.test/statement.pdf?video=-oNSVIeynzI',
                                'https://www.youtube.com/watch?v=invalid'])
def test_unknown_destinations_are_not_silently_removed(url):
    row = {'source_url': url, 'record_role': ['document']}
    apply_capture_record_role(row)
    assert row['record_role'] == ['document']


def test_video_alias_does_not_clear_a_real_documents_classification():
    row = {'record_role': ['document'], 'source_record_type': ['youtube-video'],
           'document_kind': ['witness-statement']}
    fill_document_kind(row)
    assert row['document_kind'] == ['witness-statement']
    assert row['document_family'] == ['statement']
