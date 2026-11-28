"""Incremental Apple Silicon EmbeddingGemma 2 passage delta encoding and serving overlay assembly.

This module promotes the three-stage incremental passage embedding workflow into a tested
library and CLI without adding macOS-only dependencies to ``congressional-tech``:

1. ``compute_source_delta`` compares an earlier prepared release and its serving passage
   Parquet shards against a newly prepared release. It selects only newly added documents,
   documents whose body presence or ``text_sha256`` changed, and textless (``title``)
   documents whose title changed. Body-identical documents reuse their existing passage
   vectors verbatim (even when ``title`` metadata improves), flagging any whose
   ``page_offsets`` changed for excerpt/page re-anchoring.
2. ``encode_delta`` lazily imports Apple Silicon ``fast_embeddinggemma_2`` and
   ``fast_shared.parquet_pipeline`` (from ``fast-silicon``) to encode only the delta
   documents into validated ``float16[512]`` unit-norm passages obeying SpicyEngine's
   span and coverage invariants (``MAX_PASSAGE_CHARS = 16000``).
3. ``prepare_serving`` assembles the new serving passage directory by hard-linking
   unchanged base shards directly, stream-filtering obsolete documents and re-anchoring
   changed ``page_offsets`` on modified shards, and attaching ``excerpt``, ``page``, and
   ``page_at`` to the newly encoded delta Parquet.
4. ``verify_vector_parity`` checks float32 cosine similarity between a candidate vector
   Parquet and a reference vector Parquet on matched passage coordinates.
"""

from __future__ import annotations

import argparse
import array
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

SOURCE_ID = "archive-documents"
EMBEDDING_DIMENSIONS = 512
MAX_PASSAGE_CHARS = 16000
MAX_EXCERPT_CHARS = 280
MAX_TITLE_PREFIX_TOKENS = 64
MAX_CHUNK_TOKENS = 512
CHUNK_OVERLAP_TOKENS = 51
VECTOR_NORM_MIN = 0.99
VECTOR_NORM_MAX = 1.01
DEFAULT_BATCH_ROWS = 32
DEFAULT_ENCODE_BATCH_ROWS = 4096
DEFAULT_PARITY_MIN_COSINE = 0.999998

DELTA_SOURCE_COLUMNS = ("source_id", "member_key", "body", "title", "text_sha256")
DELTA_PREPARED_SCHEMA = pa.schema(
    [(name, pa.string()) for name in ("source_id", "member_key", "source_field", "text_sha256", "content", "heading")]
)


def vector_parquet_schema(dimensions: int = EMBEDDING_DIMENSIONS) -> pa.Schema:
    """Return the Arrow schema emitted by ``embed_parquet`` for float16 passage vectors."""
    return pa.schema(
        [
            ("source_id", pa.string()),
            ("member_key", pa.string()),
            ("source_field", pa.string()),
            ("text_sha256", pa.string()),
            ("chunk_index", pa.int32()),
            ("char_start", pa.int32()),
            ("char_end", pa.int32()),
            ("token_count", pa.int32()),
            ("vector", pa.list_(pa.field("element", pa.float16()), dimensions)),
        ]
    )


def _hex(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return str(value)


def _cleanup_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _serving_codecs(schema: pa.Schema) -> tuple[list[str], dict[str, str]]:
    metadata = [name for name in schema.names if name != "vector"]
    codecs = {name: ("zstd" if name != "vector" else "NONE") for name in schema.names}
    if "vector" in schema.names:
        vec_type = schema.field("vector").type
        if pa.types.is_fixed_size_list(vec_type) or pa.types.is_list(vec_type) or pa.types.is_large_list(vec_type):
            codecs[f"vector.list.{vec_type.value_field.name}"] = "NONE"
    return metadata, codecs


def _scan_serving_part(args: tuple[str, str]) -> tuple[str, int, dict[str, tuple[str, str | None]]]:
    path_str, expected_source_id = args
    path = Path(path_str)
    pf = pq.ParquetFile(path)
    out: dict[str, tuple[str, str | None]] = {}
    rows = 0
    for batch in pf.iter_batches(batch_size=8192, columns=["source_id", "member_key", "source_field", "text_sha256"]):
        rows += batch.num_rows
        py = batch.to_pydict()
        for src, key, field, digest in zip(
            py["source_id"], py["member_key"], py["source_field"], py["text_sha256"], strict=True
        ):
            if src != expected_source_id:
                raise ValueError(f"Unexpected source_id {src!r} in serving shard {path.name} for {key}")
            norm_digest = _hex(digest)
            prev = out.get(key)
            if prev is None:
                out[key] = (field, norm_digest)
            elif prev != (field, norm_digest):
                raise ValueError(
                    f"Inconsistent serving metadata for {key} in {path.name}: {prev!r} vs {(field, norm_digest)!r}"
                )
    return path.name, rows, out


def _scan_prepared_part(
    args: tuple[str, bool, str],
) -> tuple[str, int, dict[str, tuple[str, str | None, bool, bytes, str]]]:
    path_str, check_body_ws, expected_source_id = args
    path = Path(path_str)
    pf = pq.ParquetFile(path)
    schema_names = set(pf.schema_arrow.names)
    has_text_status = "text_status" in schema_names
    cols = ["source_id", "member_key", "title", "text_sha256", "page_offsets"]
    if has_text_status:
        cols.append("text_status")
    if check_body_ws:
        cols.append("body")

    out: dict[str, tuple[str, str | None, bool, bytes, str]] = {}
    ws_only_selected = 0
    for batch in pf.iter_batches(batch_size=64, columns=cols):
        py = batch.to_pydict()
        statuses = py["text_status"] if has_text_status else [None] * batch.num_rows
        bodies = py["body"] if check_body_ws else [None] * batch.num_rows
        for src, key, title, digest, offsets, status, body in zip(
            py["source_id"],
            py["member_key"],
            py["title"],
            py["text_sha256"],
            py["page_offsets"],
            statuses,
            bodies,
            strict=True,
        ):
            if src != expected_source_id:
                raise ValueError(f"Unexpected source_id {src!r} in prepared shard {path.name} for {key}")
            if key in out:
                raise ValueError(f"Duplicate member_key {key!r} in prepared shard {path.name}")
            if check_body_ws:
                has_body = bool(body and not body.isspace())
                if status == "Selected text" and not has_body:
                    ws_only_selected += 1
            else:
                has_body = status == "Selected text"
            if offsets:
                off_sig = hashlib.blake2b(array.array("i", offsets).tobytes(), digest_size=16).digest()
            else:
                off_sig = b""
            out[key] = (title or "", _hex(digest), has_body, off_sig, path.name)
    return path.name, ws_only_selected, out


def _map_tasks(fn: Callable[[Any], Any], items: list[Any], workers: int) -> list[Any]:
    if workers <= 1 or len(items) <= 1:
        return [fn(item) for item in items]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))


