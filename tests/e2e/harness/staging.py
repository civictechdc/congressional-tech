"""Controlled Local Content-Addressed Storage (CAS) Staging Harness.

Enforces Requirement R5: All R2 objects (bodies/sha256/<xx>/<sha256>.{gz,pdf})
must be staged to local directories only. Never mutates live R2 or remote endpoints.
"""

from __future__ import annotations
import gzip
import hashlib
from pathlib import Path
from typing import Any

from .contracts import PDF_MAGIC


class LocalR2Staging:
    """Manages locally staged R2 content-addressed objects."""

    def __init__(self, root_dir: Path | str):
        self.root = Path(root_dir).resolve()
        self.bodies_dir = self.root / "bodies" / "sha256"
        self.bodies_dir.mkdir(parents=True, exist_ok=True)
        self._staged_digests: set[str] = set()

    @property
    def staged_count(self) -> int:
        return len(self._staged_digests)

    def is_pdf(self, data: bytes) -> bool:
        return data.startswith(PDF_MAGIC)

    def compute_sha256(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def stage_bytes(
        self,
        data: bytes,
        *,
        is_pdf: bool | None = None,
        compress_gzip: bool = True,
    ) -> dict[str, Any]:
        """Stage raw bytes into local R2 CAS layout.

        PDFs are staged uncompressed as .pdf for HTTP 206 byte-range streaming.
        Non-PDFs are gzipped as .gz by default.
        """
        digest = self.compute_sha256(data)
        prefix = digest[:2]
        shard_dir = self.bodies_dir / prefix
        shard_dir.mkdir(parents=True, exist_ok=True)

        is_pdf_content = self.is_pdf(data) if is_pdf is None else is_pdf

        if is_pdf_content:
            ext = "pdf"
            dest_path = shard_dir / f"{digest}.pdf"
            dest_bytes = data
        else:
            ext = "gz"
            dest_path = shard_dir / f"{digest}.gz"
            if compress_gzip:
                dest_bytes = gzip.compress(data, mtime=0)
            else:
                dest_bytes = data

        if not dest_path.exists():
            dest_path.write_bytes(dest_bytes)

        rel_uri = f"bodies/sha256/{prefix}/{digest}.{ext}"
        self._staged_digests.add(digest)

        return {
            "sha256": digest,
            "uri": rel_uri,
            "rel_path": rel_uri,
            "abs_path": dest_path,
            "raw_bytes": len(data),
            "stored_bytes": len(dest_bytes),
            "is_pdf": is_pdf_content,
            "extension": ext,
        }

    def stage_file(self, source_path: Path | str) -> dict[str, Any]:
        """Read a file from disk and stage it into local CAS."""
        data = Path(source_path).read_bytes()
        return self.stage_bytes(data)

    def get_body_bytes(self, digest: str, *, is_pdf: bool = False) -> bytes:
        """Retrieve and decompress (if .gz) stored payload from local CAS."""
        prefix = digest[:2]
        ext = "pdf" if is_pdf else "gz"
        path = self.bodies_dir / prefix / f"{digest}.{ext}"
        if not path.exists():
            # Fallback check other extension
            alt_ext = "gz" if is_pdf else "pdf"
            alt_path = self.bodies_dir / prefix / f"{digest}.{alt_ext}"
            if alt_path.exists():
                path = alt_path
                ext = alt_ext
            else:
                raise FileNotFoundError(f"CAS object {digest} not found in {self.bodies_dir}")

        raw = path.read_bytes()
        if ext == "gz":
            try:
                return gzip.decompress(raw)
            except gzip.BadGzipFile:
                return raw
        return raw

    def has_body(self, digest: str) -> bool:
        prefix = digest[:2]
        return (
            (self.bodies_dir / prefix / f"{digest}.gz").exists()
            or (self.bodies_dir / prefix / f"{digest}.pdf").exists()
        )

    def verify_cas_integrity(self) -> tuple[bool, list[str]]:
        """Verify all staged files have valid names, shards, and matching SHA-256 digests."""
        errors: list[str] = []
        for p in self.bodies_dir.glob("*/*"):
            if not p.is_file():
                continue
            name = p.name
            parts = name.split(".")
            if len(parts) != 2 or parts[1] not in ("gz", "pdf"):
                errors.append(f"Invalid file naming convention: {p}")
                continue
            digest = parts[0]
            if len(digest) != 64:
                errors.append(f"Invalid digest length in filename: {p}")
                continue
            shard = p.parent.name
            if shard != digest[:2]:
                errors.append(f"Shard mismatch: {shard} != {digest[:2]} for {p}")
                continue

            # Verify contents
            content = p.read_bytes()
            if parts[1] == "pdf":
                if not content.startswith(PDF_MAGIC):
                    errors.append(f"PDF object does not start with %PDF- header: {p}")
                calculated = hashlib.sha256(content).hexdigest()
                if calculated != digest:
                    errors.append(f"SHA-256 digest mismatch: expected {digest}, got {calculated}")
            elif parts[1] == "gz":
                try:
                    decompressed = gzip.decompress(content)
                    calculated = hashlib.sha256(decompressed).hexdigest()
                    if calculated != digest:
                        errors.append(f"Decompressed SHA-256 mismatch: expected {digest}, got {calculated}")
                except Exception as e:
                    errors.append(f"Gzip corruption in {p}: {e}")

        return (len(errors) == 0, errors)
