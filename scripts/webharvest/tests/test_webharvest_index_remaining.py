"""Index audit must not turn rejected or partial responses into absence."""
import importlib.util
import sys
from pathlib import Path
import re
from urllib.parse import urlencode

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location('index_audit', SCRIPTS / 'webharvest_index_remaining.py')
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
    host, collection = 'example.house.gov', 'congress118th'
    batches = list(MODULE.batches(host, collection, keys))
    assert sorted(k for batch in batches for k in batch) == sorted(keys)
    for batch in batches:
        url = MODULE.job_url({'host': host, 'collection': collection, 'keys': batch})
        line = f'GET {url.removeprefix("https://webharvest.gov")} HTTP/1.1'
        assert len(line.encode('ascii')) <= 4094


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


def test_rejected_request_line_splits_only_that_query_and_keeps_completed_coverage(tmp_path):
    from unittest.mock import MagicMock

    host = 'example.house.gov'
    keys = [MODULE.key(f'https://{host}/{n}.pdf') for n in range(3)]
    response = MagicMock()
    response.status_code = 400
    response.headers = {'Content-Type': 'text/html'}
    response.iter_content.return_value = [b'Request Line is too large (4207 &gt; 4094)']
    response.__enter__.return_value = response
    audit = MODULE.Audit(tmp_path, 0)
    audit.session.close()
    audit.session = MagicMock()
    audit.session.get.return_value = response
    audit.covered[keys[0]].add('congress118th')
    job = {'host': host, 'collection': 'congress118th', 'keys': keys[1:]}
    audit.fetch(job)
    assert [j['keys'] for j in audit.jobs] == [[keys[1]], [keys[2]]]
    assert audit.errors[0]['reason'] == 'server_request_line_limit_split'
    assert dict(audit.covered) == {keys[0]: {'congress118th'}}


def test_overlong_single_target_has_no_network_attempt(tmp_path):
    from unittest.mock import MagicMock

    audit = MODULE.Audit(tmp_path, 0)
    audit.session.close()
    audit.session = MagicMock()
    with pytest.raises(ValueError, match='single_url_exceeds_request_line_limit'):
        audit.fetch({'host': 'example.house.gov', 'collection': 'congress118th', 'keys': ['x' * 4200]})
    audit.session.get.assert_not_called()
    assert not audit.covered
