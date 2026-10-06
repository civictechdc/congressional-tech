"""Selected recovery preserves unrelated state and never leaks into broad replay."""
import copy
import json

import pytest

from congress_api.acquisition.raw_sync import run_sync
from congress_api.parsers.archive_links import allowed_url
from congress_api.retention.raw_archive import Archive
from congress_api.retention.capture_metadata import saved_readings
from test_async_capture import receipts
from test_raw_source_sync import MemoryStore, response
from test_raw_capture_only import execute
from test_capture_url_admission import catalog_store, legacy_pending

BAD = [
    'http://File URL path: /sites/default/files/documents/7.7.17DallinMaybeeTestimoney.pdf',
    'https://edworkfhttps://edworkforce.house.gov/UploadedFiles/TT_Hahn_3.15.18.pdforce.house.gov/UploadedFiles/TT_Hahn_3.15.18.pdf',
    'https://example.gov:/a.pdf', 'https://example.gov:bad/a.pdf',
    'https://example.gov:65536/a.pdf', 'https://bad host.gov/a.pdf',
    'https://example.gov\\evil.test/a.pdf', 'https://exam\nple.gov/a.pdf',
    'https://example.gov@evil.test/a.pdf', 'https://[2001:4860:4860::8888]junk/a.pdf',
]


@pytest.mark.parametrize('url', BAD)
def test_invalid_authorities_never_admitted(url):
    assert allowed_url(url) is None


@pytest.mark.parametrize('url', [
    'https://example.gov:8443/a%20b.pdf', 'https://example.gov/a b.pdf',
    'https://example.gov/download?url=https://publisher.gov/a.pdf',
    'https://[2001:4860:4860::8888]:443/a.pdf', 'https://example.gov./a.pdf',
    'https://münchen.example/a.pdf',
])
def test_valid_authorities_paths_and_query_urls_remain_valid(url):
    assert allowed_url(url) == url


def test_allowlist_and_invalid_legacy_retry_preserve_every_off_list_state():
    store = MemoryStore()
    archive = Archive(store, 'selected')
    a, b, future = [f'https://example.gov/{name}.xml' for name in ('a', 'b', 'future')]
    for url in [a, b, future]:
        archive.seed({'url': url})
        archive.state[url].update(outcome='request_failed')
    archive.state[future]['next_attempt_at'] = '2099-01-01T00:00:00+00:00'
    for url in BAD[:2]:
        legacy_pending(archive, url)
        archive.state[url].update(outcome='request_failed', attempts=7)
    before = copy.deepcopy(archive.state)
    calls = []
    def fetch(url):
        calls.append(url)
        return response(url, b'<a href="https://example.gov/new.pdf">new</a>', media='text/html')
    result = run_sync(archive, [], fetch=fetch, retry_outcomes=['request_failed'],
                      urls=[a, future, BAD[0]])
    assert calls == [a]
    assert result['attempted'] == 1 and result['fetch'] == 1
    assert result['admission_refusals'] == [dict(url=BAD[0], previous_outcome='request_failed', reason='outside_capture_scope')]
    final = Archive(store, 'read').state
    assert final[b] == before[b] and final[future] == before[future] and final[BAD[1]] == before[BAD[1]]
    assert final[BAD[0]] == {**before[BAD[0]], 'outcome': 'excluded_scope', 'next_attempt_at': None}
    assert final['https://example.gov/new.pdf']['outcome'] == 'pending'
    assert len(receipts(store)) == 1


def test_selected_pending_pass_does_not_schedule_discoveries_or_repair_other_rows():
    store = MemoryStore()
    archive = Archive(store, 'pending')
    url = 'https://example.gov/a.html'
    archive.seed({'url': url})
    legacy_pending(archive, BAD[0])
    old = dict(archive.state[BAD[0]])
    run_sync(archive, [], urls=[url], initial_only=True, fetch=lambda u:
             response(u, b'<a href="https://example.gov/b.pdf">PDF</a>', media='text/html'))
    assert archive.state[BAD[0]] == old
    assert archive.state['https://example.gov/b.pdf']['outcome'] == 'pending'
    assert len(receipts(store)) == 1


