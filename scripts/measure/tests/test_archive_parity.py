"""Expected E4 outcomes bind native evidence matching and narrow causes."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

from congress_api.retention.provenance import json_input, list_of, run_job
from docspec_client.client import NativeDatasets

ROOT = Path(__file__).parents[3]
FIXTURE = json.loads((ROOT / 'model/fixtures/e4-parity.json').read_text())
spec = importlib.util.spec_from_file_location('archive_parity', ROOT / 'scripts/measure/archive_parity.py')
parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parity)


def engine():
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def test_each_known_cause_has_a_narrow_predicate_and_a_counterexample(tmp_path):
    rows = []
    for case in FIXTURE['causes']:
        base = dict(difference_id=case['name'], field=case['field'], subject='file',
            value=case['value'], direction=case['direction'], old_doc='old', new_doc='new',
            fact=json.dumps(case['fact']), evidence_ref='fixture:' + case['name'])
        rows.extend([base, dict(base, difference_id=case['name'] + ':unrelated', field='review_note')])
    inputs = [json_input(tmp_path, 'observed_differences', rows, difference_id='Utf8',
        field='Utf8', subject='Utf8', value='Utf8', direction='Utf8', old_doc='Utf8',
        new_doc='Utf8', fact='Utf8', evidence_ref='Utf8')]
    result = run_job(tmp_path, engine(), inputs=inputs, steps=parity.cause_steps(), outputs=[],
        queries=[dict(name='causes', sql='SELECT difference_id,cause FROM known_causes ORDER BY difference_id,cause')])
    found = {}
    for row in result['causes']:
        found.setdefault(row['difference_id'], []).append(row['cause'])
    for case in FIXTURE['causes']:
        assert found.get(case['name']) == case['expected_causes']
        assert case['name'] + ':unrelated' not in found


def test_many_to_many_alignment_preserves_merge_and_split(tmp_path):
    old = [dict(doc=r['doc'], anchor=a, identity_anchor=a) for r in FIXTURE['topology']['oracle'] for a in r['evidence']]
    new = [dict(doc=r['doc'], anchor=a, identity_anchor=a) for r in FIXTURE['topology']['candidate'] for a in r['evidence']]
    inputs = [json_input(tmp_path, name, rows, doc='Utf8', anchor='Utf8', identity_anchor='Utf8')
              for name, rows in [('old_anchors', old), ('new_anchors', new)]]
    result = run_job(tmp_path, engine(), inputs=inputs, steps=parity.alignment_steps(), outputs=[],
        queries=[dict(name='pairs', sql='SELECT old_doc,new_doc FROM aligned_pairs ORDER BY old_doc,new_doc')])
    assert result['pairs'] == [dict(old_doc=a,new_doc=b) for a,b in FIXTURE['topology']['pairs']]


def test_unchanged_evidence_sets_do_not_cross_join_shared_addresses(tmp_path):
    inputs = [json_input(tmp_path,name,[dict(doc=prefix+str(i),anchor='same body and URL',identity_anchor='source-'+str(i))
        for i in range(5)],doc='Utf8',anchor='Utf8',identity_anchor='Utf8')
        for name,prefix in [('old_anchors','old-'),('new_anchors','new-')]]
    result=run_job(tmp_path,engine(),inputs=inputs,steps=parity.alignment_steps(),outputs=[],
        queries=[dict(name='pairs',sql='SELECT old_doc,new_doc FROM aligned_pairs ORDER BY old_doc,new_doc')])
    assert result['pairs']==[dict(old_doc='old-'+str(i),new_doc='new-'+str(i)) for i in range(5)]


def test_unclassified_and_derived_only_differences_prevent_qualification():
    assert parity.decision_ready(unclassified=1, derived_only=0, invalid_ids=0, missing_evidence=0) is False
    assert parity.decision_ready(unclassified=0, derived_only=1, invalid_ids=0, missing_evidence=0) is False
    assert parity.decision_ready(unclassified=0, derived_only=0, invalid_ids=1, missing_evidence=0) is False
    assert parity.decision_ready(unclassified=0, derived_only=0, invalid_ids=0, missing_evidence=1) is False
    assert parity.decision_ready(unclassified=0, derived_only=0, invalid_ids=0, missing_evidence=0) is True


def merge_inputs(tmp_path, *, records=(), invalid_source=False):
    fixture = FIXTURE['integration']
    members, documents = fixture['members'], fixture['documents']
    old_anchors = [dict(doc=documents[i]['doc'],anchor=m['body_key'],identity_anchor=m['source_id']) for i,m in enumerate(members)]
    new_anchors = [dict(r,doc='new-ab') for r in old_anchors]
    old_fields = [dict(doc=documents[i]['doc'],field='body_keys',subject=m['body_key'],value=m['body_key']) for i,m in enumerate(members)]
    old_fields += [dict(doc=d['doc'],field='title',subject='',value='Prior title') for d in documents[:2]]
    new_fields = [dict(r,doc='new-ab') for r in old_fields if r['field']=='body_keys']
    new_fields += [dict(doc='new-ab',field='title',subject='',value='Unexpected title')]
    witnesses = [dict(old_doc=None,new_doc='new-ab',subject=m['body_key'],
        fact=json.dumps(dict(group_kind='publisher',group_id='pkg',source_url='https://www.govinfo.gov/content/pkg/CHRG-118hhrg1.zip')),
        evidence_ref='fixture:canonical-valid-rendition-members') for m in members]
    inputs = []
    for name,rows in [('old_anchors',old_anchors),('new_anchors',new_anchors)]:
        inputs.append(json_input(tmp_path,name,rows,doc='Utf8',anchor='Utf8',identity_anchor='Utf8'))
    for name,rows in [('old_fields',old_fields),('new_fields',new_fields)]:
        inputs.append(json_input(tmp_path,name,rows,doc='Utf8',field='Utf8',subject='Utf8',value='Utf8'))
    for name,rows in [('old_documents',documents[:2]),('new_documents',documents[2:])]:
        inputs.append(json_input(tmp_path,name,rows,doc='Utf8'))
    sources = [dict(side='old',doc=documents[i]['doc'],**m) for i,m in enumerate(members)]
    sources += [dict(side='new',doc='new-ab',**m) for m in members]
    if invalid_source:
        sources[-1]['source_id']=None
    inputs += [json_input(tmp_path,'identity_sources',sources,side='Utf8',doc='Utf8',source_id='Utf8',body_key='Utf8',filename='Utf8',source_url='Utf8'),
        json_input(tmp_path,'identity_documents',[dict(side='new' if d['doc']=='new-ab' else 'old',**d) for d in documents],
            side='Utf8',doc='Utf8',document_id='Utf8',body_keys=list_of('Utf8'),source_ids=list_of('Utf8')),
        json_input(tmp_path,'witnesses',witnesses,old_doc='Utf8',new_doc='Utf8',subject='Utf8',fact='Utf8',evidence_ref='Utf8'),
        json_input(tmp_path,'difference_records',list(records),difference_id='Utf8',classification='Utf8',rule_ref='Utf8',note='Utf8',raw_signal='Utf8')]
    return inputs


def test_merge_explanation_does_not_hide_an_unrelated_visible_regression(tmp_path):
    result=parity.compare_relations(merge_inputs(tmp_path),engine=engine(),work=tmp_path/'comparison')
    for key,value in FIXTURE['integration']['expected'].items():
        assert result['counts'][key]==value
    assert result['decision_ready'] is False
    assert len(result['causes'])==len(parity.CAUSES)+1
    assert [r for r in result['causes'] if r['differences']]==[
        dict(cause='document_id_inputs_changed',differences=2,unit='document_pairs'),
        dict(cause='govinfo_same_stem_groups',differences=2,unit='field_differences')]
    assert result['clusters']==[dict(field='title',direction=direction,classification=None,differences=2,with_raw_signal=0)
                                for direction in ['added','removed']]


def test_missing_identity_and_invalid_classification_records_refuse_completion(tmp_path):
    result=parity.compare_relations(merge_inputs(tmp_path,invalid_source=True,
        records=[dict(difference_id='f'*64,classification='approve_everything',note='Not a valid classification')]),
        engine=engine(),work=tmp_path/'comparison')
    assert result['counts']['invalid_ids']==1
    assert result['counts']['invalid_records']>=1
    assert result['decision_ready'] is False


def test_classified_differences_stay_listed_and_derived_only_remains_a_blocker(tmp_path):
    records=FIXTURE['integration']['difference_records']
    result=parity.compare_relations(merge_inputs(tmp_path,records=records),engine=engine(),work=tmp_path/'comparison')
    assert result['counts']['unexplained']==4
    assert result['counts']['unclassified']==0
    assert result['counts']['invalid_records']==0
    assert result['counts']['derived_only']==1
    assert result['decision_ready'] is False
    assert sum(r['with_raw_signal'] for r in result['clusters'])==1
    # A separately authored explicit decision changes the classification. It
    # does not erase the difference or invent a large-cluster threshold.
    approved=[dict(r,classification='old_pipeline_error') if r['classification']=='derived_only_fact' else r for r in records]
    sub=tmp_path/'decided';sub.mkdir()
    complete=parity.compare_relations(merge_inputs(sub,records=approved),engine=engine(),work=sub/'comparison')
    assert complete['counts']['unexplained']==4 and complete['counts']['derived_only']==0
    assert complete['decision_ready'] is True


def test_descriptor_requires_the_pinned_pair_and_actual_candidate_files(tmp_path):
    path=tmp_path/'parity-inputs.json'
    path.write_text(json.dumps(dict(version=1,oracle=dict(selector=dict(path='missing',sha256='0'*64,size=0)))))
    with pytest.raises(ValueError,match='missing|Missing'):
        parity.load_descriptor(path)
    path.write_text(json.dumps(dict(version=1,oracle=dict(selector=dict(path='missing',sha256='0'*64,size=0)),candidate=dict(kind='f0'))))
    with pytest.raises(ValueError,match='missing|Missing'):
        parity.load_descriptor(path)


def test_model_witnesses_use_native_receipt_keys_and_match_only_source_evidence(tmp_path):
    """Caption loss, HTML addition and header names use actual capture facts."""
    data=[*FIXTURE['integration']['members'],FIXTURE['witness_twin']]
    sources=[dict(receipt_key='receipts/a.jsonl',receipt_line=i,capture_index=0,source_id=m['source_id'],
        body_sha=m['body_key'].split('/')[-1][:-3],filename=m['filename'],source_url=m['source_url'],import_date=None)
        for i,m in enumerate(data)]
    captures=[dict(receipt_key=s['receipt_key'],receipt_line=s['receipt_line'],capture_index=0,
        format='vtt' if i==0 else 'html',mode='fetch',complete=True,http_status=200,outcome='stored',
        url=s['source_url'],requested_url=s['source_url'],retrieved_at='2026-10-27T00:00:00Z',
        fidelity='saved-text' if i==2 else 'exact-bytes',member_path=None,h_content_disposition='attachment; filename="capture.txt"',
        match_basis=None,original_url=None,recovered_url=None,publisher_requested=True)
        for i,s in enumerate(sources)]
    roles=[dict(receipt_key=s['receipt_key'],receipt_line=s['receipt_line'],capture_index=0,
        record_role='caption' if i==0 else 'document',is_real_file=i!=0) for i,s in enumerate(sources)]
    old=[dict(doc='old-'+str(i),source_id=s['source_id'],body_key=data[i]['body_key'],filename=s['filename'],source_url=s['source_url']) for i,s in enumerate(sources)]
    new=[dict(doc='new-'+str(i),**{k:v for k,v in r.items() if k!='doc'}) for i,r in enumerate(old)]
    old.append(dict(doc='old-0',source_id='a'*64,body_key='bodies/sha256/ee/'+'e'*64+'.gz',filename='unobserved-real.pdf',source_url='https://fixture.test/unobserved.pdf'))
    inputs=[json_input(tmp_path,'capture_sources',sources,receipt_key='Utf8',receipt_line='Int64',capture_index='Int64',
        source_id='Utf8',body_sha='Utf8',filename='Utf8',source_url='Utf8',import_date='Utf8'),
        json_input(tmp_path,'capture_evidence',captures,receipt_key='Utf8',receipt_line='Int64',capture_index='Int64',
            **{k:'Utf8' for k in ['format','mode','outcome','url','requested_url','retrieved_at','fidelity','member_path','h_content_disposition','match_basis','original_url','recovered_url']},
            complete='Boolean',http_status='Int64',publisher_requested='Boolean'),
        json_input(tmp_path,'record_roles',roles,receipt_key='Utf8',receipt_line='Int64',capture_index='Int64',record_role='Utf8',is_real_file='Boolean'),
        json_input(tmp_path,'page_facts_rows',[dict(body_sha=r['body_sha'],status='completed',fingerprint='9'*64,error_type=None) for r in sources[1:]],body_sha='Utf8',status='Utf8',fingerprint='Utf8',error_type='Utf8'),
        *[json_input(tmp_path,name,rows,doc='Utf8',source_id='Utf8',body_key='Utf8',filename='Utf8',source_url='Utf8') for name,rows in [('old_evidence_sources',old),('new_evidence_sources',new)]]]
    available={item['name']:set(f['name'] for f in item['schema']['fields']) for item in inputs}
    available['page_facts']=available.pop('page_facts_rows')
    steps,missing=parity.model_witness_steps(available)
    steps.insert(0,dict(name='page_facts',sql="SELECT decode(body_sha,'hex') AS body_sha,status,decode(fingerprint,'hex') AS fingerprint,error_type FROM page_facts_rows"))
    assert 'direct_provider_same_text' in missing  # No retry attempt was invented.
    (tmp_path/'native').mkdir()
    reports=run_job(tmp_path/'native',engine(),inputs=inputs,steps=steps,outputs=[],queries=[dict(name='witnesses',
        sql="SELECT old_doc,new_doc,subject,json_get_str(fact,'record_role') AS role,json_get_str(fact,'header_filename') AS header,json_get_str(fact,'fingerprint') AS fingerprint,json_get_str(fact,'other_fingerprint') AS other_fingerprint,evidence_ref FROM witnesses ORDER BY old_doc,new_doc,subject")])
    assert any(r['old_doc']=='old-0' and r['role']=='caption' for r in reports['witnesses'])
    assert any(r['new_doc']=='new-1' and r['role']=='document' and r['header']=='capture.txt' for r in reports['witnesses'])
    assert all(r['evidence_ref'] is None or r['evidence_ref'].startswith('receipts/a.jsonl:') for r in reports['witnesses'])
    assert all(r['role'] is None for r in reports['witnesses'] if r['old_doc']=='old-0' and r['subject']=='')
    assert any(r['fingerprint']=='9'*64 and r['other_fingerprint']=='9'*64 for r in reports['witnesses'])


def test_recovery_causes_bind_each_visible_value_to_retained_evidence(tmp_path):
    rows=[]
    for case in FIXTURE['recovery_values']:
        for variant in ['correct','wrong','null']:
            rows.append(dict(difference_id=case['field']+':'+variant,field=case['field'],subject=case['fact']['body_sha'],
                value=case['value'] if variant=='correct' else case['wrong'] if variant=='wrong' else '[null]',direction='added',old_doc='old',new_doc='new',
                fact=json.dumps(case['fact']),evidence_ref='fixture:retained-stage'))
    inputs=[json_input(tmp_path,'observed_differences',rows,**{k:'Utf8' for k in rows[0]})]
    result=run_job(tmp_path,engine(),inputs=inputs,steps=parity.cause_steps(),outputs=[],queries=[dict(name='causes',sql='SELECT difference_id,cause FROM known_causes ORDER BY difference_id')])
    assert result['causes']==[dict(difference_id=field+':correct',cause='b7_owner_recoveries') for field in ['recovery.imported_at','recovery.kind']]


def test_native_b7_witness_uses_superseding_kind_and_earliest_fetch_date(tmp_path):
    expected=FIXTURE['b7_native_expected'];pk=dict(receipt_key='Utf8',receipt_line='Int64',capture_index='Int64')
    inputs=[json_input(tmp_path,'capture_sources',[],**pk,source_id='Utf8',body_sha='Utf8',filename='Utf8',source_url='Utf8',import_date='Utf8'),
        json_input(tmp_path,'capture_evidence',[],**pk,**{k:'Utf8' for k in ['format','mode','outcome','url','requested_url','retrieved_at','fidelity','member_path','h_content_disposition']},complete='Boolean',http_status='Int64'),
        json_input(tmp_path,'record_roles',[],**pk,record_role='Utf8',is_real_file='Boolean'),
        json_input(tmp_path,'page_facts',[],body_sha='Utf8',status='Utf8',fingerprint='Utf8',error_type='Utf8')]
    source=dict(doc='new',source_id='e'*64,body_key=None,filename='original.html',source_url=expected['original_url'])
    for name,rows in [('old_evidence_sources',[]),('new_evidence_sources',[source])]:
        inputs.append(json_input(tmp_path,name,rows,doc='Utf8',source_id='Utf8',body_key='Utf8',filename='Utf8',source_url='Utf8'))
    row=dict(id='owner-57',original_url=expected['original_url'],body_sha256=expected['body_sha'],kind=expected['kind'],
        recovered_url='https://www.govinfo.gov/hearing.htm',recovered_filename=None,decided_at='2026-10-27T21:28:14Z',identity_note='Owner approved excerpt')
    schema={k:'Utf8' for k in row}
    inputs.append(json_input(tmp_path,'current_recoveries',[row],**schema))
    old=dict(row,id='superseded',kind=expected['superseded_kind'],supersedes=None)
    inputs.append(json_input(tmp_path,'b7_recovery_decisions',[old,dict(row,supersedes='superseded')],**schema,supersedes='Utf8'))
    inputs.append(json_input(tmp_path,'b7_ready_imports',[dict(original_url=row['original_url'],body_sha256=row['body_sha256'],retrieved_at=expected['ready_time'],stored_suffix='.gz',bytes=100)],original_url='Utf8',body_sha256='Utf8',retrieved_at='Utf8',stored_suffix='Utf8',bytes='Int64'))
    inputs.append(json_input(tmp_path,'b7_source_time_minima',[dict(original_url=row['original_url'],body_sha256=row['body_sha256'],retrieved_at=expected['source_minimum'])],original_url='Utf8',body_sha256='Utf8',retrieved_at='Utf8'))
    available={item['name']:set(f['name'] for f in item['schema']['fields']) for item in inputs}
    steps,missing=parity.model_witness_steps(available)
    assert 'b7_owner_recoveries' not in missing
    reports=run_job(tmp_path,engine(),inputs=inputs,steps=steps,outputs=[],queries=[dict(name='b7',sql="SELECT DISTINCT json_get_str(fact,'expected_kind') AS kind,json_get_str(fact,'expected_imported_at') AS imported_at FROM witnesses WHERE json_get_str(fact,'stage')='raw-recoveries-owner-32c13ffa'")])
    assert reports['b7']==[dict(kind=json.dumps([expected['kind']]),imported_at=json.dumps([expected['imported_at']]))]


def test_raw_link_type_is_not_a_registry_mapped_publisher_kind():
    pk={'receipt_key','receipt_line','capture_index'}
    available={'capture_sources':pk|{'source_id','body_sha','filename','source_url','import_date','document_kind'},
        'capture_evidence':pk|{'format','mode','complete','http_status','outcome','url','requested_url','retrieved_at','fidelity','member_path','h_content_disposition'},
        'record_roles':pk|{'record_role','is_real_file'},'page_facts':{'body_sha','status','fingerprint','error_type'},
        'publisher_links':{'source_id','page_body','context','text','doc_type','link_index'}}
    _,missing=parity.model_witness_steps(available)
    assert 'publisher_link_kind' in missing


@pytest.mark.parametrize('case',FIXTURE['oracle_scope_cases'],ids=lambda case:case['name'])
def test_slice_oracle_keeps_full_components_and_reports_missing_evidence(tmp_path,case):
    import pyarrow as pa
    import pyarrow.parquet as pq
    loaded=oracle_fixture(tmp_path)
    files=FIXTURE['oracle_catalog']['files']
    rows=[dict(body_sha=files[i]['body_key'].split('/')[-1][:-3],source_url=files[i]['source_url']) for i in case['source_indexes']]
    source=tmp_path/'capture-sources.parquet';pq.write_table(pa.Table.from_pylist(rows),source)
    recoveries=tmp_path/'current-recoveries.parquet';pq.write_table(pa.table(dict(original_url=pa.array([],type=pa.string()),body_sha256=pa.array([],type=pa.string()))),recoveries)
    loaded['paths'].update(capture_sources=str(source),current_recoveries=str(recoveries))
    scope=parity.select_oracle_scope(loaded,engine=engine(),work=tmp_path/'scope')
    assert {key:scope[key] for key in ['selected_documents','selected_files','outside_documents','partial_documents','missing_files']}=={key:case[key] for key in ['selected_documents','selected_files','outside_documents','partial_documents','missing_files']}
    assert pq.ParquetFile(loaded['paths']['oracle_filenames']).metadata.num_rows==case['selected_files']
    assert pq.ParquetFile(loaded['paths']['oracle_documents']).metadata.num_rows==case['selected_documents']
    assert pq.ParquetFile(tmp_path/'scope/scope-gaps.parquet').metadata.num_rows==case['missing_files']


@pytest.mark.parametrize('case',FIXTURE['member_contexts_expected'],ids=lambda case:case['case'])
def test_source_members_have_one_identity_but_preserve_distinct_member_paths(tmp_path,case):
    member=FIXTURE['integration']['members'][0];doc=FIXTURE['integration']['documents'][0]['document_id']
    row=dict(document_id=doc,list_row=0,source_id=member['source_id'],body_key=member['body_key'],effective_filename=member['filename'],source_url=member['source_url'],member_path='one/'+member['filename'])
    second=dict(row,member_path='two/'+member['filename'])
    if case['case']=='two-documents':second.update(document_id='e'*64,list_row=1)
    if case['case']=='duplicate-context':second=dict(row)
    fields={name:'Utf8' for name in row};fields['list_row']='Int32'
    inputs=[json_input(tmp_path,'source_members',[row,second],**fields)]
    reports=run_job(tmp_path,engine(),inputs=inputs,steps=[],outputs=[],queries=[dict(name='check_'+str(i),sql=sql) for i,sql in enumerate(parity.MEMBER_CHECKS)])
    assert [reports['check_'+str(i)][0]['errors'] for i in range(2)]==case['errors']


@pytest.mark.parametrize('effective_title',['Chosen title','Reading wins'])
def test_publisher_witness_uses_canonical_kind_and_the_saved_source(tmp_path,effective_title):
    expected=FIXTURE['publisher_witness_expected'];m=FIXTURE['integration']['members'][1]
    body=m['body_key'].split('/')[-1][:-3];pk=dict(receipt_key='Utf8',receipt_line='Int64',capture_index='Int64')
    source=dict(receipt_key='receipts/source',receipt_line=1,capture_index=0,source_id=m['source_id'],body_sha=body,filename=m['filename'],source_url=m['source_url'],import_date=None)
    capture=dict(receipt_key=source['receipt_key'],receipt_line=1,capture_index=0,format='pdf',mode='fetch',complete=True,http_status=200,outcome='stored',url=m['source_url'],requested_url=m['source_url'],retrieved_at='2026-10-27T12:00:00Z',fidelity='exact-bytes',member_path=None,h_content_disposition=None)
    role=dict(receipt_key=source['receipt_key'],receipt_line=1,capture_index=0,record_role='document',is_real_file=True)
    inputs=[json_input(tmp_path,'capture_sources',[source],**pk,source_id='Utf8',body_sha='Utf8',filename='Utf8',source_url='Utf8',import_date='Utf8'),
        json_input(tmp_path,'capture_evidence',[capture],**pk,**{k:'Utf8' for k in ['format','mode','outcome','url','requested_url','retrieved_at','fidelity','member_path','h_content_disposition']},complete='Boolean',http_status='Int64'),
        json_input(tmp_path,'record_roles',[role],**pk,record_role='Utf8',is_real_file='Boolean'),
        json_input(tmp_path,'page_facts',[],body_sha='Utf8',status='Utf8',fingerprint='Utf8',error_type='Utf8'),
        json_input(tmp_path,'old_evidence_sources',[],doc='Utf8',source_id='Utf8',body_key='Utf8',filename='Utf8',source_url='Utf8'),
        json_input(tmp_path,'new_evidence_sources',[dict(doc='new',**m)],doc='Utf8',source_id='Utf8',body_key='Utf8',filename='Utf8',source_url='Utf8'),
        json_input(tmp_path,'new_wide_rows',[dict(doc='new',list_row=0,filename=m['filename'],body_hex=body)],doc='Utf8',list_row='Int32',filename='Utf8',body_hex='Utf8'),
        json_input(tmp_path,'release_sources',[dict(list_row=0,url=m['source_url'],member_path=None,is_saved=True)],list_row='Int32',url='Utf8',member_path='Utf8',is_saved='Boolean'),
        json_input(tmp_path,'source_filename_readings',[dict(source_id=m['source_id'],status='completed',document_kind=[])],source_id='Utf8',status='Utf8',document_kind=list_of('Utf8')),
        json_input(tmp_path,'source_annotation_publisher',[dict(source_id=m['source_id'],document_kind=[expected['kind']],listing_title=expected['listing_title'])],source_id='Utf8',document_kind=list_of('Utf8'),listing_title='Utf8'),
        json_input(tmp_path,'source_annotations',[dict(source_id=m['source_id'],title=effective_title)],source_id='Utf8',title='Utf8'),
        json_input(tmp_path,'publisher_links',[dict(source_id=m['source_id'],page_body='a'*64,context=json.dumps([expected['listed_on'],None]),context_url=expected['listed_on'],text=expected['late_text'],doc_type=expected['raw_type'],link_index=0)],source_id='Utf8',page_body='Utf8',context='Utf8',context_url='Utf8',text='Utf8',doc_type='Utf8',link_index='Int64')]
    cases=[dict(difference_id=name,field=field,subject=subject,value=value,direction='added',old_doc=None,new_doc='new') for name,field,subject,value in [
        ('canonical-kind','document_kind','',expected['kind']),('raw-code','document_kind','',expected['raw_type']),
        ('chosen-title','title','',expected['listing_title']),('late-title','title','',expected['late_text']),
        ('page-url','source.listed_on',m['source_url'],expected['listed_on'])]]
    inputs.append(json_input(tmp_path,'case_differences',cases,**{k:'Utf8' for k in cases[0]}))
    available={item['name']:set(f['name'] for f in item['schema']['fields']) for item in inputs}
    available['new_wide']={'doc','list_row','filename','saved_body'}
    steps,missing=parity.model_witness_steps(available)
    assert 'publisher_link_kind' not in missing
    steps.insert(0,dict(name='new_wide',sql="SELECT doc,list_row,filename,decode(body_hex,'hex') AS saved_body FROM new_wide_rows",materialize=True))
    steps.append(dict(name='observed_differences',sql='SELECT d.*,w.fact,w.evidence_ref FROM case_differences d JOIN witnesses w ON d.new_doc=w.new_doc AND d.subject=w.subject',materialize=True))
    steps+=parity.cause_steps()
    reports=run_job(tmp_path,engine(),inputs=inputs,steps=steps,outputs=[],queries=[dict(name='causes',sql='SELECT DISTINCT difference_id,cause FROM known_causes ORDER BY difference_id')])
    wanted=[dict(difference_id='canonical-kind',cause='publisher_link_kind'),dict(difference_id='page-url',cause='link_label_provenance')]
    if effective_title==expected['listing_title']:wanted.insert(1,dict(difference_id='chosen-title',cause='link_label_provenance'))
    assert reports['causes']==wanted




def oracle_fixture(tmp_path):
    """Original comparison records only; never converted into a current candidate."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    data=FIXTURE['oracle_catalog']
    columns=set().union(*parity.oracle_columns(),*(row.keys() for row in data['documents']+data['files']))
    arrays=sorted(columns-
                  {'document_id','source_id','body_key','filename','source_url'})
    schema=pa.schema([(name,pa.string()) for name in ['document_id','source_id','body_key','filename','source_url']]
        +[(name,pa.list_(pa.string())) for name in arrays])
    paths={}
    for name,rows in [('documents',data['documents']),('filenames',data['files'])]:
        path=tmp_path/(name+'.parquet');pq.write_table(pa.Table.from_pylist(rows,schema=schema),path)
        paths['oracle_'+name]=str(path)
    return dict(paths=paths,selector=dict(files=dict(documents=dict(rows=len(data['documents'])))))


