"""Source retry hints preserve native captures and avoid premature provider fallback."""

import json
import sys

import pytest

from congress_api.models.content import content_bytes
from congress_api.transport.rust_fetch import RustFetcher


GENERATION_BODY = (b'<html><title>Please Retry later in 30 Seconds</title>'
                   b'<body>The ZIP file you have requested is being generated</body></html>')


def native_worker(tmp_path, *, status=503, retry_after='15', body=GENERATION_BODY,
                  complete=True, headers=None):
    """Script the native protocol, including the rejected fallback's raw response."""
    binary = tmp_path / 'worker'
    calls = tmp_path / 'calls.jsonl'
    header_items = [{'name': 'Content-Type', 'value': 'text/html'}]
    if retry_after is not None:
        header_items.append({'name': 'Retry-After', 'value': retry_after})
    header_items.extend(headers or [])
    binary.write_text(f'''#!{sys.executable}
import sys,json,pathlib
root=pathlib.Path(sys.argv[1])
for line in sys.stdin:
 r=json.loads(line)
 with pathlib.Path({str(calls)!r}).open('a') as log:
  log.write(json.dumps(r)+'\\n')
 direct=r['transport']=='direct'
 data={body!r} if direct else b'{{"type":"WebsiteBan"}}'
 p=root/(str(r['id'])+'.body')
 p.write_bytes(data)
 response=dict(body_file=str(p),http_status={status!r} if direct else 520,
  final_url=r['url'],response_header_items={header_items!r} if direct else [],
  complete={complete!r},bytes=len(data))
 print(json.dumps(dict(id=r['id'],response=response)),flush=True)
''')
    binary.chmod(0o700)
    return binary, calls


