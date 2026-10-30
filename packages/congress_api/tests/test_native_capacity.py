"""Admission accounts for application preparation and the native owner's scratch."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from congress_api.retention import native_capacity as capacity


def client(tmp_path, scratch=100):
    limits = tmp_path / "limits.json"
    limits.write_text(json.dumps({"scratch_bytes": scratch}))
    return SimpleNamespace(workspace=tmp_path / "native", limits=limits)


def filesystem(monkeypatch, free=1000, devices=None):
    monkeypatch.setattr(capacity, "_filesystem", lambda path: (
        (devices or {}).get(Path(path).name, 1), str(path), free))


def test_same_filesystem_adds_native_and_preparation_once(tmp_path, monkeypatch):
    filesystem(monkeypatch)
    receipt = capacity.require_adoption_capacity(client(tmp_path), tmp_path / "stage",
                                                 200, headroom_bytes=50)
    assert receipt["filesystems"][0]["required_free_bytes"] == 350
    assert receipt["native_scratch_bytes"] == 100
    assert not (tmp_path / "stage").exists()
    assert not (tmp_path / "native").exists()


def test_retained_stage_is_not_charged_twice_or_modified(tmp_path, monkeypatch):
    filesystem(monkeypatch, free=260)
    stage = tmp_path / "stage"
    stage.mkdir()
    retained = stage / "retained.parquet"
    retained.write_bytes(b"x" * 100)
    receipt = capacity.require_adoption_capacity(client(tmp_path), stage, 200,
                                                 headroom_bytes=50)
    assert receipt["staging_retained_bytes"] == 100
    assert receipt["filesystems"][0]["required_free_bytes"] == 250
    assert retained.read_bytes() == b"x" * 100


def test_separate_filesystems_keep_independent_requirements(tmp_path, monkeypatch):
    filesystem(monkeypatch, free=260, devices={"stage": 1, "native": 2})
    receipt = capacity.require_adoption_capacity(client(tmp_path), tmp_path / "stage",
                                                 200, headroom_bytes=50)
    assert sorted(row["required_free_bytes"] for row in receipt["filesystems"]) == [150, 250]


def test_insufficient_space_refuses_without_creating_stage(tmp_path, monkeypatch):
    filesystem(monkeypatch, free=349)
    with pytest.raises(capacity.AdoptionCapacityError) as caught:
        capacity.require_adoption_capacity(client(tmp_path), tmp_path / "stage",
                                            200, headroom_bytes=50)
    assert caught.value.receipt["filesystems"][0]["required_free_bytes"] == 350
    assert "1 additional bytes" in str(caught.value)
    assert not (tmp_path / "stage").exists()


@pytest.mark.parametrize("invalid", [True, 0, -1, 1.5, "100"])
def test_invalid_native_limits_refuse(tmp_path, monkeypatch, invalid):
    filesystem(monkeypatch)
    with pytest.raises(ValueError, match="scratch_bytes"):
        capacity.require_adoption_capacity(client(tmp_path, invalid), tmp_path / "stage",
                                            200, headroom_bytes=50)


def test_missing_override_uses_qualified_native_default(tmp_path, monkeypatch):
    filesystem(monkeypatch, free=100 << 30)
    native = SimpleNamespace(workspace=tmp_path / "native", limits=None)
    receipt = capacity.require_adoption_capacity(native, tmp_path / "stage", 200)
    assert receipt["native_scratch_bytes"] == 32 << 30
    assert receipt["headroom_bytes"] == 8 << 30


def test_stage_symlinks_are_not_counted_as_owned_preparation(tmp_path, monkeypatch):
    filesystem(monkeypatch)
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "external").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="symlink"):
        capacity.require_adoption_capacity(client(tmp_path), stage, 200,
                                            headroom_bytes=50)


def test_preparation_estimate_uses_uncompressed_metadata_not_payload(monkeypatch):
    metadata = SimpleNamespace(num_rows=3, num_row_groups=2,
        row_group=lambda i: SimpleNamespace(total_byte_size=[100, 200][i]))
    assert capacity.preparation_budget(metadata) == 3 * 300 + 4096 * 3 + (1 << 20)


def test_progress_rechecks_space_without_walking_retained_files(tmp_path, monkeypatch):
    filesystem(monkeypatch, free=1000)
    receipt = capacity.require_adoption_capacity(
        client(tmp_path), tmp_path / "stage", 200, headroom_bytes=50)
    monkeypatch.setattr(capacity, "_retained_bytes",
                        lambda path: pytest.fail("Progress rescanned staging"))
    filesystem(monkeypatch, free=250)
    current = capacity.recheck_adoption_capacity(receipt, 100)
    assert current["filesystems"][0]["required_free_bytes"] == 250
    filesystem(monkeypatch, free=249)
    with pytest.raises(capacity.AdoptionCapacityError):
        capacity.recheck_adoption_capacity(current, 100)


def test_progress_keeps_separate_volume_headroom(tmp_path, monkeypatch):
    devices = {"stage": 1, "native": 2}
    filesystem(monkeypatch, free=1000, devices=devices)
    receipt = capacity.require_adoption_capacity(
        client(tmp_path), tmp_path / "stage", 200, headroom_bytes=50)
    filesystem(monkeypatch, free=150, devices=devices)
    current = capacity.recheck_adoption_capacity(receipt, 200)
    assert sorted(row["required_free_bytes"] for row in current["filesystems"]) == [50, 150]


def test_inspect_operator_status_reports_reusable_phases_producer_inputs_and_redacts_secrets(tmp_path, monkeypatch):
    filesystem(monkeypatch, free=2000)
    stage = tmp_path / "stage"
    stage.mkdir()
    secret = "super-secret-catalog-token-value"
    state = dict(
        latest=None,
        versions=[],
        incomplete_operations=[],
        producer_inputs=[],
    )

    class OperatorNative:
        workspace = tmp_path / "native"
        limits = client(tmp_path, scratch=100).limits
        _remote_secrets = {"DOCSPEC_CATALOG_TOKEN": secret}

        def inspect(self, dataset):
            return dict(
                dataset=dict(namespace="prod", dataset=dataset),
                latest=state["latest"],
                versions=list(state["versions"]),
                incomplete_operations=list(state["incomplete_operations"]),
            )

        def retained_producer_inputs(self):
            return list(state["producer_inputs"])

    native = OperatorNative()

    # 1. Pending state before preparation or native versions exist.
    pending = capacity.inspect_operator_status(
        native, "catalog-sources", stage_directory=stage, staging_budget_bytes=300, headroom_bytes=50
    )
    assert pending["phase"] == "pending"
    assert pending["capacity_sufficient"] is True
    assert "process_rss_bytes" in pending["resources"]["unavailable"]

    # 2. Preparing -> Prepared -> Ordered reusable staging phases.
    (stage / "request.json").write_text(json.dumps({"preparation_key": f"prep-{secret}"}))
    (stage / "part-00000000.json").write_text(json.dumps({"rows": 12}))
    preparing = capacity.inspect_operator_status(
        native, "catalog-sources", stage_directory=stage, staging_budget_bytes=300, headroom_bytes=50
    )
    assert preparing["phase"] == "preparing"
    assert preparing["preparation"]["parts_completed"] == 1
    assert preparing["preparation"]["rows_prepared"] == 12
    assert secret not in json.dumps(preparing)
    assert preparing["preparation"]["preparation_key"] == "prep-[REDACTED]"

    (stage / "complete.json").write_text(json.dumps({"rows": 12, "parts": 1}))
    prepared = capacity.inspect_operator_status(
        native, "catalog-sources", stage_directory=stage, staging_budget_bytes=300, headroom_bytes=50
    )
    assert prepared["phase"] == "prepared"
    assert prepared["preparation"]["source_preparation_completed"] is True

    (stage / "ordered.parquet").write_bytes(b"P" * 64)
    (stage / "ordered.json").write_text(json.dumps({"rows": 12}))
    ordered = capacity.inspect_operator_status(
        native,
        "catalog-sources",
        stage_directory=stage,
        staging_budget_bytes=500,
        headroom_bytes=50,
        preparation_reads={"sort_spill_peak_bytes": 4096, "sort_buffer_peak_bytes": 8192},
        preparation_metrics={"index_bytes": 1024, "staging_bytes": 2048},
    )
    assert ordered["phase"] == "ordered"
    assert ordered["preparation"]["ordered_derivative_completed"] is True
    assert ordered["resources"]["measured"]["ordered_derivative_bytes"] == 64
    assert ordered["resources"]["measured"]["sort_spill_peak_bytes"] == 4096
    assert ordered["resources"]["estimated"]["staging_budget_bytes"] == 500

    # 3. Lost-response state with retained local producer input.
    req_dir = tmp_path / "native/request-01"
    req_dir.mkdir(parents=True)
    req_file = req_dir / "request.json"
    req_file.write_text(json.dumps({
        "dataset": "catalog-sources",
        "operation": f"op-lost-{secret}",
        "expected_digest": "a" * 64,
    }))
    state["producer_inputs"] = [dict(input=str(req_dir / "source.parquet"), request=str(req_file), bytes=256)]
    lost = capacity.inspect_operator_status(
        native, "catalog-sources", stage_directory=stage, staging_budget_bytes=500, headroom_bytes=50
    )
    assert lost["phase"] == "lost-response-recovery-required"
    assert lost["outstanding_producer_bytes"] == 256
    assert lost["retained_producer_inputs"][0]["operation"] == "op-lost-[REDACTED]"
    assert secret not in json.dumps(lost)

    # 4. Early capacity refusal vs non-throwing status report.
    filesystem(monkeypatch, free=100)
    with pytest.raises(capacity.AdoptionCapacityError):
        capacity.inspect_operator_status(
            native, "catalog-sources", stage_directory=stage, staging_budget_bytes=500, headroom_bytes=50
        )
    insufficient = capacity.inspect_operator_status(
        native,
        "catalog-sources",
        stage_directory=stage,
        staging_budget_bytes=500,
        headroom_bytes=50,
        allow_insufficient_capacity=True,
    )
    assert insufficient["capacity_sufficient"] is False


def test_plan_protected_retention_protects_selected_releases_readers_incomplete_ops_and_producer_inputs(tmp_path):
    secret = "private-s3-secret-key"

    class RetentionNative:
        workspace = tmp_path / "native"
        _remote_secrets = {"DOCSPEC_S3_SECRET_ACCESS_KEY": secret}

        def __init__(self):
            self.incomplete = []
            self.producer = []
            self.removals = []

        def inspect(self, dataset):
            return dict(
                dataset=dict(namespace="ns-prod", dataset=dataset),
                latest=dict(id="rel-current"),
                versions=[dict(id="rel-old"), dict(id="rel-current")],
                incomplete_operations=list(self.incomplete),
            )

        def retained_producer_inputs(self):
            return list(self.producer)

        def inspect_retention(self, objects):
            results = []
            for obj in objects:
                path = obj["path"] if isinstance(obj, dict) else str(obj)
                results.append(dict(
                    path=path,
                    bytes=128,
                    protected=("native-pinned" in path),
                    status="protected" if "native-pinned" in path else "unreferenced",
                ))
            return results

        def plan_removal(self, request):
            self.removals.append(request)
            return dict(id=request["id"], objects=list(request["objects"]), reason=request["reason"])

    native = RetentionNative()
    app_pin = dict(
        id="rel-old",
        dataset=dict(namespace="ns-prod", dataset="catalog-sources"),
        objects=["s3://bucket/data/rel-old-part-0.parquet"],
    )
    export_pin = dict(
        id="exp-v1",
        dataset=dict(namespace="ns-prod", dataset="catalog-sources"),
        objects=["s3://bucket/exports/exp-v1.parquet"],
    )
    objects = [
        "s3://bucket/data/rel-old-part-0.parquet",
        "s3://bucket/exports/exp-v1.parquet",
        "s3://bucket/data/native-pinned.parquet",
        "s3://bucket/data/orphan-01.parquet",
    ]

    # Quiescent inspection classifies protected vs reclaimable accurately.
    plan = capacity.plan_protected_retention(
        native,
        "catalog-sources",
        namespace="ns-prod",
        objects=objects,
        application_pins=[app_pin],
        export_pins=[export_pin],
    )
    assert plan["quiescent"] is True
    assert plan["restore_ready"] is True
    assert plan["automatic_deletion"] is False
    assert plan["protected_objects"] == [
        "s3://bucket/data/rel-old-part-0.parquet",
        "s3://bucket/exports/exp-v1.parquet",
        "s3://bucket/data/native-pinned.parquet",
    ]
    assert plan["reclaimable_objects"] == ["s3://bucket/data/orphan-01.parquet"]
    assert plan["protected_bytes"] == 3 * 128
    assert plan["reclaimable_bytes"] == 128

    # Refuses removal plan if any target object is protected.
    with pytest.raises(capacity.ProtectedRetentionError, match="protected"):
        capacity.plan_protected_retention(
            native,
            "catalog-sources",
            namespace="ns-prod",
            objects=objects,
            application_pins=[app_pin],
            removal_id="rm-unsafe",
        )
    assert not native.removals

    # Allows read-only removal plan when targeting only reclaimable objects while quiescent.
    safe_removal = capacity.plan_protected_retention(
        native,
        "catalog-sources",
        namespace="ns-prod",
        objects=["s3://bucket/data/orphan-01.parquet"],
        application_pins=[app_pin],
        removal_id="rm-safe",
        reason=f"operator-check-{secret}",
    )
    assert safe_removal["removal_plan"]["id"] == "rm-safe"
    assert safe_removal["removal_plan"]["objects"] == ["s3://bucket/data/orphan-01.parquet"]
    assert secret not in json.dumps(safe_removal)

    # Active readers, incomplete operations, or pending producer inputs prevent quiescence and block removal.
    with pytest.raises(capacity.ProtectedRetentionError):
        capacity.plan_protected_retention(
            native,
            "catalog-sources",
            namespace="ns-prod",
            objects=["s3://bucket/data/orphan-01.parquet"],
            active_readers=[dict(id="reader-1", objects=["s3://bucket/data/active.parquet"])],
            removal_id="rm-active-reader",
        )

    native.producer = [
        dict(
            input=str(tmp_path / "native/request-1/replacements.parquet"),
            request="req.json",
            bytes=768,
            files=[
                dict(path=str(tmp_path / "native/request-1/replacements.parquet"), bytes=512),
                dict(path=str(tmp_path / "native/request-1/deletions.parquet"), bytes=256),
            ],
        )
    ]
    non_quiescent = capacity.plan_protected_retention(
        native,
        "catalog-sources",
        namespace="ns-prod",
        objects=[
            "s3://bucket/data/orphan-01.parquet",
            str(tmp_path / "native/request-1/deletions.parquet"),
        ],
        application_pins=[app_pin],
    )
    assert non_quiescent["quiescent"] is False
    assert non_quiescent["reclaimable_objects"] == []
    assert str(tmp_path / "native/request-1/deletions.parquet") in non_quiescent["protected_objects"]
    assert non_quiescent["protected_bytes"] == 768 + 2 * 128

    # Wrong namespace or unreferenced local path pin refuses immediately.
    with pytest.raises(capacity.ProtectedRetentionError, match="namespace"):
        capacity.plan_protected_retention(
            native,
            "catalog-sources",
            namespace="ns-prod",
            application_pins=[dict(id="rel-wrong", dataset=dict(namespace="ns-staging", dataset="catalog-sources"))],
        )
    with pytest.raises(capacity.ProtectedRetentionError, match="Unreferenced path"):
        capacity.plan_protected_retention(
            native,
            "catalog-sources",
            namespace="ns-prod",
            application_pins=["/tmp/unreferenced/local/path.parquet"],
        )
