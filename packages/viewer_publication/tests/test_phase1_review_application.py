"""URL review edges and post-merge decisions have explicit native expectations."""
import os

from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets


def test_reviews_merge_by_link_key_then_apply_latest_values(tmp_path):
    from viewer_publication.archive_provenance import current_steps
    from viewer_publication.archive_reviews import duplicate_steps,application_steps
    def review(id,target,verdict,value_json,**changes):
        return dict(dict(id=id,target=target*16,verdict=verdict,value_json=value_json,note=id,
            decided_at='2026-10-20T12:00:00Z',supersedes=None),**changes)
    reviews=[review('duplicate-one','a','duplicate_of','"'+('b'*16)+'"'),
        review('duplicate-two','b','duplicate_of','"'+('c'*16)+'"'),
        review('missing-target','e','duplicate_of','"'+('b'*16)+'"'),
        review('missing-value','a','duplicate_of','"'+('f'*16)+'"'),
        review('old-title','a','title_override','"Old title"'),
        review('title-a','b','title_override','"Same instant earlier ID"',decided_at='2026-10-21T12:00:00+00:00'),
        review('title-z','c','title_override','"Merged title winner"',decided_at='2026-10-21T12:00:00Z'),
        review('withdrawn-title','a','title_override','"Withdrawn title"',decided_at='2026-10-25T12:00:00Z'),
        review('withdraw','a','withdraw','null',decided_at='2026-10-26T12:00:00Z',supersedes='withdrawn-title'),
        review('hide-old','a','hide','true'),
        review('hide-new','b','hide','false',decided_at='2026-10-22T12:00:00Z'),
        review('kind','c','kind_override','["testimony","letter","letter"]')]
    inputs=[json_input(tmp_path,'review_records',reviews,id='Utf8',target='Utf8',verdict='Utf8',value_json='Utf8',note='Utf8',decided_at='Utf8',supersedes='Utf8'),
        json_input(tmp_path,'initial_document_link_keys',[dict(component=c,link_key=k*16) for c,k in [('one','a'),('two','b'),('three','c'),('solo','d')]],component='Utf8',link_key='Utf8'),
        json_input(tmp_path,'component_members',[dict(component=c) for c in ['one','two','three','solo']],component='Utf8')]
    steps=[current_steps()[1]]+duplicate_steps()+[
        dict(name='review_components',components=dict(sql='SELECT left_node,right_node FROM duplicate_component_edges',left='left_node',right='right_node',node_limit=100)),
        dict(name='document_link_keys',sql="SELECT DISTINCT substr(c.component,3) AS component,k.link_key FROM initial_document_link_keys k JOIN review_components c ON c.node='c:'||k.component",materialize=True),
        dict(name='document_identities',sql="SELECT DISTINCT component,'id:'||component AS document_id FROM document_link_keys",materialize=True)]
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    result=run_job(tmp_path,engine,inputs=inputs,steps=steps+application_steps(),outputs=[],queries=[
        dict(name='components',sql='SELECT node,component FROM review_components ORDER BY node'),
        dict(name='unresolved',sql='SELECT id,error FROM review_link_diagnostics ORDER BY id'),
        dict(name='applied',sql='SELECT component,hidden,note,cast(decided_at AS VARCHAR) AS decided_at,title_override,kind_override FROM review_overrides ORDER BY component'),
        dict(name='invalid',sql='SELECT * FROM review_value_diagnostics')])
    assert result['components']==[dict(node='c:'+c,component='c:'+('solo' if c=='solo' else 'one')) for c in ['one','solo','three','two']]
    assert result['unresolved']==[dict(id='missing-target',error='unresolved_review_target'),dict(id='missing-value',error='unresolved_review_value')]
    assert result['applied']==[dict(component='one',hidden=False,note='hide-new',decided_at='2026-10-22',title_override='Merged title winner',kind_override=['letter','testimony']),
                              dict(component='solo',hidden=False,note=None,decided_at=None,title_override=None,kind_override=None)]
    assert result['invalid']==[]
    # A colliding key cannot silently become a duplicate edge that hides its ambiguity.
    collision=json_input(tmp_path,'colliding_keys',[dict(component=c,link_key='a'*16) for c in ['one','solo']],component='Utf8',link_key='Utf8')
    collision['name']='initial_document_link_keys'
    work=tmp_path/'collision';work.mkdir()
    result=run_job(work,engine,inputs=[x for x in inputs if x['name']!='initial_document_link_keys']+[collision],
        steps=[current_steps()[1]]+duplicate_steps(),outputs=[],queries=[dict(name='conflicts',sql='SELECT link_key FROM document_link_key_conflicts')])
    assert result['conflicts']==[dict(link_key='a'*16)]


def test_malformed_applicable_review_value_is_a_fatal_diagnostic(tmp_path):
    from viewer_publication.archive_provenance import current_steps
    from viewer_publication.archive_reviews import application_steps
    inputs=[json_input(tmp_path,'review_records',[dict(id='invalid-hide',target='a'*16,verdict='hide',value_json='"false"',note=None,decided_at='2026-10-20T12:00:00Z',supersedes=None),
        dict(id='empty-kind',target='a'*16,verdict='kind_override',value_json='[]',note=None,decided_at='2026-10-20T12:00:00Z',supersedes=None)],
        id='Utf8',target='Utf8',verdict='Utf8',value_json='Utf8',note='Utf8',decided_at='Utf8',supersedes='Utf8'),
        json_input(tmp_path,'document_link_keys',[dict(component='one',link_key='a'*16)],component='Utf8',link_key='Utf8'),
        json_input(tmp_path,'document_identities',[dict(component='one',document_id='id:one')],component='Utf8',document_id='Utf8')]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=[current_steps()[1]]+application_steps(),outputs=[],queries=[dict(name='invalid',sql='SELECT id,error FROM review_value_diagnostics ORDER BY id')])
    assert result['invalid']==[dict(id='empty-kind',error='invalid_review_value'),dict(id='invalid-hide',error='invalid_review_value')]
