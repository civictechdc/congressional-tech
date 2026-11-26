"""1C-2 synchronization tests: body_text + SpicyEngine sync gated ahead of manifest flips."""
from __future__ import annotations

from hashlib import md5, sha256
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from test_archive_publish import Native, StorageError, Store, candidate, encoded, launch, record
from test_archive_publish_job import publish_spec
from viewer_publication import archive_publish, archive_publish_job, body_text_publish
from viewer_publication.archive_format import release_identity


@pytest.fixture(autouse=True)
def stub_release_gates(monkeypatch):
    calls = []
    monkeypatch.setattr(archive_publish, 'require_release_gates', lambda *a, **k: calls.append((a, k)))
    return calls


def _candidate_with_detail(root: Path, *, list_bytes: bytes, detail_bytes: bytes):
    out = root / 'release'
    out.mkdir(parents=True)
    (out / 'list.parquet').write_bytes(list_bytes)
    (out / 'detail.parquet').write_bytes(detail_bytes)
    files = [
        dict(name='detail.parquet', sha256=sha256(detail_bytes).hexdigest(),
             md5=md5(detail_bytes).hexdigest(), size=len(detail_bytes), rows=1),
        dict(name='list.parquet', sha256=sha256(list_bytes).hexdigest(),
             md5=md5(list_bytes).hexdigest(), size=len(list_bytes), rows=1),
    ]
    rid = release_identity(1, files)
    manifest = dict(schema_version=1, files=files, facet_counts=[], release_id=rid)
    manifest_path = out / 'manifest.json'
    manifest_path.write_bytes(encoded(manifest))
    res_path = root / 'result.json'
    res_path.write_bytes(encoded(dict(outputs=files, queries=[
        dict(name=q, data=[dict(violation=0)])
        for q in ['invariants', 'model_invariants', 'url_state_invariants', 'profile_completeness']
    ])))
    artifacts = dict(
        release=out,
        manifest_pin=dict(path=str(manifest_path), sha256=sha256(manifest_path.read_bytes()).hexdigest(),
                          size=manifest_path.stat().st_size),
        result_pin=dict(path=str(res_path), sha256=sha256(res_path.read_bytes()).hexdigest(),
                        size=res_path.stat().st_size),
    )
    return artifacts, manifest


class SyncStore(Store):
    """In-memory R2 store supporting paged listings and deletes for staged promotion."""

    def __init__(self):
        super().__init__()
        self.clock = 0
        self.modified = {}

    def put_object(self, **request):
        res = super().put_object(**request)
        self.clock += 1
        self.modified[request['Key']] = self.clock
        return res

    def get_object(self, *, Bucket, Key):
        resp = super().get_object(Bucket=Bucket, Key=Key)
        resp['LastModified'] = self.modified.get(Key, 0)
        return resp

    def list_objects_v2(self, *, Bucket, Prefix='', **kwargs):
        return dict(
            Contents=[
                dict(Key=key, LastModified=self.modified.get(key, 0), Size=len(self.objects[key]))
                for key in sorted(self.objects)
                if key.startswith(Prefix)
            ],
            IsTruncated=False,
        )

    def delete_object(self, *, Bucket, Key):
        self.events.append(('delete', Key))
        if Key not in self.objects:
            raise StorageError(404)
        del self.objects[Key]


def _stage_body_text_export(store: SyncStore, *, bucket: str, release_id: str, detail_entry: dict,
                            payload: bytes, live: bool = False) -> dict:
    digest = sha256(payload).hexdigest()
    key = f'derived/body_text/{digest}.parquet'
    store.objects[key] = payload
    store.clock += 1
    store.modified[key] = store.clock
    pointer = dict(
        version=1,
        key=key,
        sha256=digest,
        bytes=len(payload),
        rows=1,
        release_id=release_id,
        detail={'sha256': detail_entry['sha256'], 'size': detail_entry['size']},
    )
    ptr_key = 'derived/body_text/current.json' if live else body_text_publish.STAGED_POINTER_KEY
    store.put_object(
        Bucket=bucket,
        Key=ptr_key,
        Body=encoded(pointer),
        ContentLength=len(encoded(pointer)),
        ContentType='application/json',
        CacheControl='no-store',
    )
    return pointer


