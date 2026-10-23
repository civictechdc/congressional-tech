"""Bipartite graph Union-Find, endpoint aliases, and document component combination."""
from __future__ import annotations

from array import array
from collections import defaultdict
from hashlib import sha256
import pickle
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from house_naming.extraction import QUERY
from congress_api.parsers.document_links import http_url
from congress_api.retention.document_evidence import response_failed
from congress_api.retention.index.schemas import (
    EMPTY_BODY_DIGEST, GROUP_ALIAS_FIELDS, MEDIA_FORMATS, compact, display_filename,
    file_formats, fill_document_kind, merge_values, restore_filename_kind,
)
from congress_api.retention.index.sources import apply_capture_record_role


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
    """Deterministic ascending rank string so order_by=['priority_rank', 'source_id'] selects preferred row first."""
    b0, b1, b2, b3 = source_priority(row)
    flags = f"{int(not b0)}{int(not b1)}{int(not b2)}{int(not b3)}"
    fname = _invert_utf8_hex(row.get("filename") or "")
    url = _invert_utf8_hex(row.get("source_url") or "")
    sid = _invert_utf8_hex(row.get("source_id") or "")
    return f"{flags}:{fname}:{url}:{sid}"


class BipartiteUnionFind:
    """Shared array-backed Union-Find over bipartite (row <-> namespace:alias) edges."""

    def __init__(self, initial_size=0):
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
    """Join endpoint variants and identical successful document bodies."""
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
    """Return body_key only when the row is a connectable non-HTML/non-error document body."""
    return document_body(
        row.get("body_key"),
        row.get("media_type"),
        row.get("http_status"),
        row.get("capture_outcome"),
        row.get("body_format"),
        row,
    )


def canonical_key(row, unique_key=None):
    """Return the canonical endpoint grouping key for row."""
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
    """The one maintained endpoint/body policy used by grouping and lookup."""
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
