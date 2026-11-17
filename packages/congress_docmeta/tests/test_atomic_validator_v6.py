"""`V0_Stdlib_Atomic`, validator question building and the Pass-2 loop for `congress_docmeta`; no model needed."""

from __future__ import annotations

import collections
import copy
import json
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any

import pytest

from congress_docmeta import (
    DOCMETA_V4_SCHEMA_PATH,
    SCHEMA_V4_STR,
    AtomicOutputValidatorV6,
    build_excluded_kind_schema_v6,
    build_genre_conditional_question_v6,
    escalate_anomalies_gpt_oss,
    score_atomic_stdlib_v6,
    score_docmeta_anomalies_v6,
    surname_token_v6,
)
from docmeta_test_support import _auroc, _load_docs8_pairs, _load_val48_records

REPO_ROOT = Path(__file__).resolve().parents[1]  # this package
SRC_DIR = REPO_ROOT / "src"


def test_stdlib_isolation_and_repo_hygiene() -> None:
    """Verify `/usr/bin/python3 -B -I -S` imports `anomaly_router_v6`, `atomic_validator_v6`, and `parquet_runner_v6`."""
    for script_rel in (
        "src/congress_docmeta/anomaly_router_v6.py",
        "src/congress_docmeta/atomic_validator_v6.py",
        "src/congress_docmeta/grammar_router_ane_v6.py",
        "src/congress_docmeta/parquet_runner_v6.py",
    ):
        proc = subprocess.run(
            ["/usr/bin/python3", "-B", "-I", "-S", str(REPO_ROOT / script_rel)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"{script_rel} failed under -B -I -S:\n{proc.stderr}"

    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(SRC_DIR)!r})\n"
        "import congress_docmeta as dm\n"
        "from congress_docmeta import AtomicOutputValidatorV6, score_atomic_stdlib_v6\n"
        "for banned in ('mlx', 'numpy', 'pyarrow', 'tokenizers', 'llguidance', 'torch'):\n"
        "    assert banned not in sys.modules, f'Unexpected import: {banned}'\n"
    )
    proc_pkg = subprocess.run(["/usr/bin/python3", "-B", "-I", "-S", "-c", code], capture_output=True, text=True)
    assert proc_pkg.returncode == 0, proc_pkg.stderr
    assert DOCMETA_V4_SCHEMA_PATH.is_file()

    forbidden = "".join((".", "gem", "ini"))
    for folder in ("src", "tests"):
        root = REPO_ROOT / folder
        if not root.exists():
            continue
        for fp in root.rglob("*"):
            if fp.is_file() and fp.suffix in (".py", ".mm", ".h", ".md", ".json", ".toml"):
                assert forbidden not in fp.read_text(encoding="utf-8"), f"Scratch path leaked in {fp}"


