"""Final owner exceptions: expected scalar evidence before implementation."""
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from test_captures_ingest import body, ingest
from test_captures_narrow import NARROW_COLUMNS


def test_approved_schema_names_order_and_original_field_ids():
    schema=json.loads((Path(__file__).resolve().parents[3]/'model/lake/captures.schema.json').read_text())
    assert [f['name'] for f in schema['fields']]==NARROW_COLUMNS
    fields={f['name']:f for f in schema['fields']}
    assert fields['outcome']['required'] is False
    # ct-tx7u: declared field IDs match the positional IDs create_table assigns on the real lake table.
    assert {k:fields[k]['id'] for k in ('expansion','sniffed_format','sniff_version','intact','writer_job','writer_commit','attempt','fetch_http_status','fetch_outcome','mapping_version','original_path')}==dict(
        expansion=27,sniffed_format=24,sniff_version=25,intact=26,writer_job=37,writer_commit=38,attempt=14,fetch_http_status=17,fetch_outcome=18,
        mapping_version=39,original_path=12)
    # Added to a populated table, so optional in the schema; the generation guard requires mapping_version.
    assert fields['mapping_version']['required'] is False and fields['original_path']['required'] is False


def test_entry_readings_and_root_writer_repeat_without_inventing_older_readings(tmp_path):
    source=dict(writer=dict(job='capture',commit='a'*40,lockfile_digest='excluded-'*10000),
        http_status=200,outcome='saved',captures=[
            body(sniffed_format='pdf',sniff_version='v1',intact=False),
            body(sniffed_format='pdf',sniff_version='v1',intact=True),body()])
    stage=ingest(tmp_path,[source])
    table=pq.read_table(stage/'captures.parquet');rows=table.to_pylist()
    assert [(r['sniffed_format'],r['sniff_version'],r['intact']) for r in rows]==[
        ('pdf','v1',False),('pdf','v1',True),(None,None,None)]
    assert {(r['writer_job'],r['writer_commit']) for r in rows}=={('capture','a'*40)}
    assert table.schema.field('intact').type==pa.bool_()


def test_legacy_completeness_boundary_and_explicit_entry_precedence(tmp_path):
    rows=[dict(record=dict(outcome=outcome),captures=[dict(body(),bytes=size,**entry)])
        for outcome,size,entry in [('saved',123,{}),('saved',62<<20,{}),('saved',64<<20,{}),
        ('request_failed',123,{}),('resource_limit',123,{}),('saved',64<<20,dict(complete=True)),
        ('saved',123,dict(complete=False))]]
    stage=ingest(tmp_path,rows+[dict(mode='fetch',record={})])
    assert pq.read_table(stage/'captures.parquet')['complete'].to_pylist()==[
        True,True,False,False,False,True,False,True]


@pytest.mark.parametrize('prefix',[[],[0],['0']])
def test_prior_pointer_does_not_borrow_final_complete_or_confirm_cutoff(tmp_path,prefix):
    source=dict(record=[dict(http_status=200,outcome='saved',complete=False)] if prefix else
        dict(http_status=200,outcome='saved',complete=False),captures=[
            dict(body(),bytes=64<<20,pointer=prefix+['prior_attempts',0,'content','body']),
            body(pointer=prefix+['content','body'])])
    stage=ingest(tmp_path,[source]);rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['attempt'] for r in rows]==[1,0]
    assert [r['complete'] for r in rows]==[None,False]
    assert [r['http_status'] for r in rows]==[None,200]
    assert [r['outcome'] for r in rows]==[None,'stored']
    assert [r['fetch_http_status'] for r in rows]==[200,200]
    assert [r['fetch_outcome'] for r in rows]==['stored','stored']


