"""Completed-run checks read selected changes, not unrelated archive history."""
import importlib.util
import json
from pathlib import Path
from time import perf_counter

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from test_capture_verification import checkpoint, fixed_capture_clock, verifier
from congress_api.retention.raw_archive import CAPTURE_SCHEMA, STATE_SCHEMA, encode_table
from congress_api.retention.catalog_cache import capture_digest
from congress_api.retention.raw_storage import RawSnapshot, RawStorage

HELPERS = Path(__file__).resolve().parents[2] / "packages/congress_api/tests/native_memory_helpers.py"
SPEC = importlib.util.spec_from_file_location("capture_native_fixture", HELPERS)
helpers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helpers)


@pytest.fixture
def selected(checkpoint):
    store, summary = checkpoint
    captures = pq.read_table(pa.BufferReader(store.objects["indexes/captures.parquet"]))
    states = pq.read_table(pa.BufferReader(store.objects["indexes/download-state.parquet"])).cast(STATE_SCHEMA)
    owner = helpers.memory_raw_storage(store, max_state_rows=2)
    # An earlier capture must never be read to verify the completed run.
    previous = owner.publish(owner.prepare(owner.snapshot(), operation="older",
        captures=pa.Table.from_pylist([dict(source_file="ci/older", context_url="https://example.gov/older")],
                                    schema=CAPTURE_SCHEMA)))
    after = owner.publish(owner.prepare(previous, operation="completed",
        captures=captures, states=states,
        indexed_receipts=captures["receipt_key"].to_pylist()))
    summary["raw_selection"] = dict(before=previous.identity, after=after.identity)
    del store.objects["indexes/captures.parquet"]
    del store.objects["indexes/download-state.parquet"]
    store.reads.clear()
    owner.native.reads.clear()
    return store, summary, owner, previous, after


def test_native_verifier_reads_only_completed_changes_and_writes_nothing(selected, monkeypatch):
    store, summary, owner, previous, after = selected
    old_pins = {entry["release"]["dataset"]["dataset"]
                for entry in owner.capture_pages.entries(previous.manifest["captures"]["head"])}
    monkeypatch.setattr(RawSnapshot, "captures", lambda *_: pytest.fail("Full capture scan"))
    monkeypatch.setattr(RawSnapshot, "states", lambda *_: pytest.fail("Full state scan"))
    before, writes, native_writes = dict(store.objects), list(store.writes), list(owner.native.writes)
    result = verifier.verify_run(store, summary, raw_storage=owner)
    assert result["verified"] and result["state_matches_receipts"]
    assert result["receipts"] == result["capture_references"] == 3
    assert result["raw_selection"] == summary["raw_selection"]
    assert result["unique_bodies_verified"] == 2
    assert not old_pins.intersection(owner.native.reads)
    assert store.objects == before and store.writes == writes
    assert owner.native.writes == native_writes


@pytest.mark.parametrize("damage", ["after", "before", "missing"])
def test_native_verifier_requires_the_exact_selected_change_interval(selected, damage):
    store, summary, owner, _, _ = selected
    if damage == "missing":
        del summary["raw_selection"]
    else:
        summary["raw_selection"][damage] = "0" * 64
    with pytest.raises((verifier.VerificationError, ValueError)):
        verifier.verify_run(store, summary, raw_storage=owner)
    assert not owner.native.reads


@pytest.mark.parametrize("field", ["known_urls", "url_outcomes", "urls_by_source_family"])
def test_native_verifier_checks_retained_state_totals(selected, field):
    store, summary, owner, _, _ = selected
    if field == "known_urls":
        summary["accounting"][field] += 1
    else:
        key = next(iter(summary["accounting"][field]))
        summary["accounting"][field][key] += 1
    with pytest.raises(verifier.VerificationError, match="Saved-state .* accounting mismatch"):
        verifier.verify_run(store, summary, raw_storage=owner)


def test_native_verifier_refuses_state_changed_since_completed_run(selected):
    store, summary, owner, _, after = selected
    row = after.states().to_pylist()[0]
    owner.publish(owner.prepare(after, operation="later", states=[{**row, "outcome": "timeout"}]))
    with pytest.raises(verifier.VerificationError, match="selection"):
        verifier.verify_run(store, summary, raw_storage=owner)


