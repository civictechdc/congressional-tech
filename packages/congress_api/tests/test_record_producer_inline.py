"""Inline meeting refs are corpus-sized: they leave the metadata channel, and only the current line is work."""
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path

import pyarrow.parquet as pq

from capture_qualification_helpers import write_qualified_bytes
from congress_api.lake import captures, meeting_records
from docspec_client.client import NativeDatasets

STAMP = '2026-10-28T12:00:00Z'
KEY = 'receipts/congress/meetings/2026-10-28/assemble-inline.jsonl.gz'
LATER = 'receipts/congress/meetings/2026-10-29/assemble-inline.jsonl.gz'


def url(event):
    return f'https://api.congress.gov/v3/committee-meeting/118/house/{event}?format=json&padding=' + 'x' * 500


def line(event, update, witnesses=1, run='inline'):
    return json.dumps(dict(writer=dict(job='fixture', commit='a' * 40), run_id=run, family='congress/meetings',
        requested_url=url(event), url=url(event), retrieved_at=STAMP,
        record=dict(eventId=str(event), congress=118, chamber='House', title=f'Meeting {event}', updateDate=update,
            date='2024-08-01T14:00:00Z', committees=[dict(systemCode='hsag00', name='Agriculture', chamber='House')],
            witnesses=[dict(name=f'Witness {i}', organization='Lab') for i in range(witnesses)])), separators=(',', ':'))


def tight_engine(tmp_path, metadata_bytes):
    """The usual runtime with a metadata allowance smaller than the refs."""
    config = json.loads(Path(os.environ['DOCSPEC_JOB_CONFIG']).read_text())
    base = Path(os.environ['DOCSPEC_JOB_CONFIG']).parent
    limits = json.loads((base / config['limits']).resolve().read_text())
    limits['max_metadata_bytes'] = metadata_bytes
    path = tmp_path / 'limits.json'
    path.write_text(json.dumps(limits))
    config.update(binary=str((base / config['binary']).resolve()), limits=str(path), workspace=str(tmp_path / 'ws'))
    runtime = tmp_path / 'runtime.json'
    runtime.write_text(json.dumps(config))
    return NativeDatasets.from_config(runtime)


def stage_receipts(tmp_path, receipts, engine, name, existing=None, record_engine=None):
    raw = tmp_path / 'raw'
    files = []
    for key, lines in receipts.items():
        path = raw / key
        path.parent.mkdir(parents=True, exist_ok=True)
        qualification = write_qualified_bytes(path, gzip.compress((''.join(text + '\n' for text in lines)).encode(), mtime=0))
        files.append(dict(key=key, path=str(path), qualification=qualification))
    stage = captures.stage_captures(files, engine=engine, work=tmp_path / f'captures-{name}') / 'captures.parquet'
    return meeting_records.stage(captures=stage, engine=record_engine or engine, work=tmp_path / f'meetings-{name}', local_root=raw,
        existing=existing, decided_at=STAMP)


def shas(staged):
    return {row['record_sha'].hex() for row in pq.read_table(staged['records']).to_pylist()}


def digest(text):
    return sha256(text.encode()).hexdigest()


def test_refs_larger_than_the_metadata_allowance_still_stage(tmp_path):
    lines = [line(event, '2024-01-01') for event in range(400)]
    # The refs alone, about 500 bytes each as JSON, exceed the allowance.
    assert 400 * len(url(0)) > 128 << 10
    # Only the record stage is tight, because that is where the refs used to travel.
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    staged = stage_receipts(tmp_path, {KEY: lines}, engine, 'tight', record_engine=tight_engine(tmp_path, 128 << 10))
    assert staged['produced'] == 400


def test_only_the_current_line_per_url_is_work(tmp_path):
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    old = line(1, '2024-01-01', witnesses=3)
    newest = line(1, '2024-03-01', witnesses=1)
    # A later fetch of an older revision does not supersede a newer one.
    stale_refetch = line(1, '2024-02-01', witnesses=5, run='refetch')
    fewer = line(2, '2024-01-01', witnesses=1)
    more = line(2, '2024-01-01', witnesses=2)
    staged = stage_receipts(tmp_path, {KEY: [old, newest, fewer, more, stale_refetch]}, engine, 'rule')
    assert shas(staged) == {digest(newest), digest(more)}


def test_superseded_lines_stay_settled_and_a_new_revision_is_the_only_work(tmp_path):
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    old, newest = line(1, '2024-01-01'), line(1, '2024-03-01')
    first = stage_receipts(tmp_path, {KEY: [old, newest]}, engine, 'first')
    assert first['produced'] == 1
    again = stage_receipts(tmp_path, {KEY: [old, newest]}, engine, 'again', existing=first['records'])
    assert again['work_items'] == 0
    revised = line(1, '2024-04-01')
    later = stage_receipts(tmp_path, {KEY: [old, newest], LATER: [revised]}, engine, 'later', existing=first['records'])
    assert shas(later) == {digest(revised)}
