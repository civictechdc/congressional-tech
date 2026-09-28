"""A reuse hit must skip model assembly and preserve checked bytes and history."""
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from committee_explorer.browser import package, verify
from committee_explorer.export import export
from committee_explorer import reuse
from committee_explorer.state import pack, unpack

NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)


def inputs(tmp_path):
    path = tmp_path / 'meetings.jsonl.gz'
    row = {'eventId': '119550', 'congress': 119, 'chamber': 'House', 'type': 'Hearing',
           'title': 'Retained hearing', 'date': '2026-09-15', 'meetingStatus': 'Scheduled',
           'committees': [{'systemCode': 'hsif00', 'name': 'Energy and Commerce'}]}
    path.write_bytes(gzip.compress(json.dumps(row).encode(), mtime=0))
    return dict(meetings=path, state_dir=tmp_path / 'state', output_dir=tmp_path / 'full',
                reuse_from=tmp_path / 'public', format='parquet', as_of=NOW)


def test_packaged_publication_reuses_on_clean_runner_without_model_assembly(tmp_path, monkeypatch):
    args = inputs(tmp_path)
    first, _ = export(**args)
    browser, _ = package(args['output_dir'], args['reuse_from'])
    assert browser.publication_id != first.publication_id
    before = reuse.state_digests(args['state_dir'], first.publication_id)
    pack(args['state_dir'], tmp_path / 'packed')
    unpack(tmp_path / 'packed', tmp_path / 'restored')

    def forbidden(*args, **kwargs):
        raise AssertionError('unchanged publication must not construct model records')
    monkeypatch.setattr('committee_explorer.export.Assembly', forbidden)
    second, catalog = export(**{**args, 'state_dir': tmp_path / 'restored', 'output_dir': tmp_path / 'fresh',
                               'revision': 'new-pipeline-commit-with-identical-input-bytes'})
    assert catalog is None
    assert second == first
    assert reuse.state_digests(tmp_path / 'restored', first.publication_id) == before
    _, _, verified = verify(tmp_path / 'fresh')
    assert verified == first
    repackaged, _ = package(tmp_path / 'fresh', tmp_path / 'repackaged')
    assert repackaged == browser


def test_changed_native_data_refreshes_records_and_preserves_ids(tmp_path):
    args = inputs(tmp_path)
    first, catalog = export(**args)
    original = next(r for r in catalog.records if r.kind == 'meeting')
    row = json.loads(gzip.decompress(args['meetings'].read_bytes()))
    row['title'] = 'Changed source title'
    args['meetings'].write_bytes(gzip.compress(json.dumps(row).encode(), mtime=0))
    second, catalog = export(**args)
    updated = next(r for r in catalog.records if r.kind == 'meeting')
    assert updated.id == original.id
    assert updated.title == row['title']
    assert first.publication_id != second.publication_id


@pytest.mark.parametrize('change', ['limit', 'as_of', 'format', 'decisions', 'attempts', 'youtube_added', 'youtube_removed', 'transcript_name', 'code'])
def test_changed_request_invalidates_receipt(tmp_path, monkeypatch, change):
    path = tmp_path / 'source.json'
    path.write_text('{}')
    youtube = tmp_path / 'youtube'
    youtube.mkdir()
    video = youtube / 'youtube_one.json'
    video.write_text('{}')
    transcript = tmp_path / 'transcript.json'
    transcript.write_text('{}')
    options = dict(files={'meetings': path, 'issue_decisions': None, 'attempts': None}, youtube_dir=youtube,
                   transcript_files=[transcript], limit=None, format='parquet', as_of=NOW)
    first = reuse.request_key(**options)
    if change == 'limit': options['limit'] = 1
    elif change == 'as_of': options['as_of'] = NOW.replace(day=29)
    elif change == 'format': options['format'] = 'json'
    elif change == 'decisions': options['files']['issue_decisions'] = path
    elif change == 'attempts': options['files']['attempts'] = path
    elif change == 'youtube_added': (youtube / 'youtube_two.json').write_text('{}')
    elif change == 'youtube_removed': video.unlink()
    elif change == 'transcript_name':
        renamed = tmp_path / 'renamed.json'
        transcript.rename(renamed)
        options['transcript_files'] = [renamed]
    else: monkeypatch.setattr(reuse, 'implementation_digest', lambda: 'updated-implementation')
    assert reuse.request_key(**options) != first


def test_implementation_digest_tracks_source_schema_lookup_and_dependency_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(reuse, 'import_module', lambda name: SimpleNamespace(__file__=str(tmp_path / '__init__.py')))
    monkeypatch.setattr(reuse.metadata, 'version', lambda name: '1')
    code = tmp_path / 'schema.py'
    code.write_text('VERSION = 1')
    lookup = tmp_path / 'committees.csv'
    lookup.write_text('one')
    first = reuse.implementation_digest()
    code.write_text('VERSION = 2')
    second = reuse.implementation_digest()
    lookup.write_text('two')
    third = reuse.implementation_digest()
    monkeypatch.setattr(reuse.metadata, 'version', lambda name: '2')
    assert len({first, second, third, reuse.implementation_digest()}) == 4


@pytest.mark.parametrize('field', ['ids.json', 'history'])
def test_modified_state_cannot_reuse(tmp_path, field):
    args = inputs(tmp_path)
    manifest, _ = export(**args)
    receipt = json.loads((args['state_dir'] / 'reuse.json').read_text())
    target = args['state_dir'] / (f'issue-history/{manifest.publication_id}.sqlite' if field == 'history' else field)
    target.write_bytes(target.read_bytes() + b'changed')
    assert reuse.try_reuse(args['output_dir'], args['state_dir'], args['reuse_from'], receipt['request_key']) is None


def test_corrupt_retained_publication_never_replaces_current_pointer(tmp_path):
    args = inputs(tmp_path)
    manifest, _ = export(**args)
    pointer = (args['output_dir'] / 'CURRENT.json').read_bytes()
    release = args['output_dir'] / 'releases' / manifest.publication_id
    (release / manifest.partitions[0].path).write_text('corrupt')
    with pytest.raises(ValueError, match='Partition differs'):
        export(**args)
    assert (args['output_dir'] / 'CURRENT.json').read_bytes() == pointer


def test_missing_receipt_rebuilds_and_json_reuse_is_rejected(tmp_path):
    args = inputs(tmp_path)
    assert export(**args)[1] is not None
    with pytest.raises(ValueError, match='requires parquet'):
        export(**{**args, 'format': 'json'})
