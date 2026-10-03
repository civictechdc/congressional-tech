"""Write useful filename and selected retained-source metadata as flat columns.

Filename rules belong to house_naming.Engine. This command locates saved names,
keeps their meanings and references, and omits parser mechanics and diagnostics.

source_* columns retain parent context; source_document_type_basis distinguishes
publisher values from parser inference. source_occurrences keeps each original
page/link association together as Arrow structs, alongside flat filter columns.
source_committee_code is the meeting's Congress.gov systemCode; the separate
source_publisher_committee_code identifies the Senate site's owner from the
collector's existing site map. Missing context stays null. A shared document
retains all observed parents; flat lists do not imply pairwise relationships.
The archive updater reuses unchanged interpretations automatically.
document_kind uses filename evidence first, then typed contents or a recognized
source document type. document_kind_source identifies that choice; native types
stay intact.

Relative hrefs keep their literal spelling. source_resolved_url records only
destinations proved by retained parent anchors; multiple destinations stay
separate during grouping. Unplaced bodies retain their capture file, pointer,
URLs and receipt locator, even when no publisher filename was saved.
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from uuid import uuid4
from email.message import Message
from email.utils import collapse_rfc2231_value
from functools import lru_cache
import gzip
from io import BytesIO
from itertools import groupby
import json
from multiprocessing import get_context
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from house_naming import Engine, __version__, document_families
from house_naming.errors import NamingError
from house_naming.extraction import QUERY
from house_naming.values import filename_metadata as flatten  # noqa: F401 - public flat-value helper
from congress_api.retention import raw_progress as progress
from congress_api.retention.document_evidence import (
    FIELDS as EVIDENCE_FIELDS, BODY_FIELDS, body_evidence_key, cached_body_fields, evidence_fingerprint,
    enrich_sources, enrich_document_covers, read_retained_body, response_failed, apply_response_role,
)
from congress_api.parsers.source_family import family as source_family
from congress_api.parsers.document_links import http_url
from congress_api.parsers.document_cover import COVER_FIELDS


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
RESPONSE_FIELDS = (
    "response_usable", "response_body_complete", "response_format", "response_result",
)
SOURCE_SCHEMA = pa.schema(
    [
        ("body_key", pa.string()),
        ("filename", pa.string()),
        ("source_url", pa.string()),
        ("filename_origins", STRINGS),
        ("source_paths", STRINGS),
        ("media_type", STRINGS),
        ("http_status", STRINGS),
        *[(name, STRINGS) for name in RESPONSE_FIELDS],
    ]
)
ENGINE = None
EMPTY_BODY_DIGEST = sha256(b"").hexdigest()
DERIVED_KIND_SOURCES = frozenset({"source_document_type", "source_link_label", "content", "source_context"})

# Publisher document types and their XML codes, mapped to the catalog's kinds.
# This is index policy, not filename interpretation. Do not infer from link titles.
SOURCE_DOCUMENT_KINDS = {
    alias.casefold(): kind
    for kind, aliases in [
        ("witness-statement", ("Witness Statement", "WS")),
        ("testimony-disclosure", ("Witness Truth in Testimony", "truth in testimony", "WT")),
        ("witness-biography", ("Witness Biography", "WB")),
        ("witness-support", ("Witness Support Document", "WD")),
        ("member-statement", ("Member Statement", "Member Statements", "MS")),
        ("committee-amendment", ("Committee Amendment", "CA")),
        ("interchamber-amendment", ("House or Senate Amendment", "HA")),
        ("floor-amendment", ("Floor Amendment", "FA")),
        ("committee-vote", ("Committee Recorded Vote", "CV")),
        ("committee-report", ("Committee Report", "CR")),
        ("conference-report", ("Conference Report", "FR")),
        ("legislative-text", ("Bills and Resolutions", "BR", "legislative text")),
        ("summary", ("summary",)),
        ("support-document", ("Support Document", "SD")),
        ("transcript", ("Hearing: Transcript", "transcript", "HT")),
        ("witness-list", ("Hearing: Witness List", "witness list", "HW")),
        ("questions-for-record", ("Hearing: Questions for the Record", "questions for the record", "HQ")),
        ("member-roster", ("Hearing: Member Roster", "HM")),
        ("cover-page", ("Hearing: Cover Page", "HC")),
        ("table-of-contents", ("Hearing: Table of Contents", "TC")),
        ("questionnaire", ("questionnaire",)),
    ]
    for alias in aliases
}


def fill_document_kind(row):
    """Keep specific forms; expose a supported purpose through the family filter."""
    context_kind = nomination_support_context(row)
    _select_document_kind(row)
    if context_kind and not row.get('document_kind'):
        row['document_kind'] = [context_kind]
        row['document_kind_source'] = ['source_link_label' if context_kind == 'letter-of-support' else 'source_context']
    row['document_family'] = document_families([
        *(row.get('document_kind') or []), *(['nomination-support'] if context_kind else [])]) or None


def trusted_source_occurrences(row):
    """Only observed links/redirects establish a document's original context."""
    return [o for o in row.get('source_occurrences') or [] if not any(
        basis not in {'publisher_redirect', 'retained_html_link'}
        for basis in o.get('source_association_basis') or [])]


@lru_cache(maxsize=4096)
def nomination_support_label_kind(label):
    """Reuse house-naming's literal relations, targets and measure exclusions."""
    if not isinstance(label, str) or 'support' not in label.casefold():
        return None
    metadata = extract((label, None))
    if metadata.get('measure_references'):
        return None
    relations = [re.sub(r'[^a-z]', '', value.casefold())
                 for value in (metadata.get('relation_wording') or []) + (metadata.get('document_token') or [])]
    if any('oppos' in value for value in relations):
        return None
    if 'letter-of-support' in (metadata.get('document_kind') or []):
        return 'letter-of-support'
    if ((metadata.get('target_subject') or metadata.get('recipient_token'))
            and any(value.endswith(('supportfor', 'supportof')) for value in relations)):
        return 'nomination-support'
    return None


