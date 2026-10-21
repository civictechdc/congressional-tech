"""Application adapters for DocSpec change streams, schema/backfill, refresh, and receipts.

Each helper binds exact ``ReleasePin`` versions through the shared ``docspec_client``
transport while preserving application authority over source identity, transitive
alias closure, review decisions, and coherent multi-table publication.
"""
import pyarrow as pa


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


# -- ct-13cn: Certified change streams & catalog diagnostics -------------------


def inspect_catalog_changes(native, before_pin, after_pin, *, group="source",
                            identity="occurrences", key_column=None,
                            allow_full_fallback=True):
    """Consume one native ``/changes`` stream and derive counts and affected keys.

    Does not call ``/compare`` and ``/changes`` redundantly when row changes are
    consumed. Verifies exact endpoint ``VersionRef`` bindings and refuses
    unbounded full-fallback reconstruction when ``allow_full_fallback=False``.
    """
    expected_before = version_ref(before_pin)
    expected_after = version_ref(after_pin)
    with native.changes_batches(
        before_pin,
        after_pin,
        group=group,
        identity=identity,
        force_full=False,
    ) as (descriptor, reader):
        if not isinstance(descriptor, dict):
            raise ValueError("Change stream is missing its docspec.change descriptor")
        if descriptor.get("before") != expected_before or descriptor.get("after") != expected_after:
            raise ValueError("Change stream descriptor endpoints differ from the requested pins")
        path = descriptor.get("path")
        # docspec-rs serializes ChangeDescriptor.fallback (ComparisonFallback, snake_case)
        # and ComparisonEffects.evidence_refs_changed; accept only those names.
        fallback_reason = descriptor.get("fallback")
        if not allow_full_fallback and path == "full":
            raise ValueError(
                f"Incremental caller refused full comparison fallback ({fallback_reason})"
            )
        batches = list(reader)
        table = pa.Table.from_batches(batches, schema=reader.schema)

    added_rows = 0
    removed_rows = 0
    added_records = []
    removed_records = []
    changed_keys = set()
    rows = table.to_pylist()
    for row in rows:
        side = row.get("side") or row.get("change") or row.get("__docspec_change")
        record = row.get("values") if isinstance(row.get("values"), dict) else {
            k: v for k, v in row.items()
            if k not in {"side", "file", "row", "change", "weight"} and not k.startswith("__docspec_")
        }
        if key_column is not None and isinstance(record, dict) and record.get(key_column) is not None:
            changed_keys.add(record[key_column])
        if side in ("after", "added", "+1", 1):
            added_rows += 1
            added_records.append(record)
        elif side in ("before", "removed", "-1", -1):
            removed_rows += 1
            removed_records.append(record)

    effects = descriptor.get("effects") or {}
    return dict(
        descriptor=descriptor,
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
        changed_keys=sorted(changed_keys),
        table=table,
    )


# -- ct-dmca: Compatible schema evolution & resumable scalar backfills ---------


def source_schema_fields(native, pin):
    """Discover root Iceberg field IDs and names from a verified ``ReleasePin``."""
    version_ref(pin)
    with native.source_batches(pin) as reader:
        schema = reader.schema
    fields = []
    for idx, field in enumerate(schema, start=1):
        if field.name.startswith("__docspec_"):
            continue
        meta = field.metadata or {}
        raw_id = meta.get(b"PARQUET:field_id") or meta.get("PARQUET:field_id")
        field_id = (
            int(raw_id.decode() if isinstance(raw_id, bytes) else raw_id)
            if raw_id is not None
            else idx
        )
        fields.append(dict(id=field_id, name=field.name))
    return fields


def _parquet_source_paths(pin):
    return [
        obj["path"]
        for obj in pin.get("dataset", {}).get("groups", {}).get("source", {}).get("objects", ())
        if isinstance(obj, dict) and str(obj.get("path", "")).endswith(".parquet")
    ]


def evolve_catalog_schema(native, *, dataset, operation, base_pin, definition,
                          next_definition, fields=None, additions=(), write_defaults=None):
    """Apply a metadata-only compatible schema evolution against ``base_pin``."""
    ref = version_ref(base_pin)
    if ref["dataset"] != dataset:
        raise ValueError("base_pin dataset differs from target dataset")
    if fields is None:
        fields = source_schema_fields(native, base_pin)
    source_files_before = _parquet_source_paths(base_pin)
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
    if _parquet_source_paths(pin) != source_files_before:
        raise AssertionError("Schema evolution rewrote source data files")
    return dict(plan=plan, pin=pin)


def backfill_scalar_group(native, *, dataset, operation, base_pin, definition,
                          group, group_definition, fields, continuous=None,
                          correction=None):
    """Compute or resume a row-local scalar field group over ``base_pin``."""
    ref = version_ref(base_pin)
    if ref["dataset"] != dataset:
        raise ValueError("base_pin dataset differs from target dataset")
    source_files_before = _parquet_source_paths(base_pin)
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
        if correction.get("qualify", True) and (
            pin.get("dataset", {}).get("computed", {}).get(group, {}).get("qualification") is None
        ):
            qualify_spec = dict(
                backfill_spec,
                operation=str(correction.get("qualify_operation") or f"{operation}-qualify"),
                base=pin["id"],
            )
            pin = native.backfill(qualify_spec)
    if _parquet_source_paths(pin) != source_files_before:
        raise AssertionError("Scalar backfill rewrote source data files")
    return dict(plan=plan, pin=pin, correction=correction_decision)


