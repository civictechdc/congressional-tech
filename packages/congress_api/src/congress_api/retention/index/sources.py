"""Source URL extraction, name decoding, and capture row handling."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from email.message import Message
from email.utils import collapse_rfc2231_value
from functools import wraps
import json
from pathlib import Path
import re
from sys import intern
import unicodedata
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from congress_api.parsers.document_links import http_url
from congress_api.parsers.media import youtube_video_id
from congress_api.parsers.source_family import family as source_family
from congress_api.retention import raw_progress as progress
from congress_api.retention.document_evidence import response_failed
from congress_api.retention.index.schemas import (
    DOCUMENT_EXTENSIONS, SOURCE_SCHEMA, compact, context_values, merge_context,
)


def url_filename(value):
    """Decode only a URL path basename; '+' in a path remains a literal plus."""
    try:
        return unquote(urlsplit(value).path.rsplit("/", 1)[-1], errors="strict") or None
    except (ValueError, UnicodeError):
        return None


def url_document_names(url):
    """Read explicit file paths/query parameters without treating endpoints as names."""
    result = []
    if (name := url_filename(url)) and name.rsplit(".", 1)[
        -1
    ].lower() in DOCUMENT_EXTENSIONS:
        result.append((name, "url_path"))
    try:
        for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=True):
            if key.lower() in {"filename", "file", "name", "document", "attachment"}:
                # parse_qsl already decodes the parameter: do not decode twice.
                name = value.replace("\\", "/").rsplit("/", 1)[-1]
                if name.rsplit(".", 1)[-1].lower() in DOCUMENT_EXTENSIONS:
                    result.append((name, "url_query"))
    except ValueError:
        pass
    return list(dict.fromkeys(result))


def inventory_names(value):
    """Visit saved metadata links, including inventories without retained bodies."""
    if isinstance(value, dict):
        url = next(
            (
                value.get(k)
                for k in ("url", "requested_url", "final_url", "candidate_url")
                if isinstance(value.get(k), str)
            ),
            None,
        )
        header = disposition_filename(
            value.get("response_headers", value.get("headers"))
        )
        if header:
            yield header, "content_disposition", url
        for key, child in value.items():
            if isinstance(child, str) and (
                key.lower().endswith("url") or key.lower() == "href"
            ):
                for name, basis in url_document_names(child):
                    yield name, basis, child
            elif isinstance(child, (dict, list)):
                yield from inventory_names(child)
    elif isinstance(value, list):
        for child in value:
            yield from inventory_names(child)


def disposition_filename(headers):
    if not isinstance(headers, dict):
        return None
    value = next(
        (v for k, v in headers.items() if k.lower() == "content-disposition"), None
    )
    if not isinstance(value, str):
        return None
    msg = Message()
    msg["Content-Disposition"] = value
    # Prefer filename* when both a fallback and a Unicode name exist.
    params = msg.get_params(header="content-disposition", unquote=True) or []
    values = [v for k, v in params[1:] if k.lower() == "filename"]
    value = next(
        (v for v in values if isinstance(v, tuple)), values[0] if values else None
    )
    return collapse_rfc2231_value(value) if isinstance(value, tuple) else value


def nearest_record(record, pointer):
    """Find the body-owning record, without borrowing a sibling's headers."""
    parent = record if isinstance(record, dict) else {}
    current = record
    for part in json.loads(pointer or "[]"):
        current = current[part]
        if (
            isinstance(current, dict)
            and not {"sha256", "media_type", "body_encoding"} <= current.keys()
        ):
            parent = current
    return parent


def source_names(row, record):
    """Keep header, URL, and local-only spellings distinguishable."""
    url = row["context_url"]
    owner = nearest_record(record, row["pointer_json"])
    if json.loads(row['pointer_json'] or '[]')[:1] == ['archive_members']:
        path = owner['original_name']
        return [(Path(path).name, 'archive_member', None, path)]
    result = []
    headers = owner.get("response_headers", owner.get("headers"))
    if headers is None and isinstance(owner.get("httpResponseHeaders"), list):
        headers = {h["name"]: h["value"] for h in owner["httpResponseHeaders"]}
    header_name = disposition_filename(headers)
    if header_name:
        result.append((header_name, "content_disposition", url, header_name))
    for candidate in dict.fromkeys([url, owner.get("final_url") or owner.get("url")]):
        if candidate:
            name = url_filename(candidate)
            result.append((name, "url_path" if name else None, candidate, candidate))
            for query_name, basis in url_document_names(candidate):
                result.append((query_name, basis, candidate, candidate))
    if not any(item[0] for item in result) and (path := row["original_path"]):
        name = Path(path).name.removesuffix(".gz")
        if not re.fullmatch(r"[a-fA-F0-9]{32,64}(?:\.[\w.-]+)?", name):
            result = [(name, "retained_path", item[2], path) for item in result] or [
                (name, "retained_path", None, path)]
    return result


