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


def f0_fixture(tmp_path, *, bad_filename=False, bad_metadata=False, bad_ranges=False, bad_lookup=False, bad_sort=None):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_release import convert_catalog
    data=FIXTURE['f0_catalog']
    arrays=['body_keys','filenames','source_urls','body_format','format','media_type','http_status','capture_outcome',
        'response_usable','response_body_complete','filename_origins','source_paths','document_kind','document_family',
        'committee_code','congress','date_token','date_token_candidates','state_retrieved_at','source_link_label',
        'source_page_url','source_meeting_id','source_capture_url','measure_references','member_bioguide_id',
        'hearing_package_id','recovered_filename','recovered_source_url']
    schema=pa.schema([(name,pa.string()) for name in ['document_id','source_id','body_key','filename','source_url']]
        +[(name,pa.list_(pa.string())) for name in arrays])
    for name,rows in [('documents',data['documents']),('filenames',data['files'])]:
        pq.write_table(pa.Table.from_pylist(rows,schema=schema),tmp_path/(name+'.parquet'))
    pq.write_table(pa.table(dict(body_key=[r['body_key'] for r in data['files']],bytes=[100]*4,media_type=['text/html','text/html','application/pdf','application/xml'])),tmp_path/'captures.parquet')
    pq.write_table(pa.table(dict(system_code=['hsag00'],name=['Agriculture'],chamber=['house'])),tmp_path/'committees.parquet')
    manifest=convert_catalog(tmp_path/'documents.parquet',tmp_path/'filenames.parquet',tmp_path/'captures.parquet',tmp_path/'committees.parquet',
        catalog_id=parity.ORACLE_GENERATION,output=tmp_path/'release',scratch=tmp_path/'converter',engine=engine())
    release=tmp_path/'release';producer=tmp_path/'converter'
    if bad_filename or bad_metadata or bad_ranges or bad_lookup or bad_sort:
        # This is an authored bad native job, not a patch to production code.
        from hashlib import sha256
        job=json.loads((producer/'job.json').read_text())
        normalized=next(s for s in job['steps'] if s['name']=='normalized')
        before='d.filename AS "filename"'
        assert before in normalized['sql']
        if bad_filename:
            normalized['sql']=normalized['sql'].replace(before,
                "CASE WHEN d.filename='Beta.html' THEN 'Wrong.html' ELSE d.filename END AS \"filename\"",1)
        if bad_metadata:
            assert 'b.bytes AS \"bytes\"' in normalized['sql']
            normalized['sql']=normalized['sql'].replace('b.bytes AS \"bytes\"','b.bytes+1 AS \"bytes\"').replace('coalesce(b.media_type,',"coalesce('application/x-corrupt',")
        if bad_ranges:
            details=next(step for step in job['steps'] if step['name']=='details')
            details['sql']=details['sql'].replace('coalesce(s.src_len,cast(0 AS INT)) AS src_len','coalesce(s.src_len,cast(0 AS INT))+1 AS src_len')
        if bad_lookup:
            lookup=next(step for step in job['steps'] if step['name']=='url_keys')
            lookup['sql']+=' WHERE false'
        if bad_sort:
            output=next(o for o in job['outputs'] if o['name']==bad_sort)
            output['settings']['order_by'][0]['direction']='desc'
        release=tmp_path/'bad-release';release.mkdir()
        producer=tmp_path/'bad-producer';producer.mkdir()
        job['scratch']=str(producer/'native')
        for output in job['outputs']:
            output['path']=str(release/output['name'])
        (producer/'job.json').write_text(json.dumps(job))
        result=engine().run_job(producer/'job.json')
        (producer/'result.json').write_text(json.dumps(result))
        for item in manifest['files']:
            if item['name'].endswith('.parquet'):
                actual=next(r for r in result['outputs'] if r['name']==item['name'])
                for name in ['sha256','md5','size','rows']:
                    item[name]=actual[name]
            else:
                (release/item['name']).write_bytes((tmp_path/'release'/item['name']).read_bytes())
        identity=[manifest['schema_version'],[[f['name'],f['sha256'],f['size'],f['rows']] for f in manifest['files']]]
        manifest['release_id']=sha256(json.dumps(identity,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        (release/'manifest.json').write_text(json.dumps(manifest))
    selector=dict(version=1,catalog_id=parity.ORACLE_CATALOG,generation=parity.ORACLE_GENERATION,files={})
    for name,key in [('documents','documents.parquet'),('filenames','document-filenames.parquet')]:
        pin=file_pin(tmp_path/(name+'.parquet'))
        selector['files'][name]=dict(key='catalog-generations/'+parity.ORACLE_GENERATION+'/'+key,sha256=pin['sha256'],bytes=pin['size'],rows=len(data[name if name=='documents' else 'files']))
        (tmp_path/(name+'-receipt.json')).write_text(json.dumps(dict(key=selector['files'][name]['key'],identity=dict(sha256=pin['sha256'],bytes=pin['size']))))
    (tmp_path/'selector.json').write_text(json.dumps(selector))
    example=json.loads((ROOT/'model/fixtures/e4-parity-inputs.example.json').read_text())
    def pin(name):
        path=tmp_path/name
        return dict(path=str(path),**file_pin(path))
    example['oracle']=dict(selector=pin('selector.json'),documents=pin('documents.parquet'),filenames=pin('filenames.parquet'),
        documents_receipt=pin('documents-receipt.json'),filenames_receipt=pin('filenames-receipt.json'))
    example['candidate']=dict(kind='f0',release=str(release),manifest_sha256=file_pin(release/'manifest.json')['sha256'],
        build_job=dict(path=str(producer/'job.json'),**file_pin(producer/'job.json')),
        build_result=dict(path=str(producer/'result.json'),**file_pin(producer/'result.json')))
    example['cause_relations']={}
    path=tmp_path/'f0-template.json';path.write_text(json.dumps(example))
    return path


def test_actual_f0_candidate_has_only_converter_gaps(tmp_path):
    template=f0_fixture(tmp_path)
    descriptor=parity.prepare_f0(template,engine=engine(),work=tmp_path/'prepare')
    result=parity.compare_descriptor(descriptor,engine_config=os.environ['DOCSPEC_JOB_CONFIG'],work=tmp_path/'comparison')
    for field in ['unexplained','unclassified','invalid_ids']:
        assert result['counts'][field]==FIXTURE['f0_catalog']['expected'][field]
    assert set(FIXTURE['f0_catalog']['expected']['required_causes'])<={row['cause'] for row in result['causes'] if row['differences']}
    assert result['candidate_kind']=='f0'
    assert result['model_qualified'] is False
    assert result['decision_ready'] is True


def test_f0_conversion_proofs_do_not_excuse_a_corrupt_visible_filename(tmp_path):
    template=f0_fixture(tmp_path,bad_filename=True)
    descriptor=parity.prepare_f0(template,engine=engine(),work=tmp_path/'prepare')
    result=parity.compare_descriptor(descriptor,engine_config=os.environ['DOCSPEC_JOB_CONFIG'],work=tmp_path/'comparison')
    assert result['counts']['unexplained']==2
    assert result['counts']['invalid_ids']==0
    assert result['decision_ready'] is False


def test_public_bytes_cannot_change_after_the_pinned_producer_result(tmp_path):
    template=f0_fixture(tmp_path)
    descriptor=parity.prepare_f0(template,engine=engine(),work=tmp_path/'prepare')
    path=tmp_path/'release/list.parquet'
    path.write_bytes(path.read_bytes()+b'tampered')
    with pytest.raises(ValueError,match='size differs|digest differs'):
        parity.compare_descriptor(descriptor,engine_config=os.environ['DOCSPEC_JOB_CONFIG'],work=tmp_path/'comparison')


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


def test_corrupt_native_download_metadata_is_not_invisible(tmp_path):
    template=f0_fixture(tmp_path,bad_metadata=True)
    descriptor=parity.prepare_f0(template,engine=engine(),work=tmp_path/'prepare')
    result=parity.compare_descriptor(descriptor,engine_config=os.environ['DOCSPEC_JOB_CONFIG'],work=tmp_path/'comparison')
    assert result['counts']['unexplained']==FIXTURE['f0_catalog']['expected']['bad_metadata_unexplained']
    assert result['decision_ready'] is False


def test_native_private_mapping_permutation_is_not_public_row_evidence(tmp_path):
    from congress_api.retention.provenance import file_pin
    template=f0_fixture(tmp_path)
    descriptor=parity.prepare_f0(template,engine=engine(),work=tmp_path/'prepare')
    value=json.loads(descriptor.read_text());candidate=value['candidate']
    job=json.loads(Path(candidate['layout_job']['path']).read_text())
    rows=next(o for o in job['outputs'] if o['name']=='document_rows')
    members=next(o for o in job['outputs'] if o['name']=='source_members')
    rows['sql']=rows['sql'].replace('SELECT list_row,','SELECT cast((list_row+1)%3 AS INT) AS list_row,',1)
    members['sql']=members['sql'].replace('o.list_row,','cast((o.list_row+1)%3 AS INT) AS list_row,',1)
    work=tmp_path/'permuted';work.mkdir();job['scratch']=str(work/'native')
    for output in job['outputs']:output['path']=str(work/(output['name']+'.parquet'))
    (work/'job.json').write_text(json.dumps(job));result=engine().run_job(work/'job.json')
    (work/'result.json').write_text(json.dumps(result))
    for key,name in [('layout_job','job.json'),('layout_result','result.json'),('source_members','source_members.parquet'),('document_rows','document_rows.parquet')]:
        path=work/name;candidate[key]=dict(path=str(path),**file_pin(path))
    descriptor.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='projection|lineage'):
        parity.compare_descriptor(descriptor,engine_config=os.environ['DOCSPEC_JOB_CONFIG'],work=tmp_path/'comparison')


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


def test_bad_native_attachment_ranges_refuse_before_parity(tmp_path):
    template=f0_fixture(tmp_path,bad_ranges=True)
    descriptor=parity.prepare_f0(template,engine=engine(),work=tmp_path/'prepare')
    with pytest.raises(ValueError,match='range|attachment'):
        parity.compare_descriptor(descriptor,engine_config=os.environ['DOCSPEC_JOB_CONFIG'],work=tmp_path/'comparison')


def test_missing_native_url_resolution_rows_are_unexplained(tmp_path):
    template=f0_fixture(tmp_path,bad_lookup=True)
    descriptor=parity.prepare_f0(template,engine=engine(),work=tmp_path/'prepare')
    result=parity.compare_descriptor(descriptor,engine_config=os.environ['DOCSPEC_JOB_CONFIG'],work=tmp_path/'comparison')
    assert result['counts']['unexplained']==4
    assert result['decision_ready'] is False


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



def test_model_body_sets_exclude_nonreal_members_but_keep_their_source_evidence(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congress_api.retention.provenance import file_pin
    template=f0_fixture(tmp_path)
    descriptor=parity.prepare_f0(template,engine=engine(),work=tmp_path/'prepare')
    loaded=parity.load_descriptor(descriptor)
    # This checks the projection only. The F0 manifest still cannot qualify as
    # a model release through load_descriptor/compare_descriptor.
    loaded['descriptor']['candidate']['kind']='model'
    files=FIXTURE['f0_catalog']['files']
    sources=[dict(receipt_key='receipts/test.jsonl',receipt_line=i,capture_index=0,source_id=row['source_id']) for i,row in enumerate(files)]
    roles=[dict(receipt_key='receipts/test.jsonl',receipt_line=i,capture_index=0,is_real_file=i!=0) for i in range(len(files))]
    for name,rows in [('capture_sources',sources),('record_roles',roles)]:
        path=tmp_path/(name+'.parquet');pq.write_table(pa.Table.from_pylist(rows),path)
        loaded['paths'][name]=str(path)
        loaded['descriptor']['cause_relations'][name]=dict(path=str(path),**file_pin(path))
    directory=tmp_path/'normalized';directory.mkdir()
    inputs,steps=parity.normalization(loaded,directory=directory)
    result=run_job(directory,engine(),inputs=inputs,steps=steps,outputs=[],queries=[dict(name='counts',sql='SELECT (SELECT count(*) FROM new_bodies) AS bodies,(SELECT count(*) FROM new_anchors) AS anchors')])
    assert result['counts']==[dict(bodies=FIXTURE['f0_catalog']['expected']['model_real_bodies'],anchors=4)]


@pytest.mark.parametrize('table',['list.parquet','detail.parquet','sources.parquet','recoveries.parquet'])
def test_native_descending_public_writer_cannot_authenticate_ascending_private_rows(tmp_path,table):
    template=f0_fixture(tmp_path,bad_sort=table)
    with pytest.raises(ValueError,match='sort|order'):
        parity.prepare_f0(template,engine=engine(),work=tmp_path/'prepare')


def test_null_recovery_values_remain_observable_before_cause_classification(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    template=f0_fixture(tmp_path)
    descriptor=parity.prepare_f0(template,engine=engine(),work=tmp_path/'prepare')
    loaded=parity.load_descriptor(descriptor)
    schema=pq.read_schema(loaded['paths']['release_recoveries'])
    row=dict(list_row=0,ordinal=0,kind=None,body=bytes.fromhex('d'*64),suffix='.gz',bytes=100,imported_at=None,recovered_url='https://www.govinfo.gov/hearing.htm',identity_note=None)
    path=tmp_path/'null-recoveries.parquet';pq.write_table(pa.Table.from_pylist([row],schema=schema),path)
    # Exercise value projection of this deliberately bad public row; the full
    # descriptor path independently checks native production and range custody.
    loaded['paths']['release_recoveries']=str(path)
    directory=tmp_path/'normalized';directory.mkdir()
    inputs,steps=parity.normalization(loaded,directory=directory)
    reports=run_job(directory,engine(),inputs=inputs,steps=steps,outputs=[],queries=[dict(name='values',sql="SELECT field,value FROM new_fields WHERE field IN ('recovery.kind','recovery.imported_at') ORDER BY field")])
    assert reports['values']==[dict(field=field,value=value) for field,value in sorted(FIXTURE['f0_catalog']['expected']['null_recovery_values'].items())]


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
    template=f0_fixture(tmp_path)
    descriptor=parity.prepare_f0(template,engine=engine(),work=tmp_path/'prepare')
    loaded=parity.load_descriptor(descriptor)
    files=FIXTURE['f0_catalog']['files']
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


@pytest.mark.parametrize('case',FIXTURE['producer_profile_cases'],ids=lambda case:case['case'])
def test_model_profile_is_pinned_and_the_same_producer_has_zero_completeness_errors(tmp_path,case):
    from congress_api.retention.provenance import file_pin
    template=f0_fixture(tmp_path)
    value=json.loads(template.read_text());candidate=value['candidate'];candidate['kind']='model'
    manifest=json.loads((Path(candidate['release'])/'manifest.json').read_text())
    profile=tmp_path/'profile.json';profile.write_text(json.dumps({'owner_admission':'E2'}))
    candidate['producer_profile']=dict(path=str(profile),**file_pin(profile))
    job_path=Path(candidate['build_job']['path']);result_path=Path(candidate['build_result']['path'])
    job=json.loads(job_path.read_text());result=json.loads(result_path.read_text())
    job['queries'].append(dict(name='profile_completeness',sql='SELECT 0 AS missing_pages'))
    check=dict(name='profile_completeness',data=[dict(missing_pages=0)])
    result['queries'].append(check)
    name=case['case']
    if name=='missing-pin':candidate.pop('producer_profile')
    if name=='changed-profile':profile.write_text('{}')
    if name=='missing-check':result['queries'].remove(check)
    if name=='empty-check':check['data']=[]
    if name=='positive-count':check['data'][0]['missing_pages']=1
    if name=='null-count':check['data'][0]['missing_pages']=None
    if name=='boolean-count':check['data'][0]['missing_pages']=False
    job_path.write_text(json.dumps(job));result_path.write_text(json.dumps(result))
    for key,path in [('build_job',job_path),('build_result',result_path)]:candidate[key]=dict(path=str(path),**file_pin(path))
    if case['accepted']:parity.producer_inputs(template.parent,candidate,manifest)
    else:
        with pytest.raises(ValueError,match='profile|completeness|pin|digest'):
            parity.producer_inputs(template.parent,candidate,manifest)


def test_cause_metadata_cannot_replace_the_pinned_oracle_or_public_candidate(tmp_path):
    from congress_api.retention.provenance import file_pin
    template=f0_fixture(tmp_path);value=json.loads(template.read_text())
    value['cause_relations']={'oracle_documents':dict(value['oracle']['filenames'],required_columns=[])}
    template.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='replace|reserved'):
        parity.load_descriptor(template)
