"""Rebuild the paired document tables from retained receipts and source bodies.

Every run replays source context; unchanged filename/body meanings may be cached
by their existing parser fingerprints. Preserve prior tables before replacement.
Documents publish first and filenames last using the store's conditional writes.
Readers must check matching catalog_id values, including after an interrupted run.
"""

from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.compute as pc

from congress_api.parsers.source_family import family as source_family
from congress_api.retention import document_index as index
from congress_api.retention.document_evidence import read_retained_body
from congress_api.retention.document_recovery import recover_sources, recovery_fingerprint
from congress_api.retention.raw_archive import CAPTURES_KEY, CAPTURE_SCHEMA, decode_table

FILENAMES = "indexes/document-filenames.parquet"
DOCUMENTS = "indexes/documents.parquet"


def rebuild_catalog(store, captures=None, *, seeds=(), workers=4):
    """Publish derived tables only; never instantiate or save acquisition state."""
    if captures is None:
        data = store.read(CAPTURES_KEY)
        if data is None:
            raise ValueError("Missing retained capture index")
        captures = decode_table(data)
    if captures.schema.remove_metadata() != CAPTURE_SCHEMA:
        raise ValueError("Unexpected capture index schema")
    previous_bytes = store.read(FILENAMES)
    previous = decode_table(previous_bytes) if previous_bytes else None
    # Read both ETags before publication; also retain any unmatched prior pair.
    previous_documents = store.read(DOCUMENTS)
    meta = (previous.schema.metadata or {}) if previous is not None else {}
    if int(meta.get(b"raw_capture_rows", b"0")) > len(captures):
        raise ValueError("Capture index was truncated since the last catalog rebuild")
    sources = {}

    def add(body_key, filename, source_url, **values):
        key = (body_key, filename, source_url)
        row = sources.setdefault(key, dict(body_key=body_key, filename=filename, source_url=source_url))
        for field, items in values.items():
            if items:
                row[field] = index.merge_values(field, row.get(field), items)
        return row

    context = index.DocumentSources()
    if previous is not None:
        columns = [f for f in previous.column_names if f in
                   set(index.SOURCE_SCHEMA.names) | index.SOURCE_CONTEXT_FIELDS | {"capture_outcome"}]
        for batch in previous.select(columns).to_batches(max_chunksize=4096):
            for row in batch.to_pylist():
                # Preserve known source locators and actual response facts. Old
                # flat context has no reliable basis; its exact bytes are archived
                # below, before replacement, instead of guessing a native type.
                add(**{k: v for k, v in row.items() if k not in index.SOURCE_CONTEXT_FIELDS})
                for occurrence in row.get("source_occurrences") or []:
                    if occurrence.get("source_document_type_basis") == ["publisher"] or occurrence.get("source_probe_status"):
                        context.add_url(row.get("source_url"), occurrence)

    read_body = lambda key: read_retained_body(None, key, read_compressed=store.read)
    context = index.read_document_sources(captures=captures, read_receipt=store.read,
                                          read_body=read_body, context=context)

    def link_names(link, receipt=None):
        url = link.get("url")
        if not url:
            return
        context.add_link(link, receipt)
        names = index.url_document_names(url)
        if not names and (name := index.url_filename(url)):
            names = [(name, "url_path")]
        for name, basis in names:
            add(None, name, url, filename_origins=[basis])

    for link in seeds:
        link_names(link)
    # Include migration receipts and recurring captures, regardless of cursor.
    # Historical Senate download routing is interpreted by the current owner.
    selected = pc.is_in(captures["family"], value_set=pa.array(index.FAMILIES))
    senate = captures.filter(pc.equal(captures["family"], "senate/pages"))
    downloads = pa.array(sorted({url for url in senate["context_url"].to_pylist()
                                 if url and source_family(url=url) == "documents"}), type=pa.string())
    selected = pc.or_(selected, pc.and_(pc.equal(captures["family"], "senate/pages"),
                                      pc.is_in(captures["context_url"], value_set=downloads)))
    recurring = pc.fill_null(pc.match_substring(captures["receipt_key"], "/download-"), False)
    selected = pc.or_(selected, recurring)
    for record, rows, receipt in index.retained_records(captures.filter(selected), store.read):
        if isinstance(record, dict):
            for link in record.get("source_context", {}).get("observations", []):
                link_names(link, receipt)
            for link in record.get("links", []):
                link_names(link, receipt)
            context.add_redirect(record, receipt)
            context.add_associations(record, receipt)
        for row in rows:
            is_recurring = "/download-" in (row.get("receipt_key") or "")
            if is_recurring and json.loads(row.get("pointer_json") or "[]") not in ([], ["content", "body"]):
                continue  # Provider transport and prior attempts are not this response.
            observed = index.response_metadata(row, record)
            locator = {k: sorted(v) for k, v in {**receipt, **index.context_values(
                source_capture_file=row.get("source_file"), source_capture_pointer=row.get("pointer_json"),
                source_capture_url=row.get("context_url"), source_occurrence_scope="capture")}.items()}
            observed.update({**locator, "source_occurrences": [locator]})
            owner = index.nearest_record(record, row.get("pointer_json"))
            if owner.get("outcome"):
                observed["capture_outcome"] = [owner["outcome"]]
            if row.get("body_key") or is_recurring:
                for name, basis, url, source in index.source_names(row, record) or [(None, None, None, None)]:
                    add(row.get("body_key") or owner.get("retained_body_key"), name, url, filename_origins=[basis] if basis else [],
                        source_paths=[source] if basis == "retained_path" else [], **observed)
            elif row.get("context_url"):
                for name, basis in index.url_document_names(row["context_url"]):
                    add(None, name, row["context_url"], filename_origins=[basis], **observed)
        if (any(not row.get("body_key") for row in rows)
                and not (isinstance(record, dict) and "xml_url" in record and "pdf_url" in record)):
            for name, basis, url in index.inventory_names(record):
                add(None, name, url, filename_origins=[basis])
    # Metadata-only publisher records can list files with no capture yet.
    for url, values in context.by_url.items():
        if values.get("source_link_url"):
            for name, basis in index.url_document_names(url) or [(index.url_filename(url), "url_path")]:
                add(None, name, url, filename_origins=[basis] if name else [])

    captured = defaultdict(list)
    for (body, name, url), row in sources.items():
        if body and url:
            captured[(name, url)].append(row)
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
    del context
    source_rows = recover_sources(sources.values(), captures, read_receipt=store.read)
    with TemporaryDirectory(prefix="raw-catalog-") as directory:
        root = Path(directory)
        (root / "indexes").mkdir()
        result = index.write_filename_metadata(
            root, source_rows, workers=workers, previous=previous, read_body=read_body,
            metadata={"raw_capture_rows": str(len(captures)),
                      "retained_recovery_fingerprint": recovery_fingerprint()},
        )
        index.validate_document_indexes(root / FILENAMES, root / DOCUMENTS,
                                        source_rows=result["rows"], document_rows=result["document_rows"])
        # Retain evidence that exists only in an older generated table, including
        # columns whose original publisher/parser basis can no longer be proved.
        for label, key, data in (("filenames", FILENAMES, previous_bytes),
                                 ("documents", DOCUMENTS, previous_documents)):
            if data is not None:
                saved = f"catalog-history/sha256/{sha256(data).hexdigest()}/{Path(key).name}"
                store.put(saved, data, immutable=True)
                result[f"previous_{label}_key"] = saved
        store.put(DOCUMENTS, (root / DOCUMENTS).read_bytes())
        store.put(FILENAMES, (root / FILENAMES).read_bytes())
    return {k: v for k, v in result.items() if k not in ("output", "documents_output")}
