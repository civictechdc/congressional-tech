"""Schema definitions, field sets, and kind mapping helpers for document indexing."""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit

import pyarrow as pa

from house_naming import Engine, document_families
from house_naming.errors import NamingError
from house_naming.extraction import QUERY
from congress_api.retention.document_evidence import (
    FIELDS as EVIDENCE_FIELDS, BODY_FIELDS, response_failed,
)
from congress_api.parsers.document_cover import COVER_FIELDS
from congress_api.parsers.document_links import http_url
from congress_api.parsers.document_types import DOCUMENT_TYPE_MEANINGS, document_type, document_label_kind

STATE_FIELDS = frozenset({'state_outcome', 'state_body_key', 'state_checked_at',
                          'state_retrieved_at', 'state_family'})
AVAILABILITY_FIELDS = STATE_FIELDS | {'hearing_package_id', 'hearing_resources'}
RESOURCE_FIELDS = ('package_id', 'url', 'body_key', 'format', 'outcome',
                   'association_basis', 'api_response_body_key', 'publisher_format_url')


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
DOCUMENT_KINDS = SOURCE_DOCUMENT_KINDS

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


def file_formats(media_types, extensions):
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


def extract(item):
    global ENGINE
    if ENGINE is None:
        ENGINE = Engine()
    filename, source_url = item
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
            result = ENGINE.extract(filename)
    except NamingError:
        return {}  # Keep the file/name row even when no metadata was extracted.
    return result["metadata"]