def compute_source_delta(
    old_prepared: str | Path,
    old_serving: str | Path,
    new_prepared: str | Path,
    out_dir: str | Path,
    *,
    workers: int = 1,
    source_id: str = SOURCE_ID,
) -> dict[str, Any]:
    """Compute the incremental passage delta between two prepared releases.

    Writes ``delta.json`` and ``delta.parquet`` atomically inside ``out_dir`` and returns
    the ``delta.json`` payload. Re-encodes only newly added documents, documents whose body
    presence or ``text_sha256`` changed, and textless (``source_field='title'``) documents
    whose title changed. Body-identical documents are reused verbatim, flagging any whose
    ``page_offsets`` changed into ``reanchor``.
    """
    if workers < 1:
        raise ValueError(f"workers must be >= 1, got {workers}")

    old_prepared_dir = Path(old_prepared)
    old_serving_dir = Path(old_serving)
    new_prepared_dir = Path(new_prepared)
    output_dir = Path(out_dir)

    t0 = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=True)

    serving_files = sorted(old_serving_dir.glob("*.parquet"))
    old_prep_files = sorted(old_prepared_dir.glob("*.parquet"))
    new_prep_files = sorted(new_prepared_dir.glob("*.parquet"))
    if not serving_files:
        raise ValueError(f"No Parquet files in old_serving directory: {old_serving_dir}")
    if not old_prep_files:
        raise ValueError(f"No Parquet files in old_prepared directory: {old_prepared_dir}")
    if not new_prep_files:
        raise ValueError(f"No Parquet files in new_prepared directory: {new_prepared_dir}")

    serving: dict[str, tuple[str, str | None, str]] = {}
    old_passages = 0
    for name, rows, part_map in _map_tasks(
        _scan_serving_part, [(str(p), source_id) for p in serving_files], workers
    ):
        old_passages += rows
        for key, (field, digest) in part_map.items():
            if key in serving:
                raise ValueError(
                    f"Duplicate member_key across serving shards: {key} ({serving[key][2]} vs {name})"
                )
            serving[key] = (field, digest, name)

    old_docs: dict[str, tuple[str, str | None, bool, bytes, str]] = {}
    for name, _, part_map in _map_tasks(
        _scan_prepared_part, [(str(p), False, source_id) for p in old_prep_files], workers
    ):
        for key, val in part_map.items():
            if key in old_docs:
                raise ValueError(f"Duplicate member_key across old_prepared shards: {key} ({old_docs[key][4]} vs {name})")
            old_docs[key] = val

    new_docs: dict[str, tuple[str, str | None, bool, bytes, str]] = {}
    ws_only_selected = 0
    for name, ws_cnt, part_map in _map_tasks(
        _scan_prepared_part, [(str(p), True, source_id) for p in new_prep_files], workers
    ):
        ws_only_selected += ws_cnt
        for key, val in part_map.items():
            if key in new_docs:
                raise ValueError(f"Duplicate member_key across new_prepared shards: {key} ({new_docs[key][4]} vs {name})")
            new_docs[key] = val

    if serving.keys() != old_docs.keys():
        raise ValueError(
            f"Old serving keys ({len(serving)}) != old prepared keys ({len(old_docs)})"
        )

    obsolete: dict[str, list[str]] = defaultdict(list)
    needed: dict[str, list[str]] = defaultdict(list)
    reanchor: dict[str, list[str]] = defaultdict(list)
    reasons: Counter[str] = Counter()
    reused_body_title_upgraded = 0
    textless_title_equals_key: list[list[str]] = []

    old_keys = serving.keys()
    new_keys = new_docs.keys()

    for key in sorted(old_keys - new_keys):
        obsolete[serving[key][2]].append(key)
        reasons["removed"] += 1

    for key in sorted(new_keys - old_keys):
        new_title, _, new_has_body, _, new_part = new_docs[key]
        needed[new_part].append(key)
        reasons["added_body" if new_has_body else "added_title"] += 1
        if not new_has_body and (not new_title.strip() or new_title == key):
            textless_title_equals_key.append([key, new_title])

    for key in sorted(old_keys & new_keys):
        srv_field, srv_sha, srv_part = serving[key]
        old_title, old_sha, _, old_offsets, _ = old_docs[key]
        new_title, new_sha, new_has_body, new_offsets, new_part = new_docs[key]

        if srv_field == "body":
            if new_has_body and new_sha is not None and new_sha == old_sha and new_sha == srv_sha:
                reasons["reused_body"] += 1
                if new_title != old_title:
                    reused_body_title_upgraded += 1
                if new_offsets != old_offsets:
                    reanchor[srv_part].append(key)
                    reasons["reanchor_page_offsets"] += 1
            else:
                obsolete[srv_part].append(key)
                needed[new_part].append(key)
                reasons["changed_body" if new_has_body else "body_lost_to_title"] += 1
                if not new_has_body and (not new_title.strip() or new_title == key):
                    textless_title_equals_key.append([key, new_title])
        elif srv_field == "title":
            if new_has_body:
                obsolete[srv_part].append(key)
                needed[new_part].append(key)
                reasons["title_gained_body"] += 1
            elif new_title != old_title:
                obsolete[srv_part].append(key)
                needed[new_part].append(key)
                reasons["changed_textless_title"] += 1
                if not new_title.strip() or new_title == key:
                    textless_title_equals_key.append([key, new_title])
            else:
                reasons["reused_title"] += 1
        else:
            raise ValueError(f"Unexpected source_field {srv_field!r} for {key}")

    reused_total = reasons["reused_body"] + reasons["reused_title"]
    added_total = reasons["added_body"] + reasons["added_title"]
    changed_total = (
        reasons["changed_body"]
        + reasons["body_lost_to_title"]
        + reasons["title_gained_body"]
        + reasons["changed_textless_title"]
    )
    delta_total = added_total + changed_total
    if len(new_docs) != reused_total + delta_total:
        raise ValueError(f"Accounting mismatch: new={len(new_docs)}, reused={reused_total}, delta={delta_total}")
    if sum(len(v) for v in needed.values()) != delta_total:
        raise ValueError("Accounting mismatch between needed shards and delta_total")
    if sum(len(v) for v in obsolete.values()) != reasons["removed"] + changed_total:
        raise ValueError("Accounting mismatch between obsolete shards and removed+changed")

    summary = {
        "old_documents": len(old_docs),
        "old_passages": old_passages,
        "new_documents": len(new_docs),
        "added": added_total,
        "removed": reasons["removed"],
        "changed": changed_total,
        "reused": reused_total,
        "reused_body": reasons["reused_body"],
        "reused_title": reasons["reused_title"],
        "reused_body_title_upgraded": reused_body_title_upgraded,
        "reanchor_page_offsets": reasons["reanchor_page_offsets"],
        "ws_only_selected_text": ws_only_selected,
        "textless_title_equals_key": len(textless_title_equals_key),
        "delta_total": delta_total,
        "changed_input_shards": len(needed),
        "obsolete_serving_shards": len(obsolete),
        "reanchor_serving_shards": len(reanchor),
        "elapsed_s": round(time.monotonic() - t0, 2),
    }
    payload = {
        "summary": summary,
        "reasons": dict(reasons),
        "textless_title_equals_key": textless_title_equals_key,
        "needed": dict(needed),
        "obsolete": dict(obsolete),
        "reanchor": dict(reanchor),
    }

    fields = list(DELTA_SOURCE_COLUMNS)
    schema = pq.read_schema(new_prep_files[0])
    subset = pa.schema([schema.field(f) for f in fields])
    written = 0
    tmp_parquet = output_dir / f".delta.parquet.tmp-{os.getpid()}"
    try:
        with pq.ParquetWriter(tmp_parquet, subset, compression="zstd") as writer:
            for name in sorted(needed):
                keys = needed[name]
                keyset = pa.array(keys)
                pf = pq.ParquetFile(new_prepared_dir / name)
                for rg in range(pf.num_row_groups):
                    ids = pf.read_row_group(rg, columns=["member_key"]).column(0)
                    if not pc.any(pc.is_in(ids, value_set=keyset)).as_py():
                        continue
                    for batch in pf.iter_batches(batch_size=8, row_groups=[rg], columns=fields):
                        picked = batch.filter(pc.is_in(batch.column("member_key"), value_set=keyset))
                        if len(picked):
                            writer.write_batch(picked)
                            written += len(picked)
        if written != delta_total:
            raise ValueError(f"Delta extraction wrote {written} rows, expected {delta_total}")
        os.chmod(tmp_parquet, 0o644)
        os.replace(tmp_parquet, output_dir / "delta.parquet")
    except BaseException:
        tmp_parquet.unlink(missing_ok=True)
        raise

    summary["elapsed_s"] = round(time.monotonic() - t0, 2)
    _atomic_write_json(output_dir / "delta.json", payload)
    return payload


