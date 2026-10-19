"""Offline probes: no provider or credential needed."""
import base64
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/webharvest'))
import webharvest_recovery as recovery


def dump(path, value):
    path.write_text(json.dumps(value))
    return path


def row(raw=b''):
    return {'original_urls': ['https://veterans.house.gov/statement'], 'candidates': [{
        'replay_url': 'https://webharvest.gov/congress113th/20141209134002id_/https://veterans.house.gov/statement',
        'match_basis': 'exact_canonical_url', 'mime': 'text/html',
        'digest': base64.b32encode(hashlib.sha1(raw).digest()).decode().rstrip('=')}]}


def retained(tmp_path, rendered=False):
    raw = ('<html><title>Statement</title><body><div class="field-name-body">' + 'evidence ' * 110 + '</div></body></html>').encode()
    body = tmp_path / 'source.html'
    body.write_bytes(raw)
    item = row(raw)
    item['retained'] = {'body_path': str(body), 'bytes': len(raw), 'sha256': recovery.sha(raw),
                        'status': 200, 'complete': True, 'final_url': item['candidates'][0]['replay_url'],
                        'evidence': 'source-receipt.json', 'rendered_copy': rendered, 'origin_status': 200}
    config = {'provider': 'retained', 'deferred': str(dump(tmp_path / 'deferred.json', [])), 'delay_seconds': 0}
    directory = tmp_path / 'attempt'
    directory.mkdir()
    return item, config, directory


def test_retained_source_and_rendered_provenance(tmp_path):
    item, config, directory = retained(tmp_path)
    result = recovery.fetch(item, config, directory, None)
    assert result['valid'] and result['source_bytes_identity_claimed']
    assert result['reused_evidence'] == 'source-receipt.json'
    item['retained']['rendered_copy'] = True
    item['candidates'][0]['digest'] = 'DIFFERENT'
    rendered_dir = tmp_path / 'rendered'
    rendered_dir.mkdir()
    result = recovery.fetch(item, config, rendered_dir, None)
    assert result['valid'] and result['rendered_copy']
    assert not result['index_digest_matches'] and not result['source_bytes_identity_claimed']


def test_dispositions_preserve_all_prior_failure_categories(tmp_path):
    categories = ['error_or_challenge', 'historical_no_prepared_statement', 'empty_document_body', 'short_text_needs_review']
    prior = []
    queue = []
    for number, category in enumerate(categories):
        item = row()
        item['original_urls'] = [f'https://example.gov/{number}']
        queue.append(item)
        prior.append({'original_urls': item['original_urls'], 'content': {'category': category}, 'valid': False})
    planned = recovery.plan(dump(tmp_path / 'queue.json', queue),
                            [dump(tmp_path / 'prior.json', prior)], [], dump(tmp_path / 'deferred.json', []))
    assert [r['disposition'] for r in planned['rows']] == ['retryable-failure', 'terminal-content', 'review-required', 'review-required']
    assert all(not r['eligible'] for r in planned['rows'])


def test_deferred_body_and_original_are_excluded(tmp_path):
    item, config, directory = retained(tmp_path)
    dump(Path(config['deferred']), [{'url': item['original_urls'][0], 'sha256': item['retained']['sha256']}])
    assert not recovery.fetch(item, config, directory, None)['valid']
    with pytest.raises(ValueError, match='deferred'):
        recovery.acquire(dump(tmp_path / 'queue.json', [item]), config, tmp_path / 'run')


def test_changed_retained_bytes_fail(tmp_path):
    item, config, directory = retained(tmp_path)
    Path(item['retained']['body_path']).write_bytes(b'changed')
    result = recovery.fetch(item, config, directory, None)
    assert not result['valid'] and result['error_type'] == 'ValueError'


def test_process_identity_rejects_stale_pid_identity():
    current = recovery.process_identity()
    assert recovery.reservation_live(current)
    assert not recovery.reservation_live(dict(current, start_and_command='different-process'))


