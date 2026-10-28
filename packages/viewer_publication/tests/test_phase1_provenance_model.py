"""Expected decisions and recovery attachment precede native provenance SQL."""
import os

from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets


def test_native_recovery_decisions_and_original_attachment(tmp_path):
    from viewer_publication.archive_model import registry_inputs
    from viewer_publication.archive_provenance import current_steps,attachment_steps,body_review_steps
    def capture(line,body,original,**changes):
        return dict(dict(receipt_key='receipt',receipt_line=line,capture_index=0,mode='retained_import',
            sha_hex=body*64,original_url=original,recovery_category='recovered_document',match_basis=None,
            recovered_url='https://retained.test/'+str(line),imported_at='2026-10-20T12:00:00Z',bytes=500),**changes)
    rows=[capture(1,'a','https://original.test/unique',recovery_category=None),
          capture(2,'b','https://original.test/absent',recovery_category=None,match_basis='official_document_identifier'),
          capture(3,'c','https://original.test/rejected'),
          capture(4,'d','https://original.test/unknown',recovery_category='not_registered'),
          capture(5,'e','https://original.test/editions'),
          capture(6,'f','https://original.test/mirror'),
          capture(7,'0',None),
          capture(8,'1','https://original.test/exact?A=1',recovery_category=None,match_basis='verified_archive_capture')]
    def decision(id,body,original,**changes):
        return dict(dict(id=id,body_sha256=body*64,original_url=original,recovered_filename=None,
            recovered_url='https://decision.test/'+id,kind='recovered_document',identity_note=id,
            decided_at='2026-10-20T12:00:00Z',supersedes=None),**changes)
    decisions=[decision('old','a',rows[0]['original_url']),
        decision('new','a',rows[0]['original_url'],kind='official_report_counterpart_available',supersedes='old'),
        decision('latest','a',rows[0]['original_url'],kind='requested_content_in_official_hearing',decided_at='2026-10-21T12:00:00Z'),
        decision('reject','c',rows[2]['original_url'],kind='rejected'),
        decision('category-priority','e',rows[4]['original_url'],kind='official_report_counterpart_available'),
        decision('wrong-exact','1','https://original.test/exact?a=1',kind='rejected'),
        decision('ghost','9','https://original.test/unmatched')]
    reviews=[dict(id='body-edge',target='a'*16,verdict='duplicate_of',value_json='"'+('b'*16)+'"',decided_at='2026-10-20T12:00:00Z',supersedes=None),
        dict(id='old-hide',target='a'*16,verdict='hide',value_json='null',decided_at='2026-10-20T12:00:00Z',supersedes=None),
        dict(id='withdraw',target='a'*16,verdict='withdraw',value_json='null',decided_at='2026-10-21T12:00:00Z',supersedes='old-hide')]
    inputs=registry_inputs(tmp_path/'registries')+[
        json_input(tmp_path,'raw_captures',rows,receipt_key='Utf8',receipt_line='Int32',capture_index='Int32',mode='Utf8',
            sha_hex='Utf8',original_url='Utf8',recovery_category='Utf8',match_basis='Utf8',recovered_url='Utf8',imported_at='Utf8',bytes='Int64'),
        json_input(tmp_path,'recovery_decisions',decisions,id='Utf8',body_sha256='Utf8',original_url='Utf8',recovered_filename='Utf8',
            recovered_url='Utf8',kind='Utf8',identity_note='Utf8',decided_at='Utf8',supersedes='Utf8'),
        json_input(tmp_path,'review_records',reviews,id='Utf8',target='Utf8',verdict='Utf8',value_json='Utf8',decided_at='Utf8',supersedes='Utf8'),
        json_input(tmp_path,'source_files',[
            dict(source_id='real-a',body_sha='a'*64,filename='a.pdf',source_url='https://copy.test/a',is_real_file=True),
            dict(source_id='real-b',body_sha='b'*64,filename='b.pdf',source_url='https://copy.test/b',is_real_file=True),
            dict(source_id='real-b-two',body_sha='b'*64,filename='mirror.pdf',source_url='https://copy.test/mirror',is_real_file=True),
            *[dict(source_id='original-'+str(i),body_sha=None,filename=str(i)+'.pdf',source_url=row['original_url'],is_real_file=False) for i,row in enumerate(rows,1)]],
            source_id='Utf8',body_sha='Utf8',filename='Utf8',source_url='Utf8',is_real_file='Boolean'),
        json_input(tmp_path,'source_labels',[
            dict(source_id='real-a',component='real-one'),dict(source_id='real-b',component='real-two'),dict(source_id='real-b-two',component='real-two'),
            *[dict(source_id='original-'+str(i),component='own-'+str(i)) for i in range(1,9)]],source_id='Utf8',component='Utf8'),
        json_input(tmp_path,'copy_url_keys',[
            dict(source_id='real-a',url_key='unique'),dict(source_id='real-a',url_key='editions'),dict(source_id='real-b',url_key='editions'),
            dict(source_id='real-b',url_key='mirror'),dict(source_id='real-b-two',url_key='mirror')],source_id='Utf8',url_key='Utf8')]
    steps=[dict(name='captures',sql="SELECT *,decode(sha_hex,'hex') AS sha256 FROM raw_captures")]+current_steps()
    steps.extend([
        dict(name='recovery_original_keys',sql="SELECT recovery_id,CASE receipt_line WHEN 1 THEN 'unique' WHEN 5 THEN 'editions' WHEN 6 THEN 'mirror' ELSE 'absent' END AS url_key FROM model_recovery_rows"),
        dict(name='effective_filenames',sql="SELECT DISTINCT 'recovery:'||id AS input_id,cast(receipt_line AS VARCHAR)||'.pdf' AS filename FROM model_recovery_rows")])
    reports=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=steps+attachment_steps()+body_review_steps(),outputs=[],queries=[
            dict(name='rows',sql='SELECT receipt_line,kind,decision_id,recovered_url FROM model_recovery_rows ORDER BY receipt_line'),
            dict(name='attachments',sql='SELECT receipt_line,component FROM recovery_attachments ORDER BY receipt_line'),
            dict(name='fatal',sql='SELECT receipt_line,error FROM recovery_diagnostics WHERE is_fatal ORDER BY receipt_line'),
            dict(name='reviews',sql='SELECT id FROM current_reviews ORDER BY id'),
            dict(name='edges',sql='SELECT left_node,right_node FROM body_review_edges')])
    assert reports['rows']==[
        dict(receipt_line=1,kind='requested_content_in_official_hearing',decision_id='latest',recovered_url='https://retained.test/1'),
        dict(receipt_line=2,kind='recovered_document',decision_id=None,recovered_url='https://retained.test/2'),
        dict(receipt_line=4,kind=None,decision_id=None,recovered_url='https://retained.test/4'),
        dict(receipt_line=5,kind='recovered_document',decision_id='category-priority',recovered_url='https://retained.test/5'),
        dict(receipt_line=6,kind='recovered_document',decision_id=None,recovered_url='https://retained.test/6'),
        dict(receipt_line=7,kind='recovered_document',decision_id=None,recovered_url='https://retained.test/7'),
        dict(receipt_line=8,kind='recovered_document',decision_id=None,recovered_url='https://retained.test/8')]
    assert reports['attachments']==[dict(receipt_line=i,component=c) for i,c in [(1,'real-one'),(2,'own-2'),(4,'own-4'),(5,'own-5'),(6,'real-two'),(8,'own-8')]]
    assert reports['fatal']==[dict(receipt_line=4,error='unknown_recovery_kind'),dict(receipt_line=7,error='missing_original_url')]
    assert reports['reviews']==[dict(id='body-edge')]
    assert reports['edges']==[dict(left_node='b:'+'a'*64,right_node='b:'+'b'*64)]


