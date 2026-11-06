"""Explanation authoring and append-only metadata corrections read no bodies."""
import json
import os

import pytest

from congress_api.retention.provenance import apply_staged, load_stage, run_job
from congress_api.retention.body_store import BodyStore, LocalAdapter
from corpus_recovery.identity_notes import authored_note, correct_generated_note
from docspec_client.client import NativeDatasets


STAMP='2026-11-06T16:00:00Z'
PIN='e'*64
SENTINEL='Reconciled from pinned accepted mappings '+PIN+'; receipt categories preserved'


def legacy(**changes):
    return dict(dict(id='immutable-base',original_url='https://docs.house.gov/original.pdf',
        recovered_url='https://www.govinfo.gov/official-hearing.pdf',recovered_filename='hearing.pdf',
        body_sha256='a'*64,kind='requested_content_in_official_hearing',match_basis='official_document_identifier',
        evidence_sha256=PIN,identity_note=SENTINEL,decided_by='legacy-reconciler',
        decided_at='2026-10-27T12:00:00Z',supersedes=None),**changes)


@pytest.mark.parametrize('note', [None, '', '  ', SENTINEL])
def test_unknown_and_generated_notes_stay_null(note):
    assert authored_note(note) is None


@pytest.mark.parametrize('note', [
    'The committee reposted the original statement at this address.',
    SENTINEL+'; reviewed against the committee index',
])
def test_authored_text_is_preserved_exactly(note):
    assert authored_note(note)==note


@pytest.mark.parametrize('note', [42, False, ['explanation']])
def test_malformed_explanation_is_refused(note):
    with pytest.raises(ValueError,match='authored explanation or null'):
        authored_note(note)


@pytest.mark.parametrize('extra', [{},dict(recovery_record_version=2,target_requirement='requested_content',
    acceptance_status='accepted',acceptance_policy='recovery-identity-v1',qualification_sha256='b'*64)])
def test_correction_changes_only_explanation_and_decision_identity(extra):
    row=legacy(**extra);before=dict(row)
    correction=correct_generated_note(row,decided_at=STAMP,decided_by='metadata-review')
    assert row==before
    assert correction['identity_note'] is None and correction['supersedes']==row['id']
    assert correction['id']!=row['id']
    assert correction==correct_generated_note(row,decided_at=STAMP,decided_by='metadata-review')
    preserved=set(row)-{'id','identity_note','supersedes','decided_at','decided_by'}
    assert {key:correction[key] for key in preserved}=={key:row[key] for key in preserved}


@pytest.mark.parametrize('changes', [dict(identity_note=None),dict(identity_note='Authored relationship'),
    dict(evidence_sha256='f'*64),dict(evidence_sha256=None),dict(identity_note=SENTINEL+' ')])
def test_correction_refuses_everything_except_own_exact_sentinel(changes):
    with pytest.raises(ValueError,match='exact generated note'):
        correct_generated_note(legacy(**changes),decided_at=STAMP,decided_by='metadata-review')


def test_maintained_stage_preserves_legacy_bytes_and_native_selection(tmp_path):
    from congress_api.cli.provenance import main
    from viewer_publication.archive_provenance import current_steps, provenance_inputs

    old=legacy();correction=correct_generated_note(old,decided_at=STAMP,decided_by='metadata-review')
    source=tmp_path/'legacy.jsonl';source.write_text(json.dumps(old)+'\n')
    old_bytes=source.read_bytes()
    authored=tmp_path/'corrections.jsonl';authored.write_text(json.dumps(correction)+'\n')
    stage=tmp_path/'stage'
    main(['--records',str(authored),'--kind','recoveries','--decided-at',STAMP,'--stage',str(stage)])
    _,manifest=load_stage(stage)
    staged=stage/manifest['provenance']
    store=BodyStore(LocalAdapter(tmp_path/'local-only-store'))
    assert apply_staged(stage,store)==apply_staged(stage,store)==dict(objects=1,records=1)
    assert source.read_bytes()==old_bytes
    assert json.loads(staged.read_text())==correction
    inputs,_=provenance_inputs(tmp_path/'inputs',recovery_files=[dict(key='legacy',path=str(source)),
        dict(key=manifest['provenance'],path=str(staged))])
    # Include a genuine explanation and a different pin to prove exact filtering.
    control=legacy(id='authored',original_url='https://docs.house.gov/other.pdf',
                   identity_note='The hearing includes the requested statement.')
    control_file=tmp_path/'controls.jsonl'
    control_file.write_text(json.dumps(control)+'\n'+json.dumps(legacy(id='different-pin',
        original_url='https://docs.house.gov/different.pdf',evidence_sha256='f'*64))+'\n')
    inputs[0]['files'].append(dict(key='controls',path=str(control_file)))
    report=run_job(tmp_path/'native',NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        inputs=inputs,steps=current_steps()[:1],outputs=[],queries=[dict(name='selected',
            sql='SELECT id,kind,body_sha256,recovered_url,identity_note FROM remaining_recovery_decisions ORDER BY id')])
    rows={r['id']:r for r in report['selected']}
    assert set(rows)=={correction['id'],'authored','different-pin'}
    assert rows[correction['id']]['identity_note'] is None
    assert rows[correction['id']]['kind']==old['kind'] and rows[correction['id']]['body_sha256']==old['body_sha256']
    assert rows[correction['id']]['recovered_url']==old['recovered_url']
    assert rows['authored']['identity_note']==control['identity_note']
    assert rows['different-pin']['identity_note']==SENTINEL
