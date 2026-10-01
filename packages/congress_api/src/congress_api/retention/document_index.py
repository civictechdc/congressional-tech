"""Write useful filename metadata as flat Parquet columns, without opening bodies.

Filename rules belong to house_naming.Engine. This command locates saved names,
keeps their meanings and references, and omits parser mechanics and diagnostics.

source_* columns retain the parent meeting/page's assertions about a linked URL.
source_committee_code is the meeting's Congress.gov systemCode; the separate
source_publisher_committee_code identifies the Senate site's owner from the
collector's existing site map. Missing context stays null. A shared document
retains all observed parents; flat lists do not imply pairwise relationships.
--source-metadata-only refreshes these fields without rerunning filename parsing.
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from uuid import uuid4
from email.message import Message
from email.utils import collapse_rfc2231_value
import gzip
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from house_naming import Engine, __version__
from house_naming.errors import NamingError
from house_naming.extraction import QUERY
from house_naming.values import filename_metadata as flatten  # noqa: F401 - public flat-value helper


FAMILIES = (
    "documents",
    "govinfo/transcript-html",
    "house/meeting-xml",
    "house/witness-xml",
)
DOCUMENT_EXTENSIONS = frozenset(
    {
        "pdf",
        "xml",
        "html",
        "htm",
        "txt",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "rtf",
        "zip",
        "csv",
        "tsv",
        "ppt",
        "pptx",
        "xsd",
    }
)
STRINGS = pa.list_(pa.string())
SOURCE_SCHEMA = pa.schema(
    [
        ("body_key", pa.string()),
        ("filename", pa.string()),
        ("source_url", pa.string()),
        ("filename_origins", STRINGS),
        ("source_paths", STRINGS),
        ("media_type", STRINGS),
        ("http_status", STRINGS),
    ]
)
ENGINE = None

MEDIA_FORMATS = {
    "application/pdf": "pdf",
    "application/json": "json",
    "application/xml": "xml",
    "text/xml": "xml",
    "text/html": "html",
    "text/plain": "txt",
    "text/csv": "csv",
    "text/tab-separated-values": "tsv",
    "application/zip": "zip",
    "application/x-zip-compressed": "zip",
    "application/msword": "doc",
    "application/rtf": "rtf",
    "text/rtf": "rtf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/octet-stream": "binary",
}


def file_formats(media_types, extensions):
    # A saved response can be HTML even when its URL ends in .pdf. Keep the
    # literal extension in the inspector; use response types for this display.
    if media_types:
        types = {
            value.split(";", 1)[0].strip().lower()
            for value in media_types
            if value.strip()
        }
        return sorted({MEDIA_FORMATS.get(value, value) for value in types})
    return (
        sorted(
            {
                "html" if value.lower() == "htm" else value.lower()
                for value in extensions or []
            }
        )
        or None
    )


def display_filename(filename):
    """Use the filename reader's query boundary; retain the literal in row data."""
    match = QUERY.search(filename or "")
    return filename[: match.start()] if match else filename


def entry_key(filename, url, row_id):
    """Group download variants of one endpoint, never equal basenames elsewhere."""
    if not filename or not url:
        return ("row", row_id)
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return ("row", row_id)

        def download_switch(pair):
            return pair[0].lower() == "download" and pair[1].lower() in (
                "",
                "1",
                "true",
            )

        path = parts.path
        if match := QUERY.search(path):
            extra = parse_qsl(path[match.start() + 1 :], keep_blank_values=True)
            # Some Senate publishers literally put &download=1 in the path.
            if extra and all(download_switch(pair) for pair in extra):
                path = path[: match.start()]
        query = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not download_switch((k, v))
        ]
        endpoint = urlunsplit(
            parts._replace(path=path, query=urlencode(query), fragment="")
        )
        return (display_filename(filename), endpoint)
    except ValueError:
        return ("row", row_id)


