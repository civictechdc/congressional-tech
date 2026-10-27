"""Run the shipped reader against release bytes written by the native engine."""
import os
from pathlib import Path
import subprocess

from docspec_client.client import NativeDatasets
from viewer_publication.archive_release import build_fixture_release

ROOT = Path(__file__).parents[3]


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
