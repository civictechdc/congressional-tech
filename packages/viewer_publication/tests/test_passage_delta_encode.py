"""Offline unit and mini-Parquet integration tests for incremental passage delta encoding."""

from __future__ import annotations

import builtins
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from viewer_publication import passage_delta_encode as delta_mod

SOURCE = delta_mod.SOURCE_ID
DIM = 8


def _unit_vector(dim: int = DIM, *, seed: int = 0) -> list[float]:
    raw = [math.sin((i + 1) * (seed + 1)) + 0.25 for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in raw))
    return [v / norm for v in raw]


def _prepared_doc(
    key: str,
    title: str,
    body: str | None,
    *,
    offsets: list[int] | None = None,
    text_status: str | None = None,
    text_sha256: str | None = None,
    source_id: str = SOURCE,
) -> dict[str, object]:
    has_body = bool(body and not body.isspace())
    if text_sha256 is None:
        text_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest() if has_body else None
    if text_status is None:
        text_status = "Selected text" if has_body else "No text"
    return {
        "source_id": source_id,
        "member_key": key,
        "title": title,
        "body": body,
        "text_sha256": text_sha256,
        "text_status": text_status,
        "page_offsets": offsets,
    }


def _prepared_schema() -> pa.Schema:
    return pa.schema(
        [
            ("source_id", pa.string()),
            ("member_key", pa.string()),
            ("title", pa.string()),
            ("body", pa.string()),
            ("text_sha256", pa.string()),
            ("text_status", pa.string()),
            ("page_offsets", pa.list_(pa.int32())),
        ]
    )


def _serving_schema(dim: int = DIM) -> pa.Schema:
    return (
        delta_mod.vector_parquet_schema(dim)
        .append(pa.field("excerpt", pa.string()))
        .append(pa.field("page", pa.int32()))
        .append(pa.field("page_at", pa.int32()))
    )


def _write_prepared(directory: Path, shards: dict[str, list[dict[str, object]]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    schema = _prepared_schema()
    for name, docs in shards.items():
        pq.write_table(pa.Table.from_pylist(docs, schema=schema), directory / f"{name}.parquet")
    return directory


def _serving_row(
    doc: dict[str, object],
    *,
    field: str | None = None,
    start: int = 0,
    end: int | None = None,
    chunk_index: int = 0,
    token_count: int = 5,
    dim: int = DIM,
    seed: int = 1,
) -> dict[str, object]:
    body = doc["body"] or ""
    title = doc["title"] or ""
    if field is None:
        field = "body" if (body and not body.isspace()) else "title"
    text = body if field == "body" else title
    if end is None:
        end = len(text)
    rec = delta_mod.text_pages(doc)
    excerpt, page, page_at = delta_mod.preview(rec, field, start, end)
    return {
        "source_id": doc["source_id"],
        "member_key": doc["member_key"],
        "source_field": field,
        "text_sha256": doc["text_sha256"],
        "chunk_index": chunk_index,
        "char_start": start,
        "char_end": end,
        "token_count": token_count,
        "vector": _unit_vector(dim, seed=seed),
        "excerpt": excerpt,
        "page": page,
        "page_at": page_at,
    }


def _write_serving(directory: Path, shards: dict[str, list[dict[str, object]]], *, dim: int = DIM) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    schema = _serving_schema(dim)
    for name, rows in shards.items():
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), directory / f"{name}.parquet")
    return directory


class _FakeInnerTokenizer:
    """Whitespace-word tokenizer returning deterministic token ids and character offsets."""

    def encode(self, text: str, *, add_special_tokens: bool = False) -> SimpleNamespace:
        _ = add_special_tokens
        ids: list[int] = []
        offsets: list[tuple[int, int]] = []
        pos = 0
        n = len(text)
        while pos < n:
            while pos < n and text[pos].isspace():
                pos += 1
            if pos >= n:
                break
            end = pos
            while end < n and not text[end].isspace():
                end += 1
            ids.append(len(ids) + 10)
            offsets.append((pos, end))
            pos = end
        return SimpleNamespace(ids=ids, offsets=offsets)


class _FakeEngine:
    def __init__(self, *, ane_available: bool = True) -> None:
        self.tokenizer = SimpleNamespace(_tok=_FakeInnerTokenizer())
        self.ane_available = ane_available
        self.closed = False

    def __enter__(self) -> _FakeEngine:
        return self

    def __exit__(self, *exc: object) -> None:
        self.closed = True
        # Mirror FastEmbeddingGemma2.close(), which clears ane_available on exit.
        self.ane_available = False


