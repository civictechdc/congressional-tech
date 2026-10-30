"""Content-addressed bodies, immutable receipts, and coherent native selection.

The caller supplies configured native storage. Bodies precede immutable receipts;
one conditional raw selector publishes exact completed capture and state pins.
Unselected receipts recover interrupted acquisition without refetching. Legacy
snapshot reading and exact adoption remain separate explicit boundaries.
"""

from datetime import datetime, timedelta, timezone
import heapq
from itertools import islice
import gzip
import hashlib
import json
from io import BytesIO
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.models.content import CapturedBody
from congress_api.parsers.archive_links import allowed_url, capture_links, related_links
from congress_api.parsers.source_family import family
from congress_api.retention.receipt_privacy import public_receipt
from congress_api.retention.body_files import CapturedFile
from congress_api.retention.bundles import separate
from congress_api.retention.capture_inspection import inspect_body
from congress_api.retention.archive_members import (
    ArchiveReadError, ZipLimits, is_office_zip, iter_archive_members,
)

from congress_api.retention.raw_schemas import (
    CAPTURE_SCHEMA,
    STATE_SCHEMA,
    LEGACY_CAPTURE_SCHEMA,
    LEGACY_STATE_SCHEMA,
    RAW_ARCHIVE_ROW_GROUP_SIZE,
    parse_sha256,
    format_sha256,
    parse_timestamp,
    format_timestamp,
    parse_http_status,
    derive_body_key,
    with_derived_body_keys,
    normalize_capture_dict,
    normalize_state_dict,
    prepare_capture_table,
    prepare_state_table,
    encode_table,
)
from congress_api.retention.raw_storage import _merge_states

STATE_KEY = "indexes/download-state.parquet"
CAPTURES_KEY = "indexes/captures.parquet"
NON_DOWNLOAD_OUTCOMES = frozenset({'saved', 'excluded_media', 'excluded_probe',
                                  'repaired_url', 'excluded_scope'})

_RAW_STORAGE_EXPORTS = frozenset({
    'STATE_BUCKET_COUNT',
    'STATE_KEY_SHA256_FIELD',
    'STATE_MERGE_SPEC',
    'STATE_PARTITION_SPEC',
    'STATE_PARTITIONED_SCHEMA',
    '_merge_states',
    'state_key_sha256',
})