def test_pagination_requires_explicit_end_and_every_page():
    assert not recovery.pagination_state([{'cursor': None, 'rows': 1}])['complete']
    assert not recovery.pagination_state([{'cursor': None, 'continuation': 'next', 'rows': 0}])['complete']
    assert recovery.pagination_state([{'cursor': None, 'continuation': 'next'},
                                      {'cursor': 'next', 'continuation': None, 'complete': True}])['complete']
    assert not recovery.pagination_state([{'cursor': None, 'continuation': None}])['complete']


def test_budget_and_credentials_are_explicit(tmp_path):
    config = {'provider': 'firecrawl', 'credential_env': 'TEST_PROVIDER_KEY', 'max_requests': 26,
              'request_ceiling_usd': 1, 'budget_usd': 25}
    with pytest.raises(ValueError, match='budget'):
        recovery.load_config(dump(tmp_path / 'config.json', config))
    config['max_requests'] = 25
    assert recovery.load_config(dump(tmp_path / 'config.json', config))['credential_env'] == 'TEST_PROVIDER_KEY'


def test_successful_download_not_repeated(tmp_path, monkeypatch):
    item, config, directory = retained(tmp_path)
    queue = dump(tmp_path / 'queue.json', [item])
    run = tmp_path / 'run'
    recovery.acquire(queue, config, run)
    monkeypatch.setattr(recovery, 'fetch', lambda *args: pytest.fail('Repeated successful download'))
    assert recovery.acquire(queue, config, run)['completed'] == 1


