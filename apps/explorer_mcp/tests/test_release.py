from contextlib import contextmanager
import fcntl
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3

import pyarrow.parquet as pq
import pytest

from congressional_explorer_mcp import release
from congressional_explorer_mcp.models import ExplorerError
from congressional_explorer_mcp.reader import Reader
from conftest import CURRENT, manifest, replace_rows


def test_opaque_index_download_streams_hashes_and_cleans_failed_transfer(tmp_path, monkeypatch):
    """A SQLite asset uses the same bounded transfer as large release tables."""
    source = tmp_path / 'search_index.sqlite'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE retained_text(content BLOB)')
        db.execute('INSERT INTO retained_text VALUES (zeroblob(2500000))')
    digest = sha256(source.read_bytes()).hexdigest()
    item = dict(name=source.name, sha256=digest, size=source.stat().st_size, rows=1)
    objects = tmp_path / 'objects'; objects.mkdir()
    reads = []
    @contextmanager
    def bounded(location):
        with Path(location).open('rb') as stream:
            class CheckedStream:
                def read(self, size):
                    assert 0 < size <= 1 << 20
                    reads.append(size)
                    return stream.read(size)
            yield CheckedStream()
    monkeypatch.setattr(release, 'opened', bounded)
    result = release.retain(source, item, objects, None)
    assert result.stat().st_size == item['size'] and len(reads) >= 4
    assert sha256(result.read_bytes()).hexdigest() == digest
    with pytest.raises(ExplorerError, match='checksum'):
        release.retain(source, dict(item, sha256='f' * 64), objects, None)
    assert not list(objects.glob('*.partial'))


def test_same_release_reuses_verified_files_without_payload_or_footer_reads(tmp_path, monkeypatch):
    first = release.prepare(tmp_path, CURRENT/'manifest.json')
    opened = release.opened
    calls = []
    @contextmanager
    def record(location):
        calls.append(str(location))
        with opened(location) as stream:
            yield stream
    monkeypatch.setattr(release, 'opened', record)
    import duckdb
    monkeypatch.setattr(duckdb, 'connect', lambda **kwargs: pytest.fail('Unchanged release reread Parquet footers'))
    assert release.prepare(tmp_path, CURRENT/'manifest.json') == first
    assert calls == [str(CURRENT/'manifest.json')]
    assert sum(p.stat().st_size for p in (tmp_path/'objects').iterdir()) == sum(f['size'] for f in first['manifest']['files'])


def test_pointer_and_direct_manifest_choose_identical_release(tmp_path):
    public = tmp_path/'public'; identity = json.loads((CURRENT/'manifest.json').read_bytes())['release_id']
    target = public/'releases'/identity
    shutil.copytree(CURRENT, target)
    (public/'manifest.json').write_bytes(release.encoded({'release_id':identity}))
    selected = release.prepare(tmp_path/'cache', public/'manifest.json')
    assert selected['release_id'] == identity
    assert selected['tables']['list'][0]['rows'] == 7


def test_interrupted_prepare_keeps_previous_selection_and_reuses_completed_files(tmp_path, phase2, monkeypatch):
    cache = tmp_path/'cache'
    before = release.prepare(cache, CURRENT/'manifest.json')
    opened = release.opened
    @contextmanager
    def interrupt(location):
        if Path(location) == phase2.parent/'witnesses.parquet':
            raise OSError('simulated interrupted transfer')
        with opened(location) as stream:
            yield stream
    monkeypatch.setattr(release, 'opened', interrupt)
    with pytest.raises(OSError, match='interrupted'):
        release.prepare(cache, phase2)
    assert release.load_selection(cache)['release_id'] == before['release_id']
    assert not list((cache/'objects').glob('*.partial'))
    transferred = []
    @contextmanager
    def record(location):
        if Path(location).parent == phase2.parent and str(location).endswith('.parquet'):
            transferred.append(Path(location).name)
        with opened(location) as stream:
            yield stream
    monkeypatch.setattr(release, 'opened', record)
    after = release.prepare(cache, phase2)
    assert after['release_id'] != before['release_id']
    assert transferred == ['witnesses.parquet']


def test_bad_checksum_never_selects_candidate(tmp_path, phase2):
    cache = tmp_path/'cache'; before = release.prepare(cache, CURRENT/'manifest.json')
    broken = tmp_path/'broken'; shutil.copytree(phase2.parent, broken)
    with (broken/'bills.parquet').open('ab') as stream:
        stream.write(b'wrong')
    with pytest.raises(ExplorerError, match='size'):
        release.prepare(cache, broken/'manifest.json')
    assert release.load_selection(cache)['release_id'] == before['release_id']
    assert not list((cache/'objects').glob('*.partial'))