def test_stage_sync_commit_orders_body_text_and_spicyengine_before_manifest_flip(tmp_path):
    store = SyncStore()
    native = Native(store)

    # Publish initial release r_old.
    first_dir = tmp_path / 'first'
    first_artifacts, first_manifest = candidate(first_dir, payload=b'release-one-list')
    r_old = first_manifest['release_id']
    first_res, _, _ = launch(first_dir, store=store, native=native, artifacts=first_artifacts)
    assert first_res['status'] == 'published'
    first_detail = dict(name='detail.parquet', sha256=sha256(b'detail-1').hexdigest(),
                        md5=md5(b'detail-1').hexdigest(), size=8, rows=1)
    _stage_body_text_export(store, bucket='derived-fixture', release_id=r_old,
                            detail_entry=first_detail, payload=b'PAR1-bt-1-PAR1', live=True)

    # Build second candidate r_new with a real detail.parquet entry.
    second_dir = tmp_path / 'second'
    second_artifacts, second_manifest = _candidate_with_detail(
        second_dir, list_bytes=b'release-two-list', detail_bytes=b'detail-two-bytes',
    )
    r_new = second_manifest['release_id']
    files = second_manifest['files']

    pointer, etag = archive_publish.read_pointer(store, bucket='derived-fixture')
    input_record, keys = record()
    passed = lambda **ctx: dict(status='passed', releaseId=ctx['release_id'], targets='owner-approved')

    # Stage r_new without flipping live manifest.json.
    staged_res = archive_publish.publish_candidate(
        client=store, engine=native, bucket='derived-fixture', work=second_dir / 'publish',
        **second_artifacts, input_record=input_record, receipt_keys=keys,
        pointer=pointer, expected_etag=etag, public_origin='https://archive.example.test',
        canary=passed, contract=passed, base_release=second_dir / 'base-release',
        stage_only=True,
    )
    assert staged_res['status'] == 'staged'
    assert json.loads(store.objects['viewer-publications/manifest.json'])['release_id'] == r_old
    assert json.loads(store.objects[archive_publish.STAGED_POINTER])['release_id'] == r_new

    # Write staged-publication.json and publish spec for commit_staged().
    job_dir = tmp_path / 'job'
    job_dir.mkdir(parents=True, exist_ok=True)
    spec = publish_spec(job_dir)
    spec['bucket'] = 'derived-fixture'
    spec['_model'] = {'captures': {'kind': 'parquet'}}
    work_dir = Path(spec['work'])
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / 'staged-publication.json').write_text(json.dumps(dict(
        status='staged', bucket='derived-fixture', **staged_res['staged'],
    )))

    # Stage body_text export for r_new (still leaves live pointers on r_old!).
    bt_new_ptr = _stage_body_text_export(
        store, bucket='derived-fixture', release_id=r_new, detail_entry=files[0],
        payload=b'PAR1-bt-2-PAR1', live=False,
    )
    assert json.loads(store.objects['derived/body_text/current.json'])['release_id'] == r_old

    # Simulate SpicyEngine warming up after trigger and switching to r_new before flip!
    timeline = []
    engine_state = {'release_id': r_old, 'polls': 0}

    def fake_trigger(rid):
        timeline.append(('trigger', rid))
        # While SpicyEngine is indexing, live manifest is STILL r_old!
        assert json.loads(store.objects['viewer-publications/manifest.json'])['release_id'] == r_old

    def fake_health(url, timeout):
        engine_state['polls'] += 1
        timeline.append(('health', engine_state['polls']))
        if engine_state['polls'] >= 3:
            engine_state['release_id'] = r_new
        return {'release_id': engine_state['release_id'], 'serenedb': {'connected': True}}

    now = [0.0]
    committed = archive_publish_job.commit_staged(
        spec,
        storage_factory=lambda **_: store,
        spicyengine_origin='https://spicyengine.example.test',
        spicyengine_timeout=30.0,
        health_fetcher=fake_health,
        sync_trigger=fake_trigger,
        clock=lambda: now[0],
        sleep=lambda dt: now.__setitem__(0, now[0] + dt),
    )
    assert committed['status'] == 'published'
    assert committed['live_release'] == r_new
    assert committed['body_text']['status'] == 'promoted'
    assert json.loads(store.objects['viewer-publications/manifest.json'])['release_id'] == r_new
    assert json.loads(store.objects['derived/body_text/current.json']) == bt_new_ptr
    assert archive_publish.STAGED_POINTER not in store.objects
    assert body_text_publish.STAGED_POINTER_KEY not in store.objects
    # Old body_text parquet retired after promotion; new parquet retained.
    assert bt_new_ptr['key'] in store.objects
    assert not any(k.endswith(f"{sha256(b'PAR1-bt-1-PAR1').hexdigest()}.parquet") for k in store.objects)
    # Trigger ran before the live manifest flip.
    assert timeline[0] == ('health', 1)
    assert timeline[1] == ('trigger', r_new)
    assert engine_state['release_id'] == r_new


