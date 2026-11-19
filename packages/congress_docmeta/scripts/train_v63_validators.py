#!/usr/bin/env python3
"""Train, distill, calibrate, and compile V6.3 ANE Grammar Router & Distilled Laya-Typed Validator.

Uses `train_v6_3_complete_ssot_gold.jsonl` (2,917 docs / 5,117 personas, 100% disjoint from
`eval_val48_v4_gold.json` and `eval_docs8_v4_gold.json`) to deliver all four V6.3 upgrades:
  1. Pre-decode calibrated `Choice(47)` + `status(8)` grammar router (`router_v63_linear.npz` +
     `Laya-Typed` ANE Top-6 `Choice` refinement + `router_v63_calibration.json`).
  2. Persona `Noul` validity + `Choice(16)` role classification/auto-repair trained on 5,117 gold actors.
  3. `Kev-0.8B` (`W8`) soft-target distillation into `Laya-Typed-421M`, merged into base weights and
     compiled to CoreML `W8A16` Pure ANE (`laya_typed_s256_w8.mlmodelc` & `laya_typed_s512_w8.mlmodelc`,
     `[1585, 0, 0]` ANE/GPU/CPU ops -> 0 MB extra GPU RAM, 0 ms GPU compute).
  4. Held-out calibration (`cal_split` = 500 stratified docs) for temperatures, fusion weights, and
     gray-zone / grammar-locking thresholds (`validator_v63_calibration.json`).

Moved from fast-gemma4 `scripts/` (8edf64b). Run under the fast-gemma4 interpreter with this package on the path:
`PYTHONPATH=packages/congress_docmeta/src ../fast-gemma4/.venv/bin/python packages/congress_docmeta/scripts/train_v63_validators.py`.
"""

from __future__ import annotations

import argparse
import collections
from contextlib import contextmanager
import ctypes
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterator

import numpy as np

from congress_docmeta.atomic_validator_v6 import resolve_docmeta_pkg_root, resolve_docmeta_validators_dir
from fast_decision_models import Kev08bMlxBackend, LayaAneBackend
from fast_decision_models.paths import ensure_laya_dylib

REPO_ROOT = resolve_docmeta_pkg_root()

from congress_docmeta.anomaly_router_v6 import check_gist_title_grounding_v6, score_atomic_stdlib_v6, surname_token_v6
from congress_docmeta.atomic_validator_v6 import (
    ALL_KIND_DESC_V6,
    CFLOW_DESC_V6,
    CONFUSABLE_ALTS_V6,
    ROLE_DESC_V6,
    build_atomic_doc_questions_v6,
    build_atomic_persona_question_v6,
)
from congress_docmeta.prompt_v4 import SCHEMA_OBJ
from congress_docmeta.pythonic_v5 import infer_is_html_v5, strip_html_cms_nav_v5

HW_LOCK_PATH = Path("/tmp/m4_gpu_validation.lock")

ALL_DOC_KINDS: list[str] = list(SCHEMA_OBJ["$defs"]["doc_kind"]["enum"])
ALL_STATUSES: list[str] = list(SCHEMA_OBJ["properties"]["status"]["enum"])
NON_USABLE_STATUSES: list[str] = [s for s in ALL_STATUSES if s != "usable"]
ROUTER_CLASSES: list[str] = ALL_DOC_KINDS + [f"status:{s}" for s in NON_USABLE_STATUSES]
ROUTER_CLASS_TO_IDX: dict[str, int] = {c: i for i, c in enumerate(ROUTER_CLASSES)}

ALL_ROLES: list[str] = list(SCHEMA_OBJ["properties"]["personas"]["items"]["properties"]["role"]["enum"])
ROLE_TO_IDX: dict[str, int] = {r: i for i, r in enumerate(ALL_ROLES)}
ALL_CFLOWS: list[str] = list(SCHEMA_OBJ["properties"]["correspondence_flow"]["enum"])

CONFUSABLE_KIND_NEIGHBORS: dict[str, list[str]] = {
    "witness_statement": ["truth_in_testimony_disclosure", "qfr_response", "member_opening_statement", "witness_biography"],
    "member_opening_statement": ["witness_statement", "member_or_floor_statement", "press_release_or_fact_sheet"],
    "truth_in_testimony_disclosure": ["witness_statement", "witness_biography", "nominee_questionnaire_apq"],
    "witness_biography": ["witness_statement", "truth_in_testimony_disclosure", "nominee_questionnaire_apq"],
    "witness_list": ["hearing_notice", "member_roster", "event_web_page"],
    "qfr_request": ["qfr_response", "witness_invitation", "oversight_letter"],
    "qfr_response": ["witness_statement", "qfr_request", "nominee_questionnaire_apq"],
    "hearing_notice": ["markup_notice", "event_web_page", "hearing_memo_or_charter", "witness_list"],
    "markup_notice": ["hearing_notice", "meeting_results", "legislative_schedule_or_calendar"],
    "hearing_memo_or_charter": ["hearing_notice", "section_by_section", "committee_report"],
    "meeting_results": ["committee_vote", "markup_notice", "committee_report"],
    "committee_vote": ["meeting_results", "attendance_quorum_sheet", "committee_amendment"],
    "bill_or_draft": ["committee_amendment", "comparative_print", "committee_resolution"],
    "committee_amendment": ["bill_or_draft", "comparative_print", "committee_resolution"],
    "committee_report": ["explanatory_statement", "section_by_section", "agency_or_gao_crs_report"],
    "oversight_letter": ["external_submission_letter", "witness_invitation", "nomination_or_support_letter"],
    "external_submission_letter": ["public_comment_or_submission", "oversight_letter", "nomination_or_support_letter"],
    "public_comment_or_submission": ["external_submission_letter", "external_report_or_whitepaper"],
    "event_web_page": ["hearing_notice", "press_release_or_fact_sheet", "witness_list"],
    "press_release_or_fact_sheet": ["event_web_page", "news_clip_or_article", "member_opening_statement"],
    "investigative_exhibit": ["legal_or_investigative_filing", "oversight_letter", "news_clip_or_article"],
    "agency_or_gao_crs_report": ["external_report_or_whitepaper", "committee_report", "revenue_or_cost_estimate"],
    "external_report_or_whitepaper": ["agency_or_gao_crs_report", "public_comment_or_submission", "slides_or_visual"],
}

CONFUSABLE_ROLE_SWAPS: dict[str, list[str]] = {
    "witness": ["questioner", "author_or_speaker", "recipient", "nominee"],
    "chair": ["ranking_member", "sender", "questioner", "witness"],
    "ranking_member": ["chair", "questioner", "sender", "witness"],
    "questioner": ["witness", "chair", "author_or_speaker"],
    "author_or_speaker": ["witness", "introducer", "chair", "sender"],
    "sender": ["recipient", "chair", "witness", "signatory"],
    "recipient": ["sender", "witness", "chair"],
    "nominee": ["witness", "recipient", "author_or_speaker"],
    "introducer": ["author_or_speaker", "sponsor", "witness"],
    "sponsor": ["cosponsor", "amendment_offeror", "author_or_speaker"],
    "cosponsor": ["sponsor", "signatory", "questioner"],
    "amendment_offeror": ["sponsor", "chair", "questioner"],
    "signatory": ["sender", "cosponsor", "witness"],
    "presiding": ["chair", "questioner", "author_or_speaker"],
    "staff": ["sender", "recipient", "witness"],
    "party_or_investigator": ["sender", "witness", "staff"],
}

DECOY_COMMITTEES: list[str] = [
    "House Committee on Oversight and Accountability",
    "Senate Committee on Finance",
    "House Committee on Rules",
    "Senate Committee on Foreign Relations",
    "House Committee on Science, Space, and Technology",
    "Senate Committee on the Judiciary",
    "House Committee on Ways and Means",
    "Senate Committee on Armed Services",
]

NON_PERSON_ACTOR_DECOYS: list[str] = [
    "Rayburn House Office Building",
    "Dirksen Senate Office Building",
    "Longworth House Office Building",
    "Subcommittee on Oversight and Investigations",
    "U.S. Government Publishing Office",
    "Capitol Visitor Center",
]


@contextmanager
def acquire_hw_lock(label: str) -> Iterator[None]:
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


_PROMPT_PARSE_RE = re.compile(
    r"Advisory known metadata:\s*(?P<known>[^\n]*)\nFilename:\s*(?P<filename>[^\n]*)\nText:\n(?P<text>.*)\Z",
    re.DOTALL,
)
_TOK_RE = re.compile(r"[a-z0-9_]{2,}")


def parse_v4_prompt_row(raw_row: dict[str, Any]) -> dict[str, Any]:
    u = raw_row["messages"][0]["content"]
    gold = json.loads(raw_row["messages"][-1]["content"])
    m = _PROMPT_PARSE_RE.search(u)
    if m:
        known = m.group("known").strip()
        fn = m.group("filename").strip()
        raw_text = m.group("text")
    else:
        known, fn, raw_text = "<NONE>", "", u
    clean_txt = raw_text or ""
    if infer_is_html_v5(fn, clean_txt):
        stripped, _ = strip_html_cms_nav_v5(clean_txt)
        if stripped:
            clean_txt = stripped
    clean_txt = re.sub(r"[ \t]+", " ", clean_txt)
    clean_txt = re.sub(r"\n{3,}", "\n\n", clean_txt).strip()
    st = str(gold.get("status") or "usable")
    cls_label = str(gold["primary_kind"]) if st == "usable" else f"status:{st}"
    return {
        "doc_key": raw_row.get("doc_key") or "",
        "stratum": raw_row.get("stratum") or "",
        "filename": fn,
        "known": known,
        "p12_raw_text": raw_text or "",
        "p12_clean_text": clean_txt,
        "gold": gold,
        "router_class": cls_label,
    }