def _stub_embed_parquet(
    engine: object,
    input_path: Path,
    output_path: Path,
    *,
    dimensions: int = DIM,
    chunk_chars: int = 24,
    **kwargs: object,
) -> SimpleNamespace:
    _ = (engine, kwargs)
    # Mirror fast_shared.parquet_pipeline.embed_parquet single-file suffix requirement.
    assert output_path.suffix.lower() == ".parquet", f"Expected .parquet single-file path, got {output_path}"
    table = pq.read_table(input_path)
    out_rows = []
    total_tokens = 0
    for row_idx, row in enumerate(table.to_pylist()):
        content = row["content"]
        length = len(content)
        start = 0
        chunk_index = 0
        while start < length:
            end = min(length, start + chunk_chars)
            toks = max(1, len(content[start:end].split()))
            total_tokens += toks
            out_rows.append(
                {
                    "source_id": row["source_id"],
                    "member_key": row["member_key"],
                    "source_field": row["source_field"],
                    "text_sha256": row["text_sha256"],
                    "chunk_index": chunk_index,
                    "char_start": start,
                    "char_end": end,
                    "token_count": toks,
                    "vector": _unit_vector(dimensions, seed=row_idx * 17 + chunk_index + 3),
                }
            )
            chunk_index += 1
            if end == length:
                break
            start = max(start + 1, end - 4)
    pq.write_table(
        pa.Table.from_pylist(out_rows, schema=delta_mod.vector_parquet_schema(dimensions)),
        output_path,
    )
    return SimpleNamespace(total_tokens=total_tokens)


def test_source_delta_classifies_all_transitions_and_reuses_body_with_upgraded_title(tmp_path):
    # Old release across two serving shards:
    # - shard-unchanged: d_reuse_body (body unchanged, title upgraded!), d_reuse_title (unchanged textless)
    # - shard-mixed: d_reanchor (body unchanged, page_offsets changed), d_changed_body, d_body_lost,
    #                d_title_gained, d_title_changed, d_removed
    d_reuse_body = _prepared_doc("d-reuse-body", "Untitled", "Alpha rural broadband hearing testimony")
    d_reuse_title = _prepared_doc("d-reuse-title", "Committee Schedule", None)
    d_reanchor = _prepared_doc("d-reanchor", "Budget Report", "Page one text\nPage two text", offsets=[0, 14])
    d_changed_body = _prepared_doc("d-changed-body", "Appropriations", "Original appropriations draft")
    d_body_lost = _prepared_doc("d-body-lost", "Attachment Notice", "Short body later withdrawn")
    d_title_gained = _prepared_doc("d-title-gained", "Witness Bio", None)
    d_title_changed = _prepared_doc("d-title-changed", "d-title-changed", None)
    d_removed = _prepared_doc("d-removed", "Retired WARC", "Old archived HTML document")

    old_prepared = _write_prepared(
        tmp_path / "old" / "prepared",
        {
            "part-00": [d_reuse_body, d_reuse_title, d_reanchor, d_changed_body],
            "part-01": [d_body_lost, d_title_gained, d_title_changed, d_removed],
        },
    )
    old_serving = _write_serving(
        tmp_path / "old" / "serving",
        {
            "shard-00": [_serving_row(d_reuse_body, seed=1), _serving_row(d_reuse_title, seed=2)],
            "shard-01": [
                _serving_row(d_reanchor, seed=3),
                _serving_row(d_changed_body, seed=4),
                _serving_row(d_body_lost, seed=5),
                _serving_row(d_title_gained, seed=6),
                _serving_row(d_title_changed, seed=7),
                _serving_row(d_removed, seed=8),
            ],
        },
    )

    # New release:
    n_reuse_body = _prepared_doc(
        "d-reuse-body",
        "Upgraded Title From Meetings Parquet",
        "Alpha rural broadband hearing testimony",
    )
    n_reuse_title = _prepared_doc("d-reuse-title", "Committee Schedule", None)
    n_reanchor = _prepared_doc("d-reanchor", "Budget Report", "Page one text\nPage two text", offsets=[0, 9])
    n_changed_body = _prepared_doc("d-changed-body", "Appropriations", "Updated appropriations final text")
    # Whitespace-only body with text_status='Selected text' must fall back to title.
    n_body_lost = _prepared_doc("d-body-lost", "Attachment Notice", "   \n\t ", text_status="Selected text")
    n_title_gained = _prepared_doc("d-title-gained", "Witness Bio", "Newly extracted biography text")
    n_title_changed = _prepared_doc("d-title-changed", "Hearing Witness List", None)
    n_added_body = _prepared_doc("d-added-body", "New Testimony", "Fresh testimony on grid reliability")
    n_added_title = _prepared_doc("d-added-title", "d-added-title", None)

    new_prepared = _write_prepared(
        tmp_path / "new" / "prepared",
        {
            "part-00": [n_reuse_body, n_reuse_title, n_reanchor, n_changed_body, n_added_body],
            "part-01": [n_body_lost, n_title_gained, n_title_changed, n_added_title],
        },
    )

    out_dir = tmp_path / "delta"
    payload = delta_mod.compute_source_delta(old_prepared, old_serving, new_prepared, out_dir, workers=1)
    summary = payload["summary"]
    reasons = payload["reasons"]

    assert summary["old_documents"] == 8
    assert summary["new_documents"] == 9
    assert summary["reused"] == 3
    assert summary["reused_body"] == 2
    assert summary["reused_title"] == 1
    assert summary["reused_body_title_upgraded"] == 1
    assert summary["reanchor_page_offsets"] == 1
    assert summary["added"] == 2
    assert summary["changed"] == 4
    assert summary["removed"] == 1
    assert summary["delta_total"] == 6
    assert summary["ws_only_selected_text"] == 1
    assert summary["textless_title_equals_key"] == 1
    assert reasons == {
        "added_body": 1,
        "added_title": 1,
        "body_lost_to_title": 1,
        "changed_body": 1,
        "changed_textless_title": 1,
        "reanchor_page_offsets": 1,
        "removed": 1,
        "reused_body": 2,
        "reused_title": 1,
        "title_gained_body": 1,
    }
    assert payload["reanchor"] == {"shard-01.parquet": ["d-reanchor"]}
    assert "shard-00.parquet" not in payload["obsolete"]
    assert "shard-00.parquet" not in payload["reanchor"]
    assert sorted(payload["obsolete"]["shard-01.parquet"]) == [
        "d-body-lost",
        "d-changed-body",
        "d-removed",
        "d-title-changed",
        "d-title-gained",
    ]
    delta_keys = set(pq.read_table(out_dir / "delta.parquet")["member_key"].to_pylist())
    assert delta_keys == {
        "d-added-body",
        "d-added-title",
        "d-body-lost",
        "d-changed-body",
        "d-title-changed",
        "d-title-gained",
    }
    assert json.loads((out_dir / "delta.json").read_text(encoding="utf-8")) == payload