def __getattr__(name):
    if name in _RAW_STORAGE_EXPORTS:
        from congress_api.retention import raw_storage
        return getattr(raw_storage, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class BodyLimitExceeded(ValueError):
    """Retained bytes need a larger inspection budget; they remain in storage."""



def decode_table(data, *, derive_body_key=False):
    table = pq.read_table(pa.BufferReader(data))
    if derive_body_key:
        return with_derived_body_keys(table)
    return table


def read_table(source, *, derive_body_key=True):
    table = pq.read_table(source)
    if derive_body_key:
        return with_derived_body_keys(table)
    return table


def capture_rank(row):
    """Prefer known successful, original bytes; use dates within that quality."""
    return (
        row.get("http_status") == 200,
        row.get("fidelity") == "exact-bytes",
        row.get("retrieved_at") or "",
    )


def prepare_capture(response, *, outcome, links, context=None, mode="fetch", scanned=True,
                    max_payload_bytes=None, archive_limits=None):
    """Separate validated bytes without writing storage or mutating archive state."""
    bodies = {}

    def retain(data):
        digest = data.sha256 if isinstance(data, CapturedFile) else hashlib.sha256(data).hexdigest()
        m_type = (response.get('content', {}).get('media_type') if isinstance(response, dict) else None) or getattr(data, 'media_type', None)
        key = derive_body_key(digest, m_type)
        bodies.setdefault(key, data)
        return key

    record, captures = separate({**response, "outcome": outcome, "mode": mode,
                                "links": list(links), "source_context": context or {}}, retain)
    retained_bytes = sum(map(len, bodies.values()))
    if max_payload_bytes is not None and retained_bytes > max_payload_bytes:
        raise BodyLimitExceeded('Separated capture bodies exceed the payload budget')
    publisher = next((cap for cap in captures if cap['pointer'] == ['content', 'body']), None)
    if not publisher or not record.get('complete') or outcome != 'saved':
        return record, captures, bodies, scanned
    data = bodies[publisher['body_key']]
    if isinstance(data, CapturedFile):
        if not data.prefix(4).startswith((b'PK\x03\x04', b'PK\x05\x06', b'rtfd')):
            return record, captures, bodies, scanned
        # Archive expansion keeps its existing aggregate and member bounds.
        data = data.read_bytes()
    limits = archive_limits or ZipLimits()
    media = (record.get('content', {}).get('media_type') or '').lower()
    suffix = urlsplit(record.get('url') or record['requested_url']).path.lower().rsplit('.', 1)[-1]
    office = (suffix in {'docx', 'docm', 'dotx', 'dotm', 'xlsx', 'xlsm', 'xltx', 'xltm',
                         'pptx', 'pptm', 'potx', 'potm', 'ppsx', 'ppsm'}
              or suffix in {'odt', 'ods', 'odp'}
              or 'officedocument' in media or 'vnd.ms-' in media
              or 'vnd.oasis.opendocument' in media or is_office_zip(data, limits=limits))
    if office or not data.startswith((b'PK\x03\x04', b'PK\x05\x06', b'rtfd')):
        return record, captures, bodies, scanned
    record['archive_members'] = []
    maximum = limits.max_total_bytes
    member_limit = limits.max_member_bytes
    if max_payload_bytes is not None:
        remaining = max_payload_bytes - retained_bytes
        # Converting the growing bytearray to bytes temporarily duplicates one
        # member. Keep that scratch space inside the caller's reservation too;
        # this byte accounting excludes Python object and parser overhead.
        member_limit = min(member_limit, remaining // 2)
        maximum = min(maximum, remaining - member_limit)
    if maximum <= 0 or member_limit <= 0:
        record['archive_processing'] = {'status': 'aggregate_size_limit'}
        return record, captures, bodies, scanned
    limits = ZipLimits(**{**vars(limits), 'max_total_bytes': maximum, 'max_member_bytes': member_limit})
    try:
        for member in iter_archive_members(data, archive_path=publisher['body_key'], limits=limits):
            position = len(record['archive_members'])
            item = dict(original_name=member.original_name, entry_index=member.entry_index,
                        parent_archive_body_key=publisher['body_key'], status=member.status,
                        error_type=member.error_type, unsafe_name=member.unsafe_name,
                        nested_archive=member.nested_archive, declared_bytes=member.declared_bytes,
                        compressed_bytes=member.compressed_bytes)
            if member.source_offset is not None:
                item.update(container_format='apple_file_wrapper_v3_regular',
                            source_offset=member.source_offset)
            if member.data is not None:
                extension = member.original_name.lower().rsplit('.', 1)[-1]
                member_media = {'pdf': 'application/pdf', 'xml': 'application/xml',
                                'html': 'text/html', 'htm': 'text/html', 'txt': 'text/plain',
                                'csv': 'text/csv', 'json': 'application/json',
                                'zip': 'application/zip'}.get(extension, 'application/octet-stream')
                item['content'] = CapturedBody.from_bytes(member.data, member_media).source_dict()
                item, member_captures = separate(item, retain)
                for cap in member_captures:
                    cap['pointer'] = ['archive_members', position, *cap['pointer']]
                    cap['context_url'] = publisher.get('context_url') or record['requested_url']
                    cap['original_path'] = member.original_name
                    cap['retrieved_at'] = publisher.get('retrieved_at')
                    cap['http_status'] = publisher.get('http_status')
                captures.extend(member_captures)
                member_key = member_captures[0]['body_key']
                # Larger retained files still reach the bounded metadata reader,
                # but link parsing stays inside that reader's 16 MiB ceiling.
                if not member.nested_archive and len(member.data) <= 16 * 1024**2:
                    try:
                        member_outcome, kind = inspect_body(member.data, '', member_media)
                        if member_outcome in {'saved', 'html'} and kind in {'xml', 'html'}:
                            for link in related_links(member.data, '', kind):
                                values = [value for key, value in link.get('attributes', {}).items()
                                          if key.rsplit('}', 1)[-1] in {'href', 'url', 'doc-url', 'data', 'src'}]
                                if kind == 'xml' and link.get('tag', '').lower() in {'url', 'uri'}:
                                    values.append(link.get('text', '').strip())
                                if not any(candidate['url'] == link['url'] for value in values
                                           for candidate in capture_links({'url': value})):
                                    continue
                                record['links'].append({**link, 'parent_url': record['requested_url'],
                                    'parent_sha256': publisher['sha256'], 'member_body_key': member_key,
                                    'archive_member': {'entry_index': member.entry_index,
                                                       'original_name': member.original_name}})
                    except (ValueError, UnicodeError) as exc:
                        item['link_error_type'] = type(exc).__name__
            record['archive_members'].append(item)
        record['archive_processing'] = {'status': 'completed'}
    except ArchiveReadError as exc:
        record['archive_processing'] = {'status': exc.status, 'error_type': type(exc).__name__}
    return record, captures, bodies, scanned


def metadata_body_keys(record, captures):
    """Unique complete publisher and successful member bodies, in capture order."""
    if not record.get('complete'):
        return []
    result = []
    for cap in captures:
        pointer = cap['pointer']
        primary = pointer == ['content', 'body']
        member = (len(pointer) == 4 and pointer[0] == 'archive_members'
                  and pointer[2:] == ['content', 'body']
                  and record['archive_members'][pointer[1]]['status'] == 'completed')
        if (primary or member) and cap['body_key'] not in result:
            result.append(cap['body_key'])
    return result


def body_payload(data):
    """Prepare the same compressed representation for sync and async retention."""
    digest = hashlib.sha256(data).hexdigest()
    payload = gzip.compress(data, compresslevel=1, mtime=0)
    return payload, dict(body_key=f"bodies/sha256/{digest[:2]}/{digest}.gz",
                        sha256=digest, bytes=len(data),
                        stored_sha256=hashlib.sha256(payload).hexdigest(), stored_bytes=len(payload))


def existing_body_info(payload, info):
    """Verify an orphan's original gzip bytes before admitting its reference."""
    if hashlib.sha256(gzip.decompress(payload)).hexdigest() != info['sha256']:
        raise ValueError("Stored body checksum mismatch")
    return {**info, 'stored_sha256': hashlib.sha256(payload).hexdigest(), 'stored_bytes': len(payload)}


class _Acquisition:
    """Shared receipt, body and URL behavior for maintained native acquisition."""

    @property
    def retained_body_hashes(self):
        """Only writes confirmed in this run can bypass another key-based create.

        ``body_info`` also reads the persisted index, whose rows cannot prove
        that a body exists. The run set is shared by sync and async retention.
        """
        if not hasattr(self, '_retained_body_hashes'):
            self._retained_body_hashes = set()
        return self._retained_body_hashes

    def _seed_catalog_source(self, source):
        from congress_api.retention.capture_url_admission import (
            PROVENANCE_COLUMNS, publisher_download_candidate, independent_publisher_link,
        )
        columns = ['source_url', 'body_key', 'format', 'http_status', 'media_type']
        columns.extend(name for name in PROVENANCE_COLUMNS if name in source.schema_arrow.names)
        rows = (row for batch in source.iter_batches(batch_size=256, columns=columns)
                for row in batch.to_pylist())
        for row in rows:
            if not publisher_download_candidate(row):
                continue  # Retain probe evidence without scheduling new guesses.
            links = self.seed_links({"url": row["source_url"]},
                                    publisher_link=independent_publisher_link(row))
            # An aggregate catalog body cannot be assigned to a recovered URL.
            url = links[0]['url'] if len(links) == 1 and not links[0].get('url_repair') else None
            if (
                not url
                or self.state[url]['outcome'] == 'excluded_probe'
                or not row["body_key"]
                or self.state[url].get("body_key")
                or self.state[url].get("checked_at")
                or "200" not in (row["http_status"] or [])
            ):
                continue
            formats = set(row["format"] or [])
            # A claimed format is not proof of a usable file. Inspect retained
            # bytes once before treating it as a successful document.
            if formats and formats <= {
                "pdf",
                "doc",
                "docx",
                "xls",
                "xlsx",
                "ppt",
                "pptx",
                "zip",
                "rtf",
            }:
                sha_candidate = row["body_key"].rsplit("/", 1)[-1].removesuffix(".gz") if row.get("body_key") else None
                sha_val = sha_candidate if (sha_candidate is not None and len(sha_candidate) == 64) else None
                self.state[url].update(
                    body_key=row["body_key"],
                    sha256=sha_val,
                    media_type=next(iter(row["media_type"] or []), None),
                    # The filename index aggregates observations; it does not
                    # associate one HTTP status with this particular body.
                    http_status=None,
                    fidelity="retained-file",
                    outcome="retained",
                    links_scanned=False,
                )


    def seed(self, item, *, publisher_link=False):
        url = allowed_url(item.get("url"))
        if url:
            self._seed_url(url, item)
            if publisher_link and self.state[url]['outcome'] == 'excluded_probe':
                self.state[url].update(outcome='pending', next_attempt_at=None)
        return url


    def _seed_url(self, url, item):
        self.state.setdefault(
            url,
            dict(
                url=url,
                family=item.get("family") or family(url=url) or "documents",
                outcome="pending",
                body_key=None,
                sha256=None,
                media_type=None,
                fidelity=None,
                retrieved_at=None,
                checked_at=None,
                next_attempt_at=None,
                http_status=None,
                attempts=0,
                links_scanned=False,
            ),
        )


    def seed_links(self, item, *, publisher_link=False):
        """Keep a repaired source value in state; schedule its valid children once."""
        links = capture_links(item)
        for link in links:
            original = link.get('original_url') if link.get('url_repair') else None
            if original:
                self._seed_url(original, item)
                if self.state[original]['outcome'] == 'pending':
                    self.state[original]['outcome'] = 'repaired_url'
            self.seed(link, publisher_link=publisher_link)
        return links


    def admit_pending_urls(self, urls=None):
        """Recheck restored pending URLs before acquisition, preserving old evidence.

        The original state row also keeps repair provenance across batch limits:
        each run can reconstruct its children's observations without a new index.
        Historical attempts and retained bodies remain untouched.
        """
        observations = []
        rejected = [state for state in self._admission_states(urls)
                    if (urls is None or state['url'] in urls)
                    and state['outcome'] in {'pending', 'repaired_url'} and not allowed_url(state['url'])]
        for state in rejected:
            links = self.seed_links({'url': state['url'], 'family': state['family']},
                                    publisher_link=True)
            if not links:
                state['outcome'] = 'excluded_scope'
            observations.extend(links)
        return observations


    def _admission_states(self, urls):
        return self.state.values()


    def put_body(self, data):
        from congress_api.retention.body_keys import is_pdf_bytes, physical_body_object_key

        digest = hashlib.sha256(data).hexdigest()
        if digest not in self.retained_body_hashes:
            compressed, info = body_payload(data)
            created = self.store.put(info['body_key'], compressed, immutable=True)
            # An orphan from an interrupted run may use different gzip bytes.
            if created is False:
                info = existing_body_info(self.store.read(info['body_key']), info)
            if getattr(self.store, 'store_uncompressed_pdfs', False) and is_pdf_bytes(data):
                pdf_key = physical_body_object_key(info['body_key'], is_pdf=True)
                if hasattr(self.store, 'put_pdf_body'):
                    self.store.put_pdf_body(pdf_key, data)
                else:
                    self.store.put(pdf_key, data, immutable=True)
            self.body_info[digest] = info
            self.retained_body_hashes.add(digest)
        return self.body_info[digest]["body_key"]


    def body(self, state, max_bytes=None):
        from congress_api.retention.body_keys import physical_body_object_key

        info = self.body_info.get(state.get("sha256"), {})
        if max_bytes is not None and (info.get("bytes") or 0) > max_bytes:
            raise BodyLimitExceeded("Retained body exceeds inspection limit")
        payload = self.store.read(state["body_key"])
        if payload is None and state.get("body_key"):
            payload = self.store.read(physical_body_object_key(state["body_key"], is_pdf=True))
        if payload is not None and payload[:2] != b"\x1f\x8b":
            data = payload[: max_bytes + 1] if max_bytes is not None else payload
        else:
            with gzip.GzipFile(fileobj=BytesIO(payload)) as stream:
                data = stream.read(max_bytes + 1 if max_bytes is not None else -1)
        if max_bytes is not None and len(data) > max_bytes:
            raise BodyLimitExceeded("Retained body exceeds inspection limit")
        if state.get("sha256") and hashlib.sha256(data).hexdigest() != state["sha256"]:
            raise ValueError("Retained body checksum mismatch")
        return data


    def record(
        self, response, *, outcome, links, scanned=True, context=None, mode="fetch"
    ):
        record, captures, bodies, scanned = prepare_capture(
            response, outcome=outcome, links=links, scanned=scanned, context=context, mode=mode)
        for data in bodies.values():
            self.put_body(data)
        if self.metadata is not None:
            for key in metadata_body_keys(record, captures):
                self.metadata.record(bodies[key], key)
        return self.record_prepared(record, captures, scanned=scanned)


    def record_prepared(self, record, captures, *, scanned=True):
        """Commit a capture only after all referenced bodies have been retained."""
        response = record
        outcome, mode = record['outcome'], record['mode']
        url = response["requested_url"]
        self.seed({"url": url})
        previous = self.state[url]
        now = datetime.now(timezone.utc)
        terminal = outcome in NON_DOWNLOAD_OUTCOMES
        retry = (
            None
            if terminal or outcome == "retained"
            else (
                now
                + timedelta(
                    days=7
                    if response.get("http_status") in (404, 410) or outcome == "html"
                    else 1
                )
            ).isoformat()
        )
        if outcome == 'retry_later':
            retry = (now + timedelta(seconds=response['retry_later']['delay_seconds'])).isoformat()
        state = {
            **previous,
            "outcome": outcome,
            "checked_at": now.isoformat(),
            "next_attempt_at": retry,
            "http_status": response.get("http_status"),
            "retrieved_at": response.get("retrieved_at"),
            "attempts": previous["attempts"] + (mode == "fetch"),
            "links_scanned": scanned,
        }
        content = response.get("content")
        if content:
            state.update(sha256=content["sha256"], media_type=content["media_type"])
        publisher = next(
            (c for c in captures if c["pointer"] == ["content", "body"]), None
        )
        if publisher:
            state["body_key"] = publisher["body_key"]
            state["fidelity"] = (
                previous.get("fidelity") or "retained-file"
                if mode == "replay"
                else publisher["fidelity"]
            )
        for cap in captures:
            cap.update(self.body_info[cap["sha256"]])
            pointer = cap["pointer"]
            prior_source = (
                len(pointer) == 4 and pointer[0] == "prior_attempts"
                and pointer[2:] == ["content", "body"]
            )
            archive_member = (len(pointer) == 4 and pointer[0] == 'archive_members'
                              and pointer[2:] == ['content', 'body'])
            cap["family"] = (
                previous["family"]
                if prior_source or archive_member or pointer
                in (["content", "body"], ["provider_response", "httpResponseBody"])
                else "external/provider-responses"
            )
            if mode == "replay" and cap["pointer"] == ["content", "body"]:
                cap["fidelity"] = state["fidelity"]
        # Inference and retry state are separate from the unchanged source response.
        receipt = dict(
            source_file=f"ci/{self.run_id}",
            source_line=None,
            record=record,
            captures=captures,
            download_state=self._receipt_state(state),
        )
        self.pending.append(receipt)
        self.apply(receipt)
        if len(self.pending) >= (1000 if self.metadata is not None else 100):
            self.flush()
        return state


    def _receipt_state(self, state):
        return state


    def flush(self):
        """Publish bounded receipt batches; never rewrite a prior batch."""
        if self.metadata is not None:
            # Resume must never skip extraction whose result was not retained.
            self.metadata.flush()
        while self.pending:
            owner = self.pending[0]["download_state"]["family"]
            batch = [self._publication_receipt(r) for r in self.pending if r["download_state"]["family"] == owner]
            self.sequence += 1
            key = f"receipts/{owner}/{self.day}/download-{self.run_id}-{self.sequence:06d}.jsonl.gz"
            payload = "".join(
                json.dumps(public_receipt(r), ensure_ascii=False, separators=(",", ":")) + "\n"
                for r in batch
            )
            self.store.put(
                key, gzip.compress(payload.encode(), mtime=0), immutable=True
            )
            for line, receipt in enumerate(batch, 1):
                self.add_index(receipt, key, line)
            self.pending = [
                r for r in self.pending if r["download_state"]["family"] != owner
            ]


    def _publication_receipt(self, receipt):
        return receipt


    def apply(self, receipt):
        state = receipt["download_state"]
        previous = self.state.get(state["url"])
        self.state[state["url"]] = _merge_states(previous, state) if previous is not None else state
        for link in receipt["record"].get("links", []):
            self.seed_links(link, publisher_link=True)
        for cap in receipt["captures"]:
            sha_hex = format_sha256(cap.get("sha256"))
            b_key = cap.get("body_key") or derive_body_key(sha_hex, cap.get("media_type"))
            stored_sha = cap.get("stored_sha256")
            if stored_sha is None and cap.get("is_stored"):
                stored_sha = sha_hex
            if sha_hex:
                self.body_info[sha_hex] = {
                    "body_key": b_key,
                    "sha256": sha_hex,
                    "bytes": cap.get("bytes"),
                    "stored_sha256": stored_sha,
                    "stored_bytes": cap.get("stored_bytes"),
                }


    def add_index(self, receipt, key, line):
        state = receipt["download_state"]
        record = receipt["record"]
        for cap in receipt["captures"] or [{}]:
            self.additions.append(
                {
                    **cap,
                    "family": cap.get("family", state["family"]),
                    "capture_date": (record.get("retrieved_at") or "undated")[:10],
                    "source_file": receipt["source_file"],
                    "receipt_key": key,
                    "receipt_line": line,
                    "reference_kind": "capture" if cap else "metadata",
                    "pointer_json": json.dumps(cap.get("pointer", [])),
                    "context_url": state["url"],
                    "retrieved_at": record["retrieved_at"],
                    "http_status": record.get("provider_http_status")
                    if cap.get("family") == "external/provider-responses"
                    else cap.get("http_status", record.get("http_status")),
                    "resolution": state["outcome"],
                    "fidelity": cap.get("fidelity", "saved-record"),
                }
            )



class _BodyLookup:
    """Fetch one bounded native body leaf on first use of a digest."""
    def __init__(self, snapshot):
        self.snapshot, self.cache = snapshot, {}

    def get(self, digest, default=None):
        if digest not in self.cache:
            self.cache[digest] = self.snapshot.body_info(digest)
        return self.cache[digest] if self.cache[digest] is not None else default

    def __contains__(self, digest):
        return self.get(digest) is not None

    def __getitem__(self, digest):
        value = self.get(digest)
        if value is None:
            raise KeyError(digest)
        return value

    def __setitem__(self, digest, value):
        self.cache[digest] = value


class Archive(_Acquisition):
    """Acquire bodies and receipts using one coherent native raw selection.

    Construction reads current URL scheduling state, never historical captures.
    Exact snapshot adoption is an explicit step; missing native selection
    refuses before acquisition so existing archives cannot be silently replaced.
    """
    def _seed_catalog(self, saved_metadata):
        from congress_api.retention.catalog_publication import FILENAMES, DOCUMENTS, MANIFEST_KEY, read_catalog
        store = self.store
        object_version = getattr(store, 'version', lambda key: None)
        version = object_version(MANIFEST_KEY)
        if version == 'missing':
            version = object_version(FILENAMES)
        self.filename_version = version
        if version is not None and saved_metadata.get(b'filename_version') == str(version).encode():
            return
        selector = store.read(MANIFEST_KEY)
        if selector is not None:
            if json.loads(selector).get('version') != 2:
                raise ValueError('Changed file catalog requires explicit catalog adoption')
        elif any(object_version(key) != 'missing' for key in (FILENAMES, DOCUMENTS)):
            raise ValueError('Legacy catalog files require explicit catalog adoption')
        with read_catalog(store, native=self.storage.native,
                read=lambda key: selector if key == MANIFEST_KEY else store.read(key)) as snapshot:
            if callable(getattr(snapshot, 'changes_since', None)):
                self.filename_version = snapshot.identity
                cursor = self.selected.manifest['filename_version']
                if not isinstance(cursor, dict):
                    raise ValueError('Native catalog acquisition requires an explicit initial cursor seed')
                if cursor != snapshot.identity:
                    self._seed_catalog_source(snapshot.changed_sources_since(cursor, max_ordered_bytes=64 << 20))
            elif callable(getattr(snapshot, 'table', None)):
                raise ValueError('Native catalog lacks retained source changes')
            elif not snapshot.files and snapshot.manifest is None:
                # Exact absence is an explicit cursor, never a legacy fallback.
                self.filename_version = snapshot.identity
            else:
                raise ValueError('Native catalog lacks retained source changes')


    def __init__(self, store, run_id, *, storage, repair=False):
        if storage.store is not store:
            raise ValueError('Archive storage belongs to another object store')
        if repair:
            raise ValueError('Legacy checkpoint repair belongs to explicit seed adoption')
        self.store, self.run_id, self.storage = store, run_id, storage
        self.selected = storage.snapshot()
        self.initial_identity = self.selected.identity
        if self.selected.version is None:
            raise RuntimeError('Explicit raw archive seed adoption is required before recurring capture')
        from congress_api.retention.raw_state_map import RawStateMap
        self.state = RawStateMap(self.selected)
        self.body_info = _BodyLookup(self.selected)
        self.additions, self.pending = [], []
        self._indexed_receipts = set()
        self._reading_parts, self._reading_by_body, self._replace_readings = {}, {}, set()
        self.sequence = self._save_sequence = 0
        self.metadata = None
        self.day = datetime.now(timezone.utc).date().isoformat()
        version = self.selected.manifest['filename_version']
        saved_metadata = {b'filename_version': str(version).encode()} if version is not None else {}
        self._seed_catalog(saved_metadata)
        # Receipts remain acquisition evidence after interruption. Membership is
        # keyed publication metadata; no capture-table scan constructs this set.
        for key in sorted(store.keys('receipts/')):
            if '/download-' not in key or self.selected.has_receipt(key):
                continue
            for line_number, line in enumerate(gzip.decompress(store.read(key)).splitlines(), 1):
                receipt = json.loads(line)
                self.apply(receipt)
                self.add_index(receipt, key, line_number)

    @property
    def captures(self):
        """Explicit full export for investigation/adoption consumers."""
        return with_derived_body_keys(self.selected.captures())

    @property
    def raw_selection(self):
        return dict(before=self.initial_identity, after=self.selected.identity)

    @property
    def state_counts(self):
        return self.selected.state_counts

    @property
    def retained_body_count(self):
        return self.selected.body_count

    def scheduled_states(self, *, outcomes, now=None, urls=None, invalid_only=False):
        """Merge changed working rows with exact selected candidates in old order."""
        from congress_api.retention.raw_state_routes import due_time, invalid, priority
        cached = set(self.state.rows)
        deadline = due_time(now.isoformat()) if now is not None else None
        working = sorted((row for row in self.state.rows.values()
            if row['outcome'] in outcomes and (urls is None or row['url'] in urls)
            and (not invalid_only or invalid(row))
            and (deadline is None or due_time(row.get('next_attempt_at')) <= deadline)), key=priority)
        selected = (row for row in self.selected.state_candidates(outcomes=outcomes,
            now=now, urls=urls, invalid_only=invalid_only) if row['url'] not in cached)
        for row in heapq.merge(working, selected, key=priority):
            yield self.state.admit_selected(row)

    def _admission_states(self, urls):
        return self.scheduled_states(outcomes={'pending', 'repaired_url'}, urls=urls, invalid_only=True)

    def capture_queue(self, *, now, limit, urls, retry_outcomes, initial_only, reinspect_retained, retry_now):
        """Admit at most this run's attempt budget, retaining scheduler fairness."""
        outcomes = (set(retry_outcomes) if retry_outcomes else {'pending'} if initial_only else
                    (set(self.state_counts['url_outcomes']) |
                     {row['outcome'] for row in self.state.rows.values()} | {None, ''}) - NON_DOWNLOAD_OUTCOMES)
        if reinspect_retained:
            outcomes = {self.state[url]['outcome'] for url in urls}
        due = None if reinspect_retained or retry_now else now
        options = dict(outcomes=outcomes, now=due, urls=urls)
        refusals = []
        for state in self.scheduled_states(**options, invalid_only=True):
            refusals.append(dict(url=state['url'], previous_outcome=state['outcome'], reason='outside_capture_scope'))
            state.update(outcome='excluded_scope', next_attempt_at=None)
        return list(islice(self.scheduled_states(**options), limit)), refusals

    def _receipt_state(self, state):
        # Acquisition receipts describe download decisions in JSON. Opaque
        # adopted Arrow fields remain typed in the native state selection.
        res = {}
        for name in STATE_SCHEMA.names:
            val = state.get(name)
            if name == "sha256" and val is not None:
                val = format_sha256(val)
            elif isinstance(val, datetime):
                val = format_timestamp(val)
            res[name] = val
        if "body_key" in state or res.get("sha256"):
            res["body_key"] = state.get("body_key") or derive_body_key(
                res.get("sha256"), state.get("media_type")
            )
        return res

    def apply(self, receipt):
        for reference in receipt.get('reading_parts', ()):
            self.register_reading_part(reference, replace=receipt.get('replace_readings', ()))
        url = receipt['download_state']['url']
        previous = self.state.get(url, {})
        super().apply(receipt)
        self.state[url] = {**previous, **self.state[url]}

    def add_index(self, receipt, key, line):
        super().add_index(receipt, key, line)
        self._indexed_receipts.add(key)

    def register_reading_part(self, reference, *, replace=()):
        selected = {name: reference[name] for name in ('key', 'bytes', 'sha256', 'rows')}
        self._reading_parts[selected['key']] = selected
        for body in reference.get('body_keys', ()):
            self._reading_by_body[body] = selected
        self._replace_readings.update(replace)

    def _publication_receipt(self, receipt):
        bodies = metadata_body_keys(receipt['record'], receipt['captures'])
        parts = {self._reading_by_body[key]['key']: self._reading_by_body[key]
                 for key in bodies
                 if key in self._reading_by_body}
        return dict(receipt, reading_parts=[parts[key] for key in sorted(parts)],
                    replace_readings=sorted(set(bodies) & self._replace_readings)) if parts else receipt

    def save(self):
        self.flush()
        updates = self.state.changed()
        if (not self.additions and not updates and not self._indexed_receipts and not self._reading_parts
                and self.filename_version == self.selected.manifest['filename_version']):
            return self.selected
        prepared = self.storage.prepare(self.selected,
            operation=f'archive:{self.run_id}:{self._save_sequence}',
            captures=prepare_capture_table(self.additions),
            states=prepare_state_table(updates, schema=self.storage.state_schema),
            indexed_receipts=self._indexed_receipts, filename_version=self.filename_version,
            reading_parts=tuple(self._reading_parts.values()), replace_readings=self._replace_readings)
        self.selected = self.storage.publish(prepared)
        self.body_info.snapshot = self.selected
        self.body_info.cache = {key: value for key, value in self.body_info.cache.items() if value is not None}
        self.state.rebase(self.selected)
        self._indexed_receipts.clear()
        self._reading_parts.clear()
        self._reading_by_body.clear()
        self._replace_readings.clear()
        self.additions.clear()
        self._save_sequence += 1
        return self.selected