@pytest.mark.parametrize('failure_mode', ['missing_body_text', 'mismatched_body_text', 'spicyengine_stale', 'spicyengine_disconnected'])
def test_failure_or_mismatch_blocks_flip_and_keeps_live_pointers_intact(tmp_path, failure_mode):
    store = SyncStore()
    native = Native(store)

    first_dir = tmp_path / 'first'
    first_artifacts, first_manifest = candidate(first_dir, payload=b'release-one')
    r_old = first_manifest['release_id']
    launch(first_dir, store=store, native=native, artifacts=first_artifacts)
    first_detail = dict(name='detail.parquet', sha256=sha256(b'detail-1').hexdigest(),
                        md5=md5(b'detail-1').hexdigest(), size=8, rows=1)
    _stage_body_text_export(store, bucket='derived-fixture', release_id=r_old,
                            detail_entry=first_detail, payload=b'PAR1-bt-1-PAR1', live=True)

    second_dir = tmp_path / 'second'
    second_artifacts, second_manifest = _candidate_with_detail(
        second_dir, list_bytes=b'release-two', detail_bytes=b'detail-two',
    )
    r_new = second_manifest['release_id']
    second_detail = second_manifest['files'][0]
    pointer, etag = archive_publish.read_pointer(store, bucket='derived-fixture')
    input_record, keys = record()
    passed = lambda **ctx: dict(status='passed', releaseId=ctx['release_id'], targets='owner-approved')
    staged_res = archive_publish.publish_candidate(
        client=store, engine=native, bucket='derived-fixture', work=second_dir / 'publish',
        **second_artifacts, input_record=input_record, receipt_keys=keys,
        pointer=pointer, expected_etag=etag, public_origin='https://archive.example.test',
        canary=passed, contract=passed, base_release=second_dir / 'base-release',
        stage_only=True,
    )

    job_dir = tmp_path / 'job'
    job_dir.mkdir(parents=True, exist_ok=True)
    spec = publish_spec(job_dir)
    spec['bucket'] = 'derived-fixture'
    spec['_model'] = {'captures': {'kind': 'parquet'}}
    work_dir = Path(spec['work'])
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / 'staged-publication.json').write_text(json.dumps(dict(
        status='staged', bucket='derived-fixture', **staged_res['staged'],
    )))

    if failure_mode == 'mismatched_body_text':
        _stage_body_text_export(
            store, bucket='derived-fixture', release_id='f' * 64,
            detail_entry=second_detail, payload=b'PAR1-bt-wrong-PAR1', live=False,
        )
    elif failure_mode in ('spicyengine_stale', 'spicyengine_disconnected'):
        _stage_body_text_export(
            store, bucket='derived-fixture', release_id=r_new,
            detail_entry=second_detail, payload=b'PAR1-bt-2-PAR1', live=False,
        )

    now = [0.0]
    def health(url, timeout):
        if failure_mode == 'spicyengine_disconnected':
            return {'release_id': r_new, 'serenedb': {'connected': False}}
        return {'release_id': r_old, 'serenedb': {'connected': True}}

    # Note candidate() has no detail.parquet; inject detail_entry check only when present.
    before_events = len(store.events)
    with pytest.raises((ValueError, RuntimeError)):
        archive_publish_job.commit_staged(
            spec,
            storage_factory=lambda **_: store,
            spicyengine_origin='https://spicyengine.example.test',
            spicyengine_timeout=10.0,
            health_fetcher=health,
            clock=lambda: now[0],
            sleep=lambda dt: now.__setitem__(0, now[0] + dt),
        )

    # Zero manifest or body_text pointer flips occurred!
    assert json.loads(store.objects['viewer-publications/manifest.json'])['release_id'] == r_old
    assert json.loads(store.objects['derived/body_text/current.json'])['release_id'] == r_old
    assert not any(
        ev == ('put', 'viewer-publications/manifest.json') or ev == ('put', 'derived/body_text/current.json')
        for ev in store.events[before_events:]
    )


def test_archive_workflow_and_spicyengine_timer_align_pre_flip_sync():
    root = Path(__file__).resolve().parents[3]
    wf = yaml.load((root / '.github/workflows/archive-jobs.yml').read_text(), Loader=yaml.BaseLoader)
    steps = wf['jobs']['publish']['steps']
    pub_idx = next(i for i, s in enumerate(steps) if s.get('run', '').endswith('run-archive-job.py publish --keep-candidate'))
    bt_idx = next(i for i, s in enumerate(steps) if 'viewer_publication.body_text_publish' in s.get('run', ''))
    commit_idx = next(i for i, s in enumerate(steps) if '--commit-staged' in s.get('run', ''))
    mcp_idx = next(i for i, s in enumerate(steps) if s.get('name') == 'Confirm the hosted MCP serves the selected release')
    assert pub_idx < bt_idx < commit_idx < mcp_idx
    assert steps[pub_idx]['env']['ARCHIVE_STAGE_ONLY'] == 'true'
    assert '--prefer-staged' in steps[bt_idx]['run'] and '--stage-only' in steps[bt_idx]['run']
    assert 'SPICYENGINE_ORIGIN' in steps[commit_idx]['env']

    timer = (root / 'deploy/spicyengine/spicyengine-update.timer').read_text()
    assert 'OnCalendar=*:*:00' in timer
    update_sh = (root / 'deploy/spicyengine/update.sh').read_text()
    assert '--prefer-staged' in update_sh
