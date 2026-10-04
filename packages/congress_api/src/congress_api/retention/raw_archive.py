"""Content-addressed bodies, immutable receipt batches, and replaceable indexes.

The caller supplies object storage. Receipts are the recovery log: bodies reach
storage before receipts; state reaches storage before the capture index. If an
index write fails, the next run replays receipts absent from the capture index.
"""

from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from io import BytesIO

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.parsers.archive_links import allowed_url
from congress_api.parsers.source_family import family
from congress_api.retention.bundles import separate

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
        from congress_api.retention.catalog_cache import capture_digest
        resumed = (not repair and 0 <= cursor <= len(self.captures) and saved_metadata.get(b'capture_digest')
                   == capture_digest(self.captures.slice(0, cursor)).encode())
        if not resumed:
            cursor = 0
        self.additions, self.body_info, self.state = [], {}, dict(saved_state)
        self.sequence = 0
        self.pending = []
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
            table = pq.read_table(
                pa.BufferReader(names),
                columns=[
                    "source_url",
                    "body_key",
                    "format",
                    "http_status",
                    "media_type",
                ],
            )
            for row in table.to_pylist():
                url = self.seed({"url": row["source_url"]})
                if (
                    not url
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

    def seed(self, item):
        url = allowed_url(item.get("url"))
        if url:
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
        return url

    def put_body(self, data):
        digest = hashlib.sha256(data).hexdigest()
        if digest not in self.body_info:
            key = f"bodies/sha256/{digest[:2]}/{digest}.gz"
            compressed = gzip.compress(data, compresslevel=1, mtime=0)
            created = self.store.put(key, compressed, immutable=True)
            # An orphan from an interrupted run may use different gzip bytes.
            actual = self.store.read(key) if created is False else compressed
            if hashlib.sha256(gzip.decompress(actual)).hexdigest() != digest:
                raise ValueError("Stored body checksum mismatch")
            self.body_info[digest] = dict(
                body_key=key,
                sha256=digest,
                bytes=len(data),
                stored_sha256=hashlib.sha256(actual).hexdigest(),
                stored_bytes=len(actual),
            )
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
        url = response["requested_url"]
        self.seed({"url": url})
        previous = self.state[url]
        now = datetime.now(timezone.utc)
        terminal = outcome in {"saved", "excluded_media"}
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
        original = {
            **response,
            "outcome": outcome,
            "mode": mode,
            "links": links,
            "source_context": context or {},
        }
        record, captures = separate(original, self.put_body)
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
            cap["family"] = (
                previous["family"]
                if prior_source or pointer
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
        if len(self.pending) >= 100:
            self.flush()
        return state

    def flush(self):
        """Publish bounded receipt batches; never rewrite a prior batch."""
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
            self.seed(link)
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
