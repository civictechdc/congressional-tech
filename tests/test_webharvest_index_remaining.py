"""Index audit must not turn rejected or partial responses into absence."""
import importlib.util
import sys
from pathlib import Path
import re
from urllib.parse import urlencode

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/webharvest'))
SPEC = importlib.util.spec_from_file_location('index_audit', Path(__file__).resolve().parents[1] / 'scripts/webharvest/webharvest_index_remaining.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_compact_pattern_is_an_exact_union_including_optional_suffixes():
    keys = ['gov,house,example)/files/a.pdf', 'gov,house,example)/files/a.pdf?x=1',
            'gov,house,example)/files/b(1).pdf', 'gov,house,example)/other/a+b.pdf']
    pattern = re.compile(MODULE.key_pattern(keys))
    assert all(pattern.fullmatch(k) for k in keys)
    for other in ['gov,house,example)/files/c.pdf', keys[0] + '?x=2', keys[0] + 'extra', keys[2].replace('(1)', '1')]:
        assert not pattern.fullmatch(other)


def test_batches_stay_below_observed_request_line_limit_without_losing_keys():
    keys = [f'gov,house,example)/files/{n:05d}-some-very-long-document-name.pdf?value={n * 17}' for n in range(600)]
    batches = list(MODULE.batches('example.house.gov', keys))
    assert sorted(k for batch in batches for k in batch) == sorted(keys)
    assert all(len(urlencode(MODULE.params('example.house.gov', batch))) <= 3600 for batch in batches)


def test_empty_index_is_valid_but_html_is_not():
    assert MODULE.parse_cdx(b'') == ([], None)
    with pytest.raises(ValueError):
        MODULE.parse_cdx(b'<html><title>Session Verification</title></html>')


def test_truncation_token_is_preserved():
    raw = b'gov,house,example)/a.pdf 20240101000000 https://example.house.gov/a.pdf application/pdf 200 ABC - - 12 30 file.warc.gz\n\neJwExampleToken\n'
    rows, token = MODULE.parse_cdx(raw)
    assert rows[0]['status'] == '200'
    assert token == 'eJwExampleToken'


def test_malformed_source_domains_are_kept_out_of_network_queries():
    assert MODULE.key('http://https//example.house.gov/a.pdf') is None
    assert MODULE.key('https://user:pass@example.house.gov/a.pdf') is None
    assert MODULE.key('https://example.house.gov/a.pdf') == 'gov,house,example)/a.pdf'


@pytest.mark.parametrize('truncated', [False, True])
def test_reuse_keeps_partial_capture_leads_but_only_complete_queries_cover_absence(tmp_path, truncated):
    original = 'https://example.house.gov/a.pdf'
    canonical = MODULE.key(original)
    raw = (f'{canonical} 20240101000000 {original} application/pdf 200 ABC - - 12 30 file.warc.gz\n'
           + ('\neJwExampleToken\n' if truncated else '')).encode()
    body = tmp_path / 'request.body'
    body.write_bytes(raw)
    proof = {'metadata': str(tmp_path / 'request.json'), 'body_path': str(body), 'sha256': MODULE.digest(raw)}
    MODULE.save(Path(proof['metadata']), {'status': 200, 'complete': True, 'sha256': proof['sha256'],
        'url': 'https://webharvest.gov/congress118th/timemap/cdx?' + urlencode(MODULE.params('example.house.gov', [canonical]))})
    MODULE.save(tmp_path / 'remaining-urls.json', [original])
    MODULE.save(tmp_path / 'coverage.json', [{'source': 'fresh_targeted_index', 'collection': 'congress118th',
        'host': 'example.house.gov', 'keys': [canonical], 'requests': [proof]}])
    audit = MODULE.Audit(tmp_path / 'new', 1)
    audit.urls = [original]
    audit.by_key = {canonical: [original]}
    audit.by_host = {'example.house.gov': {canonical}}
    audit.reuse_audit(tmp_path)
    assert len(audit.matches[canonical]) == 1
    assert ('congress118th' in audit.covered[canonical]) is not truncated
    body.write_bytes(raw + b'tampered')
    with pytest.raises(ValueError, match='evidence_mismatch'):
        audit.reuse_audit(tmp_path)


@pytest.mark.parametrize('truncated', [False, True])
def test_host_inventory_covers_targets_only_when_complete_and_falls_back_when_truncated(tmp_path, truncated):
    from unittest.mock import MagicMock
    original = 'https://example.house.gov/missing.pdf'
    canonical = MODULE.key(original)
    raw = (b'gov,house,example)/other.pdf 20240101000000 https://example.house.gov/other.pdf application/pdf 200 ABC - - 12 30 file.warc.gz\n'
           + (b'\neJwExampleToken\n' if truncated else b''))
    response = MagicMock()
    response.status_code = 200
    response.headers = {'Content-Type': 'text/plain'}
    response.iter_content.return_value = [raw]
    response.__enter__.return_value = response
    audit = MODULE.Audit(tmp_path, 0)
    audit.session.close()
    audit.session = MagicMock()
    audit.session.get.return_value = response
    audit.by_key = {canonical: [original]}
    audit.fetch({'host': 'example.house.gov', 'collection': 'congress118th', 'keys': [canonical], 'mode': 'host'})
    assert ('congress118th' in audit.covered[canonical]) is not truncated
    assert not audit.matches[canonical]
    assert len(audit.jobs) == int(truncated)
    if truncated:
        assert audit.jobs[0].get('mode') != 'host'
        assert audit.jobs[0]['keys'] == [canonical]
