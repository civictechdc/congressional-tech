"""Next-rebuild HTTP aliases from a retained primary file reference."""
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from test_captures_ingest import ingest


FIXTURE = Path(__file__).resolve().parents[3] / 'model/fixtures/captures-entry-http-status.json'


def retained_sample(entry_field):
    sample = json.loads(FIXTURE.read_text())
    entry = sample['receipt']['file_references'][0]
    entry[entry_field] = entry.pop('http_status')
    return sample


@pytest.mark.parametrize('entry_field', ['http_status', 'status_code'])
def test_primary_entry_status_alias_supplies_absent_final_status(tmp_path, entry_field):
    sample = retained_sample(entry_field)
    stage = ingest(tmp_path, [sample['receipt']], key=sample['source']['receipt_key'])
    [row] = pq.read_table(stage / 'captures.parquet').to_pylist()
    assert row['http_status'] == sample['expected']['http_status']
    assert row['outcome'] == sample['expected']['outcome']
    assert row['sha256'] == bytes.fromhex(sample['expected']['sha256'])
    assert (row['receipt_line'], row['capture_index']) == (1, 0)


@pytest.mark.parametrize('entry_field', ['http_status', 'status_code'])
@pytest.mark.parametrize('final_owner', ['line', 'record'])
@pytest.mark.parametrize('final_field', ['http_status', 'status_code'])
def test_final_404_overrides_primary_entry_200(tmp_path, entry_field, final_owner, final_field):
    sample = retained_sample(entry_field)
    receipt = sample['receipt']
    final = receipt if final_owner == 'line' else receipt['record']
    final[final_field] = 404
    stage = ingest(tmp_path, [receipt], key=sample['source']['receipt_key'])
    [row] = pq.read_table(stage / 'captures.parquet').to_pylist()
    assert row['http_status'] == 404
    assert row['outcome'] == 'failed'
    assert row['sha256'] == bytes.fromhex(sample['expected']['sha256'])
