"""Unit, staging, and registry tests for wikidata/reconcile captures and readings (ct-39u8)."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re

import pyarrow.parquet as pq

from congress_api.acquisition.capture_scheduler import (
    WIKIDATA_RECONCILE_USER_AGENT,
    default_request_headers,
)
from congress_api.lake import readings
from congress_api.lake.capture_staging import stage_captures
from congress_api.parsers.wikidata_reconcile import reading_row
from docspec_client.client import NativeDatasets

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).parent / 'fixtures/wikidata_reconcile/sample.json'


def test_wikidata_reconcile_reading_row_extracts_queries_and_rejects_invalid():
    parsed = reading_row(FIXTURE.read_bytes())
    assert parsed['status'] == 'completed'
    fields = {item['field']: json.loads(item['value']) for item in parsed['fields']}
    assert list(fields.keys()) == ['query:b001']
    assert fields['query:b001'][0]['id'] == 'Q464135'
    assert fields['query:b001'][0]['score'] == 100.0

    multi = reading_row(json.dumps({
        'b222': {'result': []},
        'b111': {'result': [dict(id='Q49108', name='MIT', description='university', score=98.5, match=True)]},
    }).encode('utf-8'))
    assert multi['status'] == 'completed'
    assert [f['field'] for f in multi['fields']] == ['query:b111', 'query:b222']
    assert json.loads(multi['fields'][1]['value']) == []

    for bad in (
        b'not json',
        b'\xff\xfe',
        b'[]',
        b'{"b1": "not-an-object"}',
        b'{"b1": {"result": "not-a-list"}}',
        b'{"b1": {"result": [123]}}',
        b'{"b1": {"result": [{"id": "Q123", "score": NaN}]}}',
        b'{"b1": {"result": [{"id": "P123", "score": 95.0}]}}',
        b'{"b1": {"result": [{"id": "Q123", "score": true}]}}',
    ):
        refused = reading_row(bad)
        assert refused['status'] == 'error'
        assert refused['error_type'] == 'unsupported_wikidata_reconcile'


def test_wikidata_reconcile_stage_scopes_only_wikidata_reconcile_captures(tmp_path):
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    raw = tmp_path / 'raw'
    wd_bytes = FIXTURE.read_bytes()
    other_json = b'{"bill": {"number": "1", "title": "Other API JSON"}}'

    def put_body(data: bytes):
        sha = hashlib.sha256(data).hexdigest()
        gz = gzip.compress(data, mtime=0)
        dest = raw / f'bodies/sha256/{sha[:2]}/{sha}.gz'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(gz)
        return sha, len(data), len(gz), hashlib.md5(gz).hexdigest()

    wd_sha, wd_len, wd_gz_len, wd_md5 = put_body(wd_bytes)
    other_sha, other_len, other_gz_len, other_md5 = put_body(other_json)

    def make_receipt(family_key: str, url: str, sha: str, size: int, gz_size: int, md5: str):
        rpath = raw / family_key
        rpath.parent.mkdir(parents=True, exist_ok=True)
        line = dict(
            url=url,
            requested_url=url,
            retrieved_at='2026-11-25T00:00:00Z',
            http_status=200,
            complete=True,
            captures=[dict(
                outcome='stored',
                sha256=sha,
                bytes=size,
                media_type='application/json',
                sniffed_format='json',
                sniff_version=readings.current_version('sniff'),
                intact=True,
                stored_suffix='.gz',
                stored_bytes=gz_size,
                stored_md5=md5,
            )],
        )
        encoded = gzip.compress((json.dumps(line) + '\n').encode(), mtime=0)
        rpath.write_bytes(encoded)
        pin = tmp_path / (Path(family_key).name + '.pin.json')
        pin.write_text(json.dumps(dict(
            path=str(rpath),
            size=len(encoded),
            sha256=hashlib.sha256(encoded).hexdigest(),
            producer='test',
        )))
        return dict(key=family_key, path=str(rpath), qualification=str(pin))

    receipts = [
        make_receipt(
            'receipts/wikidata/reconcile/2026-11-25/reconcile.jsonl.gz',
            'https://wikidata-reconciliation.wmcloud.org/en/api?queries=%7B%22b111%22%3A%7B%22limit%22%3A5%2C%22query%22%3A%22mit%22%7D%7D',
            wd_sha,
            wd_len,
            wd_gz_len,
            wd_md5,
        ),
        make_receipt(
            'receipts/congress_gov/api/2026-11-25/api.jsonl.gz',
            'https://api.congress.gov/v3/bill/119/hr/1?format=json',
            other_sha,
            other_len,
            other_gz_len,
            other_md5,
        ),
    ]
    captures = stage_captures(receipts, engine=engine, work=tmp_path / 'captures') / 'captures.parquet'
    staged = readings.stage(
        captures=captures,
        body_inventory=None,
        captured_copies=True,
        local_root=raw,
        engine=engine,
        work=tmp_path / 'stage-wikidata',
        decided_at='2026-11-25T00:00:00Z',
        parser='wikidata_reconcile',
        parser_workers=1,
    )
    rows = pq.read_table(staged['readings']).to_pylist()
    assert len(rows) == 1
    assert rows[0]['body_sha'].hex() == wd_sha
    assert rows[0]['parser'] == 'wikidata_reconcile'
    assert rows[0]['parser_version'] == readings.current_version('wikidata_reconcile')
    assert rows[0]['status'] == 'completed'
    assert [f['field'] for f in rows[0]['fields']] == ['query:b001']


def test_wikidata_reconcile_capture_scope_recheck_and_headers():
    scope = json.loads((ROOT / 'model/registries/capture-scope.json').read_text())['entries']
    wd_entries = [entry for entry in scope if entry['family'] == 'wikidata/reconcile']
    assert len(wd_entries) == 1
    pattern = re.compile(wd_entries[0]['patterns'][0])
    assert pattern.match('https://wikidata-reconciliation.wmcloud.org/en/api?queries=%7B%7D')
    assert not pattern.match('https://wikidata-reconciliation.wmcloud.org/en/api?queries=%7B%7D#frag')
    assert not pattern.match('https://example.org/en/api?queries=%7B%7D')

    intervals = json.loads((ROOT / 'model/registries/recheck-intervals.json').read_text())
    wd_int = [entry for entry in intervals if entry['family'] == 'wikidata/reconcile']
    assert len(wd_int) == 1
    assert wd_int[0]['min_age_days'] is None
    assert wd_int[0]['max_age_days'] is None
    assert wd_int[0]['interval_seconds'] == 3153600000

    assert default_request_headers('https://wikidata-reconciliation.wmcloud.org/en/api?queries=%7B%7D') == {
        'User-Agent': WIKIDATA_RECONCILE_USER_AGENT,
        'Accept': 'application/json',
    }
    assert default_request_headers('https://docs.house.gov/meetings/') == {}
