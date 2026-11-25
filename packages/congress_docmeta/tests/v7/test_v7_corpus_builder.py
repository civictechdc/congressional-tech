"""Offline unit tests for DocMeta V7.3 10K+ corpus builder, sharder & sealer (`ct-so28`)."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from congress_docmeta.v7.factory.corpus_builder import (
    build_batch_schema,
    build_v73_candidate_pool,
    run_sharded_corpus_build,
    seal_v73_corpus,
)
from congress_docmeta.v7.release_metadata import (
    validate_croissant_manifest,
    validate_dcat3_catalog,
)


def _write_synthetic_ssot(path: Path, count: int = 8) -> None:
    rows = []
    for i in range(count):
        if i % 3 == 0:
            text = f"UniqueWord_{i}_alpha Written Statement of Witness {i} TestimonyTopic_{i} Gamma_{i} March {10 + i}, 2025."
            kind = "witness_statement"
            fname = f"HHRG-119-IF00-Wstate-Wit{i}-202503{10 + i}.pdf"
        elif i % 3 == 1:
            text = f"QfrMarker_{i} Followup Inquiry_{i} to Expert_{i}. Question_{i}: Why_{i}? Response_{i}: Details_{i}. April 2, 2026."
            kind = "qfr_response"
            fname = f"HHRG-119-IF00-QFR-20260402-{i}.pdf"
        else:
            text = "403 Forbidden - Access Denied by Cloudflare"
            kind = "error_or_non_document"
            fname = f"err_{i}.pdf"
        rows.append(
            {
                "doc_key": f"ssot_{i:04d}_" + ("a" * 54),
                "split": "train",
                "messages": [
                    {
                        "role": "user",
                        "content": f"Advisory known metadata: {{}}\nFilename: {fname}\nText:\n{text}",
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({"status": "usable" if i % 3 != 2 else "error_or_block", "primary_kind": kind}),
                    },
                ],
            }
        )
    # Include an exact duplicate text row to test text_sha256 deduplication.
    rows.append({**rows[0], "doc_key": "ssot_dup_" + ("b" * 55)})
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _write_synthetic_parquets(tmp_path: Path) -> tuple[Path, Path, Path]:
    q_path = tmp_path / "llm_queue.parquet"
    d_path = tmp_path / "det.parquet"
    p_path = tmp_path / "p12.parquet"

    q_rows = []
    d_rows = []
    p_rows = []
    for i in range(18):
        is_2026 = i < 6
        ev_date = "2026-02-18" if is_2026 else "2023-06-12"
        fmt = "html" if i % 4 == 0 else "pdf"
        locked = "bill_or_draft" if i % 5 == 0 else (None if i % 2 == 0 else "witness_biography")
        text = (
            f"Committee Hearing Notice {i}: Oversight of Grid SectorAlpha_{i} topic_{i} phase_{i} on {ev_date}."
            if locked is None
            else f"Bill Text {i}: Be it enacted LegislationMeasure_{i} section_{i} title_{i} on {ev_date}."
            if locked == "bill_or_draft"
            else f"Biographical Sketch of Dr. Alex Morgan_{i}, Director BioInst_{i}, specialty_{i}, {ev_date}."
        )
        dk = f"mined_{i:04d}_" + ("c" * 53)
        q_rows.append(
            {
                "list_row": i,
                "doc_key": dk,
                "p12_clean_text": text,
                "p12_raw_text": text,
                "filename": f"doc_{i}.{fmt}",
                "rel_event_date": ev_date,
                "rel_chamber": "house",
                "rel_committees": ["hsif00"],
                "locked_primary_kind": locked,
                "effective_format": fmt,
                "stapled_ttf_disclosure_json": '{"ok":1}' if i == 1 else None,
                "p3_toc_or_gavel_slice": None,
            }
        )
        d_rows.append(
            {
                "list_row": i,
                "doc_key": dk,
                "filename": f"doc_{i}.{fmt}",
                "rel_event_date": ev_date,
                "v6_det_chamber": "house",
                "v6_det_committees": ["hsif00"],
                "effective_format": fmt,
                "deterministic_status": "queued_llm" if locked is None else "usable",
            }
        )
        p_rows.append(
            {
                "list_row": i,
                "p12_lines": text,
                "html_cms_nav_stripped_text": text,
                "waf_or_error_detected": False,
            }
        )

    # Add 2 deterministic hard negatives (WAF + catalog XML)
    for j, (st, waf, txt) in enumerate(
        [
            ("error_or_block", True, "403 Forbidden Cloudflare security challenge block page"),
            ("catalog_xml", False, "<?xml version='1.0'?><mods><titleInfo>Hearing</titleInfo></mods>"),
        ],
        start=100,
    ):
        dk = f"neg_{j:04d}_" + ("d" * 55)
        d_rows.append(
            {
                "list_row": j,
                "doc_key": dk,
                "filename": f"neg_{j}.xml",
                "rel_event_date": "2024-05-01",
                "v6_det_chamber": "senate",
                "v6_det_committees": [],
                "effective_format": "xml",
                "deterministic_status": st,
            }
        )
        p_rows.append(
            {
                "list_row": j,
                "p12_lines": txt,
                "html_cms_nav_stripped_text": None,
                "waf_or_error_detected": waf,
            }
        )

    pq.write_table(pa.Table.from_pylist(q_rows), q_path)
    pq.write_table(pa.Table.from_pylist(d_rows), d_path)
    pq.write_table(pa.Table.from_pylist(p_rows), p_path)
    return q_path, d_path, p_path


def test_build_pool_sharded_run_resume_and_seal(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot.jsonl"
    _write_synthetic_ssot(ssot, count=6)
    q_path, d_path, p_path = _write_synthetic_parquets(tmp_path)
    corpus_dir = tmp_path / "corpus"

    manifest = build_v73_candidate_pool(
        ssot_path=ssot,
        llm_queue_path=q_path,
        deterministic_path=d_path,
        p12_path=p_path,
        out_dir=corpus_dir,
        target_total=20,
        min_2026=5,
        seed=7,
    )
    assert manifest["total_candidates"] == 20
    assert manifest["ssot_count"] == 5  # 6 rows (2 error rows share 1 text_sha256) + 1 explicit dup -> 5 unique!
    assert manifest["count_2026"] >= 5
    cand_path = Path(manifest["candidates_path"])
    assert cand_path.is_file()

    # Run first 2 shards of size 6 in dry_run mode.
    res1 = run_sharded_corpus_build(
        candidates_path=cand_path,
        out_dir=corpus_dir,
        shard_size=6,
        max_shards=2,
        workers=2,
        dry_run=True,
    )
    assert res1["completed_shards"] == 2
    assert res1["skipped_shards"] == 0

    # Resume over all shards: first 2 MUST skip without rerunning, remaining 2 execute.
    res2 = run_sharded_corpus_build(
        candidates_path=cand_path,
        out_dir=corpus_dir,
        shard_size=6,
        workers=2,
        dry_run=True,
    )
    assert res2["completed_shards"] == 4
    assert res2["skipped_shards"] == 2

    sealed = seal_v73_corpus(corpus_dir=corpus_dir, candidates_path=cand_path)
    assert sealed["total_processed"] == 20
    assert sealed["gold_count"] == 20
    assert sealed["decontamination"]["clean"] is True
    assert Path(sealed["files"]["parquet"]).is_file()
    assert validate_croissant_manifest(json.loads(Path(sealed["files"]["croissant"]).read_text())) == []
    assert validate_dcat3_catalog(json.loads(Path(sealed["files"]["dcat3"]).read_text())) == []
    table = pq.read_table(sealed["files"]["parquet"])
    assert table.num_rows == 20


def test_run_sharded_corpus_build_single_specialist_family(tmp_path: Path) -> None:
    cand_path = tmp_path / "candidates.jsonl"
    doc_text = (
        "Committee Hearing Notice: Oversight of AI Procurement on March 18, 2025 "
        "in Rayburn 2141 before the Committee on Energy and Commerce."
    )
    rec = {
        "pool_index": 0,
        "doc_key": "spec_only_doc_0001",
        "text": doc_text,
        "filename": "HHRG-119-IF00-Notice-20250318.pdf",
        "source_pool": "archive_v6_2",
        "stratum": "locked_kind:hearing_notice",
        "doc_date": "2025-03-18",
        "event_date": "2025-03-18",
        "chamber": "house",
        "committees": ["hsif00"],
        "prior_kind": "hearing_notice",
        "is_2026": False,
    }
    cand_path.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    calls: list[tuple[str, str]] = []

    def _make_spy_adapter(fam: str):
        def _adapter(prompt: str, schema: dict, *, model_id: str = "", timeout_s: float = 30.0):
            del prompt, timeout_s
            title = str(schema.get("title") or "")
            if "primary_genre" in schema.get("properties", {}):
                calls.append((fam, "core"))
                return {
                    "rationale": "Hearing notice detected.",
                    "status": "usable",
                    "media_format": "prose",
                    "is_packet": False,
                    "contains_genres": [],
                    "primary_genre": "hearing_or_markup_notice",
                    "specialist_family": "event_logistics",
                    "subkind": None,
                    "verbatim_title": "Oversight of AI Procurement",
                    "title_span": {"quote": "Oversight of AI Procurement", "start": 0, "end": 1},
                    "doc_date": "2025-03-18",
                    "date_spans": [],
                    "chamber": "house",
                    "congress": 119,
                    "committees": [],
                    "subcommittees": [],
                    "gist": "Oversight hearing notice.",
                    "topics": ["ai"],
                }
            calls.append((fam, f"specialist:{title}"))
            return {
                "rationale": "Single specialist extraction.",
                "event_type": "hearing",
                "event_title": "Oversight of AI Procurement",
                "event_title_span": {"quote": "Oversight of AI Procurement", "start": 0, "end": 1},
                "event_date": "2025-03-18",
                "event_date_span": {"quote": "March 18, 2025", "start": 0, "end": 1},
                "event_time": None,
                "venue_kind": "capitol_room",
                "venue": "Rayburn 2141",
                "venue_span": {"quote": "Rayburn 2141", "start": 0, "end": 1},
                "witnesses": [],
                "due_date": None,
                "bill_refs": [],
            }

        return _adapter

    adapters = {fam: _make_spy_adapter(fam) for fam in ("claude", "codex", "gemini")}
    out_dir = tmp_path / "corpus_single_spec"
    res = run_sharded_corpus_build(
        candidates_path=cand_path,
        out_dir=out_dir,
        cache_path=tmp_path / "cache.sqlite",
        shard_size=10,
        workers=1,
        specialist_families=("claude",),
        live_checkeval=False,
        adapters=adapters,
    )
    assert res["completed_shards"] == 1
    assert sorted(fam for fam, stage in calls if stage == "core") == ["claude", "codex", "gemini"]
    assert [fam for fam, stage in calls if stage.startswith("specialist:")] == ["claude"]

    row = json.loads((out_dir / "shards" / "shard_0000.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["specialist_fields"]["venue"] == "Rayburn 2141"
    assert row["specialist_fields"]["event_date"] == "2025-03-18"


def test_batched_corpus_build_unpacks_falls_back_and_stops_at_50_pct(tmp_path: Path) -> None:
    import re
    from congress_docmeta.v7.factory.runners import AdapterOutput
    from congress_docmeta.v7.factory.cache import SixTupleCache

    cand_path = tmp_path / "candidates_batch.jsonl"
    docs = []
    for i in range(6):
        txt = (
            f"Committee Hearing Notice {i}: Oversight TopicAlpha_{i} on March {10 + i}, 2025 "
            f"in Rayburn 214{i} before the Committee on Energy and Commerce."
        )
        docs.append(
            {
                "pool_index": i,
                "doc_key": f"batch_doc_{i:04d}",
                "text": txt,
                "filename": f"HHRG-119-IF00-Notice-{i}.pdf",
                "source_pool": "archive_v6_2",
                "stratum": "locked_kind:hearing_notice",
                "doc_date": f"2025-03-{10 + i:02d}",
                "event_date": f"2025-03-{10 + i:02d}",
                "chamber": "house",
                "committees": ["hsif00"],
                "prior_kind": "hearing_notice",
                "is_2026": False,
            }
        )
    cand_path.write_text("".join(json.dumps(d) + "\n" for d in docs), encoding="utf-8")

    # Test A: B=4 micro-batch where d02 is dropped from the batch response -> triggers single-doc fallback!
    def _make_batched_adapter(fam: str, *, stop_on_shard2: bool = False):
        def _adapter(prompt: str, schema: dict, *, model_id: str = "", timeout_s: float = 30.0):
            del model_id, timeout_s
            is_batch = "items" in (schema.get("properties") or {})
            is_spec = "Stage 2" in prompt or "EventLogistics" in str(schema.get("title") or "")
            usage_pct = 55.0 if (stop_on_shard2 and fam == "codex" and "TopicAlpha_4" in prompt) else 12.0

            if is_batch:
                chunks = re.findall(r"doc_id=(d\d+).*?<<<DOC_TEXT>>>\n(.*?)\n<<<END_DOC_TEXT>>>", prompt, re.DOTALL)
                items = []
                for did, txt in chunks:
                    if fam == "claude" and did == "d02" and "TopicAlpha_2" in txt and not is_spec:
                        continue  # Intentionally drop 1 item to test single-doc fallback!
                    if is_spec:
                        m_topic = re.search(r"Oversight TopicAlpha_\d+", txt)
                        topic = m_topic.group(0) if m_topic else "Committee Hearing Notice"
                        items.append(
                            {
                                "doc_id": did,
                                "rationale": "Batched specialist.",
                                "event_type": "hearing",
                                "event_title": topic,
                                "event_title_span": {"quote": topic, "start": 0, "end": 1},
                                "event_date": "2025-03-10",
                                "event_date_span": {"quote": "Committee Hearing Notice", "start": 0, "end": 1},
                                "event_time": None,
                                "venue_kind": "capitol_room",
                                "venue": "Energy and Commerce",
                                "venue_span": {"quote": "Energy and Commerce", "start": 0, "end": 1},
                                "witnesses": [],
                                "due_date": None,
                                "bill_refs": [],
                            }
                        )
                    else:
                        items.append(
                            {
                                "doc_id": did,
                                "rationale": "Batched core.",
                                "status": "usable",
                                "media_format": "prose",
                                "is_packet": False,
                                "contains_genres": [],
                                "primary_genre": "hearing_or_markup_notice",
                                "specialist_family": "event_logistics",
                                "subkind": None,
                                "verbatim_title": "Committee Hearing Notice",
                                "title_span": {"quote": "Committee Hearing Notice", "start": 0, "end": 1},
                                "doc_date": None,
                                "date_spans": [],
                                "chamber": "house",
                                "congress": 119,
                                "committees": [],
                                "subcommittees": [],
                                "gist": "Hearing notice.",
                                "topics": ["oversight"],
                            }
                        )
                raw = json.dumps({"items": items})
                return AdapterOutput(raw_text=raw, extracted_json_str=raw, returncode=0, usage_pct=usage_pct)

            # Single-doc fallback response
            if is_spec:
                raw = json.dumps(
                    {
                        "rationale": "Fallback specialist.",
                        "event_type": "hearing",
                        "event_title": "Committee Hearing Notice",
                        "event_title_span": {"quote": "Committee Hearing Notice", "start": 0, "end": 1},
                        "event_date": None,
                        "event_date_span": None,
                        "event_time": None,
                        "venue_kind": "capitol_room",
                        "venue": "Energy and Commerce",
                        "venue_span": {"quote": "Energy and Commerce", "start": 0, "end": 1},
                        "witnesses": [],
                        "due_date": None,
                        "bill_refs": [],
                    }
                )
            else:
                raw = json.dumps(
                    {
                        "rationale": "Fallback single core.",
                        "status": "usable",
                        "media_format": "prose",
                        "is_packet": False,
                        "contains_genres": [],
                        "primary_genre": "hearing_or_markup_notice",
                        "specialist_family": "event_logistics",
                        "subkind": None,
                        "verbatim_title": "Committee Hearing Notice",
                        "title_span": {"quote": "Committee Hearing Notice", "start": 0, "end": 1},
                        "doc_date": None,
                        "date_spans": [],
                        "chamber": "house",
                        "congress": 119,
                        "committees": [],
                        "subcommittees": [],
                        "gist": "Hearing notice.",
                        "topics": ["oversight"],
                    }
                )
            return AdapterOutput(raw_text=raw, extracted_json_str=raw, returncode=0, usage_pct=usage_pct)

        return _adapter

    out_dir = tmp_path / "batched_run"
    cache_path = tmp_path / "batched_cache.sqlite"
    res = run_sharded_corpus_build(
        candidates_path=cand_path,
        out_dir=out_dir,
        cache_path=cache_path,
        shard_size=4,
        workers=2,
        families=("claude", "codex"),
        specialist_families=("claude",),
        batch_size=4,
        specialist_batch_size=2,
        max_usage_pct=50.0,
        live_checkeval=False,
        adapters={
            "claude": _make_batched_adapter("claude", stop_on_shard2=True),
            "codex": _make_batched_adapter("codex", stop_on_shard2=True),
        },
    )
    # Shard 0 (4 docs) succeeds (with fallback recovering dropped d02); Shard 1 hits 55% usage and halts cleanly!
    assert res["completed_shards"] == 1
    assert res["stopped_reason"] is not None and "codex" in res["stopped_reason"]
    assert res["usage_guard"]["tripped"] is True
    assert (out_dir / "shards" / "shard_0000.jsonl").is_file()
    assert not (out_dir / "shards" / "shard_0001.jsonl").exists()

    with SixTupleCache(cache_path) as c:
        stats = c.stats()
        assert stats["total_entries"] >= 12  # Shard 0 (4 claude + 4 codex + 4 spec) + valid unpacked items from Shard 1!


def _collect_refs(node: object) -> list[str]:
    refs: list[str] = []
    if isinstance(node, dict):
        if isinstance(node.get("$ref"), str):
            refs.append(node["$ref"])
        for val in node.values():
            refs.extend(_collect_refs(val))
    elif isinstance(node, list):
        for item in node:
            refs.extend(_collect_refs(item))
    return refs


def test_build_batch_schema_hoists_defs_for_all_v7_schemas() -> None:
    from congress_docmeta.v7.factory.pilot import _resolve_v7_runtime_specs

    _cb_ver, core_schema, specialist_schemas, _core_cls, _spec_clses = _resolve_v7_runtime_specs(None)
    assert len(specialist_schemas) == 5

    all_schemas = [("DocMetaCoreTriageBatch", core_schema)] + [
        (f"DocMetaSpecialistBatch_{sf}", sc) for sf, sc in sorted(specialist_schemas.items())
    ]
    for title, single_schema in all_schemas:
        batch = build_batch_schema(single_schema, title)
        assert isinstance(batch.get("$defs"), dict) and batch["$defs"], f"Missing top-level $defs for {title}"
        assert "$defs" not in batch["properties"]["items"]["items"]
        refs = _collect_refs(batch)
        assert refs, f"Expected $ref entries in {title}"
        for ref in refs:
            assert ref.startswith("#/$defs/"), f"Unexpected $ref {ref!r} in {title}"
            def_name = ref.split("#/$defs/", 1)[1]
            assert def_name in batch["$defs"], f"Dangling $ref {ref!r} in {title}"


def test_usage_guard_requires_telemetry_and_trips_on_schema_rejection(tmp_path: Path) -> None:
    from congress_docmeta.v7.factory.runners import AdapterOutput, UsageGuard

    guard = UsageGuard(max_usage_pct=50.0, require_telemetry=True, max_missing_telemetry=2)
    assert guard.record("claude", None, returncode=0) is False
    assert guard.record("claude", 6.0, returncode=0) is False  # Resets missing streak!
    assert guard.record("claude", None, returncode=0) is False
    assert guard.record("codex", None, error="nonzero_error", returncode=1) is False  # Failed call does not count.
    assert guard.record("claude", None, returncode=0) is True
    assert guard.triggered_reason is not None and "without usage_pct telemetry" in guard.triggered_reason

    cand_path = tmp_path / "cands_schema_err.jsonl"
    docs = [
        {
            "pool_index": i,
            "doc_key": f"schema_doc_{i:04d}",
            "text": f"Committee Hearing Notice {i}: Oversight TopicBeta_{i} on March {10 + i}, 2025.",
            "filename": f"HHRG-119-IF00-Notice-{i}.pdf",
            "source_pool": "archive_v6_2",
            "stratum": "locked_kind:hearing_notice",
            "doc_date": f"2025-03-{10 + i:02d}",
            "event_date": f"2025-03-{10 + i:02d}",
            "chamber": "house",
            "committees": ["hsif00"],
            "prior_kind": "hearing_notice",
            "is_2026": False,
        }
        for i in range(4)
    ]
    cand_path.write_text("".join(json.dumps(d) + "\n" for d in docs), encoding="utf-8")

    single_calls = 0

    def _reject_schema_adapter(prompt: str, schema: dict, *, model_id: str = "", timeout_s: float = 30.0):
        nonlocal single_calls
        del prompt, model_id, timeout_s
        if "items" not in (schema.get("properties") or {}):
            single_calls += 1
        return AdapterOutput(
            raw_text="",
            extracted_json_str=None,
            returncode=1,
            error='{"error":{"code":"invalid_json_schema","message":"missing $defs"}}',
            usage_pct=6.0,
        )

    out_dir = tmp_path / "schema_err_out"
    res = run_sharded_corpus_build(
        candidates_path=cand_path,
        out_dir=out_dir,
        cache_path=tmp_path / "schema_err_cache.sqlite",
        shard_size=4,
        workers=1,
        families=("claude", "codex"),
        specialist_families=("claude",),
        batch_size=4,
        max_usage_pct=50.0,
        live_checkeval=False,
        adapters={"claude": _reject_schema_adapter, "codex": _reject_schema_adapter},
    )
    assert single_calls == 0
    assert res["completed_shards"] == 0
    assert res["usage_guard"]["tripped"] is True
    assert "batch schema rejected" in str(res["stopped_reason"])
    assert not (out_dir / "shards" / "shard_0000.jsonl").exists()


def test_batched_three_family_with_stripped_agy_and_telemetry_guard(monkeypatch, tmp_path: Path) -> None:
    import re
    import congress_docmeta.v7.factory.runners as runners_mod
    from congress_docmeta.v7.factory.cache import SixTupleCache
    from congress_docmeta.v7.factory.runners import AdapterOutput

    cand_path = tmp_path / "candidates_3fam.jsonl"
    docs = []
    # 14 docs: docs 0..11 test agy max_items=12 cap; docs 12 & 13 (60K chars each) test <=110K char cap.
    for i in range(14):
        base = (
            f"Committee Hearing Notice {i}: Oversight TopicThreeFam_{i} on March {10 + (i % 15):02d}, 2025 "
            f"in Rayburn 21{i:02d} before the Committee on Energy and Commerce."
        )
        txt = base if i < 12 else (base + "\n" + ("Additional testimony background details. " * 1500))
        docs.append(
            {
                "pool_index": i,
                "doc_key": f"threefam_doc_{i:04d}",
                "text": txt,
                "filename": f"HHRG-119-IF00-Notice-{i}.pdf",
                "source_pool": "archive_v6_2",
                "stratum": "locked_kind:hearing_notice",
                "doc_date": f"2025-03-{10 + (i % 15):02d}",
                "event_date": f"2025-03-{10 + (i % 15):02d}",
                "chamber": "house",
                "committees": ["hsif00"],
                "prior_kind": "hearing_notice",
                "is_2026": False,
            }
        )
    cand_path.write_text("".join(json.dumps(d) + "\n" for d in docs), encoding="utf-8")

    def _core_item(did: str | None = None) -> dict:
        item = {
            "rationale": "Hearing notice confirmed by Committee Hearing Notice.",
            "status": "usable",
            "media_format": "prose",
            "is_packet": False,
            "contains_genres": [],
            "primary_genre": "hearing_or_markup_notice",
            "specialist_family": "event_logistics",
            "subkind": None,
            "verbatim_title": "Committee Hearing Notice",
            "title_span": {"quote": "Committee Hearing Notice", "start": 0, "end": 1},
            "doc_date": None,
            "date_spans": [],
            "chamber": "house",
            "congress": 119,
            "committees": [],
            "subcommittees": [],
            "gist": "Oversight hearing notice.",
            "topics": ["oversight"],
        }
        if did is not None:
            return {"doc_id": did, **item}
        return item

    def _spec_item(did: str) -> dict:
        return {
            "doc_id": did,
            "rationale": "Batched specialist extraction.",
            "event_type": "hearing",
            "event_title": "Committee Hearing Notice",
            "event_title_span": {"quote": "Committee Hearing Notice", "start": 0, "end": 1},
            "event_date": "2025-03-10",
            "event_date_span": {"quote": "Committee Hearing Notice", "start": 0, "end": 1},
            "event_time": None,
            "venue_kind": "capitol_room",
            "venue": "Energy and Commerce",
            "venue_span": {"quote": "Energy and Commerce", "start": 0, "end": 1},
            "witnesses": [],
            "due_date": None,
            "bill_refs": [],
        }

    agy_chunk_sizes: list[int] = []
    agy_prompt_lengths: list[int] = []
    agy_system_prompts: list[str] = []

    def fake_claude(
        prompt: str,
        schema: dict,
        *,
        model_id: str | None = None,
        effort: str | None = None,
        timeout_s: float = 120.0,
        binary: str = "",
        cwd: Path | None = None,
        system_prompt: str | None = None,
        stripped_prefix: bool = False,
        stream_json: bool = False,
    ) -> AdapterOutput:
        del model_id, effort, timeout_s, binary, cwd
        assert stripped_prefix is True
        assert stream_json is True
        assert system_prompt is not None and len(system_prompt) > 100
        schema_title = str(schema.get("title") or "").lower()
        is_spec = "event_logistics" in schema_title or "eventlogistics" in schema_title
        dids = re.findall(r"doc_id=(d\d+)", prompt)
        if not dids:
            raw = json.dumps(_spec_item("d00") if is_spec else _core_item(None))
            return AdapterOutput(raw_text=raw, extracted_json_str=raw, returncode=0, usage_pct=12.0)
        items = [_spec_item(d) if is_spec else _core_item(d) for d in dids]
        raw = json.dumps({"items": items})
        return AdapterOutput(raw_text=raw, extracted_json_str=raw, returncode=0, usage_pct=12.0)

    def fake_codex(
        prompt: str,
        schema: dict,
        *,
        model_id: str | None = None,
        reasoning_effort: str | None = None,
        timeout_s: float = 120.0,
        binary: str = "",
        cwd: Path | None = None,
        stripped_prefix: bool = False,
        json_events: bool = False,
        ephemeral: bool = True,
        sessions_root: Path | None = None,
    ) -> AdapterOutput:
        del schema, model_id, reasoning_effort, timeout_s, binary, cwd, sessions_root
        assert stripped_prefix is True
        assert json_events is True
        assert ephemeral is False
        dids = re.findall(r"doc_id=(d\d+)", prompt)
        raw = json.dumps({"items": [_core_item(d) for d in dids]})
        return AdapterOutput(raw_text=raw, extracted_json_str=raw, returncode=0, usage_pct=10.0)

    def fake_agy_stripped(
        prompt: str,
        *,
        system_prompt: str,
        model_id: str = "",
        timeout_s: float = 180.0,
        binary: str = "",
        agent_name: str = "",
    ) -> AdapterOutput:
        del timeout_s, binary, agent_name
        assert model_id == "gemini-4-neon-low"
        assert "OUTPUT JSON CONTRACT" in system_prompt
        # Must NOT duplicate the full codebook inside -p prompt when agent.md carries it.
        assert "OUTPUT JSON CONTRACT" not in prompt
        agy_system_prompts.append(system_prompt)
        agy_prompt_lengths.append(len(prompt))
        chunks = re.findall(r"doc_id=(d\d+).*?<<<DOC_TEXT>>>\n(.*?)\n<<<END_DOC_TEXT>>>", prompt, re.DOTALL)
        dids = [d for d, _ in chunks]
        agy_chunk_sizes.append(len(dids))
        # Drop d02 from the 12-doc batch to trigger single-doc fallback, then return bare JSON object!
        if len(dids) == 12:
            raw = json.dumps({"items": [_core_item(d) for d in dids if d != "d02"]})
        elif len(dids) == 1 and "TopicThreeFam_2" in chunks[0][1]:
            raw = json.dumps(_core_item(None))
        else:
            raw = json.dumps({"items": [_core_item(d) for d in dids]})
        return AdapterOutput(raw_text=raw, extracted_json_str=raw, returncode=0, usage_pct=None)

    monkeypatch.setattr(runners_mod, "invoke_claude_cli", fake_claude)
    monkeypatch.setattr(runners_mod, "invoke_codex_cli", fake_codex)
    monkeypatch.setattr(runners_mod, "invoke_agy_stripped_cli", fake_agy_stripped)

    out_dir = tmp_path / "out_3fam"
    cache_path = tmp_path / "cache_3fam.sqlite"
    res = run_sharded_corpus_build(
        candidates_path=cand_path,
        out_dir=out_dir,
        cache_path=cache_path,
        shard_size=14,
        workers=2,
        families=("claude", "codex", "gemini"),
        specialist_families=("claude",),
        batch_size=16,
        specialist_batch_size=8,
        claude_model="claude-opus-5-5",
        claude_effort="low",
        codex_model="gpt-6.1-terra",
        codex_reasoning_effort="low",
        gemini_model="gemini-4-neon-low",
        stripped_prefix=True,
        max_usage_pct=50.0,
        live_checkeval=False,
    )
    assert res["completed_shards"] == 1
    assert res["stopped_reason"] is None
    assert res["usage_guard"]["tripped"] is False
    assert res["usage_guard"]["usage_by_family"] == {"claude": 12.0, "codex": 10.0}
    # Gemini must split into 12 + 1 + 1 + 1 (fallback), never > 12 docs or > 110K chars!
    assert sorted(agy_chunk_sizes) == [1, 1, 1, 12]
    assert max(agy_prompt_lengths) < 110_000

    shard_lines = (out_dir / "shards" / "shard_0000.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(shard_lines) == 14
    for ln in shard_lines:
        row = json.loads(ln)
        assert row["verdict"] == "auto_accept_gold"
        assert sorted(row["consensus_families"]) == ["claude", "codex", "gemini"]
        assert row["specialist_fields"]["venue"] == "Energy and Commerce"

    with SixTupleCache(cache_path) as cache:
        gem_entries = cache._conn.execute(
            "SELECT raw_text FROM completions WHERE family = 'gemini'"
        ).fetchall()
        assert len(gem_entries) == 14
        for (raw_json,) in gem_entries:
            obj = json.loads(raw_json)
            assert "doc_id" not in obj
            assert obj["primary_genre"] == "hearing_or_markup_notice"


def test_cleanlab_audit_handles_missing_optional_deps_gracefully(monkeypatch) -> None:
    import sys
    from congress_docmeta.v7.factory.corpus_builder import _run_cleanlab_audit

    monkeypatch.setitem(sys.modules, "cleanlab", None)
    monkeypatch.setitem(sys.modules, "cleanlab.filter", None)
    classes = ("witness_testimony", "hearing_or_markup_notice", "bill_or_amendment")
    texts = [f"Sample legislative document {i} text for {classes[i % 3]}." for i in range(36)]
    labels = [classes[i % 3] for i in range(36)]
    res = _run_cleanlab_audit(texts, labels)
    assert res["checked"] is False
    assert str(res["reason"]).startswith("optional_dependency_missing:")
    assert res["n_usable"] == 36


def test_seal_supports_extra_shards_candidates_and_overrides(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot.jsonl"
    _write_synthetic_ssot(ssot, count=6)
    q_path, d_path, p_path = _write_synthetic_parquets(tmp_path)
    corpus_dir = tmp_path / "corpus"
    manifest = build_v73_candidate_pool(
        ssot_path=ssot,
        llm_queue_path=q_path,
        deterministic_path=d_path,
        p12_path=p_path,
        out_dir=corpus_dir,
        target_total=10,
        min_2026=3,
        seed=9,
    )
    cand_path = Path(manifest["candidates_path"])
    run_sharded_corpus_build(
        candidates_path=cand_path,
        out_dir=corpus_dir,
        shard_size=10,
        workers=2,
        dry_run=True,
    )

    shard_file = corpus_dir / "shards" / "shard_0000.jsonl"
    orig_bytes = shard_file.read_bytes()
    base_rows = [json.loads(line) for line in shard_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    usable_row = next(r for r in base_rows if (r.get("gold") or {}).get("status") == "usable")
    flipped_dk = str(usable_row["doc_key"])
    deadlock_target_row = next(
        r for r in base_rows if str(r["doc_key"]) != flipped_dk and (r.get("gold") or {}).get("status") == "usable"
    )
    dl_dk = str(deadlock_target_row["doc_key"])

    # Simulate an unedited base shard containing a deadlock by mutating a copy inside a fresh corpus_dir2,
    # keeping shard_file immutable test exact too.
    # Actually make dl_dk a deadlock in shard_file before first seal test, then verify shard_file is untouched by overrides!
    mutated_rows = []
    for r in base_rows:
        if r["doc_key"] == dl_dk:
            mutated_rows.append(
                {
                    **r,
                    "verdict": "deadlock_needs_owner",
                    "deadlock_reason": "three_way_deadlock",
                    "gold": None,
                    "specialist_fields": None,
                }
            )
        else:
            mutated_rows.append(r)
    shard_file.write_text("".join(json.dumps(r) + "\n" for r in mutated_rows), encoding="utf-8")
    locked_shard_bytes = shard_file.read_bytes()

    # Build 1 extra top-up candidate + extra shard row
    extra_dk = "topup_0001_" + ("e" * 53)
    extra_cands = tmp_path / "extra_cands.jsonl"
    extra_cands.write_text(
        json.dumps(
            {
                "pool_index": 10,
                "doc_key": extra_dk,
                "text": "CONGRESSIONAL BUDGET OFFICE COST ESTIMATE H.R. 999 Fiscal Year 2025 budgetary impact.",
                "filename": "hr999cbo.pdf",
                "source_pool": "archive_v6_2_topup",
                "stratum": "budget_topup:fiscal",
                "doc_date": "2024-06-01",
                "event_date": "2024-06-01",
                "chamber": "house",
                "committees": [],
                "prior_kind": None,
                "is_2026": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    extra_shard = tmp_path / "extra_shard.jsonl"
    extra_shard.write_text(
        json.dumps(
            {
                "doc_key": extra_dk,
                "text_sha256": "x" * 64,
                "filename": "hr999cbo.pdf",
                "source_pool": "archive_v6_2_topup",
                "stratum": "budget_topup:fiscal",
                "doc_date": "2024-06-01",
                "event_date": "2024-06-01",
                "chamber": "house",
                "committees": [],
                "prior_kind": None,
                "is_2026": False,
                "verdict": "auto_accept_gold",
                "deadlock_reason": None,
                "consensus_families": ["claude", "codex", "gemini"],
                "gold": {
                    **usable_row["gold"],
                    "primary_genre": "budget_or_cost_estimate",
                    "specialist_family": "legislation_report_fiscal",
                    "verbatim_title": "CONGRESSIONAL BUDGET OFFICE COST ESTIMATE H.R. 999 Fiscal Year 2025",
                    "title_span": None,
                    "doc_date": None,
                    "date_spans": [],
                },
                "specialist_fields": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    overrides_path = tmp_path / "overrides.jsonl"
    overrides_path.write_text(
        json.dumps(
            {
                "doc_key": dl_dk,
                "verdict": "checkeval_resolved",
                "deadlock_reason": None,
                "consensus_families": ["claude", "gemini"],
                "gold": {
                    **deadlock_target_row["gold"],
                    "primary_genre": "qfr_correspondence",
                    "specialist_family": "correspondence_qfr_oversight",
                },
                "specialist_fields": None,
                "polish_source": "deadlock_2of3_verified",
            }
        )
        + "\n"
        + json.dumps(
            {
                "doc_key": flipped_dk,
                "gold": {
                    **usable_row["gold"],
                    "primary_genre": "oversight_or_committee_letter",
                    "specialist_family": "correspondence_qfr_oversight",
                },
                "specialist_fields": None,
                "polish_source": "cleanlab_checkeval",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    sealed = seal_v73_corpus(
        corpus_dir=corpus_dir,
        candidates_path=cand_path,
        extra_candidates_paths=[extra_cands],
        extra_shard_paths=[extra_shard],
        overrides_path=overrides_path,
    )
    assert shard_file.read_bytes() == locked_shard_bytes
    assert orig_bytes != locked_shard_bytes
    assert sealed["total_processed"] == 11
    assert sealed["gold_count"] == 11
    assert sealed["deadlock_count"] == 0
    assert sealed["polish_overrides_applied"] == 2
    assert validate_croissant_manifest(json.loads(Path(sealed["files"]["croissant"]).read_text())) == []
    assert validate_dcat3_catalog(json.loads(Path(sealed["files"]["dcat3"]).read_text())) == []
    tbl = pq.read_table(sealed["files"]["parquet"])
    assert tbl.num_rows == 11
    by_dk = {row["doc_key"]: row for row in tbl.to_pylist()}
    assert by_dk[dl_dk]["primary_genre"] == "qfr_correspondence"
    assert by_dk[flipped_dk]["primary_genre"] == "oversight_or_committee_letter"
    assert by_dk[extra_dk]["primary_genre"] == "budget_or_cost_estimate"


def test_reconcile_and_validate_v7_payload_repairs_and_rejects() -> None:
    from congress_docmeta.v7.factory.grounding import reconcile_and_validate_v7_payload

    text = (
        "CONGRESSIONAL OVERSIGHT HEARING\n"
        "ON GRID SECURITY AND RESILIENCE\n"
        "SAN RAMON, Calif., April 13, 2021\n"
        "Written Testimony of Dr. Maya Lin, Department of Veterans Affairs Office of Inspector General."
    )
    # 1) Fix truncated verbatim_title against grounded title_span + synthesize missing date_spans + fix issuer_org vs issuer_org_span.
    t_start = text.index("CONGRESSIONAL OVERSIGHT HEARING\nON GRID SECURITY AND RESILIENCE")
    t_end = t_start + len("CONGRESSIONAL OVERSIGHT HEARING\nON GRID SECURITY AND RESILIENCE")
    org_start = text.index("Department of Veterans Affairs Office of Inspector General")
    org_end = org_start + len("Department of Veterans Affairs Office of Inspector General")
    name_start = text.index("Dr. Maya Lin")
    name_end = name_start + len("Dr. Maya Lin")

    core_in = {
        "rationale": "Testimony with date in text.",
        "status": "usable",
        "media_format": "prose",
        "is_packet": False,
        "contains_genres": [],
        "primary_genre": "witness_testimony",
        "specialist_family": "testimony_bio_disclosure",
        "subkind": None,
        "verbatim_title": "CONGRESSIONAL OVERSIGHT HEARING ON GRID SECURITY",
        "title_span": {
            "quote": "CONGRESSIONAL OVERSIGHT HEARING\nON GRID SECURITY AND RESILIENCE",
            "start": t_start,
            "end": t_end,
        },
        "doc_date": "2021-04-13",
        "date_spans": [],
        "chamber": None,
        "congress": None,
        "committees": [],
        "subcommittees": [],
        "gist": None,
        "topics": [],
    }
    spec_in = {
        "rationale": "Witness testimony details.",
        "personas": [
            {
                "name": "Maya Lin",
                "name_span": {"quote": "Dr. Maya Lin", "start": name_start, "end": name_end},
                "role": "witness",
                "entity_type": "gov_official",
            }
        ],
        "issuer_org": "VA OIG",
        "issuer_org_span": {
            "quote": "Department of Veterans Affairs Office of Inspector General",
            "start": org_start,
            "end": org_end,
        },
    }
    rec_core, rec_spec, repairs, errs = reconcile_and_validate_v7_payload(text, core_in, spec_in)
    assert errs == []
    assert "reconciled_title_span" in repairs
    assert "synthesized_grounded_date_span" in repairs
    assert "reconciled_issuer_org_span" in repairs
    assert rec_core["date_spans"][0]["quote"] == "April 13, 2021"
    assert rec_spec is not None and rec_spec["issuer_org"] == "Department of Veterans Affairs Office of Inspector General"

    # 2) Abstain ungrounded doc_date when no matching date exists in text.
    no_date_text = "Prepared Statement of Dr. Maya Lin before the Committee on Energy and Commerce."
    core_no_date = {
        **core_in,
        "verbatim_title": "Prepared Statement of Dr. Maya Lin",
        "title_span": None,
        "doc_date": "1999-01-01",
        "date_spans": [],
    }
    rec_core2, _, repairs2, errs2 = reconcile_and_validate_v7_payload(no_date_text, core_no_date)
    assert errs2 == []
    assert "abstained_ungrounded_doc_date" in repairs2
    assert rec_core2["doc_date"] is None


def test_seal_authentic_byte_identity_metadata_and_strict_gates(tmp_path: Path) -> None:
    import pytest

    ssot = tmp_path / "ssot.jsonl"
    _write_synthetic_ssot(ssot, count=6)
    q_path, d_path, p_path = _write_synthetic_parquets(tmp_path)
    corpus_dir = tmp_path / "corpus"
    manifest = build_v73_candidate_pool(
        ssot_path=ssot,
        llm_queue_path=q_path,
        deterministic_path=d_path,
        p12_path=p_path,
        out_dir=corpus_dir,
        target_total=12,
        min_2026=3,
        seed=11,
    )
    cand_path = Path(manifest["candidates_path"])
    cands = [json.loads(ln) for ln in cand_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    # Attach authentic saved_body_hex / link_key_hex on half of the candidates, leave others None.
    for idx, c in enumerate(cands):
        if idx % 2 == 0:
            c["link_key_hex"] = f"{idx + 1:016x}"
            c["saved_body_hex"] = f"{idx + 100:064x}"
        else:
            c.pop("link_key_hex", None)
            c.pop("saved_body_hex", None)
    cand_path.write_text("".join(json.dumps(c) + "\n" for c in cands), encoding="utf-8")

    run_sharded_corpus_build(
        candidates_path=cand_path,
        out_dir=corpus_dir,
        shard_size=12,
        workers=2,
        dry_run=True,
    )

    sealed = seal_v73_corpus(
        corpus_dir=corpus_dir,
        candidates_path=cand_path,
        ssot_path=ssot,
        llm_queue_path=q_path,
        deterministic_path=d_path,
    )
    assert sealed["source_identity_coverage"]["matched_saved_body"] == 6
    assert sealed["source_identity_coverage"]["missing_saved_body"] == 6
    assert sealed["grounding_audit"]["verified_zero_errors"] is True
    assert sealed["counterfactual_suite"]["evaluation_mode"] == "harness_mechanics_self_check"
    assert "git_provenance" in sealed
    assert "train" in sealed["split_genre_counts"] or "sealed_temporal_2026" in sealed["split_genre_counts"]

    tbl = pq.read_table(sealed["files"]["parquet"])
    croissant = json.loads(Path(sealed["files"]["croissant"]).read_text(encoding="utf-8"))
    assert validate_croissant_manifest(croissant, expected_columns=tbl.schema.names) == []
    assert croissant["version"] == "7.3.0"
    assert "single teacher (`claude`)" in croissant["rai:dataLimitations"]

    by_dk = {r["doc_key"]: r for r in tbl.to_pylist()}
    for idx, c in enumerate(cands):
        row = by_dk[c["doc_key"]]
        if idx % 2 == 0:
            assert row["body_sha256"] == f"{idx + 100:064x}"
            assert row["link_key_hex"] == f"{idx + 1:016x}"
        else:
            # Must NEVER fabricate body_sha256 from doc_key or sha256(doc_key)!
            assert row["body_sha256"] is None
            assert row["link_key_hex"] is None

    # Strict mode must fail closed when minilm_checked is False or genres are below floor!
    manifest_file = corpus_dir / "sealed" / "MANIFEST.json"
    manifest_file.unlink()
    with pytest.raises(RuntimeError, match="Strict seal gate failed"):
        seal_v73_corpus(
            corpus_dir=corpus_dir,
            candidates_path=cand_path,
            ssot_path=ssot,
            llm_queue_path=q_path,
            deterministic_path=d_path,
            strict=True,
            min_genre_count=150,
        )
    assert not manifest_file.exists()
    assert (corpus_dir / "sealed" / "MANIFEST_FAILED.json").is_file()


def test_seal_similarity_waivers_and_hard_leak_never_waived(tmp_path: Path, monkeypatch) -> None:
    import pytest
    import congress_docmeta.v7.factory.corpus_builder as cb_mod
    from congress_docmeta.v7.factory.splits import DecontamFlag, DecontaminationReport

    ssot = tmp_path / "ssot.jsonl"
    _write_synthetic_ssot(ssot, count=6)
    q_path, d_path, p_path = _write_synthetic_parquets(tmp_path)
    corpus_dir = tmp_path / "corpus"
    manifest = build_v73_candidate_pool(
        ssot_path=ssot,
        llm_queue_path=q_path,
        deterministic_path=d_path,
        p12_path=p_path,
        out_dir=corpus_dir,
        target_total=12,
        min_2026=3,
        seed=17,
    )
    cand_path = Path(manifest["candidates_path"])
    run_sharded_corpus_build(candidates_path=cand_path, out_dir=corpus_dir, shard_size=12, workers=2, dry_run=True)

    cands = [json.loads(ln) for ln in cand_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    # Clear event_date/doc_date on two error/unlocked docs so extract_event_group_key and dates are None -> is_distinct_event=False.
    cands[2]["event_date"] = None
    cands[2]["doc_date"] = None
    cands[2]["filename"] = "a.htm"
    cands[3]["event_date"] = None
    cands[3]["doc_date"] = None
    cands[3]["filename"] = "b.htm"
    cand_path.write_text("".join(json.dumps(c) + "\n" for c in cands), encoding="utf-8")
    eval_dk = cands[2]["doc_key"]
    train_dk = cands[3]["doc_key"]

    # Case 1: unwaived is_distinct_event=False similarity hit MUST fail closed under strict=True.
    monkeypatch.setattr(
        cb_mod,
        "_run_cleanlab_audit",
        lambda texts, labels: {"checked": True, "n_audited": len(texts), "flagged_count": 0},
    )
    monkeypatch.setattr(
        cb_mod,
        "audit_decontamination",
        lambda tr, ev, **kw: DecontaminationReport(
            clean=False,
            train_count=len(tr),
            eval_count=len(ev),
            flagged_count=1,
            flagged_docs=[
                DecontamFlag(
                    eval_doc_key=eval_dk,
                    eval_split="dev_iter",
                    matched_train_doc_key=train_dk,
                    reasons=["minilm_cosine"],
                    minilm_cosine=0.95,
                )
            ],
            reason_counts={"minilm_cosine": 1},
            minilm_checked=True,
        ),
    )

    with pytest.raises(RuntimeError, match="similarity_decontam"):
        seal_v73_corpus(
            corpus_dir=corpus_dir,
            candidates_path=cand_path,
            ssot_path=ssot,
            llm_queue_path=q_path,
            deterministic_path=d_path,
            strict=True,
            min_genre_count=0,
            allow_boilerplate_tfidf=True,
        )

    # Case 2: exact reviewed waiver passes similarity_decontam and records applied waiver.
    waivers_file = tmp_path / "waivers.json"
    waivers_file.write_text(
        json.dumps([{"eval_doc_key": eval_dk, "matched_train_doc_key": train_dk, "reason": "Distinct nominees."}], indent=2),
        encoding="utf-8",
    )
    res_ok = seal_v73_corpus(
        corpus_dir=corpus_dir,
        candidates_path=cand_path,
        ssot_path=ssot,
        llm_queue_path=q_path,
        deterministic_path=d_path,
        strict=True,
        min_genre_count=0,
        allow_boilerplate_tfidf=True,
        decontam_waivers_path=waivers_file,
    )
    assert res_ok["seal_gates"]["passed"] is True
    assert len(res_ok["decontamination_waivers_applied"]) == 1
    assert res_ok["decontamination_waivers_applied"][0]["eval_doc_key"] == eval_dk

    # Case 3: hard leak (`exact_sha`) can NEVER be waived even when pair is listed in waivers.
    monkeypatch.setattr(
        cb_mod,
        "audit_decontamination",
        lambda tr, ev, **kw: DecontaminationReport(
            clean=False,
            train_count=len(tr),
            eval_count=len(ev),
            flagged_count=1,
            flagged_docs=[
                DecontamFlag(
                    eval_doc_key=eval_dk,
                    eval_split="dev_iter",
                    matched_train_doc_key=train_dk,
                    reasons=["exact_sha"],
                )
            ],
            reason_counts={"exact_sha": 1},
            minilm_checked=True,
        ),
    )
    with pytest.raises(RuntimeError, match="hard_decontam_zero"):
        seal_v73_corpus(
            corpus_dir=corpus_dir,
            candidates_path=cand_path,
            ssot_path=ssot,
            llm_queue_path=q_path,
            deterministic_path=d_path,
            strict=True,
            min_genre_count=0,
            allow_boilerplate_tfidf=True,
            decontam_waivers_path=waivers_file,
        )


def test_bidi_invisible_format_grounding_and_title_repair() -> None:
    from congress_docmeta.v7.factory.grounding import (
        reconcile_and_validate_v7_payload,
        repair_span_refs_in_payload,
        strip_invisible_format_chars,
        verify_span_grounding,
    )

    bidi_text = (
        "\u202dWritten Testimony of\u202c\n"
        "\u202dDr. Jayesh K. Gupta\u202c\n"
        "\u202dJuly 16, 2025\u202c\n"
        "\u202dChairman Franklin, thank you for the opportunity to testify.\u202c"
    )
    assert strip_invisible_format_chars(bidi_text).startswith("Written Testimony of\nDr. Jayesh K. Gupta")

    clean_title = "Written Testimony of Dr. Jayesh K. Gupta"
    core_in = {
        "rationale": "Explicit written witness testimony heading and date.",
        "status": "usable",
        "media_format": "prose",
        "is_packet": False,
        "contains_genres": [],
        "primary_genre": "witness_testimony",
        "specialist_family": "testimony_bio_disclosure",
        "subkind": "written_testimony",
        "verbatim_title": clean_title,
        "title_span": {"quote": clean_title, "start": 0, "end": 1},
        "doc_date": "2025-07-16",
        "date_spans": [],
        "chamber": "house",
        "congress": 119,
        "committees": [],
        "subcommittees": [],
        "gist": "Written testimony on weather forecasting.",
        "topics": ["weather"],
    }
    repaired = repair_span_refs_in_payload(bidi_text, core_in)
    assert "\u202d" not in repaired["title_span"]["quote"]
    assert repaired["title_span"]["start"] == bidi_text.index("Written")
    assert "Dr. Jayesh K. Gupta" in bidi_text[repaired["title_span"]["start"] : repaired["title_span"]["end"]]

    rec_core, rec_spec, repairs, errs = reconcile_and_validate_v7_payload(bidi_text, core_in)
    assert errs == []
    assert rec_spec is None
    assert "synthesized_grounded_date_span" in repairs
    assert rec_core["verbatim_title"] == clean_title
    assert rec_core["date_spans"][0]["quote"] == "July 16, 2025"
    assert verify_span_grounding(bidi_text, rec_core).passed is True


def test_build_pool_excludes_sha_alias_and_appends_p3_rescue(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot.jsonl"
    ssot.write_text("", encoding="utf-8")
    q_path = tmp_path / "llm_queue.parquet"
    d_path = tmp_path / "det.parquet"
    p_path = tmp_path / "p12.parquet"

    # Minimal llm_queue row with >9000-char cover/roster p12 + p3 rescue slice (ensures p3 isn't truncated).
    cov_dk = "cover_p3_" + ("e" * 55)
    long_p12 = "U.S. GOVERNMENT PUBLISHING OFFICE HEARING ON CLEAN ENERGY\n" + ("ROSTER ENTRY BLOCK. " * 470)
    assert len(long_p12) > 9000
    q_rows = [
        {
            "list_row": 0,
            "doc_key": cov_dk,
            "p12_clean_text": long_p12,
            "p12_raw_text": long_p12,
            "filename": "CHRG-119hhrg99999.pdf",
            "rel_event_date": "2025-04-01",
            "rel_chamber": "house",
            "rel_committees": ["hsif00"],
            "locked_primary_kind": "hearing_transcript",
            "effective_format": "pdf",
            "stapled_ttf_disclosure_json": None,
            "p3_toc_or_gavel_slice": "The subcommittee met at 10:00 a.m., Hon. Chair presiding.",
            "is_cover_roster_p12": True,
        }
    ]
    # Deterministic rows: 1 sha_alias (MUST be excluded from Stratum F) + 1 genuine error_or_block.
    alias_dk = "sha_alias_" + ("f" * 54)
    err_dk = "real_err_" + ("9" * 55)
    d_rows = [
        {
            "list_row": 0,
            "doc_key": cov_dk,
            "filename": "CHRG-119hhrg99999.pdf",
            "rel_event_date": "2025-04-01",
            "v6_det_chamber": "house",
            "v6_det_committees": ["hsif00"],
            "effective_format": "pdf",
            "deterministic_status": "queued_llm",
        },
        {
            "list_row": 1,
            "doc_key": alias_dk,
            "filename": "regan-testimony.pdf",
            "rel_event_date": "2025-04-01",
            "v6_det_chamber": "house",
            "v6_det_committees": ["hsif00"],
            "effective_format": "pdf",
            "deterministic_status": "sha_alias",
        },
        {
            "list_row": 2,
            "doc_key": err_dk,
            "filename": "err.pdf",
            "rel_event_date": "2025-04-01",
            "v6_det_chamber": "house",
            "v6_det_committees": [],
            "effective_format": "html",
            "deterministic_status": "error_or_block",
        },
    ]
    p_rows = [
        {
            "list_row": 0,
            "p12_lines": "U.S. GOVERNMENT PUBLISHING OFFICE HEARING ON CLEAN ENERGY",
            "html_cms_nav_stripped_text": None,
            "waf_or_error_detected": False,
        },
        {
            "list_row": 1,
            "p12_lines": "COVER ONLY ALIAS",
            "html_cms_nav_stripped_text": None,
            "waf_or_error_detected": False,
        },
        {
            "list_row": 2,
            "p12_lines": "403 Forbidden Cloudflare Access Denied",
            "html_cms_nav_stripped_text": None,
            "waf_or_error_detected": True,
        },
    ]
    pq.write_table(pa.Table.from_pylist(q_rows), q_path)
    pq.write_table(pa.Table.from_pylist(d_rows), d_path)
    pq.write_table(pa.Table.from_pylist(p_rows), p_path)

    manifest = build_v73_candidate_pool(
        ssot_path=ssot,
        llm_queue_path=q_path,
        deterministic_path=d_path,
        p12_path=p_path,
        out_dir=tmp_path / "pool",
        target_total=10,
        min_2026=0,
        seed=5,
    )
    cands = [
        json.loads(ln)
        for ln in Path(manifest["candidates_path"]).read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    by_dk = {c["doc_key"]: c for c in cands}
    assert alias_dk not in by_dk
    assert err_dk in by_dk
    assert cov_dk in by_dk
    assert "[... p3 rescue ...]" in by_dk[cov_dk]["text"]
    assert "The subcommittee met at 10:00 a.m." in by_dk[cov_dk]["text"]


def test_seal_hygiene_gates_quarantine_body_contradiction_and_blank_head(tmp_path: Path, monkeypatch) -> None:
    import pytest
    import congress_docmeta.v7.factory.corpus_builder as cb_mod
    from congress_docmeta.v7.factory.splits import DecontaminationReport

    ssot = tmp_path / "ssot.jsonl"
    _write_synthetic_ssot(ssot, count=6)
    q_path, d_path, p_path = _write_synthetic_parquets(tmp_path)
    corpus_dir = tmp_path / "corpus"
    manifest = build_v73_candidate_pool(
        ssot_path=ssot,
        llm_queue_path=q_path,
        deterministic_path=d_path,
        p12_path=p_path,
        out_dir=corpus_dir,
        target_total=12,
        min_2026=3,
        seed=19,
    )
    cand_path = Path(manifest["candidates_path"])
    run_sharded_corpus_build(candidates_path=cand_path, out_dir=corpus_dir, shard_size=12, workers=2, dry_run=True)

    cands = [json.loads(ln) for ln in cand_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    shard_rows = [json.loads(ln) for ln in (corpus_dir / "shards" / "shard_0000.jsonl").read_text().splitlines() if ln.strip()]
    usable_row = next(r for r in shard_rows if (r.get("gold") or {}).get("status") == "usable")
    usable_dk = usable_row["doc_key"]
    other_usable_dk = next(r["doc_key"] for r in shard_rows if (r.get("gold") or {}).get("status") == "usable" and r["doc_key"] != usable_dk)

    # Mock cleanlab & decontam so only the new hygiene gates decide strict pass/fail.
    monkeypatch.setattr(
        cb_mod,
        "_run_cleanlab_audit",
        lambda texts, labels: {"checked": True, "n_audited": len(texts), "flagged_count": 0},
    )
    monkeypatch.setattr(
        cb_mod,
        "audit_decontamination",
        lambda tr, ev, **kw: DecontaminationReport(
            clean=True,
            train_count=len(tr),
            eval_count=len(ev),
            flagged_count=0,
            flagged_docs=[],
            reason_counts={},
            minilm_checked=True,
        ),
    )

    # 1) Conflicting usable vs cover_or_toc on identical body_sha256 MUST fail body_sha_status_consistency.
    shared_sha = "ab" * 32
    for idx, c in enumerate(cands):
        c["link_key_hex"] = f"{idx + 1:016x}"
        c["saved_body_hex"] = shared_sha if c["doc_key"] in (usable_dk, other_usable_dk) else f"{idx + 50:064x}"
    cand_path.write_text("".join(json.dumps(c) + "\n" for c in cands), encoding="utf-8")

    conflict_ov = tmp_path / "conflict_ov.jsonl"
    conflict_ov.write_text(
        json.dumps(
            {
                "doc_key": other_usable_dk,
                "gold": {
                    **usable_row["gold"],
                    "status": "cover_or_toc",
                    "media_format": None,
                    "is_packet": False,
                    "contains_genres": [],
                    "primary_genre": None,
                    "specialist_family": None,
                    "subkind": None,
                    "title_span": None,
                    "doc_date": None,
                    "date_spans": [],
                },
                "specialist_fields": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="body_sha_status_consistency"):
        seal_v73_corpus(
            corpus_dir=corpus_dir,
            candidates_path=cand_path,
            overrides_path=conflict_ov,
            ssot_path=ssot,
            llm_queue_path=q_path,
            deterministic_path=d_path,
            strict=True,
            min_genre_count=0,
        )

    # 2) Blank-head tail-only window in gold MUST fail zero_blank_head_tail_only.
    tail_dk = other_usable_dk
    for idx, c in enumerate(cands):
        c["saved_body_hex"] = f"{idx + 50:064x}"
        if c["doc_key"] == tail_dk:
            c["text"] = "\n\n[... page 29 tail ...]\n25\nIf confirmed I will work with GPO. April 13, 2021."
    cand_path.write_text("".join(json.dumps(c) + "\n" for c in cands), encoding="utf-8")
    clean_tail_ov = tmp_path / "tail_ov.jsonl"
    clean_tail_ov.write_text(
        json.dumps(
            {
                "doc_key": tail_dk,
                "gold": {
                    "rationale": "Tail fragment only.",
                    "status": "usable",
                    "media_format": "prose",
                    "is_packet": False,
                    "contains_genres": [],
                    "primary_genre": "witness_testimony",
                    "specialist_family": "testimony_bio_disclosure",
                    "subkind": None,
                    "verbatim_title": None,
                    "title_span": None,
                    "doc_date": None,
                    "date_spans": [],
                    "chamber": None,
                    "congress": None,
                    "committees": [],
                    "subcommittees": [],
                    "gist": "Tail fragment.",
                    "topics": [],
                },
                "specialist_fields": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="zero_blank_head_tail_only"):
        seal_v73_corpus(
            corpus_dir=corpus_dir,
            candidates_path=cand_path,
            overrides_path=clean_tail_ov,
            ssot_path=ssot,
            llm_queue_path=q_path,
            deterministic_path=d_path,
            strict=True,
            min_genre_count=0,
        )

    # 3) Quarantining tail_dk resolves zero_blank_head_tail_only, writes quarantined_v7_3.jsonl, and passes 9/9 checks.
    quar_ov = tmp_path / "quar_ov.jsonl"
    quar_ov.write_text(
        json.dumps(
            {
                "doc_key": tail_dk,
                "verdict": "quarantined_excluded",
                "deadlock_reason": "quarantined_blank_head_tail_only",
                "gold": None,
                "specialist_fields": None,
                "polish_source": "v7_3_1_hygiene_rc2",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    ok_manifest = seal_v73_corpus(
        corpus_dir=corpus_dir,
        candidates_path=cand_path,
        overrides_path=quar_ov,
        ssot_path=ssot,
        llm_queue_path=q_path,
        deterministic_path=d_path,
        strict=True,
        min_genre_count=0,
    )
    assert ok_manifest["seal_gates"]["passed"] is True
    assert ok_manifest["seal_gates"]["checks"]["body_sha_status_consistency"] is True
    assert ok_manifest["seal_gates"]["checks"]["zero_blank_head_tail_only"] is True
    assert ok_manifest["quarantined_count"] == 1
    assert ok_manifest["gold_count"] == 11
    assert Path(ok_manifest["files"]["quarantined_jsonl"]).is_file()

    # 4) Atomic staging on --strict failure preserves prior sealed files & cleans .staging_seal;
    #    title-only-head tail (<80 non-ws head chars) fails zero_blank_head_tail_only while
    #    a substantial >=80-char head + [... page N tail ...] passes; and two conflicting
    #    non-usable statuses (cover_or_toc vs ocr_unreadable) fail body_sha_status_consistency.
    atomic_out = tmp_path / "atomic_sealed"
    atomic_out.mkdir(parents=True, exist_ok=True)
    prior_manifest_bytes = b'{"sealed_at":"sentinel","gold_count":999}'
    prior_pq_bytes = b"PAR1_SENTINEL_KEEP_INTACT"
    (atomic_out / "MANIFEST.json").write_bytes(prior_manifest_bytes)
    (atomic_out / "docmeta_v7_3.parquet").write_bytes(prior_pq_bytes)

    third_dk = next(
        r["doc_key"]
        for r in shard_rows
        if (r.get("gold") or {}).get("status") == "usable" and r["doc_key"] not in (usable_dk, tail_dk)
    )
    for idx, c in enumerate(cands):
        if c["doc_key"] == usable_dk:
            c["saved_body_hex"] = shared_sha
        elif c["doc_key"] == third_dk:
            c["saved_body_hex"] = shared_sha
        else:
            c["saved_body_hex"] = f"{idx + 150:064x}"
        if c["doc_key"] == tail_dk:
            c["text"] = "WELFARE REFORM PROPOSALS\n\n\n[... page 390 tail ...]\n382\nFrom: public@example.org April 13, 2021."
    cand_path.write_text("".join(json.dumps(c) + "\n" for c in cands), encoding="utf-8")

    nonusable_conflict_ov = tmp_path / "nonusable_conflict_ov.jsonl"
    nonusable_base = {
        **usable_row["gold"],
        "media_format": None,
        "is_packet": False,
        "contains_genres": [],
        "primary_genre": None,
        "specialist_family": None,
        "subkind": None,
        "title_span": None,
        "doc_date": None,
        "date_spans": [],
    }
    nonusable_conflict_ov.write_text(
        "".join(
            json.dumps(x) + "\n"
            for x in [
                {"doc_key": usable_dk, "gold": {**nonusable_base, "status": "cover_or_toc"}, "specialist_fields": None},
                {"doc_key": third_dk, "gold": {**nonusable_base, "status": "ocr_unreadable"}, "specialist_fields": None},
                {"doc_key": tail_dk, "gold": json.loads(clean_tail_ov.read_text(encoding="utf-8").splitlines()[0])["gold"], "specialist_fields": None},
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="body_sha_status_consistency") as exc_info:
        seal_v73_corpus(
            corpus_dir=corpus_dir,
            candidates_path=cand_path,
            out_dir=atomic_out,
            overrides_path=nonusable_conflict_ov,
            ssot_path=ssot,
            llm_queue_path=q_path,
            deterministic_path=d_path,
            strict=True,
            min_genre_count=0,
        )
    assert "zero_blank_head_tail_only" in str(exc_info.value)
    assert (atomic_out / "MANIFEST.json").read_bytes() == prior_manifest_bytes
    assert (atomic_out / "docmeta_v7_3.parquet").read_bytes() == prior_pq_bytes
    assert (atomic_out / "MANIFEST_FAILED.json").is_file()
    assert not (atomic_out / ".staging_seal").exists()

    # Substantial (>=80 non-ws chars) cover head before [... page N tail ...] is allowed when not contradictory.
    for idx, c in enumerate(cands):
        c["saved_body_hex"] = f"{idx + 250:064x}"
        if c["doc_key"] == tail_dk:
            c["text"] = (
                "SUBCOMMITTEE ON ENVIRONMENT AND MANUFACTURING SLIDE PRESENTATION TITLE COVER PAGE DETAILS\n"
                "Additional presenter subtitle context exceeding eighty characters cleanly.\n\n"
                "[... page 5 tail ...]\nSurface Features. April 13, 2021."
            )
    cand_path.write_text("".join(json.dumps(c) + "\n" for c in cands), encoding="utf-8")
    ok_long_head = seal_v73_corpus(
        corpus_dir=corpus_dir,
        candidates_path=cand_path,
        out_dir=atomic_out,
        overrides_path=clean_tail_ov,
        ssot_path=ssot,
        llm_queue_path=q_path,
        deterministic_path=d_path,
        strict=True,
        min_genre_count=0,
    )
    assert ok_long_head["seal_gates"]["passed"] is True
    assert not (atomic_out / "MANIFEST_FAILED.json").exists()
    assert not (atomic_out / ".staging_seal").exists()
