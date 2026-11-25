"""Content-addressed 6-tuple SQLite cache for DocMeta V7.2 3-family labeling.

Follows the `bespokelabsai/curator` pattern: the cache key is strictly
`(input_sha256, codebook_version, model_id, prompt_hash, schema_hash, slice_spec, rollout_id)`
and deliberately excludes any downstream `parse()` or post-processing version so
parser fixes replay at 100% cache hit rate with zero CLI re-invocations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any


CACHE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS completions (
    input_sha256 TEXT NOT NULL,
    codebook_version TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    schema_hash TEXT NOT NULL,
    slice_spec TEXT NOT NULL,
    rollout_id INTEGER NOT NULL DEFAULT 0,
    cache_key_hash TEXT NOT NULL,
    family TEXT,
    stage TEXT,
    raw_text TEXT NOT NULL,
    extracted_json_str TEXT,
    latency_ms REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    returncode INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    PRIMARY KEY (
        input_sha256,
        codebook_version,
        model_id,
        prompt_hash,
        schema_hash,
        slice_spec,
        rollout_id
    )
);

CREATE INDEX IF NOT EXISTS idx_completions_key_hash
ON completions (cache_key_hash);
"""


def discover_main_checkout_root(start: Path | None = None) -> Path:
    """Resolve `<main checkout>` from `start` without spawning subprocesses (worktree-aware)."""
    here = (start or Path(__file__)).resolve()
    for anc in (here, *here.parents):
        dot_git = anc / ".git"
        if dot_git.is_dir():
            return anc
        if dot_git.is_file():
            try:
                raw = dot_git.read_text(encoding="utf-8", errors="ignore").strip()
                if raw.startswith("gitdir:"):
                    gitdir = (anc / raw.split(":", 1)[1].strip()).resolve()
                    commondir_f = gitdir / "commondir"
                    if commondir_f.is_file():
                        common = (gitdir / commondir_f.read_text(encoding="utf-8").strip()).resolve()
                        if common.name == ".git":
                            return common.parent
            except OSError:
                pass
            return anc
    return here.parents[5] if len(here.parents) > 5 else here.parent


def default_cache_path() -> Path:
    """Return `<main checkout>/.cache/archive-release/docmeta-v7-factory/cache.sqlite`."""
    return discover_main_checkout_root() / ".cache" / "archive-release" / "docmeta-v7-factory" / "cache.sqlite"