@pytest.mark.parametrize('error',['missing',None,{},'failure'])
def test_cutoff_requires_explicit_false_and_respects_generic_error_presence(tmp_path,error):
    record=dict(http_status=200,outcome='saved')
    if error != 'missing':record['error']=error
    stage=ingest(tmp_path,[dict(record=record,captures=[dict(body(),bytes=64<<20,complete=False)]),
        dict(record=dict(http_status=200,outcome='saved'),captures=[dict(body(),bytes=64<<20)]),
        dict(record=dict(http_status=200,outcome='saved'),captures=[dict(body(),bytes=64<<20,complete=False),
            body(complete=True)])])
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['outcome'] for r in rows]==['size_limit' if error in ('missing',None) else 'stored','stored','stored','stored']


def test_expansion_inference_is_local_to_retained_member_attempt_and_context(tmp_path):
    source=dict(record=dict(url='https://example.test/final'),captures=[
        body(attempt=0,context_url='a'),body(attempt=0,context_url='a',member_path='a.pdf'),
        body(attempt=0,context_url='b'),dict(body(attempt=0,context_url='b',member_path='absent.pdf'),sha256=None),
        body(attempt=1,context_url='a'),
        body(attempt=1,context_url='c'),body(attempt=1,context_url='c',member_path='c.pdf'),
        body(attempt=0,context_url='a',expansion='encrypted_member')])
    stage=ingest(tmp_path,[source]);rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['expansion'] for r in rows]==['expanded',None,None,None,None,'expanded',None,'encrypted_member']
    assert [r['fetch_outcome'] for r in rows]==['stored']*8


def test_batch_record_captures_extended_prior_attempts_and_intra_item_fetch_consistency(tmp_path):
    import os
    from docspec_client.client import NativeDatasets
    from congress_api.lake.capture_staging import stage_captures
    from test_captures_ingest import files
    config=json.loads(Path(os.environ['DOCSPEC_JOB_CONFIG']).read_text())
    # This config moves to tmp_path, so a binary named relative to the original must be resolved first.
    config['binary']=str((Path(os.environ['DOCSPEC_JOB_CONFIG']).parent/config['binary']).resolve())
    limits=tmp_path/'tight-limits.json'
    limits.write_text(json.dumps(dict(compute_threads=2,memory_bytes=512<<20,scratch_bytes=256<<20,
        batch_rows=2,max_batch_bytes=4<<20,max_metadata_bytes=8<<20)))
    rt=tmp_path/'tight-runtime.json'
    rt.write_text(json.dumps({**config,'limits':str(limits),'workspace':str(tmp_path/'ws')}))
    engine=NativeDatasets.from_config(rt)
    batch_line=dict(
        record=dict(captures=[dict(status_code=200,complete=True) for _ in range(20)]),
        file_references=[body(http_status=200,pointer=['captures',i,'path']) for i in range(20)],
    )
    list_caps_line=dict(
        record=[dict(url='https://example.test/list-cap',captures=[dict(http_status=200,complete=True)])],
        file_references=[
            body(pointer=[0,'captures',0,'path']),
            body(pointer=['record',0,'captures',0,'path']),
        ],
    )
    nine_priors_line=dict(
        record=dict(
            url='https://example.test/nine-priors',
            http_status=200,
            outcome='stored',
            complete=True,
            prior_attempts=[dict(http_status=500+i,outcome='failed',complete=False) for i in range(9)],
        ),
        captures=[
            body(pointer=['prior_attempts',8,'body']),
            body(pointer=['content','body'],complete=True),
        ],
    )
    entry_status_broadcast_line=dict(
        record=dict(url='https://example.test/entry-broadcast'),
        captures=[
            body(attempt=1,http_status=503,complete=False),
            body(attempt=0,http_status=200,complete=True),
        ],
    )
    bodiless_final_line=dict(
        record=dict(url='https://example.test/bodiless-final',http_status=200,outcome='saved'),
        captures=[
            body(attempt=1,http_status=200,complete=True),
            dict(body(attempt=0,complete=False),sha256=None),
        ],
    )
    stage=stage_captures(
        files(tmp_path/'input',[batch_line,list_caps_line,nine_priors_line,entry_status_broadcast_line,bodiless_final_line]),
        engine=engine,work=tmp_path/'stage')
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    by_line={line:[r for r in rows if r['receipt_line']==line] for line in range(1,6)}
    assert len(by_line[1])==20 and {r['http_status'] for r in by_line[1]}=={200}
    assert {r['fetch_http_status'] for r in by_line[1]}=={200} and {r['fetch_outcome'] for r in by_line[1]}=={'stored'}
    assert [(r['http_status'],r['complete'],r['fetch_http_status'],r['fetch_outcome']) for r in by_line[2]]==[(200,True,200,'stored')]*2
    assert [(r['attempt'],r['http_status'],r['outcome'],r['fetch_http_status'],r['fetch_outcome']) for r in by_line[3]]==[
        (9,508,'failed',200,'stored'),(0,200,'stored',200,'stored')]
    assert [(r['attempt'],r['http_status'],r['fetch_http_status'],r['fetch_outcome']) for r in by_line[4]]==[
        (1,503,200,'stored'),(0,200,200,'stored')]
    assert [(r['attempt'],r['outcome'],r['fetch_http_status'],r['fetch_outcome']) for r in by_line[5]]==[
        (1,'stored',200,'failed'),(0,'failed',200,'failed')]


