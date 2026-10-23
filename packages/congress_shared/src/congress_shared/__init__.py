"""Shared primitives for Congressional Tech packages."""
from __future__ import annotations

from congress_shared.custody import (
    CHUNK_BYTES,
    VerifiedFile,
    canonical_json_bytes,
    copy_checked,
    custody_identity,
    file_identity,
    issue_verified_file,
    iter_canonical_digest,
    read_bound_receipt,
    verify_local_file,
    write_atomic_bytes,
    write_atomic_json,
    write_bound_receipt,
)
from congress_shared.dates import (
    congress_to_years,
    parse_utc_timestamp,
    year_to_congress,
)
from congress_shared.storage import R2Config, connect_r2

__all__ = [
    "CHUNK_BYTES",
    "R2Config",
    "VerifiedFile",
    "canonical_json_bytes",
    "congress_to_years",
    "connect_r2",
    "copy_checked",
    "custody_identity",
    "file_identity",
    "issue_verified_file",
    "iter_canonical_digest",
    "parse_utc_timestamp",
    "read_bound_receipt",
    "verify_local_file",
    "write_atomic_bytes",
    "write_atomic_json",
    "write_bound_receipt",
    "year_to_congress",
]