def nomination_support_context(row):
    """Recognize Judiciary nomination support from one actual page/link pair.

    Flat unions cannot establish this relationship. A support purpose says
    nothing about correspondence form, authorship, or verified person identity.
    """
    if row.get('record_role') in (['source-record'], ['capture-state'], ['error-response']) or response_failed(row):
        return None
    found = None
    for occurrence in trusted_source_occurrences(row):
        if occurrence.get('source_occurrence_scope') != ['anchor']:
            continue
        if not any(re.fullmatch(
            r'(?:(?:time(?: and room)?|room|location) change:\s*)?(?:nominations|(?:the )?nomination of .+)',
            title.strip(), re.I) for title in occurrence.get('source_page_title') or []):
            continue
        pages = []
        for value in occurrence.get('source_original_page_url') or []:
            try:
                page = urlsplit(value)
                if (page.scheme in {'http', 'https'} and page.hostname in {'judiciary.senate.gov', 'www.judiciary.senate.gov'}
                        and page.path.startswith('/committee-activity/hearings/')):
                    pages.append(page)
            except ValueError:
                continue
        if pages and occurrence.get('source_link_url'):
            for label in occurrence.get('source_link_label') or []:
                kind = nomination_support_label_kind(label)
                if kind == 'letter-of-support':
                    return kind
                found = kind or found
    return found


def _select_document_kind(row):
    """Choose a kind without changing native fields or broadening filename rules."""
    if row.get("document_kind"):
        row["document_kind_source"] = ["recovered_filename" if row.get("recovered_filename") else "filename"]
        return
    if row.get("content_document_kind"):
        row["document_kind"] = row["content_document_kind"]
        row["document_kind_source"] = ["content"]
        return
    if row.get("record_role") in (["source-record"], ["capture-state"], ["error-response"]):
        row["document_kind"] = row["document_kind_source"] = None
        return
    # A collector recovery candidate carries useful context but does not prove
    # it is the document the publisher linked. Only established occurrences
    # may supply a missing kind; keep all candidates' literal metadata visible.
    occurrences = row.get("source_occurrences")
    trusted = trusted_source_occurrences(row)
    def scope(observation):
        pages = observation.get('source_original_page_url') or []
        links = observation.get('source_link_url') or []
        return (pages[0], http_url(links[0]) or links[0]) if len(pages) == len(links) == 1 else None

    inferred = {'inventory_inference', 'house_parser_inference', 'senate_parser_inference', 'senate_parser_fallback'}
    explicit = {scope(o) for o in trusted if scope(o) and any(
        basis.startswith('publisher') for basis in o.get('source_document_type_basis') or [])
        and any(' '.join(value.split()).casefold() in SOURCE_DOCUMENT_KINDS
                for value in o.get('source_document_type') or [])}
    # A publisher's own member section corrects an older witness guess for
    # this exact page/link. Preserve both observations and unrelated parents.
    trusted = [o for o in trusted if not (scope(o) in explicit
               and o.get('source_document_type_basis')
               and set(o['source_document_type_basis']) <= inferred)]
    source_types = ([value for o in trusted for value in o.get("source_document_type") or []]
                    if occurrences else row.get("source_document_type") or [])
    label_kinds = ([value for o in trusted for value in o.get("source_label_document_kind") or []]
                   if occurrences else row.get("source_label_document_kind") or [])
    kinds = {
        kind for value in source_types
        if (kind := SOURCE_DOCUMENT_KINDS.get(" ".join(value.split()).casefold()))
    }
    row["document_kind"] = sorted(kinds) or None
    row["document_kind_source"] = ["source_document_type"] if kinds else None
    if not kinds and label_kinds:
        row["document_kind"] = sorted(set(label_kinds))
        row["document_kind_source"] = ["source_link_label"]

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
        parts = urlsplit(http_url(url) or url)
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
        and not response_failed(row)
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
    for field in ("source_resolved_url", "capture_outcome", "body_format", *RESPONSE_FIELDS):
        columns.append(table[field].to_pylist() if field in table.column_names else [None] * len(table))
    for row_id, (filename, url, body, media, statuses, resolved, outcomes, body_format, *response) in enumerate(
        zip(*columns)
    ):
        endpoint = entry_key(filename, url, row_id)
        # An orphan href has no host of its own. Only an observed, unambiguous
        # parent/anchor resolution can join it to an absolute endpoint.
        if endpoint == ("row", row_id) and url and resolved and len(resolved) == 1:
            endpoint = entry_key(filename, resolved[0], row_id)
        parents[root(row_id)] = root(endpoints.setdefault(endpoint, row_id))
        if document_body(body, media, statuses, outcomes, body_format, dict(zip(RESPONSE_FIELDS, response))):
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


def document_body(body, media, statuses, outcomes=None, body_format=None, response=None):
    formats = set(body_format or file_formats(media, None) or [])
    document_formats = set(MEDIA_FORMATS.values()) - {"html", "binary"}
    return (
        body
        if (
            body
            and not response_failed({**(response or {}), "http_status": statuses,
                                     "capture_outcome": outcomes})
            and body.rsplit("/", 1)[-1].removesuffix(".gz") != EMPTY_BODY_DIGEST
            and (not outcomes or set(outcomes) == {"saved"})
            and formats
            and formats <= document_formats
            and (any(str(status).startswith("2") for status in statuses or [])
                 or (not statuses and body_format == ["pdf"]))
        )
        else None
    )


