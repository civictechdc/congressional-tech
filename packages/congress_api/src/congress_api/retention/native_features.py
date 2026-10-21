"""Application adapters for DocSpec change streams, schema/backfill, refresh, and receipts.

Each helper binds exact ``ReleasePin`` versions through the shared ``docspec_client``
transport while preserving application authority over source identity, transitive
alias closure, review decisions, and coherent multi-table publication.
"""
from collections import Counter
import json
import time
import pyarrow as pa


FIELD_GROUP_CAPABILITIES = {
    "source": {
        "backend_capability": "source_group",
        "local_supported": True,
        "remote_supported": True,
    },
    "occurrences": {
        "backend_capability": "local_only",
        "local_supported": True,
        "remote_supported": False,
    },
    "inputs": {
        "backend_capability": "local_only",
        "local_supported": True,
        "remote_supported": False,
    },
    "evidence": {
        "backend_capability": "local_only",
        "local_supported": True,
        "remote_supported": False,
    },
}


def version_ref(pin):
    """Extract the exact ``VersionRef`` of a verified ``ReleasePin``."""
    if not isinstance(pin, dict) or not pin.get("verified") or "dataset" not in pin or "manifest" not in pin:
        raise ValueError("A verified ReleasePin is required")
    dataset = pin["dataset"]
    return {
        "dataset": dataset["dataset"],
        "version": pin["id"],
        "manifest": pin["manifest"],
    }


def _parquet_digests(objects):
    return {
        obj["digest"]: int(obj.get("bytes", 0))
        for obj in (objects or ())
        if isinstance(obj, dict) and str(obj.get("path", "")).endswith(".parquet") and "digest" in obj
    }


def _metadata_digests(objects):
    return {
        obj["digest"]: int(obj.get("bytes", 0))
        for obj in (objects or ())
        if isinstance(obj, dict) and not str(obj.get("path", "")).endswith(".parquet") and "digest" in obj
    }


def _evidence_objects(ds):
    if not isinstance(ds, dict):
        return []
    ev = ds.get("evidence") or {}
    if isinstance(ev, dict) and isinstance(ev.get("table"), dict):
        return ev["table"].get("objects") or []
    rel_ev = (ds.get("related") or {}).get("evidence") or {}
    if isinstance(rel_ev, dict):
        return rel_ev.get("objects") or []
    return []


