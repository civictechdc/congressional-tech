"""Metadata recovery, response facts, source refresh, and name inventory collection."""
from collections import defaultdict
from collections.abc import Mapping
import gzip
from hashlib import sha256
import inspect
from io import BytesIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unicodedata

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from congress_api.retention.body_keys import body_key_digest
from congress_api.retention.capture_metadata import RESULT_COLUMNS
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_staging import DiskRows, WorkingCatalog
import congress_api.retention.catalog_publication as catalog_publication
from congress_api.retention.document_evidence import (
    apply_response_role,
    enrich_document_covers,
    read_retained_body,
)
from congress_api.retention.index.builder import publish_local_result, write_document_indexes
from congress_api.retention.index.document_sources import DocumentSources
from congress_api.retention.index.records import (
    capture_batches,
    capture_schema,
    read_document_sources,
    record_from_capture_row,
    retained_records,
)
from congress_api.retention.index.schemas import (
    BODY_FIELDS,
    COVER_FIELDS,
    FAMILIES,
    RESPONSE_FIELDS,
    SOURCE_CONTEXT_FIELDS,
    SOURCE_OCCURRENCE_FIELDS,
    SOURCE_SCHEMA,
    extract,
    merge_values,
    metadata_type,
)
from congress_api.retention.index.sources import (
    add_name,
    capture_record_type,
    context_values,
    inventory_names,
    nearest_record,
    response_metadata,
    source_names,
    url_document_names,
)
from congress_api.parsers.source_family import family as source_family