def test_format_header_truncates_long_title_at_token_boundary():
    tok = SimpleNamespace(_tok=_FakeInnerTokenizer())
    assert delta_mod.format_header(tok, "Short Title") == "Short Title"
    words = [f"word{i:03d}" for i in range(80)]
    long_title = " ".join(words)
    truncated = delta_mod.format_header(tok, long_title, max_tokens=64)
    assert truncated == " ".join(words[:64])
    assert len(truncated) < len(long_title)


def test_prepare_delta_input_and_encode_delta_end_to_end_with_stub_engine(tmp_path):
    delta_rows = [
        _prepared_doc("doc-body", "Hearing on Broadband Access", "Rural broadband expansion testimony across states."),
        _prepared_doc("doc-title", "doc-title", "   "),
    ]
    delta_in = tmp_path / "delta.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [{k: d[k] for k in delta_mod.DELTA_SOURCE_COLUMNS} for d in delta_rows],
            schema=pa.schema([_prepared_schema().field(k) for k in delta_mod.DELTA_SOURCE_COLUMNS]),
        ),
        delta_in,
    )

    out_vectors = tmp_path / "delta-v3.parquet"
    receipt_path = tmp_path / "encode-receipt.json"
    engines_created: list[_FakeEngine] = []

    def factory() -> _FakeEngine:
        eng = _FakeEngine(ane_available=True)
        engines_created.append(eng)
        return eng

    receipt = delta_mod.encode_delta(
        delta_in,
        out_vectors,
        dimensions=DIM,
        receipt_path=receipt_path,
        encoder_factory=factory,
        embed_fn=_stub_embed_parquet,
    )

    assert len(engines_created) == 1 and engines_created[0].closed
    # ane_available must be captured BEFORE engine.close() clears it.
    assert receipt["ane_available"] is True
    assert receipt["records"] == 2
    assert receipt["body_records"] == 1
    assert receipt["title_records"] == 1
    assert receipt["fallback_id_titles"] == ["doc-title"]
    assert receipt["vectors"] >= 3
    assert receipt["dimensions"] == DIM
    assert out_vectors.is_file()
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt


def test_encode_delta_handles_empty_delta_without_loading_fast_silicon(tmp_path):
    delta_in = tmp_path / "delta.parquet"
    schema = pa.schema([_prepared_schema().field(k) for k in delta_mod.DELTA_SOURCE_COLUMNS])
    pq.write_table(schema.empty_table(), delta_in)

    out_vectors = tmp_path / "delta-empty.parquet"
    receipt = delta_mod.encode_delta(delta_in, out_vectors, dimensions=DIM)
    assert receipt["records"] == 0
    assert receipt["vectors"] == 0
    assert pq.ParquetFile(out_vectors).metadata.num_rows == 0


def test_encode_delta_raises_clear_error_when_fast_silicon_unavailable(tmp_path, monkeypatch):
    delta_in = tmp_path / "delta.parquet"
    doc = _prepared_doc("doc-1", "Title", "Some testimony text")
    pq.write_table(
        pa.Table.from_pylist(
            [{k: doc[k] for k in delta_mod.DELTA_SOURCE_COLUMNS}],
            schema=pa.schema([_prepared_schema().field(k) for k in delta_mod.DELTA_SOURCE_COLUMNS]),
        ),
        delta_in,
    )
    monkeypatch.delenv("FAST_SILICON_ROOT", raising=False)
    real_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith(("fast_embeddinggemma_2", "fast_shared")):
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    with pytest.raises(RuntimeError, match="fast-embeddinggemma-2"):
        delta_mod.encode_delta(delta_in, tmp_path / "out.parquet")


@pytest.mark.parametrize(
    "kind, match",
    [
        ("dtype", "Unexpected vector column type"),
        ("nan", "Non-finite vector component"),
        ("norm_low", "Invalid vector norm"),
        ("norm_high", "Invalid vector norm"),
        ("span_too_long", "MAX_PASSAGE_CHARS"),
        ("gap", "Gap or repeated chunk window"),
        ("missing_tail", "Missing trailing text"),
        ("token_limit", "Invalid passage"),
        ("missing_key", "Vector coverage mismatch"),
        ("extra_key", "Unexpected member_key"),
    ],
)
def test_check_vectors_rejects_invalid_outputs(tmp_path, kind, match):
    path = tmp_path / f"{kind}.parquet"
    expected = {"a": ("body", 20)}
    rows = [
        {
            "source_id": SOURCE,
            "member_key": "a",
            "source_field": "body",
            "text_sha256": "0" * 64,
            "chunk_index": 0,
            "char_start": 0,
            "char_end": 20,
            "token_count": 5,
            "vector": _unit_vector(DIM, seed=1),
        }
    ]
    schema = delta_mod.vector_parquet_schema(DIM)
    max_chars = delta_mod.MAX_PASSAGE_CHARS

    if kind == "dtype":
        schema = pa.schema(
            [
                *[f for f in schema if f.name != "vector"],
                ("vector", pa.list_(pa.float32(), DIM)),
            ]
        )
    elif kind == "nan":
        vec = _unit_vector(DIM, seed=1)
        vec[0] = float("nan")
        rows[0]["vector"] = vec
    elif kind == "norm_low":
        rows[0]["vector"] = [v * 0.5 for v in _unit_vector(DIM, seed=1)]
    elif kind == "norm_high":
        rows[0]["vector"] = [v * 1.5 for v in _unit_vector(DIM, seed=1)]
    elif kind == "span_too_long":
        max_chars = 10
    elif kind == "gap":
        rows = [
            {**rows[0], "chunk_index": 0, "char_start": 0, "char_end": 8},
            {**rows[0], "chunk_index": 1, "char_start": 10, "char_end": 20},
        ]
    elif kind == "missing_tail":
        rows[0]["char_end"] = 18
    elif kind == "token_limit":
        rows[0]["token_count"] = 513
    elif kind == "missing_key":
        expected["b"] = ("title", 10)
    elif kind == "extra_key":
        rows.append({**rows[0], "member_key": "unexpected"})

    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    with pytest.raises(ValueError, match=match):
        delta_mod.check_vectors(path, expected, dimensions=DIM, max_passage_chars=max_chars)


