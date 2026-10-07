"""Exact-target recovery of large ZIPs and PDFs with normal receipts.

The caller pins the source length/version and reviewed ZIP directory. Every
member is read through ZipFile's CRC check; publisher digests qualify known
members. No member name becomes a filesystem path, and nesting is not expanded.
"""

from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import mmap
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED

from congress_api.parsers.archive_links import allowed_url
from congress_api.retention.archive_members import (
    ZipLimits,
    _directory_preflight,
    _unsafe_name,
)
from congress_api.retention.capture_metadata import CaptureMetadata

CHUNK = 1024**2


def file_digest(path, algorithm="sha256"):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, algorithm).hexdigest()


def download_ranges(
    client,
    url,
    path,
    *,
    size,
    last_modified,
    range_bytes=16 * CHUNK,
    stop=lambda: False,
):
    """Resume only hash-verified completed ranges of the same pinned version."""
    if allowed_url(url) != url or not size > 0 or not last_modified or range_bytes <= 0:
        raise ValueError(
            "A scoped URL, positive size and pinned Last-Modified are required"
        )
    path = Path(path)
    journal = path.with_suffix(".ranges.json")
    identity = dict(url=url, size=size, last_modified=last_modified)
    saved = dict(identity, bytes=0, sha256=hashlib.sha256(b"").hexdigest(), requests=[])
    if journal.exists():
        saved = json.loads(journal.read_text())
        if any(saved.get(k) != v for k, v in identity.items()):
            raise ValueError("Partial download belongs to a different source version")
    elif path.exists():
        raise ValueError("Unqualified local partial file; refusing to overwrite it")
    if not journal.exists():
        journal.write_text(json.dumps(saved, indent=2) + "\n")
    digest = hashlib.sha256()
    with path.open("r+b" if path.exists() else "w+b") as f:
        if f.seek(0, 2) < saved["bytes"] or not 0 <= saved["bytes"] <= size:
            raise ValueError("Partial download length differs from its journal")
        f.seek(0)
        remaining = saved["bytes"]
        while remaining:
            chunk = f.read(min(CHUNK, remaining))
            digest.update(chunk)
            remaining -= len(chunk)
        if digest.hexdigest() != saved["sha256"]:
            raise ValueError("Partial download checksum mismatch")
        f.truncate(saved["bytes"])  # Only discard the uncommitted tail of our own file.
        while saved["bytes"] < size:
            if stop():
                raise InterruptedError(
                    "Streaming recovery stopped; completed ranges are resumable"
                )
            start = saved["bytes"]
            end = min(size, start + range_bytes) - 1
            started = time.monotonic()
            received = 0
            with client.stream(
                "GET",
                url,
                headers={
                    "Range": f"bytes={start}-{end}",
                    "If-Unmodified-Since": last_modified,
                    "Accept-Encoding": "identity",
                },
            ) as r:
                if (
                    r.status_code != 206
                    or str(r.url) != url
                    or r.headers.get("content-range") != f"bytes {start}-{end}/{size}"
                    or r.headers.get("last-modified") != last_modified
                    or r.headers.get("content-encoding", "identity") != "identity"
                ):
                    raise ValueError(
                        "Source changed or refused the exact pinned byte range"
                    )
                for chunk in r.iter_bytes(CHUNK):
                    if stop() or time.monotonic() - started > 300:
                        raise InterruptedError(
                            "Range deadline or stop reached; completed ranges are resumable"
                        )
                    received += len(chunk)
                    if received > end - start + 1:
                        raise ValueError("Source exceeded requested byte range")
                    f.write(chunk)
                    digest.update(chunk)
                if received != end - start + 1:
                    raise ValueError("Incomplete source range")
            f.flush()
            os.fsync(f.fileno())
            saved.update(bytes=end + 1, sha256=digest.hexdigest())
            saved["requests"].append(dict(start=start, end=end, status=206))
            temp = journal.with_suffix(".tmp")
            temp.write_text(json.dumps(saved, indent=2) + "\n")
            temp.replace(journal)
    return saved