def source_priority(row):
    successful = (
        row.get("body_key") is not None
        and any(str(status).startswith("2") for status in row.get("http_status") or [])
        and (not row.get("capture_outcome") or set(row["capture_outcome"]) == {"saved"})
    )
    document = bool(set(row.get("format") or []) - {"html", "binary"})
    named_format = bool(
        {extension.lower() for extension in row.get("extension") or []}
        & set(row.get("format") or [])
    )
    return (
        successful and document,
        successful,
        row.get("body_key") is not None,
        named_format,
    )


def source_groups(table):
    """Join endpoint variants and identical successful document bodies.

    HTML/error bodies are often shared by unrelated URLs, so they cannot join
    entries by hash. Endpoint grouping still connects a wrapper to its download.
    """
    parents = list(range(len(table)))

    def root(row):
        while parents[row] != row:
            parents[row] = parents[parents[row]]
            row = parents[row]
        return row

    endpoints, bodies = {}, {}
    columns = [
        table[name].to_pylist()
        for name in ("filename", "source_url", "body_key", "media_type", "http_status")
    ]
    columns.append(
        table["capture_outcome"].to_pylist()
        if "capture_outcome" in table.column_names
        else [None] * len(table)
    )
    for row_id, (filename, url, body, media, statuses, outcomes) in enumerate(
        zip(*columns)
    ):
        endpoint = entry_key(filename, url, row_id)
        parents[root(row_id)] = root(endpoints.setdefault(endpoint, row_id))
        if document_body(body, media, statuses, outcomes):
            parents[root(row_id)] = root(bodies.setdefault(body, row_id))
    groups, members, entry_ids = {}, [], []
    for row_id in range(len(table)):
        key = root(row_id)
        if key not in groups:
            groups[key] = len(members)
            members.append([])
        entry = groups[key]
        entry_ids.append(entry)
        members[entry].append(row_id)
    return entry_ids, members


def document_body(body, media, statuses, outcomes=None):
    formats = set(file_formats(media, None) or [])
    document_formats = set(MEDIA_FORMATS.values()) - {"html", "binary"}
    return (
        body
        if (
            body
            and (not outcomes or set(outcomes) == {"saved"})
            and formats
            and formats <= document_formats
            and any(str(status).startswith("2") for status in statuses or [])
        )
        else None
    )


def prepare_document_indexes(rows, schema):
    """Keep exact source rows and create one canonical row per document group."""
    for row in rows:
        row["source_id"] = sha256(
            compact(
                [row.get(k) for k in ("body_key", "filename", "source_url")]
            ).encode()
        ).hexdigest()
        row["format"] = file_formats(row.get("media_type"), row.get("extension"))
    grouping_schema = pa.schema([*SOURCE_SCHEMA, ("capture_outcome", STRINGS)])
    _, groups = source_groups(pa.Table.from_pylist(rows, schema=grouping_schema))
    documents = []
    for members in groups:
        sources = [rows[i] for i in members]
        bodies = sorted(
            {
                body
                for row in sources
                if (
                    body := document_body(
                        row.get("body_key"),
                        row.get("media_type"),
                        row.get("http_status"),
                        row.get("capture_outcome"),
                    )
                )
            }
        )
        # Exact retained document bytes anchor the ID. Adding URL or filename
        # aliases for those bytes does not change it; unknowns use source IDs.
        identity = (
            ["bodies", bodies]
            if bodies
            else ["sources", sorted(row["source_id"] for row in sources)]
        )
        document_id = sha256(compact(identity).encode()).hexdigest()
        # Stable tie-breaking makes the result independent of receipt order.
        preferred = max(
            sources,
            key=lambda row: (
                source_priority(row),
                row.get("filename") or "",
                row.get("source_url") or "",
                row["source_id"],
            ),
        )
        document = {
            key: preferred.get(key)
            for key in ("source_id", "body_key", "filename", "source_url")
        }
        document.update(
            document_id=document_id,
            filename=display_filename(preferred.get("filename")),
        )
        values = defaultdict(set)
        for row in sources:
            row["document_id"] = document_id
            for key, value in row.items():
                if isinstance(value, list):
                    values[key].update(value)
        document.update({key: sorted(value) for key, value in values.items() if value})
        for singular, plural in [
            ("filename", "filenames"),
            ("source_url", "source_urls"),
            ("body_key", "body_keys"),
        ]:
            document[plural] = (
                sorted({row[singular] for row in sources if row.get(singular)}) or None
            )
        documents.append(document)
    documents.sort(
        key=lambda row: ((row["filename"] or "").casefold(), row["document_id"])
    )
    catalog_id = uuid4().hex
    original = [
        field
        for field in schema
        if field.name not in {"document_id", "source_id", "format"}
    ]
    fields = [
        *original,
        pa.field("source_id", pa.string()),
        pa.field("document_id", pa.string()),
        pa.field("format", STRINGS),
    ]
    metadata = {
        **(schema.metadata or {}),
        b"format_version": b"6",
        b"catalog_id": catalog_id.encode(),
    }
    source_schema = pa.schema(fields, metadata=metadata)
    document_schema = pa.schema(
        [
            *fields,
            *[(name, STRINGS) for name in ("filenames", "source_urls", "body_keys")],
        ],
        metadata={**metadata, b"format_version": b"1"},
    )
    return rows, source_schema, documents, document_schema