def producer_metadata(tmp_path):
    """Authored metadata for the metadata guard, with no data-qualification claim."""
    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_format import LIST_COLUMNS,DETAIL_COLUMNS
    order=lambda fields:[dict(field=name,direction='asc',nulls='nulls_last') for name in fields]
    outputs=[dict(name=name+'.parquet',sql='SELECT * FROM '+relation,
                  settings=dict(order_by=order(fields))) for name,relation,fields in [
        ('list','ordered',['filename','document_date','first_captured','doc_key']),
        ('detail','details',['filename','document_date','first_captured','doc_key']),
        ('sources','source_rows',['list_row','ordinal']),('recoveries','recovery_rows',['list_row','ordinal'])]]
    outputs += [dict(name='document_rows.parquet',sql='SELECT list_row,doc_key AS document_id,'+
        ','.join(LIST_COLUMNS+DETAIL_COLUMNS)+' FROM details',settings=dict(order_by=order(['list_row']))),
        dict(name='source_members.parquet',sql='SELECT * FROM members',settings=dict(order_by=order(['document_id','source_id'])))]
    facts=[dict(name=item['name'],sha256='a'*64,size=0,rows=0) for item in outputs]
    job=dict(outputs=outputs,steps=[dict(name='ordered',sql='SELECT row_number() OVER(ORDER BY filename,document_date NULLS LAST,first_captured NULLS LAST,doc_key)-1 AS list_row FROM rows')],
             queries=[dict(name='profile_completeness',sql='SELECT 0 AS missing_pages')])
    result=dict(outputs=facts,queries=[dict(name='profile_completeness',data=[dict(missing_pages=0)])])
    def write(name,value):
        path=tmp_path/name;path.write_text(json.dumps(value));return dict(path=str(path),**file_pin(path))
    candidate=dict(build_job=write('job.json',job),build_result=write('result.json',result),
                   producer_profile=write('profile.json',dict(owner='metadata-guard-fixture')))
    for name in ('document_rows','source_members'):
        candidate[name]=dict(path=str(tmp_path/(name+'.parquet')),sha256='a'*64,size=0)
    manifest=dict(files=facts[:4])
    return candidate,manifest,job,result,write