def sha256_text(text: str) -> str:
    """Compute hex SHA-256 of UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json_sha256(obj: Any) -> str:
    """Compute deterministic SHA-256 over canonical JSON (sorted keys, compact separators)."""
    serialized = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_text(serialized)


@dataclass(frozen=True)
class CacheKey:
    """6-tuple content address (+ `rollout_id` for bounded parse retries).

    Intentionally omits `parse()` / normalization versions.
    """

    input_sha256: str
    codebook_version: str
    model_id: str
    prompt_hash: str
    schema_hash: str
    slice_spec: str
    rollout_id: int = 0

    def as_tuple(self) -> tuple[str, str, str, str, str, str, int]:
        return (
            self.input_sha256,
            self.codebook_version,
            self.model_id,
            self.prompt_hash,
            self.schema_hash,
            self.slice_spec,
            int(self.rollout_id),
        )

    def digest(self) -> str:
        return canonical_json_sha256(list(self.as_tuple()))

    def with_rollout(self, rollout_id: int) -> "CacheKey":
        return CacheKey(
            input_sha256=self.input_sha256,
            codebook_version=self.codebook_version,
            model_id=self.model_id,
            prompt_hash=self.prompt_hash,
            schema_hash=self.schema_hash,
            slice_spec=self.slice_spec,
            rollout_id=rollout_id,
        )


def make_cache_key(
    *,
    input_text: str | None = None,
    input_sha256: str | None = None,
    codebook_version: str,
    model_id: str,
    prompt_text: str | None = None,
    prompt_hash: str | None = None,
    schema: dict[str, Any] | None = None,
    schema_hash: str | None = None,
    slice_spec: str = "blind_text_only",
    rollout_id: int = 0,
) -> CacheKey:
    """Build a `CacheKey` from raw inputs or precomputed SHA-256 digests."""
    if input_sha256 is None:
        if input_text is None:
            raise ValueError("Either input_text or input_sha256 must be provided")
        input_sha256 = sha256_text(input_text)
    if prompt_hash is None:
        if prompt_text is None:
            raise ValueError("Either prompt_text or prompt_hash must be provided")
        prompt_hash = sha256_text(prompt_text)
    if schema_hash is None:
        if schema is None:
            raise ValueError("Either schema or schema_hash must be provided")
        schema_hash = canonical_json_sha256(schema)
    return CacheKey(
        input_sha256=input_sha256,
        codebook_version=str(codebook_version),
        model_id=str(model_id),
        prompt_hash=prompt_hash,
        schema_hash=schema_hash,
        slice_spec=str(slice_spec),
        rollout_id=int(rollout_id),
    )


@dataclass
class CacheEntry:
    """Stored raw completion record in `SixTupleCache`."""

    key: CacheKey
    raw_text: str
    extracted_json_str: str | None
    latency_ms: float
    created_at: str
    returncode: int
    error: str | None = None
    family: str | None = None
    stage: str | None = None

    @property
    def cache_key_hash(self) -> str:
        return self.key.digest()


class SixTupleCache:
    """Thread-safe SQLite 6-tuple cache excluding `parse()` version."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_cache_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA busy_timeout=30000;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.executescript(CACHE_SCHEMA_SQL)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "SixTupleCache":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def get(self, key: CacheKey) -> CacheEntry | None:
        """Fetch raw cached completion for `key` if present."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    input_sha256, codebook_version, model_id, prompt_hash,
                    schema_hash, slice_spec, rollout_id,
                    raw_text, extracted_json_str, latency_ms, created_at,
                    returncode, error, family, stage
                FROM completions
                WHERE input_sha256 = ?
                  AND codebook_version = ?
                  AND model_id = ?
                  AND prompt_hash = ?
                  AND schema_hash = ?
                  AND slice_spec = ?
                  AND rollout_id = ?
                """,
                key.as_tuple(),
            ).fetchone()
            if row is None:
                self._misses += 1
                return None
            self._hits += 1
            return CacheEntry(
                key=CacheKey(
                    input_sha256=row["input_sha256"],
                    codebook_version=row["codebook_version"],
                    model_id=row["model_id"],
                    prompt_hash=row["prompt_hash"],
                    schema_hash=row["schema_hash"],
                    slice_spec=row["slice_spec"],
                    rollout_id=int(row["rollout_id"]),
                ),
                raw_text=row["raw_text"],
                extracted_json_str=row["extracted_json_str"],
                latency_ms=float(row["latency_ms"]),
                created_at=row["created_at"],
                returncode=int(row["returncode"]),
                error=row["error"],
                family=row["family"],
                stage=row["stage"],
            )

    def put(self, entry: CacheEntry) -> None:
        """Upsert a raw completion entry into the SQLite cache."""
        created_at = entry.created_at or datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO completions (
                    input_sha256, codebook_version, model_id, prompt_hash,
                    schema_hash, slice_spec, rollout_id, cache_key_hash,
                    family, stage, raw_text, extracted_json_str,
                    latency_ms, created_at, returncode, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.key.input_sha256,
                    entry.key.codebook_version,
                    entry.key.model_id,
                    entry.key.prompt_hash,
                    entry.key.schema_hash,
                    entry.key.slice_spec,
                    int(entry.key.rollout_id),
                    entry.cache_key_hash,
                    entry.family,
                    entry.stage,
                    entry.raw_text,
                    entry.extracted_json_str,
                    float(entry.latency_ms),
                    created_at,
                    int(entry.returncode),
                    entry.error,
                ),
            )
            self._conn.commit()

    def delete(self, key: CacheKey) -> bool:
        """Delete a specific entry by `CacheKey`. Returns True if a row was removed."""
        with self._lock:
            cur = self._conn.execute(
                """
                DELETE FROM completions
                WHERE input_sha256 = ?
                  AND codebook_version = ?
                  AND model_id = ?
                  AND prompt_hash = ?
                  AND schema_hash = ?
                  AND slice_spec = ?
                  AND rollout_id = ?
                """,
                key.as_tuple(),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS cnt FROM completions").fetchone()
            return int(row["cnt"]) if row is not None else 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS cnt FROM completions").fetchone()
            total = int(row["cnt"]) if row is not None else 0
            return {
                "db_path": str(self.db_path),
                "total_entries": total,
                "hits": self._hits,
                "misses": self._misses,
            }


__all__ = [
    "CacheEntry",
    "CacheKey",
    "SixTupleCache",
    "canonical_json_sha256",
    "default_cache_path",
    "discover_main_checkout_root",
    "make_cache_key",
    "sha256_text",
]
