"""Offline probes: no provider or credential needed."""
import base64
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
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
                        'evidence': 'source-receipt.json', 'rendered_copy': rendered}
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
    result = recovery.fetch(item, config, directory, None)
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