@pytest.mark.parametrize('case',FIXTURE['producer_profile_cases'],ids=lambda case:case['case'])
def test_model_profile_and_required_completeness_evidence(tmp_path,case):
    candidate,manifest,job,result,write=producer_metadata(tmp_path)
    check=result['queries'][0];name=case['case']
    if name=='missing-pin':candidate.pop('producer_profile')
    if name=='changed-profile':Path(candidate['producer_profile']['path']).write_text('{}')
    if name=='missing-check':result['queries'].remove(check)
    if name=='empty-check':check['data']=[]
    if name=='positive-count':check['data'][0]['missing_pages']=1
    if name=='null-count':check['data'][0]['missing_pages']=None
    if name=='boolean-count':check['data'][0]['missing_pages']=False
    candidate['build_result']=write('result.json',result)
    if case['accepted']:parity.producer_inputs(tmp_path,candidate,manifest)
    else:
        with pytest.raises(ValueError,match='profile|completeness|pin|digest'):
            parity.producer_inputs(tmp_path,candidate,manifest)


@pytest.mark.parametrize('table',['list.parquet','detail.parquet','sources.parquet','recoveries.parquet'])
def test_descending_writer_cannot_authenticate_ascending_row_positions(tmp_path,table):
    candidate,manifest,job,result,write=producer_metadata(tmp_path)
    next(item for item in job['outputs'] if item['name']==table)['settings']['order_by'][0]['direction']='desc'
    candidate['build_job']=write('job.json',job)
    with pytest.raises(ValueError,match='sort|order'):
        parity.producer_inputs(tmp_path,candidate,manifest)