def refresh_response_metadata(
    root, rows, *, captures=None, fetch_outcomes=None, states=None, read_receipt=None
):
    """Recover response facts by exact body/URL and locators for unplaced bodies.

    A body-only row can recover its capture locations, but cannot borrow one
    response's success/failure from other requests that returned the same bytes.
    Reads directly from ``captures`` / ``fetch_outcomes`` / ``states`` tables when
    available without re-opening ``.jsonl.gz`` receipt files.
    """
    root_path = Path(root) if isinstance(root, (str, Path)) else None
    if captures is None and hasattr(root, "captures"):
        captures = root.captures() if callable(root.captures) else root.captures
    if captures is None:
        if root_path is None:
            return
        path = root_path / "indexes/captures.parquet"
        if not path.exists():
            return
        archive = pq.ParquetFile(path)
        schema_names = set(archive.schema_arrow.names)
    else:
        archive = captures
        schema_names = set(capture_schema(archive).names)
    targets = defaultdict(list)
    unplaced = set()
    for row in rows:
        if row.get("body_key") and (row.get("source_url") or row.get("filename") is None):
            targets[(row["body_key"], row.get("source_url"))].append(row)
            if not row.get("source_occurrences") or all(
                o.get("source_occurrence_scope") == ["capture"]
                for o in row["source_occurrences"]
            ):
                unplaced.add(id(row))
    if not targets:
        return
    required = {
        "body_key",
        "receipt_key",
        "receipt_line",
        "pointer_json",
        "context_url",
    }
    if not required <= schema_names:
        return
    state_by_url = {}
    for table_src in (fetch_outcomes, states):
        if table_src is None:
            continue
        rows_iter = (
            table_src.to_pylist()
            if isinstance(table_src, pa.Table)
            else (
                table_src.read().to_pylist()
                if isinstance(table_src, pq.ParquetFile)
                else list(table_src)
            )
        )
        for srow in rows_iter:
            u = srow.get("url") or srow.get("context_url")
            if u:
                state_by_url[u] = srow
    references = defaultdict(lambda: defaultdict(list))
    bodies = pa.array(sorted({key[0] for key in targets}), type=pa.string())
    optional_cols = {
        "family",
        "source_file",
        "original_path",
        "media_type",
        "http_status",
        "resolution",
        "outcome",
        "fidelity",
        "record_json",
        "usable",
        "body_complete",
        "complete",
        "format",
        "result",
    }
    columns = required | (optional_cols & schema_names)
    batches = (
        archive.iter_batches(columns=sorted(columns))
        if isinstance(archive, pq.ParquetFile)
        else capture_batches(archive, sorted(columns))
    )
    for batch in batches:
        selected = pa.Table.from_batches([batch])
        selected = selected.filter(
            pc.is_in(pc.cast(selected["body_key"], pa.string()), value_set=bodies)
        )
        for capture in selected.to_pylist():
            references[capture["receipt_key"]][capture["receipt_line"]].append(capture)

    def _apply_capture_facts(receipt, number, capture, record):
        owner = nearest_record(record, capture["pointer_json"])
        facts = response_metadata(capture, record)
        urls = {
            url
            for url in (
                capture["context_url"],
                owner.get("requested_url"),
                owner.get("final_url"),
                owner.get("url"),
            )
            if isinstance(url, str) and url
        }
        for url in urls | {None}:
            for row in targets.get((capture["body_key"], url), ()):
                if url is not None:
                    for field in RESPONSE_FIELDS:
                        if facts.get(field):
                            row[field] = merge_values(field, row.get(field), facts[field])
                if id(row) in unplaced:
                    occurrence = {
                        key: sorted(values)
                        for key, values in context_values(
                            source_capture_file=capture.get("source_file"),
                            source_capture_pointer=capture["pointer_json"],
                            source_receipt_key=receipt,
                            source_receipt_line=number,
                            source_occurrence_scope="capture",
                        ).items()
                    }
                    if urls:
                        occurrence["source_capture_url"] = sorted(urls)
                    row["source_occurrences"] = merge_values(
                        "source_occurrences", row.get("source_occurrences"), [occurrence]
                    )
                    for field, values in occurrence.items():
                        row[field] = merge_values(field, row.get(field), values)
                    if capture.get("original_path"):
                        row["source_paths"] = merge_values(
                            "source_paths",
                            row.get("source_paths"),
                            [capture["original_path"]],
                        )
                if not row.get("source_record_type") and (
                    kind := capture_record_type(
                        capture.get("family"), capture.get("pointer_json")
                    )
                ):
                    row["source_record_type"] = [kind]
                    row["record_role"] = ["source-record"]

    table_only = fetch_outcomes is not None or states is not None
    for receipt, lines in sorted(references.items()):
        receipt_path = (root_path / receipt) if root_path is not None else None
        can_read_gz = not table_only and (
            read_receipt is not None or (receipt_path is not None and receipt_path.exists())
        )
        if not can_read_gz:
            for number, cap_list in sorted(lines.items()):
                for capture in cap_list:
                    srow = state_by_url.get(capture.get("context_url"))
                    record = record_from_capture_row(capture, srow)
                    _apply_capture_facts(receipt, number, capture, record)
            lines.clear()
            continue
        stream_ctx = (
            gzip.open(BytesIO(read_receipt(receipt)), "rt", encoding="utf-8")
            if read_receipt is not None
            else gzip.open(receipt_path, "rt", encoding="utf-8")
        )
        with stream_ctx as stream:
            for number, line in enumerate(stream, 1):
                cap_list = lines.pop(number, None)
                if cap_list is not None:
                    record = json.loads(line)["record"]
                    for capture in cap_list:
                        _apply_capture_facts(receipt, number, capture, record)
                if not lines:
                    break
        if lines:
            raise ValueError(
                f"Response index references missing receipt lines: {receipt}"
            )


def refresh_source_metadata(root, context=None):
    """Refresh source facts from one captured selected pair, then publish together."""
    with (
        catalog_publication.read_catalog(LocalStore(root)) as snapshot,
        TemporaryDirectory(prefix="source-refresh-") as directory,
    ):
        if snapshot.filenames_path is None:
            raise ValueError("Missing filename index")
        working = WorkingCatalog(Path(directory) / "working.sqlite")
        try:
            staged = Path(directory) / "output"
            (staged / "indexes").mkdir(parents=True)
            return _refresh_source_metadata(
                root, context, working=working, snapshot=snapshot, output_root=staged
            )
        finally:
            working.close()