@pytest.mark.parametrize('verdict',[True,False])
def test_older_explicit_pdf_checks_stay_unchecked_without_new_writer_identity(tmp_path,verdict):
    stage=ingest(tmp_path,[dict(record=dict(http_status=200,outcome='saved',retrieved_at='2026-10-02T00:00:00Z'),
        captures=[body(sniffed_format='pdf',sniff_version='old',intact=verdict)])])
    [row]=pq.read_table(stage/'captures.parquet').to_pylist()
    assert row['intact'] is None
    assert row['writer_job'] is None and row['writer_commit'] is None


@pytest.mark.parametrize('line',[
    dict(record=dict(url='https://example.test/disagree'),captures=[
        body(attempt=0,http_status=200),
        body(attempt=0,http_status=503),
    ]),
    dict(record=dict(url='https://example.test/cap-disagree',captures=[
        dict(status_code=200),
        dict(status_code=503),
    ]),file_references=[
        body(pointer=['captures',0,'path']),
        body(pointer=['captures',1,'path']),
    ]),
    dict(record=dict(url='https://example.test/prior-error-stored',http_status=200,outcome='stored',
        prior_attempts=[dict(outcome='stored',error_type='read_timeout')]),
        captures=[body(pointer=['prior_attempts',0,'body']),body(pointer=['content','body'])]),
    dict(record=dict(url='https://example.test/prior-403-stored',http_status=200,outcome='stored',
        prior_attempts=[dict(outcome='stored',http_status=403)]),
        captures=[body(pointer=['prior_attempts',0,'body']),body(pointer=['content','body'])]),
    dict(record=dict(url='https://example.test/final-error-stored',http_status=200,outcome='stored',
        error_type='read_timeout'),captures=[body(pointer=['content','body'])]),
    dict(record=dict(url='https://example.test/final-403-stored',http_status=403,outcome='stored'),
        captures=[body(pointer=['content','body'])]),
    dict(record=dict(url='https://example.test/same-attempt-status-disagree',http_status=200),
        captures=[body(attempt=1,http_status=200),body(attempt=1,http_status=503),body(attempt=0,http_status=200)]),
    dict(record=dict(url='https://example.test/same-attempt-complete-disagree',http_status=200),
        captures=[body(attempt=1,http_status=200,complete=True),body(attempt=1,http_status=200,complete=False),body(attempt=0,http_status=200,complete=True)]),
    dict(record=dict(url='https://example.test/cap-null-fail',captures=[
        dict(status_code=200,outcome='stored'),
        dict(outcome='failed',error_type='read_timeout'),
    ]),file_references=[
        body(pointer=['captures',0,'path']),
        body(pointer=['captures',1,'path']),
    ]),
])
def test_contradictory_attempt_and_fetch_facts_refuse_staging(tmp_path,line):
    with pytest.raises(ValueError,match='conflicting attempt facts'):
        ingest(tmp_path,[line])
    assert not (tmp_path/'stage/captures.parquet').exists()


