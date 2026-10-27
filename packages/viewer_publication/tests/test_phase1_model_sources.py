"""Raw-shaped source evidence precedes the source identity and naming SQL."""
import json
import os
from pathlib import Path

from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets

ROOT=Path(__file__).parents[3]


def test_native_sources_preserve_names_member_paths_imports_and_failed_urls(tmp_path):
    from viewer_publication.archive_model import source_steps,registry_inputs
    def capture(index,**values):
        return dict(receipt_key='receipts/documents/2026-10-20/run.gz',receipt_line=index,capture_index=0,
            body_hex='a'*64,run_id='live',mode='fetch',url='https://fixture.test/a',
            requested_url='https://fixture.test/a',context_url='https://fixture.test/a',member_path=None,
            h_content_disposition=None,retrieved_at='2026-10-20T12:00:00Z',format='pdf',
            is_real_file=True,record_role='document',**values)
    rows=[]
    for index,name in [(1,'one.pdf'),(2,'two.pdf')]:
        row=capture(index);row['h_content_disposition']='attachment; filename="'+name+'"';rows.append(row)
    row=capture(3);row.update(url='https://fixture.test/mirror.pdf',context_url='https://fixture.test/mirror.pdf',retrieved_at='2026-10-19T12:00:00Z');rows.append(row)
    row=capture(4);row.update(body_hex=None,url='https://fixture.test/failed.pdf',is_real_file=False,record_role=None);rows.append(row)
    for index,path in [(5,'a/report.pdf'),(6,'b/report.pdf')]:
        row=capture(index);row.update(body_hex='b'*64,url='https://fixture.test/package.zip',context_url='https://fixture.test/package.zip',member_path=path);rows.append(row)
    row=capture(7);row.update(body_hex='c'*64,run_id='legacy-import',url='https://fixture.test/import.pdf',context_url='https://fixture.test/import.pdf');rows.append(row)
    row=capture(8);row.update(body_hex='d'*64,mode='retained_import',url='https://fixture.test/recovered.pdf',context_url='https://fixture.test/recovered.pdf',is_real_file=False);rows.append(row)
    inputs=registry_inputs(tmp_path/'registries')
    inputs=[x for x in inputs if x['name']!='import_runs']
    inputs.append(json_input(tmp_path,'import_runs',[dict(run_id='legacy-import',date='2026-10-10')],run_id='Utf8',date='Utf8'))
    inputs.append(json_input(tmp_path,'fixture_captures',rows,receipt_key='Utf8',receipt_line='Int32',capture_index='Int32',
        body_hex='Utf8',run_id='Utf8',mode='Utf8',url='Utf8',requested_url='Utf8',context_url='Utf8',member_path='Utf8',
        h_content_disposition='Utf8',retrieved_at='Utf8',format='Utf8',is_real_file='Boolean',record_role='Utf8'))
    inputs.append(json_input(tmp_path,'current_recoveries',[dict(id='recovered',original_url='https://fixture.test/dead.pdf',
        recovered_filename='dead-original.pdf',kind='recovered_document'),dict(id='failed-recovery',original_url='https://fixture.test/failed.pdf',recovered_filename='failed.pdf',kind='recovered_document')],id='Utf8',original_url='Utf8',recovered_filename='Utf8',kind='Utf8'))
    steps=[dict(name='capture_evidence',sql="SELECT receipt_key,receipt_line,capture_index,run_id,mode,url,requested_url,context_url,member_path,h_content_disposition,retrieved_at,format,decode(body_hex,'hex') AS sha256 FROM fixture_captures"),
        dict(name='record_roles',sql='SELECT receipt_key,receipt_line,capture_index,is_real_file,record_role FROM fixture_captures')]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=steps+source_steps(),outputs=[],queries=[
            dict(name='files',sql='SELECT filename,source_url,body_sha,is_real_file,cast(first_fetched AS VARCHAR) AS first_fetched,cast(in_archive_since AS VARCHAR) AS in_archive_since FROM source_files ORDER BY filename'),
            dict(name='members',sql="SELECT count(*) AS n FROM capture_sources WHERE source_url IS NULL AND member_path IS NOT NULL"),
            dict(name='ids',sql="SELECT count(*) AS n FROM source_files WHERE source_id<>encode(sha256(json_array(CASE WHEN body_sha IS NOT NULL THEN 'bodies/sha256/'||substr(body_sha,1,2)||'/'||body_sha||'.gz' END,filename,source_url)),'hex')")])

    assert len(result['files'])==7
    files={x['filename']:x for x in result['files']}
    assert set(files)=={'one.pdf','two.pdf','mirror.pdf','failed.pdf','report.pdf','import.pdf','dead-original.pdf'}
    assert files['one.pdf']['source_url']=='https://fixture.test/a'
    assert files['two.pdf']['body_sha']=='a'*64
    assert files['report.pdf']['source_url'] is None and files['report.pdf']['body_sha']=='b'*64
    assert files['failed.pdf']['body_sha'] is None and files['failed.pdf']['is_real_file'] is False
    assert files['dead-original.pdf']['body_sha'] is None and files['dead-original.pdf']['is_real_file'] is False
    assert files['import.pdf']['first_fetched'] is None and files['import.pdf']['in_archive_since']=='2026-10-10'
    assert files['mirror.pdf']['first_fetched'].startswith('2026-10-19')
    assert result['members']==[dict(n=2)] and result['ids']==[dict(n=0)]
