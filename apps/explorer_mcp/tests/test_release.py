from contextlib import contextmanager
import fcntl
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pyarrow.parquet as pq
import pytest

from congressional_explorer_mcp import release
from congressional_explorer_mcp.models import ExplorerError
from congressional_explorer_mcp.reader import Reader
from conftest import CURRENT, manifest, replace_rows


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