def test_prepare_serving_hardlinks_unchanged_filters_retires_reanchors_and_attaches_delta(tmp_path):
    # Base release:
    # - shard-00: d_keep (unchanged -> hardlinked!)
    # - shard-01: d_reanchor (UTF-8 multi-byte page offsets change -> re-anchored!), d_changed (replaced)
    # - shard-02: d_retired (only doc in shard -> retired_empty!)
    body_utf8 = "Café page one\nRésumé page two text"
    old_p2_byte = len("Café page one\n".encode("utf-8"))
    new_p2_byte = len("Café ".encode("utf-8"))

    d_keep = _prepared_doc("d-keep", "Keep Title", "Unchanged testimony body")
    d_reanchor_old = _prepared_doc("d-reanchor", "UTF8 Doc", body_utf8, offsets=[0, old_p2_byte])
    d_changed_old = _prepared_doc("d-changed", "Old Title", "Old body text")
    d_retired = _prepared_doc("d-retired", "Retired Doc", "Removed document body")

    old_prepared = _write_prepared(
        tmp_path / "old" / "prepared",
        {"part-00": [d_keep, d_reanchor_old, d_changed_old, d_retired]},
    )
    old_serving = _write_serving(
        tmp_path / "old" / "serving",
        {
            "shard-00": [_serving_row(d_keep, seed=1)],
            "shard-01": [
                _serving_row(d_reanchor_old, start=6, end=len(body_utf8), seed=2),
                _serving_row(d_changed_old, seed=3),
            ],
            "shard-02": [_serving_row(d_retired, seed=4)],
        },
    )

    d_reanchor_new = _prepared_doc("d-reanchor", "UTF8 Doc", body_utf8, offsets=[0, new_p2_byte])
    d_changed_new = _prepared_doc("d-changed", "New Title", "  Leading spaces then updated text", offsets=[0, 17])
    d_added = _prepared_doc("d-added", "Added Textless", None)
    new_prepared = _write_prepared(
        tmp_path / "new" / "prepared",
        {"part-00": [d_keep, d_reanchor_new, d_changed_new, d_added]},
    )

    delta_dir = tmp_path / "control"
    delta_mod.compute_source_delta(old_prepared, old_serving, new_prepared, delta_dir, workers=1)
    delta_vectors = delta_dir / "delta-v3.parquet"
    delta_mod.encode_delta(
        delta_dir / "delta.parquet",
        delta_vectors,
        dimensions=DIM,
        encoder_factory=lambda: _FakeEngine(ane_available=True),
        embed_fn=_stub_embed_parquet,
    )

    new_serving = tmp_path / "new" / "serving"
    summary = delta_mod.prepare_serving(
        old_serving,
        delta_vectors,
        new_prepared,
        delta_dir / "delta.json",
        new_serving,
        workers=1,
    )

    assert summary["documents"] == 4
    assert summary["files"] == 3
    assert summary["modes"] == {"hardlinked": 1, "filtered": 1, "retired_empty": 1, "delta": 1}
    assert not (new_serving / "shard-02.parquet").exists()
    # Unchanged shard must be hard-linked (same inode, zero extra storage).
    assert (new_serving / "shard-00.parquet").stat().st_ino == (old_serving / "shard-00.parquet").stat().st_ino

    # Verify UTF-8 page re-anchoring on shard-01.
    reanchored_rows = pq.read_table(new_serving / "shard-01.parquet").to_pylist()
    assert [r["member_key"] for r in reanchored_rows] == ["d-reanchor"]
    # start=6 is 'a' in 'page'; page 2 starts at char 5 ('p' after 'Café '), so page_at = len('p'.encode()) = 1!
    assert reanchored_rows[0]["page"] == 2
    assert reanchored_rows[0]["page_at"] == len("p".encode("utf-8"))
    assert reanchored_rows[0]["excerpt"] == body_utf8[6:]

    # Verify delta excerpt trimming and page anchor attachment.
    delta_serving_rows = pq.read_table(new_serving / "delta-v3.parquet").to_pylist()
    by_key: dict[str, list[dict[str, object]]] = {}
    for row in delta_serving_rows:
        by_key.setdefault(row["member_key"], []).append(row)
    assert set(by_key) == {"d-changed", "d-added"}
    first_changed = sorted(by_key["d-changed"], key=lambda r: r["chunk_index"])[0]
    assert first_changed["excerpt"].startswith("Leading spaces")
    assert first_changed["page"] == 1
    assert first_changed["page_at"] == 2
    assert by_key["d-added"][0]["source_field"] == "title"
    assert by_key["d-added"][0]["page"] is None and by_key["d-added"][0]["page_at"] is None