def test_v0_stdlib_atomic_unit_and_val48_auroc() -> None:
    """Verify zero-ML `V0_Stdlib_Atomic` catches hallucinations with >=0.825 AUROC and 0 clean false escalations."""
    # 1. Hallucinated committee + non-person persona + TTF header on witness_statement
    bad_doc = {
        "status": "usable",
        "text_quality": "native",
        "congress": 118,
        "committees": ["Committee on Oversight and Accountability"],
        "primary_kind": "witness_statement",
        "personas": [
            {"name": "Rayburn House Office Building", "role": "witness", "entity_type": "organization"},
            {"name": "Dr. Elena Vance", "role": "witness", "entity_type": "non_gov_person"},
        ],
        "composed_title": "Testimony of Elena Vance",
        "gist": "Prepared testimony on grid modernization.",
        "topics": ["grid modernization"],
    }
    bad_row = {
        "filename": "HHRG-118-SY00-TTF-VanceE-20240522.pdf",
        "text": (
            "Witness Disclosure Requirement - Truth in Testimony\n"
            "Committee on Science, Space, and Technology\n"
            "Witness Name: Dr. Elena Vance, Senior Fellow, Clean Grid Institute. " * 4
        ),
    }
    v0_bad = score_atomic_stdlib_v6(bad_doc, bad_row)
    assert v0_bad["ungrounded_committees"] == ["Committee on Oversight and Accountability"]
    assert "ttf_disclosure_header_on_witness_statement" in v0_bad["kind_conflicts"]
    assert v0_bad["persona_defect_scores"][0] >= 0.85
    assert v0_bad["persona_defect_scores"][1] == 0.0

    anom_bad = score_docmeta_anomalies_v6(bad_doc, bad_row)
    assert anom_bad["escalate_to_teacher"] is True
    assert "ungrounded_committee_hallucination" in anom_bad["anomaly_codes"]
    assert "kind_structural_contradiction" in anom_bad["anomaly_codes"]
    assert "invalid_or_misroled_persona" in anom_bad["anomaly_codes"]

    # 2. False non-usable rejection on >1,200 chars of substantive text
    substantive_txt = (
        "Statement of Dr. Alan Rivera before the Senate Committee on Energy and Natural Resources "
        "examining transmission permitting, transformer supply chains, and regional reliability standards. "
    ) * 12
    false_nu_rep = score_docmeta_anomalies_v6(
        {"status": "stub_or_blank", "text_quality": "empty"},
        {"filename": "rivera_statement.pdf", "text": substantive_txt},
    )
    assert false_nu_rep["escalate_to_teacher"] is True
    assert "false_non_usable_on_substantive_text" in false_nu_rep["anomaly_codes"]

    # 3. Phase 1A full-schema zero-ML gates: ungrounded ISO dates (`YYYY-01-01`), missing `committee_vote`
    #    `action_summary`, `correspondence_flow` genre contradictions, and multi-actor omission heuristics
    vote_text = (
        "SUBCOMMITTEE VOTES\nRoll Call 1 Date: July 14, 2025\n"
        "Motion by: Mr. Cloud\nDescription of Motion: Motion to report the bill to the full Committee.\n"
        "Results: Adopted 10 yeas to 5 nays\n"
    )
    vote_missing_summary = {
        "status": "usable",
        "text_quality": "native",
        "congress": 119,
        "committees": ["Committee on Appropriations"],
        "doc_date": "2025-01-01",
        "primary_kind": "committee_vote",
        "personas": [{"name": "Michael Cloud", "role": "amendment_offeror", "entity_type": "member"}],
        "correspondence_flow": "witness_to_committee",
        "composed_title": "Roll Call 1 on FY2026 Energy and Water Bill",
        "gist": "House Appropriations subcommittee votes on reporting FY2026 bill.",
        "topics": ["appropriations"],
    }
    v0_vote = score_atomic_stdlib_v6(
        vote_missing_summary,
        {"filename": "CRPT-119-AP10-Vote001-20250714.pdf", "text": vote_text},
    )
    assert "doc_date=2025-01-01" in v0_vote["ungrounded_dates"]
    assert "missing_action_summary_on_committee_vote" in v0_vote["action_summary_flags"]
    assert "spurious_correspondence_flow:witness_to_committee:on:committee_vote" in v0_vote["correspondence_flow_flags"]

    # Also verify `jan1_default` when month/year ('January 2025') appear without day '1'
    v0_jan1 = score_atomic_stdlib_v6(
        dict(vote_missing_summary, action_summary="Adopted 10 yeas to 5 nays", correspondence_flow=None),
        {"filename": "report_jan2025.pdf", "text": "Committee staff briefing dated January 2025: Adopted 10 yeas to 5 nays."},
    )
    assert "doc_date=2025-01-01:jan1_default" in v0_jan1["ungrounded_dates"]
    anom_vote = score_docmeta_anomalies_v6(
        vote_missing_summary,
        {"filename": "CRPT-119-AP10-Vote001-20250714.pdf", "text": vote_text},
    )
    assert anom_vote["escalate_to_teacher"] is True
    assert "missing_or_ungrounded_vote_summary" in anom_vote["anomaly_codes"]
    assert "ungrounded_iso_date" in anom_vote["anomaly_codes"]
    assert "correspondence_flow_kind_conflict" in anom_vote["anomaly_codes"]

    # Email chain with multiple From:/To: headers but only 1 extracted persona -> `suspected_persona_omission`
    email_chain_txt = (
        "From: Sarah Miller <smiller@agency.gov>\nTo: David Park <dpark@committee.gov>\n"
        "Subject: Follow-up on Inspector General Audit\n"
        "-----Original Message-----\n"
        "From: David Park <dpark@committee.gov>\nTo: Sarah Miller <smiller@agency.gov>\n"
        "Please provide the quarterly grant reconciliation tables."
    )
    anom_email = score_docmeta_anomalies_v6(
        {
            "status": "usable",
            "text_quality": "native",
            "congress": 118,
            "primary_kind": "investigative_exhibit",
            "personas": [{"name": "Sarah Miller", "role": "sender", "entity_type": "executive_official"}],
            "correspondence_flow": "internal_exhibit_chain",
            "composed_title": "Email Chain Between Sarah Miller and Committee Staff",
            "gist": "Email exchange regarding Inspector General audit tables.",
            "topics": ["audit"],
        },
        {"filename": "Exhibit_04_Email.pdf", "text": email_chain_txt},
    )
    assert "suspected_persona_omission" in anom_email["anomaly_codes"]
    assert anom_email["escalate_to_teacher"] is False  # lint flag without false teacher escalation

    # Genre-conditional `q4` builder covers `action_summary`, `disclosure`, and `correspondence_flow`
    q4_vote = build_genre_conditional_question_v6(vote_missing_summary)
    assert q4_vote is not None and q4_vote["field"] == "action_summary"
    q4_ttf = build_genre_conditional_question_v6(
        {"primary_kind": "truth_in_testimony_disclosure", "disclosure": {"gov_witness": False, "has_federal_grants": True}}
    )
    assert q4_ttf is not None and q4_ttf["field"] == "disclosure"
    q4_letter = build_genre_conditional_question_v6(
        {"primary_kind": "oversight_letter", "correspondence_flow": "committee_to_agency"}
    )
    assert q4_letter is not None and q4_letter["field"] == "correspondence_flow"

    # 4. Held-out `val_48` AUROC >= 0.825 with 0 clean false escalations
    clean_objs, chunk_rows, y_doc_def, _ = _load_val48_records()
    anom_scores: list[float] = []
    clean_fp = 0
    for i in range(len(clean_objs)):
        rep = score_docmeta_anomalies_v6(clean_objs[i], chunk_rows[i])
        anom_scores.append(float(rep["anomaly_score"]))
        if y_doc_def[i] == 0 and rep["escalate_to_teacher"]:
            clean_fp += 1
    auroc_v0 = _auroc(y_doc_def, anom_scores)
    assert auroc_v0 >= 0.825, f"Expected V0_Stdlib_Atomic AUROC >= 0.825 on val_48, got {auroc_v0:.4f}"
    assert clean_fp == 0, f"Expected 0 clean false escalations on val_48, got {clean_fp}"

    # 5. Held-out `docs_8` clean gold (0 false escalations) vs full-schema corruptions
    d8_objs, d8_rows, d8_y = _load_docs8_pairs()
    d8_clean_esc = sum(
        1 for idx in range(len(d8_objs)) if d8_y[idx] == 0 and score_docmeta_anomalies_v6(d8_objs[idx], d8_rows[idx])["escalate_to_teacher"]
    )
    d8_corrupt_flagged = sum(
        1 for idx in range(len(d8_objs)) if d8_y[idx] == 1 and score_docmeta_anomalies_v6(d8_objs[idx], d8_rows[idx])["has_anomaly"]
    )
    assert d8_clean_esc == 0, f"Expected 0 clean false escalations on docs_8 gold, got {d8_clean_esc}"
    assert d8_corrupt_flagged >= 6, f"Expected >=6/8 corrupted docs_8 flagged by V0_Stdlib_Atomic, got {d8_corrupt_flagged}"




