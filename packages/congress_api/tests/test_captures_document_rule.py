"""Real receipt lines pin the one document rule (ct-bxqa, ct-c6b0, ct-3l1c, ct-fh62).

A response is a document only when its status is 2xx other than 202 and its body is
not empty. Legacy assembly lines state that status under `status` on the object that
owns the body. Expected tuples come from each raw line's facts (printed beside each
case), not from a mapper run. List lines 13069 and 13070 are trimmed to their first
items, keeping every item whole and every pointer index unchanged.

Each rule has a row only it catches: an owner 404 with a body (3661, 13070 item 1),
an empty 200 (61862, 3290), a 202 (provider 7; fb408404 keeps the non-empty 202), and
a provider envelope over an empty origin (youtube/captions 3024 items 1 and 3).
"""
import gzip
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from capture_qualification_helpers import write_qualified_bytes
from congress_api.lake import captures
from congress_api.lake.captures import stage_captures
from docspec_client.client import NativeDatasets

FIXTURE = Path(__file__).parent / 'fixtures/document_rule_receipt_lines.jsonl'
PLAYERS = 'receipts/senate/players/2026-09-29/assemble-20260930.jsonl.gz'
COMPLETION = 'receipts/house/witness-xml/undated/assemble-20260930-completion.jsonl.gz'
ROUTING = 'receipts/house/witness-xml/undated/assemble-20260930-routing.jsonl.gz'
F, S, R = 'failed', 'stored', 'retry_later'
# (attempt, http_status, outcome, complete, fetch_http_status, fetch_outcome) per capture index
EXPECTED = {
    # record status 200, 142-byte playlist: the control.
    (PLAYERS, 3660): [(0, 200, S, True, 200, S)],
    # record status 404 with a 248-byte body; then 404 with an empty body.
    (PLAYERS, 3661): [(0, 404, F, True, 404, F)],
    (PLAYERS, 3664): [(0, 404, F, True, 404, F)],
    # master_attempts[0] 404 empty, [1] 404 with 10 bytes: other requests, so no line status.
    (PLAYERS, 78): [(0, 404, F, True, None, F)] * 2,
    # master_attempts[0] 404 empty; [1] and media_playlist_receipt 200 on another URL. One item,
    # three requests: no conflict, and the item has a final document body.
    (PLAYERS, 249): [(0, 404, F, True, None, S), (0, 200, S, True, None, S), (0, 200, S, True, None, S)],
    # List items 0-4: */receipt 200; item 5: */master_attempts 404 empty and 404 with 10 bytes.
    (PLAYERS, 13069): [(0, 200, S, True, None, S)] * 5 + [(0, 404, F, True, None, F)] * 2,
    # Unaddressed items: */receipt 404 empty, */receipt 404 with 248 bytes.
    (PLAYERS, 13070): [(0, 404, F, True, None, F)] * 2,
    # record status 202, empty body (c-span via provider).
    ('receipts/external/provider-responses/2026-09-29/assemble-20260930.jsonl.gz', 7): [(0, 202, F, True, 202, F)],
    # record status 200; a 1,306-byte provider envelope over an empty raw_path origin: neither is a
    # document, so finance111721 gets no m3u8 track from the envelope (ct-fh62).
    ('receipts/external/provider-responses/2026-09-29/assemble-20260930.jsonl.gz', 493): [(0, 200, F, True, 200, F)] * 2,
    # record status 429 with a 117-byte body.
    ('receipts/external/wayback/2026-09-29/assemble-20260930.jsonl.gz', 1): [(0, 429, R, True, 429, R)],
    # http_status 200, body_complete, empty body, no outcome; record status 503 with 14,000 bytes.
    ('receipts/documents/2026-09-29/assemble-20260930.jsonl.gz', 61862): [(0, 200, F, True, 200, F)],
    ('receipts/documents/2026-09-29/assemble-20260930.jsonl.gz', 122898): [(0, 503, R, True, 503, R)],
    # record status 403 with a 402-byte body.
    ('receipts/govinfo/transcript-html/2026-09-29/assemble-20260930.jsonl.gz', 34171): [(0, 403, F, True, 403, F)],
    # status_code 200, outcome empty_response, empty body.
    ('receipts/senate/pages/2026-09-29/assemble-20260930.jsonl.gz', 3290): [(0, 200, F, True, 200, F)],
    # Writer era: provider body, content body and prior attempt, all 200 and empty.
    ('receipts/senate/pages/2026-10-06/download-20261006T070951Z-9aaed522fe48-000003.jsonl.gz', 90):
        [(0, 200, F, True, 200, F)] * 2 + [(1, 200, F, True, 200, F)],
    # Every response/raw_path is 200 and empty; items 1 and 3 also hold 1,026 and 1,003-byte
    # provider envelopes, which are not caption tracks.
    ('receipts/youtube/captions/undated/assemble-20260930.jsonl.gz', 3024): [(0, 200, F, True, 200, F)] * 6,
    # Retained witness list: no status, no completeness, a relative importer path.
    (COMPLETION, 1): [(None, None, S, None, None, S)],
    (ROUTING, 1): [(0, None, S, True, None, S)] * 2,
}
COLUMNS = ('attempt', 'http_status', 'outcome', 'complete', 'fetch_http_status', 'fetch_outcome')