def test_bodiless_prior_capture_entry_agrees_with_generation_guard(tmp_path):
    import os
    from docspec_client.client import NativeDatasets
    from congress_api.lake.capture_backfill_guard import validate_generation
    key='receipts/documents/2026-10-20/bodiless-prior.jsonl.gz'
    stage=ingest(tmp_path,[
        dict(run_id='run',record=dict(url='https://example.test/bodiless-prior',http_status=200,outcome='stored'),
            captures=[
                dict(body(attempt=1),sha256=None),
                body(attempt=0,complete=True),
            ]),
        dict(run_id='run',record=dict(url='https://example.test/bodiless-final-stored',http_status=200,outcome='stored'),
            captures=[dict(body(attempt=0,complete=False),sha256=None)]),
        dict(run_id='run',record=dict(url='https://example.test/bodiless-line-stored',http_status=200,outcome='stored'),
            captures=[]),
    ],key=key)
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [(r['receipt_line'],r['attempt'],r['outcome'],r['fetch_outcome'],r['sha256'] is None) for r in rows]==[
        (1,1,'failed','stored',True),(1,0,'stored','stored',False),
        (2,0,'failed','failed',True),(3,0,'failed','failed',True)]
    report=validate_generation(
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        work=tmp_path/'guard',
        pin=stage/'captures.parquet',
        counts=[dict(key=key,expected_captures=4)],
    )
    assert report['status']=='validated' and report['violations']==0


def test_zyte_provider_envelope_previous_receipt_and_unaddressed_containers(tmp_path):
    provider_line=dict(
        record=dict(url='https://example.test/zyte-410',http_status=410,outcome='failed'),
        file_references=[
            body(http_status=200,pointer=['provider_response','raw_path']),
            body(http_status=410,pointer=['raw_path']),
        ],
    )
    list_provider_line=dict(
        record=[dict(url='https://example.test/list-zyte-404')],
        file_references=[
            body(http_status=200,pointer=[0,'prior','provider_response','raw_path']),
            body(http_status=404,pointer=[0,'prior','raw_path']),
        ],
    )
    previous_receipt_line=dict(
        record=dict(url='https://example.test/followup-520'),
        file_references=[
            body(http_status=200,pointer=['previous_receipt','raw_path']),
            body(http_status=520,pointer=['provider_response','raw_path']),
        ],
    )
    container_line=dict(
        record=dict(source_file='wayback/report.json'),
        captures=[
            body(http_status=200,pointer=['results',0,'raw','path']),
            body(http_status=429,pointer=['results',1,'raw','path']),
        ],
    )
    stage=ingest(tmp_path,[provider_line,list_provider_line,previous_receipt_line,container_line])
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    by_line={line:[r for r in rows if r['receipt_line']==line] for line in range(1,5)}
    assert [(r['attempt'],r['http_status'],r['outcome'],r['fetch_http_status'],r['fetch_outcome']) for r in by_line[1]]==[
        (0,410,'failed',410,'failed'),(0,410,'failed',410,'failed')]
    assert [(r['attempt'],r['http_status'],r['outcome'],r['fetch_http_status'],r['fetch_outcome']) for r in by_line[2]]==[
        (0,404,'failed',404,'failed'),(0,404,'failed',404,'failed')]
    assert [(r['attempt'],r['http_status'],r['outcome'],r['fetch_http_status'],r['fetch_outcome']) for r in by_line[3]]==[
        (1,200,'stored',520,'failed'),(0,520,'failed',520,'failed')]
    assert [(r['attempt'],r['http_status'],r['outcome'],r['fetch_http_status'],r['fetch_outcome']) for r in by_line[4]]==[
        (0,200,'stored',200,'stored'),(0,429,'retry_later',429,'retry_later')]