def test_changed_cache_and_concurrent_prepare_are_rejected(tmp_path):
    selected = release.prepare(tmp_path, CURRENT/'manifest.json')
    with (tmp_path/'prepare.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ExplorerError,match='Another prepare'):
            release.prepare(tmp_path, CURRENT/'manifest.json')
    path = Path(next(iter(selected['files'].values()))['path'])
    path.chmod(0o644)
    with pytest.raises(ExplorerError,match='changed'):
        release.load_selection(tmp_path)
    with pytest.raises(ExplorerError,match='changed'):
        release.prepare(tmp_path, CURRENT/'manifest.json')


def test_legacy_five_field_stamp_survives_st_dev_change_and_missing_object_heals(tmp_path, monkeypatch):
    selected = release.prepare(tmp_path, CURRENT/'manifest.json')
    assert all(len(item['stamp']) == 4 for item in selected['files'].values())
    selection_path = tmp_path / 'selection.json'
    legacy = json.loads(selection_path.read_bytes())
    for item in legacy['files'].values():
        item['stamp'] = [999999, *item['stamp']]
    selection_path.write_bytes(release.encoded(legacy))
    loaded = release.load_selection(tmp_path)
    assert loaded['release_id'] == selected['release_id']
    import duckdb
    monkeypatch.setattr(duckdb, 'connect', lambda **kwargs: pytest.fail('Stamp upgrade reread Parquet footers'))
    upgraded = release.prepare(tmp_path, CURRENT/'manifest.json')
    assert all(len(item['stamp']) == 4 for item in upgraded['files'].values())
    assert all(len(item['stamp']) == 4 for item in json.loads(selection_path.read_bytes())['files'].values())
    monkeypatch.undo()
    missing_sha, missing_item = next(iter(upgraded['files'].items()))
    Path(missing_item['path']).unlink()
    with pytest.raises(ExplorerError, match='changed'):
        release.load_selection(tmp_path)
    healed = release.prepare(tmp_path, CURRENT/'manifest.json')
    assert Path(healed['files'][missing_sha]['path']).exists()
    assert release.load_selection(tmp_path)['release_id'] == selected['release_id']


def test_shards_preserve_positions_duplicates_and_source_order(tmp_path):
    source=tmp_path/'release'; shutil.copytree(CURRENT,source)
    def sources(rows):
        rows.insert(1, dict(rows[0], ordinal=1))
    replace_rows(source,'sources',sources)
    def detail(rows):
        rows[0]['src_len'] += 1
        for row in rows[1:]:
            row['src_start'] += 1
    replace_rows(source,'detail',detail)
    declarations={}
    for name in ['detail','sources']:
        table=pq.read_table(source/f'{name}.parquet')
        for i,(start,end) in enumerate([(0,3),(3,table.num_rows)]):
            filename=f'{name}-{i:05}.parquet'
            pq.write_table(table.slice(start,end-start),source/filename)
            declarations[filename]=dict(shard=name,row_range=[start,end])
        (source/f'{name}.parquet').unlink()
    path=manifest(source,declarations)
    value=json.loads(path.read_bytes()); value['files'].reverse()
    value['release_id']=sha256(release.encoded([1,[[f[k] for k in ('name','sha256','size','rows')] for f in value['files']]])).hexdigest()
    path.write_bytes(release.encoded(value))
    reader=Reader(release.prepare(tmp_path/'cache',path))
    try:
        docs=reader.query_sql({'sql':'SELECT list_row,filename,hex(link_key) AS link_key FROM documents ORDER BY list_row'})['rows']
        assert [d['list_row'] for d in docs] == list(range(7))
        assert docs[6]['filename'] == 'Substitute.pdf'
        ref=dict(release_id=reader.release_id,link_key=docs[0]['link_key'],section='sources',limit=1)
        page=reader.get_document(ref)
        second=reader.get_document(dict(**ref,cursor=page['next_cursor']))
        assert page['rows'][0]['url'] == second['rows'][0]['url']
        assert [page['rows'][0]['ordinal'],second['rows'][0]['ordinal']] == [0,1]
        assert not second['has_more']
    finally:
        reader.close()


def test_bad_footer_count_and_legacy_shape_fail_before_selection(tmp_path):
    source=tmp_path/'bad'; shutil.copytree(CURRENT,source)
    path=source/'manifest.json'; value=json.loads(path.read_bytes())
    next(f for f in value['files'] if f['name']=='sources.parquet')['rows'] += 1
    value['release_id']=sha256(release.encoded([1,[[f[k] for k in ('name','sha256','size','rows')] for f in value['files']]])).hexdigest()
    path.write_bytes(release.encoded(value))
    with pytest.raises(ExplorerError,match='row count'):
        release.prepare(tmp_path/'cache',path)
    assert not (tmp_path/'cache/selection.json').exists()
    path.write_text('{"schema_version":6,"files":[]}')
    with pytest.raises(ExplorerError,match='legacy'):
        release.prepare(tmp_path/'cache',path)


def test_remote_prepare_downloads_concurrently_and_cleans_up_on_error(tmp_path, phase2, monkeypatch):
    import threading
    from urllib.parse import urlsplit

    identity = json.loads((CURRENT / 'manifest.json').read_bytes())['release_id']
    base = f'https://archive.example/viewer-publications/releases/{identity}/'
    manifest_url = base + 'manifest.json'
    active, peak = 0, 0
    lock = threading.Lock()
    two_in_flight = threading.Event()
    local_open = release.opened

    @contextmanager
    def concurrent_remote(location):
        nonlocal active, peak
        loc = str(location)
        if not loc.startswith(('http://', 'https://')):
            with local_open(loc) as stream:
                yield stream
            return
        if loc.endswith('/viewer-publications/manifest.json'):
            raise OSError('pointer unavailable')
        assert loc.startswith(base)
        name = urlsplit(loc).path.rsplit('/', 1)[-1]
        if name != 'manifest.json':
            with lock:
                active += 1
                peak = max(peak, active)
                if active >= 2:
                    two_in_flight.set()
            two_in_flight.wait(timeout=2.0)
        try:
            with local_open(CURRENT / name) as stream:
                yield stream
        finally:
            if name != 'manifest.json':
                with lock:
                    active -= 1

    monkeypatch.setattr(release, 'opened', concurrent_remote)
    cache = tmp_path / 'cache'
    selected = release.prepare(cache, manifest_url)
    assert selected['release_id'] == identity
    assert selected['archive_origin'] == 'https://archive.example'
    assert peak >= 2
    assert not list((cache / 'objects').glob('*.partial'))

    # A failure mid-parallel download preserves the prior selection and leaves no partial files.
    next_id = json.loads(phase2.read_bytes())['release_id']
    next_base = f'https://archive.example/viewer-publications/releases/{next_id}/'

    @contextmanager
    def failing_remote(location):
        loc = str(location)
        if not loc.startswith(('http://', 'https://')):
            with local_open(loc) as stream:
                yield stream
            return
        if loc.endswith('/viewer-publications/manifest.json'):
            raise OSError('pointer unavailable')
        name = urlsplit(loc).path.rsplit('/', 1)[-1]
        if name == 'witnesses.parquet':
            raise OSError('simulated remote error')
        with local_open(phase2.parent / name) as stream:
            yield stream

    monkeypatch.setattr(release, 'opened', failing_remote)
    with pytest.raises(OSError, match='simulated remote error'):
        release.prepare(cache, next_base + 'manifest.json')
    assert release.load_selection(cache)['release_id'] == identity
    assert not list((cache / 'objects').glob('*.partial'))


def test_concurrent_remote_prepare_cleans_partials_and_reuses_completed_downloads(tmp_path, monkeypatch):
    cache = tmp_path / 'cache'
    source_manifest = (CURRENT / 'manifest.json').as_uri().replace('file://', 'https://archive.example')
    opened = release.opened
    attempts = []

    @contextmanager
    def flaky_remote(location):
        text = str(location)
        if not text.startswith(('http://', 'https://')):
            with opened(text) as stream:
                yield stream
            return
        if text == source_manifest:
            local = CURRENT / 'manifest.json'
        else:
            name = text.rsplit('/', 1)[-1]
            attempts.append(name)
            if name == 'url_state.parquet' and attempts.count(name) == 1:
                raise OSError('simulated concurrent transfer failure')
            local = CURRENT / name
        with opened(local) as stream:
            yield stream

    monkeypatch.setattr(release, 'opened', flaky_remote)
    with pytest.raises(OSError, match='concurrent transfer failure'):
        release.prepare(cache, source_manifest)
    assert not list((cache / 'objects').glob('*.partial'))
    assert not (cache / 'selection.json').exists()

    seen_second_pass = []
    @contextmanager
    def retry_remote(location):
        text = str(location)
        if text.startswith(('http://', 'https://')) and text != source_manifest:
            seen_second_pass.append(text.rsplit('/', 1)[-1])
        with flaky_remote(location) as stream:
            yield stream

    monkeypatch.setattr(release, 'opened', retry_remote)
    selected = release.prepare(cache, source_manifest)
    assert selected['release_id'] == json.loads((CURRENT / 'manifest.json').read_bytes())['release_id']
    assert 'url_state.parquet' in seen_second_pass
    assert len(seen_second_pass) < len(selected['manifest']['files'])
