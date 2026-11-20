"""Held-out sets and scoring helpers shared by the DocMeta validator tests (pure and model lanes)."""

from __future__ import annotations

import collections
from contextlib import contextmanager
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Iterator

import pytest

from congress_docmeta import score_docmeta_anomalies_v6, surname_token_v6
from congress_docmeta.pythonic_v5 import infer_is_html_v5, strip_html_cms_nav_v5
from congress_docmeta.relational_rules_v6 import resolve_docmeta_v6_data_dir

VAL48_ARCHIVE_DIR = resolve_docmeta_v6_data_dir(os.environ.get("DOCMETA_V6_ARCHIVE_DIR"))
HW_LOCK_PATH = Path("/tmp/m4_gpu_validation.lock")


@contextmanager
def _hw_lock(label: str) -> Iterator[None]:
    HW_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(HW_LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o666)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()} {label} {time.time():.3f}\n".encode("utf-8"))
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _auroc(y_true: list[int], scores: list[float]) -> float:
    pos = [scores[i] for i in range(len(y_true)) if y_true[i] == 1]
    neg = [scores[i] for i in range(len(y_true)) if y_true[i] == 0]
    assert pos and neg
    wins = sum(1.0 if p > n else (0.5 if p == n else 0.0) for p in pos for n in neg)
    return wins / float(len(pos) * len(neg))


def _norm_comm_core(c: str) -> str:
    s = re.sub(r"\b(house|senate|united states|u\.s\.|committee on|the|select|permanent)\b", " ", c.lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _load_val48_records() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[int], list[int]]:
    gold_path = VAL48_ARCHIVE_DIR / "lookups_and_gold" / "eval_val48_v4_gold.json"
    eval_path = VAL48_ARCHIVE_DIR / "reports_and_receipts" / "deterministic_v6_eval.json"
    if not (gold_path.is_file() and eval_path.is_file()):
        pytest.skip(f"Held-out val_48 archive not present at {VAL48_ARCHIVE_DIR}")

    val48_raw = json.loads(gold_path.read_text(encoding="utf-8"))
    eval_v6 = json.loads(eval_path.read_text(encoding="utf-8"))
    v6_preds = eval_v6["step2_blind_4way_e2e"]["val_48"]["details"]["v6_full"]

    gist_halluc_set = {2, 19, 20, 38}
    clean_objs: list[dict[str, Any]] = []
    chunk_rows: list[dict[str, Any]] = []
    y_doc_defect: list[int] = []
    y_pers_defect: list[int] = []

    for i, r in enumerate(val48_raw):
        gold = r["gold"]
        pred = v6_preds[i]["pred"]
        fn = r.get("filename", "")
        txt = r["text"] or ""
        if infer_is_html_v5(fn, txt):
            stripped, _ = strip_html_cms_nav_v5(txt)
            if stripped:
                txt = stripped
        txt = re.sub(r"[ \t]+", " ", txt)
        txt = re.sub(r"\n{3,}", "\n\n", txt).strip()

        clean_objs.append(pred)
        chunk_rows.append(
            {
                "filename": fn,
                "known": r.get("known", "<NONE>"),
                "p12_clean_text": txt,
            }
        )

        kind_wrong = pred.get("primary_kind") != gold.get("primary_kind")
        gc_cores = {_norm_comm_core(c) for c in (gold.get("committees") or []) if _norm_comm_core(c)}
        pc_cores = {_norm_comm_core(c) for c in (pred.get("committees") or []) if _norm_comm_core(c)}
        comm_wrong = gc_cores != pc_cores
        gist_wrong = i in gist_halluc_set
        y_doc_defect.append(int(kind_wrong or comm_wrong or gist_wrong))

        gold_nr = collections.Counter(
            (surname_token_v6(x["name"]), x["role"]) for x in gold.get("personas", []) if x.get("name")
        )
        rem = dict(gold_nr)
        for px in pred.get("personas", []):
            nm = px.get("name", "")
            rl = px.get("role", "witness")
            key = (surname_token_v6(nm), rl) if nm else ("", rl)
            if rem.get(key, 0) > 0:
                rem[key] -= 1
                y_pers_defect.append(0)
            else:
                y_pers_defect.append(1)

    return clean_objs, chunk_rows, y_doc_defect, y_pers_defect


def _load_docs8_pairs() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[int]]:
    """Load all 8 `eval_docs8_v4_gold.json` clean gold extractions + 8 full-schema corruptions."""
    docs8_path = VAL48_ARCHIVE_DIR / "lookups_and_gold" / "eval_docs8_v4_gold.json"
    if not docs8_path.is_file():
        pytest.skip(f"Held-out docs_8 archive not present at {VAL48_ARCHIVE_DIR}")
    docs8_raw = json.loads(docs8_path.read_text(encoding="utf-8"))

    objs: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    y_def: list[int] = []

    for idx, r in enumerate(docs8_raw):
        fn = r.get("filename", "")
        txt = r["text"] or ""
        if infer_is_html_v5(fn, txt):
            stripped, _ = strip_html_cms_nav_v5(txt)
            if stripped:
                txt = stripped
        txt = re.sub(r"[ \t]+", " ", txt)
        txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
        row = {
            "filename": fn,
            "known": r.get("known", "<NONE>"),
            "p12_raw_text": r["text"] or "",
            "p12_clean_text": txt,
        }

        # Clean gold extraction (0)
        objs.append(copy.deepcopy(r["gold"]))
        rows.append(row)
        y_def.append(0)

        # Realistic full-schema corruption per genre (1)
        bad = copy.deepcopy(r["gold"])
        if idx == 0:
            # QFR response -> wrong committee + reversed correspondence flow
            bad["committees"] = ["House Committee on Oversight and Accountability"]
            bad["correspondence_flow"] = "committee_to_witness"
        elif idx == 1:
            # Member opening statement -> wrong Jan-1 placeholder date + modality/number flip
            bad["doc_date"] = "2020-01-01"
            bad["gist"] = "Mandates $95 billion under H.R. 9911 and repeals veteran suicide programs."
        elif idx == 2:
            # Truth in Testimony disclosure -> flipped gov_witness + flipped federal grants
            bad["disclosure"] = {
                "capacity": "government",
                "gov_witness": True,
                "has_federal_grants": False,
            }
        elif idx == 3:
            # HTML witness page -> wrong primary_kind + spurious correspondence_flow + CMS sidebar date
            bad["primary_kind"] = "press_release_or_fact_sheet"
            bad["correspondence_flow"] = "witness_to_committee"
            bad["doc_date"] = "2023-01-01"
        elif idx == 4:
            # Committee vote (`Adopted 10 yeas to 5 nays`) -> omitted `action_summary`!
            bad.pop("action_summary", None)
        elif idx == 5:
            # Committee report -> wrong committee + wrong bill number in gist
            bad["committees"] = ["Senate Committee on Finance"]
            bad["gist"] = "Senate Finance Committee reports S. 9999 repealing tax credits."
        elif idx == 6:
            # Published GPO hearing transcript -> non-person building actor + wrong kind
            bad["primary_kind"] = "witness_statement"
            bad["personas"] = [{"name": "Rayburn House Office Building", "role": "witness", "entity_type": "organization"}]
        else:
            # Field hearing witness statement -> wrong witness & topic
            bad["gist"] = "Secretary of State testifies on Arctic maritime treaty ratification."
            bad["committees"] = ["Senate Committee on Foreign Relations"]

        objs.append(bad)
        rows.append(row)
        y_def.append(1)

    return objs, rows, y_def
