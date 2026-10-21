"""Early disk admission for typed preparation; native admission remains authoritative."""
import json
import os
from pathlib import Path
import shutil
import stat

# Reference profile in the pinned DocSpec src/budget.rs. Explicit native limits
# override it; this check never writes or changes those limits.
_NATIVE_SCRATCH_BYTES = 32 << 30
_HEADROOM_BYTES = 8 << 30


class AdoptionCapacityError(ValueError):
    """Preparation cannot fit alongside the declared native scratch requirement."""

    def __init__(self, receipt):
        self.receipt = receipt
        missing = max(row["required_free_bytes"] - row["available_bytes"]
                      for row in receipt["filesystems"])
        super().__init__(
            f"Adoption needs at least {missing:,} additional bytes before preparation; "
            "free space or choose another staging volume. Native limits are unchanged.")


class ProtectedRetentionError(ValueError):
    """A retention inspection or removal plan conflicts with protected application state."""


def preparation_budget(metadata):
    """Estimate a finite enforced stage budget from Parquet metadata, without decoding.

    Three times the uncompressed size allows typed input parts, the ordered
    derivative, and external sort/write scratch; the row allowance covers
    lookup keys. This is a planning estimate, not a guarantee about Parquet
    compression or Python objects. Preparation enforces its budget.
    """
    return (3 * sum(metadata.row_group(i).total_byte_size
                    for i in range(metadata.num_row_groups))
            + 4096 * metadata.num_rows + (1 << 20))


def _filesystem(path):
    ancestor = Path(path).resolve()
    while not ancestor.exists():
        ancestor = ancestor.parent
    return ancestor.stat().st_dev, str(ancestor), shutil.disk_usage(ancestor).free


def _retained_bytes(directory):
    if directory.is_symlink():
        raise ValueError("Preparation directory cannot be a symlink")
    if not directory.exists():
        return 0
    total = 0
    for path in directory.rglob("*"):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("Preparation cannot contain a symlink")
        if stat.S_ISREG(info.st_mode):
            total += info.st_size
    return total


def require_adoption_capacity(native, directory, staging_bytes, *,
                              headroom_bytes=_HEADROOM_BYTES):
    """Check additional preparation and native scratch on their actual volumes.

    Already retained preparation occupies disk and is not charged a second time.
    This snapshot does not reserve space against other processes. The bounded
    preparation writer and native owner continue enforcing their own limits.
    """
    if type(staging_bytes) is not int or staging_bytes < 0:
        raise ValueError("Preparation budget must be a nonnegative integer")
    if type(headroom_bytes) is not int or headroom_bytes < 0:
        raise ValueError("Headroom must be a nonnegative integer")
    scratch = _NATIVE_SCRATCH_BYTES
    if getattr(native, "limits", None) is not None:
        with Path(native.limits).open("rb") as source:
            body = source.read((1 << 20) + 1)
        if len(body) > 1 << 20:
            raise ValueError("Native limits configuration exceeds its byte budget")
        settings = json.loads(body)
        if not isinstance(settings, dict):
            raise ValueError("Native limits must be a JSON object")
        scratch = settings.get("scratch_bytes", scratch)
    if type(scratch) is not int or scratch <= 0:
        raise ValueError("Native scratch_bytes must be a positive integer")
    directory = Path(directory)
    retained = _retained_bytes(directory)
    additional = max(0, staging_bytes - retained)
    volumes = {}
    for path, required, preparation in (
            (directory, additional, True), (Path(native.workspace), scratch, False)):
        device, location, available = _filesystem(path)
        if device not in volumes:
            volumes[device] = dict(path=location, available_bytes=available,
                                   device=device, preparation=False,
                                   required_free_bytes=headroom_bytes,
                                   base_required_free_bytes=headroom_bytes)
        volumes[device]["available_bytes"] = min(volumes[device]["available_bytes"], available)
        volumes[device]["required_free_bytes"] += required
        if preparation:
            volumes[device]["preparation"] = True
        else:
            volumes[device]["base_required_free_bytes"] += required
    receipt = dict(version=1, staging_budget_bytes=staging_bytes,
                   staging_retained_bytes=retained, staging_additional_bytes=additional,
                   native_scratch_bytes=scratch, headroom_bytes=headroom_bytes,
                   filesystems=list(volumes.values()))
    if any(row["available_bytes"] < row["required_free_bytes"]
           for row in receipt["filesystems"]):
        raise AdoptionCapacityError(receipt)
    return receipt