def write_document_indexes(destination, rows, schema):
    rows, source_schema, documents, document_schema = prepare_document_indexes(
        rows, schema
    )
    document_path = destination.with_name("documents.parquet")
    outputs = [
        (destination, rows, source_schema),
        (document_path, documents, document_schema),
    ]
    temporary = [path.with_suffix(".parquet.tmp") for path, _, _ in outputs]
    try:
        for tmp, (_, records, record_schema) in zip(temporary, outputs):
            with pq.ParquetWriter(tmp, record_schema, compression="zstd") as writer:
                for start in range(0, len(records), 32768):
                    writer.write_table(
                        pa.Table.from_pylist(
                            records[start : start + 32768], schema=record_schema
                        )
                    )
        source_ids = pq.read_table(temporary[0], columns=["source_id", "document_id"])
        document_ids = pq.read_table(temporary[1], columns=["source_id", "document_id"])
        if (
            len(source_ids) != len(rows)
            or len(document_ids) != len(documents)
            or len(set(source_ids["source_id"].to_pylist())) != len(rows)
            or len(set(document_ids["document_id"].to_pylist())) != len(documents)
            or set(source_ids["document_id"].to_pylist())
            != set(document_ids["document_id"].to_pylist())
            or not set(
                zip(
                    document_ids["source_id"].to_pylist(),
                    document_ids["document_id"].to_pylist(),
                )
            )
            <= set(
                zip(
                    source_ids["source_id"].to_pylist(),
                    source_ids["document_id"].to_pylist(),
                )
            )
        ):
            raise ValueError("Document/source index references do not match")
        for tmp, (path, _, _) in zip(temporary, outputs):
            tmp.replace(path)
    finally:
        for tmp in temporary:
            tmp.unlink(missing_ok=True)
    return dict(
        document_rows=len(documents),
        columns=len(source_schema),
        documents_output=str(document_path),
        documents_bytes=document_path.stat().st_size,
    )


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


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
        # RawContent is nested beneath its response. Its bytes/hash are not a
        # second response owner, and must not hide response headers or redirects.
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
    result = []
    headers = owner.get("response_headers", owner.get("headers"))
    if headers is None and isinstance(owner.get("httpResponseHeaders"), list):
        headers = {h["name"]: h["value"] for h in owner["httpResponseHeaders"]}
    header_name = disposition_filename(headers)
    if header_name:
        result.append((header_name, "content_disposition", url, header_name))
    for candidate in dict.fromkeys([url, owner.get("final_url") or owner.get("url")]):
        if candidate and (name := url_filename(candidate)):
            result.append((name, "url_path", candidate, candidate))
            for query_name, basis in url_document_names(candidate):
                result.append((query_name, basis, candidate, candidate))
    if not result and (path := row["original_path"]):
        name = Path(path).name.removesuffix(".gz")
        if not re.fullmatch(r"[a-fA-F0-9]{32,64}(?:\.[\w.-]+)?", name):
            result.append((name, "retained_path", None, path))
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
    return {
        "media_type": media,
        "http_status": {str(status)} if status is not None else set(),
    }