def _refresh_source_metadata(root, context, *, working, snapshot, output_root):
    """Refresh retained provenance and response facts, then regroup without parsing names."""
    source = pq.ParquetFile(snapshot.filenames_path)
    path = output_root / "indexes/document-filenames.parquet"
    if context is None:
        context = read_document_sources(root, context=DocumentSources(working=working))
    rows, columns = DiskRows(working.connection, "source_refresh_rows"), set()
    for batch in source.iter_batches(batch_size=4096):
        for row in batch.to_pylist():
            # A partial replay cannot retract publisher facts already retained
            # from XML/receipts. Keep those paired observations; parser-inferred
            # fields are replaced by the fresh interpretation below.
            native = [
                o
                for o in row.get("source_occurrences") or []
                if o.get("source_document_type_basis") == ["publisher"]
                or o.get("source_probe_status")
            ]
            added = context.for_url(row.get("source_url"))
            if native:
                added["source_occurrences"] = merge_values(
                    "source_occurrences", added.get("source_occurrences"), native
                )
                for occurrence in native:
                    for field, values in occurrence.items():
                        if field in SOURCE_OCCURRENCE_FIELDS and values:
                            added[field] = merge_values(field, added.get(field), values)
            row = {
                key: value
                for key, value in row.items()
                if value is not None and key not in SOURCE_CONTEXT_FIELDS
            }
            columns.update(added)
            rows.append({**row, **added})
    del context  # Rows now retain their occurrences; release lookup/transfer maps.
    for batch in rows.batches(write=True):
        refresh_response_metadata(root, [row for _, row in batch])
    columns.update(
        field
        for row in rows
        for field in row
        if field in SOURCE_CONTEXT_FIELDS | set(RESPONSE_FIELDS) | {"source_record_type"}
    )
    # Response roles depend on newly read facts, not another body download.
    for batch in rows.batches(write=True):
        for _, row in batch:
            apply_response_role(row)
    body_cache = working.mapping("source_refresh_bodies")
    for batch in rows.batches(write=True):
        enrich_document_covers(
            [row for _, row in batch],
            read_body=lambda key: read_retained_body(root, key),
            cached=body_cache,
        )
    columns.update(
        field
        for field in (*COVER_FIELDS, "body_format")
        if any(row.get(field) for row in rows)
    )
    schema = pa.schema(
        [
            *[
                f
                for f in source.schema_arrow
                if f.name not in SOURCE_CONTEXT_FIELDS | columns
            ],
            *[(name, metadata_type(name)) for name in sorted(columns)],
        ],
        metadata=source.schema_arrow.metadata,
    )
    result = dict(
        rows=len(rows),
        source_context_rows=sum(
            bool(
                r.get("source_page_url")
                or r.get("source_meeting_id")
                or r.get("source_package_id")
            )
            for r in rows
        ),
        **write_document_indexes(path, rows, schema, working=working),
    )

    return publish_local_result(root, path, result, snapshot)


