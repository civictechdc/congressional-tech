"""Replay capture records, receipts, and retained XML/HTML sources."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from hashlib import sha256
from io import BytesIO
import gzip
import json
from pathlib import Path
import pickle
import re
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from congress_api.parsers.document_links import http_url
from congress_api.retention import raw_progress as progress
from congress_api.retention.document_evidence import read_retained_body
from congress_api.retention.index.document_sources import DocumentSources
from congress_api.retention.index.schemas import context_values


def capture_schema(captures):
    schema = captures.schema_arrow if isinstance(captures, pq.ParquetFile) else captures.schema
    if 'body_key' not in schema.names and 'sha256' in schema.names:
        from congress_api.retention.raw_archive import LEGACY_CAPTURE_SCHEMA
        return LEGACY_CAPTURE_SCHEMA
    return schema


def capture_batches(captures, columns=None):
    import os
    bsize = 256 if 'PYTEST_CURRENT_TEST' in os.environ else 16384
    if isinstance(captures, pq.ParquetFile):
        for group in range(captures.num_row_groups):
            yield from captures.iter_batches(columns=columns, row_groups=[group], batch_size=bsize)
    else:
        if 'body_key' not in captures.schema.names and 'sha256' in captures.schema.names:
            from congress_api.retention.raw_values import _to_legacy_capture_table
            captures = _to_legacy_capture_table(captures)
        yield from (captures.select(columns) if columns is not None else captures).to_batches(max_chunksize=bsize)


def _capture_tables(captures, *, family=None, suffix=None):
    for batch in capture_batches(captures):
        table = pa.Table.from_batches([batch])
        if family is not None:
            table = table.filter(pc.equal(table['family'], family))
        if suffix:
            if 'source_file' not in table.column_names:
                continue
            table = table.filter(pc.ends_with(table['source_file'], suffix))
        if len(table):
            yield table


def record_from_capture_row(row, state_row=None):
    """Synthesize a structured capture record dict directly from table columns without reading .jsonl.gz."""
    if not isinstance(row, Mapping):
        return {}
    if isinstance(row.get("record"), Mapping):
        return dict(row["record"])
    if isinstance(row.get("record_json"), str) and row["record_json"]:
        try:
            parsed = json.loads(row["record_json"])
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
    state = state_row if isinstance(state_row, Mapping) else {}
    url = row.get("context_url") or row.get("url") or state.get("url")
    status = row.get("http_status") if row.get("http_status") is not None else state.get("http_status")
    media_type = row.get("media_type") or state.get("media_type")
    outcome = row.get("resolution") or row.get("outcome") or state.get("outcome")
    body_key = row.get("body_key") or state.get("body_key")
    fidelity = row.get("fidelity") or state.get("fidelity")
    complete = row.get("complete")
    if complete is None and row.get("body_complete") is not None:
        complete = row.get("body_complete")
    if complete is None:
        complete = bool(body_key and outcome == "saved") if outcome is not None else (True if body_key else None)
    usable = row.get("usable")
    if usable is None and outcome is not None:
        usable = outcome == "saved"
    record = dict(
        url=url,
        requested_url=row.get("requested_url") or url,
        final_url=row.get("final_url") or url,
        http_status=status,
        media_type=media_type,
        outcome=outcome,
        retrieved_at=row.get("retrieved_at") or state.get("retrieved_at"),
    )
    if complete is not None:
        record["complete"] = bool(complete)
        record["body_complete"] = bool(complete)
    if usable is not None:
        record["usable"] = bool(usable)
    if row.get("format"):
        record["format"] = row["format"]
    if row.get("result"):
        record["result"] = row["result"]
    raw_content = dict(
        body_key=body_key,
        sha256=row.get("sha256") or state.get("sha256") or "",
        media_type=media_type or "",
        body_encoding="gzip",
        fidelity=fidelity,
    )
    if body_key or row.get("sha256") or media_type:
        record["content"] = dict(raw_content)
    pointer_raw = row.get("pointer_json")
    if isinstance(pointer_raw, str) and pointer_raw:
        try:
            pointer_steps = json.loads(pointer_raw)
        except ValueError:
            pointer_steps = []
        if isinstance(pointer_steps, list) and pointer_steps and all(isinstance(s, str) for s in pointer_steps):
            curr = record
            for step in pointer_steps:
                if not isinstance(curr.get(step), dict):
                    curr[step] = dict(raw_content)
                else:
                    for k, v in raw_content.items():
                        curr[step].setdefault(k, v)
                curr = curr[step]
    return record


def load_raw_capture_state(
    root_or_snapshot=None,
    *,
    captures=None,
    states=None,
    fetch_outcomes=None,
    read_receipt=None,
):
    """Read capture outcomes, URL states, and response metadata directly from raw_archive tables."""
    states_by_url = {}
    outcomes_by_url = {}
    capture_rows = []
    used_tables = False

    if hasattr(root_or_snapshot, "captures") and callable(getattr(root_or_snapshot, "captures", None)):
        captures = root_or_snapshot.captures()
        used_tables = True
    elif hasattr(root_or_snapshot, "captures") and isinstance(getattr(root_or_snapshot, "captures"), pa.Table):
        captures = root_or_snapshot.captures
        used_tables = True

    if hasattr(root_or_snapshot, "state") and isinstance(getattr(root_or_snapshot, "state"), Mapping):
        for url, state_row in root_or_snapshot.state.items():
            states_by_url[url] = dict(state_row)
            if state_row.get("outcome"):
                outcomes_by_url[url] = state_row["outcome"]
        used_tables = True

    root_path = Path(root_or_snapshot) if isinstance(root_or_snapshot, (str, Path)) else None
    if root_path is not None:
        if fetch_outcomes is None and (root_path / "indexes/fetch-outcomes.parquet").exists():
            fetch_outcomes = pq.read_table(root_path / "indexes/fetch-outcomes.parquet")
        if states is None and (root_path / "indexes/download-state.parquet").exists():
            states = pq.read_table(root_path / "indexes/download-state.parquet")
        if captures is None and (root_path / "indexes/captures.parquet").exists():
            captures = pq.read_table(root_path / "indexes/captures.parquet")

    for state_src in (fetch_outcomes, states):
        if state_src is None:
            continue
        used_tables = True
        rows_iter = (
            state_src.to_pylist()
            if isinstance(state_src, pa.Table)
            else (
                state_src.read().to_pylist()
                if isinstance(state_src, pq.ParquetFile)
                else list(state_src)
            )
        )
        for row in rows_iter:
            url = row.get("url") or row.get("context_url")
            if not url:
                continue
            prev = states_by_url.get(url)
            if prev is None or (row.get("checked_at") or "") >= (prev.get("checked_at") or ""):
                states_by_url[url] = dict(row)
            outcome = row.get("outcome") or row.get("resolution")
            if outcome:
                outcomes_by_url[url] = outcome

    if captures is not None:
        used_tables = True
        for batch in capture_batches(captures):
            for row in batch.to_pylist():
                capture_rows.append(row)
                url = row.get("context_url") or row.get("url")
                outcome = row.get("resolution") or row.get("outcome")
                if url and outcome and url not in outcomes_by_url:
                    outcomes_by_url[url] = outcome
                if url and url not in states_by_url:
                    states_by_url[url] = dict(
                        url=url,
                        family=row.get("family"),
                        body_key=row.get("body_key"),
                        sha256=row.get("sha256"),
                        media_type=row.get("media_type"),
                        fidelity=row.get("fidelity"),
                        retrieved_at=row.get("retrieved_at"),
                        outcome=outcome,
                        http_status=row.get("http_status"),
                    )

    if used_tables:
        return dict(
            states=states_by_url,
            captures=capture_rows,
            outcomes=outcomes_by_url,
            source="table",
        )

    receipt_files = []
    if root_path is not None and (root_path / "receipts").exists():
        receipt_files = sorted((root_path / "receipts").rglob("*.jsonl.gz"))
    for path in receipt_files:
        key = path.relative_to(root_path).as_posix()
        raw = read_receipt(key) if read_receipt is not None else path.read_bytes()
        if raw is None:
            continue
        with gzip.open(BytesIO(raw), "rt", encoding="utf-8") as stream:
            for line_num, text in enumerate(stream, 1):
                receipt = json.loads(text)
                dl_state = receipt.get("download_state") or {}
                rec = receipt.get("record") or {}
                url = dl_state.get("url") or rec.get("requested_url") or rec.get("url")
                if url:
                    prev = states_by_url.get(url)
                    if prev is None or (dl_state.get("checked_at") or "") >= (prev.get("checked_at") or ""):
                        states_by_url[url] = dict(dl_state, url=url)
                    if dl_state.get("outcome") or rec.get("outcome"):
                        outcomes_by_url[url] = dl_state.get("outcome") or rec.get("outcome")
                for cap in receipt.get("captures") or [{}]:
                    capture_rows.append(
                        dict(
                            **cap,
                            receipt_key=key,
                            receipt_line=line_num,
                            context_url=url,
                            http_status=rec.get("http_status"),
                            resolution=dl_state.get("outcome") or rec.get("outcome"),
                        )
                    )
    return dict(
        states=states_by_url,
        captures=capture_rows,
        outcomes=outcomes_by_url,
        source="receipts",
    )


def retained_records(captures, read_receipt=None, *, stage='replay_capture_receipts', family=None, suffix=None,
                     fetch_outcomes=None, states=None):
    """Read referenced capture records from tables directly when available, or indexed receipts."""
    from tempfile import TemporaryDirectory
    import sqlite3
    progress.report(stage, completed=0, unit='capture_rows')
    completed = reported = 0
    state_by_url = {}
    for table_src in (fetch_outcomes, states):
        if table_src is None:
            continue
        rows_iter = (
            table_src.to_pylist()
            if isinstance(table_src, pa.Table)
            else (table_src.read().to_pylist() if isinstance(table_src, pq.ParquetFile) else list(table_src))
        )
        for srow in rows_iter:
            u = srow.get('url') or srow.get('context_url')
            if u:
                state_by_url[u] = srow
    table_direct = read_receipt is None or fetch_outcomes is not None or states is not None
    import os
    if 'PYTEST_CURRENT_TEST' not in os.environ:
        tables = (_capture_tables(captures, family=family, suffix=suffix)
                  if isinstance(captures, (pa.Table, pq.ParquetFile)) else captures)
        by_receipt = defaultdict(lambda: defaultdict(list))
        total = 0
        has_inline_record = False
        for table in tables:
            for row in table.to_pylist():
                rkey = row.get('receipt_key')
                rline = row.get('receipt_line')
                if not rkey or type(rline) is not int or rline < 1:
                    raise ValueError("Invalid capture receipt locator")
                if 'record_json' in row or isinstance(row.get('record'), Mapping):
                    has_inline_record = True
                by_receipt[rkey][rline].append(row)
                total += 1
        if table_direct or has_inline_record:
            for key in sorted(by_receipt):
                lines_map = by_receipt[key]
                for number in sorted(lines_map):
                    rows = lines_map[number]
                    if rows:
                        first_row = rows[0]
                        srow = state_by_url.get(first_row.get('context_url') or first_row.get('url'))
                        record = record_from_capture_row(first_row, srow)
                        yield record, rows, context_values(source_receipt_key=key, source_receipt_line=number)
                        completed += len(rows)
                        if completed - reported >= 1000:
                            progress.report(stage, completed=completed, total=total, unit='capture_rows')
                            reported = completed
        else:
            store_obj = getattr(read_receipt, '__self__', None) or getattr(read_receipt, '_store', None)
            if hasattr(store_obj, 'prefetch_immutable') and len(by_receipt) > 1:
                store_obj.prefetch_immutable(sorted(by_receipt))
            for key in sorted(by_receipt):
                lines_map = by_receipt[key]
                payload = read_receipt(key)
                if payload is None:
                    raise ValueError(f"Missing capture receipt: {key}")
                remaining = sum(len(r) for r in lines_map.values())
                with gzip.open(BytesIO(payload), "rt", encoding="utf-8") as stream:
                    for number, line in enumerate(stream, 1):
                        rows = lines_map.get(number)
                        if rows:
                            yield json.loads(line)['record'], rows, context_values(source_receipt_key=key, source_receipt_line=number)
                            completed += len(rows)
                            remaining -= len(rows)
                            if completed - reported >= 1000:
                                progress.report(stage, completed=completed, total=total, unit='capture_rows')
                                reported = completed
                        if not remaining:
                            break
                if remaining:
                    raise ValueError(f"Capture index references missing receipt lines: {key}")
        progress.report(stage, completed=completed, total=total, unit='capture_rows')
        return
    with TemporaryDirectory(prefix="receipt-positions-") as directory:
        db = sqlite3.connect(Path(directory) / "positions.sqlite")
        try:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
                             'CREATE TABLE positions(receipt TEXT,line INTEGER,position INTEGER,value BLOB); '
                             'CREATE INDEX receipt_lines ON positions(receipt,line,position);')
            tables = (_capture_tables(captures, family=family, suffix=suffix)
                      if isinstance(captures, (pa.Table, pq.ParquetFile)) else captures)
            position = total = 0
            has_inline_record = False
            for table in tables:
                records = []
                for row in table.to_pylist():
                    if not row.get('receipt_key') or type(row.get('receipt_line')) is not int or row['receipt_line'] < 1:
                        raise ValueError("Invalid capture receipt locator")
                    if 'record_json' in row or isinstance(row.get('record'), Mapping):
                        has_inline_record = True
                    records.append((row['receipt_key'], row['receipt_line'], position, pickle.dumps(row)))
                    position += 1
                db.executemany('INSERT INTO positions VALUES (?,?,?,?)', records)
                total += len(records)
            if table_direct or has_inline_record:
                for key, number in db.execute('SELECT DISTINCT receipt, line FROM positions ORDER BY receipt, line'):
                    rows = [pickle.loads(value) for value, in db.execute(
                        'SELECT value FROM positions WHERE receipt=? AND line=? ORDER BY position', (key, number))]
                    if rows:
                        first_row = rows[0]
                        srow = state_by_url.get(first_row.get('context_url') or first_row.get('url'))
                        record = record_from_capture_row(first_row, srow)
                        yield record, rows, context_values(source_receipt_key=key, source_receipt_line=number)
                        completed += len(rows)
                        if completed - reported >= 1000:
                            progress.report(stage, completed=completed, total=total, unit='capture_rows')
                            reported = completed
            else:
                for key, in db.execute('SELECT DISTINCT receipt FROM positions ORDER BY receipt'):
                    payload = read_receipt(key)
                    if payload is None:
                        raise ValueError(f"Missing capture receipt: {key}")
                    remaining, = db.execute('SELECT count(*) FROM positions WHERE receipt=?', (key,)).fetchone()
                    with gzip.open(BytesIO(payload), "rt", encoding="utf-8") as stream:
                        for number, line in enumerate(stream, 1):
                            rows = [pickle.loads(value) for value, in db.execute(
                                'SELECT value FROM positions WHERE receipt=? AND line=? ORDER BY position', (key, number))]
                            if rows:
                                yield json.loads(line)['record'], rows, context_values(source_receipt_key=key, source_receipt_line=number)
                                completed += len(rows)
                                remaining -= len(rows)
                                if completed - reported >= 1000:
                                    progress.report(stage, completed=completed, total=total, unit='capture_rows')
                                    reported = completed
                            if not remaining:
                                break
                    if remaining:
                        raise ValueError(f"Capture index references missing receipt lines: {key}")
        finally:
            db.close()
    progress.report(stage, completed=completed, total=total, unit='capture_rows')


def add_retained_senate_pages(context, captures, read_body):
    """Read independent HTML observations without replacing older saved state."""
    from congress_api.models.content import RawContent
    from congress_api.parsers.senate import parsed
    from congress_api.parsers.senate_page import SITE

    required = {"family", "http_status", "body_key", "context_url", "receipt_key", "receipt_line"}
    if not required <= set(capture_schema(captures).names):
        return
    observations = {} if context.working is None else context.working.mapping('senate_capture_observations')
    observations.clear()
    rows = (row for table in _capture_tables(captures, family='senate/pages')
            for row in table.filter(pc.equal(table['http_status'], 200)).select(sorted(required)).to_pylist())
    for row in rows:
        url, key = row["context_url"], row["body_key"]
        if not url or not key:
            continue
        try:
            host = (urlsplit(url).hostname or "").removeprefix("www.")
        except ValueError:
            continue
        if host not in SITE.values():
            continue
        digest = key.rsplit("/", 1)[-1].removesuffix(".gz")
        if digest in context.by_url.get(url, {}).get("source_page_sha256", set()):
            continue
        identity = url, key, host
        receipts = observations.get(identity, set())
        receipts.add((row['receipt_key'], row['receipt_line']))
        observations[identity] = receipts
    import os
    if 'PYTEST_CURRENT_TEST' not in os.environ and read_body is not None:
        store_obj = getattr(read_body, '_store', None) or getattr(read_body, '__self__', None)
        if hasattr(store_obj, 'prefetch_immutable'):
            store_obj.prefetch_immutable([k for (_, k, _) in observations])
    for (url, key, host), receipts in progress.track(
            observations.items(), 'read_senate_html', unit='pages'):
        raw = read_body(key)
        if raw is None or not re.search(br"<(?:html\b|!doctype\s+html\b)", raw[:2048], re.I):
            continue
        page = parsed(raw.decode("utf-8", "replace"), url)
        page["raw_html"] = RawContent.from_bytes(raw, "text/html").source_dict()
        for receipt, line in sorted(receipts):
            context.add_senate({host: {"pages": {url: page}}}, context_values(
                source_receipt_key=receipt, source_receipt_line=line))


def add_retained_house_documents(context, captures, read_body):
    """Replay publisher XML through the existing House parser, with exact locators."""
    from congress_api.parsers.house_evidence import retained_evidence
    from congress_api.parsers.xml import parse_xml
    from xml.etree.ElementTree import ParseError

    rows = (row for table in _capture_tables(captures)
            for row in table.filter(pc.is_in(table['family'], value_set=pa.array(
                ['house/meeting-xml', 'house/witness-xml']))).to_pylist())
    import os
    if 'PYTEST_CURRENT_TEST' not in os.environ and read_body is not None:
        rows = list(rows)
        store_obj = getattr(read_body, '_store', None) or getattr(read_body, '__self__', None)
        if hasattr(store_obj, 'prefetch_immutable'):
            store_obj.prefetch_immutable([
                r['body_key'] for r in rows
                if r.get('body_key') and r.get('http_status') in (None, 200)
            ])
    seen = set()
    for row in progress.track(rows, 'read_house_xml', unit='capture_rows'):
        key, url = row.get("body_key"), row.get("context_url")
        if not key or (key, url) in seen or row.get("http_status") not in (None, 200):
            continue
        seen.add((key, url))
        body = read_body(key)
        if body is None:
            continue
        try:
            root = parse_xml(body)
            if root.tag not in {"committee-meeting", "witness-list"}:
                continue
            evidence = retained_evidence(root if root.tag == "committee-meeting" else None,
                                         root if root.tag == "witness-list" else None)
        except (ValueError, ParseError):
            continue
        event = root.get("meeting-id", "").removeprefix("HMKP")
        with context.observation(context_values(source_receipt_key=row.get('receipt_key'),
                                                source_receipt_line=row.get('receipt_line'))):
            meeting = context.event_context(event, "house")
        values = {**context_values(source_meeting_id=event, source_chamber="House"),
                  **meeting, **context_values(
            source_page_url=url, source_original_page_url=url, source_page_sha256=sha256(body).hexdigest(),
            source_receipt_key=row.get("receipt_key"), source_receipt_line=row.get("receipt_line"))}
        context.add_house_evidence(evidence, values)


def read_document_sources(root=None, urls=None, *, captures=None, read_receipt=None, read_body=None, context=None):
    """Read retained parents and explicit download-page links, without HTTP."""
    context = context or DocumentSources()
    if captures is None:
        path = root / "indexes/captures.parquet"
        if not path.exists():
            return context
        captures = pq.read_table(path)
    read_receipt = read_receipt or (lambda key: (root / key).read_bytes())
    read_body = read_body or (lambda key: read_retained_body(root, key))
    def records(family, suffix=None):
        stage = 'read_' + (suffix or family).replace('/', '_').replace('.', '_')
        for record, _, receipt in retained_records(captures, read_receipt, stage=stage, family=family, suffix=suffix):
            yield record, receipt

    for record, receipt in records("congress/meetings"):
        context.add_meeting(record, receipt)
    wanted = urls
    for record, receipt in records("senate/pages", "senate.json.gz"):
        context.add_senate(record, receipt, read_body=read_body)
    for record, receipt in records(None, "house-sites.json.gz"):
        context.add_house_sites(record, receipt, read_body=read_body)
    for record, receipt in records(None, "house.json.gz"):
        context.add_house(record, receipt)
    add_retained_house_documents(context, captures, read_body)
    for record, receipt in records("documents", "documents/inventory.jsonl.gz"):
        context.add_inventory(record, receipt)
    add_retained_senate_pages(context, captures, read_body)
    body_references = defaultdict(set) if context.working is None else context.working.mapping('source_body_references')
    body_references.clear()
    if {"body_key", "context_url"} <= set(capture_schema(captures).names):
        for batch in capture_batches(captures, ['receipt_key', 'receipt_line', 'body_key', 'context_url']):
            for row in batch.to_pylist():
                if row['context_url'] in context.by_url and row['body_key']:
                    identity = row['receipt_key'], row['receipt_line']
                    references = body_references.get(identity, set())
                    references.add((row['body_key'], row['context_url']))
                    body_references[identity] = references
    for record, receipt in records(None, "/receipts.jsonl"):
        context.add_redirect(record, receipt)
        context.add_associations(record, receipt)
        if not isinstance(record, dict) or record.get("format") != "html_requires_document_discovery":
            continue
        requested = record.get("url")
        if requested not in context.by_url:
            continue
        ref = (next(iter(receipt["source_receipt_key"])), int(next(iter(receipt["source_receipt_line"]))))
        for key, url in body_references.get(ref, ()):
            if url != requested:
                continue
            body = read_body(key)
            if body is None:
                continue
            from congress_api.parsers.senate_page import source_details
            files, _, _ = source_details(body.decode("utf-8", "replace"), requested, [])
            for linked in files:
                context.add_transfer(requested, linked, {**receipt, **context_values(
                    source_association_basis="retained_html_link", source_associated_url=requested)})
    context.urls = {http_url(url) or url for url in wanted} if wanted is not None else None
    return context
