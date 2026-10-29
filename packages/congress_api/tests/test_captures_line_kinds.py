"""Owner-declared record kinds remain distinct from real acquisition outcomes."""
import importlib.util
import json
from pathlib import Path
import shutil

import pyarrow.parquet as pq
import pytest
from congress_api.lake import captures,receipt_metadata
from test_captures_ingest import body,ingest

ROOT=Path(captures.__file__).resolve().parents[5]
CASES=json.loads((ROOT/'model/fixtures/receipt-line-kinds.json').read_text())
def key(family='documents'):return 'receipts/'+family+'/undated/assemble-fixture.jsonl.gz'

@pytest.mark.parametrize('case',CASES,ids=[x['kind'] for x in CASES])
def test_every_registered_record_kind_has_a_fixture(tmp_path,case):
    stage=ingest(tmp_path,[dict(record=case['record'])],key=key(case['family']))
    [row]=pq.read_table(stage/'captures.parquet').to_pylist()
    assert row['outcome']==case['outcome'] and row['sha256'] is None
    assert row['http_status'] is None and row['capture_index']==0

@pytest.mark.parametrize('fact',[dict(outcome='failed'),dict(outcome='request_failed'),dict(mode='fetch'),
    dict(http_status=404),dict(error='retained request error')])
def test_explicit_acquisition_fact_does_not_become_a_reference(tmp_path,fact):
    stage=ingest(tmp_path,[dict(record=dict(url='https://fixture.test/report.pdf',**fact))],key=key())
    [row]=pq.read_table(stage/'captures.parquet').to_pylist()
    assert row['outcome']==('request_failed' if fact.get('outcome')=='request_failed' else 'failed')

@pytest.mark.parametrize('case',['family','scalar','list_scalar','unknown_api','daily_shape'])
def test_unknown_record_only_shape_refuses_before_append(tmp_path,case):
    record=dict(url='https://fixture.test/report.pdf');source=key()
    if case=='family':source=key('not-enumerated')
    elif case=='scalar':record='unknown scalar'
    elif case=='list_scalar':record=['unknown scalar']
    elif case=='unknown_api':record=dict(url='https://api.congress.gov/v3/not-enumerated/1')
    else:source=source.replace('assemble-fixture','unreviewed-daily')
    with pytest.raises(ValueError,match='unknown.*line kind'):
        ingest(tmp_path,[dict(record=record)],key=source)
    assert not (tmp_path/'stage/ingested-receipts.json').exists()

def test_array_items_keep_separate_record_and_acquisition_outcomes(tmp_path):
    stage=ingest(tmp_path,[dict(record=[dict(url='https://fixture.test/report.pdf'),
        dict(title='Retained inline record'),dict(url='https://fixture.test/error.pdf',outcome='failed')])],key=key())
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['capture_index'] for r in rows]==[0,1,2]
    assert [r['outcome'] for r in rows]==['reference','saved-record','failed']

@pytest.mark.parametrize(('final','expected'),[(None,200),(404,404)])
def test_entry_status_code_fills_only_an_absent_final_status(tmp_path,final,expected):
    line=dict(captures=[body(status_code=200)])
    if final is not None:line['http_status']=final
    stage=ingest(tmp_path,[line])
    [row]=pq.read_table(stage/'captures.parquet').to_pylist();assert row['http_status']==expected

def test_line_kind_registry_is_complete_and_version_bound(tmp_path):
    registry=ROOT/'model/registries/receipt-line-kinds.json'
    assert {c['kind'] for c in CASES}=={k['id'] for k in json.loads(registry.read_text())['kinds']}
    sources=[Path(captures.__file__),Path(receipt_metadata.__file__),registry,
             ROOT/'model/registries/receipt-domain-outcomes.json']
    for source in sources:
        target=tmp_path/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    copied=tmp_path/Path(captures.__file__).relative_to(ROOT)
    spec=importlib.util.spec_from_file_location('copied_line_kind_mapping',copied)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    before=module.current_version();target=tmp_path/registry.relative_to(ROOT);target.write_bytes(target.read_bytes()+b'\n')
    assert module.current_version()!=before


@pytest.mark.parametrize('representation',['pointer','pointer_json','prefixed_json','both'])
def test_both_pointer_representations_select_items_before_coverage(tmp_path,representation):
    records=[dict(url='https://fixture.test/unreferenced.pdf'),
             dict(url='https://fixture.test/one.pdf',http_status=200,outcome='saved'),
             dict(url='https://fixture.test/two.pdf',http_status=200,outcome='saved')]
    references=[]
    for index in [1,2]:
        pointer=[index,'raw_path'];fields={}
        if representation in {'pointer','both'}:fields['pointer']=pointer
        if representation in {'pointer_json','both'}:fields['pointer_json']=json.dumps(pointer)
        if representation=='prefixed_json':fields['pointer_json']=json.dumps(['record',str(index),'raw_path'])
        references.append(body(**fields))
    stage=ingest(tmp_path,[dict(record=records,captures=references)],key=key())
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert len(rows)==3 and [r['capture_index'] for r in rows]==[0,1,2]
    assert [r['url'] for r in rows]==[records[1]['url'],records[2]['url'],records[0]['url']]
    assert [r['sha256'] is None for r in rows]==[False,False,True]
    assert pq.read_table(stage/'capture-evidence.parquet')['source_record_index'].to_pylist()==[1,2,0]


def test_every_explicit_failure_translation_survives_a_success_http_code(tmp_path):
    from congress_api.retention.provenance import run_job
    from docspec_client.client import NativeDatasets
    import os
    failures=[k for k,v in captures.LEGACY_OUTCOMES.items() if v=='failed']
    source=[dict(record=dict(outcome=label,http_status=202,complete=True),captures=[body()]) for label in failures]
    source.append(dict(record=dict(outcome='excluded_media',http_status=200,complete=False),captures=[dict(body(),bytes=0)]))
    stage=ingest(tmp_path,source)
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['outcome'] for r in rows]==['failed']*len(source)
    work=tmp_path/'good-fetch-check';work.mkdir()
    result=run_job(work,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        inputs=[dict(name='capture_evidence',kind='parquet',path=str(stage/'captures.parquet'))],
        steps=[dict(name='good_fetches',sql=(ROOT/'model/sql/good-fetches.sql').read_text())],outputs=[],
        queries=[dict(name='rows',sql='SELECT count(*) AS n FROM good_fetches')])
    assert result['rows']==[{'n':0}]
