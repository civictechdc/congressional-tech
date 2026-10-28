"""D3: one typed reading per distinct filename/URL/version, through native work lists."""
import gzip
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets
from house_naming.errors import NamingError


def reader():
    from congress_api.lake import filenames
    return filenames


STAMP = '2026-10-27T18:00:00Z'


class Worker:
    def __init__(self, parser, version, callable_path, **bounds):
        self.parser, self.version, self.bounds = parser, version, bounds
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def parse(self, input_id, payload):
        assert isinstance(payload, bytes)
        row = reader().parse_payload(payload)
        return dict(status='completed', value=row)


class TerminalWorker(Worker):
    def parse(self, input_id, payload):
        return dict(status='unreadable', reason='timeout', attempts=2)


def engine():
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def test_typed_bill_keys_use_known_congress_and_preserve_literals():
    row = reader().read_filename('BILLS-119hr6028ih.pdf', '', catalog_version='v')
    assert row['status'] == 'completed' and row['valid']
    assert row['congress'] == 119 and row['measure_type'] == 'hr'
    assert row['measure_keys'] == ['119-hr-6028']
    assert row['package_id'] == 'BILLS-119hr6028ih'
    unknown = reader().read_filename('H.R.1.S.2.pdf', '', catalog_version='v')
    assert unknown['measure_keys'] == [] and unknown['measure_number'] is None
    assert [v['value'] for v in unknown['fields'] if v['field'] == 'measure_references'] == ['hr1', 's2']


def test_dates_bioguide_and_all_facets_keep_ambiguity():
    row = reader().read_filename('HHRG-119-IF00-Wstate-X000001-20260203.pdf', '', catalog_version='v')
    assert row['filename_date'].isoformat() == '2026-02-03'
    assert row['bioguide_ids'] == ['X000001'] and row['committee_code'] == ['IF00']
    assert row['package_id'] is None
    ambiguous = reader().read_filename('01-02-2003.pdf', '', catalog_version='v')
    assert ambiguous['filename_date'] is None
    empty = reader().read_filename('', '', catalog_version='v')
    assert empty['status'] == 'completed' and not empty['valid']


class Parser:
    def __init__(self, error): self.calls = []; self.error = error
    def extract(self, filename, *, source_url=None, **kwargs):
        self.calls.append(source_url)
        if source_url is not None: raise NamingError(self.error, 'stable code, private detail')
        return {'valid': False, 'matches': [], 'metadata': {'document_kind': ['a', 'b'],
                'congress': ['118', '119'], 'measure_references': ['hr7']}}


def test_only_invalid_source_url_retries_without_changing_identity():
    parser = Parser('invalid-source-url')
    row = reader().read_filename('a.pdf', 'bad URL', catalog_version='v', parser=parser)
    assert parser.calls == ['bad URL', None] and row['source_url'] == 'bad URL'
    assert row['status'] == 'completed' and row['error_type'] is None
    assert row['document_kind'] == ['a', 'b'] and row['congress'] is None
    parser = Parser('invalid-filename')
    row = reader().read_filename('a.pdf', 'https://a.test/a', catalog_version='v', parser=parser)
    assert parser.calls == ['https://a.test/a']
    assert row['status'] == 'error' and row['error_type'] == 'invalid-filename'
    assert 'private detail' not in str(row)
    with pytest.raises(RuntimeError, match='input unavailable'):
        reader().read_filename('a.pdf', '', catalog_version='v', parser=Unavailable())


class Unavailable:
    def extract(self, *args, **kwargs): raise RuntimeError('input unavailable')


def test_large_input_is_settled_without_entering_the_parser():
    row = reader().read_filename('x' * 16385, '', catalog_version='v', parser=Unavailable())
    assert row['status'] == 'size_limit' and not row['valid']


