"""Immutable native capture rows retain observation identity and source values."""
import pyarrow as pa
import pytest

from congress_api.retention.raw_archive import LEGACY_CAPTURE_SCHEMA as CAPTURE_SCHEMA, STATE_SCHEMA
from congress_api.retention.raw_values import capture_table, ordered_captures, state_table


def test_capture_occurrences_keep_failed_duplicate_and_null_empty_values():
    rows = [dict(context_url='https://example.gov/a.pdf', receipt_key='receipts/one.gz',
                 receipt_line=1, body_key='bodies/one.gz', sha256='one', http_status=200,
                 resolution='saved', original_path=None),
            dict(context_url='https://example.gov/a.pdf', receipt_key='receipts/one.gz',
                 receipt_line=2, body_key=None, sha256=None, http_status=429,
                 resolution='retry_later', original_path=''),
            dict(context_url='https://example.gov/a.pdf', receipt_key='receipts/two.gz',
                 receipt_line=1, body_key='bodies/one.gz', sha256='one', http_status=200,
                 resolution='saved', original_path=None)]
    original = pa.Table.from_pylist(rows, schema=CAPTURE_SCHEMA)
    stored = capture_table(original, first_order=37)
    assert stored['_capture_order'].to_pylist() == [37, 38, 39]
    assert ordered_captures(stored.take(pa.array([2, 0, 1]))).equals(original)
    assert stored['body_key'].to_pylist().count('bodies/one.gz') == 2
    assert ordered_captures(capture_table([], first_order=40)).schema == CAPTURE_SCHEMA


def test_invalid_capture_order_and_duplicate_url_state_refuse():
    with pytest.raises(ValueError, match='nonnegative'):
        capture_table([], first_order=-1)
    stored = capture_table([{}], first_order=2)
    with pytest.raises(ValueError, match='capture order'):
        ordered_captures(pa.concat_tables([stored, stored]))
    with pytest.raises(ValueError, match='Duplicate URLs'):
        state_table([dict(url='https://example.gov/a'), dict(url='https://example.gov/a')])
    original = pa.Table.from_pylist([dict(url='https://example.gov/a', attempts=0,
                                        links_scanned=False, outcome='pending', next_attempt_at=None)],
                                   schema=STATE_SCHEMA)
    assert state_table(original).equals(original)