def response_metadata(row, record):
    """Keep actual response metadata with the body-owning record, not URL guesses."""
    owner = nearest_record(record, row["pointer_json"])
    media = {
        owner[k]
        for k in ("media_type", "content_type")
        if isinstance(owner.get(k), str) and owner[k]
    }
    for key in ("response_headers", "headers"):
        headers = owner.get(key)
        if isinstance(headers, dict):
            media.update(
                v
                for k, v in headers.items()
                if k.lower() == "content-type" and isinstance(v, str) and v
            )
    if not media and row.get("media_type"):
        media.add(row["media_type"])
    status = next(
        (
            owner[k]
            for k in ("http_status", "status_code", "status")
            if isinstance(owner.get(k), int) and not isinstance(owner.get(k), bool)
        ),
        row.get("http_status"),
    )
    result = {
        "media_type": media,
        "http_status": {str(status)} if status is not None else set(),
    }
    for source, target in (("usable", "response_usable"), ("body_complete", "response_body_complete")):
        value = owner.get(source)
        if source == "body_complete" and value is None:
            value = owner.get("complete")
        if type(value) is bool:
            result[target] = {str(value).lower()}
    for source, target in (("format", "response_format"), ("result", "response_result")):
        if isinstance(value := owner.get(source), str) and value:
            result[target] = {value}
    return result


def add_name(names, body, filename, url, basis, source=None, metadata=None):
    entry = names.setdefault(
        (body, filename, url), {field: set() for field in SOURCE_SCHEMA.names[3:]}
    )
    if basis:
        entry["filename_origins"].add(basis)
    if basis in {"retained_path", "archive_member"}:
        entry["source_paths"].add(source)
    for field, values in (metadata or {}).items():
        entry[field].update(values)
    names[(body, filename, url)] = entry


class SourceFilters(Mapping):
    """Read flat filters from paired observations instead of retaining both."""
    def __init__(self, occurrences, extras):
        self.occurrences, self.extras = occurrences, extras

    def __iter__(self):
        return iter(self.occurrences)

    def __len__(self):
        return len(self.occurrences)

    def __contains__(self, url):
        return url in self.occurrences

    def __getitem__(self, url):
        if url not in self.occurrences:
            raise KeyError(url)
        values = {}
        merge_context(values, self.extras.get(url, {}))
        for occurrence in self.occurrences[url].values():
            merge_context(values, occurrence)
        return values


def _observed_parent(method):
    @wraps(method)
    def observed(self, record, receipt=None, **options):
        with self.observation(receipt):
            return method(self, record, receipt, **options)
    return observed


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


def capture_record_type(family, pointer_json):
    """Recognize a retained source page from its collector's explicit field."""
    try:
        pointer = json.loads(pointer_json or "[]")
    except (TypeError, ValueError):
        return None
    if (family == "house/meeting-xml" and isinstance(pointer, list)
            and pointer[-2:] == ["evidence", "html"]):
        return "committee-meeting-page"
    return None


PAGE_RECORD_TYPES = {
    'hearing': 'committee-hearing-page',
    'field hearing': 'committee-hearing-page',
    'meeting': 'committee-meeting-page',
    'business meeting': 'committee-meeting-page',
    'markup': 'committee-meeting-page',
}


def _page_key(value):
    url = http_url(value)
    if not url:
        return None
    parts = urlsplit(url)
    path = parts.path[:-1] if len(parts.path) > 1 and parts.path.endswith('/') else parts.path
    return urlunsplit(parts._replace(path=path, fragment=''))


def recognize_publisher_page(row):
    """A saved HTML response is a source page when that page was recorded for its URL."""
    if row.get('source_record_type') or row.get('record_role') not in (None, ['document']):
        return
    if row.get('document_kind') or response_failed(row):
        return
    signals = [*(row.get('format') or []), *(row.get('media_type') or []), *(row.get('body_format') or [])]
    kinds = {str(value).split(';', 1)[0].strip().casefold() for value in signals}
    if kinds and not ({'html', 'text/html'} & kinds):
        return
    file_url = _page_key(row.get('source_url'))
    if not file_url or file_url not in {_page_key(value) for value in row.get('source_page_url') or []}:
        return
    titles = [' '.join(value.split()).casefold() for value in row.get('source_page_title') or [] if isinstance(value, str)]
    types = [' '.join(value.split()).casefold() for value in row.get('source_meeting_type') or [] if isinstance(value, str)]
    kind = next((PAGE_RECORD_TYPES[value] for value in titles if value in PAGE_RECORD_TYPES), None)
    if kind is None and 'hearing' in types:
        kind = 'committee-hearing-page'
    if kind is None and {'meeting', 'markup'} & set(types):
        kind = 'committee-meeting-page'
    if kind is None:
        return
    row['source_record_type'] = [kind]
    row['record_role'] = ['source-record']


def apply_capture_record_role(row):
    """Keep receipt/pointer pairs together when recognizing embedded source HTML."""
    if row.get('source_record_type') == ['download-state']:
        row['record_role'] = ['capture-state']
        return
    if youtube_video_id(row.get('source_url')):
        row['source_record_type'] = ['youtube-video']
        if row.get('record_role') != ['error-response']:
            row['record_role'] = ['source-record']
        return
    if row.get("source_record_type"):
        return
    for occurrence in row.get("source_occurrences") or []:
        if occurrence is None:
            continue
        if occurrence.get("source_occurrence_scope") != ["capture"]:
            continue
        for receipt in occurrence.get("source_receipt_key") or []:
            if not receipt.startswith("receipts/"):
                continue
            family = "/".join(receipt.split("/")[1:3])
            for pointer in occurrence.get("source_capture_pointer") or []:
                if kind := capture_record_type(family, pointer):
                    row["source_record_type"] = [kind]
                    row["record_role"] = ["source-record"]
                    return
    recognize_publisher_page(row)
