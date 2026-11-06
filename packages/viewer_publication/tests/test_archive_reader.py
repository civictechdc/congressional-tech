"""Run the shipped reader against release bytes written by the native engine."""
import os
from pathlib import Path
import subprocess
import pytest

from docspec_client.client import NativeDatasets
from viewer_publication.archive_fixture import build_fixture_release

ROOT = Path(__file__).parents[3]


@pytest.mark.parametrize('missing', ['none', 'document_date_status', 'address_versions'])
def test_current_reader_requires_current_fields_and_preserves_nulls(tmp_path, missing):
    """Real public metadata and hand-worked seven-row Parquet; no native build."""
    import json
    import shutil
    import pyarrow as pa
    import pyarrow.parquet as pq
    from test_release_comparison import current_catalog, descriptor
    from viewer_publication.archive_format import release_identity

    release = tmp_path/'release'
    shutil.copytree(ROOT/'model/fixtures/archive-contract/current', release)
    (release/'schema.json').unlink()
    detail = pq.read_table(release/'detail.parquet')
    if 'document_date_status' in detail.column_names:
        detail = detail.drop(['document_date_status'])
    if missing != 'document_date_status':
        detail = detail.append_column('document_date_status', pa.nulls(detail.num_rows, pa.string()))
    pq.write_table(detail, release/'detail.parquet')
    retired = pa.table({'link_key': [b'\xaa'*8, b'\xbb'*8], 'successor_key': [None, None], 'last_release_id': ['d'*64]*2,
        'last_filename': ['removed.pdf']*2, 'address_versions': [None, []]}, schema=pa.schema([
            ('link_key', pa.binary(8)), ('successor_key', pa.binary(8)), ('last_release_id', pa.string()),
            ('last_filename', pa.string()), ('address_versions', pa.list_(pa.binary(8)))]))
    if missing == 'address_versions':
        retired = retired.drop(['address_versions'])
    pq.write_table(retired, release/'retired_links.parquet')
    for name, data in current_catalog().artifacts.items():
        path = release/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    files = [descriptor(path.relative_to(release).as_posix(), path.read_bytes(),
        pq.read_metadata(path).num_rows if path.suffix == '.parquet' else 0)
        for path in sorted(release.rglob('*')) if path.is_file() and path.name != 'manifest.json']
    manifest = dict(schema_version=1, release_id=release_identity(1, files), files=files)
    (release/'manifest.json').write_text(json.dumps(manifest))
    script = """
      import assert from 'node:assert/strict';
      import {readFile} from 'node:fs/promises';
      import {join} from 'node:path';
      import {openArchive} from './src/components/explorer/reader/archive.ts';
      const root=process.env.ARCHIVE_FIXTURE, missing=process.env.ARCHIVE_MISSING_FIELD;
      const manifest=JSON.parse(await readFile(join(root,'manifest.json')));
      const fetcher=async(url,options={})=>{
        const path=new URL(url).pathname;
        if(path==='/manifest.json')return Response.json({release_id:manifest.release_id});
        const bytes=await readFile(join(root,path.split('/').slice(3).join('/')));
        if(!options.headers?.Range)return new Response(bytes);
        const [start,end]=options.headers.Range.slice(6).split('-').map(Number);
        return new Response(bytes.subarray(start,end+1),{status:206,headers:{'Content-Range':`bytes ${start}-${end}/${bytes.length}`}});
      };
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
        env=dict(os.environ, ARCHIVE_FIXTURE=str(release), ARCHIVE_MISSING_FIELD=missing),
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout+result.stderr


def test_shared_reader_contract(tmp_path):
    release = tmp_path / 'release'
    build_fixture_release(ROOT / 'model/fixtures/hand-release.json', output=release,
        scratch=tmp_path / 'job', engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']))
    result = subprocess.run(['node', '--test', str(ROOT / 'apps/site/scripts/archive-reader.test.mjs')],
        cwd=ROOT / 'apps/site', env=dict(os.environ, ARCHIVE_FIXTURE=str(release)),
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_shards_cross_absolute_row_ranges(tmp_path):
    """Expected: detail row4 in shard2; row1's two sources straddle sources row3."""
    import json
    from hashlib import sha256

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    release = tmp_path / 'release'
    manifest = build_fixture_release(ROOT / 'model/fixtures/hand-release.json', output=release,
        scratch=tmp_path / 'job', engine=engine)
    original = json.loads((tmp_path / 'job/job.json').read_text())
    settings = {item['name']: item['settings'] for item in original['outputs']}
    detail_fields = settings['detail.parquet']['columns']
    source_fields = settings['sources.parquet']['columns']
    detail_select = ','.join(f'cast({name}*2 AS INT) AS {name}' if name in {'src_start', 'src_len'} else name for name in detail_fields)
    source_select = ','.join('cast(s.ordinal*2+copy AS INT) AS ordinal' if name == 'ordinal' else f's.{name}' for name in source_fields)
    steps = [dict(name='d', sql=f'SELECT {detail_select},cast(row_number() OVER()-1 AS INT) AS _row FROM old_detail'),
             dict(name='s', sql=f'SELECT {source_select} FROM old_sources s CROSS JOIN unnest(make_array(0,1)) AS copies(copy)')]
    outputs = []
    for name, relation, ranges, keys in [('detail', 'd', [(0,3),(3,7)], ['_row']),
                                        ('sources', 's', [(0,3),(3,14)], ['list_row','ordinal'])]:
        for index, (start, end) in enumerate(ranges):
            writer = dict(settings[name+'.parquet'], order_by=[dict(field=key) for key in keys])
            predicate = f'_row>={start} AND _row<{end}' if name == 'detail' else f'list_row*2+ordinal>={start} AND list_row*2+ordinal<{end}'
            # Each source fixture has exactly one original source, ordinal0.
            outputs.append(dict(name=f'{name}-{index:05}.parquet', path=str(release/f'{name}-{index:05}.parquet'),
                sql=f'SELECT * FROM {relation} WHERE {predicate}', settings=writer))
    spec = dict(scratch=str(tmp_path/'shard-native'), inputs=[dict(name='old_detail',kind='parquet',path=str(release/'detail.parquet')),
        dict(name='old_sources',kind='parquet',path=str(release/'sources.parquet'))], steps=steps, outputs=outputs)
    path=tmp_path/'shard-job.json';path.write_text(json.dumps(spec));result=engine.run_job(path)
    files=[item for item in manifest['files'] if item['name'] not in {'detail.parquet','sources.parquet'}]
    for output in result['outputs']:
        item=dict(output);item.pop('footer_bytes',None);name,index=item['name'].removesuffix('.parquet').rsplit('-',1)
        ranges=[(0,3),(3,7 if name=='detail' else 14)]
        item.update(shard=name,row_range=list(ranges[int(index)]),producer='archive',coverage={});files.append(item)
    identity=[manifest['schema_version'],[[f['name'],f['sha256'],f['size'],f['rows']] for f in files]]
    manifest.update(files=files,release_id=sha256(json.dumps(identity,separators=(',',':')).encode()).hexdigest())
    (release/'manifest.json').write_text(json.dumps(manifest))
    result=subprocess.run(['npm','run','test:archive-shards','--workspaces=false'],cwd=ROOT/'apps/site',
        env=dict(os.environ,ARCHIVE_FIXTURE=str(release)),capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr


def test_reader_redirects_retired_keys_and_shows_removal_notices(tmp_path):
    """Gate 2 in the site reader: live, redirected, removed and never-published keys."""
    import json
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_format import release_identity
    from viewer_publication.release_gate import RETIRED
    release = tmp_path / 'release'
    manifest = build_fixture_release(ROOT / 'model/fixtures/hand-release.json', output=release,
        scratch=tmp_path / 'job', engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']))
    links = pq.read_table(release / 'links.parquet').to_pylist()
    live = links[0]
    rows = [dict(link_key=b'\xaa' * 8, successor_key=live['link_key'], last_release_id='d' * 64, last_filename='old.pdf'),
            dict(link_key=b'\xbb' * 8, successor_key=None, last_release_id='e' * 64, last_filename='gone.pdf',
                 address_versions=[live['link_key']])]
    pq.write_table(pa.Table.from_pylist(rows, schema=RETIRED), release / 'retired_links.parquet')
    pin = file_pin(release / 'retired_links.parquet')
    manifest['files'] = [f for f in manifest['files'] if f['name'] != 'retired_links.parquet'] + [
        dict(name='retired_links.parquet', sha256=pin['sha256'], size=pin['size'], rows=2, md5='0' * 32,
             row_range=None, shard=None, producer='archive', coverage={})]
    manifest['release_id'] = release_identity(1, manifest['files'])
    (release / 'manifest.json').write_text(json.dumps(manifest))
    (release / 'retired-expected.json').write_text(json.dumps(dict(
        live=dict(key=live['link_key'].hex(), index=live['list_row']), redirect=dict(key='aa' * 8),
        removed=dict(key='bb' * 8, last_release_id='e' * 64, last_filename='gone.pdf', versions=[live['link_key'].hex()]))))
    result = subprocess.run(['node', '--test', str(ROOT / 'apps/site/scripts/archive-retired.test.mjs')],
        cwd=ROOT / 'apps/site', env=dict(os.environ, ARCHIVE_FIXTURE=str(release)),
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr


def test_reader_opens_earlier_witness_keys_through_the_key_map(tmp_path):
    """ct-kb4w in the site reader: an unambiguous earlier key opens its successor; the others say why not."""
    release = tmp_path / 'release'
    build_fixture_release(ROOT / 'model/fixtures/hand-release.json', output=release,
        scratch=tmp_path / 'job', engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']))
    result = subprocess.run(['node', '--test', str(ROOT / 'apps/site/scripts/archive-witness-map.test.mjs')],
        cwd=ROOT / 'apps/site', env=dict(os.environ, ARCHIVE_FIXTURE=str(release)),
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