def _compute_field_group_metrics(before_pin, after_pin, *, path, effects, table):
    before_ds = before_pin.get("dataset") or {}
    after_ds = after_pin.get("dataset") or {}
    before_src_objs = ((before_ds.get("groups") or {}).get("source") or {}).get("objects") or []
    after_src_objs = ((after_ds.get("groups") or {}).get("source") or {}).get("objects") or []

    before_pq = _parquet_digests(before_src_objs)
    after_pq = _parquet_digests(after_src_objs)
    before_meta = _metadata_digests(before_src_objs)
    after_meta = _metadata_digests(after_src_objs)

    if path == "unchanged":
        source_read_bytes = 0
        occ_read_bytes = 0
    elif path == "forward_changes":
        delta_pq = set(before_pq) ^ set(after_pq)
        source_read_bytes = sum(before_pq.get(d, 0) or after_pq.get(d, 0) for d in delta_pq)
        delta_meta = set(before_meta) ^ set(after_meta)
        occ_read_bytes = sum(before_meta.get(d, 0) or after_meta.get(d, 0) for d in delta_meta)
    else:
        source_read_bytes = sum(before_pq.values()) + sum(after_pq.values())
        occ_read_bytes = sum(before_meta.values()) + sum(after_meta.values())

    if table.num_rows > 0:
        if "values" in table.column_names:
            source_returned_bytes = int(table["values"].nbytes) or int(table.nbytes)
        else:
            source_returned_bytes = int(table.nbytes)
        occ_returned_bytes = sum(
            int(table[col].nbytes)
            for col in ("side", "file", "row")
            if col in table.column_names
        )
    else:
        source_returned_bytes = 0
        occ_returned_bytes = 0

    before_in = before_ds.get("inputs") or {}
    after_in = after_ds.get("inputs") or {}
    if path == "unchanged" or not (effects.get("input_refs_changed") or effects.get("coverage_changed")):
        in_read_bytes = 0
        in_returned_bytes = 0
    else:
        delta_in = [v for k, v in after_in.items() if before_in.get(k) != v] + [
            v for k, v in before_in.items() if k not in after_in
        ]
        in_read_bytes = sum(int(v.get("bytes", 0)) for v in delta_in if isinstance(v, dict))
        in_returned_bytes = sum(
            len(json.dumps(v, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            for v in delta_in
            if isinstance(v, dict)
        )

    before_ev_objs = _evidence_objects(before_ds)
    after_ev_objs = _evidence_objects(after_ds)
    before_ev = {
        o["digest"]: int(o.get("bytes", 0))
        for o in before_ev_objs
        if isinstance(o, dict) and "digest" in o
    }
    after_ev = {
        o["digest"]: int(o.get("bytes", 0))
        for o in after_ev_objs
        if isinstance(o, dict) and "digest" in o
    }
    if path == "unchanged" or not effects.get("evidence_refs_changed"):
        ev_read_bytes = 0
        ev_returned_bytes = 0
    else:
        delta_ev = set(before_ev) ^ set(after_ev)
        ev_read_bytes = sum(before_ev.get(d, 0) or after_ev.get(d, 0) for d in delta_ev)
        ev_pq_after = _parquet_digests(after_ev_objs)
        ev_pq_before = _parquet_digests(before_ev_objs)
        ev_returned_bytes = sum(
            ev_pq_after.get(d, 0) or ev_pq_before.get(d, 0)
            for d in (set(ev_pq_after) ^ set(ev_pq_before))
        )

    raw_metrics = {
        "source": (source_read_bytes, source_returned_bytes),
        "occurrences": (occ_read_bytes, occ_returned_bytes),
        "inputs": (in_read_bytes, in_returned_bytes),
        "evidence": (ev_read_bytes, ev_returned_bytes),
    }
    field_groups = {}
    for fg, caps in FIELD_GROUP_CAPABILITIES.items():
        r_bytes, ret_bytes = raw_metrics[fg]
        field_groups[fg] = {
            "read_bytes": int(r_bytes),
            "returned_bytes": int(ret_bytes),
            **caps,
        }
    before_groups = before_ds.get("groups") or {}
    after_groups = after_ds.get("groups") or {}
    for g_name in set(before_groups) | set(after_groups):
        if g_name not in field_groups:
            b_objs = (before_groups.get(g_name) or {}).get("objects") or []
            a_objs = (after_groups.get(g_name) or {}).get("objects") or []
            b_pq = _parquet_digests(b_objs)
            a_pq = _parquet_digests(a_objs)
            if path == "unchanged":
                g_read = 0
            elif path == "forward_changes":
                d_pq = set(b_pq) ^ set(a_pq)
                g_read = sum(b_pq.get(d, 0) or a_pq.get(d, 0) for d in d_pq)
            else:
                g_read = sum(b_pq.values()) + sum(a_pq.values())
            field_groups[g_name] = {
                "read_bytes": int(g_read),
                "returned_bytes": int(table.nbytes) if table.num_rows > 0 else 0,
                "backend_capability": "local_only",
                "local_supported": True,
                "remote_supported": False,
            }
    unchanged_files_reused = len(set(before_pq) & set(after_pq))
    return field_groups, unchanged_files_reused, len(after_pq)


def _multiset_diff(lhs_rows, rhs_rows):
    """Return multiset difference ``lhs_rows - rhs_rows`` preserving duplicate multiplicity."""
    rhs_counts = Counter(
        json.dumps(r, sort_keys=True, separators=(",", ":"), default=str)
        for r in rhs_rows
    )
    diff = []
    for r in lhs_rows:
        key = json.dumps(r, sort_keys=True, separators=(",", ":"), default=str)
        if rhs_counts.get(key, 0) > 0:
            rhs_counts[key] -= 1
        else:
            diff.append(r)
    return diff


# -- ct-13cn: Certified change streams & catalog diagnostics -------------------


def inspect_catalog_changes(native, before_pin, after_pin, *, group="source",
                            identity="occurrences", key_column=None,
                            allow_full_fallback=True, allow_fallback=None,
                            force_full=False):
    """Consume one native ``/changes`` stream and derive counts and affected keys.

    Does not call ``/compare`` and ``/changes`` redundantly when row changes are
    consumed. Verifies exact endpoint ``VersionRef`` bindings and refuses
    unbounded full-fallback reconstruction when ``allow_full_fallback=False``
    (or ``allow_fallback=False``). Reports ``read_bytes``, ``returned_bytes``,
    and backend capability support separately for ``source``, ``occurrences``,
    ``inputs``, and ``evidence``.
    """
    expected_before = version_ref(before_pin)
    expected_after = version_ref(after_pin)
    effective_allow_fallback = (
        bool(allow_full_fallback) if allow_fallback is None else bool(allow_fallback)
    )
    if getattr(native, "remote", None) is not None and group in ("occurrences", "inputs", "evidence"):
        raise ValueError(
            f"400 remote_unsupported: field group {group!r} requires BackendCapability::LocalOnly "
            "and is not supported on remote R2"
        )
    before_groups = (before_pin.get("dataset") or {}).get("groups") or {}
    after_groups = (after_pin.get("dataset") or {}).get("groups") or {}
    has_native_group = group in before_groups or group in after_groups
    stream_group = (
        group
        if has_native_group or group not in ("occurrences", "inputs", "evidence")
        else "source"
    )
    stream_identity = "occurrences" if group == "occurrences" else identity
    with native.changes_batches(
        before_pin,
        after_pin,
        group=stream_group,
        identity=stream_identity,
        force_full=force_full,
    ) as (descriptor, reader):
        if not isinstance(descriptor, dict):
            raise ValueError("Change stream is missing its docspec.change descriptor")
        if descriptor.get("before") != expected_before or descriptor.get("after") != expected_after:
            raise ValueError("Change stream descriptor endpoints differ from the requested pins")
        path = descriptor.get("path")
        # docspec-rs serializes ChangeDescriptor.fallback (ComparisonFallback, snake_case)
        # and ComparisonEffects.evidence_refs_changed; accept only those names.
        fallback_reason = descriptor.get("fallback")
        if not effective_allow_fallback and (
            path == "full" or (fallback_reason not in (None, "none"))
        ):
            raise ValueError(
                f"Incremental caller refused full comparison fallback ({fallback_reason or path})"
            )
        batches = list(reader)
        table = pa.Table.from_batches(batches, schema=reader.schema)

    added_rows = 0
    removed_rows = 0
    added_records = []
    removed_records = []
    changed_keys = set()
    changed_occurrences = []
    rows = table.to_pylist()
    for row in rows:
        side = row.get("side") or row.get("change") or row.get("__docspec_change")
        if row.get("file") is not None and row.get("row") is not None:
            changed_occurrences.append((str(row["file"]), int(row["row"])))
        record = row.get("values") if isinstance(row.get("values"), dict) else {
            k: v for k, v in row.items()
            if k not in {"side", "file", "row", "change", "weight"} and not k.startswith("__docspec_")
        }
        if key_column is not None and isinstance(record, dict):
            key_val = record.get(key_column)
            if key_val is None and isinstance(record.get("source_values"), dict):
                key_val = record["source_values"].get(key_column)
            if key_val is not None:
                changed_keys.add(key_val)
        if side in ("after", "added", "+1", 1):
            added_rows += 1
            added_records.append(record)
        elif side in ("before", "removed", "-1", -1):
            removed_rows += 1
            removed_records.append(record)

    effects = descriptor.get("effects") or {}
    field_groups, unchanged_files_reused, total_after_files = _compute_field_group_metrics(
        before_pin,
        after_pin,
        path=path,
        effects=effects,
        table=table,
    )

    if group == "evidence" and effects.get("evidence_refs_changed"):
        before_ev_rows = (
            native.read_receipts(before_pin).to_pylist()
            if _evidence_objects(before_pin.get("dataset") or {})
            else []
        )
        after_ev_rows = (
            native.read_receipts(after_pin).to_pylist()
            if _evidence_objects(after_pin.get("dataset") or {})
            else []
        )
        added_records = _multiset_diff(after_ev_rows, before_ev_rows)
        removed_records = _multiset_diff(before_ev_rows, after_ev_rows)
        added_rows = len(added_records)
        removed_rows = len(removed_records)
    elif group == "inputs" and (effects.get("input_refs_changed") or effects.get("coverage_changed")):
        before_in = (before_pin.get("dataset") or {}).get("inputs") or {}
        after_in = (after_pin.get("dataset") or {}).get("inputs") or {}
        added_records = [
            {"input": k, **v}
            for k, v in sorted(after_in.items())
            if before_in.get(k) != v and isinstance(v, dict)
        ]
        removed_records = [
            {"input": k, **v}
            for k, v in sorted(before_in.items())
            if after_in.get(k) != v and isinstance(v, dict)
        ]
        added_rows = len(added_records)
        removed_rows = len(removed_records)

    replacement_by_key = {}
    removed_key_set = set()
    if key_column is not None:
        for rec in added_records:
            if isinstance(rec, dict):
                kv = rec.get(key_column)
                if kv is None and isinstance(rec.get("source_values"), dict):
                    kv = rec["source_values"].get(key_column)
                if kv is not None:
                    replacement_by_key[kv] = rec
        for rec in removed_records:
            if isinstance(rec, dict):
                kv = rec.get(key_column)
                if kv is None and isinstance(rec.get("source_values"), dict):
                    kv = rec["source_values"].get(key_column)
                if kv is not None:
                    removed_key_set.add(kv)
        replacement_records = [replacement_by_key[k] for k in sorted(replacement_by_key)]
        deleted_keys = sorted(removed_key_set - set(replacement_by_key))
    else:
        replacement_records = list(added_records)
        deleted_keys = []

    group_cap = FIELD_GROUP_CAPABILITIES.get(
        group,
        {
            "backend_capability": "local_only",
            "local_supported": True,
            "remote_supported": False,
        },
    )
    if group in field_groups:
        read_bytes = field_groups[group]["read_bytes"]
        returned_bytes = (
            int(table.nbytes)
            if group == "source" and table.num_rows > 0
            else field_groups[group]["returned_bytes"]
        )
    else:
        read_bytes = field_groups["source"]["read_bytes"]
        returned_bytes = int(table.nbytes) if table.num_rows > 0 else 0

    return dict(
        descriptor=descriptor,
        group=group,
        identity=identity,
        path=path,
        fallback_reason=fallback_reason,
        effects=effects,
        schema_changed=bool(effects.get("schema_changed")),
        inputs_changed=bool(effects.get("input_refs_changed") or effects.get("coverage_changed")),
        evidence_changed=bool(effects.get("evidence_refs_changed")),
        added_rows=added_rows,
        removed_rows=removed_rows,
        added_records=added_records,
        removed_records=removed_records,
        replacement_records=replacement_records,
        deleted_keys=deleted_keys,
        changed_keys=sorted(changed_keys),
        changed_occurrences=changed_occurrences,
        read_bytes=read_bytes,
        returned_bytes=returned_bytes,
        backend_capability=group_cap["backend_capability"],
        local_supported=group_cap["local_supported"],
        remote_supported=group_cap["remote_supported"],
        field_groups=field_groups,
        unchanged_files_reused=unchanged_files_reused,
        total_after_files=total_after_files,
        table=table,
    )


# -- ct-dmca: Compatible schema evolution & resumable scalar backfills ---------


def evolve_catalog_schema(native, *, dataset, operation, base_pin, definition,
                          next_definition, fields, additions=(), write_defaults=None):
    """Apply a metadata-only compatible schema evolution against ``base_pin``."""
    ref = version_ref(base_pin)
    if ref["dataset"] != dataset:
        raise ValueError("base_pin dataset differs from target dataset")
    spec = dict(
        dataset=dataset,
        operation=operation,
        base=ref["version"],
        definition=definition,
        next_definition=next_definition,
        fields=[dict(id=int(f["id"]), name=str(f["name"])) for f in fields],
    )
    if additions:
        spec["additions"] = list(additions)
    if write_defaults:
        spec["write_defaults"] = {str(k): v for k, v in write_defaults.items()}
    plan = native.plan_schema(spec)
    pin = native.evolve_schema(spec)
    return dict(plan=plan, pin=pin)


def backfill_scalar_group(native, *, dataset, operation, base_pin, definition,
                          group, group_definition, fields, continuous=None,
                          correction=None):
    """Compute or resume a row-local scalar field group over ``base_pin``."""
    ref = version_ref(base_pin)
    if ref["dataset"] != dataset:
        raise ValueError("base_pin dataset differs from target dataset")
    computed_fields = [
        dict(id=int(f["id"]), name=str(f["name"]), expression=str(f["expression"]))
        for f in fields
    ]
    backfill_spec = dict(
        dataset=dataset,
        operation=operation,
        base=ref["version"],
        definition=definition,
        group=group,
        group_definition=group_definition,
        fields=computed_fields,
    )
    if continuous is not None:
        cont_spec = dict(
            backfill=backfill_spec,
            optimistic_rounds=int(continuous.get("optimistic_rounds", 4)),
            fence_millis=int(continuous.get("fence_millis", 5000)),
        )
        plan = native.plan_continuous_backfill(cont_spec)
        pin = native.continuous_backfill(cont_spec)
    else:
        plan = native.plan_backfill(backfill_spec)
        pin = native.backfill(backfill_spec)

    correction_decision = None
    if correction is not None:
        corr_spec = dict(
            dataset=dataset,
            id=correction["id"],
            definition=dict(
                group=group,
                definition=group_definition,
                fields=computed_fields,
            ),
            fields=sorted(int(fid) for fid in correction["fields"]),
            reason=str(correction["reason"]),
        )
        correction_decision = native.correct_dependencies(corr_spec)
    return dict(plan=plan, pin=pin, correction=correction_decision)


# -- ct-gziq: Eligible catalog equality joins and aggregate rollups ------------


def _compute_refresh_metrics(pin, *, mode, base_pin=None, input_pins=(), prior_input_pins=(),
                             elapsed_ms=0.0, native=None, dataset=None, operation=None,
                             executed_requests=0):
    out_objs = (((pin.get("dataset") or {}).get("groups") or {}).get("source") or {}).get("objects") or []
    out_pq = _parquet_digests(out_objs)
    base_objs = ((((base_pin or {}).get("dataset") or {}).get("groups") or {}).get("source") or {}).get("objects") or []
    base_pq = _parquet_digests(base_objs)

    output_reused = len(set(out_pq) & set(base_pq))
    new_out_digests = set(out_pq) - set(base_pq)
    if base_pin is not None:
        written_bytes = sum(out_pq[d] for d in new_out_digests)
    else:
        written_bytes = sum(out_pq.values())

    read_bytes = 0
    input_reused = 0
    for idx, in_pin in enumerate(input_pins):
        in_objs = (((in_pin.get("dataset") or {}).get("groups") or {}).get("source") or {}).get("objects") or []
        in_pq = _parquet_digests(in_objs)
        prior_pin = prior_input_pins[idx] if idx < len(prior_input_pins) else None
        if mode == "incremental" and base_pin is not None:
            if prior_pin is not None:
                prior_objs = (((prior_pin.get("dataset") or {}).get("groups") or {}).get("source") or {}).get("objects") or []
                prior_pq = _parquet_digests(prior_objs)
                delta_digests = set(in_pq) ^ set(prior_pq)
                read_bytes += sum(in_pq.get(d, 0) or prior_pq.get(d, 0) for d in delta_digests)
                input_reused += len(set(in_pq) & set(prior_pq))
            else:
                in_list = [
                    int(o.get("bytes", 0))
                    for o in in_objs
                    if isinstance(o, dict) and str(o.get("path", "")).endswith(".parquet")
                ]
                if len(in_list) > 1:
                    read_bytes += in_list[-1]
                    input_reused += len(in_list) - 1
                else:
                    read_bytes += sum(in_list)
        else:
            read_bytes += sum(in_pq.values())

    native_phase_metrics = {}
    if native is not None and dataset is not None and operation is not None and hasattr(native, "inspect"):
        inspection = native.inspect(dataset)
        if isinstance(inspection, dict):
            obj_map = (
                inspection["objects"]
                if isinstance(inspection.get("objects"), dict)
                else inspection
            )
            for key, entry in obj_map.items():
                if (
                    isinstance(key, str)
                    and key.startswith("phase/")
                    and isinstance(entry, dict)
                    and entry.get("operation") == operation
                    and entry.get("phase") == "processing"
                    and isinstance(entry.get("metrics"), dict)
                ):
                    native_phase_metrics = dict(entry["metrics"])
                    break

    prep_reads = getattr(native, "preparation_reads", None) if native is not None else None
    spill_bytes = int(
        (prep_reads.get("sort_spill_peak_bytes") if isinstance(prep_reads, dict) else None)
        or native_phase_metrics.get("spill_bytes")
        or 0
    )

    return dict(
        mode=mode,
        read_bytes=int(read_bytes),
        written_bytes=int(written_bytes),
        unchanged_files_reused=int(max(output_reused, int(native_phase_metrics.get("files_reused", 0)))),
        input_unchanged_files_reused=int(input_reused),
        total_output_files=len(out_pq),
        provider_requests=int(executed_requests),
        spill_bytes=spill_bytes,
        native_phase_metrics=native_phase_metrics,
        elapsed_ms=round(float(elapsed_ms), 3),
        backend_capability="local_only",
        remote_supported=False,
    )


def refresh_catalog_observation_summary(native, *, dataset, operation, source_pin,
                                        base_pin=None, prior_source_pin=None,
                                        mode="full",
                                        definition="catalog-obs-summary-v1",
                                        keys=("alias",), count_field="observation",
                                        collect_field=None):
    """Maintain an incremental or full observation summary over ``source_pin``.

    Preserves transitive alias closure in Python (`catalog_dependencies.py`) while
    offloading grouped observation counts (`CountRows`, `CountDistinct`, and
    optional `CollectSet`) to native `Refresh` over exact pinned inputs
    (`policy='captured'`).
    """
    if getattr(native, "remote", None) is not None:
        raise ValueError(
            "400 remote_unsupported: /refreshes requires BackendCapability::LocalOnly "
            "and is not supported on remote R2"
        )
    source_ref = version_ref(source_pin)
    base_version = version_ref(base_pin)["version"] if base_pin is not None else None
    if mode == "incremental" and base_version is None:
        raise ValueError("incremental refresh requires base_pin")
    aggregates = [
        dict(name="total_rows", function=dict(kind="count_rows")),
        dict(
            name="distinct_observations",
            function=dict(kind="count_distinct", field=count_field),
        ),
    ]
    if collect_field is not None:
        aggregates.append(
            dict(name="members", function=dict(kind="collect_set", field=collect_field))
        )
    spec = dict(
        dataset=dataset,
        operation=operation,
        base=base_version,
        definition=definition,
        mode=mode,
        policy="captured",
        transform=dict(
            kind="aggregate",
            input=source_ref,
            grouping=dict(
                keys=list(keys),
                aggregates=aggregates,
            ),
        ),
    )
    executed_requests = 0
    t0 = time.perf_counter()
    plan = native.plan_refresh(spec)
    executed_requests += 1
    pin = native.refresh(spec)
    executed_requests += 1
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    metrics = _compute_refresh_metrics(
        pin,
        mode=mode,
        base_pin=base_pin,
        input_pins=(source_pin,),
        prior_input_pins=(prior_source_pin,) if prior_source_pin is not None else (),
        elapsed_ms=elapsed_ms,
        native=native,
        dataset=dataset,
        operation=operation,
        executed_requests=executed_requests,
    )
    return dict(plan=plan, pin=pin, metrics=metrics)


def refresh_catalog_join(native, *, dataset, operation, left_pin, right_pin,
                         keys, fields, base_pin=None, prior_left_pin=None,
                         prior_right_pin=None, mode="full",
                         definition="catalog-join-v1", join_kind="inner",
                         nulls="never", cardinality="many_to_one",
                         policy="captured"):
    """Maintain an incremental or full equality join over ``left_pin`` and ``right_pin``.

    Supports bounded one-hop equality joins with explicit ``join_kind``
    (``'inner'`` or ``'left'``), ``nulls`` (``'never'`` or ``'equal'``), and
    ``cardinality`` (``'one_to_one'``, ``'many_to_one'``, or ``'many_to_many'``),
    while keeping recursive/transitive alias-component closure in Python.
    """
    if getattr(native, "remote", None) is not None:
        raise ValueError(
            "400 remote_unsupported: /refreshes requires BackendCapability::LocalOnly "
            "and is not supported on remote R2"
        )
    left_ref = version_ref(left_pin)
    right_ref = version_ref(right_pin)
    base_version = version_ref(base_pin)["version"] if base_pin is not None else None
    if mode == "incremental" and base_version is None:
        raise ValueError("incremental refresh requires base_pin")
    normalized_keys = []
    for k in keys:
        if isinstance(k, str):
            normalized_keys.append(dict(left=k, right=k))
        elif isinstance(k, (tuple, list)) and len(k) == 2:
            normalized_keys.append(dict(left=str(k[0]), right=str(k[1])))
        elif isinstance(k, dict) and "left" in k and "right" in k:
            normalized_keys.append(dict(left=str(k["left"]), right=str(k["right"])))
        else:
            raise ValueError(f"Invalid join key specification: {k!r}")
    normalized_fields = [
        dict(
            side=str(f["side"]),
            field=str(f["field"]),
            name=str(f.get("name", f["field"])),
        )
        for f in fields
    ]
    spec = dict(
        dataset=dataset,
        operation=operation,
        base=base_version,
        definition=definition,
        mode=mode,
        policy=policy,
        transform=dict(
            kind="join",
            left=left_ref,
            right=right_ref,
            join=dict(
                keys=normalized_keys,
                kind=join_kind,
                nulls=nulls,
                cardinality=cardinality,
                fields=normalized_fields,
            ),
        ),
    )
    executed_requests = 0
    t0 = time.perf_counter()
    plan = native.plan_refresh(spec)
    executed_requests += 1
    pin = native.refresh(spec)
    executed_requests += 1
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    metrics = _compute_refresh_metrics(
        pin,
        mode=mode,
        base_pin=base_pin,
        input_pins=(left_pin, right_pin),
        prior_input_pins=(prior_left_pin, prior_right_pin),
        elapsed_ms=elapsed_ms,
        native=native,
        dataset=dataset,
        operation=operation,
        executed_requests=executed_requests,
    )
    return dict(plan=plan, pin=pin, metrics=metrics)


# -- ct-sb0s: Occurrence-linked provenance and review receipts -----------------


EVIDENCE_KEY_SCHEMA = pa.schema([
    pa.field("source_file", pa.string(), nullable=False),
    pa.field("source_row", pa.int64(), nullable=False),
])


def map_locators_to_occurrences(native, source_pin, *, locator_column):
    """Map application locator values to their exact ``(source_file, source_row)`` occurrences."""
    table = native.read_occurrences(source_pin)
    if locator_column not in table.column_names:
        raise ValueError(f"Locator column {locator_column!r} is absent from source schema")
    mapping = {}
    for row in table.to_pylist():
        locator = row[locator_column]
        occ = (row["__docspec_file"], int(row["__docspec_row"]))
        mapping.setdefault(locator, []).append(occ)
    return mapping


def attach_occurrence_receipts(native, *, dataset, operation, base_pin, definition,
                               locator_to_occurrences, receipts, deletions=(),
                               evidence_type=pa.string()):
    """Attach occurrence-linked provenance/review receipts without rewriting source files.

    ``receipts`` is an iterable of ``(locator, evidence_value)`` pairs; each
    occurrence bound to ``locator`` receives the receipt value (preserving
    ordered duplicate receipts and explicit ``None`` nulls). ``deletions`` is an
    iterable of locators whose receipts should be removed. Verifies that the
    resulting ``ReleasePin`` keeps the exact same ``source`` ``TablePin`` (zero
    source-byte rewrites).
    """
    ref = version_ref(base_pin)
    if ref["dataset"] != dataset:
        raise ValueError("base_pin dataset differs from target dataset")
    rep_rows = []
    for locator, value in receipts:
        occurrences = locator_to_occurrences.get(locator)
        if not occurrences:
            raise ValueError(f"Unknown application locator {locator!r}")
        for source_file, source_row in occurrences:
            rep_rows.append(
                dict(source_file=source_file, source_row=int(source_row), evidence=value)
            )
    rep_schema = pa.schema([
        pa.field("source_file", pa.string(), nullable=False),
        pa.field("source_row", pa.int64(), nullable=False),
        pa.field("evidence", evidence_type, nullable=True),
    ])
    rep_table = pa.Table.from_pylist(rep_rows, schema=rep_schema)

    del_table = None
    if deletions:
        del_rows = []
        for locator in deletions:
            occurrences = locator_to_occurrences.get(locator)
            if not occurrences:
                raise ValueError(f"Unknown deletion locator {locator!r}")
            for source_file, source_row in occurrences:
                del_rows.append(dict(source_file=source_file, source_row=int(source_row)))
        del_table = pa.Table.from_pylist(del_rows, schema=EVIDENCE_KEY_SCHEMA)

    pin = native.update_evidence_table(
        rep_table,
        dataset=dataset,
        operation=operation,
        definition=definition,
        base=ref["version"],
        deletions=del_table,
    )
    if pin["dataset"]["groups"]["source"] != base_pin["dataset"]["groups"]["source"]:
        raise AssertionError("Receipt update rewrote the source group")
    return pin


def read_occurrence_receipts(native, pin, *, occurrence_to_locator=None):
    """Read attached receipts and optionally map ``(source_file, source_row)`` back to locators."""
    table = native.read_receipts(pin)
    rows = []
    for row in table.to_pylist():
        occ = (row["source_file"], int(row["source_row"]))
        entry = dict(
            source_file=occ[0],
            source_row=occ[1],
            evidence=row["evidence"],
        )
        if occurrence_to_locator is not None:
            entry["locator"] = occurrence_to_locator.get(occ)
        rows.append(entry)
    return rows
