"""Exercise the shipped reader using explicit inventories of retained release files.

The baseline comes from the accepted native fixture. Deliberate reader variants
write only their changed, bounded tables; they do not qualify a native candidate.
"""
from copy import deepcopy
from hashlib import md5, sha256
import json
import os
from pathlib import Path
import subprocess

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from viewer_publication.archive_format import release_identity

ROOT = Path(__file__).parents[3]


def reader_release(request):
    """Consume a caller-qualified retained inventory without starting a native job.

    With no retained inventory, ordinary producer/consumer tests build their own
    baseline. Rich fixture authoring remains a separate test and never uses this
    override.
    """
    inventory = os.environ.get('ARCHIVE_RETAINED_FIXTURE_FILES')
    if inventory is None:
        return request.getfixturevalue('build_native_fixture')()
    files = {name: Path(path) for name, path in json.loads(Path(inventory).read_text()).items()}
    assert all(path.is_absolute() for path in files.values()), 'Retained inventory requires absolute paths'
    manifest = json.loads(files['manifest.json'].read_text())
    assert files.keys() == {'manifest.json', *(item['name'] for item in manifest['files'])}
    assert manifest['release_id'] == release_identity(manifest['schema_version'], manifest['files'])
    return manifest, files


def test_reader_fixture_inventory_transport():
    """Keep exact membership, nested names and invalid-range checks in the lane."""
    result = subprocess.run(['node', '--test', str(ROOT/'apps/site/scripts/archive-test-fixture.test.mjs')],
        cwd=ROOT/'apps/site', env=os.environ.copy(), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout+result.stderr


def reader_environment(directory, files, **extra):
    """Keep expectation sidecars separate from the exact release inventory."""
    assert all(Path(path).is_absolute() for path in files.values())
    inventory = directory/'reader-files.json'
    inventory.write_text(json.dumps({name: str(path) for name, path in files.items()}))
    return dict(os.environ, ARCHIVE_FIXTURE_FILES=str(inventory), **extra)


def reader_variant(directory, manifest, files, tables, *, remove=()):
    """Retain genuine controls and original native bytes beside test-only changes.

    An outer delivery identity describes these exact bytes. Native catalog
    acceptance still belongs to the original candidate, never to this variant.
    """
    directory.mkdir()
    result = dict(files)
    changed = set(tables) | set(remove)
    catalog = json.loads(Path(files['catalog.ddk.json']).read_text())
    assert not changed.intersection(item['path'] for item in catalog['files']), (
        'A reader variant cannot replace a catalog companion without new genuine metadata')
    descriptors = {item['name']: deepcopy(item) for item in manifest['files']}
    for name in remove:
        result.pop(name)
        descriptors.pop(name)
    for name, (table, shard, row_range) in tables.items():
        path = directory/name
        pq.write_table(table, path)
        data = path.read_bytes()
        descriptors[name] = dict(name=name, size=len(data), sha256=sha256(data).hexdigest(),
            md5=md5(data).hexdigest(), rows=table.num_rows, producer='archive', coverage={},
            shard=shard, row_range=row_range)
        result[name] = path
    variant = dict(deepcopy(manifest), files=list(descriptors.values()))
    variant['release_id'] = release_identity(variant['schema_version'], variant['files'])
    path = directory/'manifest.json'
    path.write_text(json.dumps(variant))
    result['manifest.json'] = path
    (directory/'reader-variant.json').write_text(json.dumps({
        'purpose': 'Bounded reader behavior test; not native candidate qualification',
        'baseline_release_id': manifest['release_id'], 'release_id': variant['release_id'],
        'changed_files': sorted(changed)}))
    assert result.keys() == {'manifest.json', *(item['name'] for item in variant['files'])}
    return variant, result


@pytest.mark.parametrize('missing', ['none', 'document_date_status', 'address_versions'])
def test_current_reader_requires_current_fields_and_preserves_nulls(tmp_path, request, missing):
    manifest, files = reader_release(request)
    detail = pq.read_table(files['detail.parquet'])
    index = detail.schema.get_field_index('document_date_status')
    assert index >= 0, 'The native baseline must include the current date-status field'
    detail = detail.drop(['document_date_status']) if missing == 'document_date_status' else detail.set_column(
        index, detail.schema.field(index), pa.nulls(detail.num_rows, pa.string()))
    retired = pa.table({'link_key': [b'\xaa'*8, b'\xbb'*8], 'successor_key': [None, None],
        'last_release_id': ['d'*64]*2, 'last_filename': ['removed.pdf']*2,
        'address_versions': [None, []]}, schema=pa.schema([
            ('link_key', pa.binary(8)), ('successor_key', pa.binary(8)),
            ('last_release_id', pa.string()), ('last_filename', pa.string()),
            ('address_versions', pa.list_(pa.binary(8)))]))
    if missing == 'address_versions':
        retired = retired.drop(['address_versions'])
    _, variant = reader_variant(tmp_path/'variant', manifest, files, {
        'detail.parquet': (detail, None, None), 'retired_links.parquet': (retired, None, None)})
    script = """
      import assert from 'node:assert/strict';
      import {loadArchiveFixture} from './scripts/archive-test-fixture.mjs';
      import {openArchive} from './src/components/explorer/reader/archive.ts';
      const {fetcher}=await loadArchiveFixture();
      const missing=process.env.ARCHIVE_MISSING_FIELD;
      const reader=await openArchive('https://fixture.test/manifest.json',{fetcher});
      if(missing==='none'){
        assert.equal((await reader.entry(0)).detail.document_date_status,null);
        for(const key of ['aa','bb'])assert.deepEqual((await reader.locate(key.repeat(8))).removed.versions,[]);
      }else{
        const operation=missing==='document_date_status'?reader.entry(0):reader.locate('aa'.repeat(8));
        await assert.rejects(operation,new RegExp('missing '+missing));
      }
    """
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT/'apps/site',
        env=reader_environment(tmp_path, variant, ARCHIVE_MISSING_FIELD=missing),
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout+result.stderr


def test_shared_reader_contract(tmp_path, request):
    _, files = reader_release(request)
    # The producer deliberately separates native outputs from application controls.
    assert Path(files['list.parquet']).parent != Path(files['manifest.json']).parent
    result = subprocess.run(['node', '--test', str(ROOT/'apps/site/scripts/archive-reader.test.mjs')],
        cwd=ROOT/'apps/site', env=reader_environment(tmp_path, files),
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout+result.stderr


def test_rich_entity_reader_contract(tmp_path, build_native_fixture):
    """Run the full entity scenario through authored inputs and the native writer."""
    from archive_entity_fixture import author_entity_inputs

    documents, entity_files = author_entity_inputs(tmp_path/'entity-inputs')
    _, files = build_native_fixture(documents, name='rich-fixture', entity_files=entity_files)
    env = reader_environment(tmp_path, files)
    env['ARCHIVE_ENTITY_FIXTURE_FILES'] = env['ARCHIVE_FIXTURE_FILES']
    result = subprocess.run(['node', '--test', str(ROOT/'apps/site/scripts/archive-entities.test.mjs')],
        cwd=ROOT/'apps/site', env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout+result.stderr


def test_reader_shards_cross_absolute_row_ranges(tmp_path, request):
    """Reader-only reshaping: detail row 4 in shard 2; row 1 spans source row 3."""
    manifest, files = reader_release(request)
    detail = pq.read_table(files['detail.parquet'])
    sources = pq.read_table(files['sources.parquet'])
    assert detail.num_rows == sources.num_rows == 7
    assert sources.column('ordinal').to_pylist() == [0]*7
    for name in ('src_start', 'src_len'):
        index = detail.schema.get_field_index(name)
        field = detail.schema.field(index)
        detail = detail.set_column(index, field,
            pa.array([value*2 for value in detail.column(name).to_pylist()], type=field.type))
    sources = sources.take(pa.array([index for index in range(7) for _ in range(2)]))
    ordinal = sources.schema.get_field_index('ordinal')
    field = sources.schema.field(ordinal)
    sources = sources.set_column(ordinal, field, pa.array([0, 1]*7, type=field.type))
    tables = {}
    for name, table in [('detail', detail), ('sources', sources)]:
        for index, (start, end) in enumerate([(0, 3), (3, table.num_rows)]):
            tables[f'{name}-{index:05}.parquet'] = (table.slice(start, end-start), name, [start, end])
    _, variant = reader_variant(tmp_path/'shards', manifest, files, tables,
        remove=('detail.parquet', 'sources.parquet'))
    result = subprocess.run(['node', '--test', str(ROOT/'apps/site/scripts/archive-shards.test.mjs')],
        cwd=ROOT/'apps/site', env=reader_environment(tmp_path, variant),
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout+result.stderr


def test_reader_redirects_retired_keys_and_shows_removal_notices(tmp_path, request):
    """Gate 2 in the reader: live, redirected, removed and never-published keys."""
    from viewer_publication.release_gate import RETIRED

    manifest, files = reader_release(request)
    live = pq.read_table(files['links.parquet']).to_pylist()[0]
    rows = [dict(link_key=b'\xaa'*8, successor_key=live['link_key'],
                 last_release_id='d'*64, last_filename='old.pdf'),
            dict(link_key=b'\xbb'*8, successor_key=None, last_release_id='e'*64,
                 last_filename='gone.pdf', address_versions=[live['link_key']])]
    _, variant = reader_variant(tmp_path/'retired', manifest, files, {
        'retired_links.parquet': (pa.Table.from_pylist(rows, schema=RETIRED), None, None)})
    expected = tmp_path/'retired-expected.json'
    expected.write_text(json.dumps(dict(
        live=dict(key=live['link_key'].hex(), index=live['list_row']), redirect=dict(key='aa'*8),
        removed=dict(key='bb'*8, last_release_id='e'*64, last_filename='gone.pdf',
                     versions=[live['link_key'].hex()]))))
    result = subprocess.run(['node', '--test', str(ROOT/'apps/site/scripts/archive-retired.test.mjs')],
        cwd=ROOT/'apps/site', env=reader_environment(tmp_path, variant, ARCHIVE_EXPECTED_FILE=str(expected)),
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout+result.stderr


def test_reader_opens_earlier_witness_keys_through_the_key_map(tmp_path, request):
    """Earlier keys resolve only when unambiguous; other outcomes explain why."""
    _, files = reader_release(request)
    result = subprocess.run(['node', '--test', str(ROOT/'apps/site/scripts/archive-witness-map.test.mjs')],
        cwd=ROOT/'apps/site', env=reader_environment(tmp_path, files),
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout+result.stderr