def add_name(names, body, filename, url, basis, source=None, metadata=None):
    entry = names.setdefault(
        (body, filename, url), {field: set() for field in SOURCE_SCHEMA.names[3:]}
    )
    if basis:
        entry["filename_origins"].add(basis)
    if basis == "retained_path":
        entry["source_paths"].add(source)
    for field, values in (metadata or {}).items():
        entry[field].update(values)


# These describe where a document URL was listed. They never overwrite fields
# read from the filename, and multiple parent meetings remain multiple values.
SOURCE_CONTEXT_FIELDS = frozenset(
    {
        "source_congress",
        "source_chamber",
        "source_meeting_id",
        "source_meeting_key",
        "source_meeting_title",
        "source_meeting_date",
        "source_meeting_type",
        "source_committee_code",
        "source_committee_name",
        "source_committee_url",
        "source_page_url",
        "source_page_title",
        "source_page_date",
        "source_page_type",
        "source_publisher_committee_code",
        "source_document_group",
        "source_document_type",
        "source_document_label",
        "source_document_format",
        "source_document_added_at",
        "source_document_published_at",
        "source_package_id",
    }
)


def context_values(**values):
    return {
        key: {str(value)}
        for key, value in values.items()
        if isinstance(value, (str, int))
        and not isinstance(value, bool)
        and str(value).strip()
    }


def merge_context(target, values):
    for key, items in values.items():
        if items:
            target.setdefault(key, set()).update(items)