def recheck_adoption_capacity(receipt, retained_bytes):
    """Refresh free space using tracked stage bytes, without walking files again."""
    if type(retained_bytes) is not int or retained_bytes < 0:
        raise ValueError("Retained preparation bytes must be a nonnegative integer")
    additional = max(0, receipt["staging_budget_bytes"] - retained_bytes)
    volumes = []
    for volume in receipt["filesystems"]:
        device, _, available = _filesystem(Path(volume["path"]))
        if device != volume["device"]:
            raise ValueError("Adoption filesystem changed after capacity admission")
        required = volume["base_required_free_bytes"]
        if volume["preparation"]:
            required += additional
        volumes.append(dict(volume, available_bytes=available, required_free_bytes=required))
    current = dict(receipt, staging_retained_bytes=retained_bytes,
                   staging_additional_bytes=additional, filesystems=volumes)
    if any(row["available_bytes"] < row["required_free_bytes"] for row in volumes):
        raise AdoptionCapacityError(current)
    return current


def _secret_values(native):
    secrets = set()
    remote_secrets = getattr(native, "_remote_secrets", None)
    if isinstance(remote_secrets, dict):
        for value in remote_secrets.values():
            if isinstance(value, str) and value:
                secrets.add(value)
    for name, value in os.environ.items():
        if name.startswith("DOCSPEC_") and any(token in name for token in ("TOKEN", "SECRET", "KEY", "CREDENTIAL")):
            if value:
                secrets.add(value)
    return sorted(secrets, key=len, reverse=True)


def _redact(value, secrets):
    if not secrets:
        return value
    if isinstance(value, str):
        result = value
        for secret in secrets:
            result = result.replace(secret, "[REDACTED]")
        return result
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item, secrets) for item in value)
    if isinstance(value, dict):
        return {_redact(k, secrets): _redact(v, secrets) for k, v in value.items()}
    return value


def _inspect_stage_receipts(stage_directory):
    if stage_directory is None:
        return dict(
            stage_directory=None,
            preparation_key=None,
            parts_completed=0,
            rows_prepared=0,
            source_preparation_completed=False,
            ordered_derivative_completed=False,
            ordered_derivative_bytes=0,
            retained_bytes=0,
        )
    directory = Path(stage_directory)
    retained = _retained_bytes(directory)
    if not directory.exists():
        return dict(
            stage_directory=str(directory),
            preparation_key=None,
            parts_completed=0,
            rows_prepared=0,
            source_preparation_completed=False,
            ordered_derivative_completed=False,
            ordered_derivative_bytes=0,
            retained_bytes=0,
        )
    request_path = directory / "request.json"
    complete_path = directory / "complete.json"
    ordered_path = directory / "ordered.json"
    ordered_parquet = directory / "ordered.parquet"
    request_data = json.loads(request_path.read_text()) if request_path.is_file() else {}
    complete_data = json.loads(complete_path.read_text()) if complete_path.is_file() else None
    part_receipts = sorted(directory.glob("part-*.json"))
    rows_prepared = (
        complete_data.get("rows", 0)
        if isinstance(complete_data, dict)
        else sum(json.loads(path.read_text()).get("rows", 0) for path in part_receipts)
    )
    return dict(
        stage_directory=str(directory),
        preparation_key=request_data.get("preparation_key") if isinstance(request_data, dict) else None,
        parts_completed=len(part_receipts),
        rows_prepared=rows_prepared,
        source_preparation_completed=complete_path.is_file(),
        ordered_derivative_completed=ordered_path.is_file(),
        ordered_derivative_bytes=ordered_parquet.stat().st_size if ordered_parquet.is_file() else 0,
        retained_bytes=retained,
    )


