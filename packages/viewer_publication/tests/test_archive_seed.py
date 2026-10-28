"""Authored v5 seed cases precede the native conversion implementation."""
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT=Path(__file__).parents[3]
ARRAYS='body_keys format body_format media_type source_link_label document_kind document_family committee_code congress date_token date_token_candidates measure_references member_bioguide_id hearing_package_id source_meeting_id source_meeting_title source_meeting_date source_chamber source_committee_code source_committee_name source_page_url state_retrieved_at source_document_type source_document_added_at'.split()


def compact(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))
def digest(value):return hashlib.sha256(compact(value).encode()).hexdigest()


def seed_spec(tmp_path,change=None):
    from congress_api.retention.provenance import file_pin
    fixture=json.loads((ROOT/'model/fixtures/seed-v5.json').read_text())
    if change:change(fixture)
    fields=[pa.field(name,pa.string()) for name in ['document_id','source_id','body_key','filename','source_url']]
    schema=pa.schema(fields+[pa.field(name,pa.list_(pa.string())) for name in ARRAYS])
    paths={}
    for name in ['documents','filenames']:
        rows=[{**{key:[] for key in ARRAYS},**row} for row in fixture[name]]
        path=tmp_path/(name+'.parquet');pq.write_table(pa.Table.from_pylist(rows,schema=schema),path)
        paths[name]=path
    path=tmp_path/'captures.parquet'
    pq.write_table(pa.Table.from_pylist(fixture['captures'],schema=pa.schema([('body_key',pa.string()),('bytes',pa.int64()),('stored_bytes',pa.int64())])),path);paths['captures']=path
    path=tmp_path/'accepted.json';path.write_text(compact(fixture['accepted'])+'\n');paths['accepted']=path
    value=dict(version=1,kind='seed_v5',display_only=True,catalog_id='a'*32,generation='b'*32,
        document_rows=len(fixture['documents']),engine_revision=json.loads(Path(os.environ['DOCSPEC_JOB_CONFIG']).read_text())['source_revision'],engine_config=os.environ['DOCSPEC_JOB_CONFIG'],
        output=str(tmp_path/'release'),scratch=str(tmp_path/'jobs'),
        input_files={name:dict(path=str(path),**file_pin(path)) for name,path in paths.items()})
    spec=tmp_path/'seed.json';spec.write_text(compact(value));return spec,fixture


def build(tmp_path,change=None):
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_seed import load_seed_spec,build_seed_release
    path,fixture=seed_spec(tmp_path,change);spec=load_seed_spec(path)
    with NativeDatasets.from_config(spec['engine_config']) as engine:
        manifest=build_seed_release(spec,engine=engine,output=Path(spec['output']),scratch=Path(spec['scratch']))
    return manifest,spec,fixture


def test_seed_keeps_real_ids_sizes_recovery_sources_and_reconciles(tmp_path):
    manifest,spec,fixture=build(tmp_path)
    result=json.loads((Path(spec['scratch'])/'result.json').read_text())
    reports={item['name']:item['data'] for item in result['queries']}
    assert reports['seed_reconciliation']==[dict(input_docs=4,listed=3,excluded=1)]
    assert sum(row['count'] for row in reports['seed_exclusions'])==1
    assert reports['seed_exclusions'][0]['reason']=='duplicate_document_identity'
    assert reports['seed_invariants'] and all(type(v) is int and v==0 for v in reports['seed_invariants'][0].values())
    assert len(reports['probe_selectors'])==1
    out=Path(spec['output'])
    expected={item['name'] for item in json.loads((ROOT/'model/registries/release-schema.json').read_text())['files']}
    assert {p.name for p in out.glob('*.parquet')}==expected
    assert manifest['origin']['kind']=='seed_v5' and manifest['origin']['display_only'] is True
    assert manifest['origin']['label']=='seed: v5 catalog bbbbbbbb'
    assert set(manifest['origin']['input_files'])=={'documents','filenames','captures','accepted'}
    for name in expected:
        assert [f.name for f in pq.ParquetFile(out/name).schema_arrow]==[f['name'] for f in next(item for item in json.loads((ROOT/'model/registries/release-schema.json').read_text())['files'] if item['name']==name)['columns']]
    details=pq.read_table(out/'detail.parquet').to_pylist();listed=pq.read_table(out/'list.parquet').to_pylist()
    by_name={row['filename']:(row,details[i]) for i,row in enumerate(listed)}
    assert by_name['report.pdf'][1]['saved_bytes']==20
    assert by_name['report.pdf'][0]['meeting_keys']==['123456']
    assert by_name['missing.pdf'][1]['saved_body'] is None
    recoveries=pq.read_table(out/'recoveries.parquet').to_pylist()
    assert len(recoveries)==1 and recoveries[0]['kind']=='recovered_document'
    assert recoveries[0]['bytes']==30 and recoveries[0]['imported_at'] is None
    sources=pq.read_table(out/'sources.parquet').to_pylist()
    assert any(row['listed_on']=='https://fixture.test/hearing' for row in sources)
    members=pq.read_table(Path(spec['scratch'])/'seed-members.parquet').to_pylist()
    for row in members:
        key=row['logical_body_key']
        assert row['source_id']==digest([key,row['filename'],row['source_url']])
        assert not row['source_id'].startswith('legacy-')
    ids=pq.read_table(Path(spec['scratch'])/'seed-identities.parquet').to_pylist()
    for row in ids:
        expected_id=digest(['bodies',row['body_keys']]) if row['body_keys'] else digest(['sources',row['source_ids']])
        assert row['document_id']==expected_id
    assert pq.read_table(out/'url_state.parquet').num_rows==0
    assert json.loads((out/'capture_scope.json').read_text())['entries']==[]