class DocumentSources:
    """Interpret supplied parent records; join by exact URL or scoped event ID.

    All fields describe source assertions, not the document's contents. Publisher
    committee codes from the existing collector map are separate from a meeting's
    committee/subcommittee codes. No filename or shared-host matching is used.
    """

    def __init__(self, urls=None):
        self.urls = urls
        self.by_url = {}
        self.meetings = {}
        self.events = defaultdict(set)

    def add_url(self, url, values):
        if isinstance(url, str) and url and (self.urls is None or url in self.urls):
            merge_context(self.by_url.setdefault(url, {}), values)

    def for_url(self, url):
        return {
            key: sorted(values)
            for key, values in self.by_url.get(url, {}).items()
            if values
        }

    def add_link(self, link):
        """Read a native seed or discovered link retained by recurring capture."""
        parent = link.get("context") or {}
        self.add_meeting(parent)
        native = link.get("native") or {}
        if isinstance(native, list):
            native = dict(zip(("documentType", "name", "url"), native))
        group = next(
            (
                p
                for p in link.get("pointer", [])
                if p in ("meetingDocuments", "witnessDocuments", "hearingTranscript")
            ),
            None,
        )
        values = context_values(
            source_congress=parent.get("congress"),
            source_chamber=parent.get("chamber"),
            source_meeting_id=parent.get("eventId"),
            source_meeting_title=parent.get("title"),
            source_meeting_date=parent.get("date"),
            source_meeting_type=parent.get("type"),
            source_page_url=link.get("parent_url"),
            source_document_group=group,
            source_document_type=native.get("documentType"),
            source_document_label=native.get("name")
            or native.get("description")
            or link.get("text"),
            source_document_format=native.get("format"),
        )
        merge_context(
            values,
            self.event_context(
                parent.get("eventId"), parent.get("chamber"), parent.get("congress")
            ),
        )
        # A linked file inherits the known meeting/page context, but not a
        # different document's label or type simply because that page linked it.
        merge_context(
            values,
            {
                k: v
                for k, v in self.by_url.get(link.get("parent_url"), {}).items()
                if not k.startswith("source_document_")
            },
        )
        for committee in parent.get("committees") or []:
            merge_context(
                values,
                context_values(
                    source_committee_code=committee.get("systemCode"),
                    source_committee_name=committee.get("name"),
                    source_committee_url=committee.get("url"),
                ),
            )
        self.add_url(link.get("url"), values)

    def event_context(self, event, chamber=None, congress=None):
        keys = self.events.get(str(event), set())
        keys = [
            k
            for k in keys
            if (not chamber or k[1] == str(chamber).lower())
            and (congress is None or k[0] == str(congress))
        ]
        # An unscoped identifier cannot choose between chambers or Congresses.
        return self.meetings[keys[0]] if len(keys) == 1 else {}

    def add_meeting(self, record):
        if not isinstance(record, dict):
            return
        record = record.get("committeeMeeting", record)
        if not isinstance(record, dict) or not all(
            record.get(k) for k in ("eventId", "chamber", "congress")
        ):
            return
        key = (
            str(record["congress"]),
            str(record["chamber"]).lower(),
            str(record["eventId"]),
        )
        values = context_values(
            source_congress=record["congress"],
            source_chamber=record["chamber"],
            source_meeting_id=record["eventId"],
            source_meeting_key="/".join(key),
            source_meeting_title=record.get("title"),
            source_meeting_date=record.get("date"),
            source_meeting_type=record.get("type"),
            source_page_url=record.get("_url"),
        )
        for committee in record.get("committees") or []:
            if isinstance(committee, dict):
                merge_context(
                    values,
                    context_values(
                        source_committee_code=committee.get("systemCode"),
                        source_committee_name=committee.get("name"),
                        source_committee_url=committee.get("url"),
                    ),
                )
        self.events[key[2]].add(key)
        merge_context(self.meetings.setdefault(key, {}), values)
        self.add_url(record.get("_url"), values)
        for group in ("meetingDocuments", "witnessDocuments", "hearingTranscript"):
            for document in record.get(group) or []:
                if isinstance(document, dict):
                    context = {name: set(items) for name, items in values.items()}
                    merge_context(
                        context,
                        context_values(
                            source_document_group=group,
                            source_document_type=document.get("documentType"),
                            source_document_label=document.get("name")
                            or document.get("description"),
                            source_document_format=document.get("format"),
                        ),
                    )
                    self.add_url(document.get("url"), context)

    def add_senate(self, state):
        from congress_api.parsers.senate_page import SITE

        if not isinstance(state, dict):
            return
        publishers = {host: code for code, host in SITE.items()}
        for host, site in state.items():
            if not isinstance(site, dict):
                continue
            for url, page in site.get("pages", {}).items():
                if not isinstance(page, dict):
                    continue
                event = page.get("event") or {}
                context = context_values(
                    source_page_url=url,
                    source_page_title=page.get("title"),
                    source_page_date=event.get("date"),
                    source_page_type=event.get("type"),
                    source_publisher_committee_code=publishers.get(host),
                )
                # Preserve existing confirmed matches, never candidate_events.
                workflow = (site.get("workflow") or {}).get(url, page)
                for event_id in workflow.get("events") or []:
                    merge_context(context, self.event_context(event_id))
                self.add_url(url, context)
                for document in page.get("documents") or []:
                    if not isinstance(document, (list, tuple)) or len(document) != 3:
                        continue
                    kind, label, document_url = document
                    values = {name: set(items) for name, items in context.items()}
                    merge_context(
                        values,
                        context_values(
                            source_document_group="page.documents",
                            source_document_type=kind,
                            source_document_label=label,
                        ),
                    )
                    self.add_url(document_url, values)

    def add_inventory(self, record):
        if not isinstance(record, dict) or not isinstance(
            record.get("observations"), list
        ):
            return
        url = record.get("url")
        if not url or self.urls is not None and url not in self.urls:
            return
        for observation in record["observations"]:
            if not isinstance(observation, dict):
                continue
            context = context_values(
                source_congress=observation.get("congress"),
                source_chamber=observation.get("chamber"),
                source_meeting_id=observation.get("event_id"),
                source_page_url=observation.get("page_url"),
                source_package_id=observation.get("package_id"),
                source_document_label=observation.get("description")
                or observation.get("label"),
                source_document_group=observation.get("group"),
                source_document_type=observation.get("kind"),
            )
            events = observation.get("events") or []
            if observation.get("event_id") is not None:
                events = [*events, observation["event_id"]]
            for event in events:
                merge_context(
                    context,
                    self.event_context(
                        event, observation.get("chamber"), observation.get("congress")
                    ),
                )
            page = observation.get("page_url")
            merge_context(context, self.by_url.get(page, {}))
            native = observation.get("native") or {}
            group = observation.get("group_attributes") or {}
            file = observation.get("native_file") or {}
            selector = observation.get("selector", "").split("/")
            merge_context(
                context,
                context_values(
                    source_document_group=selector[1] if len(selector) > 1 else None,
                    source_document_type=native.get("documentType")
                    or group.get("type"),
                    source_document_label=native.get("name")
                    or native.get("description"),
                    source_document_format=native.get("format") or file.get("doc-type"),
                    source_document_added_at=file.get("add-date"),
                    source_document_published_at=file.get("publish-date"),
                ),
            )
            self.add_url(url, context)


