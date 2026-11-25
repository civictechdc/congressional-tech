"""Offline unit tests for stripped `agy` bulk review & deadlock adjudication (`ct-so28`)."""

from __future__ import annotations

import json
from pathlib import Path
import re

from congress_docmeta.v7.factory.bulk_review import (
    parse_deadlock_digest_md,
    run_bulk_review,
)
from congress_docmeta.v7.factory.runners import (
    AdapterOutput,
    _prepare_stripped_agy_workspace,
    build_agy_stripped_command,
)


def _core_payload(
    *,
    status: str = "usable",
    media_format: str | None = "prose",
    primary_genre: str | None = "hearing_or_markup_notice",
    specialist_family: str | None = "event_logistics",
    quote: str = "Committee Hearing Notice",
) -> dict:
    is_usable = status == "usable"
    return {
        "rationale": f"Classified from verbatim quote {quote}.",
        "status": status,
        "media_format": media_format if is_usable else None,
        "is_packet": False,
        "contains_genres": [],
        "primary_genre": primary_genre if is_usable else None,
        "specialist_family": specialist_family if is_usable else None,
        "subkind": None,
        "verbatim_title": quote if is_usable else None,
        "title_span": {"quote": quote, "start": 0, "end": 1} if is_usable else None,
        "doc_date": None,
        "date_spans": [],
        "chamber": "house" if is_usable else None,
        "congress": 119 if is_usable else None,
        "committees": [],
        "subcommittees": [],
        "gist": "Test document summary.",
        "topics": ["oversight"] if is_usable else [],
    }


def test_stripped_agy_workspace_and_command(tmp_path: Path) -> None:
    ws_cwd, settings_path = _prepare_stripped_agy_workspace(
        tmp_path,
        system_prompt="Return ONLY strict JSON.",
        agent_name="docmeta-bulk-reviewer",
    )
    agent_md = (ws_cwd / ".agents" / "agents" / "docmeta-bulk-reviewer" / "agent.md").read_text(encoding="utf-8")
    assert "tools: []" in agent_md
    assert "mcpServers: []" in agent_md
    assert "skills: []" in agent_md
    assert "plugins: []" in agent_md
    assert "commandExecutionPolicy: off" in agent_md
    assert "Return ONLY strict JSON." in agent_md

    settings_obj = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings_obj["disableSlashCommands"] is True
    assert settings_obj["permissions"] == {"deny": ["*"]}

    cmd = build_agy_stripped_command(
        "Audit batch",
        settings_path,
        agent_name="docmeta-bulk-reviewer",
        model="gemini-4-neon-medium",
    )
    assert "--json-schema" not in cmd
    assert "--mode" not in cmd
    assert "--disable-slash-commands" in cmd
    assert cmd[cmd.index("--model") + 1] == "gemini-4-neon-medium"
    assert cmd[cmd.index("--agent") + 1] == "docmeta-bulk-reviewer"
    assert cmd[cmd.index("--output-format") + 1] == "json"