def test_private_mapping_permutation_refuses_before_any_payload_read(tmp_path):
    candidate,manifest,job,result,write=producer_metadata(tmp_path)
    row=next(item for item in job['outputs'] if item['name']=='document_rows.parquet')
    row['sql']=row['sql'].replace('SELECT list_row,','SELECT (list_row+1)%3 AS list_row,')
    candidate['build_job']=write('job.json',job)
    loaded=dict(base=tmp_path,descriptor=dict(candidate=candidate),manifest=manifest,
        paths={key:candidate[key]['path'] for key in ('source_members','document_rows')})
    with pytest.raises(ValueError,match='projection lineage'):
        parity.validate_layout(loaded,engine=None,work=tmp_path/'not-created')
    assert not (tmp_path/'not-created').exists()


@pytest.mark.parametrize('defect',['length','start','ordinal','orphan'])
def test_native_attachment_range_accounting_detects_planted_errors(tmp_path,defect):
    row=dict(list_row=0,src_start=0,src_len=1,rec_start=0,rec_len=0)
    source=dict(list_row=0,ordinal=0)
    if defect=='length':row['src_len']=2
    if defect=='start':row['src_start']=1
    if defect=='ordinal':source['ordinal']=1
    if defect=='orphan':source['list_row']=1
    inputs=[json_input(tmp_path,'document_rows',[row],**{key:'Int64' for key in row}),
        json_input(tmp_path,'release_sources',[source],list_row='Int64',ordinal='Int64'),
        json_input(tmp_path,'release_recoveries',[],list_row='Int64',ordinal='Int64')]
    steps,checks=parity.attachment_layout_checks()
    report=run_job(tmp_path,engine(),inputs=inputs,steps=steps,outputs=[],
        queries=[dict(name='check_'+str(i),sql=sql) for i,sql in enumerate(checks)])
    assert sum(value[0]['errors'] for value in report.values())>0