def read_document_sources(root, urls=None):
    """Read retained parent records only, without document bodies or HTTP."""
    context = DocumentSources(urls)
    path = root / "indexes/captures.parquet"
    if not path.exists():
        return context
    archive = pq.ParquetFile(path)
    columns = [
        name
        for name in ("family", "source_file", "receipt_key", "receipt_line")
        if name in archive.schema_arrow.names
    ]
    captures = archive.read(columns=columns)

    def records(family, suffix=None):
        selected = captures.filter(pc.equal(captures["family"], family))
        if suffix:
            if "source_file" not in selected.column_names:
                return
            selected = selected.filter(pc.ends_with(selected["source_file"], suffix))
        references = defaultdict(set)
        for row in selected.to_pylist():
            references[row["receipt_key"]].add(row["receipt_line"])
        for receipt, lines in sorted(references.items()):
            with gzip.open(root / receipt, "rt", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, 1):
                    if line_number in lines:
                        lines.remove(line_number)
                        yield json.loads(line)["record"]
                    if not lines:
                        break
            if lines:
                raise ValueError(
                    f"Context index references missing receipt lines: {receipt}"
                )

    for record in records("congress/meetings"):
        context.add_meeting(record)
    # Parent pages also supply context for inventory links. Retain page entries
    # even when the caller only needs linked document URLs.
    wanted = context.urls
    context.urls = None
    for record in records("senate/pages", "senate.json.gz"):
        context.add_senate(record)
    context.urls = wanted
    for record in records("documents", "documents/inventory.jsonl.gz"):
        context.add_inventory(record)
    return context


def refresh_source_metadata(root, context=None):
    """Enrich existing rows, then regroup; filename parsing and identities stay unchanged."""
    path = root / "indexes/document-filenames.parquet"
    source = pq.ParquetFile(path)
    if context is None:
        urls = {
            url
            for url in source.read(columns=["source_url"])["source_url"].to_pylist()
            if url
        }
        context = read_document_sources(root, urls)
    rows, columns = [], set()
    for batch in source.iter_batches(batch_size=4096):
        for row in batch.to_pylist():
            row = {
                key: value
                for key, value in row.items()
                if value is not None and key not in SOURCE_CONTEXT_FIELDS
            }
            added = context.for_url(row.get("source_url"))
            columns.update(added)
            rows.append({**row, **added})
    schema = pa.schema(
        [
            *[f for f in source.schema_arrow if f.name not in SOURCE_CONTEXT_FIELDS],
            *[(name, STRINGS) for name in sorted(columns)],
        ],
        metadata=source.schema_arrow.metadata,
    )
    return dict(
        rows=len(rows),
        source_context_rows=sum(
            bool(
                r.get("source_page_url")
                or r.get("source_meeting_id")
                or r.get("source_package_id")
            )
            for r in rows
        ),
        **write_document_indexes(path, rows, schema),
    )