def prepare_document_indexes(rows, schema):
    """Keep exact source rows and create one canonical row per document group."""
    progress.report('group_documents', total=len(rows), unit='source_rows')
    for name in ("document_kind", "document_kind_source", "document_family", "record_role", "source_record_type"):
        if name not in schema.names:
            schema = schema.append(pa.field(name, STRINGS))
    # The parser's public metadata keeps both names for compatibility. These
    # tables need only one normalized publication code, alongside raw spelling.
    # Preserve either column if any row actually carries a distinct reading.
    redundant = "publication_code_code"
    if redundant in schema.names and all(
        not row.get(redundant) or row[redundant] == row.get("publication_type")
        for row in rows
    ):
        schema = pa.schema([field for field in schema if field.name != redundant],
                           metadata=schema.metadata)
        for row in rows:
            row.pop(redundant, None)
    for row in rows:
        apply_capture_record_role(row)
        # Source metadata can change without reparsing filenames. Remove only
        # previous fallbacks before regrouping so they never outrank an alias's
        # filename kind or survive removal/correction of the source assertion.
        if any(value in DERIVED_KIND_SOURCES for value in row.get("document_kind_source") or []):
            row["document_kind"] = None
        row.pop("document_kind_source", None)
        row["source_id"] = sha256(
            compact(
                [row.get(k) for k in ("body_key", "filename", "source_url")]
            ).encode()
        ).hexdigest()
        row["record_role"] = row.get("record_role") or ["document"]
        row["format"] = (None if row["record_role"] == ["capture-state"] else
                         row.get("body_format") or file_formats(row.get("media_type"), row.get("extension")))
    grouping_schema = pa.schema([*SOURCE_SCHEMA, ("source_resolved_url", STRINGS),
                                ("capture_outcome", STRINGS), ("body_format", STRINGS)])
    _, groups = source_groups(pa.Table.from_pylist(rows, schema=grouping_schema))
    documents = []
    for members in progress.track(groups, 'combine_document_metadata', unit='document_groups'):
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
                        row.get("body_format"),
                        row,
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
            filename=display_filename((preferred.get("recovered_filename") or [preferred.get("filename")])[0]),
        )
        values = defaultdict(set)
        for row in sources:
            row["document_id"] = document_id
            for key, value in row.items():
                if isinstance(value, list):
                    if key != "source_occurrences":
                        values[key].update(value)
        document.update({key: sorted(value) for key, value in values.items() if value})
        occurrences = merge_values("source_occurrences", *[row.get("source_occurrences") for row in sources])
        if occurrences:
            document["source_occurrences"] = occurrences
        # A successful document and its error/marker history can share an endpoint.
        # The group's role describes its usable document; each source keeps its role.
        roles = values["record_role"]
        document["record_role"] = [next(role for role in (
            "document", "source-record", "error-response", "capture-state"
        ) if role in roles)]
        # Aggregate filename kinds before filling individual source-row gaps.
        # A broad native type on an alias must not dilute a more specific name.
        fill_document_kind(document)
        if any(row.get("document_kind") and not row.get("recovered_filename") for row in sources):
            document["document_kind_source"] = ["filename"]
        for row in sources:
            fill_document_kind(row)
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
        b"format_version": b"10",
        b"catalog_id": catalog_id.encode(),
    }
    source_schema = pa.schema(fields, metadata=metadata)
    document_schema = pa.schema(
        [
            *fields,
            *[(name, STRINGS) for name in ("filenames", "source_urls", "body_keys")],
        ],
        metadata={**metadata, b"format_version": b"5"},
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
    progress.report('write_document_tables', completed=0, total=len(rows) + len(documents), unit='rows')
    written = 0
    try:
        for tmp, (_, records, record_schema) in zip(temporary, outputs):
            with pq.ParquetWriter(tmp, record_schema, compression="zstd") as writer:
                for start in range(0, len(records), 32768):
                    writer.write_table(
                        pa.Table.from_pylist(
                            records[start : start + 32768], schema=record_schema
                        )
                    )
                    written += min(32768, len(records) - start)
                    progress.report('write_document_tables', completed=written,
                                    total=len(rows) + len(documents), unit='rows')
        progress.report('validate_document_tables')
        validate_document_indexes(*temporary, source_rows=len(rows), document_rows=len(documents))
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


def validate_document_indexes(source_path, document_path, *, source_rows=None, document_rows=None):
    """Validate the actual paired files before either destination is replaced."""
    source_ids = pq.read_table(source_path, columns=["source_id", "document_id"])
    document_ids = pq.read_table(document_path, columns=["source_id", "document_id"])
    source_meta = source_ids.schema.metadata or {}
    document_meta = document_ids.schema.metadata or {}
    if not source_meta.get(b"catalog_id") or source_meta[b"catalog_id"] != document_meta.get(b"catalog_id"):
        raise ValueError("Document/source catalog_id values do not match")
    sources = source_ids["source_id"].to_pylist()
    groups = source_ids["document_id"].to_pylist()
    preferred = document_ids["source_id"].to_pylist()
    documents = document_ids["document_id"].to_pylist()
    if (source_rows is not None and len(sources) != source_rows
            or document_rows is not None and len(documents) != document_rows
            or any(value is None for values in (sources, groups, preferred, documents) for value in values)
            or len(set(sources)) != len(sources) or len(set(documents)) != len(documents)
            or set(groups) != set(documents)
            or not set(zip(preferred, documents)) <= set(zip(sources, groups))):
        raise ValueError("Document/source index references do not match")


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def metadata_type(name):
    """Keep source occurrences paired in Arrow, without serializing them as JSON."""
    if name == "source_occurrences":
        return pa.list_(pa.struct([(field, STRINGS) for field in SOURCE_OCCURRENCE_FIELDS]))
    return STRINGS


def merge_values(field, *groups):
    if field != "source_occurrences":
        return sorted({value for group in groups if group for value in group})
    # Arrow fills absent struct fields with null on readback. Normalize those
    # away before deduplication so repeated refreshes do not multiply origins.
    values = {}
    for group in groups:
        for occurrence in group or []:
            normalized = {key: sorted(set(items)) for key, items in occurrence.items() if items}
            if normalized:
                values[json.dumps(normalized, sort_keys=True)] = normalized
    return [values[key] for key in sorted(values)]


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
            value = owner.get("complete")  # SourceCapture's native spelling.
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
        "source_link_url",
        "source_link_href",
        "source_resolved_url",
        "source_link_label",
        "source_witness_name",
        "source_witness_position",
        "source_witness_organization",
        "source_participant_label",
        "source_page_sha256",
        "source_original_page_url",
        "source_link_heading",
        "source_link_context",
        "source_document_type_basis",
        "source_label_document_kind",
        "source_association_basis",
        "source_associated_url",
        "source_receipt_key",
        "source_receipt_line",
        "source_capture_file",
        "source_capture_pointer",
        "source_capture_url",
        "source_occurrence_scope",
        "source_probe_status",
        "source_probe_method",
        "source_probe_checked_at",
        "source_occurrences",
    }
)


SOURCE_OCCURRENCE_FIELDS = tuple(sorted(SOURCE_CONTEXT_FIELDS - {"source_occurrences"}))