def visible_comparison_inputs(tmp_path, *, defect=None):
    """One unchanged identity with independently authored old/new visible values."""
    member=FIXTURE['integration']['members'][0]
    identity=FIXTURE['integration']['documents'][0]['document_id']
    inputs=[]
    for side,doc in [('old','old'),('new','0')]:
        inputs += [json_input(tmp_path,side+'_documents',[dict(doc=doc)],doc='Utf8'),
            json_input(tmp_path,side+'_anchors',[dict(doc=doc,anchor=member['body_key'],identity_anchor=member['source_id'])],
                       doc='Utf8',anchor='Utf8',identity_anchor='Utf8')]
    inputs += [json_input(tmp_path,'identity_sources',[
        dict(side=side,doc=doc,**member) for side,doc in [('old','old'),('new','0')]],
        side='Utf8',doc='Utf8',source_id='Utf8',body_key='Utf8',filename='Utf8',source_url='Utf8'),
        json_input(tmp_path,'identity_documents',[
            dict(side=side,doc=doc,document_id=identity,body_keys=[member['body_key']],source_ids=[member['source_id']])
            for side,doc in [('old','old'),('new','0')]],
            side='Utf8',doc='Utf8',document_id='Utf8',body_keys=list_of('Utf8'),source_ids=list_of('Utf8')),
        json_input(tmp_path,'witnesses',[],old_doc='Utf8',new_doc='Utf8',subject='Utf8',fact='Utf8',evidence_ref='Utf8'),
        json_input(tmp_path,'difference_records',[],difference_id='Utf8',classification='Utf8',rule_ref='Utf8',note='Utf8',raw_signal='Utf8')]
    old=dict(document_id='old',filename=member['filename'],source_link_label=[],body_key=member['body_key'],
        first_captured=None,state_retrieved_at=[],date_token=[],saved_bytes=100,saved_media_type='application/pdf')
    new=dict(doc='0',filename=member['filename'],title=None,saved_body_hex=member['body_key'].split('/')[-1][:-3],
        first_captured=None,date_kind='unknown',document_date=None,document_date_source=None,
        saved_kind='original',hidden=False,saved_suffix='.gz',saved_bytes=100,saved_media_type='application/pdf',
        in_archive_since=None,removed_on=None,review_note=None,review_decided_at=None)
    if defect is not None:new[defect]={'filename':'wrong.pdf','saved_bytes':101,'saved_media_type':'text/plain'}[defect]
    old_types={key:'Utf8' for key in old}
    old_types.update({key:list_of('Utf8') for key in ('source_link_label','state_retrieved_at','date_token')})
    old_types['saved_bytes']='Int64'
    new_types={key:'Utf8' for key in new};new_types.update(hidden='Boolean',saved_bytes='Int64')
    inputs += [json_input(tmp_path,'old_wide',[old],**old_types),
        json_input(tmp_path,'new_wide_input',[new],**new_types)]
    return inputs,[dict(name='new_wide',sql="SELECT *,decode(saved_body_hex,'hex') AS saved_body FROM new_wide_input")]