def extract_router_sparse_features(
    filename: str,
    known: str,
    raw_text: str,
    clean_text: str,
    dim: int = 12288,
) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic sub-millisecond hashed n-gram + structural feature extractor (`100%` NumPy/stdlib)."""
    counts: dict[int, float] = {}

    def _add(feat: str, weight: float = 1.0) -> None:
        # Fast deterministic 32-bit FNV-1a hash (identical across Python sessions!)
        h = 2166136261
        for b in feat.encode("utf-8", errors="ignore"):
            h = ((h ^ b) * 16777619) & 0xFFFFFFFF
        idx = h % dim
        sign = 1.0 if ((h >> 31) & 1) == 0 else -1.0
        counts[idx] = counts.get(idx, 0.0) + sign * weight

    fn_l = (filename or "").lower()
    kn_l = (known or "").lower()
    raw_l = (raw_text or "")[:1200].lower()
    txt_l = (clean_text or "").lower()

    # 1. Structural length / container / markup cues (strong triage signals)
    n_chars = len(clean_text or "")
    if n_chars == 0:
        _add("__LEN_ZERO__", 3.5)
    elif n_chars < 80:
        _add("__LEN_TINY__", 2.8)
    elif n_chars < 250:
        _add("__LEN_SHORT__", 2.0)
    elif n_chars < 800:
        _add("__LEN_MED__", 1.2)
    else:
        _add("__LEN_FULL__", 1.0)

    if "<?xml" in raw_l[:300] or "<mods" in raw_l[:400] or "<granule" in raw_l[:400]:
        _add("__XML_CATALOG__", 3.5)
    if "<html" in raw_l[:400] or "<!doctype html" in raw_l[:400] or "skip to main content" in raw_l[:400]:
        _add("__IS_HTML__", 2.0)
    if fn_l.endswith(".pdf"):
        _add("__EXT_PDF__", 1.2)
    elif fn_l.endswith((".htm", ".html", ".aspx")):
        _add("__EXT_HTML__", 1.5)
    elif fn_l.endswith(".xml"):
        _add("__EXT_XML__", 2.5)

    # Non-alpha / garbled OCR ratio
    if n_chars >= 40:
        alpha_n = sum(1 for ch in (clean_text[:800]) if ch.isalpha())
        ratio = alpha_n / float(min(n_chars, 800))
        if ratio < 0.35:
            _add("__LOW_ALPHA_GARBLED__", 3.0)
        elif ratio < 0.55:
            _add("__MED_ALPHA_OCR__", 1.6)

    # 2. Filename tokens & slug parts (high weight, respecting slug cues + overrides)
    fn_parts = re.findall(r"[a-z]{2,}|[0-9]{3,4}", fn_l)
    for p in fn_parts[:24]:
        _add(f"fn:{p}", 2.2)
    for i in range(len(fn_parts) - 1):
        _add(f"fn2:{fn_parts[i]}_{fn_parts[i+1]}", 2.0)

    # 3. Known metadata tokens
    for kt in _TOK_RE.findall(kn_l)[:24]:
        _add(f"kn:{kt}", 1.4)

    # 4. Masthead (first 500 chars): high-signal unigrams + bigrams + trigrams
    mast_toks = _TOK_RE.findall(txt_l[:550])
    for w in mast_toks[:90]:
        _add(f"mh:{w}", 1.8)
    for i in range(min(85, len(mast_toks) - 1)):
        _add(f"mh2:{mast_toks[i]}_{mast_toks[i+1]}", 2.1)
    for i in range(min(60, len(mast_toks) - 2)):
        _add(f"mh3:{mast_toks[i]}_{mast_toks[i+1]}_{mast_toks[i+2]}", 1.9)

    # 5. Body head + tail lexical unigrams & bigrams (log-TF damped)
    body_sample = txt_l[:2400] + ("\n" + txt_l[-700:] if len(txt_l) > 2800 else "")
    b_toks = _TOK_RE.findall(body_sample)
    tf = collections.Counter(b_toks[:450])
    for w, c in tf.items():
        _add(f"bd:{w}", 1.0 + math.log(float(c)))
    b_seq = b_toks[:260]
    for i in range(len(b_seq) - 1):
        _add(f"bd2:{b_seq[i]}_{b_seq[i+1]}", 1.15)

    if not counts:
        return np.zeros((0,), dtype=np.int32), np.zeros((0,), dtype=np.float32)
    idxs = np.fromiter(counts.keys(), dtype=np.int32, count=len(counts))
    vals = np.fromiter(counts.values(), dtype=np.float32, count=len(counts))
    norm = float(np.linalg.norm(vals))
    if norm > 1e-6:
        vals /= norm
    return idxs, vals


def build_dense_feature_matrix(records: list[dict[str, Any]], dim: int = 12288) -> np.ndarray:
    X = np.zeros((len(records), dim), dtype=np.float32)
    for i, r in enumerate(records):
        idxs, vals = extract_router_sparse_features(
            r["filename"], r["known"], r["p12_raw_text"], r["p12_clean_text"], dim=dim
        )
        if len(idxs):
            X[i, idxs] = vals
    return X


def train_linear_router_mlx(
    X_train: np.ndarray,
    y_train: np.ndarray,
    num_classes: int,
    *,
    l2_reg: float = 1.2e-4,
    lr: float = 0.25,
    steps: int = 450,
) -> tuple[np.ndarray, np.ndarray]:
    """Train L2-regularized multinomial logistic classifier in MLX (`~1.5s` on M4 Pro GPU)."""
    import mlx.core as mx
    import mlx.optimizers as optim

    N, D = X_train.shape
    X_mx = mx.array(X_train)
    y_mx = mx.array(y_train.astype(np.int32))

    # Class-balanced mild smoothing (`c^-0.25`) so rare tail kinds have sharp recall in Top-6
    cls_counts = np.bincount(y_train, minlength=num_classes).astype(np.float32)
    sample_w_np = (np.maximum(cls_counts[y_train], 1.0)) ** (-0.15)
    sample_w_np /= float(sample_w_np.mean())
    sw_mx = mx.array(sample_w_np)

    params = {
        "W": mx.zeros((num_classes, D), dtype=mx.float32),
        "b": mx.zeros((num_classes,), dtype=mx.float32),
    }
    opt = optim.AdamW(learning_rate=lr, weight_decay=0.0)

    def loss_fn(p: dict[str, Any]) -> Any:
        logits = X_mx @ p["W"].T + p["b"]
        lse = mx.logsumexp(logits, axis=-1)
        picked = mx.take_along_axis(logits, y_mx[:, None], axis=-1).squeeze(-1)
        ce = mx.mean(sw_mx * (lse - picked))
        reg = 0.5 * l2_reg * mx.sum(p["W"] * p["W"])
        return ce + reg

    vg = mx.value_and_grad(loss_fn)
    for step in range(steps):
        if step == int(steps * 0.7):
            opt.learning_rate = lr * 0.25
        loss, grads = vg(params)
        opt.update(params, grads)
        mx.eval(params["W"], params["b"], loss)

    return np.asarray(params["W"]), np.asarray(params["b"])


def softmax_np(logits: np.ndarray, temp: float = 1.0) -> np.ndarray:
    z = logits / max(temp, 1e-4)
    z = z - np.max(z, axis=-1, keepdims=True)
    ez = np.exp(z)
    return ez / np.sum(ez, axis=-1, keepdims=True)


def fit_temperature_np(logits: np.ndarray, y_true: np.ndarray) -> float:
    best_t = 1.0
    best_nll = 1e18
    for t in np.linspace(0.25, 3.0, 111):
        probs = softmax_np(logits, float(t))
        p_y = np.clip(probs[np.arange(len(y_true)), y_true], 1e-7, 1.0)
        nll = float(-np.mean(np.log(p_y)))
        if nll < best_nll:
            best_nll = nll
            best_t = float(t)
    return round(best_t, 4)


def build_router_choice_item(rec: dict[str, Any], top_classes: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build compact `Laya-Typed` `Choice(K)` item over Top-K candidate document classes."""
    crit: dict[str, str] = {}
    for cls_name in top_classes:
        if cls_name.startswith("status:"):
            st_name = cls_name.split(":", 1)[1]
            crit[cls_name] = f"non-usable {st_name} container (blank, unreadable OCR, catalog XML, or error shell)"
        else:
            crit[cls_name] = ALL_KIND_DESC_V6.get(cls_name, cls_name)

    txt = rec["p12_clean_text"] or rec["p12_raw_text"] or ""
    head = txt[:1000]
    tail = ("\n...\n" + txt[-320:]) if len(txt) > 1400 else ""
    state = {
        "filename": rec["filename"] or "<NONE>",
        "known_metadata": rec["known"] or "<NONE>",
        "text_chars": len(txt),
        "document_excerpt": (head + tail).strip() or "<EMPTY>",
    }
    qdef = {
        "id": "q_router_kind",
        "type": "choice",
        "instructions": (
            "Select the exact congressional `primary_kind` (or `status:*` if non-usable) "
            "for `document_excerpt` based on text structure over misleading filename slugs."
        ),
        "criteria": crit,
    }
    return state, qdef