def _inspect_producer_inputs(native):
    raw_inputs = native.retained_producer_inputs() if hasattr(native, "retained_producer_inputs") else []
    summarized = []
    for item in raw_inputs:
        entry = dict(item)
        request_file = Path(item["request"]) if isinstance(item.get("request"), str) else None
        if request_file is not None and request_file.is_file():
            try:
                payload = json.loads(request_file.read_text())
                if isinstance(payload, dict):
                    entry["dataset"] = payload.get("dataset")
                    entry["operation"] = payload.get("operation")
                    entry["expected_digest"] = payload.get("expected_digest")
                    replacements = payload.get("replacements")
                    deletions = payload.get("deletions")
                    if isinstance(replacements, dict):
                        entry["replacements_digest"] = replacements.get("digest")
                    if isinstance(deletions, dict):
                        entry["deletions_digest"] = deletions.get("digest")
                    entry.setdefault("files", [])
            except (OSError, ValueError):
                pass
        summarized.append(entry)
    return summarized


def inspect_operator_status(native, dataset, *, stage_directory=None, staging_budget_bytes=0,
                            headroom_bytes=_HEADROOM_BYTES, preparation_metrics=None,
                            preparation_reads=None, process_rss_bytes=None,
                            allow_insufficient_capacity=False):
    """Report reusable preparation/native phases, producer inputs, and disk headroom without secrets."""
    secrets = _secret_values(native)
    inspection = native.inspect(dataset) if hasattr(native, "inspect") else {}
    authority = inspection.get("authority") if isinstance(inspection, dict) else None
    lifecycle_revision = (
        inspection.get("current_revision")
        if isinstance(inspection, dict) and type(inspection.get("current_revision")) is int
        else (authority.get("revision") if isinstance(authority, dict) and type(authority.get("revision")) is int else None)
    )
    latest = inspection.get("latest") if isinstance(inspection, dict) else None
    latest_id = latest.get("id") if isinstance(latest, dict) else (latest if isinstance(latest, str) else None)
    versions = inspection.get("versions", []) if isinstance(inspection, dict) else []
    completed_ids = [
        item.get("id") if isinstance(item, dict) else item
        for item in versions
        if isinstance(item, (dict, str))
    ]
    incomplete = inspection.get("incomplete_operations", []) if isinstance(inspection, dict) else []
    incomplete_ids = [
        item.get("id") if isinstance(item, dict) else item
        for item in incomplete
        if isinstance(item, (dict, str))
    ]
    producer_inputs = _inspect_producer_inputs(native)
    outstanding_producer_bytes = sum((item.get("bytes") or 0) for item in producer_inputs)
    stage = _inspect_stage_receipts(stage_directory)

    target_dir = Path(stage_directory) if stage_directory is not None else Path(native.workspace)
    capacity_sufficient = True
    try:
        capacity = require_adoption_capacity(
            native,
            target_dir,
            staging_budget_bytes,
            headroom_bytes=headroom_bytes,
        )
    except AdoptionCapacityError as error:
        if not allow_insufficient_capacity:
            raise
        capacity_sufficient = False
        capacity = error.receipt

    if producer_inputs:
        phase = "lost-response-recovery-required"
    elif incomplete_ids:
        phase = "native-incomplete"
    elif stage["ordered_derivative_completed"]:
        phase = "ordered"
    elif stage["source_preparation_completed"]:
        phase = "prepared"
    elif stage["parts_completed"] > 0:
        phase = "preparing"
    elif latest_id is not None:
        phase = "completed"
    else:
        phase = "pending"

    metrics = dict(preparation_metrics or getattr(native, "preparation_metrics", {}) or {})
    reads = dict(preparation_reads or getattr(native, "preparation_reads", {}) or {})
    measured = dict(
        staging_retained_bytes=stage["retained_bytes"],
        ordered_derivative_bytes=stage["ordered_derivative_bytes"],
        outstanding_producer_bytes=outstanding_producer_bytes,
        sort_spill_peak_bytes=reads.get("sort_spill_peak_bytes"),
        sort_buffer_peak_bytes=reads.get("sort_buffer_peak_bytes"),
        index_bytes=metrics.get("index_bytes"),
        staging_bytes=metrics.get("staging_bytes", stage["retained_bytes"]),
        process_rss_bytes=process_rss_bytes,
    )
    unavailable = sorted(key for key, value in measured.items() if value is None)
    report = dict(
        dataset=dataset,
        phase=phase,
        latest_release_id=latest_id,
        completed_release_ids=completed_ids,
        version_count=len(completed_ids),
        lifecycle_revision=lifecycle_revision,
        lifecycle_compaction_available=hasattr(native, "compact_lifecycle") and getattr(native, "remote", None) is None,
        incomplete_operation_ids=incomplete_ids,
        retained_producer_inputs=producer_inputs,
        outstanding_producer_bytes=outstanding_producer_bytes,
        preparation=stage,
        resources=dict(
            measured={key: value for key, value in measured.items() if value is not None},
            estimated=dict(
                staging_budget_bytes=capacity["staging_budget_bytes"],
                native_scratch_bytes=capacity["native_scratch_bytes"],
                headroom_bytes=capacity["headroom_bytes"],
            ),
            unavailable=unavailable,
        ),
        capacity_sufficient=capacity_sufficient,
        capacity=capacity,
    )
    return _redact(report, secrets)


