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
    assert result['causes']==[dict(cause='govinfo_same_stem_groups',differences=2)]
    assert result['clusters']==[dict(field='title',direction=direction,classification=None,differences=2,with_raw_signal=0)
                                for direction in ['added','removed']]


def test_missing_identity_and_invalid_classification_records_refuse_completion(tmp_path):
    result=parity.compare_relations(merge_inputs(tmp_path,invalid_source=True,
        records=[dict(difference_id='f'*64,classification='approve_everything',note='Not a valid classification')]),
        engine=engine(),work=tmp_path/'comparison')
    assert result['counts']['invalid_ids']==1
    assert result['counts']['invalid_records']>=1
    assert result['decision_ready'] is False