def collect_names(root, inventory_dir, families=FAMILIES):
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
    table = table.filter(pc.is_in(table["family"], value_set=pa.array(families)))
    by_receipt = defaultdict(lambda: defaultdict(list))
    bodies, names = set(), {}
    for row in table.to_pylist():
        by_receipt[row["receipt_key"]][row["receipt_line"]].append(row)
        if row["body_key"]:
            bodies.add(row["body_key"])
    for receipt_key, lines in sorted(by_receipt.items()):
        with gzip.open(root / receipt_key, "rt", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                rows = lines.pop(line_number, None)
                if rows:
                    receipt = json.loads(line)
                    for row in rows:
                        if row["body_key"]:
                            metadata = response_metadata(row, receipt["record"])
                            located = source_names(row, receipt["record"]) or [
                                (None, None, None, None)
                            ]
                            for filename, basis, url, source in located:
                                add_name(
                                    names,
                                    row["body_key"],
                                    filename,
                                    url,
                                    basis,
                                    source,
                                    metadata,
                                )
                        elif row["context_url"]:
                            for filename, basis in url_document_names(
                                row["context_url"]
                            ):
                                add_name(
                                    names, None, filename, row["context_url"], basis
                                )
                    if any(row["body_key"] is None for row in rows):
                        for filename, basis, url in inventory_names(receipt["record"]):
                            add_name(names, None, filename, url, basis)
                if not lines:
                    break
        if lines:
            raise ValueError(f"Index references missing receipt lines: {receipt_key}")

    # The full filename corpus includes URL-query and response-header names,
    # even when their corresponding files have never been downloaded.
    catalog = {}
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
    by_url = defaultdict(set)
    for _, filename, url in names:
        if url and filename:
            by_url[url].add(filename)
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
    captured_pairs = defaultdict(set)
    for body, filename, url in names:
        if body and url:
            captured_pairs[(filename, url)].add(body)
    for key in list(names):
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


def extract(item):
    global ENGINE
    if ENGINE is None:
        ENGINE = Engine()
    filename, source_url = item
    if filename is None:
        return {}
    # URL path segments from source API records are identifiers, not fetched
    # document filenames. Keep their source role without asking a lexical date
    # parser to interpret the digits. Original rows and URLs remain unchanged.
    if filename.isascii() and filename.isdigit() and source_url:
        try:
            url = urlsplit(source_url)
            path = url.path.strip("/").split("/")
            if (
                url.scheme in {"http", "https"}
                and url.hostname == "api.congress.gov"
                and len(path) == 5
                and path[0] == "v3"
                and path[1] in {"hearing", "committee-meeting", "bill"}
                and path[-1] == filename
            ):
                return {
                    "source_record_identifier": [filename],
                    "source_record_type": [path[1]],
                }
        except ValueError:
            pass  # Retain the ordinary invalid-URL fallback below.
    try:
        try:
            result = ENGINE.extract(filename, source_url=source_url)
        except NamingError as error:
            if error.code != "invalid-source-url":
                raise
            # A malformed saved URL need not hide a readable basename. No
            # publisher-specific rule is enabled without accepted URL context.
            result = ENGINE.extract(filename)
    except NamingError:
        return {}  # Keep the file/name row even when no metadata was extracted.
    return result["metadata"]


def parser_fingerprint():
    """Invalidate cached meanings when either the rules or implementation change."""
    import house_naming
    import inspect

    root = Path(house_naming.__file__).parent
    digest = sha256()
    digest.update(inspect.getsource(extract).encode())
    for path in sorted(p for p in root.rglob("*") if p.suffix in {".py", ".json"}):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def write_filename_metadata(
    root, source_rows, *, workers=4, previous=None, metadata=None
):
    """Interpret supplied source rows; acquisition and storage discovery stay outside."""
    started = time.monotonic()
    inputs = defaultdict(list)
    bodies, names = set(), set()
    for source in source_rows:
        inputs[(source["filename"], source["source_url"])].append(source)
        if source["body_key"]:
            bodies.add(source["body_key"])
        if source["filename"]:
            names.add(source["filename"])
    fingerprint = parser_fingerprint()
    cached = {}
    source_fields = (
        set(SOURCE_SCHEMA.names) | SOURCE_CONTEXT_FIELDS | {"capture_outcome"}
    )
    if (
        previous is not None
        and (previous.schema.metadata or {}).get(b"house_naming_fingerprint")
        == fingerprint.encode()
    ):
        fields = (
            set(previous.column_names)
            - source_fields
            - {"source_id", "document_id", "format"}
        )
        for batch in previous.to_batches(max_chunksize=4096):
            for row in batch.to_pylist():
                cached[(row["filename"], row["source_url"])] = {
                    k: row[k] for k in fields if row[k] is not None
                }
    pending = [key for key in inputs if key not in cached]
    # A single-worker path is useful for callers already running a worker and
    # keeps small rebuilds independent of process spawning.
    if workers == 1:
        cached.update(zip(pending, map(extract, pending)))
    elif pending:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for i, (key, parsed) in enumerate(
                zip(pending, pool.map(extract, pending, chunksize=128)), 1
            ):
                cached[key] = parsed
                if i % 10000 == 0:
                    print(
                        compact(
                            {
                                "stage": "extracting",
                                "inputs_done": i,
                                "inputs_total": len(pending),
                            }
                        ),
                        flush=True,
                    )
    rows, columns = (
        [],
        {
            key
            for group in inputs.values()
            for row in group
            for key in row
            if key in SOURCE_CONTEXT_FIELDS | {"capture_outcome"} and row[key]
        },
    )
    for key in inputs:
        columns.update(cached[key])
        rows.extend({**row, **cached[key]} for row in inputs[key])
    if columns & set(SOURCE_SCHEMA.names):
        raise ValueError("Extracted metadata conflicts with source locator columns")
    schema = pa.schema(
        [*SOURCE_SCHEMA, *[(name, STRINGS) for name in sorted(columns)]],
        metadata={
            "format_version": "5",
            "house_naming_version": __version__,
            "house_naming_fingerprint": fingerprint,
            **(metadata or {}),
        },
    )
    destination = root / "indexes/document-filenames.parquet"
    if {row["body_key"] for row in rows if row["body_key"]} != bodies:
        raise ValueError("Filename table does not cover every selected retained body")
    if names != {row["filename"] for row in rows if row["filename"]}:
        raise ValueError("Filename table does not cover every known spelling")
    document_stats = write_document_indexes(destination, rows, schema)
    return dict(
        rows=len(rows),
        **document_stats,
        distinct_bodies=len(bodies),
        distinct_filenames=len(
            {row["filename"] for row in rows if row["filename"] is not None}
        ),
        rows_without_retained_body=sum(row["body_key"] is None for row in rows),
        parser_inputs=len(inputs),
        parsed_inputs=len(pending),
        output=str(destination),
        output_bytes=destination.stat().st_size,
        elapsed_seconds=round(time.monotonic() - started),
    )


def build(root, inventory_dir, *, workers=4, families=FAMILIES):
    names, capture_rows, bodies, known_variants = collect_names(
        root, inventory_dir, families
    )
    print(
        compact(
            {
                "stage": "names_located",
                "capture_rows": capture_rows,
                "bodies": len(bodies),
                "filename_rows": len(names),
            }
        ),
        flush=True,
    )
    context = read_document_sources(root, {url for _, _, url in names if url})
    sources = (
        dict(
            body_key=body,
            filename=filename,
            source_url=url,
            **context.for_url(url),
            **{k: sorted(v) or None for k, v in origins.items()},
        )
        for (body, filename, url), origins in names.items()
    )
    return dict(
        write_filename_metadata(root, sources, workers=workers),
        capture_rows=capture_rows,
        known_inventory_spellings=len(known_variants),
    )


def refresh_filename_metadata(root, *, workers=4):
    """Reinterpret saved names without opening bodies, receipts or inventories."""
    source = pq.ParquetFile(root / "indexes/document-filenames.parquet")
    fields = [
        *SOURCE_SCHEMA.names,
        *sorted(
            (SOURCE_CONTEXT_FIELDS | {"capture_outcome"})
            & set(source.schema_arrow.names)
        ),
    ]
    rows = (
        row
        for batch in source.iter_batches(columns=fields)
        for row in batch.to_pylist()
    )
    return write_filename_metadata(root, rows, workers=workers)


def reindex_documents(root):
    """Refresh document grouping from existing fields without rerunning extraction."""
    path = root / "indexes/document-filenames.parquet"
    source = pq.ParquetFile(path)
    rows = [
        {key: value for key, value in row.items() if value is not None}
        for batch in source.iter_batches(batch_size=4096)
        for row in batch.to_pylist()
    ]
    return dict(
        rows=len(rows), **write_document_indexes(path, rows, source.schema_arrow)
    )
