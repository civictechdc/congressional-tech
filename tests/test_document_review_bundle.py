from copy import deepcopy
import json
import pyarrow.parquet as pq
import pytest

from congress_api.retention.document_review_catalog import write_candidates
from congress_api.retention.document_review_receipts import file_digest
from congress_api.retention.document_review_bundle import load_bundle, select_document
from test_document_review_catalog import fixture


def bundle(tmp_path,unsupported=False):
    args=fixture(tmp_path,unsupported);write_candidates(**args)
    summary=args['output']/'summary.json'
    return args,summary


@pytest.mark.parametrize('unsupported',[False,True])
def test_bundle_selection_withdrawal_and_detached_results(tmp_path,unsupported):
    args,summary=bundle(tmp_path,unsupported)
    candidates=load_bundle(summary,file_digest(summary),args['sources'],args['documents'])
    doc=pq.read_table(args['documents']).to_pylist()[0];sources=pq.read_table(args['sources']).to_pylist()
    before=deepcopy((doc,sources,candidates))
    result=select_document(doc,sources,candidates)
    assert result['status']==('annotation_only_unsupported_forms' if unsupported else 'candidate_applied')
    assert select_document(doc,sources)['document']==doc
    assert select_document(doc,sources,{})['document']==doc
    result['document']['document_kind'].append('mutation')
    assert (doc,sources,candidates)==before
    control=dict(doc,document_id='other');control_sources=[dict(sources[0],document_id='other')]
    assert select_document(control,control_sources,candidates)['document']==control


@pytest.mark.parametrize('change',['summary_bytes','candidate_bytes','baseline_bytes','evidence_bytes','version','approval',
    'duplicate','coverage','counts','candidate_kind','candidate_context','review_scope','implementation','output_path'])
def test_bundle_refuses_stale_or_tampered_data(tmp_path,change):
    args,summary=bundle(tmp_path);expected=file_digest(summary);meta=json.loads(summary.read_text())
    candidate=args['output']/'candidates.jsonl';rows=[json.loads(line) for line in candidate.read_text().splitlines()]
    if change=='summary_bytes':summary.write_text('{}')
    elif change=='candidate_bytes':candidate.write_text('{}\n')
    elif change=='baseline_bytes':
        with args['sources'].open('ab') as stream:stream.write(b'changed')
    elif change=='evidence_bytes':(tmp_path/'body.pdf').write_bytes(b'changed')
    else:
        if change=='version':meta['bundle_version']=True
        elif change=='approval':meta['release_approved']=True
        elif change=='coverage':meta['reviewed_groups']=2
        elif change=='counts':meta['case_status']={'no_review':1}
        elif change=='implementation':meta['implementation']['house_naming_fingerprint']='changed'
        elif change=='output_path':meta['outputs']={'../elsewhere.jsonl':meta['outputs']['candidates.jsonl']}
        else:
            if change=='duplicate':rows*=2
            elif change=='candidate_kind':rows[0]['document']['document_kind']=['biography']
            elif change=='candidate_context':rows[0]['document']['source_occurrences']=[]
            elif change=='review_scope':rows[0]['review']['group_sha256']='changed'
            candidate.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            meta['outputs']['candidates.jsonl']=file_digest(candidate)
        summary.write_text(json.dumps(meta));expected=file_digest(summary)
    with pytest.raises(ValueError):load_bundle(summary,expected,args['sources'],args['documents'])


def test_loaded_candidates_are_rechecked_when_current_rows_change(tmp_path):
    args,summary=bundle(tmp_path)
    candidates=load_bundle(summary,file_digest(summary),args['sources'],args['documents'])
    doc=pq.read_table(args['documents']).to_pylist()[0];sources=pq.read_table(args['sources']).to_pylist()
    sources[0]['filename']='replacement.pdf'
    with pytest.raises(ValueError,match='current baseline'):select_document(doc,sources,candidates)
    assert select_document(doc,sources)['document']==doc


def test_other_pair_path_is_not_an_implicit_transfer(tmp_path):
    args,summary=bundle(tmp_path)
    copy=tmp_path/'other-sources.parquet';copy.write_bytes(args['sources'].read_bytes())
    with pytest.raises(ValueError,match='different baseline'):load_bundle(summary,file_digest(summary),copy,args['documents'])


@pytest.mark.parametrize('change',['input','implementation'])
def test_reader_rechecks_snapshot_before_returning_candidates(tmp_path,monkeypatch,change):
    from congress_api.retention import document_review_bundle as reader
    args,summary=bundle(tmp_path)
    if change=='input':
        original=reader.selected_groups
        def changed(path,*rest):
            rows=original(path,*rest)
            if path==args['documents']:
                with path.open('ab') as stream:stream.write(b'changed after reading')
            return rows
        monkeypatch.setattr(reader,'selected_groups',changed)
    else:
        calls=iter([reader.implementation(),{'changed':True}])
        monkeypatch.setattr(reader,'implementation',lambda:next(calls))
    with pytest.raises(ValueError):load_bundle(summary,file_digest(summary),args['sources'],args['documents'])
