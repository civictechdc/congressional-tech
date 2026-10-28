"""Owner-decided D1 bulk columns; other evidence stays behind the raw pointer."""
import json

import pyarrow.parquet as pq
import pytest

from test_captures_ingest import body, ingest, STAMP


NARROW_COLUMNS = [
    'receipt_key', 'receipt_line', 'capture_index', 'run_id', 'mode', 'outcome',
    'family', 'requested_url', 'url', 'context_url', 'member_path', 'h_content_disposition', 'http_status',
    'complete', 'retrieved_at', 'sha256', 'bytes', 'media_type', 'fidelity',
    'stored_suffix', 'stored_bytes', 'stored_md5', 'recovery_category',
    'original_url', 'recovered_url', 'match_basis', 'evidence_sha256', 'imported_at',
]


def test_public_index_has_only_the_28_bulk_columns(tmp_path):
    stage = ingest(tmp_path, [dict(record=dict(url='https://example.test/a'),
                                    captures=[body()])])
    assert pq.read_schema(stage/'captures.parquet').names == NARROW_COLUMNS


@pytest.mark.parametrize('complete', [True, False])
def test_final_line_completeness_is_repeated_without_prior_or_member_borrowing(tmp_path, complete):
    source = dict(http_status=200, complete=complete, retrieved_at=STAMP,
        prior_attempts=[dict(http_status=206, complete=not complete)],
        record=dict(complete=not complete), captures=[
            body(attempt=1, complete=not complete, pointer=['prior_attempts', 0, 'body']),
            body(attempt=0, complete=complete, pointer=['content', 'body']),
            body(complete=not complete, member_path='inside.pdf',
                 pointer=['archive_members', 0, 'body'])])
    stage = ingest(tmp_path, [source])
    rows = pq.read_table(stage/'captures.parquet').to_pylist()
    assert [row['complete'] for row in rows] == [complete]*3
    assert [row['http_status'] for row in rows] == [200]*3
    assert [row['capture_index'] for row in rows] == [0, 1, 2]


def test_prior_header_writer_and_inline_payload_are_not_bulk_evidence(tmp_path):
    marker = 'on-demand-evidence-only-'
    source = dict(mode='fetch', outcome='retry_later', http_status=200,
        complete=True, retrieved_at=STAMP,
        response_header_items=[dict(name='Retry-After', value='120'),
                               dict(name='Content-Disposition', value=marker*2000)],
        prior_attempts=[dict(complete=False, http_status=206, body=marker*2000)],
        writer=dict(job=marker*2000, commit=marker),
        record=dict(meeting=dict(description=marker*2000)),
        captures=[body(attempt=0, complete=True) for _ in range(32)])
    stage = ingest(tmp_path, [source], key='receipts/congress/meetings/2026-10-20/run.jsonl.gz')
    rows = pq.read_table(stage/'captures.parquet').to_pylist()
    assert len(rows) == 32 and {row['outcome'] for row in rows} == {'retry_later'}
    assert marker not in str(pq.read_table(stage/'capture-evidence.parquet').to_pylist())
    job = json.loads((stage/'job.json').read_text())
    sql = '\n'.join(step['sql'] for step in job['steps'])
    for excluded in ('prior_attempts', 'response_header_items',
                     '_ingest_writer', 'record_sha'):
        assert excluded not in sql


def test_older_line_without_final_completeness_keeps_null(tmp_path):
    stage = ingest(tmp_path, [dict(record=dict(http_status=200,
        prior_attempts=[dict(complete=False)]), captures=[body(complete=True)])])
    assert pq.read_table(stage/'captures.parquet')['complete'].to_pylist() == [None]


def test_headers_do_not_override_final_status_outcome(tmp_path):
    stage = ingest(tmp_path, [dict(http_status=200, complete=True,
        response_headers={'retry-after': '120'}, captures=[body()])])
    assert pq.read_table(stage/'captures.parquet')['outcome'].to_pylist() == ['stored']


def test_duplicate_captures_keep_ordinals_and_secondary_storage(tmp_path):
    stage = ingest(tmp_path, [dict(record=dict(http_status=200, complete=True),
        captures=[body(), body()], file_references=[body(stored_bytes=19,
            stored_md5='b'*32, stored_suffix='')])])
    rows = pq.read_table(stage/'captures.parquet').to_pylist()
    assert [row['capture_index'] for row in rows] == [0, 1]
    assert [row['stored_bytes'] for row in rows] == [19, 19]
    assert [row['stored_md5'] for row in rows] == [bytes.fromhex('b'*32)]*2
    assert [row['stored_suffix'] for row in rows] == ['', '']


def test_import_label_without_recovery_evidence_remains_fetch(tmp_path):
    stage = ingest(tmp_path, [dict(mode='import', record=dict(url='https://example.test/a'),
                                   captures=[body()])])
    [row] = pq.read_table(stage/'captures.parquet').to_pylist()
    assert row['mode'] == 'fetch'
    assert all(row[name] is None for name in ('original_url', 'recovered_url',
                                              'match_basis', 'imported_at'))


def test_all_older_entry_time_aliases_precede_line_and_record_time(tmp_path):
    aliases = ('retrieved_at', 'captured_at', 'observed_at',
               'parent_retrieved_at', '_retrieved_at', 'capture_date')
    rows = [dict(retrieved_at='2026-10-22T00:00:00Z',
                 record=dict(retrieved_at='2026-10-21T00:00:00Z'),
                 captures=[body(**{name: '2026-10-20' if name == 'capture_date' else STAMP})])
            for name in aliases]
    stage = ingest(tmp_path, rows)
    actual = pq.read_table(stage/'captures.parquet')['retrieved_at'].to_pylist()
    assert [value.isoformat() for value in actual] == [
        '2026-10-20T12:34:56+00:00']*5 + ['2026-10-20T00:00:00+00:00']


def test_bodiless_list_ignores_differences_in_on_demand_evidence(tmp_path):
    stage = ingest(tmp_path, [dict(record=[
        dict(url='https://example.test/a', complete=True,
             prior_attempts=dict(complete=False), response_headers={'X-Padding': 'first'}),
        dict(url='https://example.test/a', complete=True,
             prior_attempts=[dict(complete=False)], response_headers={'X-Padding': 'second'}),
    ])])
    [row] = pq.read_table(stage/'captures.parquet').to_pylist()
    assert row['complete'] is True and row['url'] == 'https://example.test/a'


@pytest.mark.parametrize('name', ['content-disposition', 'Content-Disposition'])
def test_owner_approved_flat_record_download_header_paths(tmp_path, name):
    value = 'attachment; filename="retained.pdf"'
    stage = ingest(tmp_path, [dict(record=dict(response_headers={name: value}),
                                    captures=[body()])])
    assert pq.read_table(stage/'captures.parquet')['h_content_disposition'].to_pylist() == [value]


def test_download_header_lowercase_precedes_uppercase_and_other_shapes_stay_raw(tmp_path):
    stage = ingest(tmp_path, [
        dict(record=dict(response_headers={'content-disposition': 'lower', 'Content-Disposition': 'upper'})),
        dict(response_headers={'content-disposition': 'root'},
             record=dict(headers={'content-disposition': 'other'},
                         response_header_items=[dict(name='Content-Disposition', value='items')],
                         prior_attempts=[dict(response_headers={'content-disposition': 'prior'})],
                         source_metadata=dict(response_headers={'content-disposition': 'duplicate'}))),
    ])
    assert pq.read_table(stage/'captures.parquet')['h_content_disposition'].to_pylist() == ['lower', None]