def test_govinfo_generation_keeps_direct_evidence_and_schedules_thirty_seconds(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYTE_TOKEN', 'fixture-token')
    binary, calls = native_worker(tmp_path)
    url = 'https://www.govinfo.gov/content/pkg/CHRG-119hhrg00001.zip'
    with RustFetcher(binary) as fetcher:
        result, inspection = fetcher.fetch_spooled(url, before_read=lambda: None)
        assert not list(fetcher.root.glob('*.body'))
    assert inspection == ('retry_later', [])
    assert result['retry_later'] == {'delay_seconds': 30, 'reason': 'govinfo_zip_generation'}
    assert result['http_status'] == 503 and result['complete']
    assert result['response_headers']['retry-after'] == '15'
    assert {'name': 'Retry-After', 'value': '15'} in result['response_header_items']
    assert content_bytes(result['content']) == GENERATION_BODY
    assert 'prior_attempts' not in result
    assert [json.loads(line)['transport'] for line in calls.read_text().splitlines()] == ['direct']


@pytest.mark.parametrize('status,retry_after,delay', [
    (429, '60', 60), (503, '0', 1), (503, '3600', 3600),
    (503, '7200', 7200), (503, '9999999999999999999999', 2**31 - 1),
])
def test_valid_retry_after_avoids_provider(tmp_path, monkeypatch, status, retry_after, delay):
    monkeypatch.setenv('ZYTE_TOKEN', 'fixture-token')
    binary, calls = native_worker(tmp_path, status=status, retry_after=retry_after, body=b'busy')
    with RustFetcher(binary) as fetcher:
        result, inspection = fetcher.fetch_spooled('https://example.gov/file', before_read=lambda: None)
    assert inspection == ('retry_later', [])
    assert result['retry_later'] == {'delay_seconds': delay, 'reason': 'retry_after'}
    assert len(calls.read_text().splitlines()) == 1


@pytest.mark.parametrize('status,header,complete', [
    (503, None, True), (503, '-1', True), (503, '1.5', True),
    (503, 'nonsense', True), (503, '9' * 5000, True),
    (403, '15', True), (200, '15', True), (503, '15', False),
])
def test_invalid_hint_or_ineligible_response_preserves_fallback(tmp_path, monkeypatch, status, header, complete):
    monkeypatch.setenv('ZYTE_TOKEN', 'fixture-token')
    binary, calls = native_worker(tmp_path, status=status, retry_after=header, body=b'busy', complete=complete)
    with RustFetcher(binary) as fetcher:
        result, _ = fetcher.fetch_spooled('https://example.gov/file', before_read=lambda: None)
    assert 'retry_later' not in result
    assert result['prior_attempts'][0]['http_status'] == status
    assert [json.loads(line)['transport'] for line in calls.read_text().splitlines()] == ['direct', 'zyte']


def test_duplicate_retry_after_with_invalid_value_retains_ordinary_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYTE_TOKEN', 'fixture-token')
    binary, calls = native_worker(tmp_path, headers=[{'name': 'retry-after', 'value': 'invalid'}])
    with RustFetcher(binary) as fetcher:
        result, _ = fetcher.fetch_spooled('https://example.gov/file', before_read=lambda: None)
    assert 'retry_later' not in result
    assert len(result['prior_attempts'][0]['response_header_items']) == 3
    assert len(calls.read_text().splitlines()) == 2


def test_retry_after_http_date_uses_capture_time_and_preserves_header(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime, parsedate_to_datetime
    import math
    monkeypatch.setenv('ZYTE_TOKEN', 'fixture-token')
    value = format_datetime(datetime.now(timezone.utc) + timedelta(minutes=4), usegmt=True)
    binary, calls = native_worker(tmp_path, retry_after=value, body=b'busy')
    with RustFetcher(binary) as fetcher:
        result, inspection = fetcher.fetch_spooled('https://example.gov/file', before_read=lambda: None)
    expected = math.ceil((parsedate_to_datetime(value) - datetime.fromisoformat(result['retrieved_at'])).total_seconds())
    assert result['retry_later']['delay_seconds'] == expected
    assert result['response_headers']['retry-after'] == value
    assert inspection == ('retry_later', []) and len(calls.read_text().splitlines()) == 1


def test_generation_body_other_origin_obeys_header_without_govinfo_minimum(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYTE_TOKEN', 'fixture-token')
    binary, _ = native_worker(tmp_path)
    with RustFetcher(binary) as fetcher:
        result = fetcher.fetch('https://example.gov/content/pkg/foo.zip', transport='direct')
    assert result['retry_later'] == {'delay_seconds': 15, 'reason': 'retry_after'}


def test_govinfo_duplicate_retry_after_preserves_fields_and_uses_longest(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYTE_TOKEN', 'fixture-token')
    binary, calls = native_worker(tmp_path, retry_after='30',
        headers=[{'name': 'retry-after', 'value': '15'}])
    url = 'https://www.govinfo.gov/content/pkg/CHRG-119hhrg00001.zip'
    with RustFetcher(binary) as fetcher:
        result, inspection = fetcher.fetch_spooled(url, before_read=lambda: None)
    assert inspection == ('retry_later', [])
    assert result['retry_later'] == {'delay_seconds': 30, 'reason': 'govinfo_zip_generation'}
    assert result['response_headers']['retry-after'] == '15'
    assert [h['value'] for h in result['response_header_items']
            if h['name'].lower() == 'retry-after'] == ['30', '15']
    assert content_bytes(result['content']) == GENERATION_BODY
    assert len(calls.read_text().splitlines()) == 1


@pytest.mark.parametrize('values,delay', [(['60', '15'], 60), (['15', '60'], 60)])
def test_duplicate_generic_retry_after_uses_longest_independent_of_order(tmp_path, monkeypatch, values, delay):
    monkeypatch.setenv('ZYTE_TOKEN', 'fixture-token')
    binary, calls = native_worker(tmp_path, status=429, retry_after=values[0], body=b'busy',
        headers=[{'name': 'retry-after', 'value': values[1]}])
    with RustFetcher(binary) as fetcher:
        result, inspection = fetcher.fetch_spooled('https://example.gov/file', before_read=lambda: None)
    assert inspection == ('retry_later', [])
    assert result['retry_later'] == {'delay_seconds': delay, 'reason': 'retry_after'}
    assert len(calls.read_text().splitlines()) == 1


def test_duplicate_http_date_and_delta_are_parsed_as_separate_raw_fields(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime, parsedate_to_datetime
    import math
    monkeypatch.setenv('ZYTE_TOKEN', 'fixture-token')
    value = format_datetime(datetime.now(timezone.utc) + timedelta(minutes=4), usegmt=True)
    binary, calls = native_worker(tmp_path, retry_after='15', body=b'busy',
        headers=[{'name': 'Retry-After', 'value': value}])
    with RustFetcher(binary) as fetcher:
        result, inspection = fetcher.fetch_spooled('https://example.gov/file', before_read=lambda: None)
    expected = math.ceil((parsedate_to_datetime(value) - datetime.fromisoformat(result['retrieved_at'])).total_seconds())
    assert result['retry_later']['delay_seconds'] == expected
    assert inspection == ('retry_later', [])
    assert [h['value'] for h in result['response_header_items']
            if h['name'].lower() == 'retry-after'] == ['15', value]
    assert len(calls.read_text().splitlines()) == 1