def source_label_kind(label):
    """Only a standalone genre or final, explicit label segment supplies a signal."""
    if not isinstance(label, str):
        return None
    match = re.fullmatch(r"(?:[^\r\n]+?\s+-\s+)?(Article|Op-Ed)", label.strip(), re.I)
    return match[1].lower() if match else None


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

    Original publisher words, parser inferences and collector relationships
    remain separately identified. Occurrences preserve parent/link pairings;
    flat fields are filters, not associations. No filename or shared-host
    matching supplies provenance or document identity.
    """

    def __init__(self, urls=None):
        self.urls = {http_url(url) or url for url in urls} if urls is not None else None
        self.by_url = {}
        self.occurrences = defaultdict(dict)
        self.transfers = defaultdict(list)
        self.meetings = {}
        self.events = defaultdict(set)

    def add_url(self, url, values):
        if isinstance(url, str):
            url = http_url(url) or url
        if not isinstance(url, str) or not url or self.urls is not None and url not in self.urls:
            return
        if "source_occurrences" in values:
            # Restored flat filters already summarize paired observations. Do
            # not turn that summary into a fabricated cross-product occurrence.
            merge_context(self.by_url.setdefault(url, {}), {
                key: items for key, items in values.items()
                if key in SOURCE_OCCURRENCE_FIELDS and items})
            pending = [(url, occurrence) for occurrence in values.get("source_occurrences") or []]
        else:
            pending = [(url, values)]
        while pending:
            destination, supplied = pending.pop()
            occurrence = {key: sorted(set(items)) for key, items in supplied.items()
                          if key in SOURCE_OCCURRENCE_FIELDS and items}
            if not occurrence:
                continue
            occurrence.setdefault("source_occurrence_scope", ["source_record"])
            # Repeated retained copies of the same observation need one exact
            # representative locator. The captures index retains every receipt.
            identity = sha256(json.dumps({key: items for key, items in occurrence.items()
                if not key.startswith("source_receipt_")}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if identity in self.occurrences[destination]:
                continue
            self.occurrences[destination][identity] = occurrence
            merge_context(self.by_url.setdefault(destination, {}), occurrence)
            for target, association in self.transfers.get(destination, []):
                # Each transferred occurrence retains its original parent/link.
                # Association fields describe this edge, never document identity.
                pending.append((target, self.transfer_occurrence(occurrence, association)))

    @staticmethod
    def transfer_occurrence(occurrence, association):
        result = dict(occurrence)
        for field, values in association.items():
            if field.startswith("source_receipt_") and result.get(field):
                continue  # Keep the original source locator, not a later edge's.
            result[field] = merge_values(field, result.get(field), values)
        return result

    def add_transfer(self, requested, final, values):
        requested = (http_url(requested) or requested) if isinstance(requested, str) else requested
        final = (http_url(final) or final) if isinstance(final, str) else final
        if not all(isinstance(url, str) and url for url in (requested, final)) or requested == final:
            return
        association = {key: sorted(items) for key, items in values.items() if items}
        edge = (final, association)
        if any(target == final and {k: v for k, v in previous.items() if not k.startswith("source_receipt_")}
               == {k: v for k, v in association.items() if not k.startswith("source_receipt_")}
               for target, previous in self.transfers[requested]):
            return
        self.transfers[requested].append(edge)
        for occurrence in list(self.occurrences.get(requested, {}).values()):
            self.add_url(final, self.transfer_occurrence(occurrence, association))

    def for_url(self, url):
        url = (http_url(url) or url) if isinstance(url, str) else url
        result = {key: sorted(values) for key, values in self.by_url.get(url, {}).items() if values}
        if self.occurrences.get(url):
            result["source_occurrences"] = [dict(self.occurrences[url][key])
                                            for key in sorted(self.occurrences[url])]
        return result

    def add_link(self, link, receipt=None):
        """Read a native seed or discovered link retained by recurring capture."""
        parent = link.get("context") or {}
        self.add_meeting(parent)
        native = link.get("native") or {}
        parsed_tuple = isinstance(native, (list, tuple))
        house_tuple = parsed_tuple and len(native) >= 4
        if parsed_tuple:
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
            source_original_page_url=link.get("parent_url"),
            source_link_url=link.get("url"),
            source_link_label=link.get("text"),
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
                for k, v in self.by_url.get(http_url(link.get("parent_url") or '') or link.get("parent_url"), {}).items()
                if not k.startswith(("source_document_", "source_link_", "source_witness_", "source_participant_", "source_receipt_", "source_associat", "source_label_"))
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
        if link.get("parent_url"):
            values["source_original_page_url"] = {link["parent_url"]}
        merge_context(values, receipt or {})
        if native.get("documentType"):
            basis = ("house_parser_inference" if house_tuple else
                     "senate_parser_fallback" if native["documentType"] == "other" else "senate_parser_inference") if parsed_tuple else "publisher"
            merge_context(values, context_values(source_document_type_basis=basis))
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

    def refresh_meeting_context(self):
        """Join later meeting facts to earlier links using their scoped event ID."""
        for url, observations in list(self.occurrences.items()):
            for occurrence in list(observations.values()):
                events = occurrence.get('source_meeting_id') or []
                chambers = occurrence.get('source_chamber') or []
                congresses = occurrence.get('source_congress') or []
                if len(events) != 1 or len(chambers) != 1 or len(congresses) > 1:
                    continue
                meeting = self.event_context(events[0], chambers[0], congresses[0] if congresses else None)
                if not meeting:
                    continue
                expanded = dict(occurrence)
                for field, values in meeting.items():
                    if field in {"source_page_url", "source_original_page_url"}:
                        continue  # Keep the actual parent page of this link.
                    expanded[field] = merge_values(field, expanded.get(field), values)
                if expanded != occurrence:
                    self.add_url(url, expanded)

    def add_meeting(self, record, receipt=None):
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
            source_original_page_url=record.get("_url"),
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
        # A child inherits meeting facts, not every archive copy's locator.
        merge_context(values, receipt or {})
        self.add_url(record.get("_url"), values)
        for group in ("meetingDocuments", "witnessDocuments", "hearingTranscript"):
            for document in record.get(group) or []:
                if isinstance(document, dict):
                    context = {name: set(items) for name, items in values.items()}
                    merge_context(
                        context,
                        context_values(
                            source_document_group=group,
                            source_link_url=document.get("url"),
                            source_document_type=document.get("documentType"),
                            source_document_type_basis="publisher" if document.get("documentType") else None,
                            source_document_label=document.get("name")
                            or document.get("description"),
                            source_document_format=document.get("format"),
                        ),
                    )
                    self.add_url(document.get("url"), context)

    def add_senate(self, state, receipt=None, *, read_body=None):
        from congress_api.parsers.senate import parsed
        from congress_api.parsers.senate_page import SITE, document_context

        if not isinstance(state, dict):
            return
        publishers = {host: code for code, host in SITE.items()}
        for host, site in state.items():
            if not isinstance(site, dict):
                continue
            for url, page in site.get("pages", {}).items():
                if not isinstance(page, dict):
                    continue
                workflow = (site.get("workflow") or {}).get(url, page)
                digest = ((page.get("cache_replay") or workflow.get("cache_replay") or {}).get("raw_sha256")
                          or (page.get("raw_html") or {}).get("sha256"))
                metadata_by_url = page.get("document_metadata") or {}
                event = page.get("event") or {}
                # Replay only the exact retained observation, never an arbitrary
                # newer page at the same URL. The storage dependency validates
                # the digest and bounds the read; missing bodies retain state.
                if read_body is not None and digest and re.fullmatch(r"[a-f0-9]{64}", digest):
                    raw = read_body(f"bodies/sha256/{digest[:2]}/{digest}.gz")
                    if raw:
                        # Refresh the discovered links and their witnesses too;
                        # old parser output may not contain a newly recognized
                        # anchor. Keep the original byte digest as its locator.
                        page = {**page, **parsed(raw.decode("utf-8", "replace"), url)}
                        metadata_by_url = page.get("document_metadata") or {}
                        event = page.get("event") or event
                context = context_values(
                    source_page_url=url,
                    source_original_page_url=url,
                    source_page_title=page.get("title"),
                    source_page_date=event.get("date"),
                    source_page_type=event.get("type"),
                    source_publisher_committee_code=publishers.get(host.removeprefix("www.")),
                    source_page_sha256=digest,
                )
                merge_context(context, receipt or {})
                # Preserve existing confirmed matches, never candidate_events.
                for event_id in workflow.get("events") or []:
                    merge_context(context, self.event_context(event_id))
                context["source_original_page_url"] = {url}
                self.add_url(url, context)
                for document in page.get("documents") or []:
                    if not isinstance(document, (list, tuple)) or len(document) != 3:
                        continue
                    kind, label, document_url = document
                    metadata = (metadata_by_url.get(document_url)
                                or metadata_by_url.get(http_url(document_url) or document_url) or {})
                    anchors = metadata.get("occurrences")
                    if not anchors:
                        anchors = [{**metadata, "labels": sorted(set(metadata.get("labels") or []) |
                            {value for value in [(page.get("document_labels") or {}).get(document_url)] if value})}]
                    for anchor in anchors:
                        context_kind, context_basis = document_context(anchor)
                        values = {name: set(items) for name, items in context.items()}
                        merge_context(values, context_values(
                            source_document_group="page.documents",
                            source_document_type=context_kind or kind,
                            source_document_type_basis=context_basis if context_kind else
                                "senate_parser_fallback" if kind == "other" else "senate_parser_inference",
                            source_document_label=label,
                            source_link_url=document_url,
                            source_link_context=anchor.get("paragraph_text"),
                            source_occurrence_scope="anchor" if metadata.get("occurrences") else "retained_url_aggregate",
                        ))
                        for written in anchor.get("labels") or []:
                            merge_context(values, context_values(source_link_label=written,
                                          source_label_document_kind=source_label_kind(written)))
                        for heading in anchor.get("headings") or []:
                            merge_context(values, context_values(source_link_heading=heading))
                        if card := anchor.get("witness_card"):
                            merge_context(values, context_values(source_participant_label=card.get("name")))
                        witnesses = page.get("witnesses") or []
                        for i in anchor.get("witness_indexes") or []:
                            if type(i) is not int or not 0 <= i < len(witnesses):
                                continue
                            witness = witnesses[i]
                            if isinstance(witness, dict):
                                merge_context(values, context_values(
                                    source_witness_name=witness.get("name"),
                                    source_witness_position=witness.get("position"),
                                    source_witness_organization=witness.get("organization"),
                                ))
                        self.add_url(document_url, values)
                        for attributes in anchor.get("attributes") or []:
                            href = attributes.get("href")
                            if not isinstance(href, str) or not href:
                                continue
                            try:
                                # Match the parser's observed destination, not
                                # a guessed host or a filename search result.
                                if urlsplit(href).scheme or urljoin(url, href) != document_url:
                                    continue
                            except ValueError:
                                continue
                            self.add_url(href, {**values, "source_link_href": {href},
                                               "source_resolved_url": {document_url}})

    def add_house(self, state, receipt=None):
        """Retain saved House parser labels separately from literal XML metadata."""
        if not isinstance(state, dict):
            return
        for event, page in state.items():
            if not isinstance(page, dict) or not isinstance(page.get("documents"), list):
                continue
            values = {**self.event_context(event, "house"), **(receipt or {})}
            for document in page["documents"]:
                if not isinstance(document, (list, tuple)) or len(document) < 3:
                    continue
                kind, label, url = document[:3]
                self.add_url(url, {**values, **context_values(
                    source_document_group="house.documents", source_link_url=url,
                    source_document_type=kind, source_document_label=label,
                    source_document_type_basis="house_parser_inference" if kind else None)})
            self.add_house_evidence(page.get("evidence") or {}, values)

    def add_house_evidence(self, evidence, receipt=None):
        """Read the existing House evidence model without flattening file ownership."""
        witnesses = {w.get("selector"): w for w in evidence.get("witness_observations") or []}
        for group in evidence.get("document_groups") or []:
            if not group.get("active"):
                continue
            witness = witnesses.get(group.get("owning_witness_selector"), {})
            for file in group.get("files") or []:
                if not file.get("active"):
                    continue
                attributes = (file.get("metadata") or {}).get("attributes") or {}
                self.add_url(file.get("url"), {**(receipt or {}), **context_values(
                    source_link_url=file.get("url"), source_capture_pointer=file.get("selector"),
                    source_document_group=group.get("source"), source_witness_name=witness.get("name"),
                    source_document_type=group.get("type") or group.get("legacy_kind"),
                    source_document_type_basis="publisher" if group.get("type") else
                        "house_parser_inference" if group.get("legacy_kind") else None,
                    source_document_label=group.get("description"), source_document_format=file.get("format"),
                    source_document_added_at=attributes.get("add-date"),
                    source_document_published_at=attributes.get("publish-date"))})

    def add_inventory(self, record, receipt=None):
        if not isinstance(record, dict) or not isinstance(
            record.get("observations"), list
        ):
            return
        url = record.get("url")
        if not url or self.urls is not None and (http_url(url) or url) not in self.urls:
            return
        for observation in record["observations"]:
            if not isinstance(observation, dict):
                continue
            context = context_values(
                source_congress=observation.get("congress"),
                source_chamber=observation.get("chamber"),
                source_meeting_id=observation.get("event_id"),
                source_page_url=observation.get("page_url"),
                source_original_page_url=observation.get("page_url"),
                source_link_url=url,
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
            merge_context(context, {key: values for key, values in self.by_url.get(http_url(page) or page, {}).items()
                                    if not key.startswith(("source_document_", "source_link_", "source_witness_", "source_participant_", "source_label_", "source_associat", "source_receipt_"))})
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
            if page:
                context["source_original_page_url"] = {page}
            merge_context(context, receipt or {})
            native_type = native.get("documentType") or group.get("type")
            # Preserve both native and collector types as separate paired claims.
            kinds = [(native_type, "publisher"), (observation.get("kind"), "inventory_inference")]
            if not any(kind for kind, _ in kinds):
                self.add_url(url, context)
            for kind, basis in kinds:
                if kind:
                    self.add_url(url, {**context, **context_values(source_document_type=kind,
                                                                  source_document_type_basis=basis)})

    def add_redirect(self, record, receipt=None):
        """Transfer observed relationships, including failed responses, not identity."""
        if not isinstance(record, dict):
            return
        requested = record.get("requested_url") or record.get("url")
        final = record.get("final_url") or (record.get("url") if record.get("requested_url") else None)
        if type(record.get("http_status")) is int and requested and final and requested != final:
            self.add_transfer(requested, final, {**(receipt or {}), **context_values(
                source_association_basis="publisher_redirect", source_associated_url=requested)})

    def add_associations(self, record, receipt=None):
        """Retain collector recovery lineage without calling it a redirect."""
        if not isinstance(record, dict):
            return
        requested = record.get("url")
        for association in record.get("source_associations") or []:
            if not isinstance(association, dict):
                continue
            original, basis = association.get("original_url"), association.get("basis")
            if isinstance(basis, str) and basis and basis != "publisher_redirect":
                self.add_transfer(original, requested, {**(receipt or {}), **context_values(
                    source_association_basis=basis, source_associated_url=original)})


def add_retained_senate_pages(context, captures, read_body):
    """Read independent HTML observations without replacing older saved state."""
    from congress_api.models.content import RawContent
    from congress_api.parsers.senate import parsed
    from congress_api.parsers.senate_page import SITE

    required = {"family", "http_status", "body_key", "context_url", "receipt_key", "receipt_line"}
    if not required <= set(captures.column_names):
        return
    selected = captures.filter(pc.and_(pc.equal(captures["family"], "senate/pages"),
                                      pc.equal(captures["http_status"], 200)))
    observations = {}
    for row in selected.select(sorted(required)).to_pylist():
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
            continue  # This exact page observation was already replayed above.
        observations.setdefault((url, key, host), set()).add((row["receipt_key"], row["receipt_line"]))
    for (url, key, host), receipts in progress.track(
            observations.items(), 'read_senate_html', unit='pages'):
        raw = read_body(key)
        if raw is None or not re.search(br"<(?:html\b|!doctype\s+html\b)", raw[:2048], re.I):
            continue
        page = parsed(raw.decode("utf-8", "replace"), url)
        # parsed(str) hashes re-encoded text. The locator must identify the
        # original retained bytes, including any non-UTF-8 publisher content.
        page["raw_html"] = RawContent.from_bytes(raw, "text/html").source_dict()
        for receipt, line in sorted(receipts):
            context.add_senate({host: {"pages": {url: page}}}, context_values(
                source_receipt_key=receipt, source_receipt_line=line))


def retained_records(captures, read_receipt, *, stage='replay_capture_receipts'):
    """Read each referenced receipt line once, with all its indexed body pointers."""
    progress.report(stage, completed=0, total=len(captures), unit='capture_rows')
    completed = reported = 0
    references = defaultdict(lambda: defaultdict(list))
    batches = captures.to_batches(max_chunksize=65536)
    # Keep row positions while grouping; decoding every URL, path and body
    # field here duplicates the whole capture inventory as Python objects.
    for batch_number, batch in enumerate(batches):
        for position, row in enumerate(batch.select(["receipt_key", "receipt_line"]).to_pylist()):
            if not row.get("receipt_key") or type(row.get("receipt_line")) is not int or row["receipt_line"] < 1:
                raise ValueError("Invalid capture receipt locator")
            references[row["receipt_key"]][row["receipt_line"]].append((batch_number, position))
    for key, lines in sorted(references.items()):
        payload = read_receipt(key)
        if payload is None:
            raise ValueError(f"Missing capture receipt: {key}")
        with gzip.open(BytesIO(payload), "rt", encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                positions = lines.pop(number, None)
                if positions:
                    rows = []
                    # Taking from the original batch avoids repeatedly joining
                    # every Arrow chunk for each small receipt lookup.
                    for batch_number, group in groupby(positions, key=lambda item: item[0]):
                        selected = pa.array([position for _, position in group], type=pa.int64())
                        rows.extend(batches[batch_number].take(selected).to_pylist())
                    yield json.loads(line)["record"], rows, context_values(
                        source_receipt_key=key, source_receipt_line=number)
                    completed += len(rows)
                    if completed - reported >= 1000:
                        progress.report(stage, completed=completed, total=len(captures), unit='capture_rows')
                        reported = completed
                if not lines:
                    break
        if lines:
            raise ValueError(f"Capture index references missing receipt lines: {key}")
    progress.report(stage, completed=completed, total=len(captures), unit='capture_rows')


def add_retained_house_documents(context, captures, read_body):
    """Replay publisher XML through the existing House parser, with exact locators."""
    from congress_api.parsers.house_evidence import retained_evidence
    from congress_api.parsers.xml import parse_xml
    from xml.etree.ElementTree import ParseError

    selected = captures.filter(pc.is_in(captures["family"], value_set=pa.array(
        ["house/meeting-xml", "house/witness-xml"])))
    seen = set()
    for row in progress.track(selected.to_pylist(), 'read_house_xml', unit='capture_rows'):
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
        values = {**context_values(source_meeting_id=event, source_chamber="House"),
                  **context.event_context(event, "house"), **context_values(
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
    columns = [
        name
        for name in ("family", "source_file", "receipt_key", "receipt_line", "body_key", "context_url", "http_status")
        if name in captures.column_names
    ]
    captures = captures.select(columns)

    def records(family, suffix=None):
        selected = captures if family is None else captures.filter(pc.equal(captures["family"], family))
        if suffix:
            if "source_file" not in selected.column_names:
                return
            selected = selected.filter(pc.ends_with(selected["source_file"], suffix))
        stage = 'read_' + (suffix or family).replace('/', '_').replace('.', '_')
        for record, _, receipt in retained_records(selected, read_receipt, stage=stage):
            yield record, receipt

    for record, receipt in records("congress/meetings"):
        context.add_meeting(record, receipt)
    # Parent pages also supply context for inventory links. Retain page entries
    # even when the caller only needs linked document URLs.
    wanted = urls
    for record, receipt in records("senate/pages", "senate.json.gz"):
        context.add_senate(record, receipt, read_body=read_body)
    for record, receipt in records(None, "house.json.gz"):
        context.add_house(record, receipt)
    add_retained_house_documents(context, captures, read_body)
    for record, receipt in records("documents", "documents/inventory.jsonl.gz"):
        context.add_inventory(record, receipt)
    add_retained_senate_pages(context, captures, read_body)
    # Download receipts can refer to an HTML landing page whose exact anchor
    # supplies the later requested URL. Read only those retained page bodies.
    body_references = defaultdict(set)
    if {"body_key", "context_url"} <= set(captures.column_names):
        selected = captures.filter(pc.is_in(captures["context_url"], value_set=pa.array(sorted(context.by_url), type=pa.string())))
        for row in selected.select(["receipt_key", "receipt_line", "body_key", "context_url"]).to_pylist():
            if row["body_key"]:
                body_references[(row["receipt_key"], row["receipt_line"])].add((row["body_key"], row["context_url"]))
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


def apply_capture_record_role(row):
    """Keep receipt/pointer pairs together when recognizing embedded source HTML."""
    if row.get("source_record_type"):
        return
    for occurrence in row.get("source_occurrences") or []:
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


def refresh_response_metadata(root, rows):
    """Recover response facts by exact body/URL and locators for unplaced bodies.

    A body-only row can recover its capture locations, but cannot borrow one
    response's success/failure from other requests that returned the same bytes.
    """
    path = root / "indexes/captures.parquet"
    if not path.exists():
        return
    targets = defaultdict(list)
    unplaced = set()
    for row in rows:
        if row.get("body_key") and (row.get("source_url") or row.get("filename") is None):
            targets[(row["body_key"], row.get("source_url"))].append(row)
            if not row.get("source_occurrences") or all(
                o.get("source_occurrence_scope") == ["capture"] for o in row["source_occurrences"]
            ):
                unplaced.add(id(row))
    if not targets:
        return
    archive = pq.ParquetFile(path)
    required = {"body_key", "receipt_key", "receipt_line", "pointer_json", "context_url"}
    if not required <= set(archive.schema_arrow.names):
        return
    references = defaultdict(lambda: defaultdict(list))
    bodies = pa.array(sorted({key[0] for key in targets}), type=pa.string())
    columns = required | ({"family", "source_file", "original_path", "media_type", "http_status"}
                          & set(archive.schema_arrow.names))
    for batch in archive.iter_batches(columns=sorted(columns)):
        selected = pa.Table.from_batches([batch])
        selected = selected.filter(pc.is_in(pc.cast(selected["body_key"], pa.string()), value_set=bodies))
        for capture in selected.to_pylist():
            references[capture["receipt_key"]][capture["receipt_line"]].append(capture)
    for receipt, lines in sorted(references.items()):
        with gzip.open(root / receipt, "rt", encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                captures = lines.pop(number, None)
                if captures is not None:
                    record = json.loads(line)["record"]
                    for capture in captures:
                        owner = nearest_record(record, capture["pointer_json"])
                        facts = response_metadata(capture, record)
                        urls = {url for url in (capture["context_url"], owner.get("requested_url"),
                                owner.get("final_url"), owner.get("url")) if isinstance(url, str) and url}
                        for url in urls | {None}:
                            for row in targets.get((capture["body_key"], url), ()):
                                if url is not None:
                                    for field in RESPONSE_FIELDS:
                                        if facts.get(field):
                                            row[field] = merge_values(field, row.get(field), facts[field])
                                if id(row) in unplaced:
                                    occurrence = {key: sorted(values) for key, values in context_values(
                                        source_capture_file=capture.get("source_file"),
                                        source_capture_pointer=capture["pointer_json"],
                                        source_receipt_key=receipt, source_receipt_line=number,
                                        source_occurrence_scope="capture",
                                    ).items()}
                                    if urls:
                                        occurrence["source_capture_url"] = sorted(urls)
                                    row["source_occurrences"] = merge_values(
                                        "source_occurrences", row.get("source_occurrences"), [occurrence])
                                    for field, values in occurrence.items():
                                        row[field] = merge_values(field, row.get(field), values)
                                    if capture.get("original_path"):
                                        row["source_paths"] = merge_values(
                                            "source_paths", row.get("source_paths"), [capture["original_path"]])
                                if (not row.get("source_record_type") and (kind := capture_record_type(
                                        capture.get("family"), capture.get("pointer_json")))):
                                    row["source_record_type"] = [kind]
                                    row["record_role"] = ["source-record"]
                if not lines:
                    break
        if lines:
            raise ValueError(f"Response index references missing receipt lines: {receipt}")


def refresh_source_metadata(root, context=None):
    """Refresh retained provenance and response facts, then regroup without parsing names."""
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
            # A partial replay cannot retract publisher facts already retained
            # from XML/receipts. Keep those paired observations; parser-inferred
            # fields are replaced by the fresh interpretation below.
            native = [o for o in row.get("source_occurrences") or []
                      if o.get("source_document_type_basis") == ["publisher"] or o.get("source_probe_status")]
            added = context.for_url(row.get("source_url"))
            if native:
                added["source_occurrences"] = merge_values(
                    "source_occurrences", added.get("source_occurrences"), native)
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
    refresh_response_metadata(root, rows)
    columns.update(field for row in rows for field in row
                   if field in SOURCE_CONTEXT_FIELDS | set(RESPONSE_FIELDS) | {"source_record_type"})
    # Response roles depend on newly read facts, not another body download.
    for row in rows:
        apply_response_role(row)
    enrich_document_covers(rows, read_body=lambda key: read_retained_body(root, key))
    columns.update(field for field in (*COVER_FIELDS, 'body_format')
                   if any(row.get(field) for row in rows))
    schema = pa.schema(
        [
            *[f for f in source.schema_arrow if f.name not in SOURCE_CONTEXT_FIELDS | columns],
            *[(name, metadata_type(name)) for name in sorted(columns)],
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
    selected = pc.is_in(table["family"], value_set=pa.array(families))
    if "documents" in families:
        # Reinterpret historical page routing through the same source owner.
        # This recovers existing downloads without rewriting immutable receipts.
        pages = pc.equal(table["family"], "senate/pages")
        urls = table.filter(pages)["context_url"].to_pylist()
        downloads = pa.array(sorted({url for url in urls if url and source_family(url=url) == "documents"}),
                             type=pa.string())
        selected = pc.or_(selected, pc.and_(pages, pc.is_in(table["context_url"], value_set=downloads)))
    table = table.filter(selected)
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
    # API records and known error endpoints are acquisition inputs. Keep their
    # source role instead of treating endpoint names as document subjects.
    # This does not alter the retained filename, URL, or response status.
    if source_url:
        try:
            url = urlsplit(source_url)
            path = url.path.strip("/").split("/")
            if url.scheme in {"http", "https"}:
                if (url.hostname == "api.govinfo.gov" and len(path) == 3
                        and path[0] == "collections" and re.fullmatch(r'[A-Z]+', path[1])
                        and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', path[2])):
                    return {"source_record_identifier": [path[1]],
                            "source_record_type": ["collection-listing"]}
                if (url.hostname in {"www.govinfo.gov", "govinfo.gov"} and len(path) == 4
                        and path[:2] == ["metadata", "pkg"]
                        and path[3] in {"mods.xml", "premis.xml", "mets.xml"}):
                    return {"source_record_identifier": [path[2]],
                            "source_record_type": [path[3][:-4]], "extension": ["xml"]}
                if (url.hostname == "api.govinfo.gov" and len(path) == 3
                        and path[0] == "packages" and path[2] == filename == "summary"):
                    return {"source_record_identifier": [path[1]],
                            "source_record_type": ["package-summary"]}
                if (path[-1] == filename and (
                    (url.hostname == "docs.house.gov" and url.path == "/committee/Error/Error.aspx")
                    or (url.hostname == "www.govinfo.gov" and url.path == "/error")
                )):
                    return {"source_record_type": ["error-page"],
                            **({"extension": ["aspx"]} if filename == "Error.aspx" else {})}
            if (
                filename and filename.isascii() and filename.isdigit()
                and url.scheme in {"http", "https"}
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
    if filename is None:
        return {}
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
    root, source_rows, *, workers=4, previous=None, metadata=None, read_body=None, cache_store=None, reuse_results=True
):
    """Interpret supplied source rows; acquisition and storage discovery stay outside."""
    started = time.monotonic()
    progress.report('prepare_filename_inputs')
    from congress_api.retention.document_recovery import recover_sources, recovery_fingerprint
    if (root / 'indexes/captures.parquet').exists():
        source_rows = recover_sources(source_rows, pq.ParquetFile(root / 'indexes/captures.parquet'),
            read_receipt=lambda key: (root / key).read_bytes())
        metadata = {**(metadata or {}), 'retained_recovery_fingerprint': recovery_fingerprint()}
    inputs = defaultdict(list)
    bodies, names = set(), set()
    for source in source_rows:
        inputs[(source["filename"], source["source_url"])].append(source)
        if source["body_key"]:
            bodies.add(source["body_key"])
        if source["filename"]:
            names.add(source["filename"])
    fingerprint = parser_fingerprint()
    progress.report('reuse_cached_metadata')
    from congress_api.retention.catalog_cache import LocalStore, load_results, save_results
    cache_store = cache_store or LocalStore(root)
    cached = load_results(cache_store, 'filenames', fingerprint, ('filename', 'source_url'), reuse=reuse_results)
    body_fingerprint = evidence_fingerprint()
    body_cache = load_results(cache_store, 'bodies', body_fingerprint, ('reader', 'body_key'), reuse=reuse_results)
    if reuse_results and previous is not None and (previous.schema.metadata or {}).get(b"body_evidence_fingerprint") == body_fingerprint.encode():
        for batch in previous.select([k for k in (BODY_FIELDS | {"body_key"}) if k in previous.column_names]).to_batches():
            for row in batch.to_pylist():
                if key := body_evidence_key(row):
                    body_cache.setdefault(key, cached_body_fields(row, key))
    source_fields = (
        set(SOURCE_SCHEMA.names) | SOURCE_CONTEXT_FIELDS | {"capture_outcome"}
    )
    if (
        reuse_results and previous is not None
        and "document_kind_source" in previous.column_names
        and (previous.schema.metadata or {}).get(b"house_naming_fingerprint")
        == fingerprint.encode()
    ):
        fields = (
            set(previous.column_names)
            - source_fields
            - {"source_id", "document_id", "format", "document_kind_source"}
            - EVIDENCE_FIELDS
        )
        for batch in previous.to_batches(max_chunksize=4096):
            for row in batch.to_pylist():
                if row.get("filename") is None:
                    continue  # Anonymous bodies share no reusable filename meaning.
                if row.get("recovered_filename") or row.get("body_format") or row.get("cache_marker_state"):
                    continue  # These meanings depend on retained evidence, not just names.
                cached.setdefault((row["filename"], row["source_url"]), {
                    k: row[k] for k in fields if row[k] is not None
                    and not (k == "document_kind"
                             and any(value in DERIVED_KIND_SOURCES for value in row.get("document_kind_source") or []))
                })
    if not reuse_results:
        cached, body_cache = {}, {}
    pending = [key for key in inputs if key not in cached]
    def collect(parsed):
        for key, fields in progress.track(zip(pending, parsed), 'extract_filenames',
                                         total=len(pending), unit='filenames'):
            cached[key] = fields

    try:
        if workers == 1:
            collect(map(extract, pending))
        elif pending:
            with ProcessPoolExecutor(max_workers=workers, mp_context=get_context('spawn')) as pool:
                collect(pool.map(extract, pending, chunksize=128))
    finally:
        # A failed later stage can reuse these completed filename results.
        save_results(cache_store, 'filenames', fingerprint, ('filename', 'source_url'), cached)

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
    progress.report('inspect_document_contents', total=len(bodies), unit='distinct_retained_bodies')
    def interpret(key):
        if key not in cached:
            cached[key] = extract(key)
        return cached[key]
    deferred_bodies = set()
    supplied_reader = read_body or (lambda key: read_retained_body(root, key))
    def inspect_body(key):
        data = supplied_reader(key)
        if data is None:
            deferred_bodies.add(key)
        return data
    try:
        enrich_sources(rows, read_body=inspect_body,
                       extract=interpret, cached=body_cache)
    finally:
        save_results(cache_store, 'bodies', body_fingerprint, ('reader', 'body_key'), body_cache)
        save_results(cache_store, 'filenames', fingerprint, ('filename', 'source_url'), cached)
    progress.report('apply_response_metadata', total=len(rows), unit='source_rows')
    refresh_response_metadata(root, rows)
    for row in rows:
        apply_response_role(row)
    columns.update(key for row in rows for key, value in row.items()
                   if isinstance(value, list) and key not in SOURCE_SCHEMA.names)
    if columns & set(SOURCE_SCHEMA.names):
        raise ValueError("Extracted metadata conflicts with source locator columns")
    schema = pa.schema(
        [*SOURCE_SCHEMA, *[(name, metadata_type(name)) for name in sorted(columns)]],
        metadata={
            "format_version": "5",
            "house_naming_version": __version__,
            "house_naming_fingerprint": fingerprint,
            "body_evidence_fingerprint": body_fingerprint,
            "deferred_body_reads": str(len(deferred_bodies)),
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
    """Reinterpret names and selected retained bodies without discovery or acquisition."""
    source = pq.ParquetFile(root / "indexes/document-filenames.parquet")
    fields = [
        *[name for name in SOURCE_SCHEMA.names if name in source.schema_arrow.names],
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
    return write_filename_metadata(root, rows, workers=workers, previous=source.read(), metadata={
        key.decode(): value.decode() for key, value in (source.schema_arrow.metadata or {}).items()
        if key in {b'raw_capture_rows', b'retained_recovery_fingerprint'}})


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
