"""Real receipt lines pin the fb408404 envelope semantics.

Expected tuples come from each line's raw facts, not from a mapper run. The fixture
holds trimmed real lines, with the source key and line number beside each.

The list-valued provider case has one real line (documents/2026-09-29:121811, 849
items), so test_captures_final34's synthetic test keeps covering it.

This gate sees only these lines. Envelope shapes have no fixed count, and the wrong
v21 rows were found by a whole-corpus differential, not by a fixture.
"""
import gzip
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from capture_qualification_helpers import write_qualified_bytes
from congress_api.lake.captures import stage_captures
from docspec_client.client import NativeDatasets

FIXTURE = Path(__file__).parent / 'fixtures/fb408404_receipt_lines.jsonl'
DOCUMENTS = 'receipts/documents/2026-09-29/assemble-20260930.jsonl.gz'
ATTEMPT_1_COMPLETE = 'asserted separately'
# (attempt, http_status, outcome, complete, fetch_http_status, fetch_outcome)
EXPECTED = {
    # record 410; [provider_response,raw_path] 200 is Zyte API's own status, [raw_path] 410.
    'receipts/external/provider-responses/2026-09-29/assemble-20260930.jsonl.gz':
        [(0, 410, 'failed', True, 410, 'failed')] * 2,
    # No record address; [results,0,raw,path] 200, [results,1,raw,path] 429.
    'receipts/external/wayback/2026-09-29/assemble-20260930.jsonl.gz':
        [(0, 200, 'stored', True, 200, 'stored'), (0, 429, 'retry_later', True, 429, 'retry_later')],
    # One retained file, no URL or status.
    'receipts/external/provider-responses/undated/assemble-20260930-completion.jsonl.gz':
        [(None, None, 'stored', None, None, 'stored')],
    # record outcome=http_error, 202; prior attempt 202 with no outcome.
    'receipts/external/provider-responses/2026-10-11/download-20261011T134611Z-e84fedd3f9c2-000012.jsonl.gz':
        [(0, 202, 'failed', True, 202, 'failed')] * 2 + [(1, 202, 'failed', True, 202, 'failed')],
    # [previous_receipt,raw_path] 200, [provider_response,raw_path] 520. Attempt 1's `complete`
    # is asserted on its own below; attempt 0's is the not-truncated final-attempt derivation.
    DOCUMENTS: [(1, 200, 'stored', ATTEMPT_1_COMPLETE, 520, 'failed'), (0, 520, 'failed', True, 520, 'failed')],
}
COLUMNS = ('attempt', 'http_status', 'outcome', 'complete', 'fetch_http_status', 'fetch_outcome')


@pytest.fixture(scope='module')
def rows(tmp_path_factory):
    root = tmp_path_factory.mktemp('fb408404')
    lines = [json.loads(text) for text in FIXTURE.read_text().splitlines()]
    assert {line['key'] for line in lines} == set(EXPECTED)
    files = []
    for index, line in enumerate(lines):
        path = root / f'receipt-{index}.gz'
        data = gzip.compress((json.dumps(line['row'], separators=(',', ':')) + '\n').encode(), mtime=0)
        files.append(dict(key=line['key'], path=str(path), qualification=write_qualified_bytes(path, data)))
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        stage = stage_captures(files, engine=engine, work=root / 'stage')
    return pq.read_table(stage / 'captures.parquet').to_pylist()


def test_real_envelope_lines_map_to_their_raw_facts(rows):
    actual = {key: [] for key in EXPECTED}
    for row in rows:
        values = tuple(row[name] for name in COLUMNS)
        if row['receipt_key'] == DOCUMENTS and row['attempt'] == 1:
            values = values[:3] + (ATTEMPT_1_COMPLETE,) + values[4:]
        actual[row['receipt_key']].append(values)
    assert actual == EXPECTED


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='ct-v8y0: the mapper does not read previous_receipt.body_complete')
def test_previous_receipt_body_complete_reaches_the_attempt(rows):
    [row] = [row for row in rows if row['receipt_key'] == DOCUMENTS and row['attempt'] == 1]
    assert row['complete'] is True
