"""Rejected listing evidence cannot overwrite a valid source snapshot."""
from datetime import datetime
import json
from pathlib import Path

import pytest

from congress_api.retention.rejected_pages import retain_rejected_page


def test_rejected_pages_append_raw_values_without_touching_snapshot(tmp_path):
    output = tmp_path / 'nested/meetings.jsonl.gz'
    output.parent.mkdir()
    output.write_bytes(b'previous valid snapshot')
    first = {'committees': None, 'unrecognized': ['José', '', {}, []]}
    path = retain_rejected_page(output, first, url='https://api.congress.gov/v3/committee', offset=0)
    assert path == output.with_suffix('.gz.rejected.json')
    retain_rejected_page(output, {'new': True}, url='https://api.congress.gov/v3/committee', offset=250)
    rows = json.loads(path.read_text())
    assert [row['response'] for row in rows] == [first, {'new': True}]
    assert [row['offset'] for row in rows] == [0, 250]
    assert all(datetime.fromisoformat(row['retrieved_at']).utcoffset().total_seconds() == 0 for row in rows)
    assert output.read_bytes() == b'previous valid snapshot'
    assert not path.with_suffix(path.suffix + '.tmp').exists()


def test_failed_atomic_replace_keeps_prior_evidence(tmp_path, monkeypatch):
    path = retain_rejected_page(tmp_path / 'committees.gz', {'before': 1}, url='https://example.gov', offset=0)
    before = path.read_bytes()
    def fail(*args, **kwargs):
        raise OSError('replace failed')
    monkeypatch.setattr(Path, 'replace', fail)
    with pytest.raises(OSError, match='replace failed'):
        retain_rejected_page(tmp_path / 'committees.gz', {'after': 2}, url='https://example.gov', offset=1)
    assert path.read_bytes() == before


def test_original_retention_import_is_same_function():
    from congress_api.fetch.rejected import retain_rejected_page as old
    assert old is retain_rejected_page
