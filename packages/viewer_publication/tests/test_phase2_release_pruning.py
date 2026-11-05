"""Phase-2 release pruning, external pin wire contract, and stale-pin handling."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from types import SimpleNamespace

import pytest

from test_archive_maintenance import BOUNDARY, LIVE, NOW, OLD, PINNED, PREVIOUS, RECENT, Store, add_input
from viewer_publication.archive_maintenance import (
    ARCHIVE_RELEASE_PINS,
    ArchiveMaintenanceStore,
    execute,
    load_spec,
    maintain_releases,
    prunable_release_ids,
    read_archive_release_pins,
)
from viewer_publication.archive_publish import SPICY_PINS, input_digest
from viewer_publication.receipt_pins import PREFIX, write_input_receipts

STALE_PIN = '1' * 64
SECOND_PIN = '2' * 64


def _add_entity_input(store, release, identity, entity_digests):
    record = add_input(store, release, identity)
    for key in list(store.objects):
        if key.startswith(PREFIX + release + '/inputs/'):
            del store.objects[key]
    record['entity_digests'] = dict(entity_digests)
    keys = ['receipts/documents/' + identity + '.jsonl.gz']
    record['input_digest'] = input_digest(
        receipt_keys=keys,
        provenance=record['provenance'],
        profile=record['profile'],
        entity_digests=record['entity_digests'],
    )
    return write_input_receipts(store, release, record['input_digest'], record, keys)


def test_read_archive_release_pins_validates_v1_wire_contract(tmp_path):
    payload = {
        'version': 1,
        'updated_at': '2026-10-30T18:00:00Z',
        'releases': [PINNED, SECOND_PIN, PINNED],
    }
    raw_bytes = json.dumps(payload).encode('utf-8')

    # Mapping, JSON string, bytes, local Path, and file:// URI
    assert read_archive_release_pins(payload) == [PINNED, SECOND_PIN]
    assert read_archive_release_pins(raw_bytes.decode('utf-8')) == [PINNED, SECOND_PIN]
    assert read_archive_release_pins(raw_bytes) == [PINNED, SECOND_PIN]

    pin_file = tmp_path / 'archive-releases.json'
    pin_file.write_bytes(raw_bytes)
    assert read_archive_release_pins(pin_file) == [PINNED, SECOND_PIN]
    assert read_archive_release_pins(str(pin_file)) == [PINNED, SECOND_PIN]
    assert read_archive_release_pins(pin_file.as_uri()) == [PINNED, SECOND_PIN]

    # Store with viewer-publications/pins/archive-releases.json
    store = Store()
    store.create(ARCHIVE_RELEASE_PINS, raw_bytes)
    assert read_archive_release_pins(store) == [PINNED, SECOND_PIN]

    # ArchiveMaintenanceStore SDK adapter
    class PinSDK:
        meta = SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts': 1}))

        def get_object(self, **request):
            assert request == {'Bucket': 'archive-fixture', 'Key': ARCHIVE_RELEASE_PINS}
            return {'Body': BytesIO(raw_bytes), 'ContentLength': len(raw_bytes)}

        def put_object(self, **request):
            raise AssertionError('Unexpected SDK PUT')

    sdk_store = ArchiveMaintenanceStore(client=PinSDK(), bucket='archive-fixture')
    assert sdk_store.read_archive_release_pins() == [PINNED, SECOND_PIN]
    assert read_archive_release_pins(sdk_store) == [PINNED, SECOND_PIN]


@pytest.mark.parametrize(
    'bad_source',
    [
        None,
        b'not-json',
        '{"unclosed": ',
        '[]',
        {'version': 2, 'updated_at': '2026-10-30T18:00:00Z', 'releases': [PINNED]},
        {'version': True, 'updated_at': '2026-10-30T18:00:00Z', 'releases': [PINNED]},
        {'version': '1', 'updated_at': '2026-10-30T18:00:00Z', 'releases': [PINNED]},
        {'version': 1, 'updated_at': '', 'releases': [PINNED]},
        {'version': 1, 'updated_at': '   ', 'releases': [PINNED]},
        {'version': 1, 'updated_at': None, 'releases': [PINNED]},
        {'version': 1, 'updated_at': '2026-10-30T18:00:00Z', 'releases': PINNED},
        {'version': 1, 'updated_at': '2026-10-30T18:00:00Z', 'releases': ['A' * 64]},
        {'version': 1, 'updated_at': '2026-10-30T18:00:00Z', 'releases': ['a' * 63]},
        {'version': 1, 'updated_at': '2026-10-30T18:00:00Z', 'releases': ['g' * 64]},
        {'version': 1, 'updated_at': '2026-10-30T18:00:00Z', 'releases': [123]},
        {'version': 1, 'updated_at': '2026-10-30T18:00:00Z', 'releases': [], 'extra': True},
        {'version': 1, 'releases': []},
    ],
)
def test_read_archive_release_pins_fails_closed_on_schema_or_parse_error(bad_source):
    with pytest.raises(ValueError):
        read_archive_release_pins(bad_source)


def test_configured_external_pin_source_failure_aborts_before_inventory_or_delete(tmp_path):
    store = Store()
    add_input(store, LIVE, 'live')
    add_input(store, PREVIOUS, 'previous')
    store.create(PREFIX + OLD + '/manifest.json', b'{}')
    store.times[PREFIX + OLD + '/manifest.json'] = NOW - timedelta(days=2)

    missing_path = tmp_path / 'missing-pins.json'
    with pytest.raises(ValueError):
        maintain_releases(store, now=NOW, external_pins_source=missing_path, execute=True)
    assert store.list_calls == 0 and store.deleted == []

    # Missing pin object in store when external_pins_source=store also fails closed
    with pytest.raises(ValueError):
        maintain_releases(store, now=NOW, external_pins_source=store, execute=True)
    assert store.list_calls == 0 and store.deleted == []


def test_stale_external_pins_are_recorded_without_crashing_kept_input_records():
    store = Store()
    add_input(store, LIVE, 'live')
    add_input(store, PREVIOUS, 'previous')
    add_input(store, PINNED, 'active-external')
    store.create(PREFIX + OLD + '/manifest.json', b'{}')
    store.times[PREFIX + OLD + '/manifest.json'] = NOW - timedelta(days=2)

    pin_doc = {
        'version': 1,
        'updated_at': '2026-10-30T18:00:00Z',
        'releases': [PINNED, STALE_PIN],
    }
    result = maintain_releases(
        store,
        now=NOW,
        external_pins_source=json.dumps(pin_doc),
        execute=True,
    )
    assert result['status'] == 'executed'
    assert result['stale_external_pins'] == [STALE_PIN]
    assert result['kept_releases'] == sorted([LIVE, PREVIOUS, PINNED, STALE_PIN])
    assert len(result['kept_inputs']) == 3
    assert result['delete_keys'] == [PREFIX + OLD + '/manifest.json']
    assert store.deleted == [PREFIX + OLD + '/manifest.json']


def test_missing_live_or_last_good_still_fails_closed_even_when_stale_external_pins_present():
    for missing_pointer_release in (LIVE, PREVIOUS):
        store = Store()
        add_input(store, LIVE, 'live')
        add_input(store, PREVIOUS, 'previous')
        for key in list(store.objects):
            if key.startswith(PREFIX + missing_pointer_release + '/'):
                del store.objects[key]
        store.create(PREFIX + OLD + '/manifest.json', b'{}')
        store.times[PREFIX + OLD + '/manifest.json'] = NOW - timedelta(days=2)

        with pytest.raises(ValueError, match='Kept release has no input record'):
            maintain_releases(store, now=NOW, external_pins=[STALE_PIN], execute=True)
        assert store.deleted == []


def test_partially_pruned_external_pin_without_input_record_is_treated_as_stale_without_crashing():
    store = Store()
    add_input(store, LIVE, 'live')
    add_input(store, PREVIOUS, 'previous')
    # PINNED still has release.json/manifest.json in releases/, but its inputs/<digest>.json was already pruned
    store.create(PREFIX + PINNED + '/release.json', b'{}')
    store.create(PREFIX + PINNED + '/manifest.json', b'{}')
    store.create(PREFIX + OLD + '/manifest.json', b'{}')
    store.times[PREFIX + OLD + '/manifest.json'] = NOW - timedelta(days=2)

    result = maintain_releases(store, now=NOW, external_pins=[PINNED], execute=True)
    assert result['status'] == 'executed'
    assert result['stale_external_pins'] == [PINNED]
    assert result['kept_releases'] == sorted([LIVE, PREVIOUS, PINNED])
    assert len(result['kept_inputs']) == 2
    assert result['delete_keys'] == [PREFIX + OLD + '/manifest.json']
    assert store.deleted == [PREFIX + OLD + '/manifest.json']

    # If LIVE or PREVIOUS lacks an input record (even if also in external_pins), it still fails closed
    for pointer_release in (LIVE, PREVIOUS):
        bad_store = Store()
        add_input(bad_store, LIVE, 'live')
        add_input(bad_store, PREVIOUS, 'previous')
        for key in list(bad_store.objects):
            if key.startswith(PREFIX + pointer_release + '/inputs/'):
                del bad_store.objects[key]
        bad_store.create(PREFIX + OLD + '/manifest.json', b'{}')
        bad_store.times[PREFIX + OLD + '/manifest.json'] = NOW - timedelta(days=2)
        with pytest.raises(ValueError, match='Kept release has no input record'):
            maintain_releases(bad_store, now=NOW, external_pins=[pointer_release, PINNED], execute=True)
        assert bad_store.deleted == []


def test_execute_fails_closed_before_deleting_releases_when_raw_verification_inputs_missing(tmp_path):
    from botocore.hooks import HierarchicalEmitter
    from congress_api.lake.daily import ALL_TABLE_NAMES

    deleted_keys = []
    release_list_calls = []

    class TrackingR2Client:
        meta = SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts': 1}), events=HierarchicalEmitter())

        def get_object(self, **request):
            raise AssertionError(f'Unexpected release GET before raw_verification: {request}')

        def put_object(self, **request):
            raise AssertionError(f'Unexpected PUT before raw_verification: {request}')

        def get_paginator(self, op):
            assert op == 'list_objects_v2'
            return SimpleNamespace(paginate=lambda **_: [{'Contents': [], 'IsTruncated': False}])

        def delete_object(self, **request):
            deleted_keys.append(request['Key'])
            return {}

        def list_objects_v2(self, **request):
            release_list_calls.append(request)
            raise AssertionError('Should not list or delete releases when raw_verification fails')

    class OkRuntime:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def verify_runtime(self):
            return {'verified': True}

    spec_payload = {
        'version': 1,
        'bucket': 'archive-fixture',
        'catalog_root': None,
        'work': str(tmp_path / 'maint-work'),
        'external_pins': [],
        'tables': {name: {'namespace': ['archive'], 'name': name} for name in ALL_TABLE_NAMES},
        'thresholds': {'file_count': 256, 'manifest_count': 64, 'scan_planning_seconds': 30.0},
        'engine_config': str(tmp_path / 'runtime.json'),
        'raw_verification': {
            'captures': str(tmp_path / 'missing-captures.parquet'),
            'receipt_inventory': str(tmp_path / 'missing-receipt-inventory.json'),
            'verification_inventory': str(tmp_path / 'missing-verification-inventory.json'),
            'apply_staged': True,
        },
    }
    spec_path = tmp_path / 'maintenance-spec.json'
    spec_path.write_text(json.dumps(spec_payload), encoding='utf-8')

    with pytest.raises(ValueError, match='raw_verification'):
        execute(
            spec_path,
            runtime_factory=lambda _: OkRuntime(),
            storage_factory=lambda **_: TrackingR2Client(),
            now=NOW,
            execute=True,
        )
    assert deleted_keys == []

    # (a) Corrupt captures.parquet fails inside verify_raw before maintain_releases deletes anything
    corrupt_captures = tmp_path / 'corrupt-captures.parquet'
    corrupt_captures.write_bytes(b'not-a-valid-parquet-file')
    receipt_inv = tmp_path / 'receipt-inventory.json'
    receipt_inv.write_text('[]', encoding='utf-8')
    verify_inv = tmp_path / 'verification-inventory.json'
    verify_inv.write_text('[]', encoding='utf-8')
    spec_payload['work'] = str(tmp_path / 'maint-work-corrupt')
    spec_payload['raw_verification'] = {
        'captures': str(corrupt_captures),
        'receipt_inventory': str(receipt_inv),
        'verification_inventory': str(verify_inv),
        'apply_staged': True,
    }
    spec_path.write_text(json.dumps(spec_payload), encoding='utf-8')

    import pyarrow as pa

    with pytest.raises((pa.ArrowInvalid, ValueError)):
        execute(
            spec_path,
            runtime_factory=lambda _: OkRuntime(),
            storage_factory=lambda **_: TrackingR2Client(),
            now=NOW,
            execute=True,
        )
    assert deleted_keys == [] and release_list_calls == []

    # (b) verify_raw returning valid=False (missing raw object) refuses release pruning before any delete
    import congress_api.retention.raw_verifier as raw_verifier_mod

    spec_payload['work'] = str(tmp_path / 'maint-work-invalid-raw')
    spec_path.write_text(json.dumps(spec_payload), encoding='utf-8')
    orig_verify = raw_verifier_mod.verify
    try:
        raw_verifier_mod.verify = lambda *a, **k: {'valid': False, 'missing_bodies': 1}
        with pytest.raises(RuntimeError, match='raw verification failed; refusing release pruning'):
            execute(
                spec_path,
                runtime_factory=lambda _: OkRuntime(),
                storage_factory=lambda **_: TrackingR2Client(),
                now=NOW,
                execute=True,
            )
    finally:
        raw_verifier_mod.verify = orig_verify
    assert deleted_keys == []


def test_execute_writes_spicy_generations_even_when_no_releases_are_deleted():
    store = Store()
    written_calls = []

    def record_spicy(generations):
        written_calls.append(list(generations))
        store.create(SPICY_PINS, json.dumps({'version': 1, 'generations': generations}).encode('utf-8'))

    store.write_spicy_generations = record_spicy
    _add_entity_input(store, LIVE, 'live', {'members': '1' * 64})
    _add_entity_input(store, PREVIOUS, 'previous', {'members': '1' * 64})
    _add_entity_input(store, PINNED, 'pinned', {'bills': '2' * 64})

    # RECENT is only 1 hour old, so delete_keys == []
    store.create(PREFIX + RECENT + '/manifest.json', b'{}')
    store.times[PREFIX + RECENT + '/manifest.json'] = NOW - timedelta(hours=1)

    result = maintain_releases(store, now=NOW, external_pins=[PINNED], execute=True)
    assert result['delete_keys'] == []
    assert store.deleted == []
    expected = [
        {'family': 'bills', 'digest': '2' * 64},
        {'family': 'members', 'digest': '1' * 64},
    ]
    assert result['spicy_generations'] == expected
    assert written_calls == [expected]
    assert json.loads(store.objects[SPICY_PINS]) == {'version': 1, 'generations': expected}


def test_prunable_release_ids_and_maintenance_job_spec_sections():
    from pathlib import Path

    newest = {
        LIVE: NOW - timedelta(days=5),
        PREVIOUS: NOW - timedelta(days=4),
        PINNED: NOW - timedelta(days=3),
        OLD: NOW - timedelta(days=2),
        BOUNDARY: NOW - timedelta(days=1),
        RECENT: NOW - timedelta(hours=2),
    }
    assert prunable_release_ids(newest, kept=[LIVE, PREVIOUS, PINNED], now=NOW) == [OLD]

    root = Path(__file__).resolve().parents[3]
    spec = load_spec(root / 'model/jobs/maintenance.json')
    assert spec['external_pins_source'] == 'https://data.spicygov.ai/pins/archive-releases.json'
    raw = spec['raw_verification']
    assert raw['captures']['kind'] == 'native_table'
    assert '/archive_r1b/captures/' in raw['captures']['metadata_location']
    assert raw['apply_staged'] is True
    assert not raw.keys() & {'receipt_inventory', 'verification_inventory'}
    assert 'lake_maintenance' in spec
    assert set(spec['lake_maintenance']) >= {'observations', 'rebuild', 'purge'}
