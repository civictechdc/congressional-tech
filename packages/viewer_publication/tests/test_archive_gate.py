"""F1: gates and optimistic pointer commit share the local/CI execution path."""
import json
import subprocess
from pathlib import Path

import pytest

from viewer_publication.archive_gate import gate_and_flip

ROOT = Path(__file__).parents[3]


class Pointer:
    def __init__(self, value=None): self.value = value; self.etag = 'original' if value else None; self.puts = []
    def put_object(self, **args):
        self.puts.append(args)
        if args.get('IfMatch') != self.etag or self.etag is None and args.get('IfNoneMatch') != '*':
            raise RuntimeError('lost pointer race')
        self.value = json.loads(args['Body']); self.etag = 'next'; return {'ETag': self.etag}


def passed(): return {'status': 'passed', 'releaseId': 'b' * 64, 'targets': 'owner-approved'}


@pytest.mark.parametrize('which',['contract','canary'])
@pytest.mark.parametrize('qualification',['owner-gated',None,'estimated','measured','provisional-emulated'])
def test_unqualified_target_receipt_makes_zero_pointer_puts(which,qualification):
    store=Pointer({'release_id':'a'*64,'previous_release_id':None})
    receipt=dict(passed(),targets=qualification)
    with pytest.raises(ValueError,match='measured|qualif'):
        gate_and_flip(store,bucket='fake',release_id='b'*64,previous_release_id='a'*64,
            expected_etag='original',contract=(lambda:receipt) if which=='contract' else passed,
            canary=(lambda:receipt) if which=='canary' else passed)
    assert store.puts==[] and store.etag=='original'
    assert store.value=={'release_id':'a'*64,'previous_release_id':None}


@pytest.mark.parametrize('which', ['canary', 'contract'])
def test_gate_failure_preserves_original_pointer_and_etag(which):
    store = Pointer({'release_id': 'a' * 64, 'previous_release_id': None})
    def fail(): raise RuntimeError('gate failed')
    with pytest.raises(RuntimeError, match='gate failed'):
        gate_and_flip(store, bucket='fake', release_id='b' * 64, previous_release_id='a' * 64,
                      expected_etag='original', canary=fail if which == 'canary' else passed,
                      contract=fail if which == 'contract' else passed)
    assert store.value == {'release_id': 'a' * 64, 'previous_release_id': None}
    assert store.etag == 'original' and not store.puts


@pytest.mark.parametrize('result', [{'status': 'incomplete'}, {'status': 'passed', 'releaseId': 'c' * 64}, None])
def test_gate_receipt_must_pass_for_exact_candidate(result):
    store = Pointer()
    with pytest.raises(ValueError):
        gate_and_flip(store, bucket='fake', release_id='b' * 64, previous_release_id=None,
                      expected_etag=None, canary=lambda: result, contract=passed)
    assert not store.puts


def test_success_first_publish_and_lost_race():
    for previous in [None, 'a' * 64]:
        store = Pointer({'release_id': previous} if previous else None)
        gate_and_flip(store, bucket='fake', release_id='b' * 64, previous_release_id=previous,
                      expected_etag=store.etag, canary=passed, contract=passed)
        assert store.value == {'release_id': 'b' * 64, 'previous_release_id': previous}
        assert store.puts[0]['CacheControl'] == 'no-store'
        assert store.puts[0].get('IfMatch') == ('original' if previous else None)
        assert store.puts[0].get('IfNoneMatch') == (None if previous else '*')
    store = Pointer({'release_id': 'a' * 64})
    def competing():
        store.value = {'release_id': 'c' * 64}; store.etag = 'competitor'; return passed()
    with pytest.raises(RuntimeError, match='lost pointer race'):
        gate_and_flip(store, bucket='fake', release_id='b' * 64, previous_release_id='a' * 64,
                      expected_etag='original', canary=competing, contract=passed)
    assert store.value == {'release_id': 'c' * 64}


def test_local_contract_precedes_upload_canary_and_contract_failure_stops_it():
    events = []
    store = Pointer()
    def check(name):
        events.append(name)
        return passed()
    gate_and_flip(store, bucket='fake', release_id='b' * 64, previous_release_id=None,
                  expected_etag=None, contract=lambda: check('contract'), canary=lambda: check('upload-canary'))
    assert events == ['contract', 'upload-canary']
    def refuse(): raise RuntimeError('local candidate refused')
    with pytest.raises(RuntimeError):
        gate_and_flip(Pointer(), bucket='fake', release_id='b' * 64, previous_release_id=None,
                      expected_etag=None, contract=refuse, canary=lambda: pytest.fail('upload reached'))


