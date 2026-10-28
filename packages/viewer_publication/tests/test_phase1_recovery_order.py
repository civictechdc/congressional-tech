"""The public recovery ordinal follows preference, time, body and receipt tie-breaks."""
import os
from pathlib import Path

from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets

ROOT=Path(__file__).parents[3]


def test_native_recovery_export_preserves_saved_recovery_preference(tmp_path):
    rows=[dict(component='component',id=str(i),receipt_key=key,receipt_line=1,capture_index=0,
        original_url='https://fixture.test/original',kind=kind,body_sha=body*64,bytes=100,
        imported_at=stamp,recovered_url='https://fixture.test/copy',identity_note=None)
        for i,(key,kind,body,stamp) in enumerate([
            ('a','requested_content_in_official_hearing','a','2026-10-27T12:00:00Z'),
            ('z','recovered_document','b','2026-10-25T12:00:00Z'),
            ('y','recovered_document','c','2026-10-26T12:00:00Z')])]
    fields={name:'Utf8' for name in ['component','id','receipt_key','original_url','kind','body_sha','imported_at','recovered_url','identity_note']}
    fields.update(receipt_line='Int32',capture_index='Int32',bytes='Int64')
    inputs=[json_input(tmp_path,'final_recovery_attachments',rows,**fields),
        json_input(tmp_path,'document_identities',[dict(component='component',document_id='d'*64)],component='Utf8',document_id='Utf8'),
        json_input(tmp_path,'body_evidence',[dict(body_sha=c*64,suffix='.gz') for c in ['a','b','c']],body_sha='Utf8',suffix='Utf8')]
    reports=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,steps=[
        dict(name='saved_recoveries',sql=(ROOT/'model/sql/saved-recoveries.sql').read_text(),materialize=True),
        dict(name='recovery_input',sql=(ROOT/'model/sql/document-recovery-input.sql').read_text(),materialize=True)],outputs=[],queries=[
            dict(name='ordered',sql='SELECT kind,recovered_url,encode(body,\'hex\') AS body FROM recovery_input ORDER BY recovery_key')])
    assert [r['body'] for r in reports['ordered']]==['c'*64,'b'*64,'a'*64]