def test_provenance_inputs_keep_review_values_as_native_json(tmp_path):
    import json
    from viewer_publication.archive_provenance import provenance_inputs,current_steps
    path=tmp_path/'reviews.jsonl'
    records=[dict(id='kind',target='a'*16,verdict='kind_override',value=['testimony','letter'],note='retained',reviewer='fixture',decided_at='2026-10-20T12:00:00Z',supersedes=None),
             dict(id='title',target='a'*16,verdict='title_override',value='Observed title',note=None,reviewer='fixture',decided_at='2026-10-20T12:00:00Z',supersedes=None)]
    path.write_text('\n'.join(json.dumps(row,separators=(',',':')) for row in records)+'\n')
    inputs,steps=provenance_inputs(tmp_path/'inputs',review_files=[dict(key='provenance/reviews/fixture.jsonl',path=str(path))])
    reports=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=steps+current_steps()[:2],outputs=[],queries=[dict(name='reviews',sql='SELECT id,value_json,value_text,note FROM current_reviews ORDER BY id')])
    assert reports['reviews']==[dict(id='kind',value_json='["testimony","letter"]',value_text=None,note='retained'),
                                dict(id='title',value_json='"Observed title"',value_text='Observed title',note=None)]


def test_every_observed_recovery_kind_uses_the_model_classifier(tmp_path):
    """Retained category/basis samples exercise production SQL, including refusal."""
    import hashlib
    import json
    from pathlib import Path
    from viewer_publication.archive_model import registry_inputs
    from viewer_publication.archive_provenance import provenance_inputs,current_steps
    root=Path(__file__).parents[3]
    cases=json.loads((root/'model/fixtures/recovery-kind-cases.json').read_text())
    # Keep observed receipt identities and classification facts. Addresses and
    # the unknown-kind row are authored inputs, not evidence of a raw capture.
    rows=[dict(case_id=case['id'],receipt_key=case.get('receipt_key','receipts/fixtures/recovery-kinds.jsonl'),
        receipt_line=case.get('receipt_line',1),capture_index=case.get('capture_index',0),
        body_hex=case.get('body_hex') or hashlib.sha256(case['id'].encode()).hexdigest(),
        recovery_category=case['category'],match_basis=case['match_basis'],
        original_url='https://fixture.test/recovery/'+case['id'],recovered_url='https://fixture.test/copy/'+case['id'],
        imported_at='2026-10-20T12:00:00Z',bytes=case.get('bytes',1),mode='retained_import') for case in cases]
    inputs=registry_inputs(tmp_path/'registries')
    records,steps=provenance_inputs(tmp_path/'decisions');inputs+=records
    inputs.append(json_input(tmp_path,'cases',rows,**{name:'Utf8' for name in ['case_id','receipt_key','body_hex',
        'recovery_category','match_basis','original_url','recovered_url','imported_at','mode']},
        receipt_line='Int32',capture_index='Int32',bytes='Int64'))
    steps+=[dict(name='captures',sql="SELECT *,decode(body_hex,'hex') AS sha256 FROM cases")]
    reports=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=steps+current_steps(),outputs=[],queries=[
            dict(name='kinds',sql="SELECT c.case_id,r.kind FROM model_recovery_rows r JOIN cases c USING(receipt_key,receipt_line,capture_index) ORDER BY c.case_id"),
            dict(name='fatal',sql="SELECT c.case_id,d.error FROM recovery_diagnostics d JOIN cases c USING(receipt_key,receipt_line,capture_index) WHERE d.is_fatal ORDER BY c.case_id")])
    assert reports['kinds']==[dict(case_id=case['id'],kind=case['expected_kind']) for case in sorted(cases,key=lambda x:x['id'])]
    assert reports['fatal']==[dict(case_id='unknown',error='unknown_recovery_kind')]