def test_native_verifier_retains_body_integrity_checks(selected):
    store, summary, owner, _, _ = selected
    key = next(key for key in store.objects if key.startswith("bodies/"))
    store.objects[key] += b"corrupt"
    with pytest.raises(verifier.VerificationError, match="Stored body hash/length"):
        verifier.verify_run(store, summary, raw_storage=owner)


def test_unchanged_zero_attempt_run_needs_no_native_payload_reads(selected):
    store, summary, owner, _, after = selected
    summary.update(run_id="20261006T020304Z-abcdef123456", attempted=0,
                   timeout=0, saved=0, request_failed=0, body_metadata={},
                   raw_selection=dict(before=after.identity, after=after.identity))
    summary["accounting"]["capture_tasks_completed"] = 0
    result = verifier.verify_run(store, summary, raw_storage=owner)
    assert result["verified"] and result["receipts"] == 0
    assert result["known_urls"] == 3
    assert owner.native.reads == []


@pytest.mark.parametrize("unrelated", [10, 1000])
def test_verification_cost_excludes_unrelated_payloads(checkpoint, unrelated, record_property):
    store, summary = checkpoint
    additions = pq.read_table(pa.BufferReader(store.objects["indexes/captures.parquet"]))
    changes = pq.read_table(pa.BufferReader(store.objects["indexes/download-state.parquet"])).cast(STATE_SCHEMA)
    old_captures = pa.Table.from_pylist([
        dict(source_file="ci/old", context_url=f"https://example.gov/old-{n}")
        for n in range(unrelated)], schema=CAPTURE_SCHEMA)
    old_state = pa.Table.from_pylist([
        dict(url=f"https://example.gov/old-{n}", outcome="pending", family="documents")
        for n in range(unrelated)], schema=STATE_SCHEMA)
    captures, state = pa.concat_tables([old_captures, additions]), pa.concat_tables([old_state, changes])
    store.objects["indexes/captures.parquet"] = encode_table(captures)
    store.objects["indexes/download-state.parquet"] = encode_table(state.replace_schema_metadata({
        b"capture_rows": str(len(captures)).encode(),
        b"capture_digest": capture_digest(captures).encode()}))
    summary["accounting"]["known_urls"] += unrelated
    summary["accounting"]["url_outcomes"]["pending"] += unrelated
    summary["accounting"]["urls_by_source_family"]["documents"] = unrelated
    store.reads.clear()
    started = perf_counter()
    legacy = verifier.verify_legacy_run(store, summary)
    legacy_seconds = perf_counter() - started
    legacy_bytes = sum(len(store.objects.get(key, b"")) for key in store.reads)

    owner = helpers.memory_raw_storage(store, max_state_rows=4)
    before = owner.publish(owner.prepare(owner.snapshot(), operation="old",
        captures=old_captures, states=old_state))
    after = owner.publish(owner.prepare(before, operation="run", captures=additions, states=changes,
        indexed_receipts=additions["receipt_key"].to_pylist()))
    summary["raw_selection"] = dict(before=before.identity, after=after.identity)
    del store.objects["indexes/captures.parquet"]
    del store.objects["indexes/download-state.parquet"]
    owner = RawStorage(store, owner.native, max_state_rows=4)
    store.reads.clear()
    owner.native.reads.clear()
    started = perf_counter()
    current = verifier.verify_run(store, summary, raw_storage=owner)
    native_seconds = perf_counter() - started
    native_rows = sum(len(owner.native.tables[key]) for key in owner.native.reads)
    for key, value in legacy.items():
        assert current[key] == value
    assert native_rows <= len(additions) + 4 * 2  # Two attempted URLs; bounded state leaves.
    record_property("verification_cost", json.dumps(dict(unrelated=unrelated,
        legacy_object_bytes=legacy_bytes, legacy_seconds=legacy_seconds,
        native_application_object_bytes=sum(len(store.objects.get(key, b"")) for key in store.reads),
        native_arrow_bytes=sum(owner.native.tables[key].nbytes for key in owner.native.reads),
        native_rows=native_rows, native_seconds=native_seconds,
        scope="In-memory native transport; application reads and logical Arrow bytes, not provider I/O",
        fresh_domain_owner=True, test_state_leaf_rows=4, writes=0)))
