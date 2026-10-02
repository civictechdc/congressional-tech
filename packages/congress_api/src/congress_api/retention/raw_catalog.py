"""Rebuild both document tables from saved names and new durable receipts.

Selected House bodies are read through the supplied store; unchanged body meanings
are reused from the previous table. The filename table commits last and carries the capture
row count consumed. If publishing either table fails, the next run repeats the
uncommitted delta. Readers must check that both tables have the same catalog_id.
"""

from collections import defaultdict
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention import document_index as index
from congress_api.retention.document_evidence import read_retained_body
from congress_api.retention.document_recovery import recover_sources, recovery_fingerprint

FILENAMES = "indexes/document-filenames.parquet"
DOCUMENTS = "indexes/documents.parquet"


def rebuild_catalog(store, captures, *, seeds=(), workers=4):
    previous_bytes = store.read(FILENAMES)
    previous = (
        pq.read_table(pa.BufferReader(previous_bytes)) if previous_bytes else None
    )
    # Read both ETags before publication; never overwrite an unread index.
    store.read(DOCUMENTS)
    meta = (previous.schema.metadata or {}) if previous is not None else {}
    cursor = int(meta.get(b"raw_capture_rows", b"0"))
    if cursor > len(captures):
        raise ValueError("Capture index was truncated since the last catalog rebuild")
    source_fields = (
        set(index.SOURCE_SCHEMA.names)
        | index.SOURCE_CONTEXT_FIELDS
        | {"capture_outcome"}
    )
    sources = {}

    def add(body_key, filename, source_url, **values):
        key = (body_key, filename, source_url)
        row = sources.setdefault(
            key, dict(body_key=body_key, filename=filename, source_url=source_url)
        )
        for field, items in values.items():
            if items:
                row[field] = index.merge_values(field, row.get(field), items)
        return row

    context = index.DocumentSources()
    if previous is not None:
        columns = [f for f in previous.column_names if f in source_fields]
        for batch in previous.select(columns).to_batches(max_chunksize=4096):
            for row in batch.to_pylist():
                add(**row)
                context.add_url(
                    row.get("source_url"),
                    {k: v for k, v in row.items() if k in index.SOURCE_CONTEXT_FIELDS},
                )

    def link_names(link):
        url = link.get("url")
        if not url:
            return
        context.add_link(link)
        names = index.url_document_names(url)
        if not names and (name := index.url_filename(url)):
            names = [(name, "url_path")]
        for name, basis in names:
            add(None, name, url, filename_origins=[basis])

    for link in seeds:
        link_names(link)
    # Bootstrap tables already cover migration receipts. Recurring receipts
    # must also be consumed on the first run, including any interrupted run.
    references = defaultdict(lambda: defaultdict(list))
    for batch in captures.slice(cursor).to_batches(max_chunksize=65536):
        for row in batch.to_pylist():
            key = row.get("receipt_key") or ""
            if "/download-" in key:
                references[key][row["receipt_line"]].append(row)
    if previous is None and len(captures) and not references:
        raise ValueError(
            "Initial filename inventory is required before recurring rebuild"
        )
    for key, lines in sorted(references.items()):
        payload = store.read(key)
        if payload is None:
            raise ValueError(f"Missing capture receipt: {key}")
        for number, line in enumerate(gzip.decompress(payload).splitlines(), 1):
            rows = lines.pop(number, None)
            if rows is None:
                continue
            receipt = json.loads(line)
            record = receipt["record"]
            for link in record.get("source_context", {}).get("observations", []):
                link_names(link)
            for link in record.get("links", []):
                link_names(link)
            context.add_redirect(record)
            context.add_associations(record)
            for row in rows:
                if json.loads(row.get("pointer_json") or "[]") not in (
                    [],
                    ["content", "body"],
                ):
                    continue
                observed = index.response_metadata(row, record)
                observed["capture_outcome"] = [record["outcome"]]
                for name, basis, url, _ in index.source_names(row, record):
                    add(
                        row.get("body_key") or record.get("retained_body_key"),
                        name,
                        url,
                        filename_origins=[basis],
                        **observed,
                    )
        if lines:
            raise ValueError(f"Capture index references missing receipt lines: {key}")

    # A queued name stops being an unfetched duplicate once that exact name/URL
    # has a captured body. Keep all historical body versions and source values.
    captured = defaultdict(list)
    for key, row in sources.items():
        if key[0] and key[2]:
            captured[key[1:]].append(row)
    for key in list(sources):
        body, name, url = key
        if body is None and (name, url) in captured:
            old = sources.pop(key)
            for row in captured[(name, url)]:
                for field, items in old.items():
                    if isinstance(items, list):
                        row[field] = index.merge_values(field, row.get(field), items)
    for row in sources.values():
        for field, values in context.for_url(row.get("source_url")).items():
            row[field] = index.merge_values(field, row.get(field), values)
    recovery = recovery_fingerprint()
    replay = captures if meta.get(b'retained_recovery_fingerprint') != recovery.encode() else captures.slice(cursor)
    source_rows = recover_sources(sources.values(), replay, read_receipt=store.read)
    with TemporaryDirectory(prefix="raw-catalog-") as directory:
        root = Path(directory)
        (root / "indexes").mkdir()
        result = index.write_filename_metadata(
            root,
            source_rows,
            workers=workers,
            previous=previous,
            read_body=lambda key: read_retained_body(None, key, read_compressed=store.read),
            metadata={"raw_capture_rows": str(len(captures)), 'retained_recovery_fingerprint': recovery},
        )
        # The filename table is the cursor: publish it only after documents.
        store.put(DOCUMENTS, (root / DOCUMENTS).read_bytes())
        store.put(FILENAMES, (root / FILENAMES).read_bytes())
    return {k: v for k, v in result.items() if k not in ("output", "documents_output")}