@pytest.fixture(scope='module')
def staged(tmp_path_factory):
    root = tmp_path_factory.mktemp('document-rule')
    groups = {}
    for text in FIXTURE.read_text().splitlines():
        line = json.loads(text)
        groups.setdefault(line['key'], []).append(line)
    assert {(key, line['line']) for key, lines in groups.items() for line in lines} == set(EXPECTED)
    files = []
    for index, (key, lines) in enumerate(groups.items()):
        path = root / f'receipt-{index}.gz'
        data = gzip.compress(''.join(json.dumps(line['row'], separators=(',', ':')) + '\n'
                                     for line in lines).encode(), mtime=0)
        files.append(dict(key=key, path=str(path), qualification=write_qualified_bytes(path, data)))
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        stage = stage_captures(files, engine=engine, work=root / 'stage')
    rows = pq.read_table(stage / 'captures.parquet').to_pylist()
    for row in rows:  # the trimmed file numbers lines from 1; restore the original number
        row['source_line'] = groups[row['receipt_key']][row['receipt_line'] - 1]['line']
    return groups, rows


def test_every_response_is_a_document_only_by_the_one_rule(staged):
    _, rows = staged
    actual = {key: [] for key in EXPECTED}
    for row in sorted(rows, key=lambda r: (r['receipt_key'], r['receipt_line'], r['capture_index'])):
        actual[(row['receipt_key'], row['source_line'])].append(tuple(row[name] for name in COLUMNS))
    assert actual == EXPECTED


def test_every_row_names_the_mapping_that_produced_it(staged):
    _, rows = staged
    assert {row['mapping_version'] for row in rows} == {captures.current_version()}


def test_only_relative_importer_paths_are_carried(staged):
    groups, rows = staged
    raw = {key: [entry.get('original_path') for line in lines for entry in line['row']['file_references']]
           for key, lines in groups.items() if key in (COMPLETION, ROUTING)}
    # The raw facts: one relative path on the completion line, absolute local paths on routing.
    assert raw[COMPLETION] == ['external-sources/hearing-text/docs_house_xml/wlist/108265.xml']
    assert all(path.startswith('/Users/') for path in raw[ROUTING])
    paths = {(row['receipt_key'], row['capture_index']): row['original_path'] for row in rows
             if row['receipt_key'] in (COMPLETION, ROUTING)}
    assert paths == {(COMPLETION, 0): 'external-sources/hearing-text/docs_house_xml/wlist/108265.xml',
                     (ROUTING, 0): None, (ROUTING, 1): None}
    assert all(not (row['original_path'] or '').startswith('/') for row in rows)


def test_a_202_body_is_not_a_document_even_when_the_writer_said_stored(tmp_path):
    """No corpus row isolates this (every non-empty 202 also says http_error), so a writer-shape line does."""
    line = dict(run_id='run', mode='fetch', family='documents', requested_url='https://example.gov/a.pdf',
                url='https://example.gov/a.pdf', retrieved_at='2026-10-27T10:00:00Z', http_status=202,
                outcome='stored', writer=dict(job='capture', commit='a' * 40),
                captures=[dict(pointer=['content', 'body'], attempt=0, complete=True, context_url='https://example.gov/a.pdf',
                               sha256='ab' * 32, bytes=2279, media_type='text/html', fidelity='exact-bytes',
                               stored_suffix='.gz', stored_bytes=900, stored_md5='c' * 32)])
    path = tmp_path / 'receipt.gz'
    data = gzip.compress((json.dumps(line) + '\n').encode(), mtime=0)
    files = [dict(key='receipts/documents/2026-10-27/run-000001.jsonl.gz', path=str(path),
                  qualification=write_qualified_bytes(path, data))]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        stage = stage_captures(files, engine=engine, work=tmp_path / 'stage')
    rows = pq.read_table(stage / 'captures.parquet').to_pylist()
    assert [tuple(row[name] for name in COLUMNS) for row in rows] == [(0, 202, F, True, 202, F)]


def test_an_owner_status_contradicting_the_line_status_refuses(tmp_path):
    """Measured 0 in the corpus; a future contradiction refuses instead of picking one."""
    line = dict(source_file='x', record=dict(url='https://example.gov/a.m3u8', http_status=200, status=404),
                captures=[], file_references=[dict(reference_kind='file', pointer_json='["body_path"]',
                    sha256='ab' * 32, bytes=10, family='senate/players', fidelity='retained-file')])
    path = tmp_path / 'receipt.gz'
    data = gzip.compress((json.dumps(line) + '\n').encode(), mtime=0)
    files = [dict(key='receipts/senate/players/2026-09-29/assemble-20260930.jsonl.gz', path=str(path),
                  qualification=write_qualified_bytes(path, data))]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        with pytest.raises(ValueError, match='conflicting attempt facts'):
            stage_captures(files, engine=engine, work=tmp_path / 'stage')