def test_interrupted_after_download_resumes_without_fetch(tmp_path, monkeypatch):
    item, config, directory = retained(tmp_path)
    queue = dump(tmp_path / 'queue.json', [item])
    run = tmp_path / 'run'
    real_classify = recovery.classify_cached
    monkeypatch.setattr(recovery, 'classify_cached', lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        recovery.acquire(queue, config, run)
    assert len(list((run / 'downloads').glob('*/download.json'))) == 1
    assert not list((run / 'requests').glob('*/receipt.json'))
    monkeypatch.setattr(recovery, 'classify_cached', real_classify)
    monkeypatch.setattr(recovery.requests.Session, 'get', lambda *args, **kw: pytest.fail('Repeated request'))
    result = recovery.acquire(queue, config, run)
    assert result['complete'] and result['completed'] == 1
    assert recovery.receipt_rows(run)[0]['valid']
    (run / 'results.json').unlink()
    (run / 'progress.json').unlink()
    assert recovery.aggregate(run)['complete']
    assert len(recovery.read(run / 'results.json')) == 1


def test_in_flight_interruption_never_automatically_retries(tmp_path, monkeypatch):
    item, config, directory = retained(tmp_path)
    queue = dump(tmp_path / 'queue.json', [item])
    monkeypatch.setattr(recovery, 'fetch', lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        recovery.acquire(queue, config, tmp_path / 'run')
    monkeypatch.setattr(recovery, 'fetch', lambda *args: pytest.fail('In-flight request retried'))
    result = recovery.acquire(queue, config, tmp_path / 'run')
    assert result['dispositions'] == {'review-required': 1}


def test_same_source_download_and_extraction_reused_for_multiple_originals(tmp_path, monkeypatch):
    item, config, directory = retained(tmp_path)
    second = dict(item, original_urls=['https://veterans.house.gov/alternate'])
    queue = dump(tmp_path / 'queue.json', [item, second])
    run = tmp_path / 'run'
    assert recovery.acquire(queue, config, run)['completed'] == 2
    assert len(list((run / 'downloads').glob('*/download.json'))) == 1
    assert len(list((run / 'classification-cache').glob('*.json'))) == 1
    receipts = recovery.receipt_rows(run)
    assert {tuple(r['original_urls']) for r in receipts} == {tuple(item['original_urls']), tuple(second['original_urls'])}
    assert all('text' not in r['content'] for r in receipts)


def test_receipts_are_immutable_and_aggregate_written_once(tmp_path, monkeypatch):
    item, config, directory = retained(tmp_path)
    rows = [dict(item, original_urls=[f'https://example.gov/{i}']) for i in range(20)]
    queue = dump(tmp_path / 'queue.json', rows)
    run = tmp_path / 'run'
    aggregate_writes = []
    real_save = recovery.save
    def track(path, value):
        if Path(path).name == 'results.json':
            aggregate_writes.append(len(json.dumps(value)))
        return real_save(path, value)
    monkeypatch.setattr(recovery, 'save', track)
    recovery.acquire(queue, config, run)
    assert len(aggregate_writes) == 1
    receipt = next((run / 'requests').glob('*/receipt.json'))
    raw = receipt.read_bytes()
    with pytest.raises(FileExistsError):
        recovery.immutable(receipt, {'changed': True})
    assert receipt.read_bytes() == raw


def test_classifier_cache_invalidation_and_frozen_source(tmp_path):
    from webharvest_validation import freeze, classify_cached
    item, config, directory = retained(tmp_path)
    raw = Path(item['retained']['body_path']).read_bytes()
    snapshot = tmp_path / 'snapshot'
    validator = freeze(snapshot, {'rule': 1})
    first, proof = classify_cached(raw, tmp_path / 'cache', snapshot, validator)
    assert first['category'] == 'substantial_document_body'
    assert freeze(snapshot, {'rule': 1}) == validator
    with pytest.raises(ValueError, match='configuration'):
        freeze(snapshot, {'rule': 2})
    other = tmp_path / 'snapshot2'
    changed = freeze(other, {'rule': 2})
    _, next_proof = classify_cached(raw, tmp_path / 'cache', other, changed)
    assert proof['path'] != next_proof['path']
    _, body_proof = classify_cached(raw.replace(b'evidence', b'testimony'), tmp_path / 'cache', snapshot, validator)
    assert body_proof['path'] != proof['path']
    # Published cache result remains reusable even if current classifier code moves.
    (snapshot / 'classifier.py').write_text('raise AssertionError("not executed for cache hit")')
    assert classify_cached(raw, tmp_path / 'cache', snapshot, validator)[0] == first
    with pytest.raises(ValueError, match='classifier changed'):
        freeze(snapshot, {'rule': 1})


def test_completed_receipt_qualification_preserves_source_and_provenance(tmp_path):
    item, config, directory = retained(tmp_path, rendered=True)
    run = tmp_path / 'run'
    recovery.acquire(dump(tmp_path / 'queue.json', [item]), config, run)
    source = next((run / 'requests').glob('*/receipt.json'))
    output = tmp_path / 'qualified'
    result = recovery.qualify([source], output, Path(config['deferred']))
    assert result['qualified'] == 1
    receipt = recovery.receipt_rows(output)[0]
    assert receipt['rendered_copy'] and not receipt['source_bytes_identity_claimed']
    assert receipt['source_receipt_sha256'] == recovery.sha(source.read_bytes())
    assert not receipt['worker_completion_claimed']


def test_pdf_checks_keep_decoders_and_preview_is_optional(tmp_path, monkeypatch):
    import gzip
    from webharvest_validation import validate_pdf
    fixtures = Path(__file__).parent / 'fixtures/capture-failures'
    # Real historical parser failures remain readable by Poppler; neither check is dropped.
    for name in ['numeric-operand.pdf.gz', 'malformed-text-array.pdf.gz']:
        body = tmp_path / name[:-3]
        raw = gzip.decompress((fixtures / name).read_bytes())
        body.write_bytes(raw)
        result = validate_pdf(body, tmp_path / name)
        assert result['valid_pdf'] and result['all_pages_rendered'] == result['pages_decoded']
        assert not result['preview_requested'] and 'preview_exit' not in result
        body.write_bytes(raw[:100])
        assert not validate_pdf(body, tmp_path / ('truncated-' + name))['valid_pdf']
    # Preview failure cannot veto acceptance; acceptance renderer still runs.
    body = tmp_path / 'valid.pdf'
    body.write_bytes(gzip.decompress((fixtures / 'numeric-operand.pdf.gz').read_bytes()))
    real_run = recovery.subprocess.run
    def fail_preview(command, **kwargs):
        if '-png' in command:
            raise recovery.subprocess.TimeoutExpired(command, 45)
        return real_run(command, **kwargs)
    monkeypatch.setattr(recovery.subprocess, 'run', fail_preview)
    assert validate_pdf(body, tmp_path / 'optional-preview', preview=True)['valid_pdf']


def test_blocked_run_does_not_resume_acquisition_automatically(tmp_path, monkeypatch):
    item, config, directory = retained(tmp_path)
    other = dict(item, original_urls=['https://example.gov/other'],
                 candidates=[dict(item['candidates'][0], replay_url=item['candidates'][0]['replay_url'] + '/other')])
    queue = dump(tmp_path / 'queue.json', [item, other])
    def blocked(row, *args):
        return {'original_urls': row['original_urls'], 'status': 429, 'valid': False,
                'disposition': 'retryable-failure'}
    monkeypatch.setattr(recovery, 'fetch', blocked)
    assert recovery.acquire(queue, config, tmp_path / 'run')['completed'] == 1
    monkeypatch.setattr(recovery, 'fetch', lambda *args: pytest.fail('Blocked campaign resumed'))
    assert recovery.acquire(queue, config, tmp_path / 'run')['completed'] == 1


def test_direct_media_rejected_before_body_download(tmp_path):
    item, config, directory = retained(tmp_path)
    config['provider'] = 'direct'
    class Media:
        status_code = 200
        url = item['candidates'][0]['replay_url']
        headers = {'content-type': 'video/mp4'}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def iter_content(self, *args):
            pytest.fail('Media body read')
    class Session:
        def get(self, *args, **kwargs):
            return Media()
    result = recovery.fetch(item, config, directory, Session())
    assert not result['valid'] and 'body_path' not in result


def test_firecrawl_exact_url_origin_and_secret_headers(tmp_path, monkeypatch):
    item, config, directory = retained(tmp_path)
    config.update(provider='firecrawl', credential_env='OFFLINE_TEST_KEY')
    monkeypatch.setenv('OFFLINE_TEST_KEY', 'offline-secret-must-not-appear')
    raw = Path(item['retained']['body_path']).read_text()
    class Response:
        status_code = 200
        def json(self):
            return {'data': {'rawHtml': raw, 'metadata': {'statusCode': 200,
                    'url': item['candidates'][0]['replay_url'], 'contentType': 'text/html'}}}
    class Session:
        def post(self, url, **kwargs):
            assert kwargs['headers']['Authorization'] == 'Bearer offline-secret-must-not-appear'
            return Response()
    result = recovery.fetch(item, config, directory, Session())
    assert result['valid'] and result['rendered_copy']
    assert 'offline-secret-must-not-appear' not in json.dumps(result)
    assert not result['source_bytes_identity_claimed']


def test_stale_reservations_and_deferred_body_do_not_become_eligible(tmp_path):
    item = row()
    queue = dump(tmp_path / 'queue.json', [item])
    forbidden = dump(tmp_path / 'deferred.json', [{'url': 'https://elsewhere.gov/other', 'sha256': 'blocked-body'}])
    prior = dump(tmp_path / 'prior.json', {'original_urls': item['original_urls'], 'valid': True, 'sha256': 'blocked-body'})
    result = recovery.plan(queue, [prior], [], forbidden)
    assert result['rows'][0]['disposition'] == 'review-required'
    stale = dump(tmp_path / 'reservation.json', {'process': dict(recovery.process_identity(), start_and_command='stale'), 'original_urls': item['original_urls']})
    result = recovery.plan(queue, [], [stale], forbidden)
    assert result['rows'][0]['disposition'] == 'review-required'
    assert not result['rows'][0]['eligible']


def test_duplicate_pagination_cursor_cannot_hide_an_incomplete_chain():
    assert not recovery.pagination_state([{'cursor': None, 'continuation': 'next'},
                                          {'cursor': None, 'continuation': None, 'complete': True}])['complete']


def test_new_classifier_source_invalidates_cache(tmp_path, monkeypatch):
    import webharvest_validation as validation
    item, config, directory = retained(tmp_path)
    raw = Path(item['retained']['body_path']).read_bytes()
    first = validation.freeze(tmp_path / 'first', {})
    package = tmp_path / 'package'
    package.mkdir()
    real = validation.classifier_directory()
    for name in ['html.py']:
        (package / name).write_bytes((real / name).read_bytes() + b'\n# newer classifier source\n')
    monkeypatch.setattr(validation, 'classifier_directory', lambda: package)
    second = validation.freeze(tmp_path / 'second', {})
    assert first['classifier_sha256'] != second['classifier_sha256']
    _, a = validation.classify_cached(raw, tmp_path / 'cache', tmp_path / 'first', first)
    _, b = validation.classify_cached(raw, tmp_path / 'cache', tmp_path / 'second', second)
    assert a['path'] != b['path']


def test_pdf_qualification_reuses_frozen_acceptance_and_checks_retained_bytes(tmp_path):
    import gzip
    raw = gzip.decompress((Path(__file__).parent / 'fixtures/capture-failures/numeric-operand.pdf.gz').read_bytes())
    body = tmp_path / 'retained.pdf'
    body.write_bytes(raw)
    source = dump(tmp_path / 'receipt.json', {'original_url': 'https://example.gov/file.pdf',
                  'requested_url': 'https://example.gov/file.pdf', 'final_url': 'https://example.gov/file.pdf',
                  'body_path': str(body), 'sha256': recovery.sha(raw), 'bytes': len(raw),
                  'complete': True, 'status': 200, 'kind': 'pdf'})
    deferred = dump(tmp_path / 'deferred.json', [])
    output = tmp_path / 'qualified'
    assert recovery.qualify([source], output, deferred, kind='pdf')['qualified'] == 1
    assert recovery.qualify([source], output, deferred, kind='pdf')['qualified'] == 1
    assert len(list((output / 'pdf-cache').glob('*/acceptance.json'))) == 1
    result = recovery.receipt_rows(output)[0]
    assert result['source_receipt_sha256'] == recovery.sha(source.read_bytes())
    assert not result['source_bytes_identity_claimed']
    body.write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash or length'):
        recovery.qualify([source], output, deferred, kind='pdf')


def test_cookie_routes_to_target_for_both_provider_modes(tmp_path, monkeypatch):
    item, config, directory = retained(tmp_path)
    config.update(provider='firecrawl', credential_env='OFFLINE_TEST_KEY', cookie_env='OFFLINE_TARGET_COOKIE')
    monkeypatch.setenv('OFFLINE_TEST_KEY', 'offline-api-secret')
    monkeypatch.setenv('OFFLINE_TARGET_COOKIE', 'session=offline-target-cookie')
    raw = Path(item['retained']['body_path']).read_text()
    class Response:
        status_code = 200
        url = item['candidates'][0]['replay_url']
        headers = {'content-type': 'text/html'}
        def json(self):
            return {'data': {'rawHtml': raw, 'metadata': {'statusCode': 200, 'url': self.url}}}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def iter_content(self, *args): return iter([raw.encode()])
    class Session:
        def post(self, url, **kwargs):
            assert 'Cookie' not in kwargs['headers']
            assert kwargs['json']['headers']['Cookie'] == 'session=offline-target-cookie'
            return Response()
        def get(self, url, **kwargs):
            assert kwargs['headers']['Cookie'] == 'session=offline-target-cookie'
            return Response()
    result = recovery.fetch(item, config, directory, Session())
    assert result['valid'] and 'offline-target-cookie' not in json.dumps(result)
    other = tmp_path / 'direct-cookie'
    other.mkdir()
    assert recovery.fetch(item, dict(config, provider='direct'), other, Session())['valid']


def test_firecrawl_origin_refusal_stops_even_when_transport_is_200(tmp_path, monkeypatch):
    item, config, directory = retained(tmp_path)
    other = dict(item, original_urls=['https://example.gov/other'],
                 candidates=[dict(item['candidates'][0], replay_url=item['candidates'][0]['replay_url'] + '/other')])
    config.update(provider='firecrawl', workers=1, credential_env='OFFLINE_TEST_KEY')
    monkeypatch.setenv('OFFLINE_TEST_KEY', 'offline-only')
    calls = []
    class Session:
        def post(self, url, **kwargs):
            calls.append(kwargs['json']['url'])
            class Response:
                status_code = 200
                def json(self):
                    return {'data': {'rawHtml': '<html><title>Unavailable</title></html>',
                            'metadata': {'statusCode': 429, 'url': kwargs['json']['url']}}}
            return Response()
        def close(self): pass
    monkeypatch.setattr(recovery.requests, 'Session', Session)
    result = recovery.acquire(dump(tmp_path / 'queue.json', [item, other]), config, tmp_path / 'run')
    assert len(calls) == 1 and result['completed'] == 1
    assert recovery.receipt_rows(tmp_path / 'run')[0]['origin_status'] == 429
    assert recovery.receipt_rows(tmp_path / 'run')[0]['disposition'] == 'retryable-failure'
    assert recovery.acquire(tmp_path / 'queue.json', config, tmp_path / 'run')['completed'] == 1
    assert len(calls) == 1


def test_bounded_workers_overlap_and_share_one_start_clock(tmp_path, monkeypatch):
    import threading
    import time
    item, config, directory = retained(tmp_path)
    config.update(workers=5, delay_seconds=0.025)
    rows = [dict(item, original_urls=[f'https://example.gov/{i}'],
                 candidates=[dict(item['candidates'][0], replay_url=item['candidates'][0]['replay_url'] + f'/{i}')]) for i in range(7)]
    times = []
    active = [0, 0]
    lock = threading.Lock()
    def fetch(row, *args):
        with lock:
            times.append(time.monotonic())
            active[0] += 1
            active[1] = max(active[1], active[0])
        time.sleep(0.11)
        with lock: active[0] -= 1
        return {'original_urls': row['original_urls'], 'valid': True, 'status': 200, 'disposition': 'qualified'}
    monkeypatch.setattr(recovery, 'fetch', fetch)
    result = recovery.acquire(dump(tmp_path / 'queue.json', rows), config, tmp_path / 'run')
    assert result['completed'] == 7 and 2 <= active[1] <= 5
    assert min(b-a for a, b in zip(times, times[1:])) >= 0.020
    with pytest.raises(ValueError, match='Workers'):
        recovery.acquire(tmp_path / 'queue.json', dict(config, workers=6), tmp_path / 'invalid')


def test_parallel_refusal_prevents_additional_admissions(tmp_path, monkeypatch):
    import threading
    import time
    item, config, directory = retained(tmp_path)
    config.update(workers=5, delay_seconds=0)
    rows = [dict(item, original_urls=[f'https://example.gov/{i}'],
                 candidates=[dict(item['candidates'][0], replay_url=item['candidates'][0]['replay_url'] + f'/{i}')]) for i in range(12)]
    calls = []
    def fetch(row, *args):
        calls.append(row['original_urls'][0])
        if row['original_urls'][0].endswith('/0'):
            return {'original_urls': row['original_urls'], 'valid': False, 'status': 200, 'origin_status': 403,
                    'disposition': 'retryable-failure'}
        time.sleep(0.02)
        return {'original_urls': row['original_urls'], 'valid': True, 'status': 200, 'disposition': 'qualified'}
    monkeypatch.setattr(recovery, 'fetch', fetch)
    recovery.acquire(dump(tmp_path / 'queue.json', rows), config, tmp_path / 'run')
    assert 1 <= len(calls) <= 5
    assert not any(url.endswith(('/5', '/6', '/7', '/8', '/9', '/10', '/11')) for url in calls)


def test_prior_aggregate_is_read_and_hashed_once(tmp_path, monkeypatch):
    items = [dict(row(), original_urls=[f'https://example.gov/{i}']) for i in range(100)]
    prior = dump(tmp_path / 'prior.json', [{'original_urls': r['original_urls'], 'valid': False} for r in items])
    original = Path.read_bytes
    reads = []
    def track(path):
        if path == prior: reads.append(path)
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', track)
    planned = recovery.plan(dump(tmp_path / 'queue.json', items), [prior], [], dump(tmp_path / 'deferred.json', []))
    assert len(planned['rows']) == 100 and len(reads) == 1


def test_parallel_same_body_extracts_once(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import time
    import webharvest_validation as validation
    item, config, directory = retained(tmp_path)
    raw = Path(item['retained']['body_path']).read_bytes()
    snapshot = tmp_path / 'snapshot'
    validator = validation.freeze(snapshot, {})
    misses = []
    original = validation._classify_cached
    def track(raw, directory, snapshot, validator):
        path = directory / (validation.digest(raw) + '-' + validator['validator_sha256'] + '.json')
        if not path.exists():
            misses.append(path)
            time.sleep(0.02)
        return original(raw, directory, snapshot, validator)
    monkeypatch.setattr(validation, '_classify_cached', track)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: validation.classify_cached(raw, tmp_path / 'cache', snapshot, validator), range(10)))
    assert len(misses) == 1 and len({r[1]['path'] for r in results}) == 1


def test_parallel_admission_respects_finite_request_grant(tmp_path, monkeypatch):
    item, config, directory = retained(tmp_path)
    config.update(workers=5, delay_seconds=0, max_requests=2)
    rows = [dict(item, original_urls=[f'https://example.gov/{i}'],
                 candidates=[dict(item['candidates'][0], replay_url=item['candidates'][0]['replay_url'] + f'/{i}')]) for i in range(8)]
    calls = []
    def fetch(row, *args):
        calls.append(row)
        return {'original_urls': row['original_urls'], 'valid': True, 'status': 200, 'disposition': 'qualified'}
    monkeypatch.setattr(recovery, 'fetch', fetch)
    result = recovery.acquire(dump(tmp_path / 'queue.json', rows), config, tmp_path / 'run')
    assert len(calls) == result['completed'] == result['downloads_started'] == 2


def test_frozen_classifier_preserves_printed_transcript_and_historical_snapshots(tmp_path):
    import webharvest_validation as validation
    raw = ('<html><title>Committee on Veterans Affairs hearing</title><body>'
           'HEARING BEFORE HOUSE OF REPRESENTATIVES SERIAL No. 112-11 '
           'Printed for the use of the committee ' + 'testimony ' * 500 + '</body></html>').encode()
    snapshot = tmp_path / 'snapshot'
    validator = validation.freeze(snapshot, {})
    content, _ = validation.classify_cached(raw, tmp_path / 'cache', snapshot, validator)
    assert content['category'] == 'substantial_document_body'
    assert content['subtype'] == 'printed_hearing_transcript'
    # Already-retained snapshots used classify as the public wrapper name.
    historical = tmp_path / 'historical'
    historical.mkdir()
    source = b'def classify(raw):\n    return {"category":"substantial_document_body","subtype":"historical"}\n'
    (historical / 'classifier.py').write_bytes(source)
    prior = dict(validator, classifier_sha256=validation.digest(source), validator_sha256='historical')
    original, _ = validation.classify_cached(raw, tmp_path / 'cache', historical, prior)
    assert original['subtype'] == 'historical'
