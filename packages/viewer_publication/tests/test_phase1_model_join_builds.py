"""Wide model records stream through joins with narrow evidence build sides."""
import os
from pathlib import Path

from congress_api.retention.provenance import json_input, run_job
from docspec_client.client import NativeDatasets

ROOT = Path(__file__).resolve().parents[3]


def test_body_and_capture_evidence_do_not_build_wide_preserved_rows(tmp_path):
    inputs = [
        json_input(tmp_path, 'capture_rows', [dict(body='a'*64, bytes=1000, stored_suffix='.gz', stored_bytes=100)],
                   body='Utf8', bytes='Int64', stored_suffix='Utf8', stored_bytes='Int64'),
        json_input(tmp_path, 'sniff_rows', [dict(body='a'*64, format='pdf', intact=True, intact_basis='read', error_type=None)],
                   body='Utf8', format='Utf8', intact='Boolean', intact_basis='Utf8', error_type='Utf8'),
        json_input(tmp_path, 'admission_rows', [], body='Utf8', format='Utf8'),
        json_input(tmp_path, 'copy_rows', [], body_sha='Utf8', intact='Boolean'),
        json_input(tmp_path, 'storage_rows', [], key='Utf8', size='Int64'),
        json_input(tmp_path, 'conflict_rows', [], body_sha='Utf8'),
    ]
    steps = [
        dict(name='captures', sql="SELECT *,decode(body,'hex') AS sha256,cast(NULL AS BOOLEAN) AS intact FROM capture_rows"),
        dict(name='sniff_facts', sql="SELECT * EXCLUDE(body),decode(body,'hex') AS body_sha FROM sniff_rows"),
        dict(name='body_admissions', sql="SELECT decode(body,'hex') AS body_sha,format FROM admission_rows"),
        dict(name='copy_verifications', sql='SELECT * FROM copy_rows'),
        dict(name='storage_verifications', sql='SELECT * FROM storage_rows'),
        dict(name='verification_conflicts', sql='SELECT * FROM conflict_rows'),
    ]
    for name in ['body_evidence', 'capture_evidence']:
        steps.append(dict(name=name, sql=(ROOT/'model/sql'/name.replace('_','-')).with_suffix('.sql').read_text()))
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        report = run_job(tmp_path/'job', engine, inputs=inputs, steps=steps, outputs=[], queries=[
            dict(name='body_plan', sql='EXPLAIN SELECT * FROM body_evidence'),
            dict(name='capture_plan', sql='EXPLAIN SELECT * FROM capture_evidence'),
            dict(name='facts', sql='SELECT body_sha,format,stored_size FROM body_evidence'),
        ])
    assert report['facts'] == [dict(body_sha='a'*64, format='pdf', stored_size=100)]
    for query in ['body_plan','capture_plan']:
        plan=next(row['plan'] for row in report[query] if row['plan_type']=='physical_plan')
        lines=plan.splitlines()
        joins=[i for i,line in enumerate(lines) if 'HashJoinExec:' in line]
        assert joins, plan
        for i in joins:
            first=lines[i+1];indent=len(first)-len(first.lstrip());build=[first]
            for line in lines[i+2:]:
                if len(line)-len(line.lstrip())<=indent:break
                build.append(line)
            # Both preserved inputs grow with corpus size. They must be the
            # streamed side rather than retained in each hash reservation.
            assert not any('original_size' in line or 'stored_suffix' in line for line in build), '\n'.join(build)