def test_version_digest_covers_package_nested_vocabularies_and_lock(tmp_path):
    from congress_api.lake.versions import version_digest
    package = tmp_path / 'package'; package.mkdir()
    (package/'one.py').write_text('a')
    nested = package/'data'; nested.mkdir(); vocabulary = nested/'codes.json'; vocabulary.write_text('{}')
    lock = tmp_path/'uv.lock'; lock.write_text('locked')
    def version(): return version_digest(packages={'parser': package}, files={'lock': lock}, values={'vocab': {'x': ['a']}})
    first = version(); assert first == version()
    vocabulary.write_text('{"a":1}'); second = version(); assert second != first
    lock.write_text('changed'); assert version() != second
    before_cache = version()
    cache = package/'__pycache__'; cache.mkdir(); (cache/'x.pyc').write_bytes(b'ignored')
    assert version() == before_cache
    assert version_digest(packages={'parser': package}, files={'lock': lock}, values={'vocab': {'x': ['b']}}) != before_cache


def input_tables(tmp_path, rows):
    schema = pa.schema([('receipt_key',pa.string()),('receipt_line',pa.int64()),('capture_index',pa.int32()),
        ('mode',pa.string()),('url',pa.string()),('requested_url',pa.string()),('member_path',pa.string()),
        ('h_content_disposition',pa.string()),('sha256',pa.binary(32))])
    path=tmp_path/'captures.parquet'; pq.write_table(pa.Table.from_pylist(rows,schema=schema),path)
    return path


def test_capture_filename_uses_download_header(tmp_path):
    captures=input_tables(tmp_path,[dict(receipt_key='r',receipt_line=1,capture_index=0,mode='fetch',
        url='https://a.test/addresspath.pdf',h_content_disposition='attachment; filename=header-only.pdf')])
    result=reader().stage(worker_factory=Worker,decided_at=STAMP,captures=captures,recovery_files=[],
        engine=engine(),work=tmp_path/'job')
    rows=pq.read_table(result['readings']).to_pylist()
    assert [(row['filename'],row['source_url']) for row in rows] == [
        ('header-only.pdf','https://a.test/addresspath.pdf')]
    assert rows[0]['status']=='completed'


def test_native_effective_names_and_work_anti_join(tmp_path):
    cases = [
        dict(url='https://a.test/path.pdf', h_content_disposition="attachment; filename=old.pdf; filename*=UTF-8''caf%C3%A9.pdf"),
        dict(url='https://a.test/path.pdf?name=b.pdf&file=a%2520%2Bb.pdf&file=later.pdf'),
        dict(url='https://a.test/path.pdf?file=%FF.pdf'),
        dict(url='https://a.test/path.pdf', member_path='folder/Member%20.pdf'),
        dict(url=None, requested_url='https://a.test/Requested%20Name.pdf'),
        dict(url='https://a.test/path.pdf?name=source.pdf',requested_url='https://a.test/path?file=requested.pdf'),
        dict(url='https://a.test/path.pdf?file&name=ignored.pdf'),
        dict(url='https://a.test/path.pdf#fragment?file=ignored.pdf'),
        dict(url='https://a.test/path.pdf?file=question?mark.pdf'),
    ]
    captures=input_tables(tmp_path,[dict(receipt_key='r',receipt_line=i,capture_index=0,mode='fetch',**row)
        for i,row in enumerate(cases,1)])
    version = reader().current_version()
    result=reader().stage(worker_factory=Worker, decided_at=STAMP, captures=captures, recovery_files=[], engine=engine(), work=tmp_path/'job', catalog_version=version)
    rows=pq.read_table(result['readings']).to_pylist()
    assert len(rows) == 9  # Same path name at different exact URLs remains separate work.
    names={r['filename'] for r in rows}
    assert names == {'café.pdf','a%20+b.pdf','%FF.pdf','Member%20.pdf','Requested Name.pdf','source.pdf','path.pdf','question?mark.pdf'}
    member=next(r for r in rows if r['filename']=='Member%20.pdf'); assert member['source_url']==''
    second=reader().stage(worker_factory=Worker, decided_at=STAMP, captures=captures,recovery_files=[],existing=result['readings'],engine=engine(),work=tmp_path/'again',catalog_version=version)
    assert pq.read_metadata(second['readings']).num_rows == 0
    newer=reader().stage(worker_factory=Worker, decided_at=STAMP, captures=captures,recovery_files=[],existing=result['readings'],engine=engine(),work=tmp_path/'new',vocabularies={'member_surnames': {'119': ['New']}})
    assert pq.read_metadata(newer['readings']).num_rows == 9