def test_real_canary_failure_against_hand_candidate_does_not_flip(tmp_path):
    """Synthetic hand fixture references absent saved bodies; real reader must refuse."""
    import os
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_fixture import build_fixture_release
    release = tmp_path / 'release'
    manifest = build_fixture_release(ROOT / 'model/fixtures/hand-release.json', output=release,
        scratch=tmp_path / 'job', engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']))
    store = Pointer({'release_id': 'a' * 64, 'previous_release_id': None})
    def canary():
        result = subprocess.run(['npm', 'run', 'canary:archive-local', '--workspaces=false', '--', '--release', str(release)],
            cwd=ROOT / 'apps/site', text=True, capture_output=True, timeout=70)
        assert result.returncode != 0
        assert 'Saved copy not found' in result.stderr
        raise RuntimeError('actual canary refused missing saved body')
    with pytest.raises(RuntimeError, match='actual canary refused'):
        gate_and_flip(store, bucket='fake', release_id=manifest['release_id'], previous_release_id='a' * 64,
                      expected_etag='original', canary=canary,
                      contract=lambda: {'status': 'passed', 'releaseId': manifest['release_id'], 'targets':'owner-approved'})
    assert store.etag == 'original' and not store.puts
    assert store.value == {'release_id': 'a' * 64, 'previous_release_id': None}


@pytest.mark.parametrize('name',['contract','canary'])
@pytest.mark.parametrize('receipt,message',[
    (None,'did not pass for the candidate'),
    ({'status':'incomplete'},'did not pass for the candidate'),
    ({'status':'passed','releaseId':'c'*64,'targets':'owner-approved'},'did not pass for the candidate'),
    (dict(passed(),targets='owner-gated'),'requires measured-target qualification'),
    (dict(passed(),targets=None),'requires measured-target qualification'),
    (dict(passed(),targets='estimated'),'requires measured-target qualification'),
    (passed(),None),
])
def test_shared_receipt_validator_and_final_gate_have_the_same_policy(name,receipt,message):
    from viewer_publication.archive_gate import validate_receipt
    original=dict(receipt) if isinstance(receipt,dict) else receipt
    store=Pointer()
    def standalone():return validate_receipt(receipt,release_id='b'*64,name=name)
    def final_gate():return gate_and_flip(store,bucket='fake',release_id='b'*64,
        previous_release_id=None,expected_etag=None,
        contract=(lambda:receipt) if name=='contract' else passed,
        canary=(lambda:receipt) if name=='canary' else passed)
    if message:
        for check in [standalone,final_gate]:
            with pytest.raises(ValueError) as error:check()
            assert str(error.value)==f'Archive {name} {message}'
        assert store.puts==[]
    else:
        assert standalone() is None
        final_gate()
        assert len(store.puts)==1
    assert receipt==original


def test_first_engine_release_replaces_the_actual_legacy_pointer_with_its_observed_etag():
    from io import BytesIO
    raw=(ROOT/'apps/site/scripts/fixtures/old-viewer-pointer.json').read_bytes()
    response=dict(Body=BytesIO(raw),ETag='observed-legacy-etag',ContentLength=len(raw))
    try:legacy=json.loads(response['Body'].read(response['ContentLength']))
    finally:response['Body'].close()
    assert 'catalog_id' in legacy and 'release_id' not in legacy
    store=Pointer(legacy);store.etag=response['ETag']
    gate_and_flip(store,bucket='fake',release_id='b'*64,previous_release_id=None,
        expected_etag=response['ETag'],contract=passed,canary=passed)
    assert store.value==dict(release_id='b'*64,previous_release_id=None)
    assert store.puts[0]['IfMatch']==response['ETag']
    assert 'IfNoneMatch' not in store.puts[0]


@pytest.mark.parametrize('previous',[None,'a'*64])
@pytest.mark.parametrize('etag',['',' ',0,True])
def test_blank_or_untyped_pointer_etags_refuse_before_reader_checks(previous,etag):
    store=Pointer({'release_id':'a'*64})
    def reached():pytest.fail('Invalid pointer binding reached a reader check')
    with pytest.raises(ValueError,match='pinned together'):
        gate_and_flip(store,bucket='fake',release_id='b'*64,previous_release_id=previous,
            expected_etag=etag,contract=reached,canary=reached)
    assert store.puts==[]


def test_existing_engine_release_requires_the_observed_etag_before_reader_checks():
    store=Pointer({'release_id':'a'*64})
    def reached():pytest.fail('Missing outgoing ETag reached a reader check')
    with pytest.raises(ValueError,match='pinned together'):
        gate_and_flip(store,bucket='fake',release_id='b'*64,previous_release_id='a'*64,
            expected_etag=None,contract=reached,canary=reached)
    assert store.puts==[]


@pytest.mark.parametrize('origin',[None,dict(kind='model'),dict(kind='model',display_only=False),
                                  dict(kind='model',display_only=True),dict(kind='unknown'),
                                  dict(kind='seed_v5',display_only=False),dict(kind='seed_v5',display_only=True)])
def test_emulated_target_receipts_require_an_admitted_release_origin(origin):
    store=Pointer();receipt=dict(passed(),targets='provisional-emulated')
    def flip():
        return gate_and_flip(store,bucket='fake',release_id='b'*64,previous_release_id=None,
            expected_etag=None,manifest_origin=origin,contract=lambda:receipt,canary=lambda:receipt)
    if isinstance(origin,dict) and origin.get('kind')=='model' and origin.get('display_only') is not True:
        flip();assert len(store.puts)==1
    else:
        with pytest.raises(ValueError,match='qualification'):flip()
        assert store.puts==[]