def test_prepare_serving_refuses_delta_filename_collision_and_coverage_mismatch(tmp_path):
    doc_a = _prepared_doc("a", "Title A", "Body text A")
    doc_b = _prepared_doc("b", "Title B", "Body text B")
    prepared = _write_prepared(tmp_path / "prepared", {"part-00": [doc_a, doc_b]})
    base = _write_serving(tmp_path / "base", {"shard-00": [_serving_row(doc_a, seed=1)]})
    changes = tmp_path / "delta.json"
    changes.write_text(json.dumps({"obsolete": {}, "reanchor": {}}), encoding="utf-8")

    # Collision with existing base shard filename.
    colliding = tmp_path / "shard-00.parquet"
    pq.write_table(delta_mod.vector_parquet_schema(DIM).empty_table(), colliding)
    with pytest.raises(ValueError, match="collides"):
        delta_mod.prepare_serving(base, colliding, prepared, changes, tmp_path / "out-collide")

    # Missing document 'b' fails coverage check.
    with pytest.raises(ValueError, match="missing=1"):
        delta_mod.prepare_serving(base, None, prepared, changes, tmp_path / "out-missing")


def test_verify_vector_parity_passes_near_identical_and_rejects_drift(tmp_path):
    ref_vec = _unit_vector(DIM, seed=5)
    close_vec = [v + 1e-4 for v in ref_vec]
    close_norm = math.sqrt(sum(v * v for v in close_vec))
    close_vec = [v / close_norm for v in close_vec]
    drifted_vec = _unit_vector(DIM, seed=99)

    base_row = {
        "source_id": SOURCE,
        "member_key": "m-1",
        "source_field": "body",
        "text_sha256": "a" * 64,
        "chunk_index": 0,
        "char_start": 0,
        "char_end": 12,
        "token_count": 3,
    }
    schema = delta_mod.vector_parquet_schema(DIM)
    ref_path = tmp_path / "ref.parquet"
    close_path = tmp_path / "close.parquet"
    drift_path = tmp_path / "drift.parquet"
    pq.write_table(pa.Table.from_pylist([{**base_row, "vector": ref_vec}], schema=schema), ref_path)
    pq.write_table(pa.Table.from_pylist([{**base_row, "vector": close_vec}], schema=schema), close_path)
    pq.write_table(pa.Table.from_pylist([{**base_row, "vector": drifted_vec}], schema=schema), drift_path)

    ok = delta_mod.verify_vector_parity(ref_path, close_path, min_cosine=0.99999)
    assert ok["passed"] is True
    assert ok["matched"] == 1
    assert ok["min_cosine"] >= 0.99999

    with pytest.raises(ValueError, match="Vector parity failed"):
        delta_mod.verify_vector_parity(ref_path, drift_path, min_cosine=0.999998)


def test_cli_source_delta_and_prepare_serving_round_trip(tmp_path, capsys):
    doc = _prepared_doc("doc-1", "Hearing", "Testimony text unchanged")
    old_prep = _write_prepared(tmp_path / "old-prep", {"part-00": [doc]})
    old_srv = _write_serving(tmp_path / "old-srv", {"shard-00": [_serving_row(doc, seed=1)]})
    new_prep = _write_prepared(tmp_path / "new-prep", {"part-00": [doc]})

    delta_dir = tmp_path / "delta-cli"
    rc = delta_mod.main(
        [
            "source-delta",
            "--old-prepared",
            str(old_prep),
            "--old-serving",
            str(old_srv),
            "--new-prepared",
            str(new_prep),
            "--out",
            str(delta_dir),
            "--workers",
            "1",
        ]
    )
    assert rc == 0
    delta_out = json.loads(capsys.readouterr().out)
    assert delta_out["delta_total"] == 0 and delta_out["reused"] == 1

    out_srv = tmp_path / "new-srv"
    rc = delta_mod.main(
        [
            "prepare-serving",
            "--base",
            str(old_srv),
            "--documents",
            str(new_prep),
            "--changes",
            str(delta_dir / "delta.json"),
            "--output",
            str(out_srv),
            "--workers",
            "1",
        ]
    )
    assert rc == 0
    srv_out = json.loads(capsys.readouterr().out)
    assert srv_out["documents"] == 1 and srv_out["modes"] == {"hardlinked": 1}