def _extract_pin_reference(pin, *, dataset, namespace, kind):
    if isinstance(pin, str):
        if not pin.strip() or "/" in pin or "\\" in pin:
            raise ProtectedRetentionError(f"Unreferenced path or empty identifier cannot act as a {kind} pin")
        return dict(id=pin, objects=set(), digest=None)
    if not isinstance(pin, dict):
        raise ProtectedRetentionError(f"Invalid {kind} pin format")
    pin_id = pin.get("id") or pin.get("version") or pin.get("operation")
    if not isinstance(pin_id, str) or not pin_id.strip():
        raise ProtectedRetentionError(f"Protected {kind} pin requires an explicit id or version")
    pin_dataset = pin.get("dataset")
    if isinstance(pin_dataset, dict):
        if pin_dataset.get("dataset") and pin_dataset.get("dataset") != dataset:
            raise ProtectedRetentionError(f"Protected {kind} pin dataset differs from {dataset}")
        if namespace is not None and pin_dataset.get("namespace") and pin_dataset.get("namespace") != namespace:
            raise ProtectedRetentionError(f"Protected {kind} pin namespace differs from {namespace}")
    elif isinstance(pin_dataset, str) and pin_dataset != dataset:
        raise ProtectedRetentionError(f"Protected {kind} pin dataset differs from {dataset}")
    objects = set()
    for item in pin.get("objects", ()):
        if isinstance(item, str) and item:
            objects.add(item)
        elif isinstance(item, dict) and isinstance(item.get("path"), str):
            objects.add(item["path"])
    manifest = pin.get("manifest")
    digest = manifest.get("digest") if isinstance(manifest, dict) else None
    if isinstance(manifest, dict) and isinstance(manifest.get("path"), str):
        objects.add(manifest["path"])
    return dict(id=pin_id, objects=objects, digest=digest)


