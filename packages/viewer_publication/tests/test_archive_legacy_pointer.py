"""First engine publication replaces the exact old pointer through its ETag."""
import json
import os
from pathlib import Path

import pytest

from archive_job_fixture import real_model_spec
from docspec_client.client import NativeDatasets
from test_archive_controller import Runtime
from test_archive_publish import Store

OLD=Path(__file__).parents[3]/'apps/site/scripts/fixtures/old-viewer-pointer.json'


def test_legacy_pointer_has_no_engine_predecessor_but_retains_exact_evidence(tmp_path):
    from viewer_publication.archive_publish import read_pointer
    store=Store();raw=OLD.read_bytes();store.objects['viewer-publications/manifest.json']=raw
    evidence=tmp_path/'outgoing.json'
    assert read_pointer(store,bucket='derived-fixture',evidence=evidence)==(None,'initial')
    assert evidence.read_bytes()==raw and len(raw)==1907
    store.objects['viewer-publications/manifest.json']=b'{"unexpected":"shape"}'
    with pytest.raises(ValueError,match='pointer'):
        read_pointer(store,bucket='derived-fixture')


def test_actual_model_first_flip_uses_old_etag_and_no_old_release(tmp_path):
    from viewer_publication.archive_controller import run_publish
    from viewer_publication.archive_model_job import load_spec
    spec,_,_=real_model_spec(tmp_path);path=tmp_path/'model.json';path.write_text(json.dumps(spec))
    store=Store();raw=OLD.read_bytes();store.objects['viewer-publications/manifest.json']=raw
    legacy_key='viewer-publications/releases/old-filename-viewer/index.html';store.objects[legacy_key]=b'legacy'
    def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        result=run_publish(load_spec(path),work=tmp_path/'publish',client=store,engine=Runtime(native,store),
            bucket='derived-fixture',receipt_keys=['receipts/documents/2026-10-27/slice.jsonl.gz'],provenance=[],
            run={'id':'first-engine'},public_origin='https://archive.fixture.test',contract=passed,canary=passed)
    assert result['status']=='published'
    pointer=json.loads(store.objects['viewer-publications/manifest.json'])
    assert pointer==dict(release_id=result['release_id'],previous_release_id=None)
    put=next(r for r in store.requests if r['Key']=='viewer-publications/manifest.json')
    assert put['IfMatch']=='initial' and 'IfNoneMatch' not in put
    assert (tmp_path/'publish/outgoing-pointer.json').read_bytes()==raw
    assert ('get',legacy_key) not in store.events and store.objects[legacy_key]==b'legacy'