def test_pass2_closed_loop_schema_exclusion_critique_and_reverification() -> None:
    """Verify Phase 1B Pass-2 excluded-kind schema, critique prompt injection, and closed-loop re-verification."""
    excl = build_excluded_kind_schema_v6("witness_statement")
    assert "witness_statement" not in excl["properties"]["primary_kind"]["enum"]
    assert "truth_in_testimony_disclosure" in excl["properties"]["primary_kind"]["enum"]
    # Keep `$defs.doc_kind.enum` intact for secondary_kinds
    assert "witness_statement" in excl["$defs"]["doc_kind"]["enum"]

    seen_prompts: list[str] = []
    seen_grammars: list[Any] = []

    class _Item:
        def __init__(self, obj: dict[str, Any]) -> None:
            self.parsed = obj
            self.text = json.dumps(obj)

    class _Batch:
        def __init__(self, items: list[_Item]) -> None:
            self.items = items

    class _MockTeacher:
        def generate_batch(self, prompts: list[str], *, per_doc_grammars: Any = None, **_kw: Any) -> _Batch:
            seen_prompts.extend(prompts)
            seen_grammars.extend(per_doc_grammars or [])
            # Row 0: Teacher genuinely repairs kind + committee -> should be ACCEPTED!
            good_fix = {
                "status": "usable",
                "text_quality": "native",
                "chamber": "house",
                "congress": 118,
                "committees": ["Committee on Science, Space, and Technology"],
                "primary_kind": "truth_in_testimony_disclosure",
                "personas": [{"name": "Elena Vance", "role": "witness", "entity_type": "non_gov_person"}],
                "disclosure": {"capacity": "organization", "gov_witness": False, "has_federal_grants": False},
                "composed_title": "Truth in Testimony Disclosure of Elena Vance",
                "gist": "Elena Vance submits Truth in Testimony disclosure to House Science Committee.",
                "topics": ["grid modernization"],
            }
            # Row 1: Teacher fixes stdlib anomaly (`anomaly_score=0`) BUT hallucinates unfaithful gist -> REJECTED!
            bad_halluc = {
                "status": "usable",
                "text_quality": "native",
                "chamber": "house",
                "congress": 118,
                "committees": ["Committee on Science, Space, and Technology"],
                "primary_kind": "witness_statement",
                "personas": [{"name": "Jane Doe", "role": "witness", "entity_type": "non_gov_person"}],
                "composed_title": "HALLUCINATED TEACHER SUMMARY",
                "gist": "HALLUCINATED TEACHER SUMMARY",
                "topics": ["electric grid"],
            }
            return _Batch([_Item(good_fix), _Item(bad_halluc)])

    rows = [
        {
            "filename": "HHRG-118-SY00-TTF-VanceE-20240522.pdf",
            "p12_clean_text": (
                "Witness Disclosure Requirement - Truth in Testimony\n"
                "Committee on Science, Space, and Technology\nWitness Name: Elena Vance."
            ),
        },
        {
            "filename": "HHRG-118-SY00-Wstate-DoeJ-20240522.pdf",
            "p12_clean_text": "Statement of Jane Doe before the Committee on Science, Space, and Technology on electric grid reliability.",
        },
    ]
    pmetas = [{"tier1_target_kind": None}, {"tier1_target_kind": "witness_statement"}]
    cur_objs = [
        {
            "status": "usable",
            "text_quality": "native",
            "congress": 118,
            "committees": ["Committee on Oversight and Accountability"],
            "primary_kind": "witness_statement",
            "personas": [{"name": "Elena Vance", "role": "witness", "entity_type": "non_gov_person"}],
            "composed_title": "Testimony of Elena Vance",
            "gist": "Elena Vance testifies.",
            "topics": ["grid"],
        },
        {
            "status": "usable",
            "text_quality": "native",
            "congress": 118,
            "committees": ["Committee on Science, Space, and Technology"],
            "primary_kind": "witness_statement",
            "personas": [{"name": "Jane Doe", "role": "witness", "entity_type": "non_gov_person"}],
            "composed_title": "Testimony of Jane Doe on Electric Grid Reliability",
            "gist": "Jane Doe testifies on electric grid reliability.",
            "topics": ["electric grid"],
        },
    ]
    cur_texts = [json.dumps(x) for x in cur_objs]
    cur_anoms = [
        {
            "has_anomaly": True,
            "escalate_to_teacher": True,
            "anomaly_score": 2.0,
            "anomaly_codes": ["atomic_kind_suspect", "ungrounded_committee_hallucination"],
        },
        {
            "has_anomaly": True,
            "escalate_to_teacher": True,
            "anomaly_score": 1.0,
            "anomaly_codes": ["ungrounded_usc_citation"],
        },
    ]
    cur_verdicts: list[dict[str, Any] | None] = [
        {
            "score": 0.18,
            "defect_score": 0.82,
            "is_faithful": False,
            "escalate": True,
            "field_probs": {"primary_kind": 0.08, "committees": 0.05, "gist": 0.65},
            "codes": ["atomic_kind_suspect", "atomic_committee_suspect"],
        },
        {
            "score": 0.88,
            "defect_score": 0.12,
            "is_faithful": True,
            "escalate": False,
            "field_probs": {"primary_kind": 0.98, "committees": 0.95, "gist": 0.90},
            "codes": [],
        },
    ]
    cur_verdicts_json: list[str | None] = [json.dumps(v) for v in cur_verdicts]

    def _closed_loop_verifier(cands: Any, _rows: Any) -> list[dict[str, Any]]:
        out = []
        for c in cands:
            bad = "HALLUCINATED" in str(c.get("gist") or "")
            out.append(
                {
                    "score": 0.10 if bad else 0.94,
                    "defect_score": 0.90 if bad else 0.06,
                    "is_faithful": not bad,
                    "escalate": bad,
                    "codes": ["atomic_gist_suspect"] if bad else [],
                }
            )
        return out

    esc_n, acc_n, backups = escalate_anomalies_gpt_oss(
        _MockTeacher(),
        flagged_indices=[0, 1],
        prompts_user_content=["PROMPT_0", "PROMPT_1"],
        rows=rows,
        pmetas=pmetas,
        current_objs=cur_objs,
        current_texts=cur_texts,
        current_anomalies=cur_anoms,
        external_verifier=_closed_loop_verifier,
        current_verdicts=cur_verdicts,
        current_verdicts_json=cur_verdicts_json,
    )
    assert esc_n == 2
    assert acc_n == 1  # Row 0 accepted; Row 1 rejected because teacher introduced a semantic hallucination!
    assert 0 in backups and 1 not in backups
    assert cur_objs[0]["primary_kind"] == "truth_in_testimony_disclosure"
    assert cur_objs[1]["gist"] == "Jane Doe testifies on electric grid reliability."
    assert "[Pass-1 Verifier Critique:" in seen_prompts[0]
    assert isinstance(seen_grammars[0], dict)
    assert "witness_statement" not in seen_grammars[0]["properties"]["primary_kind"]["enum"]
