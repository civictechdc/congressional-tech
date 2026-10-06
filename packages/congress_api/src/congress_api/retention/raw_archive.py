"""Content-addressed bodies, immutable receipt batches, and replaceable indexes.

The caller supplies object storage. Receipts are the recovery log: bodies reach
storage before receipts; state reaches storage before the capture index. With a
valid checkpoint, the next run recovers unindexed receipts. An interrupted index
pair or mismatching checkpoint requires explicit repair after investigation;
receipts preserve the evidence needed to repair without refetching.
"""

from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from io import BytesIO
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.models.content import CapturedBody
from congress_api.parsers.archive_links import allowed_url, capture_links, inspect_body, related_links
from congress_api.parsers.source_family import family
from congress_api.retention.bundles import separate
from congress_api.retention.archive_members import (
    ArchiveReadError, ZipLimits, is_office_zip, iter_archive_members,
)

CAPTURE_SCHEMA = pa.schema(
    [
        (k, t)
        for k, t in (
            ("family", pa.string()),
            ("capture_date", pa.string()),
            ("source_file", pa.string()),
            ("source_line", pa.int64()),
            ("receipt_key", pa.string()),
            ("receipt_line", pa.int64()),
            ("reference_kind", pa.string()),
            ("pointer_json", pa.string()),
            ("context_url", pa.string()),
            ("body_key", pa.string()),
            ("sha256", pa.string()),
            ("bytes", pa.int64()),
            ("stored_sha256", pa.string()),
            ("stored_bytes", pa.int64()),
            ("fidelity", pa.string()),
            ("media_type", pa.string()),
            ("retrieved_at", pa.string()),
            ("http_status", pa.int64()),
            ("resolution", pa.string()),
            ("original_path", pa.string()),
        )
    ]
)
STATE_SCHEMA = pa.schema(
    [
        (name, pa.string())
        for name in (
            "url",
            "family",
            "body_key",
            "sha256",
            "media_type",
            "fidelity",
            "retrieved_at",
            "outcome",
            "checked_at",
            "next_attempt_at",
        )
    ]
    + [
        ("http_status", pa.int64()),
        ("attempts", pa.int64()),
        ("links_scanned", pa.bool_()),
    ]
)
STATE_KEY = "indexes/download-state.parquet"
CAPTURES_KEY = "indexes/captures.parquet"
NON_DOWNLOAD_OUTCOMES = frozenset({'saved', 'excluded_media', 'excluded_probe',
                                  'repaired_url', 'excluded_scope'})


class BodyLimitExceeded(ValueError):
    """Retained bytes need a larger inspection budget; they remain in storage."""


def encode_table(table):
    stream = pa.BufferOutputStream()
    pq.write_table(table, stream, compression="zstd")
    return stream.getvalue().to_pybytes()


def decode_table(data):
    return pq.read_table(pa.BufferReader(data))


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
        digest = hashlib.sha256(data).hexdigest()
        key = f"bodies/sha256/{digest[:2]}/{digest}.gz"
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