def retain_file(archive, path, scratch):
    """Reuse known content identities; stream gzip and conditional object writes."""
    path, scratch = Path(path), Path(scratch)
    digest = file_digest(path)
    size = path.stat().st_size
    if digest in archive.body_info:
        info = archive.body_info[digest]
        if info["bytes"] != size:
            raise ValueError("Retained body identity has a different length")
        return info
    key = f"bodies/sha256/{digest[:2]}/{digest}.gz"
    with path.open("rb") as source, scratch.open("wb") as destination:
        with gzip.GzipFile(
            filename="", fileobj=destination, mode="wb", compresslevel=1, mtime=0
        ) as zipped:
            while chunk := source.read(CHUNK):
                zipped.write(chunk)
    created = archive.store.put_file(key, scratch)
    if created is False:
        # Conditional conflict may be an earlier orphan with different gzip bytes.
        archive.store.read_file(key, scratch, max_bytes=size + size // 100 + CHUNK)
        actual = hashlib.sha256()
        raw_size = 0
        with gzip.open(scratch, "rb") as f:
            while chunk := f.read(CHUNK):
                raw_size += len(chunk)
                if raw_size > size:
                    raise ValueError("Stored body length mismatch")
                actual.update(chunk)
        if actual.hexdigest() != digest or raw_size != size:
            raise ValueError("Stored body checksum mismatch")
    info = dict(
        body_key=key,
        sha256=digest,
        bytes=size,
        stored_sha256=file_digest(scratch),
        stored_bytes=scratch.stat().st_size,
    )
    archive.body_info[digest] = info
    scratch.unlink()
    return info


def metadata_file(metadata, path, info):
    """Keep exact-file recovery on the shared, bounded metadata reader."""
    metadata.record_file(path, info["body_key"])


def _finish_recovery(archive, metadata, *, fetch, replay=0, members=0):
    """Persist normal metadata/checkpoints and report downloads separately from replays."""
    metadata.flush()
    archive.save()
    completed = fetch + replay
    return dict(
        mode="capture",
        run_id=archive.run_id,
        acquisition_status="completed",
        attempted=completed,
        saved=completed,
        fetch=fetch,
        replay=replay,
        initial_only=False,
        archive_member_captures=members,
        body_metadata=dict(metadata.counts),
        accounting=dict(
            capture_tasks_completed=completed,
            capture_tasks_submitted=completed,
            fetch_tasks_completed=fetch,
            retained_replays_completed=replay,
            known_urls=len(archive.state),
            usable_capture_results=completed,
            urls_by_source_family=dict(
                Counter(s.get("family") or "unknown" for s in archive.state.values())
            ),
            url_outcomes=dict(Counter(s["outcome"] for s in archive.state.values())),
        ),
    )


def recover_pdf(
    archive, client, manifest, directory, *, spool_bytes=5120 * CHUNK,
    range_bytes=16 * CHUNK, stop=lambda: False,
):
    """Retain an exact PDF only after validating its pinned publisher hash."""
    if archive.pending or archive.metadata is not None:
        raise ValueError("PDF recovery requires a fresh archive collector")
    if (manifest.get("kind") != "file"
            or manifest.get("media_type") != "application/pdf"
            or not manifest.get("sha256")):
        raise ValueError("PDF recovery requires a publisher-qualified PDF manifest")
    size, url = manifest["bytes"], manifest["url"]
    if not 0 < size or 2 * size + size // 100 + CHUNK > spool_bytes:
        raise ValueError("PDF exceeds the existing spool budget")
    directory = Path(directory)
    directory.mkdir(exist_ok=True)
    path = directory / "source.pdf"
    transfer = download_ranges(
        client, url, path, size=size, last_modified=manifest["last_modified"],
        range_bytes=range_bytes, stop=stop,
    )
    if transfer["sha256"] != manifest["sha256"]:
        raise ValueError("PDF publisher checksum mismatch")
    with path.open("rb") as source:
        if not source.read(8).startswith(b"%PDF-"):
            raise ValueError("Qualified content is not a PDF")
    if stop():
        raise InterruptedError("Streaming recovery stopped before publication")
    now = datetime.now(timezone.utc).isoformat()
    with CaptureMetadata(archive.store, archive.run_id) as metadata:
        archive.metadata = metadata
        try:
            info = retain_file(archive, path, directory / "body.gz")
            metadata_file(metadata, path, info)
            if stop():
                raise InterruptedError("Streaming recovery stopped before receipt publication")
            record = dict(
                requested_url=url, url=url, retrieved_at=now, transport="direct-range",
                http_status=206, complete=True, outcome="saved", mode="fetch", links=[],
                range_transfer=transfer, source_context={}, publisher_sha256=manifest["sha256"],
                content=dict(body=None, body_encoding="utf-8", media_type="application/pdf",
                             sha256=info["sha256"]),
            )
            capture = dict(
                **info, pointer=["content", "body"], media_type="application/pdf",
                context_url=url, fidelity="exact-bytes", retrieved_at=now, http_status=206,
            )
            archive.record_prepared(record, [capture], scanned=False)
            return _finish_recovery(archive, metadata, fetch=1)
        finally:
            archive.metadata = None


def recover_zip(
    archive,
    client,
    manifest,
    directory,
    *,
    spool_bytes=5120 * CHUNK,
    range_bytes=16 * CHUNK,
    stop=lambda: False,
):
    """Retain one ZIP and qualify explicitly named source URLs from its members."""
    if archive.pending or archive.metadata is not None:
        raise ValueError("Streaming recovery requires a fresh archive collector")
    directory = Path(directory)
    directory.mkdir(exist_ok=True)
    url, size = manifest["url"], manifest["bytes"]
    entries = manifest["members"]
    if (
        not 0 < size
        or 2 * size + size // 100 + CHUNK > spool_bytes
        or not 0 < len(entries) <= 1024
        or sum(x["bytes"] for x in entries) > spool_bytes
        or any(
            x["bytes"] < 0
            or size + 2 * x["bytes"] + x["bytes"] // 100 + CHUNK > spool_bytes
            for x in entries
        )
    ):
        raise ValueError("Reviewed archive or members exceed the existing spool budget")
    path = directory / "source.zip"
    scratch = directory / "body.gz"
    transfer = download_ranges(
        client,
        url,
        path,
        size=size,
        last_modified=manifest["last_modified"],
        range_bytes=range_bytes,
        stop=stop,
    )
    if manifest.get("sha256") and transfer["sha256"] != manifest["sha256"]:
        raise ValueError("Archive publisher checksum mismatch")
    limits = ZipLimits(
        max_archive_bytes=size,
        max_member_bytes=spool_bytes,
        max_total_bytes=spool_bytes,
    )
    with path.open("rb") as f, mmap.mmap(
        f.fileno(), 0, access=mmap.ACCESS_READ
    ) as view:
        _directory_preflight(view, limits)
    now = datetime.now(timezone.utc).isoformat()
    record = dict(
        requested_url=url,
        url=url,
        retrieved_at=now,
        transport="direct-range",
        http_status=206,
        complete=True,
        outcome="saved",
        mode="fetch",
        links=[],
        range_transfer=transfer,
        archive_members=[],
        source_context={},
    )
    captures, recovered = [], []
    counts = Counter()
    with (
        ZipFile(path) as z,
        CaptureMetadata(archive.store, archive.run_id) as metadata,
        TemporaryDirectory(prefix="members-", dir=directory) as temporary,
    ):
        scratch = Path(temporary) / "body.gz"
        actual = [(i.filename, i.file_size, i.CRC) for i in z.infolist()]
        expected = [(i["name"], i["bytes"], int(i["crc32"], 16)) for i in entries]
        if actual != expected or any(
            i.flag_bits & 1 or i.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
            for i in z.infolist()
        ):
            raise ValueError(
                "ZIP directory differs from reviewed members or uses unsupported encoding"
            )
        archive.metadata = metadata
        try:
            parent = retain_file(archive, path, scratch)
            metadata_file(metadata, path, parent)
            record["content"] = dict(
                body=None,
                body_encoding="utf-8",
                media_type="application/zip",
                sha256=parent["sha256"],
            )
            captures.append(
                dict(
                    **parent,
                    pointer=["content", "body"],
                    media_type="application/zip",
                    context_url=url,
                    fidelity="exact-bytes",
                    retrieved_at=now,
                    http_status=206,
                )
            )
            for position, (entry, qualified) in enumerate(zip(z.infolist(), entries)):
                if stop():
                    raise InterruptedError(
                        "Streaming recovery stopped before receipt publication"
                    )
                if entry.is_dir():
                    raise ValueError("Reviewed recovery requires regular members")
                member = Path(temporary) / "member.bin"
                count = 0
                with z.open(entry) as src, member.open("wb") as dst:
                    while chunk := src.read(CHUNK):
                        count += len(chunk)
                        if count > entry.file_size:
                            raise ValueError("ZIP member exceeds declared size")
                        dst.write(chunk)
                if count != entry.file_size:
                    raise ValueError("Incomplete ZIP member")
                digest = file_digest(member)
                if qualified.get("sha256") and digest != qualified["sha256"]:
                    raise ValueError("ZIP member publisher checksum mismatch")
                if qualified.get("source_url") and (
                    not qualified.get("sha256")
                    or allowed_url(qualified["source_url"]) != qualified["source_url"]
                ):
                    raise ValueError(
                        "A member URL requires independent publisher hash qualification"
                    )
                info = retain_file(archive, member, scratch)
                metadata_file(metadata, member, info)
                with member.open("rb") as f:
                    prefix = f.read(4)
                item = dict(
                    original_name=entry.orig_filename,
                    entry_index=position,
                    parent_archive_body_key=parent["body_key"],
                    status="completed",
                    error_type=None,
                    unsafe_name=_unsafe_name(entry.orig_filename),
                    nested_archive=prefix in (b"rtfd", b"PK\x03\x04", b"PK\x05\x06"),
                    declared_bytes=count,
                    compressed_bytes=entry.compress_size,
                    content=dict(
                        body=None,
                        body_encoding="utf-8",
                        media_type=qualified["media_type"],
                        sha256=digest,
                    ),
                )
                record["archive_members"].append(item)
                captures.append(
                    dict(
                        **info,
                        pointer=["archive_members", position, "content", "body"],
                        media_type=qualified["media_type"],
                        original_path=entry.orig_filename,
                        context_url=url,
                        fidelity="exact-bytes",
                        retrieved_at=now,
                        http_status=206,
                    )
                )
                if qualified.get("source_url"):
                    recovered.append((qualified, info, position))
                member.unlink()
            if stop():
                raise InterruptedError(
                    "Streaming recovery stopped before receipt publication"
                )
            record["archive_processing"] = {"status": "completed"}
            archive.record_prepared(record, captures, scanned=False)
            counts["fetch"] += 1
            # A verified archive member can repair its exact document URL without
            # claiming a second HTTP download. Keep the ZIP/member provenance.
            for qualified, info, position in recovered:
                target = qualified["source_url"]
                if (
                    archive.state.get(target, {}).get("outcome") == "saved"
                    and archive.state[target].get("sha256") == info["sha256"]
                ):
                    continue
                content = dict(
                    body=None,
                    body_encoding="utf-8",
                    media_type=qualified["media_type"],
                    sha256=info["sha256"],
                )
                derived = dict(
                    requested_url=target,
                    url=target,
                    retrieved_at=now,
                    transport="retained_archive_member",
                    http_status=None,
                    complete=True,
                    outcome="saved",
                    mode="replay",
                    links=[],
                    content=content,
                    recovered_from=dict(
                        url=url,
                        body_key=parent["body_key"],
                        entry_index=position,
                        publisher_sha256=qualified["sha256"],
                    ),
                )
                archive.record_prepared(
                    derived,
                    [
                        dict(
                            **info,
                            pointer=["content", "body"],
                            media_type=qualified["media_type"],
                            context_url=target,
                            fidelity="exact-bytes",
                            retrieved_at=now,
                            http_status=None,
                        )
                    ],
                    scanned=False,
                )
                counts["replay"] += 1
            return _finish_recovery(
                archive, metadata, fetch=counts["fetch"], replay=counts["replay"],
                members=len(entries),
            )
        finally:
            archive.metadata = None