def test_content_and_locator_signals_build_only_small_rule_inputs(tmp_path):
    import re
    inputs=[
        json_input(tmp_path,'page_rows',[dict(body='a'*64,status='completed',xml_root='document',
            title='Report',heading='Report',text_head='Substantive report',text_bytes=1000,
            link_count=0,link_text_bytes=0)],body='Utf8',status='Utf8',xml_root='Utf8',title='Utf8',
            heading='Utf8',text_head='Utf8',text_bytes='Int64',link_count='Int64',link_text_bytes='Int64'),
        json_input(tmp_path,'capture_locators',[dict(url='https://fixture.test/report.pdf',member_path=None)],
            url='Utf8',member_path='Utf8'),
        json_input(tmp_path,'page_signals',[
            dict(id='near_empty',kind='threshold',pattern=None,number=100),
            dict(id='listing_links',kind='threshold',pattern=None,number=5),
            dict(id='listing_percent',kind='threshold',pattern=None,number=50),
            dict(id='error',kind='error_word',pattern='captcha',number=None),
            dict(id='api',kind='api_endpoint',pattern='/api/',number=None)],
            id='Utf8',kind='Utf8',pattern='Utf8',number='Int64'),
        json_input(tmp_path,'file_shapes',[dict(pattern='[.]pdf$')],pattern='Utf8')]
    steps=[dict(name='page_facts',sql="SELECT * EXCLUDE(body),decode(body,'hex') AS body_sha FROM page_rows")]
    for name in ['body_signals','locator_signals']:
        steps.append(dict(name=name,sql=(ROOT/'model/sql'/name.replace('_','-')).with_suffix('.sql').read_text()))
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        report=run_job(tmp_path/'job',engine,inputs=inputs,steps=steps,outputs=[],queries=[
            dict(name='body_plan',sql='EXPLAIN SELECT * FROM body_signals'),
            dict(name='locator_plan',sql='EXPLAIN SELECT * FROM locator_signals'),
            dict(name='bodies',sql='SELECT status,source_record,error_response,wrapper,feed,listing FROM body_signals'),
            dict(name='locators',sql='SELECT api,error_response,feed,file_shaped FROM locator_signals')])
    assert report['bodies']==[dict(status='completed',source_record=False,error_response=False,
        wrapper=False,feed=False,listing=False)]
    assert report['locators']==[dict(api=False,error_response=False,feed=False,file_shaped=True)]
    for query in ['body_plan','locator_plan']:
        plan=next(row['plan'] for row in report[query] if row['plan_type']=='physical_plan');lines=plan.splitlines()
        joins=[i for i,line in enumerate(lines) if 'CrossJoinExec' in line]
        assert joins,plan
        for i in joins:
            first=lines[i+1];indent=len(first)-len(first.lstrip());build=[first]
            for line in lines[i+2:]:
                if len(line)-len(line.lstrip())<=indent:break
                build.append(line)
            assert not any(re.search(r'\b(?:text_head|url)@',line) for line in build),'\n'.join(build)


def test_source_and_model_url_cross_joins_build_the_single_validation_row(tmp_path):
    from viewer_publication.archive_model import source_steps
    inputs=[json_input(tmp_path,'url_inputs',[
        dict(input_id='one',url='https://fixture.test/report'),dict(input_id='two',url=None)],
        input_id='Utf8',url='Utf8'),
        json_input(tmp_path,'url_normalized',[
            dict(url='https://fixture.test/report',base_key='fixture.test/report',error=None,still_wrapped=False),
            dict(url=None,base_key=None,error='invalid_url',still_wrapped=False)],
            url='Utf8',base_key='Utf8',error='Utf8',still_wrapped='Boolean'),
        json_input(tmp_path,'url_variants',[],canonical_url='Utf8',variant_url='Utf8')]
    model=(ROOT/'model/sql/url-keys.sql').read_text()
    source=next(step['sql'] for step in source_steps() if step['name']=='source_url_keys')
    steps=[dict(name='source_url_inputs',sql='SELECT * FROM url_inputs'),
        dict(name='source_url_normalized',sql='SELECT * FROM url_normalized'),
        dict(name='model_keys',sql=model),dict(name='source_keys',sql=source)]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        report=run_job(tmp_path/'job',engine,inputs=inputs,steps=steps,outputs=[],queries=[
            dict(name='model_plan',sql='EXPLAIN SELECT * FROM model_keys'),
            dict(name='source_plan',sql='EXPLAIN SELECT * FROM source_keys'),
            dict(name='model',sql='SELECT * FROM model_keys ORDER BY input_id'),
            dict(name='source',sql='SELECT * FROM source_keys ORDER BY input_id')])
    assert report['model']==report['source']==[
        dict(input_id='one',url='https://fixture.test/report',url_key='fixture.test/report',error=None,still_wrapped=False),
        dict(input_id='two',url=None,url_key=None,error='invalid_url',still_wrapped=False)]
    for query in ['model_plan','source_plan']:
        plan=next(row['plan'] for row in report[query] if row['plan_type']=='physical_plan');lines=plan.splitlines()
        joins=[i for i,line in enumerate(lines) if 'CrossJoinExec' in line]
        assert joins,plan
        for i in joins:
            first=lines[i+1];indent=len(first)-len(first.lstrip());build=[first]
            for line in lines[i+2:]:
                if len(line)-len(line.lstrip())<=indent:break
                build.append(line)
            first_aggregate=next((line for line in build if 'AggregateExec:' in line),'')
            assert 'gby=[]' in first_aggregate,'\n'.join(build)