def format_header(tokenizer: Any, title: str, *, max_tokens: int = MAX_TITLE_PREFIX_TOKENS) -> str:
    """Truncate a document title prefix to at most ``max_tokens`` tokenizer tokens."""
    if not title or max_tokens <= 0:
        return ""
    if len(title.encode("utf-8")) <= max_tokens:
        return title
    inner = getattr(tokenizer, "_tok", tokenizer)
    encoded = inner.encode(title, add_special_tokens=False)
    if len(encoded.ids) <= max_tokens:
        return title
    return title[: encoded.offsets[max_tokens - 1][1]]


def prepare_delta_input(
    source_parquet: str | Path,
    dest_parquet: str | Path,
    tokenizer: Any,
    *,
    source_id: str = SOURCE_ID,
    max_title_tokens: int = MAX_TITLE_PREFIX_TOKENS,
) -> tuple[dict[str, tuple[str, int]], list[str], list[str]]:
    """Transform ``delta.parquet`` into ``embed_parquet`` input with ``content`` and ``heading``."""
    source_path = Path(source_parquet)
    dest_path = Path(dest_parquet)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    columns = list(DELTA_SOURCE_COLUMNS)
    expected: dict[str, tuple[str, int]] = {}
    missing: list[str] = []
    fallback_id_titles: list[str] = []
    tmp_path = dest_path.with_name(f".{dest_path.name}.tmp-{os.getpid()}")

    try:
        with pq.ParquetWriter(tmp_path, DELTA_PREPARED_SCHEMA, compression="zstd", compression_level=1) as writer:
            for batch in pq.ParquetFile(source_path).iter_batches(batch_size=24, columns=columns):
                rows = []
                for row in batch.to_pylist():
                    key = row["member_key"]
                    if row["source_id"] != source_id:
                        raise ValueError(f"Unexpected source_id {row['source_id']!r} for {key}")
                    if key in expected or key in missing:
                        raise ValueError(f"Duplicate member_key {key!r} in {source_path.name}")
                    title = row["title"] or ""
                    body = row["body"] or ""
                    if body and not body.isspace():
                        field = "body"
                        value = body
                        header = format_header(tokenizer, title, max_tokens=max_title_tokens)
                    elif title.strip():
                        if title == key:
                            fallback_id_titles.append(key)
                        field = "title"
                        value = title
                        header = ""
                    else:
                        missing.append(key)
                        continue
                    expected[key] = (field, len(value))
                    rows.append(
                        {
                            "source_id": row["source_id"],
                            "member_key": key,
                            "source_field": field,
                            "text_sha256": _hex(row["text_sha256"]),
                            "content": value,
                            "heading": header,
                        }
                    )
                if rows:
                    writer.write_table(pa.Table.from_pylist(rows, schema=DELTA_PREPARED_SCHEMA))
        os.replace(tmp_path, dest_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    return expected, missing, fallback_id_titles


def _try_import_numpy() -> Any | None:
    try:
        return importlib.import_module("numpy")
    except ImportError:
        return None


def _check_vector_batch(
    vector_col: pa.Array,
    *,
    dimensions: int,
    norm_min: float,
    norm_max: float,
    np_mod: Any | None,
) -> None:
    if np_mod is not None:
        arr = vector_col.flatten().to_numpy(zero_copy_only=False).astype(np_mod.float32).reshape(-1, dimensions)
        if not bool(np_mod.all(np_mod.isfinite(arr))):
            raise ValueError("Non-finite vector component")
        norms = np_mod.linalg.norm(arr, axis=1)
        if not bool(np_mod.all((norms > norm_min) & (norms < norm_max))):
            raise ValueError(f"Invalid vector norm range: {float(norms.min()):.6f}..{float(norms.max()):.6f}")
        return

    for row in vector_col.to_pylist():
        if row is None or len(row) != dimensions:
            raise ValueError(f"Vector row has invalid length (expected {dimensions})")
        sq_sum = 0.0
        for component in row:
            val = float(component)
            if not math.isfinite(val):
                raise ValueError("Non-finite vector component")
            sq_sum += val * val
        norm = math.sqrt(sq_sum)
        if not (norm_min < norm < norm_max):
            raise ValueError(f"Invalid vector norm: {norm:.6f} (expected {norm_min}..{norm_max})")


def check_vectors(
    vectors_parquet: str | Path,
    expected: dict[str, tuple[str, int]],
    *,
    dimensions: int = EMBEDDING_DIMENSIONS,
    max_passage_chars: int = MAX_PASSAGE_CHARS,
    max_chunk_tokens: int = MAX_CHUNK_TOKENS,
    norm_min: float = VECTOR_NORM_MIN,
    norm_max: float = VECTOR_NORM_MAX,
) -> tuple[int, int, int]:
    """Validate float16 vector type, finiteness, unit norms, span bounds, and 1:1 coverage."""
    pf = pq.ParquetFile(vectors_parquet)
    if "vector" not in pf.schema_arrow.names:
        raise ValueError(f"Missing vector column in {vectors_parquet}")
    vec_type = pf.schema_arrow.field("vector").type
    if not (
        pa.types.is_fixed_size_list(vec_type)
        and vec_type.value_type == pa.float16()
        and vec_type.list_size == dimensions
    ):
        raise ValueError(
            f"Unexpected vector column type {vec_type!r}; expected fixed_size_list<float16>[{dimensions}]"
        )

    if not expected:
        if pf.metadata.num_rows != 0:
            raise ValueError(f"Expected 0 vector rows for empty delta, got {pf.metadata.num_rows}")
        return 0, 0, 0

    np_mod = _try_import_numpy()
    ranges: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    vector_count = 0
    tokens = 0
    max_span_chars = 0

    for batch in pf.iter_batches(
        batch_size=1024,
        columns=["member_key", "source_field", "chunk_index", "char_start", "char_end", "token_count", "vector"],
    ):
        _check_vector_batch(
            batch.column("vector"),
            dimensions=dimensions,
            norm_min=norm_min,
            norm_max=norm_max,
            np_mod=np_mod,
        )
        py = batch.select(
            ["member_key", "source_field", "chunk_index", "char_start", "char_end", "token_count"]
        ).to_pydict()
        for key, field, idx, lo, hi, count in zip(*py.values(), strict=True):
            if key not in expected:
                raise ValueError(f"Unexpected member_key in vector output: {key!r}")
            exp_field, exp_len = expected[key]
            span = hi - lo
            if span > max_span_chars:
                max_span_chars = span
            if field != exp_field or not (0 <= lo < hi <= exp_len) or not (0 < count <= max_chunk_tokens):
                raise ValueError(
                    f"Invalid passage for {key}: field={field!r}, span=[{lo}:{hi}] (len={exp_len}), "
                    f"token_count={count}, expected={expected[key]!r}"
                )
            if span > max_passage_chars:
                raise ValueError(
                    f"Passage exceeds MAX_PASSAGE_CHARS ({max_passage_chars}): {key} {field} [{lo}:{hi}] ({span})"
                )
            ranges[key].append((idx, lo, hi))
            tokens += count
        vector_count += batch.num_rows

    if expected.keys() != ranges.keys():
        missing_count = len(expected.keys() - ranges.keys())
        extra_count = len(ranges.keys() - expected.keys())
        raise ValueError(
            f"Vector coverage mismatch: missing={missing_count}, extra={extra_count}"
        )

    for key, spans in ranges.items():
        end = 0
        for i, (idx, lo, hi) in enumerate(sorted(spans)):
            if i != idx or lo > end or hi <= end:
                raise ValueError(
                    f"Gap or repeated chunk window for {key}: expected index={i}, got idx={idx}, "
                    f"span=[{lo}:{hi}], prev_end={end}"
                )
            end = hi
        if end != expected[key][1]:
            raise ValueError(f"Missing trailing text for {key}: covered up to {end}, expected {expected[key][1]}")

    return vector_count, tokens, max_span_chars


def _load_fast_silicon(fast_silicon_root: str | Path | None = None) -> tuple[Any, Callable[..., Any]]:
    """Lazily load Apple Silicon ``FastEmbeddingGemma2`` and ``embed_parquet``."""
    root_val = fast_silicon_root or os.environ.get("FAST_SILICON_ROOT")
    if root_val:
        root = Path(root_val).expanduser().resolve()
        for rel in ("packages/fast-embeddinggemma-2/src", "packages/fast-shared/src"):
            candidate = str(root / rel)
            if Path(candidate).is_dir() and candidate not in sys.path:
                sys.path.insert(0, candidate)
    try:
        emb_mod = importlib.import_module("fast_embeddinggemma_2")
        pipe_mod = importlib.import_module("fast_shared.parquet_pipeline")
        return emb_mod.FastEmbeddingGemma2, pipe_mod.embed_parquet
    except ImportError as exc:
        raise RuntimeError(
            "Apple Silicon delta encoding requires fast-embeddinggemma-2 and fast-shared "
            "(with mlx on Apple Silicon). Run with a fast-silicon Python environment or set "
            "--fast-silicon-root / FAST_SILICON_ROOT."
        ) from exc


def encode_delta(
    delta_parquet: str | Path,
    output_parquet: str | Path,
    *,
    model_home: str | Path | None = None,
    fast_silicon_root: str | Path | None = None,
    mode: str = "hetero",
    dimensions: int = EMBEDDING_DIMENSIONS,
    max_chunk_tokens: int = MAX_CHUNK_TOKENS,
    overlap: int = CHUNK_OVERLAP_TOKENS,
    max_passage_chars: int = MAX_PASSAGE_CHARS,
    batch_rows: int = DEFAULT_BATCH_ROWS,
    encode_batch_rows: int = DEFAULT_ENCODE_BATCH_ROWS,
    work_dir: str | Path | None = None,
    receipt_path: str | Path | None = None,
    source_id: str = SOURCE_ID,
    encoder_factory: Callable[[], Any] | None = None,
    embed_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Encode ``delta.parquet`` into a validated ``float16[dimensions]`` passage vector Parquet."""
    t0 = time.monotonic()
    delta_path = Path(delta_parquet)
    output_path = Path(output_parquet)
    if not delta_path.is_file():
        raise FileNotFoundError(f"Missing delta Parquet: {delta_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    work_root = Path(work_dir) if work_dir is not None else output_path.parent
    work_root.mkdir(parents=True, exist_ok=True)

    pf = pq.ParquetFile(delta_path)
    if pf.metadata.num_rows == 0:
        pending = output_path.with_name(f".{output_path.stem}.pending-{os.getpid()}.parquet")
        try:
            empty_table = vector_parquet_schema(dimensions).empty_table()
            pq.write_table(empty_table, pending, compression="zstd")
            check_vectors(
                pending,
                {},
                dimensions=dimensions,
                max_passage_chars=max_passage_chars,
                max_chunk_tokens=max_chunk_tokens,
            )
            os.chmod(pending, 0o644)
            os.replace(pending, output_path)
        except BaseException:
            _cleanup_path(pending)
            raise
        with output_path.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        receipt = {
            "file": output_path.name,
            "bytes": output_path.stat().st_size,
            "sha256": sha,
            "records": 0,
            "body_records": 0,
            "title_records": 0,
            "fallback_id_titles": [],
            "vectors": 0,
            "tokens": 0,
            "max_span_chars": 0,
            "dimensions": dimensions,
            "mode": mode,
            "prepare_s": 0.0,
            "encode_s": 0.0,
            "total_s": round(time.monotonic() - t0, 3),
            "ane_available": False,
        }
        if receipt_path is not None:
            _atomic_write_json(Path(receipt_path), receipt)
        return receipt

    if encoder_factory is None or embed_fn is None:
        engine_cls, default_embed = _load_fast_silicon(fast_silicon_root)
        if encoder_factory is None:
            resolved_home = Path(model_home) if model_home is not None else None
            encoder_factory = lambda: engine_cls(home=resolved_home, default_mode=mode, warmup=False)  # noqa: E731
        if embed_fn is None:
            embed_fn = default_embed

    # Keep a `.parquet` suffix on the staged file so fast_shared.parquet_pipeline.embed_parquet
    # writes a single Parquet file rather than treating the target path as a sharded directory.
    pending = output_path.with_name(f".{output_path.stem}.pending-{os.getpid()}.parquet")
    with tempfile.TemporaryDirectory(prefix=".delta-encode-", dir=work_root) as tmp_dir:
        prep_path = Path(tmp_dir) / "delta-input.parquet"
        try:
            with encoder_factory() as engine:
                # Capture ane_available before context exit, because close() clears handles.
                ane_available = bool(getattr(engine, "ane_available", False))

                t_prep = time.monotonic()
                expected, missing, fallback_id_titles = prepare_delta_input(
                    delta_path,
                    prep_path,
                    engine.tokenizer,
                    source_id=source_id,
                )
                if missing:
                    raise ValueError(f"Records with no searchable text ({len(missing)}): {missing[:10]}")
                prep_s = round(time.monotonic() - t_prep, 3)

                t_enc = time.monotonic()
                stats = embed_fn(
                    engine,
                    prep_path,
                    pending,
                    text_col="content",
                    header_col="heading",
                    keep_cols=["source_id", "member_key", "source_field", "text_sha256"],
                    add_document_prefix=True,
                    mode=mode,
                    dimensions=dimensions,
                    chunk=True,
                    max_chunk_tokens=max_chunk_tokens,
                    overlap=overlap,
                    skip_empty=True,
                    dtype="float16",
                    batch_rows=batch_rows,
                    encode_batch_rows=encode_batch_rows,
                    progress_every=0,
                )
                encode_s = round(time.monotonic() - t_enc, 3)

                count, tokens, max_span_chars = check_vectors(
                    pending,
                    expected,
                    dimensions=dimensions,
                    max_passage_chars=max_passage_chars,
                    max_chunk_tokens=max_chunk_tokens,
                )
                reported_tokens = getattr(stats, "total_tokens", None)
                if reported_tokens is not None and tokens != reported_tokens:
                    raise ValueError(
                        f"Validated token count ({tokens}) differs from embed_parquet total_tokens ({reported_tokens})"
                    )
                os.chmod(pending, 0o644)
                os.replace(pending, output_path)
        except BaseException:
            _cleanup_path(pending)
            raise

    with output_path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    receipt = {
        "file": output_path.name,
        "bytes": output_path.stat().st_size,
        "sha256": sha,
        "records": len(expected),
        "body_records": sum(1 for field, _ in expected.values() if field == "body"),
        "title_records": sum(1 for field, _ in expected.values() if field == "title"),
        "fallback_id_titles": fallback_id_titles,
        "vectors": count,
        "tokens": tokens,
        "max_span_chars": max_span_chars,
        "dimensions": dimensions,
        "mode": mode,
        "prepare_s": prep_s,
        "encode_s": encode_s,
        "total_s": round(time.monotonic() - t0, 3),
        "ane_available": ane_available,
    }
    if receipt_path is not None:
        _atomic_write_json(Path(receipt_path), receipt)
    return receipt


def text_pages(row: dict[str, Any]) -> tuple[str, str, list[int]]:
    """Decode physical UTF-8 byte ``page_offsets`` into character start offsets."""
    body = row["body"] or ""
    pages = row["page_offsets"] or []
    if not pages:
        return body, row["title"] or "", []
    raw = body.encode("utf-8")
    if pages[0] != 0 or pages != sorted(pages) or pages[-1] > len(raw):
        raise ValueError(f"Invalid physical page offsets for {row['member_key']}")
    chars = [0]
    for start, end in zip(pages, pages[1:]):
        chars.append(chars[-1] + len(raw[start:end].decode("utf-8")))
    return body, row["title"] or "", chars


def preview(record: tuple[str, str, list[int]], field: str, start: int, end: int) -> tuple[str, int | None, int | None]:
    """Compute SpicyEngine's verbatim ``excerpt``, 1-based ``page``, and UTF-8 ``page_at``."""
    body, title, pages = record
    text = body if field == "body" else title
    if field not in ("body", "title") or not (0 <= start < end <= len(text)):
        raise ValueError(f"Passage outside source text: field={field} start={start} end={end} len={len(text)}")
    while start + 1 < end and text[start].isspace():
        start += 1
    if field != "body" or not pages:
        return text[start : min(end, start + MAX_EXCERPT_CHARS)], None, None
    page = bisect_right(pages, start)
    cut = pages[page] if page < len(pages) else len(text)
    excerpt = text[start : min(end, start + MAX_EXCERPT_CHARS, cut)]
    return excerpt, page, len(text[pages[page - 1] : start].encode("utf-8"))


def _read_records(
    documents: Path, locations: dict[str, str], keys: set[str]
) -> dict[str, tuple[str, str, list[int]]]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for key in keys:
        if key not in locations:
            raise ValueError(f"Passage document {key!r} is missing from prepared release")
        grouped[locations[key]].add(key)
    records: dict[str, tuple[str, str, list[int]]] = {}
    for name, wanted in grouped.items():
        source = pq.ParquetFile(documents / name)
        for rg in range(source.num_row_groups):
            ids = source.read_row_group(rg, columns=["member_key"]).column(0)
            if not (set(ids.to_pylist()) & wanted):
                continue
            for batch in source.iter_batches(
                batch_size=12, row_groups=[rg], columns=["member_key", "title", "body", "page_offsets"]
            ):
                for row in batch.to_pylist():
                    if row["member_key"] in wanted:
                        records[row["member_key"]] = text_pages(row)
    if len(records) != len(keys):
        raise ValueError(f"Loaded {len(records)} prepared records, expected {len(keys)}")
    return records


def _process_base_shard(
    task: tuple[str, str, str, list[str], list[str], dict[str, str]],
) -> tuple[str, str, int, set[str]]:
    source_str, target_str, docs_str, excluded_list, reanchor_list, reanchor_locs = task
    source = Path(source_str)
    target = Path(target_str)
    documents = Path(docs_str)

    if target.exists():
        pf = pq.ParquetFile(target)
        keys = set(pf.read(columns=["member_key"]).column(0).to_pylist())
        return source.name, "existing", pf.metadata.num_rows, keys

    excluded = set(excluded_list)
    reanchor_set = set(reanchor_list)
    pf = pq.ParquetFile(source)

    if not excluded and not reanchor_set:
        os.link(source, target)
        keys = set(pf.read(columns=["member_key"]).column(0).to_pylist())
        return source.name, "hardlinked", pf.metadata.num_rows, keys

    records = _read_records(documents, reanchor_locs, reanchor_set) if reanchor_set else {}
    schema = pf.schema_arrow
    metadata, codecs = _serving_codecs(schema)
    omitted = pa.array(sorted(excluded), type=pa.string()) if excluded else None

    partial = target.with_name(f".{target.name}.partial-{os.getpid()}")
    total = 0
    kept_keys: set[str] = set()
    try:
        with pq.ParquetWriter(partial, schema, compression=codecs, use_dictionary=metadata) as writer:
            for batch in pf.iter_batches(batch_size=2048):
                if omitted is not None:
                    batch = batch.filter(pc.invert(pc.is_in(batch.column("member_key"), value_set=omitted)))
                if len(batch) == 0:
                    continue
                if reanchor_set:
                    mk_list = batch.column("member_key").to_pylist()
                    kept_keys.update(mk_list)
                    if any(k in reanchor_set for k in mk_list):
                        sf_list = batch.column("source_field").to_pylist()
                        cs_list = batch.column("char_start").to_pylist()
                        ce_list = batch.column("char_end").to_pylist()
                        ex_list = batch.column("excerpt").to_pylist()
                        pg_list = batch.column("page").to_pylist()
                        pa_list = batch.column("page_at").to_pylist()
                        for idx, key in enumerate(mk_list):
                            if key in reanchor_set:
                                ex, pg, pat = preview(records[key], sf_list[idx], cs_list[idx], ce_list[idx])
                                ex_list[idx], pg_list[idx], pa_list[idx] = ex, pg, pat
                        cols = [
                            pa.array(ex_list, pa.string())
                            if name == "excerpt"
                            else pa.array(pg_list, pa.int32())
                            if name == "page"
                            else pa.array(pa_list, pa.int32())
                            if name == "page_at"
                            else batch.column(name)
                            for name in schema.names
                        ]
                        writer.write_table(pa.Table.from_arrays(cols, schema=schema))
                    else:
                        writer.write_batch(batch)
                else:
                    kept_keys.update(batch.column("member_key").to_pylist())
                    writer.write_batch(batch)
                total += len(batch)

        if total == 0:
            partial.unlink(missing_ok=True)
            return source.name, "retired_empty", 0, set()
        os.chmod(partial, 0o644)
        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    return source.name, "filtered", total, kept_keys


def _process_delta(
    delta: Path,
    target: Path,
    documents: Path,
    locations: dict[str, str],
) -> tuple[str, str, int, set[str]]:
    pf = pq.ParquetFile(delta)
    if pf.metadata.num_rows == 0:
        return delta.name, "delta_empty", 0, set()

    keys = set(pf.read(columns=["member_key"]).column(0).to_pylist())
    records = _read_records(documents, locations, keys)
    schema = (
        pf.schema_arrow.append(pa.field("excerpt", pa.string()))
        .append(pa.field("page", pa.int32()))
        .append(pa.field("page_at", pa.int32()))
    )
    metadata, codecs = _serving_codecs(schema)

    partial = target.with_name(f".{target.name}.partial-{os.getpid()}")
    total = 0
    try:
        with pq.ParquetWriter(partial, schema, compression=codecs, use_dictionary=metadata) as writer:
            for batch in pf.iter_batches(batch_size=2048):
                fields = batch.select(["member_key", "source_field", "char_start", "char_end"]).to_pydict()
                excerpts: list[str] = []
                pages: list[int | None] = []
                offsets: list[int | None] = []
                for key, field, start, end in zip(*fields.values(), strict=True):
                    snippet, page, offset = preview(records[key], field, start, end)
                    excerpts.append(snippet)
                    pages.append(page)
                    offsets.append(offset)
                writer.write_table(
                    pa.Table.from_arrays(
                        [
                            *batch.columns,
                            pa.array(excerpts, pa.string()),
                            pa.array(pages, pa.int32()),
                            pa.array(offsets, pa.int32()),
                        ],
                        schema=schema,
                    )
                )
                total += len(batch)
        os.chmod(partial, 0o644)
        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    return delta.name, "delta", total, keys


def prepare_serving(
    base_serving: str | Path,
    delta_vectors: str | Path | None,
    new_prepared: str | Path,
    changes_json: str | Path,
    output_dir: str | Path,
    *,
    workers: int = 1,
    source_id: str = SOURCE_ID,
) -> dict[str, Any]:
    """Assemble serving passage Parquets by hard-linking unchanged shards and attaching delta previews."""
    if workers < 1:
        raise ValueError(f"workers must be >= 1, got {workers}")

    base_dir = Path(base_serving)
    docs_dir = Path(new_prepared)
    changes_path = Path(changes_json)
    out_dir = Path(output_dir)
    delta_path = Path(delta_vectors) if delta_vectors is not None else None

    t0 = time.monotonic()
    out_dir.mkdir(parents=True, exist_ok=True)

    doc_parts = sorted(docs_dir.glob("*.parquet"))
    if not doc_parts:
        raise ValueError(f"No prepared document shards in {docs_dir}")
    locations: dict[str, str] = {}
    for part in doc_parts:
        table = pq.read_table(part, columns=["source_id", "member_key"])
        for src, key in zip(table["source_id"].to_pylist(), table["member_key"].to_pylist(), strict=True):
            if src != source_id:
                raise ValueError(f"Unexpected source_id {src!r} in {part.name} for {key}")
            if key in locations:
                raise ValueError(f"Duplicate document identity: {key}")
            locations[key] = part.name

    changes = json.loads(changes_path.read_text(encoding="utf-8"))
    obsolete: dict[str, list[str]] = changes.get("obsolete", {})
    reanchor: dict[str, list[str]] = changes.get("reanchor", {})

    base_files = sorted(base_dir.glob("*.parquet"))
    if not base_files:
        raise ValueError(f"No base serving Parquet files in {base_dir}")
    if delta_path is not None and any(p.name == delta_path.name for p in base_files):
        raise ValueError(f"Delta filename collides with base serving shard: {delta_path.name}")

    tasks = []
    for src in base_files:
        excl = obsolete.get(src.name, [])
        reanc = reanchor.get(src.name, [])
        reanc_locs = {k: locations[k] for k in reanc}
        tasks.append((str(src), str(out_dir / src.name), str(docs_dir), excl, reanc, reanc_locs))

    seen: set[str] = set()
    total = 0
    modes: Counter[str] = Counter()
    for name, mode, count, keys in _map_tasks(_process_base_shard, tasks, workers):
        if seen & keys:
            raise ValueError(f"Passage identity occurs in multiple source partitions: {name}")
        seen.update(keys)
        total += count
        modes[mode] += 1

    if delta_path is not None:
        _, mode, count, keys = _process_delta(delta_path, out_dir / delta_path.name, docs_dir, locations)
        if seen & keys:
            raise ValueError(f"Delta overlaps base keys: {len(seen & keys)}")
        seen.update(keys)
        total += count
        modes[mode] += 1

    if seen != locations.keys():
        missing = len(locations.keys() - seen)
        extra = len(seen - locations.keys())
        raise ValueError(f"Passage coverage differs from current release: missing={missing}, extra={extra}")

    return {
        "passages": total,
        "documents": len(seen),
        "files": len(list(out_dir.glob("*.parquet"))),
        "modes": dict(modes),
        "elapsed_s": round(time.monotonic() - t0, 2),
    }


def _load_keyed_vectors(path: Path) -> dict[tuple[str, str, str, int, int, int], list[float]]:
    pf = pq.ParquetFile(path)
    cols = ["source_id", "member_key", "source_field", "chunk_index", "char_start", "char_end", "vector"]
    vectors: dict[tuple[str, str, str, int, int, int], list[float]] = {}
    for batch in pf.iter_batches(batch_size=1024, columns=cols):
        py = batch.to_pydict()
        for src, mk, sf, idx, lo, hi, vec in zip(*(py[c] for c in cols), strict=True):
            key = (src, mk, sf, int(idx), int(lo), int(hi))
            if key in vectors:
                raise ValueError(f"Duplicate passage coordinate {key} in {path}")
            vectors[key] = [float(v) for v in vec]
    return vectors


def verify_vector_parity(
    reference_parquet: str | Path,
    candidate_parquet: str | Path,
    *,
    min_cosine: float = DEFAULT_PARITY_MIN_COSINE,
    subset: bool = False,
    strict: bool = True,
) -> dict[str, Any]:
    """Compare candidate vectors against a reference vector Parquet on matched passage coordinates."""
    ref = _load_keyed_vectors(Path(reference_parquet))
    cand = _load_keyed_vectors(Path(candidate_parquet))

    if not cand:
        raise ValueError(f"Candidate vector Parquet has no rows: {candidate_parquet}")
    if subset:
        extra = cand.keys() - ref.keys()
        if extra:
            raise ValueError(f"Candidate has {len(extra)} coordinates absent from reference, e.g. {min(extra)}")
    elif cand.keys() != ref.keys():
        missing = len(ref.keys() - cand.keys())
        extra = len(cand.keys() - ref.keys())
        raise ValueError(f"Passage coordinate sets differ: missing={missing}, extra={extra}")

    np_mod = _try_import_numpy()
    keys = sorted(cand.keys())
    if np_mod is not None:
        a = np_mod.asarray([ref[k] for k in keys], dtype=np_mod.float32)
        b = np_mod.asarray([cand[k] for k in keys], dtype=np_mod.float32)
        if a.shape != b.shape:
            raise ValueError(f"Vector shape mismatch: reference={a.shape}, candidate={b.shape}")
        norms_a = np_mod.linalg.norm(a, axis=1)
        norms_b = np_mod.linalg.norm(b, axis=1)
        if bool(np_mod.any(norms_a == 0)) or bool(np_mod.any(norms_b == 0)):
            raise ValueError("Zero-norm vector encountered during parity check")
        cosines = np_mod.sum(a * b, axis=1) / (norms_a * norms_b)
        min_cos = float(cosines.min())
        mean_cos = float(cosines.mean())
        max_cos = float(cosines.max())
        max_abs_diff = float(np_mod.max(np_mod.abs(a - b)))
    else:
        cos_vals: list[float] = []
        max_abs_diff = 0.0
        for key in keys:
            va, vb = ref[key], cand[key]
            if len(va) != len(vb):
                raise ValueError(f"Vector dimension mismatch for {key}: {len(va)} vs {len(vb)}")
            dot = 0.0
            na = 0.0
            nb = 0.0
            for x, y in zip(va, vb, strict=True):
                dot += x * y
                na += x * x
                nb += y * y
                diff = abs(x - y)
                if diff > max_abs_diff:
                    max_abs_diff = diff
            if na == 0.0 or nb == 0.0:
                raise ValueError(f"Zero-norm vector encountered for {key}")
            cos_vals.append(dot / (math.sqrt(na) * math.sqrt(nb)))
        min_cos = min(cos_vals)
        mean_cos = sum(cos_vals) / len(cos_vals)
        max_cos = max(cos_vals)

    passed = min_cos >= min_cosine
    result = {
        "matched": len(keys),
        "reference_rows": len(ref),
        "candidate_rows": len(cand),
        "min_cosine": min_cos,
        "mean_cosine": mean_cos,
        "max_cosine": max_cos,
        "max_abs_diff": max_abs_diff,
        "threshold": min_cosine,
        "passed": passed,
    }
    if strict and not passed:
        raise ValueError(
            f"Vector parity failed: min_cosine={min_cos:.8f} < threshold={min_cosine:.8f} "
            f"(max_abs_diff={max_abs_diff:.6f}, matched={len(keys)})"
        )
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for delta extraction, Apple Silicon encoding, serving assembly, and parity checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    delta_cmd = sub.add_parser("source-delta", help="Compute incremental passage delta between prepared releases")
    delta_cmd.add_argument("--old-prepared", required=True, type=Path)
    delta_cmd.add_argument("--old-serving", required=True, type=Path)
    delta_cmd.add_argument("--new-prepared", required=True, type=Path)
    delta_cmd.add_argument("--out", required=True, type=Path)
    delta_cmd.add_argument("--workers", type=int, default=4)

    encode_cmd = sub.add_parser("encode-delta", help="Encode delta.parquet locally on Apple Silicon")
    encode_cmd.add_argument("--delta", required=True, type=Path)
    encode_cmd.add_argument("--output", required=True, type=Path)
    encode_cmd.add_argument("--model-home", type=Path, default=None)
    encode_cmd.add_argument("--fast-silicon-root", type=Path, default=None)
    encode_cmd.add_argument("--mode", default="hetero")
    encode_cmd.add_argument("--dimensions", type=int, default=EMBEDDING_DIMENSIONS)
    encode_cmd.add_argument("--receipt", type=Path, default=None)

    serving_cmd = sub.add_parser("prepare-serving", help="Assemble serving passage Parquet overlay")
    serving_cmd.add_argument("--base", required=True, type=Path)
    serving_cmd.add_argument("--delta", type=Path, default=None)
    serving_cmd.add_argument("--documents", required=True, type=Path)
    serving_cmd.add_argument("--changes", required=True, type=Path)
    serving_cmd.add_argument("--output", required=True, type=Path)
    serving_cmd.add_argument("--workers", type=int, default=4)

    parity_cmd = sub.add_parser("verify-parity", help="Check cosine parity between two vector Parquets")
    parity_cmd.add_argument("--reference", required=True, type=Path)
    parity_cmd.add_argument("--candidate", required=True, type=Path)
    parity_cmd.add_argument("--min-cosine", type=float, default=DEFAULT_PARITY_MIN_COSINE)
    parity_cmd.add_argument("--subset", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "source-delta":
        payload = compute_source_delta(
            args.old_prepared,
            args.old_serving,
            args.new_prepared,
            args.out,
            workers=args.workers,
        )
        print(json.dumps(payload["summary"], sort_keys=True))
    elif args.command == "encode-delta":
        receipt = encode_delta(
            args.delta,
            args.output,
            model_home=args.model_home,
            fast_silicon_root=args.fast_silicon_root,
            mode=args.mode,
            dimensions=args.dimensions,
            receipt_path=args.receipt,
        )
        print(json.dumps(receipt, sort_keys=True))
    elif args.command == "prepare-serving":
        result = prepare_serving(
            args.base,
            args.delta,
            args.documents,
            args.changes,
            args.output,
            workers=args.workers,
        )
        print(json.dumps(result, sort_keys=True))
    else:
        result = verify_vector_parity(
            args.reference,
            args.candidate,
            min_cosine=args.min_cosine,
            subset=args.subset,
        )
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