def test_recovery_original_work_deduplicates_and_rejection_removes_name_override(tmp_path):
    captures=input_tables(tmp_path,[dict(receipt_key='r',receipt_line=1,capture_index=0,mode='retained_import',
        url='https://archive.test/recovered.pdf')])
    path=tmp_path/'recoveries.jsonl.gz'
    decisions=[dict(body_sha256='a'*64,id='a',original_url='https://a.test/Original.pdf',recovered_filename='Old.pdf',kind='recovered_document',decided_at='2026-10-01T00:00:00Z'),
               dict(body_sha256='a'*64,id='b',original_url='https://a.test/Original.pdf',recovered_filename='Rejected.pdf',kind='rejected',decided_at='2026-10-02T00:00:00Z'),
               dict(body_sha256='c'*64,id='c',original_url='https://a.test/Another.pdf',recovered_filename='Named.pdf',kind='recovered_document',decided_at='2026-10-02T00:00:00Z'),
               dict(body_sha256='d'*64,id='d',original_url='https://a.test/Another.pdf',recovered_filename='Other Body.pdf',kind='recovered_document',decided_at='2026-10-03T00:00:00Z')]
    with gzip.open(path,'wt') as out:
        for row in decisions: out.write(json.dumps(row)+'\n')
    result=reader().stage(worker_factory=Worker, decided_at=STAMP, captures=captures,recovery_files=[dict(key='provenance/recoveries/source.jsonl',path=str(path))],engine=engine(),work=tmp_path/'job')
    rows=pq.read_table(result['readings']).to_pylist()
    assert {(r['filename'],r['source_url']) for r in rows} == {('Original.pdf','https://a.test/Original.pdf'),('Named.pdf','https://a.test/Another.pdf'),('Other Body.pdf','https://a.test/Another.pdf')}


def test_stage_refuses_a_version_that_does_not_name_its_code_and_inputs(tmp_path):
    captures=input_tables(tmp_path, [])
    with pytest.raises(ValueError, match='version'):
        reader().stage(worker_factory=Worker, decided_at=STAMP, captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'job',catalog_version='wrong')