@pytest.mark.parametrize('failure',['missing_size','conflicting_size','unknown_recovery_kind','missing_status','null_status'])
def test_seed_refuses_missing_facts_and_unmapped_recoveries(tmp_path,failure):
    def change(fixture):
        if failure=='missing_size':fixture['captures']=fixture['captures'][2:]
        elif failure=='conflicting_size':fixture['captures'][1]['bytes']=999
        elif failure=='unknown_recovery_kind':fixture['accepted']['recoveries'][0]['recovery_basis']='unmapped-new-claim'
        elif failure=='missing_status':del fixture['accepted']['recoveries'][0]['recovery_status']
        else:fixture['accepted']['recoveries'][0]['recovery_status']=None
    with pytest.raises(ValueError,match='[Ii]nvariant|[Ss]ize|[Rr]ecovery'):
        build(tmp_path,change)
    assert not (tmp_path/'release/manifest.json').exists()


def test_seed_plan_reads_no_inputs_or_runtime(tmp_path):
    from viewer_publication.archive_seed import load_seed_spec
    path,fixture=seed_spec(tmp_path)
    raw=json.loads(path.read_text())
    for value in raw['input_files'].values():Path(value['path']).unlink()
    raw['engine_config']=str(tmp_path/'unopened-runtime.json');path.write_text(compact(raw))
    spec=load_seed_spec(path)
    assert spec['kind']=='seed_v5' and not Path(spec['output']).exists()

@pytest.mark.parametrize('name',[
    'model/jobs/seed-v5.json','model/sql/seed-v5-documents.sql',
    'model/registries/recovery-kinds.json','model/registries/reader-limits.json'])
def test_seed_refuses_definition_drift_before_native_effects(tmp_path,name):
    from viewer_publication.archive_seed import load_seed_spec,build_seed_release
    from congress_api.retention.derived_files import file_identity
    path,_=seed_spec(tmp_path);spec=load_seed_spec(path)
    assert name in spec['profile']['definition_hashes']
    # An owned copy can have the same declared bytes, but it cannot replace
    # custody of the definition the loader actually inspected.
    owned=tmp_path/'definition';owned.write_bytes((ROOT/name).read_bytes())
    proof=file_identity(owned);owned.write_bytes(owned.read_bytes()+b'\n')
    spec['_definition_identities'][name]=proof
    class NeverRun:
        source_revision=spec['engine_revision']
        def run_job(self,*args):pytest.fail('Drift must refuse before native execution')
    with pytest.raises(ValueError,match='[Cc]ustody|[Dd]efinition'):
        build_seed_release(spec,engine=NeverRun(),output=spec['output'],scratch=spec['scratch'])
    assert not Path(spec['output']).exists() and not Path(spec['scratch']).exists()


def test_seed_refuses_definition_hash_drift_during_native_execution(tmp_path):
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_seed import load_seed_spec,build_seed_release
    path,_=seed_spec(tmp_path);spec=load_seed_spec(path)
    name='model/jobs/seed-v5.json'
    with NativeDatasets.from_config(spec['engine_config']) as native:
        class ObservedNative:
            source_revision=native.source_revision
            def run_job(self,*args,**kwargs):
                result=native.run_job(*args,**kwargs)
                spec['profile']['definition_hashes'][name]='0'*64
                return result
        with pytest.raises(ValueError,match='[Dd]efinition'):
            build_seed_release(spec,engine=ObservedNative(),output=spec['output'],scratch=spec['scratch'])
