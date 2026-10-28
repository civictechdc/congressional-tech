"""Pinned body facts and page contexts must work on the narrow capture schema."""
import os

from congress_api.retention.provenance import json_input,list_of,struct,run_job
from docspec_client.client import NativeDatasets


def test_pinned_evidence_and_page_contexts_do_not_borrow_capture_parser_fields(tmp_path):
    from viewer_publication.archive_model import evidence_steps,registry_inputs
    capture_fields=dict(receipt_key='Utf8',receipt_line='Int32',capture_index='Int32',run_id='Utf8',mode='Utf8',
        outcome='Utf8',family='Utf8',requested_url='Utf8',url='Utf8',context_url='Utf8',member_path='Utf8',
        http_status='Int32',complete='Boolean',retrieved_at='Utf8',body_hex='Utf8',bytes='Int64',media_type='Utf8',
        fidelity='Utf8',stored_suffix='Utf8',stored_bytes='Int64',stored_md5='Utf8')
    def capture(index,body,url,**changes):
        return dict(dict(receipt_key='receipt',receipt_line=index,capture_index=0,run_id='run',mode='fetch',outcome='stored',
            family='documents',requested_url=url,url=url,context_url=url,member_path=None,http_status=200,complete=True,
            retrieved_at='2026-10-20T12:00:00Z',body_hex=body*64,bytes=1000,media_type=None,fidelity='exact',
            stored_suffix='.gz',stored_bytes=100,stored_md5='0'*32),**changes)
    rows=[capture(1,'a','https://fixture.test/checked.pdf'),capture(2,'b','https://fixture.test/unchecked.pdf'),
        capture(3,'c','https://fixture.test/one/page'),capture(4,'c','https://fixture.test/one/page',retrieved_at='2026-10-21T12:00:00Z'),
        capture(5,'c','https://fixture.test/two/page'),capture(6,'c','https://fixture.test/bad/page',http_status=503),
        capture(7,'d','https://fixture.test/failed-reading')]
    links_type=list_of(struct(**{name:'Utf8' for name in ['href','text','tag','basis','group_path','doc_type','add_date','publish_date','remove_date']}))
    reading_fields=dict(body_hex='Utf8',parser='Utf8',parser_version='Utf8',status='Utf8',error_type='Utf8',format='Utf8',
        intact='Boolean',xml_root='Utf8',title='Utf8',heading='Utf8',text_head='Utf8',text_bytes='Int32',link_count='Int32',
        link_text_bytes='Int32',content_date='Utf8',named_meetings=list_of('Int64'),base_href='Utf8',links=links_type,fingerprint_hex='Utf8')
    readings=[dict(body_hex=body*64,parser='sniff',parser_version='sniff-1',status='completed',format=kind,intact=intact)
        for body,kind,intact in [('a','pdf',False),('b','pdf',None),('c','html',None),('d','html',None)]]
    readings.extend([dict(body_hex='c'*64,parser='html',parser_version='html-1',status='completed',title='Retained page',
        text_bytes=1000,text_head='A substantive document.',link_count=1,link_text_bytes=3,base_href=None,
        fingerprint_hex='f'*64,links=[dict(href='report.pdf',text='PDF',group_path='item/1')]),
        dict(body_hex='c'*64,parser='html',parser_version='old',status='completed',title='Wrong old version',links=[]),
        dict(body_hex='d'*64,parser='html',parser_version='html-1',status='size_limit',error_type='stored_size_limit',links=[])])
    inputs=registry_inputs(tmp_path/'registries')+[
        json_input(tmp_path,'capture_rows',rows,**capture_fields),json_input(tmp_path,'reading_rows',readings,**reading_fields),
        json_input(tmp_path,'parser_versions',[dict(parser=p,version=p+'-1') for p in ['sniff','html','xml','json']],parser='Utf8',version='Utf8'),
        json_input(tmp_path,'verification_records',[dict(key='bodies/sha256/aa/'+'a'*64+'.pdf',size=1000,
            intact=True,sha256_verified=True,checked_at='2026-10-21T12:00:00Z')],key='Utf8',size='Int64',intact='Boolean',
            sha256_verified='Boolean',checked_at='Utf8')]
    steps=[dict(name='captures',sql="SELECT *,decode(body_hex,'hex') AS sha256 FROM capture_rows"),
        dict(name='readings',sql="SELECT *,decode(body_hex,'hex') AS body_sha,decode(fingerprint_hex,'hex') AS fingerprint FROM reading_rows")]
    reports=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=steps+evidence_steps(),outputs=[],queries=[
            dict(name='bodies',sql='SELECT body_sha,format,intact_basis,suffix,stored_size FROM body_evidence ORDER BY body_sha'),
            dict(name='roles',sql='SELECT receipt_line,record_role,is_real_file FROM record_roles ORDER BY receipt_line'),
            dict(name='contexts',sql='SELECT context_url,cast(cast(first_good_at AS DATE) AS VARCHAR) AS first_good_date FROM page_contexts ORDER BY context_url'),
            dict(name='links',sql='SELECT context_url,href,link_index FROM link_inputs ORDER BY context_url')])
    assert reports['bodies']==[dict(body_sha='a'*64,format='pdf',intact_basis='copy',suffix='.pdf',stored_size=1000),
        dict(body_sha='b'*64,format='pdf',intact_basis='unchecked',suffix='.gz',stored_size=100),
        dict(body_sha='c'*64,format='html',intact_basis='unchecked',suffix='.gz',stored_size=100),
        dict(body_sha='d'*64,format='html',intact_basis='unchecked',suffix='.gz',stored_size=100)]
    assert reports['roles']==[dict(receipt_line=i,record_role='document' if i<7 else None,is_real_file=i<6) for i in range(1,8)]
    assert reports['contexts']==[dict(context_url='https://fixture.test/'+part+'/page',first_good_date='2026-10-20') for part in ['one','two']]
    assert reports['links']==[dict(context_url='https://fixture.test/'+part+'/page',href='report.pdf',link_index=0) for part in ['one','two']]