@pytest.mark.parametrize('defect',[None,'filename','saved_bytes','saved_media_type'])
def test_production_scalar_comparison_detects_visible_regressions(tmp_path,defect):
    inputs,steps=visible_comparison_inputs(tmp_path,defect=defect)
    inputs += [json_input(tmp_path,name,[],doc='Utf8',field='Utf8',subject='Utf8',value='Utf8')
        for name in ('old_fields','new_fields')]
    result=parity.compare_relations(inputs,engine=engine(),work=tmp_path/'comparison',
        prelude=steps,use_scalar_deltas=True,metadata=True)
    expected=0 if defect is None else 2
    assert result['counts']['differences']==result['counts']['unclassified']==expected
    assert result['counts']['invalid_ids']==0
    assert result['decision_ready']==(defect is None)
    assert {row['field'] for row in result['clusters']}==({defect} if defect else set())


@pytest.mark.parametrize('defect',[None,'missing','wrong'])
def test_production_url_field_extraction_detects_lookup_regressions(tmp_path,defect):
    from hashlib import sha256
    inputs,steps=visible_comparison_inputs(tmp_path)
    url='https://fixture.test/document.pdf'
    # DM8.2 drops the scheme and prefixes the normalized address with lookup:.
    # This explicit expected spelling does not call the producer's lookup helper.
    expected=sha256(b'lookup:fixture.test/document.pdf').digest()[:8].hex()
    urls=[] if defect=='missing' else [dict(list_row=0,lookup_hex='0'*16 if defect=='wrong' else expected)]
    inputs += [json_input(tmp_path,'old_file_rows',[dict(document_id='old',source_url=url)],
                          document_id='Utf8',source_url='Utf8'),
        json_input(tmp_path,'url_input',urls,list_row='Int32',lookup_hex='Utf8')]
    steps.append(dict(name='release_urls',sql="SELECT list_row,decode(lookup_hex,'hex') AS lookup_key FROM url_input"))
    normalizer=tmp_path/'normalizer';normalizer.mkdir()
    _unused,normal=parity.normalization(dict(paths={},descriptor={}),directory=normalizer,use_scalar_deltas=True)
    steps.extend(step for step in normal if step['name'].startswith(('old_lookup_','old_url_')))
    for name in ('old_fields','new_fields'):
        sql=next(step['sql'] for step in normal if step['name']==name)
        # Execute the production normalizer's final URL branch, without the
        # unrelated full-release fields needed by its other UNION branches.
        branch=sql.rsplit(' UNION ALL ',1)[1].removesuffix(') WHERE value IS NOT NULL')
        assert "'url_lookup' AS field" in branch
        steps.append(dict(name=name,sql=branch))
    result=parity.compare_relations(inputs,engine=engine(),work=tmp_path/'comparison',
        prelude=steps,use_scalar_deltas=True,metadata=True)
    count={None:0,'missing':1,'wrong':2}[defect]
    assert result['counts']['differences']==result['counts']['unclassified']==count
    assert result['counts']['invalid_ids']==0
    assert result['decision_ready']==(defect is None)
    assert {row['field'] for row in result['clusters']}==({'url_lookup'} if defect else set())


