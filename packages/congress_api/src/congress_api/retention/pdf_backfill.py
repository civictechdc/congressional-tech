"""Backfill uncompressed .pdf sibling objects in R2/LocalStore for accepted PDF bodies.

New PDF captures are stored uncompressed at ``bodies/sha256/<xx>/<sha256>.pdf`` while
preserving logical ``row['body_key'] = 'bodies/sha256/<xx>/<sha256>.gz'``. Historical
accepted PDF captures that only exist at ``.gz`` are stream-decompressed, SHA-256
verified, and uploaded to ``.pdf`` with ``Content-Type: application/pdf`` and
``Cache-Control: public, max-age=31536000, immutable``, keeping the ``.gz`` object intact.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
from typing import Any

from congress_api.retention.body_keys import (
    body_object_digest,
    is_pdf_bytes,
    is_pdf_format,
    physical_body_object_key,
)
from congress_api.retention.raw_storage import DEFAULT_ACCEPTED_FILES_PATH, load_excluded_body_hashes

STREAM_CHUNK_BYTES = 1024 * 1024
MAX_PDF_BACKFILL_BYTES = 512 * 1024 * 1024


def _load_accepted_entries(accepted_files: Path | str | Mapping[str, Any] | Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    source = DEFAULT_ACCEPTED_FILES_PATH if accepted_files is None else accepted_files
    if isinstance(source, Path):
        payload = json.loads(source.read_text(encoding="utf-8"))
    elif isinstance(source, str):
        path = Path(source)
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else json.loads(source)
    elif isinstance(source, Mapping):
        payload = dict(source)
    elif isinstance(source, Iterable):
        payload = list(source)
    else:
        raise ValueError(f"Unsupported accepted_files input: {type(accepted_files)!r}")

    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("files", "accepted", "entries", "deferred"):
            if isinstance(payload.get(key), list):
                return [dict(item) for item in payload[key] if isinstance(item, Mapping)]
    raise ValueError("accepted_files must be a list of file entries or a mapping containing 'files'")


def _is_entry_pdf(entry: Mapping[str, Any]) -> bool:
    for field in ("content_type", "media_type", "format", "mime_type", "filename", "url", "source_url"):
        val = entry.get(field)
        if val and is_pdf_format(val):
            return True
    body_key = entry.get("body_key")
    if isinstance(body_key, str) and body_key.endswith(".pdf"):
        return True
    return False


def _iter_pdf_digests(entries: Iterable[Mapping[str, Any]], excluded: frozenset[str]) -> list[str]:
    seen: dict[str, None] = {}

    def visit(item: Mapping[str, Any]) -> None:
        decision = item.get("decision")
        if decision == "exclude":
            return
        if _is_entry_pdf(item):
            for field in ("sha256", "body_key"):
                raw = item.get(field)
                digest = body_object_digest(raw.lower()) if isinstance(raw, str) else None
                if digest and digest not in excluded:
                    seen.setdefault(digest, None)
                    break
        zip_check = item.get("zip_Check") or {}
        for member in zip_check.get("members") or ():
            if isinstance(member, Mapping):
                visit(member)
        for member in item.get("members") or ():
            if isinstance(member, Mapping):
                visit(member)

    for entry in entries:
        visit(entry)
    return list(seen.keys())


def _object_exists(store: Any, key: str) -> bool:
    if hasattr(store, "version"):
        try:
            return store.version(key) != "missing"
        except Exception:
            pass
    return store.read(key) is not None


def _decompress_and_verify_to_file(gz_path: Path, pdf_path: Path, expected_sha256: str) -> int:
    digest = sha256()
    total = 0
    header = b""
    with gz_path.open("rb") as raw_in:
        magic = raw_in.read(2)
        raw_in.seek(0)
        stream_ctx = gzip.GzipFile(fileobj=raw_in, mode="rb") if magic == b"\x1f\x8b" else raw_in
        with stream_ctx as decompressed, pdf_path.open("wb") as out:
            while chunk := decompressed.read(STREAM_CHUNK_BYTES):
                if len(header) < 5:
                    header += chunk[: 5 - len(header)]
                total += len(chunk)
                if total > MAX_PDF_BACKFILL_BYTES:
                    raise ValueError(f"Decompressed PDF exceeds {MAX_PDF_BACKFILL_BYTES} byte limit: {expected_sha256}")
                digest.update(chunk)
                out.write(chunk)
    actual_sha = digest.hexdigest()
    if actual_sha != expected_sha256:
        raise ValueError(
            f"Decompressed PDF SHA-256 mismatch for {expected_sha256}: got {actual_sha}"
        )
    if not is_pdf_bytes(header):
        raise ValueError(f"Decompressed body for {expected_sha256} does not start with %PDF-")
    return total


def _decompress_and_verify_bytes(compressed: bytes, expected_sha256: str) -> bytes:
    digest = sha256()
    out = io.BytesIO()
    total = 0
    header = b""
    raw_in = io.BytesIO(compressed)
    stream_ctx = (
        gzip.GzipFile(fileobj=raw_in, mode="rb")
        if compressed[:2] == b"\x1f\x8b"
        else raw_in
    )
    with stream_ctx as decompressed:
        while chunk := decompressed.read(STREAM_CHUNK_BYTES):
            if len(header) < 5:
                header += chunk[: 5 - len(header)]
            total += len(chunk)
            if total > MAX_PDF_BACKFILL_BYTES:
                raise ValueError(f"Decompressed PDF exceeds {MAX_PDF_BACKFILL_BYTES} byte limit: {expected_sha256}")
            digest.update(chunk)
            out.write(chunk)
    actual_sha = digest.hexdigest()
    if actual_sha != expected_sha256:
        raise ValueError(
            f"Decompressed PDF SHA-256 mismatch for {expected_sha256}: got {actual_sha}"
        )
    if not is_pdf_bytes(header):
        raise ValueError(f"Decompressed body for {expected_sha256} does not start with %PDF-")
    return out.getvalue()


def backfill_uncompressed_pdfs(
    store: Any,
    accepted_files: Path | str | Mapping[str, Any] | Iterable[Mapping[str, Any]] | None = None,
    *,
    dry_run: bool = False,
    excluded_hashes: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Ensure every accepted PDF in ``accepted_files`` has an uncompressed ``.pdf`` object in ``store``.

    Preserves the existing ``bodies/sha256/<xx>/<sha256>.gz`` object intact.
    """
    entries = _load_accepted_entries(accepted_files)
    store_exclusions = getattr(store, "excluded_body_hashes", None)
    active_exclusions = (
        load_excluded_body_hashes(excluded_hashes)
        if excluded_hashes is not None
        else (
            load_excluded_body_hashes(store_exclusions)
            if store_exclusions
            else frozenset()
        )
    )
    pdf_digests = _iter_pdf_digests(entries, active_exclusions)

    backfilled: list[str] = []
    already_present: list[str] = []
    would_backfill: list[str] = []
    missing_source: list[str] = []

    use_file_streaming = hasattr(store, "read_file") and hasattr(store, "put_pdf_file")

    for digest in pdf_digests:
        gz_key = physical_body_object_key(digest, is_pdf=False)
        pdf_key = physical_body_object_key(digest, is_pdf=True)

        if _object_exists(store, pdf_key):
            already_present.append(pdf_key)
            continue

        if dry_run:
            if _object_exists(store, gz_key):
                would_backfill.append(pdf_key)
            else:
                missing_source.append(gz_key)
            continue

        if use_file_streaming:
            with tempfile.TemporaryDirectory(prefix="pdf-backfill-") as tmp_dir:
                gz_file = Path(tmp_dir) / f"{digest}.gz"
                pdf_file = Path(tmp_dir) / f"{digest}.pdf"
                try:
                    read_res = store.read_file(gz_key, gz_file, max_bytes=MAX_PDF_BACKFILL_BYTES)
                except Exception as exc:
                    response = getattr(exc, "response", None) or {}
                    code = (response.get("Error") or {}).get("Code")
                    if code in {"NoSuchKey", "404"}:
                        read_res = None
                    else:
                        raise
                if read_res is None or not gz_file.is_file():
                    missing_source.append(gz_key)
                    continue
                _decompress_and_verify_to_file(gz_file, pdf_file, digest)
                store.put_pdf_file(pdf_key, pdf_file)
                backfilled.append(pdf_key)
        else:
            compressed = store.read(gz_key)
            if compressed is None:
                missing_source.append(gz_key)
                continue
            raw_pdf = _decompress_and_verify_bytes(compressed, digest)
            if hasattr(store, "put_pdf_body"):
                store.put_pdf_body(pdf_key, raw_pdf)
            else:
                store.put(pdf_key, raw_pdf, immutable=True)
            backfilled.append(pdf_key)

    return {
        "dry_run": dry_run,
        "candidates": len(pdf_digests),
        "backfilled": backfilled,
        "already_present": already_present,
        "would_backfill": would_backfill,
        "missing_source": missing_source,
    }