def test_parse_deadlock_digest_md_handles_3fam_and_2fam(tmp_path: Path) -> None:
    p3 = tmp_path / "deadlocks_shard_0010.md"
    p3.write_text(
        "# DocMeta V7 Deadlock Digest for Owner Review\n\n"
        "## 1. `key_3fam_1` (`three_way_deadlock`)\n\n"
        "> Sample excerpt\n\n"
        "| Family | status | media_format | is_packet | primary_genre | grounding |\n"
        "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
        "| `claude` | `usable` | `prose` | `False` | `hearing_transcript` | `PASS` |\n"
        "| `codex` | `cover_or_toc` | `None` | `False` | `None` | `PASS` |\n"
        "| `gemini` | `None` | `None` | `None` | `None` | `FAIL (1)` |\n\n"
        "- **gemini grounding issues:** `payload`:missing_or_unparsed_payload\n",
        encoding="utf-8",
    )
    d3 = parse_deadlock_digest_md(p3)
    assert d3["key_3fam_1"]["deadlock_reason"] == "three_way_deadlock"
    assert d3["key_3fam_1"]["family_votes"]["claude"]["primary_genre"] == "hearing_transcript"
    assert d3["key_3fam_1"]["family_votes"]["codex"]["status"] == "cover_or_toc"
    assert "missing_or_unparsed_payload" in d3["key_3fam_1"]["grounding_issues"]["gemini"]

    p2 = tmp_path / "deadlocks_shard_0018.md"
    p2.write_text(
        "# DocMeta V7 Deadlock Digest for Owner Review\n\n"
        "## 1. `key_2fam_1` (`checkeval_tie_or_insufficient_evidence`)\n\n"
        "| Family | status | media_format | is_packet | primary_genre | grounding |\n"
        "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
        "| `claude` | `stub_or_blank` | `None` | `False` | `None` | `PASS` |\n"
        "| `codex` | `usable` | `prose` | `False` | `hearing_memo_or_witness_list` | `PASS` |\n\n"
        "- **CheckEval arbiter:** `checkeval_tie_or_insufficient_evidence` (majority=0.5, minority=0.0)\n"
        "  - `q_status_usable` (NO): Is usable?\n",
        encoding="utf-8",
    )
    d2 = parse_deadlock_digest_md(p2)
    assert d2["key_2fam_1"]["deadlock_reason"] == "checkeval_tie_or_insufficient_evidence"
    assert d2["key_2fam_1"]["family_votes"]["claude"]["status"] == "stub_or_blank"
    assert d2["key_2fam_1"]["family_votes"]["codex"]["primary_genre"] == "hearing_memo_or_witness_list"
    assert "q_status_usable" in d2["key_2fam_1"]["checkeval_summary"]