def test_local_stage_command_writes_only_local_outputs(tmp_path, capsys):
    captures=input_tables(tmp_path, [])
    inventory=tmp_path/'inventory.json'; inventory.write_text('[]')
    assert reader().main(['--captures',str(captures),'--recovery-inventory',str(inventory),
        '--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],'--decided-at',STAMP,'--work',str(tmp_path/'stage')],worker_factory=Worker) == 0
    result=json.loads(capsys.readouterr().out)
    assert result['catalog_version'] == reader().current_version()
    assert pq.read_metadata(result['readings']).num_rows == 0


def test_native_filename_table_preserves_schema_partition_and_noop_append(tmp_path):
    module=reader()
    module.create_table(engine=engine(),work=tmp_path/'create',catalog_root=tmp_path/'catalog',
        table={'namespace':['archive'],'name':'filename_readings'},location=tmp_path/'data',create_namespace=True)
    captures=input_tables(tmp_path,[dict(receipt_key='r',receipt_line=1,capture_index=0,mode='fetch',
        url='https://a.test/BILLS-119hr6028ih.pdf')])
    stage=module.stage(worker_factory=Worker, decided_at=STAMP, captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'stage')
    first=module.append(stage,engine=engine(),work=tmp_path/'append',catalog_root=tmp_path/'catalog',
        table={'namespace':['archive'],'name':'filename_readings'})
    assert sum(part['rows'] for part in first['files']) == 1
    second=module.append(stage,engine=engine(),work=tmp_path/'again',catalog_root=tmp_path/'catalog',
        table={'namespace':['archive'],'name':'filename_readings'})
    assert second['files'] == [] and first['metadata_location'] == second['metadata_location']
    metadata=json.loads(Path(first['metadata_location']).read_text())
    schema=metadata['schemas'][0]
    # Iceberg represents identifier fields as a set, independent of PK sort order.
    assert set(schema['identifier-field-ids']) == {1,2,3}
    assert all(field['required'] for field in schema['fields'] if field['id'] in {1,2,3})
    assert metadata['format-version'] == 2 and metadata['properties']['gc.enabled'] == 'true'
    assert metadata['partition-specs'][0]['fields'][0]['source-id'] == 3
    assert [field['name'] for field in schema['fields']] == module.SCHEMA.names


@pytest.mark.parametrize('arguments', [
    ['--apply'], ['--create-table'], ['--create-namespace'],
    ['--apply','--catalog-root','unused','--table','not-qualified']])
def test_apply_requires_explicit_local_authority_before_input_reads(tmp_path, arguments):
    with pytest.raises(SystemExit) as raised:
        reader().main(['--captures','missing','--recovery-inventory','missing',
            '--engine-config','missing','--decided-at',STAMP,'--work',str(tmp_path/'unused'),*arguments])
    assert raised.value.code == 2 and not (tmp_path/'unused').exists()


def test_explicit_local_apply_command_keeps_empty_work_a_noop(tmp_path, capsys):
    captures=input_tables(tmp_path, [])
    inventory=tmp_path/'inventory.json'; inventory.write_text('[]')
    assert reader().main(['--captures',str(captures),'--recovery-inventory',str(inventory),
        '--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],'--decided-at',STAMP,'--work',str(tmp_path/'stage'),
        '--apply','--catalog-root',str(tmp_path/'catalog'),'--table','archive.filename_readings',
        '--create-table','--create-namespace','--table-location',str(tmp_path/'data')],worker_factory=Worker) == 0
    result=json.loads(capsys.readouterr().out)
    assert result['append']['files'] == [] and (tmp_path/'catalog').exists()


def test_terminal_worker_result_stages_raw_provenance_and_rebuild_skips_it(tmp_path):
    captures=input_tables(tmp_path,[dict(receipt_key='r',receipt_line=1,capture_index=0,mode='fetch',
        url='https://a.test/Bad.pdf')])
    result=reader().stage(captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'stage',
        worker_factory=TerminalWorker,decided_at=STAMP)
    assert pq.read_metadata(result['readings']).num_rows == 0
    key=result['unreadable_key']
    records=Path(result['unreadable_path']).read_text().splitlines()
    assert key.startswith('provenance/unreadable/') and len(records)==1
    row=json.loads(records[0])
    assert row['parser']=='filename' and row['reason']=='timeout' and row['supersedes'] is None
    assert len(row['record_sha'])==64 and row['parser_version']==result['catalog_version']
    repeat=reader().stage(captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'again',
        worker_factory=TerminalWorker,decided_at=STAMP,
        unreadable_files=[dict(key=key,path=result['unreadable_path'])])
    assert repeat['unreadable_key'] is None and pq.read_metadata(repeat['work_list']).num_rows == 0


def test_same_time_unreadable_batches_share_one_raw_store_and_rebuild(tmp_path):
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    from congress_api.retention.provenance import file_pin, timestamp_key
    raw=tmp_path/'shared-raw';store=BodyStore(LocalAdapter(raw))
    captures_rows=[];staged=[];inventory=[]
    for index,name in enumerate(['Bad.pdf','OtherBad.pdf']):
        source=tmp_path/f'input-{index}';source.mkdir()
        row=dict(receipt_key=f'r-{index}',receipt_line=1,capture_index=0,mode='fetch',
            url='https://a.test/'+name)
        captures_rows.append(row)
        result=reader().stage(captures=input_tables(source,[row]),recovery_files=[],engine=engine(),
            work=tmp_path/f'stage-{index}',worker_factory=TerminalWorker,decided_at=STAMP)
        assert pq.read_metadata(result['readings']).num_rows==0
        assert store.put(result['unreadable_key'],result['unreadable_path'],
            'application/x-ndjson').outcome=='stored'
        staged.append(result)
        inventory.append(dict(key=result['unreadable_key'],path=str(raw/result['unreadable_key'])))
    assert len({item['key'] for item in inventory})==2
    records=[]
    for result,item in zip(staged,inventory):
        assert item['key']=='provenance/unreadable/'+timestamp_key(STAMP)+'-'+file_pin(item['path'])['sha256']+'.jsonl'
        assert Path(item['path']).read_bytes()==Path(result['unreadable_path']).read_bytes()
        records.extend(map(json.loads,Path(item['path']).read_text().splitlines()))
    assert len(records)==2 and len({row['record_sha'] for row in records})==2
    assert len({row['parser_version'] for row in records})==1
    assert all(row['decided_at']==STAMP and row['parser']=='filename' for row in records)
    repeat=reader().stage(captures=input_tables(tmp_path,captures_rows),recovery_files=[],engine=engine(),
        work=tmp_path/'rebuilt',worker_factory=TerminalWorker,decided_at=STAMP,unreadable_files=inventory)
    assert pq.read_metadata(repeat['work_list']).num_rows==0
    assert pq.read_metadata(repeat['readings']).num_rows==0 and repeat['unreadable_key'] is None


class PrematureWorker(Worker):
    def parse(self, input_id, payload):
        return dict(status='unreadable',reason='timeout',attempts=1)


def test_worker_cannot_author_a_terminal_decision_before_its_second_failure(tmp_path):
    captures=input_tables(tmp_path,[dict(receipt_key='r',receipt_line=1,capture_index=0,mode='fetch',
        url='https://a.test/Bad.pdf')])
    with pytest.raises(ValueError,match='worker result'):
        reader().stage(captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'stage',
            worker_factory=PrematureWorker,decided_at=STAMP)
    assert not (tmp_path/'stage/raw').exists()


@pytest.mark.parametrize('filename,expected',[
    ('bills-119hr6028ih.pdf','BILLS-119hr6028ih'),
    ('BiLlS-119HR6028IH.PDF','BILLS-119hr6028ih'),
    ('cHrG-118SHRG49104057.Pdf','CHRG-118shrg49104057')])
def test_recognized_case_variants_keep_canonical_package_keys_and_literal_fields(filename,expected):
    row=reader().read_filename(filename,'',catalog_version='v')
    assert row['valid'] and row['package_id']==expected
    assert next(value['value'] for value in row['fields'] if value['field']=='package_family') == filename.split('-')[0]


def test_actual_worker_produces_completed_rows_and_settles_transport_size_limit(tmp_path):
    from congress_api.retention.parser_worker import ParserWorker
    captures=input_tables(tmp_path,[dict(receipt_key='r',receipt_line=1,capture_index=0,mode='fetch',
        url='https://a.test/BILLS-119hr6028ih.pdf')])
    complete=reader().stage(captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'complete',decided_at=STAMP)
    [row]=pq.read_table(complete['readings']).to_pylist()
    assert row['status']=='completed' and row['measure_keys']==['119-hr-6028']
    def limited_worker(*args,**bounds):
        bounds['max_input_bytes']=1
        return ParserWorker(*args,**bounds)
    limited=reader().stage(captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'limited',
        decided_at=STAMP,worker_factory=limited_worker)
    [row]=pq.read_table(limited['readings']).to_pylist()
    assert row['status']=='size_limit' and row['error_type']=='worker_input_size_limit'
    assert limited['unreadable_key'] is None
    again=reader().stage(captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'again',
        existing=limited['readings'],decided_at=STAMP,worker_factory=limited_worker)
    assert pq.read_metadata(again['readings']).num_rows==0


def test_actual_worker_terminal_failure_stages_raw_evidence_and_rebuild_skips_it(tmp_path):
    from congress_api.retention.parser_worker import ParserWorker
    crash=tmp_path/'crash.py'
    crash.write_text("def parse(payload):\n    raise RuntimeError('fixture parser crash')\n")
    def crashing_worker(parser,version,callable_path,**bounds):
        return ParserWorker(parser,version,str(crash)+':parse',**bounds)
    captures=input_tables(tmp_path,[dict(receipt_key='r',receipt_line=1,capture_index=0,mode='fetch',
        url='https://a.test/Bad.pdf')])
    result=reader().stage(captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'stage',
        worker_factory=crashing_worker,decided_at=STAMP)
    assert pq.read_metadata(result['readings']).num_rows==0
    [line]=Path(result['unreadable_path']).read_text().splitlines()
    assert json.loads(line)['reason']=='parser_crash'
    repeat=reader().stage(captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'repeat',
        worker_factory=crashing_worker,decided_at=STAMP,
        unreadable_files=[dict(key=result['unreadable_key'],path=result['unreadable_path'])])
    assert pq.read_metadata(repeat['work_list']).num_rows==0 and repeat['unreadable_key'] is None


def test_filename_cli_creates_a_second_table_without_recreating_existing_namespace(tmp_path,capsys):
    captures=input_tables(tmp_path,[])
    inventory=tmp_path/'inventory.json'; inventory.write_text('[]')
    common=['--captures',str(captures),'--recovery-inventory',str(inventory),
        '--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],'--decided-at',STAMP,'--apply',
        '--catalog-root',str(tmp_path/'catalog'),'--create-table']
    assert reader().main([*common,'--work',str(tmp_path/'first'),'--table','archive.first',
        '--table-location',str(tmp_path/'first-data'),'--create-namespace'])==0
    capsys.readouterr()
    assert reader().main([*common,'--work',str(tmp_path/'second'),'--table','archive.second',
        '--table-location',str(tmp_path/'second-data')])==0
    assert json.loads(capsys.readouterr().out)['append']['files']==[]


def test_actual_worker_startup_failure_propagates_without_unreadable_decision(tmp_path):
    from congress_api.retention.parser_worker import ParserWorker
    bad=tmp_path/'bad_startup.py'; bad.write_text('not_the_callable = True\n')
    def startup_failure(parser,version,callable_path,**bounds):
        return ParserWorker(parser,version,str(bad)+':missing',**bounds)
    captures=input_tables(tmp_path,[dict(receipt_key='r',receipt_line=1,capture_index=0,mode='fetch',
        url='https://a.test/Bad.pdf')])
    with pytest.raises(RuntimeError,match='startup'):
        reader().stage(captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'stage',
            worker_factory=startup_failure,decided_at=STAMP)
    assert not (tmp_path/'stage/raw').exists()


def test_filename_version_tracks_its_package_and_inputs_without_sibling_d1_changes(tmp_path):
    import importlib.util
    import shutil
    module=reader()
    original=Path(module.__file__).resolve()
    fixture=tmp_path/'fixture'
    relative=original.relative_to(module.ROOT)
    destination=fixture/relative
    shutil.copytree(original.parent,destination.parent,ignore=shutil.ignore_patterns('__pycache__'))
    for relative_input in ('uv.lock','model/sql/effective-filenames.sql',
        'model/registries/filename-parameters.json','model/lake/filename-readings.schema.json'):
        target=fixture/relative_input; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(module.ROOT/relative_input,target)
    spec=importlib.util.spec_from_file_location('filename_version_fixture',destination)
    loaded=importlib.util.module_from_spec(spec); spec.loader.exec_module(loaded)
    baseline=loaded.current_version()
    sibling=fixture/'packages/congress_api/src/congress_api/lake/captures.py'
    sibling.parent.mkdir(parents=True,exist_ok=True)
    sibling.write_text('# Only the independent D1 producer changed.\n')
    assert loaded.current_version()==baseline
    nested=destination.parent/'nested'; nested.mkdir()
    (nested/'rule.py').write_text('producer_change = True\n')
    assert loaded.current_version()!=baseline
    (nested/'rule.py').unlink(); nested.rmdir()
    assert loaded.current_version()==baseline
    assert loaded.current_version(vocabularies={'member_surnames':{'119':['Changed']}})!=baseline
    for relative_input in ('uv.lock','model/sql/effective-filenames.sql',
        'model/registries/filename-parameters.json','model/lake/filename-readings.schema.json'):
        target=fixture/relative_input; data=target.read_bytes()
        target.write_bytes(data+b'\n')
        assert loaded.current_version()!=baseline
        target.write_bytes(data)
        assert loaded.current_version()==baseline


def test_module_cli_and_worker_callback_keep_the_public_package_path(tmp_path):
    import subprocess
    import sys
    captures=input_tables(tmp_path,[dict(receipt_key='r',receipt_line=1,capture_index=0,mode='fetch',
        url='https://a.test/BILLS-119hr6028ih.pdf')])
    inventory=tmp_path/'recoveries.json'; inventory.write_text('[]')
    result=subprocess.run([sys.executable,'-I','-m','congress_api.lake.filenames',
        '--captures',str(captures),'--recovery-inventory',str(inventory),'--decided-at',STAMP,
        '--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],'--work',str(tmp_path/'stage')],
        capture_output=True,text=True,check=True)
    staged=json.loads(result.stdout)
    [row]=pq.read_table(staged['readings']).to_pylist()
    assert row['status']=='completed' and row['measure_keys']==['119-hr-6028']