def collect_names(root, inventory_dir, families=FAMILIES, *, working=None):
    captures = pq.ParquetFile(root / "indexes/captures.parquet")
    table = captures.read(
        columns=[
            "family",
            "body_key",
            "receipt_key",
            "receipt_line",
            "pointer_json",
            "context_url",
            "original_path",
            *[
                name
                for name in ("media_type", "http_status")
                if name in captures.schema_arrow.names
            ],
        ]
    )
    selected = pc.is_in(table["family"], value_set=pa.array(families))
    if "documents" in families:
        # Reinterpret historical page routing through the same source owner.
        # This recovers existing downloads without rewriting immutable receipts.
        pages = pc.equal(table["family"], "senate/pages")
        urls = table.filter(pages)["context_url"].to_pylist()
        downloads = pa.array(
            sorted({url for url in urls if url and source_family(url=url) == "documents"}),
            type=pa.string(),
        )
        selected = pc.or_(
            selected, pc.and_(pages, pc.is_in(table["context_url"], value_set=downloads))
        )
    table = table.filter(selected)
    bodies = set()
    names = {} if working is None else working.mapping("inventory_names")
    for record, rows, _ in retained_records(
        table, lambda key: (root / key).read_bytes()
    ):
        for row in rows:
            if row["body_key"]:
                bodies.add(row["body_key"])
                metadata = response_metadata(row, record)
                for filename, basis, url, source in (
                    source_names(row, record) or [(None, None, None, None)]
                ):
                    add_name(
                        names, row["body_key"], filename, url, basis, source, metadata
                    )
            elif row["context_url"]:
                for filename, basis in url_document_names(row["context_url"]):
                    add_name(names, None, filename, row["context_url"], basis)
        if any(row["body_key"] is None for row in rows):
            for filename, basis, url in inventory_names(record):
                add_name(names, None, filename, url, basis)

    # The full filename corpus includes URL-query and response-header names,
    # even when their corresponding files have never been downloaded.
    catalog = {} if working is None else working.mapping("inventory_catalog")
    for batch in pq.ParquetFile(inventory_dir / "filenames.parquet").iter_batches(
        columns=["filename_key", "filename", "variants"]
    ):
        for row in batch.to_pylist():
            catalog[row["filename_key"]] = set(row["variants"] or []) | {
                row["filename"]
            }
    known_variants = {
        filename for variants in catalog.values() for filename in variants
    }
    by_url = (
        defaultdict(set) if working is None else working.mapping("inventory_urls", set)
    )
    for _, filename, url in names:
        if url and filename:
            spellings = by_url[url]
            spellings.add(filename)
            by_url[url] = spellings
    for batch in pq.ParquetFile(inventory_dir / "urls.parquet").iter_batches(
        columns=["url", "filename_keys"]
    ):
        for row in batch.to_pylist():
            url = row["url"]
            candidates = {name for name, _ in url_document_names(url)} | by_url.get(
                url, set()
            )
            for key in row["filename_keys"] or []:
                variants = catalog[
                    key
                ]  # Reject mismatched inventories rather than dropping names.
                matched = {
                    name
                    for name in candidates
                    if unicodedata.normalize("NFKC", name).casefold() == key
                }
                # A single literal spelling is an unambiguous catalog association.
                # Never distribute ambiguous casing variants across every URL.
                if not matched and len(variants) == 1:
                    matched = variants
                for filename in matched:
                    add_name(names, None, filename, url, "filename_inventory")
    observed = {filename for _, filename, _ in names}
    for filename in sorted(known_variants - observed):
        add_name(names, None, filename, None, "filename_inventory")

    # Link only a filename/URL pair actually present in a capture. A URL can
    # serve different documents over time; neither URL nor basename alone
    # establishes which response supplied an inventory-only filename.
    captured_pairs = (
        defaultdict(set)
        if working is None
        else working.mapping("inventory_pairs", set)
    )
    for body, filename, url in names:
        if body and url:
            found = captured_pairs[(filename, url)]
            found.add(body)
            captured_pairs[(filename, url)] = found
    for key in list(names) if working is None else names:
        body, filename, url = key
        if body is None and (filename, url) in captured_pairs:
            origins = names.pop(key)
            for body in captured_pairs[(filename, url)]:
                entry = names.setdefault(
                    (body, filename, url),
                    {field: set() for field in SOURCE_SCHEMA.names[3:]},
                )
                for field in origins:
                    entry[field].update(origins[field])
                names[(body, filename, url)] = entry
    # A nameless reference does not create another filename row when that same
    # body already has a named reference elsewhere in the retained evidence.
    named_bodies = {
        body for body, filename, url in names if body and filename is not None
    }
    for body in named_bodies:
        names.pop((body, None, None), None)
    named = {key[0] for key in names if key[0]}
    for body in sorted(bodies - named):
        names[(body, None, None)] = {field: set() for field in SOURCE_SCHEMA.names[3:]}
    if not known_variants <= {key[1] for key in names}:
        raise ValueError("Known filename spellings were lost")
    return names, len(table), bodies, known_variants


def parser_fingerprint():
    """Invalidate cached meanings when either the rules or implementation change."""
    import house_naming

    root = Path(house_naming.__file__).parent
    digest = sha256()
    digest.update(inspect.getsource(extract).encode())
    for path in sorted(p for p in root.rglob("*") if p.suffix in {".py", ".json"}):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def validated_body_readings(readings):
    """Accept only explicit completed PDF readings, keyed by immutable body identity.

    Callers qualify the body hash and reading provenance before choosing these
    overrides. Normal updates never select a newer reading automatically.
    """
    selected = {}
    for row in readings:
        if not isinstance(row, Mapping):
            raise ValueError("Expected an explicit completed PDF body reading")
        key = row.get("body_key", "")
        fingerprint = row.get("parser_fingerprint")
        if not isinstance(key, str) or not isinstance(fingerprint, str):
            raise ValueError("Expected body identity and parser fingerprint strings")
        if (
            body_key_digest(key) is None
            or key in selected
            or row.get("status") != "completed"
            or row.get("error_type") is not None
            or row.get("body_format") != ["pdf"]
            or not re.fullmatch(r"[a-f0-9]{64}", fingerprint)
            or set(row) - set(RESULT_COLUMNS) - BODY_FIELDS
            or any(
                value is not None
                and (
                    not isinstance(value, list)
                    or any(not isinstance(v, str) for v in value)
                )
                for name, value in row.items()
                if name in BODY_FIELDS
            )
        ):
            raise ValueError("Expected distinct qualified completed PDF body readings")
        selected[key] = dict(row)
    return selected