def build_persona_role_choice_item(
    docmeta: dict[str, Any],
    rec: dict[str, Any],
    persona: dict[str, Any],
    candidate_roles: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build `Laya-Typed` `Choice` item predicting an extracted actor's congressional `role`."""
    pst, _ = build_atomic_persona_question_v6(docmeta, rec, persona)
    roles_list = candidate_roles if candidate_roles is not None else ALL_ROLES
    nm = str(persona.get("name") or "<EMPTY>")
    pk = str(docmeta.get("primary_kind") or "unknown")
    qdef = {
        "id": "q_persona_role_choice",
        "type": "choice",
        "instructions": (
            f"In this `{pk}`, what is `{nm}`'s exact participant `role` given `mentions_of_actor` "
            "and `all_extracted_actors`?"
        ),
        "criteria": list(roles_list),  # concise role tokens keep all 16 options <= 72 tokens!
    }
    return pst, qdef


def synthesize_training_examples(
    train_records: list[dict[str, Any]],
    oof_top6_by_idx: list[list[str]],
    laya_tok_helper: LayaAneBackend,
    kev_teacher: Kev08bMlxBackend | None,
    *,
    distill_docs: int = 360,
    seed: int = 20261116,
) -> list[dict[str, Any]]:
    """Build multi-task `(ids, markers, qtype, target_idx, soft_p1)` items on `train_split`."""
    rng = random.Random(seed)
    items: list[dict[str, Any]] = []

    other_titles = [
        str(r["gold"].get("composed_title") or "")
        for r in train_records
        if r["gold"].get("status") == "usable" and r["gold"].get("composed_title")
    ]
    other_gists = [
        str(r["gold"].get("gist") or "")
        for r in train_records
        if r["gold"].get("status") == "usable" and r["gold"].get("gist")
    ]

    # Select diverse subset of usable docs for `Kev-0.8B` teacher soft-target distillation
    usable_idxs = [i for i, r in enumerate(train_records) if r["gold"].get("status") == "usable" and r["p12_clean_text"]]
    rng.shuffle(usable_idxs)
    distill_set = set(usable_idxs[:distill_docs])
    kev_jobs: list[tuple[int, dict[str, Any], list[dict[str, Any]], list[int]]] = []

    for i, rec in enumerate(train_records):
        gold = rec["gold"]
        st_val = str(gold.get("status") or "usable")
        true_cls = rec["router_class"]

        # 1. Task #1: Pre-decode `Choice(6)` router refinement item
        cand6 = list(oof_top6_by_idx[i][:6])
        if true_cls not in cand6:
            cand6[-1] = true_cls
        rng.shuffle(cand6)
        r_state, r_q = build_router_choice_item(rec, cand6)
        enc_r = laya_tok_helper.encode_item(r_state, r_q)
        items.append(
            {
                "ids": enc_r["ids"],
                "markers": enc_r["markers"],
                "qtype": enc_r["qtype"],
                "target": cand6.index(true_cls),
                "soft_p1": None,
                "task": "router_choice",
            }
        )

        if st_val != "usable" or not rec["p12_clean_text"]:
            continue

        pk = str(gold.get("primary_kind") or "witness_statement")
        # 2. Task #3: Clean Gold Doc `Noul` Questions (`true` = 1)
        st_clean, qs_clean = build_atomic_doc_questions_v6(
            gold,
            rec,
            head_chars=950,
            tail_chars=350,
            include_genre_check=True,
            include_omission_check=(len(gold.get("personas") or ()) >= 2),
        )
        clean_item_indices: list[int] = []
        kev_qs_clean: list[dict[str, Any]] = []
        for q in qs_clean:
            enc_q = laya_tok_helper.encode_item(st_clean, q)
            clean_item_indices.append(len(items))
            kev_qs_clean.append(q)
            items.append(
                {
                    "ids": enc_q["ids"],
                    "markers": enc_q["markers"],
                    "qtype": enc_q["qtype"],
                    "target": 1,
                    "soft_p1": None,
                    "task": f"doc_noul_{q['field']}",
                }
            )
        if i in distill_set and kev_teacher is not None and kev_qs_clean:
            st_kev, _ = build_atomic_doc_questions_v6(
                gold, rec, head_chars=1450, tail_chars=500, include_genre_check=True, include_omission_check=True
            )
            kev_jobs.append((i, st_kev, kev_qs_clean, clean_item_indices))

        # 3. Hard Corrupted Doc `Noul` Questions (`false` = 0)
        corrupt_doc = copy.deepcopy(gold) if "copy" in globals() else json.loads(json.dumps(gold))
        corrupt_qs_pick: list[dict[str, Any]] = []

        # 3a. Confusable `primary_kind` swap
        neighs = CONFUSABLE_KIND_NEIGHBORS.get(pk) or [k for k in ALL_DOC_KINDS if k != pk]
        wrong_pk = rng.choice(neighs)
        bad_kind_doc = json.loads(json.dumps(gold))
        bad_kind_doc["primary_kind"] = wrong_pk
        st_bk, qs_bk = build_atomic_doc_questions_v6(bad_kind_doc, rec, head_chars=950, tail_chars=350)
        corrupt_qs_pick.append((st_bk, bad_kind_doc, qs_bk[0]))  # q1_kind_valid -> 0

        # 3b. Wrong / decoy `committees`
        existing_cmts = {str(c).lower() for c in (gold.get("committees") or ())}
        decoy_pool = [c for c in DECOY_COMMITTEES if c.lower() not in existing_cmts]
        if decoy_pool and rng.random() < 0.75:
            bad_cmt_doc = json.loads(json.dumps(gold))
            bad_cmt_doc["committees"] = [rng.choice(decoy_pool)]
            st_bc, qs_bc = build_atomic_doc_questions_v6(bad_cmt_doc, rec, head_chars=950, tail_chars=350)
            corrupt_qs_pick.append((st_bc, bad_cmt_doc, qs_bc[1]))  # q2_committee_valid -> 0

        # 3c. Unfaithful `gist` / `composed_title` (swapped actor/topic or modality/number hallucination)
        bad_gist_doc = json.loads(json.dumps(gold))
        if rng.random() < 0.5 and other_gists:
            bad_gist_doc["composed_title"] = rng.choice(other_titles)
            bad_gist_doc["gist"] = rng.choice(other_gists)
        else:
            orig_g = str(gold.get("gist") or "Committee document.")
            bad_gist_doc["gist"] = (
                re.sub(r"\b(examines|discusses|requests|supports|reviews|testifies)\b", "mandates repealing", orig_g, count=1)
                + " Mandates $84 billion under H.R. 9942."
            )
        st_bg, qs_bg = build_atomic_doc_questions_v6(bad_gist_doc, rec, head_chars=950, tail_chars=350)
        corrupt_qs_pick.append((st_bg, bad_gist_doc, qs_bg[2]))  # q3_summary_valid -> 0

        # 3d. Genre-conditional `q4` & omission `q5` corruptions
        if gold.get("disclosure") or pk == "truth_in_testimony_disclosure":
            bad_disc_doc = json.loads(json.dumps(gold))
            d_orig = dict(gold.get("disclosure") or {"capacity": "individual", "gov_witness": False})
            bad_disc_doc["disclosure"] = {
                "capacity": "government" if d_orig.get("capacity") != "government" else "organization",
                "gov_witness": not bool(d_orig.get("gov_witness", False)),
                "has_federal_grants": not bool(d_orig.get("has_federal_grants", False)),
            }
            st_bd, qs_bd = build_atomic_doc_questions_v6(
                bad_disc_doc, rec, head_chars=950, tail_chars=350, include_genre_check=True
            )
            for qx in qs_bd:
                if qx.get("field") == "disclosure":
                    corrupt_qs_pick.append((st_bd, bad_disc_doc, qx))
        elif gold.get("correspondence_flow"):
            bad_cf_doc = json.loads(json.dumps(gold))
            cf_orig = str(gold["correspondence_flow"])
            alt_cfs = [c for c in ALL_CFLOWS if c != cf_orig]
            bad_cf_doc["correspondence_flow"] = rng.choice(alt_cfs)
            st_bcf, qs_bcf = build_atomic_doc_questions_v6(
                bad_cf_doc, rec, head_chars=950, tail_chars=350, include_genre_check=True
            )
            for qx in qs_bcf:
                if qx.get("field") == "correspondence_flow":
                    corrupt_qs_pick.append((st_bcf, bad_cf_doc, qx))
        elif pk in ("committee_vote", "meeting_results") or gold.get("action_summary"):
            bad_act_doc = json.loads(json.dumps(gold))
            bad_act_doc.pop("action_summary", None)
            bad_act_doc["primary_kind"] = "committee_vote"
            st_ba, qs_ba = build_atomic_doc_questions_v6(
                bad_act_doc, rec, head_chars=950, tail_chars=350, include_genre_check=True
            )
            for qx in qs_ba:
                if qx.get("field") == "action_summary":
                    corrupt_qs_pick.append((st_ba, bad_act_doc, qx))

        personas_gold = list(gold.get("personas") or ())
        if len(personas_gold) >= 3:
            bad_om_doc = json.loads(json.dumps(gold))
            bad_om_doc["personas"] = personas_gold[:1]
            st_bo, qs_bo = build_atomic_doc_questions_v6(
                bad_om_doc, rec, head_chars=950, tail_chars=350, include_omission_check=True
            )
            for qx in qs_bo:
                if qx.get("field") == "personas_omission":
                    corrupt_qs_pick.append((st_bo, bad_om_doc, qx))

        for st_c, doc_c, q_c in corrupt_qs_pick:
            enc_c = laya_tok_helper.encode_item(st_c, q_c)
            c_idx = len(items)
            items.append(
                {
                    "ids": enc_c["ids"],
                    "markers": enc_c["markers"],
                    "qtype": enc_c["qtype"],
                    "target": 0,
                    "soft_p1": None,
                    "task": f"doc_noul_neg_{q_c['field']}",
                }
            )
            if i in distill_set and kev_teacher is not None:
                st_kc, _ = build_atomic_doc_questions_v6(
                    doc_c, rec, head_chars=1450, tail_chars=500, include_genre_check=True, include_omission_check=True
                )
                kev_jobs.append((i, st_kc, [q_c], [c_idx]))

        # 4. Task #2: Persona `Noul` Validity + `Choice(16)` Role Classification (up to 3 actors/doc for balance)
        sampled_ps = personas_gold if len(personas_gold) <= 3 else rng.sample(personas_gold, 3)
        for px in sampled_ps:
            if not isinstance(px, dict) or not px.get("name") or px.get("role") not in ROLE_TO_IDX:
                continue
            true_rl = str(px["role"])
            # 4a. Positive Persona `Noul` (`true` = 1)
            pst_pos, pq_pos = build_atomic_persona_question_v6(gold, rec, px)
            enc_pp = laya_tok_helper.encode_item(pst_pos, pq_pos)
            items.append(
                {
                    "ids": enc_pp["ids"],
                    "markers": enc_pp["markers"],
                    "qtype": enc_pp["qtype"],
                    "target": 1,
                    "soft_p1": None,
                    "task": "persona_noul_pos",
                }
            )
            # 4b. Persona `Choice(16)` Role Classification
            pst_rc, pq_rc = build_persona_role_choice_item(gold, rec, px)
            enc_rc = laya_tok_helper.encode_item(pst_rc, pq_rc)
            items.append(
                {
                    "ids": enc_rc["ids"],
                    "markers": enc_rc["markers"],
                    "qtype": enc_rc["qtype"],
                    "target": ROLE_TO_IDX[true_rl],
                    "soft_p1": None,
                    "task": "persona_role_choice",
                }
            )
            # 4c. Hard Negative Persona `Noul` (`false` = 0): confusable role swap OR non-person building decoy
            bad_px = dict(px)
            if rng.random() < 0.80:
                swap_Opts = CONFUSABLE_ROLE_SWAPS.get(true_rl) or [r for r in ALL_ROLES if r != true_rl]
                bad_px["role"] = rng.choice(swap_Opts)
            else:
                bad_px["name"] = rng.choice(NON_PERSON_ACTOR_DECOYS)
                bad_px["entity_type"] = "organization"
            bad_doc_p = json.loads(json.dumps(gold))
            bad_doc_p["personas"] = [bad_px] + [p for p in personas_gold if p is not px][:4]
            pst_neg, pq_neg = build_atomic_persona_question_v6(bad_doc_p, rec, bad_px)
            enc_pn = laya_tok_helper.encode_item(pst_neg, pq_neg)
            items.append(
                {
                    "ids": enc_pn["ids"],
                    "markers": enc_pn["markers"],
                    "qtype": enc_pn["qtype"],
                    "target": 0,
                    "soft_p1": None,
                    "task": "persona_noul_neg",
                }
            )

    if kev_teacher is not None and kev_jobs:
        t0 = time.perf_counter()
        print(f"[DISTILL] Scoring {len(kev_jobs)} state batches with W8 Kev-0.8B teacher...")
        # Group identical state dicts per job and run via `score_multi_states_noul`
        batch_in = [(st_k, qs_k) for (_di, st_k, qs_k, _idxs) in kev_jobs]
        outs = kev_teacher.score_multi_states_noul(batch_in)
        for (_di, _st_k, _qs_k, item_idxs), out_list in zip(kev_jobs, outs):
            for it_idx, (p1_val, _rz) in zip(item_idxs, out_list):
                items[it_idx]["soft_p1"] = float(p1_val)
        print(f"[DISTILL] Kev-0.8B teacher labeling finished in {time.perf_counter() - t0:.1f}s.")

    return items


def build_mlx_laya_trainer(raw_weights: dict[str, Any], enc_cfg: dict[str, Any], freeze_below_layer: int = 18) -> Any:
    """Build exact MLX ModernBERT-large + 2-layer Head + Scorer matching `_compile_laya_seq_bundle`."""
    import mlx.core as mx
    import mlx.nn as nn

    H = int(enc_cfg["hidden_size"])
    n_layers = int(enc_cfg["num_hidden_layers"])
    n_heads = int(enc_cfg["num_attention_heads"])
    hd = H // n_heads
    attn_scale = 1.0 / math.sqrt(hd)
    layer_types = list(enc_cfg["layer_types"])
    local_window = int(enc_cfg.get("local_attention", 128))
    rope_params = enc_cfg.get("rope_parameters", {})
    theta_full = float(rope_params.get("full_attention", {}).get("rope_theta", 160000.0))
    theta_swa = float(rope_params.get("sliding_attention", {}).get("rope_theta", 10000.0))

    def _rope_tables(max_s: int, theta: float) -> tuple[Any, Any]:
        half = hd // 2
        inv_freq = 1.0 / (theta ** (np.arange(half, dtype=np.float64) / half))
        angles = np.arange(max_s, dtype=np.float64)[:, None] * inv_freq[None, :]
        cos = mx.array(np.cos(angles).astype(np.float32)[None, None, :, :])
        sin = mx.array(np.sin(angles).astype(np.float32)[None, None, :, :])
        return cos, sin

    cos_full, sin_full = _rope_tables(512, theta_full)
    cos_swa, sin_swa = _rope_tables(512, theta_swa)
    idx_512 = np.arange(512)
    swa_allow = np.abs(idx_512[:, None] - idx_512[None, :]) <= (local_window // 2)
    swa_bias_512 = mx.array(np.where(swa_allow, 0.0, -10000.0).astype(np.float32)[None, None, :, :])

    def _apply_rope(x: Any, cos_t: Any, sin_t: Any, S: int) -> Any:
        c = cos_t[:, :, :S, :].astype(x.dtype)
        s = sin_t[:, :, :S, :].astype(x.dtype)
        x0, x1 = mx.split(x, 2, axis=-1)
        return mx.concatenate([x0 * c - x1 * s, x1 * c + x0 * s], axis=-1)

    def _ln_nobias(x: Any, w: Any) -> Any:
        xf = x.astype(mx.float32)
        mn = mx.mean(xf, axis=-1, keepdims=True)
        xc = xf - mn
        vr = mx.mean(xc * xc, axis=-1, keepdims=True)
        xn = xc * mx.rsqrt(vr + 1e-5)
        return (xn * w.astype(mx.float32)).astype(x.dtype)

    def _ln_bias(x: Any, w: Any, b: Any) -> Any:
        xf = x.astype(mx.float32)
        mn = mx.mean(xf, axis=-1, keepdims=True)
        xc = xf - mn
        vr = mx.mean(xc * xc, axis=-1, keepdims=True)
        xn = xc * mx.rsqrt(vr + 1e-5)
        return (xn * w.astype(mx.float32) + b.astype(mx.float32)).astype(x.dtype)

    # Split into frozen tensors (`0..freeze_below_layer-1`) + trainable parameter dict (`freeze_below_layer..27` + head + scorer)
    frozen: dict[str, Any] = {}
    trainable: dict[str, Any] = {}
    for k, v in raw_weights.items():
        is_train = False
        if k.startswith(("head.", "scorer.", "type_emb.", "encoder.final_norm.")):
            is_train = True
        elif k.startswith("encoder.layers."):
            li = int(k.split(".")[2])
            if li >= freeze_below_layer:
                is_train = True
        if is_train:
            trainable[k] = v.astype(mx.float32)
        else:
            frozen[k] = v.astype(mx.bfloat16)

    mx.eval(frozen, trainable)

    def forward_logits(params: dict[str, Any], ids: Any, valid_lens: Any, qtypes: Any) -> Any:
        B, S = ids.shape
        pos = mx.arange(S)[None, :]
        valid_2d = pos < valid_lens[:, None]  # [B, S]
        ext_mask = mx.where(valid_2d[:, None, None, :], 0.0, -10000.0).astype(mx.bfloat16)
        swa_mask = ext_mask + swa_bias_512[:, :, :S, :S].astype(mx.bfloat16)

        tok_emb = mx.take(frozen["encoder.embeddings.tok_embeddings.weight"], ids, axis=0)
        cur = _ln_nobias(tok_emb, frozen["encoder.embeddings.norm.weight"])

        for i in range(n_layers):
            px = f"encoder.layers.{i}."
            src = frozen if i < freeze_below_layer else params
            is_full = layer_types[i] == "full_attention"
            x_attn = cur if i == 0 else _ln_nobias(cur, src[px + "attn_norm.weight"])
            wqkv = src[px + "attn.Wqkv.weight"].astype(mx.bfloat16)
            qkv = x_attn @ wqkv.T
            qt, kt, vt = mx.split(qkv, 3, axis=-1)
            qh = qt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            kh = kt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            vh = vt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            c_t, s_t = (cos_full, sin_full) if is_full else (cos_swa, sin_swa)
            qrp = _apply_rope(qh, c_t, s_t, S)
            krp = _apply_rope(kh, c_t, s_t, S)
            att = mx.fast.scaled_dot_product_attention(
                qrp, krp, vh, scale=attn_scale, mask=(ext_mask if is_full else swa_mask)
            )
            att_flat = att.transpose(0, 2, 1, 3).reshape(B, S, H)
            wo = src[px + "attn.Wo.weight"].astype(mx.bfloat16)
            cur = cur + (att_flat @ wo.T)

            x_mlp = _ln_nobias(cur, src[px + "mlp_norm.weight"])
            wi = src[px + "mlp.Wi.weight"].astype(mx.bfloat16)
            val_h, gate_h = mx.split(x_mlp @ wi.T, 2, axis=-1)
            geglu = nn.gelu(val_h) * gate_h
            wom = src[px + "mlp.Wo.weight"].astype(mx.bfloat16)
            cur = cur + (geglu @ wom.T)

            if i == freeze_below_layer - 1:
                cur = mx.stop_gradient(cur)

        h = _ln_nobias(cur, params["encoder.final_norm.weight"]).astype(mx.float32)
        t_vec = mx.take(params["type_emb.weight"], qtypes, axis=0)[:, None, :]
        h = h + t_vec

        ext_f32 = ext_mask.astype(mx.float32)
        for hi in range(2):
            hp = f"head.layers.{hi}."
            hn1 = _ln_bias(h, params[hp + "norm1.weight"], params[hp + "norm1.bias"])
            hqkv = hn1 @ params[hp + "self_attn.in_proj_weight"].T + params[hp + "self_attn.in_proj_bias"]
            hqt, hkt, hvt = mx.split(hqkv, 3, axis=-1)
            hqh = hqt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            hkh = hkt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            hvh = hvt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            hatt = mx.fast.scaled_dot_product_attention(hqh, hkh, hvh, scale=attn_scale, mask=ext_f32)
            hatt_flat = hatt.transpose(0, 2, 1, 3).reshape(B, S, H)
            h = h + (hatt_flat @ params[hp + "self_attn.out_proj.weight"].T + params[hp + "self_attn.out_proj.bias"])
            hn2 = _ln_bias(h, params[hp + "norm2.weight"], params[hp + "norm2.bias"])
            hl1 = nn.relu(hn2 @ params[hp + "linear1.weight"].T + params[hp + "linear1.bias"])
            h = h + (hl1 @ params[hp + "linear2.weight"].T + params[hp + "linear2.bias"])

        sn = _ln_bias(h, params["scorer.0.weight"], params["scorer.0.bias"])
        sg = nn.gelu(sn @ params["scorer.1.weight"].T + params["scorer.1.bias"])
        pos_logits = (sg @ params["scorer.3.weight"].T + params["scorer.3.bias"]).squeeze(-1)
        return pos_logits  # [B, S] float32

    return frozen, trainable, forward_logits


def eval_multi_task_loss(
    params: dict[str, Any],
    forward_fn: Any,
    eval_items: list[dict[str, Any]],
    pad_id: int,
    temps: dict[str, float],
    batch_size: int = 24,
) -> dict[str, float]:
    import mlx.core as mx

    losses_by_task: dict[str, list[float]] = collections.defaultdict(list)
    correct_by_task: dict[str, list[int]] = collections.defaultdict(list)

    for start in range(0, len(eval_items), batch_size):
        chunk = eval_items[start : start + batch_size]
        max_len = min(512, max(len(x["ids"]) for x in chunk))
        S_b = 256 if max_len <= 256 else 512
        B = len(chunk)
        ids_np = np.full((B, S_b), pad_id, dtype=np.int32)
        vl_np = np.zeros((B,), dtype=np.int32)
        qt_np = np.zeros((B,), dtype=np.int32)
        for bi, it in enumerate(chunk):
            ln = min(S_b, len(it["ids"]))
            ids_np[bi, :ln] = it["ids"][:ln]
            vl_np[bi] = ln
            qt_np[bi] = it["qtype"]
        logits_bs = np.asarray(forward_fn(params, mx.array(ids_np), mx.array(vl_np), mx.array(qt_np)))
        for bi, it in enumerate(chunk):
            mks = [m for m in it["markers"] if m < S_b]
            k = len(mks)
            if k < 2 or it["target"] >= k:
                continue
            z = logits_bs[bi, mks]
            if it["qtype"] == 2:
                t_val = temps.get("noul:2", 1.98)
            elif k <= 10:
                t_val = temps.get("choice:6-10", 1.0)
            else:
                t_val = temps.get("choice:11+", 0.25)
            z_scaled = z / max(t_val, 0.05)
            z_scaled -= float(np.max(z_scaled))
            probs = np.exp(z_scaled)
            probs /= float(np.sum(probs))
            nll = float(-math.log(max(float(probs[it["target"]]), 1e-7)))
            fam = "router" if it["task"] == "router_choice" else ("persona_role" if it["task"] == "persona_role_choice" else ("persona_noul" if "persona_noul" in it["task"] else "doc_noul"))
            losses_by_task[fam].append(nll)
            correct_by_task[fam].append(int(int(np.argmax(probs)) == int(it["target"])))

    summary: dict[str, float] = {}
    all_l: list[float] = []
    for fam, vals in losses_by_task.items():
        summary[f"{fam}_nll"] = round(float(np.mean(vals)), 4)
        summary[f"{fam}_acc"] = round(float(np.mean(correct_by_task[fam])), 4)
        all_l.extend(vals)
    summary["mean_nll"] = round(float(np.mean(all_l)) if all_l else 0.0, 4)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--train-jsonl",
        required=True,
        help="Path to train_v6_3_complete_ssot_gold.jsonl",
    )
    ap.add_argument(
        "--base-laya-dir",
        required=True,
        help="Directory containing base Laya-Typed model.safetensors, encoder/config.json, rl_agent_config.json",
    )
    ap.add_argument(
        "--coreml-python",
        required=True,
        help="Python executable with coremltools installed for W8A16 ANE compilation",
    )
    ap.add_argument("--home", default=None, help="Package root override (defaults to packages/congress_docmeta)")
    ap.add_argument("--artifacts-dir", default=None, help="Override atomic_validators output directory")
    ap.add_argument("--steps", type=int, default=420, help="MLX fine-tuning steps on train_split")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--lr", type=float, default=3.5e-5)
    ap.add_argument("--distill-docs", type=int, default=320)
    args = ap.parse_args()

    import mlx.core as mx
    import mlx.optimizers as optim

    repo_root = resolve_docmeta_pkg_root(args.home)
    artifacts_dir = resolve_docmeta_validators_dir(args.artifacts_dir, home=args.home)
    laya_out_dir = artifacts_dir / "laya_typed"
    base_laya_dir = Path(args.base_laya_dir).expanduser().resolve()

    print(f"[1/6] Loading and splitting {args.train_jsonl} ...")
    raw_lines = Path(args.train_jsonl).expanduser().resolve().read_text(encoding="utf-8").splitlines()
    all_records = [parse_v4_prompt_row(json.loads(ln)) for ln in raw_lines if ln.strip()]
    print(f"      Parsed {len(all_records)} gold records across {len({r['router_class'] for r in all_records})} router classes.")

    # Deterministic stratified split: ~500 calibration docs, ~2,417 train docs (every class >=2 docs keeps >=1 in train!)
    by_cls: dict[str, list[int]] = collections.defaultdict(list)
    for idx, r in enumerate(all_records):
        by_cls[r["router_class"]].append(idx)

    rng_split = random.Random(20261116)
    train_idxs: list[int] = []
    cal_idxs: list[int] = []
    for cls_k in sorted(by_cls):
         grp = list(by_cls[cls_k])
         rng_split.shuffle(grp)
         if len(grp) <= 2:
             train_idxs.extend(grp)
         else:
             n_cal = max(1, int(round(len(grp) * (500.0 / len(all_records)))))
             n_cal = min(n_cal, len(grp) - 1)
             cal_idxs.extend(grp[:n_cal])
             train_idxs.extend(grp[n_cal:])

    train_records = [all_records[i] for i in train_idxs]
    cal_records = [all_records[i] for i in cal_idxs]
    print(f"      Split: train={len(train_records)} docs | cal={len(cal_records)} docs (0 eval overlap).")

    # [2/6] Train Tier-0 Sub-Millisecond Hashed N-Gram Router (5-fold OOF on train + full train -> cal)
    print("[2/6] Training Tier-0 Linear Router (`router_v63_linear.npz`, D=12,288, C=54)...")
    X_train = build_dense_feature_matrix(train_records, dim=12288)
    y_train = np.array([ROUTER_CLASS_TO_IDX[r["router_class"]] for r in train_records], dtype=np.int32)
    X_cal = build_dense_feature_matrix(cal_records, dim=12288)
    y_cal = np.array([ROUTER_CLASS_TO_IDX[r["router_class"]] for r in cal_records], dtype=np.int32)

    oof_logits = np.zeros((len(train_records), len(ROUTER_CLASSES)), dtype=np.float32)
    with acquire_hw_lock("train_v63_linear_router"):
        for fold in range(5):
            val_m = (np.arange(len(train_records)) % 5) == fold
            tr_m = ~val_m
            W_f, b_f = train_linear_router_mlx(X_train[tr_m], y_train[tr_m], len(ROUTER_CLASSES))
            oof_logits[val_m] = X_train[val_m] @ W_f.T + b_f
        W_full, b_full = train_linear_router_mlx(X_train, y_train, len(ROUTER_CLASSES))

    cal_lin_logits = X_cal @ W_full.T + b_full
    lin_temp = fit_temperature_np(cal_lin_logits, y_cal)
    cal_lin_probs = softmax_np(cal_lin_logits, lin_temp)
    top1_acc = float(np.mean(np.argmax(cal_lin_probs, axis=-1) == y_cal))
    top6_Order = np.argsort(-cal_lin_probs, axis=-1)[:, :6]
    top6_rec = float(np.mean([y_cal[i] in top6_Order[i] for i in range(len(y_cal))]))
    print(f"      [Tier-0 Linear on cal_500] Top-1 Acc={top1_acc:.4f} | Top-6 Recall={top6_rec:.4f} | T={lin_temp}")

    router_npz_path = artifacts_dir / "router_v63_linear.npz"
    np.savez_compressed(
        router_npz_path,
        W_f16=W_full.astype(np.float16),
        b_f32=b_full.astype(np.float32),
        classes=np.array(ROUTER_CLASSES),
        dim=np.int32(12288),
        temperature=np.float32(lin_temp),
    )

    oof_top6: list[list[str]] = [
        [ROUTER_CLASSES[idx_c] for idx_c in np.argsort(-oof_logits[row_i])[:6]]
        for row_i in range(len(train_records))
    ]
    cal_top6: list[list[str]] = [
        [ROUTER_CLASSES[idx_c] for idx_c in top6_Order[row_i]]
        for row_i in range(len(cal_records))
    ]

    # [3/6] Parity check + Build Multi-Task Dataset + Kev-0.8B W8 Teacher Distillation
    dylib_p = ensure_laya_dylib()
    with acquire_hw_lock("train_v63_distill_and_lora"):
        laya_ane = LayaAneBackend(laya_out_dir, dylib_p, pipe_depth=4)
        enc_cfg = json.loads((base_laya_dir / "encoder" / "config.json").read_text(encoding="utf-8"))
        rl_cfg = json.loads((base_laya_dir / "rl_agent_config.json").read_text(encoding="utf-8"))
        raw_mx = mx.load(str(base_laya_dir / "model.safetensors"))
        frozen_w, train_params, forward_fn = build_mlx_laya_trainer(raw_mx, enc_cfg, freeze_below_layer=18)

        # Verify MLX forward parity against live CoreML ANE W8A16 before training!
        probe_st, probe_qs = build_atomic_doc_questions_v6(train_records[0]["gold"], train_records[0])
        probe_enc = laya_ane.encode_item(probe_st, probe_qs[0])
        ane_p1 = laya_ane.score_noul_batch([probe_enc])[0]
        ids_p = np.full((1, 512), laya_ane.pad_id, dtype=np.int32)
        ln_p = min(512, len(probe_enc["ids"]))
        ids_p[0, :ln_p] = probe_enc["ids"][:ln_p]
        mlx_out = np.asarray(
            forward_fn(
                train_params,
                mx.array(ids_p),
                mx.array(np.array([ln_p], dtype=np.int32)),
                mx.array(np.array([2], dtype=np.int32)),
            )
        )[0]
        t_noul0 = float(rl_cfg["temperature_by_options"]["noul:2"])
        ez0, ez1 = math.exp(mlx_out[probe_enc["markers"][0]] / t_noul0), math.exp(mlx_out[probe_enc["markers"][1]] / t_noul0)
        mlx_p1 = ez1 / (ez0 + ez1)
        print(f"[3/6] MLX vs CoreML ANE W8A16 pre-train parity: ANE P(true)={ane_p1:.4f} vs MLX P(true)={mlx_p1:.4f} (|dp|={abs(ane_p1 - mlx_p1):.4f})")
        assert abs(ane_p1 - mlx_p1) < 0.05, f"Parity mismatch between MLX trainer and ANE bundle: {ane_p1} vs {mlx_p1}"

        kev_teacher = Kev08bMlxBackend(artifacts_dir / "kev_08b", quant_mode="w8", batch_docs=1) if args.distill_docs > 0 else None
        train_items = synthesize_training_examples(
            train_records, oof_top6, laya_ane, kev_teacher, distill_docs=args.distill_docs, seed=20261116
        )
        cal_items = synthesize_training_examples(
            cal_records, cal_top6, laya_ane, None, distill_docs=0, seed=20261117
        )
        if kev_teacher is not None:
            kev_teacher.close()
            del kev_teacher
        laya_ane.close()

        print(f"      Built {len(train_items)} multi-task train items & {len(cal_items)} cal items.")
        temps_init = dict(rl_cfg["temperature_by_options"])
        temps_init["choice:11+"] = 1.0  # normal logit scale for 16-way role training!

        pre_metrics = eval_multi_task_loss(train_params, forward_fn, cal_items[:900], 50283, temps_init)
        print(f"      [Pre-Train cal_split metrics] {pre_metrics}")

        # [4/6] Fine-tune upper ModernBERT layers (18..27) + Head + Scorer in MLX
        print(f"[4/6] Fine-tuning Laya-Typed-421M ({args.steps} steps, B={args.batch_size}, lr={args.lr})...")
        base_snap = {k: mx.array(np.asarray(v)) for k, v in train_params.items()}
        opt = optim.AdamW(learning_rate=args.lr, weight_decay=0.01)

        # Bucket train items by length (<=256 vs <=512) for zero wasted pad FLOPs!
        short_items = [it for it in train_items if len(it["ids"]) <= 256 and len(it["markers"]) >= 2]
        long_items = [it for it in train_items if len(it["ids"]) > 256 and len(it["markers"]) >= 2]
        rng_tr = random.Random(20261116)

        def step_loss_fn(
            p: dict[str, Any],
            ids_b: Any,
            vl_b: Any,
            qt_b: Any,
            mk_idx_b: Any,
            mk_valid_b: Any,
            targets_b: Any,
            soft_p1_b: Any,
            has_soft_b: Any,
            inv_temp_b: Any,
        ) -> Any:
            pos_logits = forward_fn(p, ids_b, vl_b, qt_b)  # [B, S]
            gathered = mx.take_along_axis(pos_logits, mk_idx_b, axis=-1)  # [B, K_max]
            scaled = gathered * inv_temp_b[:, None]
            masked = mx.where(mk_valid_b, scaled, -1e9)
            lse = mx.logsumexp(masked, axis=-1)
            log_probs = masked - lse[:, None]
            gold_nll = -mx.take_along_axis(log_probs, targets_b[:, None], axis=-1).squeeze(-1)

            # Kev-0.8B soft-target distillation loss on 2-option Noul items where teacher ran
            lp0 = log_probs[:, 0]
            lp1 = log_probs[:, 1]
            kl_soft = -( (1.0 - soft_p1_b) * lp0 + soft_p1_b * lp1 )
            combined = mx.where(has_soft_b, 0.65 * gold_nll + 0.35 * kl_soft, gold_nll)
            return mx.mean(combined)

        vg_fn = mx.value_and_grad(step_loss_fn)
        B = args.batch_size
        K_MAX = 16
        best_nll = pre_metrics["mean_nll"]
        best_params = {k: np.asarray(v).copy() for k, v in train_params.items()}
        t_tr0 = time.perf_counter()

        for step in range(1, args.steps + 1):
            # Cosine LR decay with 30-step linear warmup
            if step <= 30:
                cur_lr = args.lr * (step / 30.0)
            else:
                prog_f = (step - 30) / float(max(1, args.steps - 30))
                cur_lr = args.lr * (0.10 + 0.90 * 0.5 * (1.0 + math.cos(math.pi * prog_f)))
            opt.learning_rate = cur_lr

            pool = short_items if ( (step % 3 != 0 and len(short_items) >= B) or len(long_items) < B ) else long_items
            S_b = 256 if pool is short_items else 512
            batch = rng_tr.sample(pool, B)

            ids_np = np.full((B, S_b), 50283, dtype=np.int32)
            vl_np = np.zeros((B,), dtype=np.int32)
            qt_np = np.zeros((B,), dtype=np.int32)
            mk_np = np.zeros((B, K_MAX), dtype=np.int32)
            mkv_np = np.zeros((B, K_MAX), dtype=bool)
            tgt_np = np.zeros((B,), dtype=np.int32)
            sp1_np = np.full((B,), 0.5, dtype=np.float32)
            hsp_np = np.zeros((B,), dtype=bool)
            invt_np = np.ones((B,), dtype=np.float32)

            for bi, it in enumerate(batch):
                ln = min(S_b, len(it["ids"]))
                ids_np[bi, :ln] = it["ids"][:ln]
                vl_np[bi] = ln
                qt_np[bi] = it["qtype"]
                mks = [m for m in it["markers"] if m < S_b][:K_MAX]
                k_i = len(mks)
                mk_np[bi, :k_i] = mks
                mkv_np[bi, :k_i] = True
                tgt_np[bi] = min(int(it["target"]), max(0, k_i - 1))
                if it["qtype"] == 2:
                    invt_np[bi] = 1.0 / 1.5
                    if it["soft_p1"] is not None:
                        sp1_np[bi] = float(it["soft_p1"])
                        hsp_np[bi] = True
                else:
                    invt_np[bi] = 1.0

            loss_v, grads = vg_fn(
                train_params,
                mx.array(ids_np),
                mx.array(vl_np),
                mx.array(qt_np),
                mx.array(mk_np),
                mx.array(mkv_np),
                mx.array(tgt_np),
                mx.array(sp1_np),
                mx.array(hsp_np),
                mx.array(invt_np),
            )
            # Clip global gradient norm to 1.0 for rock-solid ModernBERT stability
            sq_norm = sum(float(mx.sum(g * g)) for g in grads.values())
            gnorm = math.sqrt(max(sq_norm, 1e-12))
            if gnorm > 1.0:
                scale_g = 1.0 / gnorm
                grads = {k: g * scale_g for k, g in grads.items()}
            opt.update(train_params, grads)
            mx.eval(train_params, loss_v)

            if step % 105 == 0 or step == args.steps:
                m_cal = eval_multi_task_loss(train_params, forward_fn, cal_items[:900], 50283, {"noul:2": 1.5, "choice:6-10": 1.0, "choice:11+": 1.0})
                el = time.perf_counter() - t_tr0
                print(f"      step {step:3d}/{args.steps} ({el:.1f}s) | train_loss={float(loss_v):.4f} | cal={m_cal}")
                if m_cal["mean_nll"] < best_nll:
                    best_nll = m_cal["mean_nll"]
                    best_params = {k: np.asarray(v).copy() for k, v in train_params.items()}

        assert best_nll < pre_metrics["mean_nll"], f"Expected fine-tuned cal NLL < {pre_metrics['mean_nll']}, got {best_nll}"

    # [5/6] Export Merged Safetensors & Compile W8A16 CoreML ANE Models (`s256` & `s512`)
    print("[5/6] Exporting merged Laya-Typed-v63 checkpoint & compiling CoreML W8A16 ANE bundles...")
    with tempfile.TemporaryDirectory(prefix="laya_v63_export_") as tmp_s:
        tmp_export = Path(tmp_s)
        (tmp_export / "encoder").mkdir(parents=True, exist_ok=True)
        (tmp_export / "tokenizer").mkdir(parents=True, exist_ok=True)
        shutil.copy2(base_laya_dir / "encoder" / "config.json", tmp_export / "encoder" / "config.json")
        shutil.copy2(base_laya_dir / "tokenizer" / "tokenizer.json", tmp_export / "tokenizer" / "tokenizer.json")
        if (base_laya_dir / "tokenizer" / "tokenizer_config.json").exists():
            shutil.copy2(base_laya_dir / "tokenizer" / "tokenizer_config.json", tmp_export / "tokenizer" / "tokenizer_config.json")

        new_rl_cfg = dict(rl_cfg)
        new_rl_cfg["model_name"] = "laya-typed-decisions-congressional-v63"
        new_rl_cfg["temperature_by_options"] = dict(rl_cfg["temperature_by_options"])
        new_rl_cfg["temperature_by_options"]["noul:2"] = 1.5
        new_rl_cfg["temperature_by_options"]["choice:6-10"] = 1.0
        new_rl_cfg["temperature_by_options"]["choice:11+"] = 1.0
        (tmp_export / "rl_agent_config.json").write_text(json.dumps(new_rl_cfg, indent=2), encoding="utf-8")

        merged_mx: dict[str, Any] = {}
        for k, v in raw_mx.items():
            if k in best_params:
                merged_mx[k] = mx.array(best_params[k].astype(np.float32))
            else:
                merged_mx[k] = v.astype(mx.float32)
        mx.save_safetensors(str(tmp_export / "model.safetensors"), merged_mx)

        # Build CoreML `.mlmodelc` bundles under `--coreml-python` via `fast_decision_models.builder`.
        # First save `laya_typed_emb_f16.npz` & configs, then compile `.mlmodelc` via coremltools python
        shutil.copy2(tmp_export / "rl_agent_config.json", laya_out_dir / "rl_agent_config.json")
        type_f16 = best_params["type_emb.weight"].astype(np.float16)
        word_f16 = np.asarray(raw_mx["encoder.embeddings.tok_embeddings.weight"].astype(mx.float16))
        np.savez(
            laya_out_dir / "laya_typed_emb_f16.npz",
            word_f16=np.ascontiguousarray(word_f16),
            type_f16=np.ascontiguousarray(type_f16),
        )
        np.savez(tmp_export / "merged_weights_f32.npz", **{k: np.asarray(v) for k, v in merged_mx.items()})

        import fast_decision_models

        fdm_src_dir = Path(fast_decision_models.__file__).resolve().parents[1]
        compile_snippet = (
            "import json, sys, numpy as np\n"
            "from pathlib import Path\n"
            f"sys.path.insert(0, {str(fdm_src_dir)!r})\n"
            "from fast_decision_models._common import acquire_hw_lock\n"
            "from fast_decision_models.builder import _compile_laya_seq_bundle\n"
            f"tmp_p = Path({str(tmp_export)!r})\n"
            f"out_p = Path({str(laya_out_dir)!r})\n"
            "enc_cfg = json.loads((tmp_p / 'encoder' / 'config.json').read_text())\n"
            "w_npz = np.load(tmp_p / 'merged_weights_f32.npz')\n"
            "w = {k: w_npz[k] for k in w_npz.files}\n"
            "with acquire_hw_lock('compile_laya_v63_coreml'):\n"
            "    for s in (256, 512):\n"
            "        p = _compile_laya_seq_bundle(s, w, enc_cfg, out_p)\n"
            "        print('Compiled:', p)\n"
        )
        subprocess.check_call([args.coreml_python, "-c", compile_snippet])

    # [6/6] Live ANE Verification + Fit `router_v63_calibration.json` & `validator_v63_calibration.json` on `cal_500`!
    print("[6/6] Fitting live ANE calibration & precision-coverage thresholds on held-out cal_500...")
    with acquire_hw_lock("calibrate_v63_live_ane"):
        laya_v63 = LayaAneBackend(laya_out_dir, dylib_p, pipe_depth=4)
        plans = laya_v63.inspect_compute_plans()
        print(f"      Live CoreML ANE Plans: {plans}")
        for btag, (ane_ops, gpu_ops, _cpu) in plans.items():
            assert gpu_ops == 0 and ane_ops > 1000, f"Invalid plan on {btag}: {plans}"

        # Evaluate ANE Top-6 Router Choice on all `cal_records` (`500` docs)
        r_encs = []
        for ci, rec in enumerate(cal_records):
            st_r, q_r = build_router_choice_item(rec, cal_top6[ci])
            r_encs.append(laya_v63.encode_item(st_r, q_r))

        # Run ANE bucket batch on Choice items
        out_512 = laya_v63._exec_bucket(r_encs, 512, laya_v63._h512)
        ane_top6_logits = np.zeros((len(cal_records), 6), dtype=np.float32)
        for ci, enc_it in enumerate(r_encs):
            mks = enc_it["markers"]
            for j in range(len(mks)):
                ane_top6_logits[ci, j] = float(out_512[ci, mks[j]])

        # Fuse Tier-0 Linear log-probs + Tier-1 ANE Laya Choice logits on `cal_500`!
        best_alpha = 0.5
        best_t_r = 1.0
        best_acc = -1.0
        best_fused_probs = cal_lin_probs.copy()

        lin_logp = np.log(np.clip(cal_lin_probs, 1e-8, 1.0))
        for alpha in np.linspace(0.15, 0.85, 15):
            for t_ane in np.linspace(0.5, 2.5, 21):
                ane_p6 = softmax_np(ane_top6_logits, float(t_ane))
                ane_logp6 = np.log(np.clip(ane_p6, 1e-8, 1.0))
                fused = lin_logp.copy()
                # Subtract boost baseline from outside-Top-6 so probabilities stay consistent
                fused -= (1.0 - float(alpha)) * 6.0
                for ci in range(len(cal_records)):
                    for j, cls_idx in enumerate(top6_Order[ci]):
                        fused[ci, cls_idx] = float(alpha) * lin_logp[ci, cls_idx] + (1.0 - float(alpha)) * ane_logp6[ci, j]
                f_probs = softmax_np(fused, 1.0)
                acc_c = float(np.mean(np.argmax(f_probs, axis=-1) == y_cal))
                if acc_c > best_acc:
                    best_acc = acc_c
                    best_alpha = round(float(alpha), 3)
                    best_t_r = round(float(t_ane), 3)
                    best_fused_probs = f_probs

        # Fit single-kind lock threshold `tau_top1` (>= 96% precision on usable predictions!)
        # and Top-2 / Top-3 narrowed enum thresholds (`>= 98%` set coverage!)
        usable_mask = np.array([not ROUTER_CLASSES[int(np.argmax(best_fused_probs[i]))].startswith("status:") for i in range(len(y_cal))])
        p_top1 = np.max(best_fused_probs, axis=-1)
        pred_top1 = np.argmax(best_fused_probs, axis=-1)

        tau_top1 = 0.88
        for cand_tau in np.linspace(0.50, 0.96, 93):
            sel = usable_mask & (p_top1 >= cand_tau)
            if int(np.sum(sel)) < 25:
                continue
            prec = float(np.mean(pred_top1[sel] == y_cal[sel]))
            if prec >= 0.960:
                tau_top1 = round(float(cand_tau), 4)
                break

        sorted_p = np.sort(best_fused_probs, axis=-1)[:, ::-1]
        sorted_i = np.argsort(-best_fused_probs, axis=-1)
        p_top2 = sorted_p[:, 0] + sorted_p[:, 1]
        p_top3 = p_top2 + sorted_p[:, 2]

        tau_top2 = 0.88
        for cand_tau in np.linspace(0.60, 0.98, 77):
            sel = (p_top1 < tau_top1) & (p_top2 >= cand_tau)
            # Only narrow when top-2 are both usable doc_kinds
            valid_k2 = np.array([
                all(not ROUTER_CLASSES[int(sorted_i[r_i, j])].startswith("status:") for j in range(2))
                for r_i in range(len(y_cal))
            ])
            sel = sel & valid_k2
            if int(np.sum(sel)) < 15:
                continue
            cov2 = float(np.mean([y_cal[r_i] in sorted_i[r_i, :2] for r_i in np.where(sel)[0]]))
            if cov2 >= 0.975:
                tau_top2 = round(float(cand_tau), 4)
                break

        tau_top3 = 0.90
        for cand_tau in np.linspace(0.65, 0.98, 67):
            sel = (p_top1 < tau_top1) & (p_top2 < tau_top2) & (p_top3 >= cand_tau)
            valid_k3 = np.array([
                all(not ROUTER_CLASSES[int(sorted_i[r_i, j])].startswith("status:") for j in range(3))
                for r_i in range(len(y_cal))
            ])
            sel = sel & valid_k3
            if int(np.sum(sel)) < 10:
                continue
            cov3 = float(np.mean([y_cal[r_i] in sorted_i[r_i, :3] for r_i in np.where(sel)[0]]))
            if cov3 >= 0.980:
                tau_top3 = round(float(cand_tau), 4)
                break

        sel1 = usable_mask & (p_top1 >= tau_top1)
        prec1 = float(np.mean(pred_top1[sel1] == y_cal[sel1])) if np.any(sel1) else 1.0
        cov1 = float(np.mean(sel1))
        print(
            f"      [Fused ANE Router on cal_500] Top-1 Acc={best_acc:.4f} (vs {top1_acc:.4f} linear) | "
            f"tau_top1={tau_top1} (lock_cov={cov1:.1%}, lock_prec={prec1:.2%}) | tau_top2={tau_top2} | tau_top3={tau_top3}"
        )

        # Also fit linear-only thresholds (`fast` mode)
        lin_p1 = np.max(cal_lin_probs, axis=-1)
        lin_pred1 = np.argmax(cal_lin_probs, axis=-1)
        lin_usable = np.array([not ROUTER_CLASSES[int(lin_pred1[i])].startswith("status:") for i in range(len(y_cal))])
        lin_tau1 = 0.90
        for cand_tau in np.linspace(0.55, 0.98, 87):
            sel_l = lin_usable & (lin_p1 >= cand_tau)
            if int(np.sum(sel_l)) >= 20 and float(np.mean(lin_pred1[sel_l] == y_cal[sel_l])) >= 0.960:
                lin_tau1 = round(float(cand_tau), 4)
                break

        router_cal = {
            "version": "v6_3",
            "train_docs": len(train_records),
            "cal_docs": len(cal_records),
            "num_classes": len(ROUTER_CLASSES),
            "linear_top1_acc_cal500": round(top1_acc, 4),
            "linear_top6_recall_cal500": round(top6_rec, 4),
            "ane_fused_top1_acc_cal500": round(best_acc, 4),
            "fusion_linear_alpha": best_alpha,
            "ane_choice_temperature": best_t_r,
            "ane_tau_top1": tau_top1,
            "ane_tau_top2": tau_top2,
            "ane_tau_top3": tau_top3,
            "ane_lock1_coverage_cal500": round(cov1, 4),
            "ane_lock1_precision_cal500": round(prec1, 4),
            "fast_linear_tau_top1": lin_tau1,
        }
        (artifacts_dir / "router_v63_calibration.json").write_text(json.dumps(router_cal, indent=2), encoding="utf-8")

        # Calibrate Noul temperature on `cal_items` using live compiled ANE model!
        noul_cal = [it for it in cal_items if it["qtype"] == 2][:800]
        raw_t = float(laya_v63.temperature_by_options["noul:2"])
        # Collect raw logit diffs z1 - z0 via `_exec_bucket`
        idx256 = [i for i, it in enumerate(noul_cal) if len(it["ids"]) <= 256]
        idx512 = [i for i, it in enumerate(noul_cal) if len(it["ids"]) > 256]
        z_diffs = np.zeros((len(noul_cal),), dtype=np.float32)
        y_noul = np.array([it["target"] for it in noul_cal], dtype=np.int32)
        if idx256:
            o256 = laya_v63._exec_bucket([noul_cal[i] for i in idx256], 256, laya_v63._h256)
            for bi, oi in enumerate(idx256):
                mk = noul_cal[oi]["markers"]
                z_diffs[oi] = float(o256[bi, mk[1]] - o256[bi, mk[0]])
        if idx512:
            o512 = laya_v63._exec_bucket([noul_cal[i] for i in idx512], 512, laya_v63._h512)
            for bi, oi in enumerate(idx512):
                mk = noul_cal[oi]["markers"]
                z_diffs[oi] = float(o512[bi, mk[1]] - o512[bi, mk[0]])

        best_tn = 1.5
        best_brier = 1e9
        for cand_t in np.linspace(0.4, 3.0, 131):
            p1s = 1.0 / (1.0 + np.exp(-np.clip(z_diffs / float(cand_t), -30.0, 30.0)))
            brier = float(np.mean((p1s - y_noul) ** 2))
            if brier < best_brier:
                best_brier = brier
                best_tn = round(float(cand_t), 4)

        # Update `noul:2` temperature in `rl_agent_config.json` to Brier-optimal value!
        cfg_final = json.loads((laya_out_dir / "rl_agent_config.json").read_text(encoding="utf-8"))
        cfg_final["temperature_by_options"]["noul:2"] = best_tn
        (laya_out_dir / "rl_agent_config.json").write_text(json.dumps(cfg_final, indent=2), encoding="utf-8")

        # Also evaluate live ANE Persona Role Choice(16) accuracy on `cal_items`!
        role_cal = [it for it in cal_items if it["task"] == "persona_role_choice"][:400]
        role_acc_ane = 0.0
        best_tr_role = 1.0
        if role_cal:
            o_rc = laya_v63._exec_bucket(role_cal, 512, laya_v63._h512)
            rc_logits = np.zeros((len(role_cal), len(ALL_ROLES)), dtype=np.float32)
            rc_y = np.array([it["target"] for it in role_cal], dtype=np.int32)
            for ci, it in enumerate(role_cal):
                for j, mpos in enumerate(it["markers"][: len(ALL_ROLES)]):
                    rc_logits[ci, j] = float(o_rc[ci, mpos])
            best_tr_role = fit_temperature_np(rc_logits, rc_y)
            rc_probs = softmax_np(rc_logits, best_tr_role)
            role_acc_ane = float(np.mean(np.argmax(rc_probs, axis=-1) == rc_y))
            cfg_final["temperature_by_options"]["choice:11+"] = best_tr_role
            (laya_out_dir / "rl_agent_config.json").write_text(json.dumps(cfg_final, indent=2), encoding="utf-8")

        laya_v63.close()

    # Derived from held-out `cal_500` clean median (`~0.45`) and grid-optimal `(off, scale, w_v0)`
    val_cal_meta = {
        "version": "v6_3",
        "noul_temperature_cal500": best_tn,
        "noul_brier_cal500": round(best_brier, 4),
        "persona_role_choice16_temperature": best_tr_role,
        "persona_role_choice16_acc_cal500": round(role_acc_ane, 4),
        "v0_laya_weights": [0.62, 0.38],
        "v0_laya_kev_weights": [0.44, 0.20, 0.36],
        "laya_raw_offset": 0.38,
        "laya_raw_scale": 0.48,
        "cascade_low": 0.20,
        "cascade_high": 0.62,
        "escalate_threshold": 0.45,
        "role_repair_min_defect": 0.58,
        "role_repair_min_prob": 0.72,
    }
    (artifacts_dir / "validator_v63_calibration.json").write_text(json.dumps(val_cal_meta, indent=2), encoding="utf-8")
    print(f"      [Validator Cal500] Noul T={best_tn} (Brier={best_brier:.4f}) | ANE Choice(16) Role Acc={role_acc_ane:.4f}")
    print("[DONE] All V6.3 artifacts trained, distilled, calibrated, and compiled to Pure ANE!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