def test_run_bulk_review_audit_deadlocks_resume_and_quota_stop(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    shards_dir = corpus_dir / "shards"
    shards_dir.mkdir(parents=True)

    # Candidate texts, including Unicode \u2028 line separator inside text!
    docs = [
        {"doc_key": "dl_0000_a", "text": "Committee Hearing Transcript Draft with Speaker Turn One."},
        {"doc_key": "dl_0000_b", "text": "Brief unclear stub header only."},
        {"doc_key": "dl_0000_c", "text": "Witness Testimony of Alice Example before Energy Committee."},
        # 2-family shard 0018 docs (5 docs: confirmed_3of3, disagreement_gold [dropped in batch -> fallback],
        # confirmed_checkeval, disagreement_checkeval, deadlock_neon_vote)
        {"doc_key": "k_conf3", "text": "Committee Hearing Notice Alpha\u2028on AI Safety May 2025."},
        {"doc_key": "k_disgold", "text": "Committee Hearing Notice Beta actually Transcript Q&A Senator Smith."},
        {"doc_key": "k_confce", "text": "Committee Hearing Notice Gamma Oversight Schedule."},
        {"doc_key": "k_disce", "text": "Committee Hearing Notice Delta Roll Call Vote 12-4 Reported."},
        {"doc_key": "k_dl18", "text": "James Robbins M.D. Accompanied by Veterans Affairs Director."},
    ]
    with (corpus_dir / "candidates_v7_3.jsonl").open("w", encoding="utf-8") as fh:
        for i, d in enumerate(docs):
            fh.write(json.dumps({"pool_index": i, **d}, ensure_ascii=False) + "\n")

    # Shard 0000 (3-family deadlocks)
    s0_rows = [
        {"doc_key": "dl_0000_a", "verdict": "deadlock_needs_owner", "deadlock_reason": "three_way_deadlock", "gold": None},
        {"doc_key": "dl_0000_b", "verdict": "deadlock_needs_owner", "deadlock_reason": "checkeval_explicit_ambiguous", "gold": None},
        {"doc_key": "dl_0000_c", "verdict": "deadlock_needs_owner", "deadlock_reason": "three_way_deadlock", "gold": None},
    ]
    with (shards_dir / "shard_0000.jsonl").open("w", encoding="utf-8") as fh:
        for r in s0_rows:
            fh.write(json.dumps(r) + "\n")
    (shards_dir / "shard_0000.meta.json").write_text(json.dumps({"total_docs": 3}), encoding="utf-8")
    (shards_dir / "deadlocks_shard_0000.md").write_text(
        "## 1. `dl_0000_a` (`three_way_deadlock`)\n"
        "| `claude` | `usable` | `prose` | `False` | `hearing_transcript` | `PASS` |\n\n"
        "## 2. `dl_0000_b` (`checkeval_explicit_ambiguous`)\n"
        "| `claude` | `stub_or_blank` | `None` | `False` | `None` | `PASS` |\n\n"
        "## 3. `dl_0000_c` (`three_way_deadlock`)\n"
        "| `claude` | `usable` | `prose` | `False` | `witness_testimony` | `PASS` |\n",
        encoding="utf-8",
    )

    # Shard 0018 (2-family audit shard)
    s18_rows = [
        {"doc_key": "k_conf3", "verdict": "auto_accept_gold", "consensus_families": ["claude", "codex"], "gold": _core_payload(quote="Committee Hearing Notice Alpha")},
        {"doc_key": "k_disgold", "verdict": "auto_accept_gold", "consensus_families": ["claude", "codex"], "gold": _core_payload(quote="Committee Hearing Notice Beta")},
        {"doc_key": "k_confce", "verdict": "checkeval_resolved", "consensus_families": ["claude"], "gold": _core_payload(quote="Committee Hearing Notice Gamma")},
        {"doc_key": "k_disce", "verdict": "checkeval_resolved", "consensus_families": ["codex"], "gold": _core_payload(quote="Committee Hearing Notice Delta")},
        {"doc_key": "k_dl18", "verdict": "deadlock_needs_owner", "deadlock_reason": "checkeval_tie_or_insufficient_evidence", "gold": None},
    ]
    with (shards_dir / "shard_0018.jsonl").open("w", encoding="utf-8") as fh:
        for r in s18_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (shards_dir / "shard_0018.meta.json").write_text(json.dumps({"total_docs": 5}), encoding="utf-8")

    call_count = 0

    def _mock_agy(prompt: str, *, system_prompt: str = "", model_id: str = "", timeout_s: float = 60.0):
        nonlocal call_count
        del model_id, timeout_s
        call_count += 1
        is_deadlock = "Adjudicate all" in prompt or "deadlock adjudicator" in system_prompt
        chunks = re.findall(r"doc_id=(d\d+).*?<<<DOC_TEXT>>>\n(.*?)\n<<<END_DOC_TEXT>>>", prompt, re.DOTALL)
        items = []
        for did, txt in chunks:
            if not is_deadlock:
                # Drop k_disgold on initial batch (>1 doc) to exercise single-doc fallback!
                if len(chunks) > 1 and "Notice Beta" in txt:
                    continue
                if "Notice Alpha" in txt:
                    items.append({"doc_id": did, **_core_payload(quote="Committee Hearing Notice Alpha")})
                elif "Notice Beta" in txt:
                    items.append(
                        {
                            "doc_id": did,
                            **_core_payload(
                                primary_genre="hearing_transcript",
                                specialist_family="transcript_vote_attendance",
                                quote="Senator Smith",
                            ),
                        }
                    )
                elif "Notice Gamma" in txt:
                    items.append({"doc_id": did, **_core_payload(quote="Committee Hearing Notice Gamma")})
                elif "Notice Delta" in txt:
                    items.append(
                        {
                            "doc_id": did,
                            **_core_payload(
                                primary_genre="committee_vote_or_action",
                                specialist_family="transcript_vote_attendance",
                                quote="Roll Call Vote 12-4",
                            ),
                        }
                    )
                else:
                    items.append(
                        {
                            "doc_id": did,
                            **_core_payload(status="stub_or_blank", quote="James Robbins M.D."),
                        }
                    )
            else:
                if "Speaker Turn One" in txt:
                    items.append(
                        {
                            "doc_id": did,
                            "recommended_action": "resolve",
                            "matches_prior_family": "claude",
                            "confidence": "high",
                            "evidence_quote": "Speaker Turn One",
                            "rationale": "Grounded transcript speaker turn.",
                            "recommended_core": _core_payload(
                                primary_genre="hearing_transcript",
                                specialist_family="transcript_vote_attendance",
                                quote="Speaker Turn One",
                            ),
                        }
                    )
                elif "unclear stub" in txt:
                    items.append(
                        {
                            "doc_id": did,
                            "recommended_action": "keep_deadlock",
                            "matches_prior_family": None,
                            "confidence": "low",
                            "evidence_quote": "unclear stub header",
                            "rationale": "Genuine short fragment ambiguity.",
                            "recommended_core": None,
                        }
                    )
                elif "Alice Example" in txt:
                    # Fabricated ungrounded quote -> must be flagged validation_passed=False after retry!
                    items.append(
                        {
                            "doc_id": did,
                            "recommended_action": "resolve",
                            "matches_prior_family": "claude",
                            "confidence": "medium",
                            "evidence_quote": "NONEXISTENT FABRICATED QUOTE",
                            "rationale": "Bad ungrounded quote.",
                            "recommended_core": _core_payload(
                                primary_genre="witness_testimony",
                                specialist_family="testimony_bio_disclosure",
                                quote="Witness Testimony of Alice Example",
                            ),
                        }
                    )
                else:
                    items.append(
                        {
                            "doc_id": did,
                            "recommended_action": "resolve",
                            "matches_prior_family": "claude",
                            "confidence": "medium",
                            "evidence_quote": "James Robbins M.D.",
                            "rationale": "Attendance header only -> stub_or_blank.",
                            "recommended_core": _core_payload(status="stub_or_blank", quote="James Robbins M.D."),
                        }
                    )
        return AdapterOutput(raw_text=json.dumps({"items": items}), extracted_json_str=json.dumps({"items": items}), returncode=0)

    out_dir = tmp_path / "bulk_out"
    summary = run_bulk_review(
        corpus_dir=corpus_dir,
        out_dir=out_dir,
        min_2fam_shard=18,
        batch_size=5,
        deadlock_batch_size=4,
        workers=1,
        adapter_fn=_mock_agy,
    )
    assert summary["total_2fam_docs_reviewed"] == 5
    assert summary["audit_status_counts"] == {
        "confirmed_3of3": 1,
        "disagreement_gold": 1,
        "confirmed_checkeval": 1,
        "disagreement_checkeval": 1,
        "deadlock_neon_vote": 1,
    }
    assert summary["total_deadlocks_seen"] == 4
    assert summary["total_deadlocks_reviewed"] == 4
    assert summary["deadlock_validation_passed"] == 3  # dl_0000_c fabricated quote marked False!
    assert (out_dir / "shards" / "review_shard_0018.meta.json").is_file()
    assert (out_dir / "bulk_review_report.md").is_file()

    # Check Unicode \u2028 didn't break JSONL line count
    rev_lines = list((out_dir / "shards" / "review_shard_0018.jsonl").open("r", encoding="utf-8"))
    assert len(rev_lines) == 5

    # Idempotent rerun triggers zero extra model calls!
    calls_before_rerun = call_count
    _ = run_bulk_review(
        corpus_dir=corpus_dir,
        out_dir=out_dir,
        min_2fam_shard=18,
        batch_size=5,
        deadlock_batch_size=4,
        workers=1,
        adapter_fn=_mock_agy,
    )
    assert call_count == calls_before_rerun

    # Add shard 0019 and simulate RESOURCE_EXHAUSTED quota halt -> does not seal review_shard_0019
    with (corpus_dir / "candidates_v7_3.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"pool_index": 8, "doc_key": "k_s19", "text": "Hearing Notice 19"}) + "\n")
    (shards_dir / "shard_0019.jsonl").write_text(
        json.dumps({"doc_key": "k_s19", "verdict": "auto_accept_gold", "gold": _core_payload(quote="Hearing Notice 19")}) + "\n",
        encoding="utf-8",
    )
    (shards_dir / "shard_0019.meta.json").write_text(json.dumps({"total_docs": 1}), encoding="utf-8")

    def _quota_err(*_a, **_kw):
        return AdapterOutput(
            raw_text="",
            extracted_json_str=None,
            returncode=1,
            error="RESOURCE_EXHAUSTED: 429 capacity exceeded",
        )

    halted = run_bulk_review(
        corpus_dir=corpus_dir,
        out_dir=out_dir,
        min_2fam_shard=18,
        workers=1,
        adapter_fn=_quota_err,
    )
    assert halted["stopped_reason"] is not None and "RESOURCE_EXHAUSTED" in halted["stopped_reason"]
    assert not (out_dir / "shards" / "review_shard_0019.meta.json").exists()