class Archive:
    def __init__(self, store, run_id, *, repair=False):
        self.store, self.run_id = store, run_id
        data = store.read(CAPTURES_KEY)
        if data is None:
            raise RuntimeError(
                "The initial mirror upload must finish before recurring capture starts."
            )
        self.captures = decode_table(data)
        if self.captures.schema.remove_metadata() != CAPTURE_SCHEMA:
            raise ValueError("Unexpected capture index schema")
        saved = store.read(STATE_KEY)
        saved_table = decode_table(saved) if saved else None
        saved_metadata = (saved_table.schema.metadata or {}) if saved_table is not None else {}
        saved_state = {r['url']: r for r in saved_table.to_pylist()} if saved_table is not None else {}
        cursor = int(saved_metadata.get(b'capture_rows', b'0'))
        from congress_api.retention.catalog_cache import capture_digest_matches
        checkpoint = b'capture_rows' in saved_metadata or b'capture_digest' in saved_metadata
        resumed = (not repair and b'capture_rows' in saved_metadata and 0 <= cursor <= len(self.captures)
                   and capture_digest_matches(self.captures.slice(0, cursor), saved_metadata.get(b'capture_digest')))
        if checkpoint and not repair and not resumed:
            raise ValueError('Capture checkpoint digest mismatch or invalid cursor; verify legacy checkpoints '
                             'with their original PyArrow writer, or explicitly repair after investigation')
        if not resumed:
            cursor = 0
        self.additions, self.body_info, self.state = [], {}, dict(saved_state)
        self.sequence = 0
        self.pending = []
        self.metadata = None  # Attached only for the lifetime of acquisition.
        self.day = datetime.now(timezone.utc).date().isoformat()
        indexed = set()
        position = 0
        for batch in self.captures.to_batches(max_chunksize=65536):
            for row in batch.to_pylist():
                position += 1
                if row["receipt_key"]:
                    indexed.add(row["receipt_key"])
                if row["body_key"] and row["sha256"]:
                    self.body_info[row["sha256"]] = {
                        k: row[k]
                        for k in (
                            "body_key",
                            "sha256",
                            "bytes",
                            "stored_sha256",
                            "stored_bytes",
                        )
                    }
                if position <= cursor:
                    continue
                if json.loads(row.get('pointer_json') or '[]')[:1] == ['archive_members']:
                    continue  # Member bytes cannot stand in for the enclosing ZIP URL.
                url = allowed_url(row["context_url"])
                if not url or row["family"] in {
                    "external/provider-responses",
                    "youtube/api",
                    "congress/meetings",
                    "congress/committees",
                }:
                    continue
                self.seed({"url": url, "family": row["family"]})
                if row["body_key"] and row["http_status"] in (None, 200):
                    previous = self.state[url]
                    if previous.get("body_key") and capture_rank(
                        previous
                    ) >= capture_rank(row):
                        continue
                    self.state[url].update(
                        body_key=row["body_key"],
                        sha256=row["sha256"],
                        media_type=row["media_type"],
                        http_status=row["http_status"],
                        outcome="retained",
                        fidelity=row["fidelity"],
                        retrieved_at=row["retrieved_at"],
                    )
        # Add every known document URL, including files not yet downloaded.
        # Only a changed catalog can introduce additional unqueued document URLs.
        from congress_api.retention.catalog_publication import FILENAMES, MANIFEST_KEY, read_catalog
        # The selector changes only after both immutable tables are uploaded.
        object_version = getattr(store, 'version', lambda key: None)
        version = object_version(MANIFEST_KEY)
        if version == 'missing':
            version = object_version(FILENAMES)
        self.filename_version = version
        names = None
        if repair or version is None or saved_metadata.get(b'filename_version') != str(version).encode():
            snapshot = read_catalog(store)
            names = snapshot.filenames
        if names:
            from congress_api.retention.capture_url_admission import (
                PROVENANCE_COLUMNS, publisher_download_candidate, independent_publisher_link,
            )
            filename_file = pq.ParquetFile(pa.BufferReader(names))
            columns = [
                "source_url",
                "body_key",
                "format",
                "http_status",
                "media_type",
            ]
            columns.extend(name for name in PROVENANCE_COLUMNS
                           if name in filename_file.schema_arrow.names)
            rows = (row for batch in filename_file.iter_batches(batch_size=256, columns=columns)
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
                    self.state[url].update(
                        body_key=row["body_key"],
                        sha256=row["body_key"].rsplit("/", 1)[-1].removesuffix(".gz"),
                        media_type=next(iter(row["media_type"] or []), None),
                        # The filename index aggregates observations; it does not
                        # associate one HTTP status with this particular body.
                        http_status=None,
                        fidelity="retained-file",
                        outcome="retained",
                        links_scanned=False,
                    )
        # Persisted attempts/validation take precedence over legacy bootstrap guesses.
        if not resumed:
            self.state.update(saved_state)
        # Recover all published batches, including a run interrupted before save().
        for key in store.keys("receipts/"):
            if "/download-" not in key or key in indexed:
                continue
            for line_number, line in enumerate(
                gzip.decompress(store.read(key)).splitlines(), 1
            ):
                receipt = json.loads(line)
                self.apply(receipt)
                self.add_index(receipt, key, line_number)

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
        rejected = [state for state in self.state.values()
                    if (urls is None or state['url'] in urls)
                    and state['outcome'] in {'pending', 'repaired_url'} and not allowed_url(state['url'])]
        for state in rejected:
            links = self.seed_links({'url': state['url'], 'family': state['family']},
                                    publisher_link=True)
            if not links:
                state['outcome'] = 'excluded_scope'
            observations.extend(links)
        return observations

    def put_body(self, data):
        digest = hashlib.sha256(data).hexdigest()
        if digest not in self.body_info:
            compressed, info = body_payload(data)
            created = self.store.put(info['body_key'], compressed, immutable=True)
            # An orphan from an interrupted run may use different gzip bytes.
            if created is False:
                info = existing_body_info(self.store.read(info['body_key']), info)
            self.body_info[digest] = info
        return self.body_info[digest]["body_key"]

    def body(self, state, max_bytes=None):
        info = self.body_info.get(state.get("sha256"), {})
        if max_bytes is not None and (info.get("bytes") or 0) > max_bytes:
            raise BodyLimitExceeded("Retained body exceeds inspection limit")
        with gzip.GzipFile(
            fileobj=BytesIO(self.store.read(state["body_key"]))
        ) as stream:
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
            download_state=state,
        )
        self.pending.append(receipt)
        self.apply(receipt)
        if len(self.pending) >= (1000 if self.metadata is not None else 100):
            self.flush()
        return state

    def flush(self):
        """Publish bounded receipt batches; never rewrite a prior batch."""
        if self.metadata is not None:
            # Resume must never skip extraction whose result was not retained.
            self.metadata.flush()
        while self.pending:
            owner = self.pending[0]["download_state"]["family"]
            batch = [r for r in self.pending if r["download_state"]["family"] == owner]
            self.sequence += 1
            key = f"receipts/{owner}/{self.day}/download-{self.run_id}-{self.sequence:06d}.jsonl.gz"
            payload = "".join(
                json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
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

    def apply(self, receipt):
        state = receipt["download_state"]
        previous = self.state.get(state["url"], {})
        if (state.get("checked_at") or "") >= (previous.get("checked_at") or ""):
            self.state[state["url"]] = state
        for link in receipt["record"].get("links", []):
            self.seed_links(link, publisher_link=True)
        for cap in receipt["captures"]:
            self.body_info[cap["sha256"]] = {
                k: cap[k]
                for k in (
                    "body_key",
                    "sha256",
                    "bytes",
                    "stored_sha256",
                    "stored_bytes",
                )
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

    def save(self):
        from congress_api.retention.catalog_cache import capture_digest
        self.flush()
        combined = self.captures
        if self.additions:
            appended = pa.Table.from_pylist(self.additions, schema=CAPTURE_SCHEMA)
            combined = pa.concat_tables([combined, appended])
        metadata = {'capture_rows': str(len(combined)), 'capture_digest': capture_digest(combined)}
        if self.filename_version is not None:
            metadata['filename_version'] = str(self.filename_version)
        self.store.put(STATE_KEY, encode_table(pa.Table.from_pylist(
            list(self.state.values()), schema=STATE_SCHEMA.with_metadata(metadata))))
        if self.additions:
            self.store.put(CAPTURES_KEY, encode_table(combined))
            self.captures = combined
            self.additions.clear()