def test_only_current_model_candidates_are_admitted(tmp_path):
    with pytest.raises(ValueError,match='current model kind'):
        parity.release_inputs(tmp_path,dict(kind='f0',release='retired-converter'))


def test_model_body_sets_exclude_nonreal_members_without_losing_source_evidence(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    source=FIXTURE['integration']['members'][0]
    members=[dict(list_row=i,source_id=str(i)*64,body_key=source['body_key'],source_url=source['source_url']) for i in (1,2)]
    captured=[dict(receipt_key='receipt',receipt_line=i,capture_index=0,source_id=row['source_id']) for i,row in enumerate(members)]
    roles=[dict(receipt_key='receipt',receipt_line=i,capture_index=0,is_real_file=i==1) for i in range(2)]
    paths={}
    for name,rows in [('source_members',members),('capture_sources',captured),('record_roles',roles)]:
        path=tmp_path/(name+'.parquet');pq.write_table(pa.Table.from_pylist(rows),path);paths[name]=str(path)
    inputs,steps=parity.normalization(dict(paths=paths,descriptor=dict(cause_relations=dict(capture_sources={},record_roles={}))),directory=tmp_path)
    selected=[step for step in steps if step['name'] in {'model_real_sources','new_bodies','new_anchors'}]
    report=run_job(tmp_path,engine(),inputs=inputs,steps=selected,outputs=[],queries=[dict(name='counts',
        sql='SELECT (SELECT count(*) FROM new_bodies) AS bodies,(SELECT count(*) FROM new_anchors) AS anchors')])
    assert report['counts']==[dict(bodies=1,anchors=2)]


def test_null_recovery_values_remain_observable_before_classification(tmp_path):
    inputs,steps=parity.normalization(dict(paths={},descriptor={}),directory=tmp_path)
    # Select the exact generated recovery branches, without rebuilding a whole
    # release just to check how explicit nulls cross this comparison boundary.
    sql=next(step['sql'] for step in steps if step['name']=='new_fields')
    branches=[part for part in sql.split(' UNION ALL ') if any("'recovery."+name+"'" in part for name in ('kind','imported_at'))]
    assert len(branches)==2
    inputs.append(json_input(tmp_path,'null_recovery',[dict(list_row=0,body='d'*64,kind=None,imported_at=None)],
        list_row='Int32',body='Utf8',kind='Utf8',imported_at='Utf8'))
    report=run_job(tmp_path,engine(),inputs=inputs,steps=[dict(name='release_recoveries',
        sql="SELECT list_row,decode(body,'hex') AS body,kind,imported_at FROM null_recovery")],outputs=[],queries=[dict(name='facts',
        sql='SELECT field,value FROM ('+' UNION ALL '.join(branches)+') ORDER BY field')])
    assert report['facts']==[dict(field='recovery.imported_at',value='[null]'),dict(field='recovery.kind',value='[null]')]


def inventory_fixture(tmp_path):
    """Physical inventory checks only; these rows claim no model qualification."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from hashlib import md5,sha256
    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_format import release_identity
    native=tmp_path/'native';native.mkdir();controls=tmp_path/'controls';controls.mkdir()
    files={};entries=[]
    for name in ('list','detail','links','urls','sources','recoveries'):
        key=name+'.parquet';path=native/key;pq.write_table(pa.table({'fixture':[1]}),path)
        files[key]=str(path);entries.append(dict(name=key,rows=1,md5=md5(path.read_bytes()).hexdigest(),**file_pin(path)))
    manifest=dict(schema_version=1,origin=dict(kind='model'),files=entries,release_id=release_identity(1,entries))
    path=controls/'manifest.json';path.write_text(json.dumps(manifest));files['manifest.json']=str(path)
    return dict(kind='model',files=files,manifest=dict(path=str(path),**file_pin(path))),manifest


def test_parity_inventory_uses_retained_paths_and_detects_changed_public_bytes(tmp_path):
    candidate,manifest=inventory_fixture(tmp_path)
    paths,loaded=parity.release_inputs(tmp_path,candidate)
    assert loaded==manifest and paths['release_list']==candidate['files']['list.parquet']
    path=Path(paths['release_list']);path.write_bytes(path.read_bytes()+b'tampered')
    with pytest.raises(ValueError,match='size differs|digest differs'):
        parity.release_inputs(tmp_path,candidate)


def test_cause_metadata_cannot_replace_an_original_or_public_relation(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congress_api.retention.provenance import file_pin
    original=oracle_fixture(tmp_path);candidate,_=inventory_fixture(tmp_path)
    def pin(path):return dict(path=str(path),**file_pin(path))
    oracle={};selector=dict(catalog_id=parity.ORACLE_CATALOG,generation=parity.ORACLE_GENERATION,files={})
    for name in ('documents','filenames'):
        path=Path(original['paths']['oracle_'+name]);oracle[name]=pin(path)
        selector['files'][name]=dict(key='original/'+path.name,sha256=oracle[name]['sha256'],bytes=oracle[name]['size'],rows=pq.ParquetFile(path).metadata.num_rows)
        receipt=tmp_path/(name+'-receipt.json');receipt.write_text(json.dumps(dict(key='original/'+path.name,identity=dict(sha256=oracle[name]['sha256']))))
        oracle[name+'_receipt']=pin(receipt)
    path=tmp_path/'selector.json';path.write_text(json.dumps(selector));oracle['selector']=pin(path)
    members=tmp_path/'members.parquet'
    pq.write_table(pa.Table.from_pylist([],schema=pa.schema([(key,pa.int32() if key=='list_row' else pa.string()) for key in sorted(parity.MEMBER_COLUMNS)])),members)
    candidate.update(source_members=pin(members),document_rows=pin(members))
    value=dict(version=1,oracle=oracle,candidate=candidate,cause_relations=dict(oracle_documents=oracle['filenames']))
    descriptor=tmp_path/'descriptor.json';descriptor.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='replace a reserved input'):
        parity.load_descriptor(descriptor)
