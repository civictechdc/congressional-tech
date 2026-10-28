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


def f0_fixture(tmp_path):
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
    example['candidate']=dict(kind='f0',release=str(tmp_path/'release'),manifest_sha256=file_pin(tmp_path/'release/manifest.json')['sha256'])
    example['cause_relations']={}
    path=tmp_path/'f0-template.json';path.write_text(json.dumps(example))
    return path


def test_actual_f0_candidate_has_only_converter_gaps(tmp_path):
    template=f0_fixture(tmp_path)
    descriptor=parity.prepare_f0(template,engine=engine(),work=tmp_path/'prepare')
    result=parity.compare_descriptor(descriptor,engine_config=os.environ['DOCSPEC_JOB_CONFIG'],work=tmp_path/'comparison')
    for field in ['unexplained','unclassified','invalid_ids']:
        assert result['counts'][field]==FIXTURE['f0_catalog']['expected'][field]
    assert set(FIXTURE['f0_catalog']['expected']['required_causes'])<={row['cause'] for row in result['causes']}
    assert result['candidate_kind']=='f0'
    assert result['model_qualified'] is False
    assert result['decision_ready'] is True


def test_f0_conversion_proofs_do_not_excuse_a_corrupt_visible_filename(tmp_path):
    from hashlib import sha256,md5
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congress_api.retention.provenance import file_pin
    template=f0_fixture(tmp_path)
    descriptor=parity.prepare_f0(template,engine=engine(),work=tmp_path/'prepare')
    path=tmp_path/'release/list.parquet';table=pq.read_table(path)
    index=table.schema.get_field_index('filename')
    table=table.set_column(index,'filename',pa.array(['Wrong.html' if x=='Beta.html' else x
        for x in table.column('filename').to_pylist()],type=table.schema.field(index).type))
    pq.write_table(table,path,compression='zstd',data_page_version='2.0')
    manifest_path=tmp_path/'release/manifest.json';manifest=json.loads(manifest_path.read_text())
    entry=next(r for r in manifest['files'] if r['name']=='list.parquet')
    entry.update(sha256=file_pin(path)['sha256'],size=path.stat().st_size,md5=md5(path.read_bytes()).hexdigest())
    identity=[manifest['schema_version'],[[f['name'],f['sha256'],f['size'],f['rows']] for f in manifest['files']]]
    manifest['release_id']=sha256(json.dumps(identity,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    value=json.loads(descriptor.read_text());value['candidate']['manifest_sha256']=file_pin(manifest_path)['sha256']
    descriptor.write_text(json.dumps(value))
    result=parity.compare_descriptor(descriptor,engine_config=os.environ['DOCSPEC_JOB_CONFIG'],work=tmp_path/'comparison')
    assert result['counts']['unexplained']==2
    assert result['counts']['invalid_ids']==0
    assert result['decision_ready'] is False