def plan_protected_retention(native, dataset, *, objects=(), application_pins=(),
                             export_pins=(), active_readers=(), incomplete_operations=(),
                             removal_id=None, reason=None, namespace=None):
    """Bind application pins, active readers, incomplete operations, and producer inputs into read-only retention planning."""
    secrets = _secret_values(native)
    protected_releases = set()
    protected_exports = set()
    protected_readers = set()
    protected_object_paths = set()

    for pin in application_pins:
        ref = _extract_pin_reference(pin, dataset=dataset, namespace=namespace, kind="application release")
        protected_releases.add(ref["id"])
        protected_object_paths.update(ref["objects"])
    for pin in export_pins:
        ref = _extract_pin_reference(pin, dataset=dataset, namespace=namespace, kind="export")
        protected_exports.add(ref["id"])
        protected_object_paths.update(ref["objects"])
    for reader in active_readers:
        ref = _extract_pin_reference(reader, dataset=dataset, namespace=namespace, kind="active reader")
        protected_readers.add(ref["id"])
        protected_object_paths.update(ref["objects"])

    inspection = native.inspect(dataset) if hasattr(native, "inspect") else {}
    native_incomplete = inspection.get("incomplete_operations", []) if isinstance(inspection, dict) else []
    incomplete_ids = set()
    for item in (*incomplete_operations, *native_incomplete):
        if isinstance(item, str) and item.strip():
            incomplete_ids.add(item)
        elif isinstance(item, dict):
            op_id = item.get("id") or item.get("operation")
            if isinstance(op_id, str) and op_id.strip():
                incomplete_ids.add(op_id)
            for obj in item.get("objects", ()):
                if isinstance(obj, str) and obj:
                    protected_object_paths.add(obj)

    producer_inputs = _inspect_producer_inputs(native)
    for item in producer_inputs:
        if isinstance(item.get("input"), str):
            protected_object_paths.add(item["input"])
        for file_entry in item.get("files", ()):
            if isinstance(file_entry, dict) and isinstance(file_entry.get("path"), str):
                protected_object_paths.add(file_entry["path"])
        if isinstance(item.get("operation"), str):
            incomplete_ids.add(item["operation"])

    quiescent = not incomplete_ids and not producer_inputs and not protected_readers
    candidate_objects = list(objects)
    native_retention = (
        native.inspect_retention(candidate_objects)
        if hasattr(native, "inspect_retention") and candidate_objects
        else []
    )
    entries = native_retention.get("objects", native_retention) if isinstance(native_retention, dict) else native_retention
    if not isinstance(entries, list):
        entries = []

    by_path = {}
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("path") or entry.get("object"), str):
            key = entry.get("path") or entry.get("object")
            by_path[key] = entry

    protected_list = []
    reclaimable_list = []
    protected_bytes = sum((item.get("bytes") or 0) for item in producer_inputs)
    reclaimable_bytes = 0
    all_protected_ids = protected_releases | protected_exports | protected_readers | incomplete_ids

    for obj in candidate_objects:
        path = obj.get("path") if isinstance(obj, dict) else str(obj)
        size = obj.get("bytes", 0) if isinstance(obj, dict) else 0
        entry = by_path.get(path, {})
        if isinstance(entry, dict) and type(entry.get("bytes")) is int:
            size = entry["bytes"]
        referenced_ids = set()
        if isinstance(obj, dict):
            for field in ("version", "release_id", "operation", "export_id", "reader_id"):
                if isinstance(obj.get(field), str):
                    referenced_ids.add(obj[field])
        if isinstance(entry, dict):
            for field in ("version", "release_id", "operation"):
                if isinstance(entry.get(field), str):
                    referenced_ids.add(entry[field])
            for ref in entry.get("references", ()):
                if isinstance(ref, str):
                    referenced_ids.add(ref)
                elif isinstance(ref, dict) and isinstance(ref.get("id"), str):
                    referenced_ids.add(ref["id"])
        native_protected = (
            isinstance(entry, dict)
            and (
                entry.get("protected") is True
                or entry.get("status") in {"protected", "active", "incomplete"}
                or bool(entry.get("reasons"))
            )
        )
        is_protected = (
            not quiescent
            or native_protected
            or path in protected_object_paths
            or bool(referenced_ids & all_protected_ids)
            or any(pin_id in path for pin_id in all_protected_ids)
        )
        if is_protected:
            protected_list.append(path)
            protected_bytes += size
        else:
            reclaimable_list.append(path)
            reclaimable_bytes += size

    removal_plan = None
    if removal_id is not None:
        if not quiescent or protected_list:
            raise ProtectedRetentionError(
                "Refusing removal plan: target objects include protected releases, active readers, "
                "incomplete operations, or unresolved producer inputs"
            )
        removal_plan = native.plan_removal(
            dict(id=removal_id, objects=reclaimable_list, reason=reason or "operator-retention-plan")
        )
        if isinstance(removal_plan, dict):
            planned_objects = removal_plan.get("objects", [])
            for item in planned_objects:
                item_path = item.get("path") if isinstance(item, dict) else str(item)
                if item_path in protected_object_paths or any(pin_id in item_path for pin_id in all_protected_ids):
                    raise ProtectedRetentionError("Native removal plan included a protected application object")

    result = dict(
        dataset=dataset,
        namespace=namespace,
        quiescent=quiescent,
        restore_ready=bool(quiescent and (protected_releases or protected_exports)),
        protected_releases=sorted(protected_releases),
        protected_exports=sorted(protected_exports),
        protected_readers=sorted(protected_readers),
        incomplete_operations=sorted(incomplete_ids),
        pending_producer_inputs=producer_inputs,
        protected_objects=protected_list,
        reclaimable_objects=reclaimable_list,
        protected_bytes=protected_bytes,
        reclaimable_bytes=reclaimable_bytes,
        removal_plan=removal_plan,
        automatic_deletion=False,
    )
    return _redact(result, secrets)
