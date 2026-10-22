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
document_kind uses filename evidence first, with retained witness-statement
content refining generic testimony. Typed contents or recognized source types
otherwise fill gaps. filename_document_kind preserves the original filename
claim; document_kind_source identifies the selected evidence. Native types stay intact.

Relative hrefs keep their literal spelling. source_resolved_url records only
destinations proved by retained parent anchors; multiple destinations stay
separate during grouping. Unplaced bodies retain their capture file, pointer,
URLs and receipt locator, even when no publisher filename was saved.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from contextlib import ExitStack, contextmanager
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from uuid import uuid4
from email.message import Message
from email.utils import collapse_rfc2231_value
from functools import lru_cache, wraps
import gzip
from io import BytesIO
import json
import pickle
from multiprocessing import get_context
from pathlib import Path
import re
from sys import intern
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
from congress_api.parsers.document_links import feed_link, http_url
from congress_api.parsers.media import youtube_video_id
from congress_api.parsers.document_cover import COVER_FIELDS
from congress_api.parsers.document_types import DOCUMENT_TYPE_MEANINGS, document_type, document_label_kind
from congress_api.retention.catalog_availability import FIELDS as AVAILABILITY_FIELDS, RESOURCE_FIELDS


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
# The grouping policy reads these fields; consumers can keep large retained
# evidence in Arrow while computing exact endpoint/body dependency keys.
GROUP_ALIAS_FIELDS = (
    'filename', 'source_url', 'body_key', 'media_type', 'http_status',
    'source_resolved_url', 'capture_outcome', 'body_format', *RESPONSE_FIELDS,
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
SOURCE_DOCUMENT_KINDS = dict(DOCUMENT_TYPE_MEANINGS)


def restore_filename_kind(row):
    """Restore the filename claim before recomputing content/source choices."""
    if row.get('filename_document_kind'):
        row['document_kind'] = list(row['filename_document_kind'])
    elif any(value in DERIVED_KIND_SOURCES for value in row.get('document_kind_source') or []):
        row['document_kind'] = None
    row['filename_document_kind'] = list(row['document_kind']) if row.get('document_kind') else None
    row.pop('document_kind_source', None)


def fill_document_kind(row):
    """Keep specific forms; expose a supported purpose through the family filter."""
    restore_filename_kind(row)
    if row.get('source_record_type') == ['youtube-video'] and row.get('record_role') != ['document']:
        row['document_kind'] = row['document_kind_source'] = row['document_family'] = None
        return
    context_kind = nomination_support_context(row)
    _select_document_kind(row)
    if context_kind and not row.get('document_kind'):
        row['document_kind'] = [context_kind]
        row['document_kind_source'] = ['source_link_label' if context_kind == 'letter-of-support' else 'source_context']
    row['document_family'] = document_families([
        *(row.get('document_kind') or []), *(['nomination-support'] if context_kind else [])]) or None


def trusted_source_occurrences(row):
    """Only observed links/redirects establish a document's original context."""
    return [o for o in row.get('source_occurrences') or [] if o is not None and not any(
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
        filename_basis = "recovered_filename" if row.get("recovered_filename") else "filename"
        kinds = set(row['document_kind'])
        if 'testimony' in kinds and row.get('content_document_kind') == ['witness-statement']:
            remaining = kinds - {'testimony'}
            row['document_kind'] = sorted(remaining | {'witness-statement'})
            row['document_kind_source'] = sorted(
                ({filename_basis} if remaining else set())
                | ({'content'} if 'witness-statement' not in remaining else set()))
        else:
            row["document_kind_source"] = [filename_basis]
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
        and any(document_type(value) is not None
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
        if (kind := document_type(value))
    }
    row["document_kind"] = sorted(kinds) or None
    row["document_kind_source"] = ["source_document_type"] if kinds else None
    if not kinds and label_kinds:
        row["document_kind"] = sorted(set(label_kinds))
        row["document_kind_source"] = ["source_link_label"]
    if not row['document_kind'] and (kind := publisher_anchor_kind(row)):
        row['document_kind'] = [kind]
        row['document_kind_source'] = ['source_context']


def publisher_anchor_kind(row):
    """Fill a missing kind only when attributable publisher anchors agree.

    Flat unions cannot pair a label with its page or document. Unknown and
    conflicting anchor claims abstain; existing filename/content/types win.
    """
    from congress_api.parsers.senate_page import section_document_kind

    if response_failed(row) or (row.get('record_role') and row['record_role'] != ['document']):
        return None
    claims = []
    source_urls = {http_url(u) for u in (row.get('source_urls') or [row.get('source_url')]) if u}
    source_urls.discard(None)
    for occurrence in trusted_source_occurrences(row):
        if occurrence.get('source_occurrence_scope') != ['anchor']:
            continue
        links = occurrence.get('source_link_url') or []
        if not links:
            continue
        # Older retained anchors predate association-basis metadata. An exact
        # known URL establishes their link; a guessed URL variant never does.
        if not occurrence.get('source_association_basis') and not all(http_url(u) in source_urls for u in links):
            continue
        pages = occurrence.get('source_original_page_url') or []
        if not pages:
            continue
        try:
            urls = [urlsplit(p) for p in pages]
            if not all(u.scheme in {'http','https'} and not u.username and not u.password
                       and (u.hostname or '').endswith(('.house.gov','.senate.gov')) for u in urls):
                continue
        except ValueError:
            continue
        own = {k for label in occurrence.get('source_link_label') or []
               if (k := document_label_kind(label))}
        if len(own) > 1:
            return None
        kind = next(iter(own), None)
        if kind is None:
            headings = occurrence.get('source_link_heading') or []
            kind = document_type(section_document_kind({'headings':headings}))
            if kind is None and len(headings)==1:
                kind = document_label_kind(headings[0])
        claims.append(kind)
    return claims[0] if claims and claims[0] and all(k==claims[0] for k in claims) else None

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


def source_priority_key(row):
    """Canonical tuple ordering key (larger is higher priority) for component representative selection."""
    return (
        source_priority(row),
        row.get("filename") or "",
        row.get("source_url") or "",
        row.get("source_id") or "",
    )


def _invert_utf8_hex(value):
    raw = (value or "").replace("\x00", "").encode("utf-8") + b"\x00"
    return bytes(0xFF - b for b in raw).hex()


def source_priority_rank(row):
    """Deterministic ascending rank string so ``order_by=['priority_rank', 'source_id']`` selects the preferred row first."""
    b0, b1, b2, b3 = source_priority(row)
    flags = f"{int(not b0)}{int(not b1)}{int(not b2)}{int(not b3)}"
    fname = _invert_utf8_hex(row.get("filename") or "")
    url = _invert_utf8_hex(row.get("source_url") or "")
    sid = _invert_utf8_hex(row.get("source_id") or "")
    return f"{flags}:{fname}:{url}:{sid}"


class BipartiteUnionFind:
    """Shared array-backed Union-Find over bipartite (row <-> namespace:alias) edges."""

    def __init__(self, initial_size=0):
        from array import array
        self.parents = array("Q", range(initial_size))
        self._aliases = {}

    def add(self):
        idx = len(self.parents)
        self.parents.append(idx)
        return idx

    def root(self, key):
        parents = self.parents
        visited = []
        while True:
            parent = parents[key]
            if parent == key:
                break
            visited.append(key)
            key = parent
        for item in visited:
            parents[item] = key
        return key

    def union(self, key, target):
        self.parents[self.root(key)] = self.root(target)

    def union_row(self, row_id, row):
        while len(self.parents) <= row_id:
            self.add()
        for alias in group_aliases(row, row_id):
            self.union(row_id, self._aliases.setdefault(alias, row_id))

    def components(self):
        groups, members = {}, []
        for row_id in range(len(self.parents)):
            key = self.root(row_id)
            if key not in groups:
                groups[key] = len(members)
                members.append([])
            members[groups[key]].append(row_id)
        return members


def source_groups(table):
    """Join endpoint variants and identical successful document bodies.

    HTML/error bodies are often shared by unrelated URLs, so they cannot join
    entries by hash. Endpoint grouping still connects a wrapper to its download.
    """
    uf = BipartiteUnionFind(len(table))
    aliases = {}
    fields = GROUP_ALIAS_FIELDS
    for row_id, row in enumerate(table.select(list(dict.fromkeys(
            name for name in fields if name in table.column_names))).to_pylist()):
        for alias in group_aliases(row, row_id):
            uf.union(row_id, aliases.setdefault(alias, row_id))
    groups, members, entry_ids = {}, [], []
    for row_id in range(len(table)):
        key = uf.root(row_id)
        if key not in groups:
            groups[key] = len(members)
            members.append([])
        entry = groups[key]
        entry_ids.append(entry)
        members[entry].append(row_id)
    return entry_ids, members


def source_identity(row):
    """Preserve the catalog's source ID independently of interpretation state."""
    return sha256(compact([row.get(k) for k in ('body_key', 'filename', 'source_url')]).encode()).hexdigest()


def connectable_body_key(row):
    """Return ``body_key`` only when the row is a connectable non-HTML/non-error document body."""
    return document_body(
        row.get("body_key"),
        row.get("media_type"),
        row.get("http_status"),
        row.get("capture_outcome"),
        row.get("body_format"),
        row,
    )


def canonical_key(row, unique_key=None):
    """Return the canonical endpoint grouping key for ``row``."""
    uid = unique_key if unique_key is not None else (row.get("source_id") or source_identity(row))
    endpoint = entry_key(row.get("filename"), row.get("source_url"), uid)
    resolved = row.get("source_resolved_url")
    if (
        endpoint == ("row", uid)
        and row.get("source_url")
        and resolved
        and len(resolved) == 1
    ):
        endpoint = entry_key(row.get("filename"), resolved[0], uid)
    return compact(endpoint)


def compute_document_id(bodies, source_ids):
    """Compute the deterministic SHA-256 document component identifier."""
    sorted_bodies = sorted(set(bodies))
    identity = (
        ["bodies", sorted_bodies]
        if sorted_bodies
        else ["sources", sorted(set(source_ids))]
    )
    return sha256(compact(identity).encode()).hexdigest()


def normalize_source_row(row):
    """Normalize a source row's record role, restored filename kind, source_id, and format."""
    apply_capture_record_role(row)
    restore_filename_kind(row)
    row["source_id"] = source_identity(row)
    row["record_role"] = row.get("record_role") or ["document"]
    row["format"] = (
        None
        if row["record_role"] == ["capture-state"]
        else row.get("body_format") or file_formats(row.get("media_type"), row.get("extension"))
    )
    return row


def group_aliases(row, unique_key):
    """The one maintained endpoint/body policy used by grouping and lookup.

    Isolated relative or missing endpoints use the caller's unique row key.
    Failed or non-document bodies never form content aliases.
    """
    endpoint = entry_key(row.get('filename'), row.get('source_url'), unique_key)
    resolved = row.get('source_resolved_url')
    if (endpoint == ('row', unique_key) and row.get('source_url')
            and resolved and len(resolved) == 1):
        endpoint = entry_key(row.get('filename'), resolved[0], unique_key)
    result = [('endpoint', endpoint)]
    body = connectable_body_key(row)
    if body:
        result.append(('body', body))
    return tuple(result)


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


def combine_document_component(rows_factory, *, working=None, mutate_sources=False):
    """Single shared component combiner used by both resident and disk-staged catalog builds."""
    import pickle

    if callable(rows_factory):
        iter_rows = rows_factory
        materialized = None
    else:
        materialized = list(rows_factory)
        iter_rows = lambda: iter(materialized)

    preferred = None
    values = defaultdict(set)
    filenames, urls, bodies, retained_bodies = set(), set(), set(), set()
    if working is not None:
        occurrences = working.mapping("combined_occurrences")
        occurrences.clear()
    else:
        occurrences = {}
    hearing_resources = []
    filename_kind = False

    for row in iter_rows():
        if preferred is None or source_priority_key(row) > source_priority_key(preferred):
            preferred = row
        for field, value in row.items():
            if isinstance(value, list) and field not in {"source_occurrences", "hearing_resources"}:
                values[field].update(value)
        hearing_resources = merge_values("hearing_resources", hearing_resources, row.get("hearing_resources"))
        for occurrence in row.get("source_occurrences") or []:
            occurrences[compact(occurrence)] = occurrence
        for field, target in (("filename", filenames), ("source_url", urls), ("body_key", retained_bodies)):
            if row.get(field):
                target.add(row[field])
        body = connectable_body_key(row)
        if body:
            bodies.add(body)
        filename_kind |= bool(row.get("document_kind") and not row.get("recovered_filename"))

    if bodies:
        document_id = compute_document_id(bodies, ())
    elif working is not None:
        db = working.connection
        ids = working.mapping("component_source_ids")
        ids.clear()
        for row in iter_rows():
            ids[row["source_id"]] = True
        digest = sha256(b'["sources",[')
        first = True
        for (key,) in db.execute("SELECT key FROM component_source_ids ORDER BY key"):
            if not first:
                digest.update(b",")
            first = False
            digest.update(compact(pickle.loads(key)).encode())
        digest.update(b"]]")
        document_id = digest.hexdigest()
    else:
        document_id = compute_document_id((), (row["source_id"] for row in iter_rows()))

    document = {
        field: preferred.get(field)
        for field in ("source_id", "body_key", "filename", "source_url")
    }
    document.update(
        document_id=document_id,
        filename=display_filename((preferred.get("recovered_filename") or [preferred.get("filename")])[0]),
    )
    document.update({field: merge_values(field, items) for field, items in values.items() if items})
    paired = merge_values("source_occurrences", list(occurrences.values()))
    if paired:
        document["source_occurrences"] = paired
    if hearing_resources:
        document["hearing_resources"] = hearing_resources
    roles = values["record_role"]
    document["record_role"] = [
        next(
            role
            for role in ("document", "source-record", "error-response", "capture-state")
            if role in roles
        )
    ]
    fill_document_kind(document)
    if filename_kind and "recovered_filename" in (document.get("document_kind_source") or []):
        document["document_kind_source"] = sorted(
            {
                "filename" if basis == "recovered_filename" else basis
                for basis in document["document_kind_source"]
            }
        )
    document.update(
        filenames=sorted(filenames) or None,
        source_urls=sorted(urls) or None,
        body_keys=sorted(retained_bodies) or None,
    )
    if mutate_sources and materialized is not None:
        for row in materialized:
            row["document_id"] = document_id
            fill_document_kind(row)
    return document


def prepare_document_indexes(rows, schema):
    """Keep exact source rows and create one canonical row per document group."""
    progress.report('group_documents', total=len(rows), unit='source_rows')
    for name in ("document_kind", "filename_document_kind", "document_kind_source", "document_family", "record_role", "source_record_type"):
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
        normalize_source_row(row)
    grouping_schema = pa.schema([*SOURCE_SCHEMA, ("source_resolved_url", STRINGS),
                                ("capture_outcome", STRINGS), ("body_format", STRINGS)])
    _, groups = source_groups(pa.Table.from_pylist(rows, schema=grouping_schema))
    documents = []
    for members in progress.track(groups, 'combine_document_metadata', unit='document_groups'):
        sources = [rows[i] for i in members]
        document = combine_document_component(sources, working=None, mutate_sources=True)
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


def write_document_indexes(destination, rows, schema, *, working=None, previous=None, previous_documents=None, reuse_groups=True, catalog_id=None, preserve_columns=False, checkpoint_directory=None):
    from congress_api.retention.catalog_staging import write_grouped_indexes, WorkingCatalog
    if working is not None:
        return write_grouped_indexes(destination, rows, schema, working=working,
                                     previous=previous, previous_documents=previous_documents, reuse_groups=reuse_groups, catalog_id=catalog_id, preserve_columns=preserve_columns, checkpoint_directory=checkpoint_directory)
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix="document-working-") as directory:
        state = WorkingCatalog(Path(directory) / "working.sqlite")
        try:
            return write_grouped_indexes(destination, rows, schema, working=state,
                                         previous=previous, previous_documents=previous_documents, reuse_groups=reuse_groups, catalog_id=catalog_id, preserve_columns=preserve_columns, checkpoint_directory=checkpoint_directory)
        finally:
            state.close()


def _legacy_write_document_indexes(destination, rows, schema):
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
        from congress_shared.custody import write_atomic_bytes
        for tmp, (path, _, _) in zip(temporary, outputs):
            write_atomic_bytes(path, tmp.read_bytes(), temp_path=tmp, fsync=False)
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
    from congress_api.retention.catalog_validation import CatalogReferenceCheck
    readers = ExitStack()
    try:
        source_file = readers.enter_context(pq.ParquetFile(source_path))
        document_file = readers.enter_context(pq.ParquetFile(document_path))
        check = CatalogReferenceCheck(source_file.schema_arrow, document_file.schema_arrow)
        if (source_rows is not None and source_file.metadata.num_rows != source_rows
                or document_rows is not None and document_file.metadata.num_rows != document_rows):
            raise ValueError("Document/source index references do not match")
        with check:
            for batch in source_file.iter_batches(columns=['source_id', 'document_id'], batch_size=4096):
                check.add_sources(batch)
            for batch in document_file.iter_batches(columns=['source_id', 'document_id'], batch_size=4096):
                check.add_documents(batch)
            check.finish()
    except BaseException as error:
        try:
            readers.close()
        except BaseException as cleanup:
            error.add_note(f'Catalog validation reader cleanup also failed: {cleanup}')
        raise
    else:
        readers.close()


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def metadata_type(name):
    """Keep source occurrences paired in Arrow, without serializing them as JSON."""
    if name == "source_occurrences":
        return pa.list_(pa.struct([(field, STRINGS) for field in SOURCE_OCCURRENCE_FIELDS]))
    if name == "hearing_resources":
        return pa.list_(pa.struct([(field, pa.string()) for field in RESOURCE_FIELDS]))
    return STRINGS


def merge_values(field, *groups):
    if field == "hearing_resources":
        values = {json.dumps({k: v for k, v in item.items() if v is not None}, sort_keys=True): item
                  for group in groups for item in group or []}
        return [values[key] for key in sorted(values)]
    if field != "source_occurrences":
        return sorted({value for group in groups if group for value in group},
                      key=lambda value: (value is None, value))
    # Arrow fills absent struct fields with null on readback. Normalize those
    # away before deduplication so repeated refreshes do not multiply origins.
    values = {}
    for group in groups:
        for occurrence in group or []:
            if occurrence is None:
                continue  # A nullable struct element has no observed fields.
            normalized = {key: sorted(set(items)) for key, items in occurrence.items() if items}
            if normalized:
                # Shared source observations are values: joins replace lists,
                # they never mutate occurrences. Reuse already normalized ones.
                values[json.dumps(normalized, sort_keys=True)] = occurrence if normalized == occurrence else normalized
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
    if json.loads(row['pointer_json'] or '[]')[:1] == ['archive_members']:
        # The enclosing ZIP is a source locator, not a URL for its member bytes.
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
    if basis in {"retained_path", "archive_member"}:
        entry["source_paths"].add(source)
    for field, values in (metadata or {}).items():
        entry[field].update(values)
    names[(body, filename, url)] = entry


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


class DocumentSources:
    """Interpret supplied parent records; join by exact URL or scoped event ID.

    Original publisher words, parser inferences and collector relationships
    remain separately identified. Occurrences preserve parent/link pairings;
    flat fields are filters, not associations. No filename or shared-host
    matching supplies provenance or document identity.
    """

    def __init__(self, urls=None, *, working=None, observe=None):
        self.observe, self._observation = observe, None
        self.working = working
        self.statistics = Counter()
        self.urls = {http_url(url) or url for url in urls} if urls is not None else None
        self.occurrences = defaultdict(dict)
        self.extra_filters = {}
        self.by_url = SourceFilters(self.occurrences, self.extra_filters)
        self.transfers = defaultdict(list)
        self.meetings = {}
        self.events = defaultdict(set)
        if working is not None:
            self.occurrences = working.occurrence_store()
            self.extra_filters = working.mapping("extra_filters")
            self.transfers = working.mapping("transfers", list)
            self.meetings = working.mapping("meetings")
            self.events = working.mapping("events", set)
            self.by_url = SourceFilters(self.occurrences, self.extra_filters)

    @contextmanager
    def observation(self, receipt):
        """Associate reads and writes without adding locators to inherited facts."""
        previous = self._observation
        keys = (receipt or {}).get('source_receipt_key') or []
        lines = (receipt or {}).get('source_receipt_line') or []
        if self.observe is not None and len(keys) == len(lines) == 1:
            self._observation = dict(receipt_key=next(iter(keys)), receipt_line=int(next(iter(lines))))
        try:
            yield
        finally:
            self._observation = previous

    def _depend(self, kind, value, access):
        if self.observe is not None and self._observation is not None:
            self.observe(dict(self._observation, kind=kind, value=value, access=access))

    def report_statistics(self):
        for name, amount in self.statistics.items():
            progress.advance(name, amount)

    def _sorted_occurrences(self, url):
        observations = self.occurrences.get(url)
        if observations is None:
            return
        self.statistics['context_occurrence_scans'] += 1
        if self.working is None:
            # Readers own their lists; later row merges cannot alter context.
            values = ({field: list(items) for field, items in observations[key].items()}
                      for key in sorted(observations))
        else:
            values = observations.sorted_values()
        for occurrence in values:
            self.statistics['context_occurrence_rows_read'] += 1
            if self.working is not None:
                self.statistics['context_occurrence_decodes'] += 1
            yield occurrence

    def has_source_link(self, url):
        """Test authoritative values without building unrelated aggregate fields."""
        url = (http_url(url) or url) if isinstance(url, str) else url
        if self.extra_filters.get(url, {}).get('source_link_url'):
            return True
        return any(occurrence.get('source_link_url') for occurrence in self._sorted_occurrences(url))

    def add_url(self, url, values):
        with self.observation(values):
            self._add_url(url, values)

    def _add_url(self, url, values):
        if isinstance(url, str):
            url = http_url(url) or url
        if not isinstance(url, str) or not url or self.urls is not None and url not in self.urls:
            return
        if "source_occurrences" in values:
            # Restored flat filters already summarize paired observations. Do
            # not turn that summary into a fabricated cross-product occurrence.
            # Preserve any genuinely unpaired legacy values, but do not cache
            # another full copy of filters derivable from the occurrences.
            paired = {}
            for occurrence in values.get("source_occurrences") or []:
                merge_context(paired, occurrence)
            extra = {key: set(items) - paired.get(key, set())
                     for key, items in values.items()
                     if key in SOURCE_OCCURRENCE_FIELDS and items}
            extra = {key: items for key, items in extra.items() if items}
            if extra:
                filters = self.extra_filters.get(url, {})
                merge_context(filters, extra)
                self.extra_filters[url] = filters
                if self.working is None:
                    self.occurrences.setdefault(url, {})
                else:
                    self.occurrences.ensure(url)
            pending = [(url, occurrence) for occurrence in values.get("source_occurrences") or []]
        else:
            pending = [(url, values)]
        while pending:
            destination, supplied = pending.pop()
            # Parent URLs, titles and receipt locators recur across many links.
            # Share their immutable strings as well as the observation objects.
            occurrence = {key: sorted({intern(item) for item in items}) for key, items in supplied.items()
                          if key in SOURCE_OCCURRENCE_FIELDS and items}
            if not occurrence:
                continue
            self._depend('url', destination, 'write')
            occurrence.setdefault("source_occurrence_scope", ["source_record"])
            # Repeated retained copies of the same observation need one exact
            # representative locator. The captures index retains every receipt.
            identity = sha256(json.dumps({key: items for key, items in occurrence.items()
                if not key.startswith("source_receipt_")}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if self.working is None:
                if identity in self.occurrences[destination]:
                    continue
                self.occurrences[destination][identity] = occurrence
            elif not self.occurrences.insert(destination,identity,occurrence):
                continue
            self.restore_link(occurrence)
            for target, association in self.transfers.get(destination, []):
                # Each transferred occurrence retains its original parent/link.
                # Association fields describe this edge, never document identity.
                pending.append((target, self.transfer_occurrence(occurrence, association)))

    @staticmethod
    def collection_url(url):
        # A feed/sitemap lists unrelated events. Traversing it would turn
        # site navigation into a claimed relationship between those events.
        try:
            return feed_link({}, url) or bool(re.search(
                r'[-_](?:rss|atom|sitemap)\.xml$', urlsplit(url).path, re.I))
        except ValueError:
            return False

    @staticmethod
    def transfer_occurrence(occurrence, association):
        observed = {'publisher_redirect', 'retained_html_link', 'linked_page'}
        if 'linked_page' in association.get('source_association_basis', []):
            pages = occurrence.get('source_original_page_url') or occurrence.get('source_page_url') or []
            if any(DocumentSources.collection_url(url) for url in [*pages, *(occurrence.get('source_link_url') or [])]):
                return {}
        if occurrence.get('source_occurrence_scope') == ['linked_ancestor']:
            # A candidate match cannot establish another step in this path.
            # Redirects retain the same ancestor edge instead of making a new
            # observation for every route through a redirect cycle.
            return (dict(occurrence) if all(basis in observed
                    for basis in association.get('source_association_basis') or []) else {})
        if 'linked_page' in association.get('source_association_basis', []):
            # A link carries its ancestors' page/meeting relationships, never
            # another document's type, author, capture, or body identity.
            if (any(basis not in observed for basis in occurrence.get('source_association_basis') or [])
                    or not occurrence.get('source_link_url') or not any(occurrence.get(key) for key in (
                    'source_original_page_url', 'source_page_url', 'source_meeting_id',
                    'source_meeting_title', 'source_committee_code', 'source_committee_name'))):
                return {}
            result = {key: values for key, values in occurrence.items()
                      if not key.startswith(('source_document_', 'source_witness_',
                          'source_participant_', 'source_label_', 'source_capture_', 'source_probe_'))}
            result['source_occurrence_scope'] = ['linked_ancestor']
            result['source_association_basis'] = sorted(set(result.get('source_association_basis', [])) | {'linked_page'})
            # Keep the original edge and its receipt unchanged. Path-specific
            # values would multiply on every cycle; exact edge identities reach
            # a fixed point even when links arrive in reverse order.
            return result
        result = dict(occurrence)
        for field, values in association.items():
            if field.startswith("source_receipt_") and result.get(field):
                continue  # Keep the original source locator, not a later edge's.
            result[field] = merge_values(field, result.get(field), values)
        return result

    def add_transfer(self, requested, final, values):
        with self.observation(values):
            self._add_transfer(requested, final, values)

    def _add_transfer(self, requested, final, values):
        requested = (http_url(requested) or requested) if isinstance(requested, str) else requested
        final = (http_url(final) or final) if isinstance(final, str) else final
        if not all(isinstance(url, str) and url for url in (requested, final)) or requested == final:
            return
        if ('linked_page' in values.get('source_association_basis', [])
                and any(self.collection_url(url) for url in (requested, final))):
            return
        self._depend('url', requested, 'read')
        self._depend('url', final, 'write')
        association = {key: sorted(items) for key, items in values.items() if items}
        edge = (final, association)
        if any(target == final and {k: v for k, v in previous.items() if not k.startswith("source_receipt_")}
               == {k: v for k, v in association.items() if not k.startswith("source_receipt_")}
               for target, previous in self.transfers[requested]):
            return
        transfers = self.transfers[requested]
        transfers.append(edge)
        self.transfers[requested] = transfers
        observations = self.occurrences.get(requested, {}).values()
        # Resident dictionaries need a snapshot before cycles add entries.
        # The disk iterator captures its insertion limit without loading rows.
        if self.working is None:
            observations = list(observations)
        for occurrence in observations:
            self.add_url(final, self.transfer_occurrence(occurrence, association))

    def restore_association(self, url, occurrence):
        if occurrence.get("source_occurrence_scope") != ["association"]:
            return
        values = {key: value for key, value in occurrence.items()
                  if key in {"source_association_basis", "source_associated_url",
                             "source_receipt_key", "source_receipt_line"}}
        for original in occurrence.get("source_associated_url") or []:
            self.add_transfer(original, url, values)

    def restore_link(self, occurrence):
        """Recover one observed edge; flat lists never establish URL pairings."""
        if occurrence.get('source_occurrence_scope') in (['capture'], ['association'], ['linked_ancestor']):
            return
        if any(basis not in {'publisher_redirect', 'retained_html_link'}
               for basis in occurrence.get('source_association_basis') or []):
            return
        pages = occurrence.get('source_original_page_url') or occurrence.get('source_page_url') or []
        links = occurrence.get('source_link_url') or []
        if len(pages) == len(links) == 1:
            self.add_transfer(pages[0], links[0], {
                **{key: values for key, values in occurrence.items() if key.startswith('source_receipt_')},
                **context_values(source_association_basis='linked_page', source_associated_url=pages[0])})

    def for_url(self, url):
        url = (http_url(url) or url) if isinstance(url, str) else url
        self.statistics['context_result_reads'] += 1
        filters, observations = {}, []
        merge_context(filters, self.extra_filters.get(url, {}))
        for occurrence in self._sorted_occurrences(url):
            merge_context(filters, occurrence)
            observations.append(occurrence)
        result = {key: sorted(values) for key, values in filters.items() if values}
        if observations:
            result['source_occurrences'] = observations
        return result

    @_observed_parent
    def add_link(self, link, receipt=None):
        """Read a native seed or discovered link retained by recurring capture."""
        for occurrence in link.get('publisher_occurrences') or []:
            if not isinstance(occurrence, dict):
                continue
            page, target = http_url(occurrence.get('page') or ''), http_url(occurrence.get('url') or link.get('url') or '')
            if not page or not target:
                continue
            values = context_values(source_page_url=page, source_original_page_url=page,
                source_page_title=occurrence.get('title'), source_page_date=occurrence.get('date'),
                source_page_type=occurrence.get('kind'), source_link_url=target,
                source_link_label=occurrence.get('name'), source_occurrence_scope='anchor')
            merge_context(values, receipt or {})
            self.add_url(target, values)
            self.add_transfer(page, target, {**(receipt or {}), **context_values(
                source_association_basis='linked_page', source_associated_url=page)})
        original = link.get('original_url') if link.get('url_repair') else None
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
            source_link_url=original or link.get("url"),
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
        self.add_url(original or link.get("url"), values)
        if link.get('parent_url'):
            self.add_transfer(link['parent_url'], original or link.get('url'),
                {**(receipt or {}), **context_values(source_association_basis='linked_page',
                                                  source_associated_url=link['parent_url'])})
        if original:
            self.add_transfer(original, link.get('url'), {**(receipt or {}), **context_values(
                source_association_basis=link['url_repair'], source_associated_url=original)})

    def event_context(self, event, chamber=None, congress=None):
        # Absence and ambiguity are dependencies too: later meeting writes can
        # change either result. Broad event IDs cover scoped and unscoped reads.
        if event is not None and str(event):
            self._depend('event', str(event), 'read')
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
        for url, observations in self.occurrences.items():
            snapshot = list(observations.values()) if self.working is None else observations.values()
            for occurrence in snapshot:
                events = occurrence.get('source_meeting_id') or []
                chambers = occurrence.get('source_chamber') or []
                congresses = occurrence.get('source_congress') or []
                if len(events) != 1 or len(chambers) != 1 or len(congresses) > 1:
                    continue
                with self.observation(occurrence):
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

    @_observed_parent
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
        self._depend('event', key[2], 'write')
        events = self.events[key[2]]
        events.add(key)
        self.events[key[2]] = events
        meeting = self.meetings.get(key, {})
        merge_context(meeting, values)
        self.meetings[key] = meeting
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

    @_observed_parent
    def add_senate(self, state, receipt=None, *, read_body=None):
        from congress_api.parsers.senate import parsed
        from congress_api.parsers.senate_page import SITE
        self._add_committee_pages(state, receipt, read_body=read_body, parse_page=lambda raw, url: parsed(raw.decode("utf-8", "replace"), url),
            publishers={host: [code] for code, host in SITE.items()}, chamber='senate')

    @_observed_parent
    def add_house_sites(self, state, receipt=None, *, read_body=None):
        from congress_api.parsers.committee_pages import parse_event_page
        publishers = {host: sorted({row['code'] for row in site.get('committees', [])})
                      for host, site in state.items() if isinstance(site, dict)} if isinstance(state, dict) else {}
        self._add_committee_pages(state, receipt, read_body=read_body, parse_page=parse_event_page,
                                  publishers=publishers, chamber='house')

    def _add_committee_pages(self, state, receipt, *, read_body, parse_page, publishers, chamber):
        from congress_api.parsers.senate_page import document_context
        if not isinstance(state, dict):
            return
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
                        page = {**page, **parse_page(raw, url)}
                        metadata_by_url = page.get("document_metadata") or {}
                        event = page.get("event") or event
                context = context_values(
                    source_page_url=url,
                    source_original_page_url=url,
                    source_page_title=page.get("title"),
                    source_page_date=event.get("date"),
                    source_page_type=event.get("type"),
                    source_page_sha256=digest,
                )
                merge_context(context, {"source_publisher_committee_code": publishers.get(host.removeprefix("www."), [])})
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
                                f"{chamber}_parser_fallback" if kind == "other" else f"{chamber}_parser_inference",
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

    @_observed_parent
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

    @_observed_parent
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
                    source_page_url=group.get("source_url"),
                    source_page_sha256=group.get("source_sha256"),
                    source_link_url=file.get("url"), source_capture_pointer=file.get("selector"),
                    source_document_group=group.get("source"), source_witness_name=witness.get("name"),
                    source_document_type=group.get("type") or group.get("legacy_kind"),
                    source_document_type_basis="publisher" if group.get("type") else
                        "house_parser_inference" if group.get("legacy_kind") else None,
                    source_document_label=group.get("description"), source_document_format=file.get("format"),
                    source_document_added_at=attributes.get("add-date"),
                    source_document_published_at=attributes.get("publish-date"))})

    @_observed_parent
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

    @_observed_parent
    def add_redirect(self, record, receipt=None):
        """Transfer observed relationships, including failed responses, not identity."""
        if not isinstance(record, dict):
            return
        requested = record.get("requested_url") or record.get("url")
        final = record.get("final_url") or (record.get("url") if record.get("requested_url") else None)
        if type(record.get("http_status")) is int and requested and final and requested != final:
            self.add_transfer(requested, final, {**(receipt or {}), **context_values(
                source_association_basis="publisher_redirect", source_associated_url=requested)})

    @_observed_parent
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


def capture_schema(captures):
    return captures.schema_arrow if isinstance(captures, pq.ParquetFile) else captures.schema


def capture_batches(captures, columns=None):
    """Repeat a selected receipt input without collecting all capture payloads.

    Native replay writes one already bounded raw batch per Parquet row group.
    Read each group separately so the row-count API cannot combine many wide
    native batches into a larger decoded allocation.
    """
    if isinstance(captures, pq.ParquetFile):
        for group in range(captures.num_row_groups):
            yield from captures.iter_batches(columns=columns, row_groups=[group], batch_size=256)
    else:
        yield from (captures.select(columns) if columns is not None else captures).to_batches(max_chunksize=256)


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
            continue  # This exact page observation was already replayed above.
        identity = url, key, host
        receipts = observations.get(identity, set())
        receipts.add((row['receipt_key'], row['receipt_line']))
        observations[identity] = receipts
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
    """Read capture outcomes, URL states, and response metadata directly from raw_archive tables.

    Prefers ``fetch_outcomes``, ``captures``, and ``state`` tables (or a ``RawSnapshot``)
    and falls back to scanning ``.jsonl.gz`` receipt files only when bootstrapping
    without a table store.
    """
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

    # Fallback: bootstrap from raw .jsonl.gz receipt files only when no table store exists.
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
                    records.append((row['receipt_key'],row['receipt_line'],position,pickle.dumps(row)))
                    position += 1
                db.executemany('INSERT INTO positions VALUES (?,?,?,?)',records)
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
                    remaining, = db.execute('SELECT count(*) FROM positions WHERE receipt=?',(key,)).fetchone()
                    with gzip.open(BytesIO(payload),"rt",encoding="utf-8") as stream:
                        for number,line in enumerate(stream,1):
                            rows = [pickle.loads(value) for value, in db.execute(
                                'SELECT value FROM positions WHERE receipt=? AND line=? ORDER BY position',(key,number))]
                            if rows:
                                yield json.loads(line)['record'],rows,context_values(source_receipt_key=key,source_receipt_line=number)
                                completed += len(rows)
                                remaining -= len(rows)
                                if completed-reported >= 1000:
                                    progress.report(stage,completed=completed,total=total,unit='capture_rows')
                                    reported = completed
                            if not remaining:
                                break
                    if remaining:
                        raise ValueError(f"Capture index references missing receipt lines: {key}")
        finally:
            db.close()
    progress.report(stage,completed=completed,total=total,unit='capture_rows')


def add_retained_house_documents(context, captures, read_body):
    """Replay publisher XML through the existing House parser, with exact locators."""
    from congress_api.parsers.house_evidence import retained_evidence
    from congress_api.parsers.xml import parse_xml
    from xml.etree.ElementTree import ParseError

    rows = (row for table in _capture_tables(captures)
            for row in table.filter(pc.is_in(table['family'], value_set=pa.array(
                ['house/meeting-xml', 'house/witness-xml']))).to_pylist())
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
    # Parent pages also supply context for inventory links. Retain page entries
    # even when the caller only needs linked document URLs.
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
    # Download receipts can refer to an HTML landing page whose exact anchor
    # supplies the later requested URL. Read only those retained page bodies.
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
    """A saved HTML response is a source page when that page was recorded for its URL.

    A hearing path alone does not qualify. The file URL must be one recorded
    source page, and the recorded title or meeting type must name the page.
    """
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


def refresh_response_metadata(root, rows, *, captures=None, fetch_outcomes=None, states=None, read_receipt=None):
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
                o.get("source_occurrence_scope") == ["capture"] for o in row["source_occurrences"]
            ):
                unplaced.add(id(row))
    if not targets:
        return
    required = {"body_key", "receipt_key", "receipt_line", "pointer_json", "context_url"}
    if not required <= schema_names:
        return
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
            u = srow.get("url") or srow.get("context_url")
            if u:
                state_by_url[u] = srow
    references = defaultdict(lambda: defaultdict(list))
    bodies = pa.array(sorted({key[0] for key in targets}), type=pa.string())
    optional_cols = {
        "family", "source_file", "original_path", "media_type", "http_status",
        "resolution", "outcome", "fidelity", "record_json", "usable", "body_complete",
        "complete", "format", "result",
    }
    columns = required | (optional_cols & schema_names)
    batches = (
        archive.iter_batches(columns=sorted(columns))
        if isinstance(archive, pq.ParquetFile)
        else capture_batches(archive, sorted(columns))
    )
    for batch in batches:
        selected = pa.Table.from_batches([batch])
        selected = selected.filter(pc.is_in(pc.cast(selected["body_key"], pa.string()), value_set=bodies))
        for capture in selected.to_pylist():
            references[capture["receipt_key"]][capture["receipt_line"]].append(capture)

    def _apply_capture_facts(receipt, number, capture, record):
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

    table_only = fetch_outcomes is not None or states is not None
    for receipt, lines in sorted(references.items()):
        receipt_path = (root_path / receipt) if root_path is not None else None
        can_read_gz = (
            not table_only
            and (read_receipt is not None or (receipt_path is not None and receipt_path.exists()))
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
            raise ValueError(f"Response index references missing receipt lines: {receipt}")


def refresh_source_metadata(root, context=None):
    """Refresh source facts from one captured selected pair, then publish together."""
    from tempfile import TemporaryDirectory
    from congress_api.retention.catalog_staging import WorkingCatalog
    from congress_api.retention.catalog_cache import LocalStore
    from congress_api.retention.catalog_publication import read_catalog
    with read_catalog(LocalStore(root)) as snapshot, TemporaryDirectory(prefix="source-refresh-") as directory:
        if snapshot.filenames_path is None:
            raise ValueError("Missing filename index")
        working = WorkingCatalog(Path(directory) / "working.sqlite")
        try:
            staged = Path(directory) / "output"
            (staged / "indexes").mkdir(parents=True)
            return _refresh_source_metadata(root, context, working=working,snapshot=snapshot, output_root=staged)
        finally:
            working.close()


def _refresh_source_metadata(root, context, *, working, snapshot, output_root):
    """Refresh retained provenance and response facts, then regroup without parsing names."""
    from congress_api.retention.catalog_staging import DiskRows
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
    for batch in rows.batches(write=True):
        refresh_response_metadata(root, [row for _, row in batch])
    columns.update(field for row in rows for field in row
                   if field in SOURCE_CONTEXT_FIELDS | set(RESPONSE_FIELDS) | {"source_record_type"})
    # Response roles depend on newly read facts, not another body download.
    for batch in rows.batches(write=True):
        for _, row in batch:
            apply_response_role(row)
    body_cache = working.mapping("source_refresh_bodies")
    for batch in rows.batches(write=True):
        enrich_document_covers([row for _, row in batch], read_body=lambda key: read_retained_body(root, key), cached=body_cache)
    columns.update(field for field in (*COVER_FIELDS, 'body_format')
                   if any(row.get(field) for row in rows))
    schema = pa.schema(
        [
            *[f for f in source.schema_arrow if f.name not in SOURCE_CONTEXT_FIELDS | columns],
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

    return publish_local_result(root,path,result,snapshot)


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
        downloads = pa.array(sorted({url for url in urls if url and source_family(url=url) == "documents"}),
                             type=pa.string())
        selected = pc.or_(selected, pc.and_(pages, pc.is_in(table["context_url"], value_set=downloads)))
    table = table.filter(selected)
    bodies = set()
    names = {} if working is None else working.mapping("inventory_names")
    for record,rows,_ in retained_records(table,lambda key:(root / key).read_bytes()):
        for row in rows:
            if row['body_key']:
                bodies.add(row['body_key'])
                metadata = response_metadata(row,record)
                for filename,basis,url,source in source_names(row,record) or [(None,None,None,None)]:
                    add_name(names,row['body_key'],filename,url,basis,source,metadata)
            elif row['context_url']:
                for filename,basis in url_document_names(row['context_url']):
                    add_name(names,None,filename,row['context_url'],basis)
        if any(row['body_key'] is None for row in rows):
            for filename,basis,url in inventory_names(record):
                add_name(names,None,filename,url,basis)

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
    by_url = defaultdict(set) if working is None else working.mapping("inventory_urls", set)
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
    captured_pairs = defaultdict(set) if working is None else working.mapping("inventory_pairs", set)
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
                names[(body,filename,url)] = entry
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


def validated_body_readings(readings):
    """Accept only explicit completed PDF readings, keyed by immutable body identity.

    Callers qualify the body hash and reading provenance before choosing these
    overrides. Normal updates never select a newer reading automatically.
    """
    from congress_api.retention.capture_metadata import RESULT_COLUMNS
    from congress_api.retention.body_keys import body_key_digest
    selected = {}
    for row in readings:
        if not isinstance(row, Mapping):
            raise ValueError('Expected an explicit completed PDF body reading')
        key = row.get('body_key', '')
        fingerprint = row.get('parser_fingerprint')
        if not isinstance(key, str) or not isinstance(fingerprint, str):
            raise ValueError('Expected body identity and parser fingerprint strings')
        if (body_key_digest(key) is None or key in selected
                or row.get('status') != 'completed' or row.get('error_type') is not None
                or row.get('body_format') != ['pdf']
                or not re.fullmatch(r'[a-f0-9]{64}', fingerprint)
                or set(row) - set(RESULT_COLUMNS) - BODY_FIELDS
                or any(value is not None and (not isinstance(value, list)
                                             or any(not isinstance(v, str) for v in value))
                       for name, value in row.items() if name in BODY_FIELDS)):
            raise ValueError('Expected distinct qualified completed PDF body readings')
        selected[key] = dict(row)
    return selected


def write_filename_metadata(
    root, source_rows, *, workers=4, previous=None, metadata=None, read_body=None,
    oversized_bodies=(), cache_store=None, reuse_results=True, inspect_bodies=False, working=None, previous_documents=None, publication_snapshot=None, output_root=None,
    body_readings=(), retained_body_readings=None,
):
    """Interpret supplied source rows; optional body readings are explicit overrides."""
    body_readings = validated_body_readings(body_readings)
    if working is None:
        from tempfile import TemporaryDirectory
        from congress_api.retention.catalog_staging import WorkingCatalog
        with TemporaryDirectory(prefix="filename-working-") as directory, ExitStack() as owners:
            working = WorkingCatalog(Path(directory) / "working.sqlite")
            try:
                from congress_api.retention.catalog_cache import LocalStore
                from congress_api.retention.catalog_publication import read_catalog
                local_store = LocalStore(root)
                snapshot = publication_snapshot or owners.enter_context(read_catalog(local_store))
                staged = Path(directory) / "output"
                (staged / "indexes").mkdir(parents=True)
                result = write_filename_metadata(root, source_rows, workers=workers, previous=previous,
                    metadata=metadata, read_body=read_body, oversized_bodies=oversized_bodies,
                    cache_store=cache_store, reuse_results=reuse_results,
                    inspect_bodies=inspect_bodies, working=working, previous_documents=previous_documents, output_root=staged,
                    body_readings=body_readings.values(), retained_body_readings=retained_body_readings)
                return publish_local_result(root, staged / "indexes/document-filenames.parquet", result, snapshot)
            finally:
                working.close()
    started = time.monotonic()
    previous_schema = (previous.schema_arrow if isinstance(previous, pq.ParquetFile) else previous.schema) if previous is not None else None
    def previous_batches(columns=None):
        if isinstance(previous, pq.ParquetFile):
            return previous.iter_batches(columns=columns, batch_size=256, use_threads=False)
        return (previous.select(columns) if columns else previous).to_batches(max_chunksize=256)
    progress.report('prepare_filename_inputs')
    from congress_api.retention.document_recovery import recover_sources, recovery_fingerprint
    if (root / 'indexes/captures.parquet').exists():
        source_rows = recover_sources(source_rows, pq.ParquetFile(root / 'indexes/captures.parquet'),
            read_receipt=lambda key: (root / key).read_bytes(), working=working)
        metadata = {**(metadata or {}), 'retained_recovery_fingerprint': recovery_fingerprint()}
    from congress_api.retention.catalog_staging import ParquetRows
    inputs = working.mapping("filename_inputs")
    def row_schema(columns):
        return pa.schema([(name, SOURCE_SCHEMA.field(name).type if name in SOURCE_SCHEMA.names
                           else metadata_type(name)) for name in columns])
    rows = ParquetRows((output_root or root) / "filename-rows", row_schema)
    bodies, names = working.mapping("filename_bodies"), working.mapping("filename_names")
    fingerprint = parser_fingerprint()
    progress.report('reuse_cached_metadata')
    from congress_api.retention.catalog_cache import LocalStore, result_checkpoint
    cache_store = cache_store or LocalStore(root)
    cached = working.mapping("filename_results")
    body_fingerprint = evidence_fingerprint()
    if not inspect_bodies and previous_schema is not None:
        # A metadata-only update preserves earlier content readings. Replacing
        # their reader version without actually reading the files loses evidence.
        body_fingerprint = (previous_schema.metadata or {}).get(
            b'body_evidence_fingerprint', body_fingerprint.encode()).decode()
    reuse_bodies = reuse_results or not inspect_bodies
    body_cache = working.mapping("body_results")
    payload = cache_store.read("indexes/processing/bodies.parquet") if reuse_results and retained_body_readings is None else None
    if payload:
        cached_file = pq.ParquetFile(pa.BufferReader(payload))
        for batch in cached_file.iter_batches(batch_size=4096):
            for row in batch.to_pylist():
                key = (row.pop("reader"), row.pop("body_key"))
                body_cache[key] = {field: value for field, value in row.items() if value is not None}
    del payload
    selected_capture_readings = working.mapping("selected_capture_readings")
    if retained_body_readings is not None:
        from congress_api.retention.capture_metadata import restore_readings
        for reading in retained_body_readings:
            if reading.get('reader') is not None:
                # Legacy per-reader results precede old catalog fields, including
                # completed negative readings. Capture facts fill remaining gaps.
                restore_readings((reading,), body_cache)
            else:
                selected_capture_readings.setdefault(reading['body_key'], reading)
    source_fields = set(SOURCE_SCHEMA.names) | SOURCE_CONTEXT_FIELDS | AVAILABILITY_FIELDS | {'capture_outcome'}
    reuse_names = previous is not None and reuse_results and 'document_kind_source' in previous_schema.names
    filename_fields = (set(previous_schema.names) - source_fields
                       - {'source_id', 'document_id', 'format', 'document_kind_source'}
                       - EVIDENCE_FIELDS - BODY_FIELDS) if reuse_names else set()
    if previous is not None and (reuse_names or reuse_bodies):
        selected = (filename_fields | {'filename', 'source_url', 'recovered_filename', 'document_kind_source'}
                    if reuse_names else set())
        if reuse_bodies:
            selected |= BODY_FIELDS | {'body_key'}
        # Restore filename and body results together from one projected scan.
        for batch in previous_batches(sorted(selected & set(previous_schema.names))):
            for row in batch.to_pylist():
                if reuse_bodies and (key := body_evidence_key(row)):
                    body_cache.setdefault(key, cached_body_fields(row, key))
                if not reuse_names or row.get('filename') is None or row.get('recovered_filename'):
                    continue  # Recovered names depend on the current URL evidence.
                restore_filename_kind(row)
                cached.setdefault((row['filename'], row['source_url']), {
                    key: row[key] for key in filename_fields if row[key] is not None
                })
    if retained_body_readings is not None:
        from congress_api.retention.capture_metadata import restore_readings
        restore_readings(selected_capture_readings.values(), body_cache)
    elif reuse_results:
        # Capture already inspected these bytes before releasing them. Preserve
        # published/legacy readings first, then admit newly completed results.
        from congress_api.retention.capture_metadata import restore_body_results
        restore_body_results(cache_store, body_cache)
    for key, reading in body_readings.items():
        fields = {name: value for name, value in reading.items()
                  if name in BODY_FIELDS and value is not None}
        # Replace just these explicitly chosen results, including a deliberate
        # empty cover. Do not let old XML facts or an earlier citation resurface.
        body_cache[('xml', key)] = {}
        body_cache[('document', key)] = {name: value for name, value in fields.items()
                                       if name not in COVER_FIELDS}
        body_cache[('cover', key)] = {name: value for name, value in fields.items()
                                    if name in COVER_FIELDS}
    checkpoint_bodies = (result_checkpoint(cache_store, 'bodies', body_fingerprint,
                                         ('reader', 'body_key'), body_cache)
                         if retained_body_readings is None else lambda **kwargs: None)
    columns = set()
    pending_count = 0
    progress.report('inspect_document_contents', completed=0, unit='distinct_body_attempts')
    def interpret(key):
        if key not in cached:
            cached[key] = extract(key)
        return cached[key]
    deferred_bodies = working.mapping("deferred_bodies")
    attempted_bodies = working.mapping("attempted_bodies")
    supplied_reader = read_body or (lambda key: read_retained_body(root, key))
    def inspect_body(key):
        if not inspect_bodies:
            return None
        checkpoint_bodies()
        if key in oversized_bodies or key in deferred_bodies:
            return None  # Missing bytes retry next run; known size limits stay skipped.
        data = supplied_reader(key)
        if data is None:
            deferred_bodies[key] = True
        attempted_bodies[key] = True
        progress.report('inspect_document_contents', completed=len(attempted_bodies), unit='distinct_body_attempts')
        return data
    recovered_urls = working.mapping("recovered_urls", set)
    shared_body_fields = working.mapping("shared_body_fields")
    from contextlib import nullcontext
    from itertools import islice
    executor = (ProcessPoolExecutor(max_workers=workers, mp_context=get_context('spawn'))
                if workers > 1 else nullcontext())
    try:
        # Discover shared facts while consuming the source stream. Keep a single
        # immutable spool: later aliases may supply evidence to earlier rows.
        with executor as pool:
            source_rows = iter(source_rows)
            while records := list(islice(source_rows, 256)):
                records = [dict(row) for row in records]
                keys = list(dict.fromkeys((row['filename'], row['source_url']) for row in records))
                pending = [key for key in keys if key not in cached]
                parsed = pool.map(extract, pending, chunksize=128) if pool is not None else map(extract, pending)
                for key, fields in zip(pending, parsed):
                    cached[key] = fields
                pending_count += len(pending)
                for row in records:
                    if row.get('body_key') in body_readings:
                        for name in BODY_FIELDS:
                            row.pop(name, None)
                    key = (row['filename'], row['source_url'])
                    inputs[key] = True
                    fields = cached[key]
                    columns.update(fields)
                    row.update(fields)
                    columns.update(key for key, value in row.items()
                                   if key in SOURCE_CONTEXT_FIELDS | AVAILABILITY_FIELDS
                                   | {'capture_outcome', 'record_role', 'source_record_type', 'source_record_identifier'} and value)
                    if row['body_key']:
                        bodies[row['body_key']] = True
                    if row['filename']:
                        names[row['filename']] = True
                enrich_sources(records, read_body=inspect_body, extract=interpret,
                               cached=body_cache, urls=recovered_urls,
                               shared_body_fields=shared_body_fields)
                for row in records:
                    fill_document_kind(row)
                enrich_document_covers(records, read_body=inspect_body, cached=body_cache)
                for row in records:
                    rows.append(row)
                progress.report('extract_filenames', completed=pending_count, unit='filenames')
        # These source/recovery pages have been consumed. The spool is the only
        # remaining row stream; caches contain shared facts, not duplicate rows.
        del source_rows
        for name in ('recovery_result', 'recovery_rows'):
            working.connection.execute(f'DROP TABLE IF EXISTS {name}')
    finally:
        if inspect_bodies:
            checkpoint_bodies(force=True)
    input_count = len(inputs)
    if any(key not in bodies for key in body_readings):
        raise ValueError('Selected PDF reading has no supplied retained source row')
    if body_readings and not inspect_bodies:
        # Explicit empty covers must survive future ordinary updates; otherwise
        # old immutable capture readings could repopulate a cleared citation.
        checkpoint_bodies(force=True)
    rows_without_body = 0
    reading_provenance = json.loads((previous_schema.metadata or {}).get(
        b'body_reading_overrides', b'{}')) if previous_schema is not None and reuse_bodies else {}
    reading_provenance.update({key: row['parser_fingerprint'] for key, row in body_readings.items()})

    def finalized_rows():
        nonlocal rows_without_body
        progress.report('finalize_metadata', completed=0, total=len(rows), unit='source_rows')
        completed = 0
        for records in rows.batches():
            enrich_sources(records, read_body=lambda key: None, extract=interpret,
                           cached=body_cache, urls=recovered_urls, initialize_roles=False,
                           shared_body_fields=shared_body_fields)
            enrich_document_covers(records, read_body=lambda key: None, cached=body_cache)
            refresh_response_metadata(root, records)
            for row in records:
                apply_response_role(row)
                columns.update(key for key, value in row.items()
                               if isinstance(value, list) and key not in SOURCE_SCHEMA.names)
                if row['body_key'] and row['body_key'] not in bodies:
                    raise ValueError('Filename table does not cover every selected retained body')
                if row['filename'] and row['filename'] not in names:
                    raise ValueError('Filename table does not cover every known spelling')
                rows_without_body += row['body_key'] is None
                yield row
            completed += len(records)
            progress.report('finalize_metadata', completed=completed, total=len(rows), unit='source_rows')
        cached.clear()
        body_cache.clear()
        selected_capture_readings.clear()
        shared_body_fields.clear()

    def output_schema():
        if columns & set(SOURCE_SCHEMA.names):
            raise ValueError("Extracted metadata conflicts with source locator columns")
        return pa.schema(
            [*SOURCE_SCHEMA, *[(name, metadata_type(name)) for name in sorted(columns)]],
            metadata={
                "format_version": "5",
                "house_naming_version": __version__,
                "house_naming_fingerprint": fingerprint,
                "body_evidence_fingerprint": body_fingerprint,
                "deferred_body_reads": str(len(deferred_bodies)),
                "body_inspection": str(inspect_bodies).lower(),
                **(metadata or {}),
                **({'body_reading_overrides': json.dumps(reading_provenance, sort_keys=True)}
                   if reading_provenance else {}),
            },
        )
    destination = (output_root or root) / "indexes/document-filenames.parquet"
    document_stats = write_document_indexes(destination, finalized_rows(), output_schema, working=working, previous=previous, previous_documents=previous_documents, reuse_groups=reuse_results)
    from congress_api.retention.catalog_validation import CatalogBuildResult
    return CatalogBuildResult(
        rows=len(rows),
        **document_stats,
        distinct_bodies=len(bodies),
        distinct_filenames=len(names),
        rows_without_retained_body=rows_without_body,
        parser_inputs=input_count,
        parsed_inputs=pending_count,
        **({'refreshed_body_readings': len(body_readings)} if body_readings else {}),
        output=str(destination),
        output_bytes=destination.stat().st_size,
        elapsed_seconds=round(time.monotonic() - started),
        validation=getattr(document_stats, 'validation', None),
    )


def build(root, inventory_dir, *, workers=4, families=FAMILIES, inspect_bodies=False):
    from tempfile import TemporaryDirectory
    from congress_api.retention.catalog_staging import WorkingCatalog
    from congress_api.retention.catalog_cache import LocalStore
    from congress_api.retention.catalog_publication import read_catalog
    store = LocalStore(root)
    with read_catalog(store) as snapshot, TemporaryDirectory(prefix="inventory-working-") as directory:
        working = WorkingCatalog(Path(directory) / "working.sqlite")
        try:
            staged = Path(directory) / "output"
            (staged / "indexes").mkdir(parents=True)
            result = _build(root,inventory_dir,workers=workers,families=families,
                            inspect_bodies=inspect_bodies,working=working,output_root=staged)
            return publish_local_result(root,staged / "indexes/document-filenames.parquet",result,snapshot)
        finally:
            working.close()


def _build(root, inventory_dir, *, workers, families, inspect_bodies, working, output_root):
    names, capture_rows, bodies, known_variants = collect_names(
        root, inventory_dir, families, working=working
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
    context = read_document_sources(root,context=DocumentSources(working=working))
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
        write_filename_metadata(root, sources, workers=workers, inspect_bodies=inspect_bodies, working=working, output_root=output_root),
        capture_rows=capture_rows,
        known_inventory_spellings=len(known_variants),
    )


def filename_refresh_inputs(source):
    """Stream retained source evidence separately from filename interpretations.

    Callers pass the original table as previous= when writing so retained body
    readings survive. This helper does not read bodies or change the catalog.
    """
    fields = [
        *[name for name in SOURCE_SCHEMA.names if name in source.schema_arrow.names],
        *sorted(
            (SOURCE_CONTEXT_FIELDS | AVAILABILITY_FIELDS
             | {"capture_outcome", "record_role", "source_record_type", "source_record_identifier"})
            & set(source.schema_arrow.names)
        ),
    ]
    rows = (
        row
        for batch in source.iter_batches(columns=fields)
        for row in batch.to_pylist()
    )
    metadata = {
        key.decode(): value.decode() for key, value in (source.schema_arrow.metadata or {}).items()
        if key in {b'raw_capture_rows', b'capture_digest', b'seed_digest', b'deferred_source_bodies', b'source_lineage_version',
                   b'source_lineage_overlay', b'download_state_digest', b'download_state_rows', b'availability_policy',
                   b'source_fingerprint', b'retained_recovery_fingerprint'}}
    return rows, metadata


def refresh_filename_metadata(root, *, workers=4, inspect_bodies=False, repair=False):
    """Reuse saved interpretations unless explicitly rebuilding; never acquire sources."""
    from congress_api.retention.catalog_cache import LocalStore
    from congress_api.retention.catalog_publication import read_catalog
    with read_catalog(LocalStore(root)) as snapshot:
        if snapshot.filenames_path is None:
            raise ValueError("Missing filename index")
        source = pq.ParquetFile(snapshot.filenames_path)
        rows, metadata = filename_refresh_inputs(source)
        return write_filename_metadata(root, rows, workers=workers, previous=source, reuse_results=not repair,
            inspect_bodies=inspect_bodies, publication_snapshot=snapshot, previous_documents=pq.ParquetFile(snapshot.documents_path) if snapshot.documents_path else None, metadata=metadata)


def reindex_documents(root):
    """Refresh grouping from one input snapshot and stage its complete replacement."""
    from tempfile import TemporaryDirectory
    from congress_api.retention.catalog_cache import LocalStore
    from congress_api.retention.catalog_publication import read_catalog
    with read_catalog(LocalStore(root)) as snapshot:
        if snapshot.filenames_path is None:
            raise ValueError("Missing filename index")
        source = pq.ParquetFile(snapshot.filenames_path)
        rows = ({key:value for key,value in row.items() if value is not None}
                for batch in source.iter_batches(batch_size=4096) for row in batch.to_pylist())
        with TemporaryDirectory(prefix="document-reindex-") as directory:
            path = Path(directory) / "document-filenames.parquet"
            result = dict(rows=source.metadata.num_rows, **write_document_indexes(path,rows,source.schema_arrow))
            return publish_local_result(root,path,result,snapshot)


def publish_local_result(root, filename_path, result, snapshot):
    """Select staged files and return durable selected paths, preserving legacy roots."""
    from congress_api.retention.catalog_cache import LocalStore
    from congress_api.retention.catalog_publication import publish_catalog
    selected = publish_catalog(LocalStore(root), filename_path, filename_path.with_name("documents.parquet"),
                               previous=snapshot, validation=getattr(result, 'validation', None))
    return {**result, **selected, "output":str(root / selected['filenames_key']),
            "documents_output":str(root / selected['documents_key'])}