# -- ct-gziq: Eligible catalog equality joins and aggregate rollups ------------


def refresh_catalog_observation_summary(native, *, dataset, operation, source_pin,
                                        base_pin=None, mode="full",
                                        definition="catalog-obs-summary-v1",
                                        keys=("alias",), count_field="observation"):
    """Maintain an incremental or full observation summary over ``source_pin``.

    Preserves transitive alias closure in Python (`catalog_dependencies.py`) while
    offloading grouped observation counts (`CountRows`, `CountDistinct`) to native
    `Refresh` over exact pinned inputs (`policy='captured'`).
    """
    source_ref = version_ref(source_pin)
    base_version = version_ref(base_pin)["version"] if base_pin is not None else None
    if mode == "incremental" and base_version is None:
        raise ValueError("incremental refresh requires base_pin")
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
                aggregates=[
                    dict(name="total_rows", function=dict(kind="count_rows")),
                    dict(
                        name="distinct_observations",
                        function=dict(kind="count_distinct", field=count_field),
                    ),
                ],
            ),
        ),
    )
    plan = native.plan_refresh(spec)
    pin = native.refresh(spec)
    return dict(plan=plan, pin=pin)


# -- ct-sb0s: Occurrence-linked provenance and review receipts -----------------


EVIDENCE_KEY_SCHEMA = pa.schema([
    pa.field("source_file", pa.string(), nullable=False),
    pa.field("source_row", pa.int64(), nullable=False),
])


def map_locators_to_occurrences(native, source_pin, *, locator_column):
    """Map application locator values to their exact ``(source_file, source_row)`` occurrences."""
    version_ref(source_pin)
    table = native.read_occurrences(source_pin)
    if isinstance(locator_column, (tuple, list)):
        missing = [col for col in locator_column if col not in table.column_names]
        if missing:
            raise ValueError(f"Locator columns {missing!r} are absent from source schema")
        extract = lambda row: tuple(row[col] for col in locator_column)
    else:
        if locator_column not in table.column_names:
            raise ValueError(f"Locator column {locator_column!r} is absent from source schema")
        extract = lambda row: row[locator_column]
    mapping = {}
    for row in table.to_pylist():
        locator = extract(row)
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


def read_occurrence_receipts(native, pin, *, occurrence_to_locator=None,
                             expected_source_pin=None, expected_evidence_pin=None):
    """Read attached receipts and optionally map ``(source_file, source_row)`` back to locators."""
    version_ref(pin)
    if expected_source_pin is not None and pin["dataset"]["groups"]["source"] != expected_source_pin:
        raise ValueError("Receipt read source version differs from expected pin")
    if expected_evidence_pin is not None and pin["dataset"].get("evidence") != expected_evidence_pin:
        raise ValueError("Receipt read evidence version differs from expected pin")
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


def remap_occurrence_receipts(native, *, dataset, operation, before_pin, after_pin,
                              definition, locator_column, updated_receipts=(),
                              deleted_locators=(), evidence_type=pa.string()):
    """Remap surviving occurrence receipts by application locator across source updates.

    Preserves ordered duplicate receipts and explicit ``None`` nulls by
    application locator rather than native ``(source_file, source_row)`` row
    positions. Receipts for deleted or withdrawn locators are dropped.
    """
    version_ref(before_pin)
    after_ref = version_ref(after_pin)
    if after_ref["dataset"] != dataset:
        raise ValueError("after_pin dataset differs from target dataset")
    before_map = map_locators_to_occurrences(native, before_pin, locator_column=locator_column)
    before_inv = {occ: loc for loc, occs in before_map.items() for occ in occs}
    after_map = map_locators_to_occurrences(native, after_pin, locator_column=locator_column)

    deleted_set = set(deleted_locators)
    updated_by_locator = {}
    for locator, value in updated_receipts:
        updated_by_locator.setdefault(locator, []).append((locator, value))

    # Deduplicate per-(locator, occurrence) when a locator spans multiple rows in before_pin
    prior_by_occ = {}
    if before_pin.get("dataset", {}).get("evidence") is not None:
        for entry in read_occurrence_receipts(
            native,
            before_pin,
            occurrence_to_locator=before_inv,
            expected_source_pin=before_pin["dataset"]["groups"]["source"],
            expected_evidence_pin=before_pin["dataset"]["evidence"],
        ):
            occ = (entry["source_file"], entry["source_row"])
            prior_by_occ.setdefault(occ, []).append(entry["evidence"])

    carried_receipts = []
    for locator, occs in before_map.items():
        if locator in deleted_set or locator in updated_by_locator or locator not in after_map:
            continue
        first_occ = occs[0]
        for value in prior_by_occ.get(first_occ, ()):
            carried_receipts.append((locator, value))

    for locator, items in updated_by_locator.items():
        if locator not in deleted_set:
            carried_receipts.extend(items)

    if not carried_receipts:
        return after_pin
    return attach_occurrence_receipts(
        native,
        dataset=dataset,
        operation=operation,
        base_pin=after_pin,
        definition=definition,
        locator_to_occurrences=after_map,
        receipts=carried_receipts,
        evidence_type=evidence_type,
    )