def test_catalog_refresh_cannot_reopen_exclusion_without_matching_publisher_link():
    url = 'https://example.gov/generated.xml'
    for occurrence, expected in [([], 'excluded_probe'),
        ([dict(source_link_url=['https://example.gov/other.xml'])], 'excluded_probe'),
        ([dict(source_link_url=[url], source_association_basis=['generated_xml_probe'])], 'excluded_probe'),
        ([dict(source_link_url=[url])], 'pending')]:
        store = catalog_store([dict(source_url=url, source_occurrences=occurrence,
            body_key='bodies/should-not-reopen.gz', format=['pdf'], http_status=['200'])])
        archive = Archive(store, 'old')
        archive.seed({'url': url})
        archive.state[url].update(outcome='excluded_probe', body_key=None)
        archive.save()
        # A changed catalog is the trigger; identical catalog versions are skipped.
        refreshed = catalog_store([dict(source_url=url, source_occurrences=occurrence,
            body_key='bodies/should-not-reopen.gz', format=['pdf'], http_status=['200']),
            dict(source_url='https://example.gov/new.pdf')])
        store.objects['indexes/document-filenames.parquet'] = refreshed.objects['indexes/document-filenames.parquet']
        reopened = Archive(store, 'new').state[url]
        assert reopened['outcome'] == ('retained' if expected == 'pending' else expected)
        if expected == 'excluded_probe':
            assert reopened['body_key'] is None


def test_retained_reinspection_appends_new_readings_without_http_or_new_attempts(tmp_path):
    from io import BytesIO
    from PIL import Image
    body = BytesIO()
    Image.new('RGB', (20, 30), 'red').save(body, format='PNG')
    store = MemoryStore()
    archive = Archive(store, 'old-images')
    targets = ['https://example.gov/selected.png', 'https://example.gov/other.xml']
    for url in targets:
        archive.record(response(url, body.getvalue(), media='image/png'), outcome='unverified', links=[])
    archive.save()
    before = copy.deepcopy(archive.state)
    urls = tmp_path / 'urls.json'
    urls.write_text(json.dumps(targets[:1]))
    result = execute(tmp_path, store, '--capture-only', '--urls', urls, '--reinspect-retained',
                     '--fetcher-binary', '/does-not-exist', '--transport', 'auto')
    assert result['replay'] == 1 and result.get('fetch', 0) == 0
    assert result['accounting']['native_request_dispatches'] == 0
    final = Archive(store, 'new-images').state
    assert final[targets[0]]['outcome'] == 'saved'
    assert final[targets[0]]['attempts'] == before[targets[0]]['attempts']
    assert final[targets[0]]['sha256'] == before[targets[0]]['sha256']
    assert final[targets[1]] == before[targets[1]]
    assert list(saved_readings(store))[0]['body_format'] == ['png']
    assert len(receipts(store)) == 3
    writes = list(store.writes)
    # Explicit repeat appends a new reading while preserving completed parts.
    result = execute(tmp_path, store, '--capture-only', '--urls', urls, '--reinspect-retained')
    assert len(list(saved_readings(store))) == 2
    assert not any(k.startswith('bodies/') for k in store.writes[len(writes):])


@pytest.mark.parametrize('argv', [
    ['--urls', 'missing.json'], ['--capture-only', '--reinspect-retained'],
    ['--capture-only', '--urls', 'missing.json', '--reinspect-retained', '--retry-outcome', 'retry_later'],
    ['--capture-only', '--urls', 'missing.json', '--initial-only', '--reinspect-retained'],
    ['--capture-only', '--urls', 'missing.json', '--repair'],
])
def test_invalid_target_modes_refused_before_storage(tmp_path, argv):
    with pytest.raises(SystemExit):
        execute(tmp_path, object(), *argv)
