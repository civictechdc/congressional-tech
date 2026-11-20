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

Moved from fast-gemma4 `scripts/` (8edf64b). Run under the unified `fast-silicon` interpreter with this package on the path:
`PYTHONPATH=packages/congress_docmeta/src ../fast-silicon/.venv/bin/python packages/congress_docmeta/scripts/train_v63_validators.py`.
"""

from __future__ import annotations

import argparse
import collections
from contextlib import contextmanager
import ctypes
import fcntl
from functools import partial
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
from typing import Any, Iterator, Mapping, Sequence

import numpy as np

from congress_docmeta.atomic_validator_v6 import (
    AtomicOutputValidatorV6,
    laya_encode_ignore_truncation,
    resolve_docmeta_pkg_root,
    resolve_docmeta_validators_dir,
    write_validators_manifest,
)
from congress_docmeta.grammar_router_ane_v6 import (
    extract_router_sparse_features_v6,
    fuse_top6_router_probs,
)
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
    if os.environ.get("M4_GPU_LOCK_HELD") == "1":
        yield
        return
    HW_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(HW_LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o666)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()} {label} {time.time():.3f}\n".encode("utf-8"))
        prev = os.environ.get("M4_GPU_LOCK_HELD")
        os.environ["M4_GPU_LOCK_HELD"] = "1"
        try:
            yield
        finally:
            if prev is None:
                os.environ.pop("M4_GPU_LOCK_HELD", None)
            else:
                os.environ["M4_GPU_LOCK_HELD"] = prev
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
        "text_sha256": str(raw_row.get("text_sha256") or ""),
        "event_id": str(raw_row.get("event_id") or raw_row.get("rel_event_id") or ""),
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
    """Delegate to SSOT `extract_router_sparse_features_v6` while returning NumPy arrays."""
    idxs, vals = extract_router_sparse_features_v6(
        filename, known, raw_text, clean_text, dim=dim
    )
    if not idxs:
        return np.zeros((0,), dtype=np.int32), np.zeros((0,), dtype=np.float32)
    return np.asarray(idxs, dtype=np.int32), np.asarray(vals, dtype=np.float32)


def build_dense_feature_matrix(records: list[dict[str, Any]], dim: int = 12288) -> np.ndarray:
    X = np.zeros((len(records), dim), dtype=np.float32)
    for i, r in enumerate(records):
        idxs, vals = extract_router_sparse_features_v6(
            r["filename"], r["known"], r["p12_raw_text"], r["p12_clean_text"], dim=dim
        )
        if idxs:
            X[i, idxs] = vals
    return X


def _record_group_tokens(rec: Mapping[str, Any]) -> list[str]:
    """Extract deterministic duplicate-text and shared-hearing tokens for group splitting."""
    toks: list[str] = []
    sha = str(rec.get("text_sha256") or "").strip()
    if sha:
        toks.append(f"sha:{sha}")
    else:
        txt = str(rec.get("p12_clean_text") or rec.get("p12_raw_text") or "").strip()
        if len(txt) >= 40:
            norm_txt = re.sub(r"\s+", " ", txt).strip().lower()
            toks.append("txt:" + hashlib.sha1(norm_txt.encode("utf-8", errors="ignore")).hexdigest())

    ev_id = str(rec.get("event_id") or "").strip()
    if ev_id:
        toks.append(f"ev:{ev_id}")

    known_raw = str(rec.get("known") or "").strip()
    if known_raw and known_raw.startswith("{"):
        try:
            kd = json.loads(known_raw)
        except Exception:
            kd = None
        if isinstance(kd, Mapping):
            dt = str(kd.get("date") or "").strip()
            cmts = tuple(sorted(str(c).strip().lower() for c in (kd.get("cmt") or ()) if str(c).strip()))
            if dt and cmts:
                cong = kd.get("congress")
                toks.append(f"hk:{cong}|{'+'.join(cmts)}|{dt}")

    gold = rec.get("gold")
    if isinstance(gold, Mapping):
        edate = str(gold.get("event_date") or "").strip()
        cmts_g = tuple(sorted(str(c).strip().lower() for c in (gold.get("committees") or ()) if str(c).strip()))
        etitle = re.sub(r"\s+", " ", str(gold.get("event_title") or "").strip().lower())
        if edate and (cmts_g or etitle):
            toks.append(f"evg:{edate}|{'+'.join(cmts_g[:1])}|{etitle[:60]}")

    return toks


def assign_record_groups(records: Sequence[Mapping[str, Any]]) -> list[int]:
    """Connect records sharing identical text OR hearing/event keys via union-find."""
    n = len(records)
    parent = list(range(n))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: int, b: int) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    first_owner: dict[str, int] = {}
    for idx, rec in enumerate(records):
        for tok in _record_group_tokens(rec):
            prev = first_owner.get(tok)
            if prev is None:
                first_owner[tok] = idx
            else:
                _union(prev, idx)

    return [_find(i) for i in range(n)]


def split_records_grouped_stratified(
    all_records: Sequence[dict[str, Any]],
    *,
    target_cal: int = 560,
    seed: int = 20261116,
    min_train_per_class: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split records into disjoint `(train, cal)` keeping duplicate texts and hearings together.

    Every group stays wholly on one side. For any class with `<= 2` docs in `all_records`,
    all its docs stay in `train`, and every class retains at least `min_train_per_class` doc in
    `train`. Returns `(train_records, cal_records)` preserving input order within each side.
    """
    n = len(all_records)
    if n == 0:
        return [], []
    target_cal = max(0, min(target_cal, n))
    gids = assign_record_groups(all_records)

    cls_total: dict[str, int] = collections.Counter(str(r["router_class"]) for r in all_records)
    groups_map: dict[int, list[int]] = collections.defaultdict(list)
    for idx, g in enumerate(gids):
        groups_map[g].append(idx)

    group_cls_counts: dict[int, dict[str, int]] = {}
    group_primary: dict[int, str] = {}
    protected_groups: set[int] = set()
    for g, idxs in groups_map.items():
        cc = collections.Counter(str(all_records[i]["router_class"]) for i in idxs)
        group_cls_counts[g] = dict(cc)
        if any(cls_total[c] <= 2 for c in cc):
            protected_groups.add(g)
        group_primary[g] = min(cc.keys(), key=lambda c: (cls_total[c], c))

    by_primary: dict[str, list[int]] = collections.defaultdict(list)
    for g in sorted(groups_map):
        if g not in protected_groups:
            by_primary[group_primary[g]].append(g)

    rng = random.Random(seed)
    rem_train_by_cls = dict(cls_total)
    cal_groups: set[int] = set()
    cal_doc_count = 0

    def _can_move_to_cal(g: int) -> bool:
        return all(rem_train_by_cls[c] - cnt >= min_train_per_class for c, cnt in group_cls_counts[g].items())

    def _move_to_cal(g: int) -> None:
        nonlocal cal_doc_count
        cal_groups.add(g)
        cal_doc_count += len(groups_map[g])
        for c, cnt in group_cls_counts[g].items():
            rem_train_by_cls[c] -= cnt

    # Pass 1: proportional per-class allocation (rarest primary classes first)
    eligible_tail: list[int] = []
    for cls_k in sorted(by_primary, key=lambda c: (cls_total[c], c)):
        grp_list = list(by_primary[cls_k])
        rng.shuffle(grp_list)
        cls_target = max(1, int(round(cls_total[cls_k] * (target_cal / float(max(1, n))))))
        cls_moved = 0
        for g in grp_list:
            g_sz = len(groups_map[g])
            if cls_moved < cls_target and cal_doc_count + g_sz <= target_cal + 8 and _can_move_to_cal(g):
                _move_to_cal(g)
                cls_moved += cls_total[cls_k] if g_sz == 1 else group_cls_counts[g].get(cls_k, 1)
            else:
                eligible_tail.append(g)

    # Pass 2: top up cleanly to target_cal if rounding under-filled
    if cal_doc_count < target_cal and eligible_tail:
        rng.shuffle(eligible_tail)
        for g in eligible_tail:
            if g in cal_groups:
                continue
            g_sz = len(groups_map[g])
            if cal_doc_count + g_sz <= target_cal + 4 and _can_move_to_cal(g):
                _move_to_cal(g)
            if cal_doc_count >= target_cal:
                break

    train_records = [all_records[i] for i in range(n) if gids[i] not in cal_groups]
    cal_records = [all_records[i] for i in range(n) if gids[i] in cal_groups]
    return train_records, cal_records


def split_cal_records_disjoint(
    cal_records: Sequence[dict[str, Any]],
    *,
    early_stop_frac: float = 0.25,
    seed: int = 20261117,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split held-out `cal_records` into `(cal_thresh_records, early_stop_records)` by group."""
    n = len(cal_records)
    if n <= 1:
        return list(cal_records), list(cal_records)
    target_es = max(1, min(n - 1, int(round(n * early_stop_frac))))
    # Keep majority in cal_thresh_records (`train` side of the internal split) and ~25% in early_stop_records
    cal_thresh, early_stop = split_records_grouped_stratified(
        cal_records, target_cal=target_es, seed=seed, min_train_per_class=1
    )
    if not early_stop:
        gids = assign_record_groups(cal_records)
        uniq_g = sorted(set(gids))
        if len(uniq_g) >= 2:
            pick_g = uniq_g[0]
            cal_thresh = [cal_records[i] for i in range(n) if gids[i] != pick_g]
            early_stop = [cal_records[i] for i in range(n) if gids[i] == pick_g]
        else:
            early_stop = list(cal_thresh)
    return cal_thresh, early_stop


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


def _longest_common_prefix_len(seqs: Sequence[Sequence[int]]) -> int:
    """Return exact token-level longest common prefix length across non-empty sequences."""
    if not seqs:
        return 0
    first = seqs[0]
    lim = min(len(s) for s in seqs)
    lcp = 0
    while lcp < lim:
        tok = first[lcp]
        if any(s[lcp] != tok for s in seqs[1:]):
            break
        lcp += 1
    return lcp


def score_kev_teacher_jobs_with_prefix_reuse(
    kev_teacher: Any,
    kev_jobs: Sequence[tuple[int, dict[str, Any], list[dict[str, Any]], list[int]]],
    *,
    batch_docs: int | None = None,
) -> tuple[list[list[tuple[float, list[float]]]], dict[str, int]]:
    """Score `Kev-0.8B` teacher jobs grouped by source document, reusing shared document prefix KV + GDN state.

    Each `kev_jobs` entry is `(doc_idx, state_dict, questions, item_indices)`. Because clean and
    corrupted candidate states for the same document share `filename`, `known_metadata`, and
    `document_excerpt` (~80–85% of state tokens), we compute their exact token-level LCP once per
    document, prefill that shared prefix ONCE (`write_state=True`), and score every candidate's
    short `candidate_extraction` suffix + question branch via zero-GDN-clone `owner_idx`
    (`write_state=False`). Falls back cleanly to state-deduplicated `score_multi_states_noul`
    when `kev_teacher` is a mock or does not expose the MLX backbone.
    """
    n_jobs = len(kev_jobs)
    outs_per_job: list[list[tuple[float, list[float]]]] = [
        [(0.5, [0.0, 0.0]) for _ in qs_k] for (_di, _st_k, qs_k, _idxs) in kev_jobs
    ]
    stats: dict[str, int] = {
        "unique_docs": 0,
        "total_jobs": n_jobs,
        "total_branches": sum(len(qs_k) for (_di, _st_k, qs_k, _idxs) in kev_jobs),
        "prefix_groups": 0,
        "naive_state_tokens": 0,
        "shared_prefix_tokens": 0,
        "suffix_tokens": 0,
        "used_prefix_reuse": 0,
    }
    if not kev_jobs:
        return outs_per_job, stats

    by_doc: dict[int, list[int]] = collections.OrderedDict()
    for job_idx, (doc_idx, _st_k, _qs_k, _idxs) in enumerate(kev_jobs):
        by_doc.setdefault(int(doc_idx), []).append(job_idx)
    stats["unique_docs"] = len(by_doc)

    supports_backbone = (
        getattr(kev_teacher, "backbone", None) is not None
        and all(
            hasattr(kev_teacher, attr)
            for attr in ("encode_questions", "_pointer_logits_and_probs", "_mx", "pad_id", "batch_docs", "max_branch_batch")
        )
    )
    if not supports_backbone:
        # Deduplicate identical states within each doc while preserving exact fallback order.
        dedup_batch: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        dedup_map: list[list[tuple[int, int]]] = []
        for _doc_idx, job_indices in by_doc.items():
            state_buckets: dict[str, tuple[dict[str, Any], list[dict[str, Any]], list[tuple[int, int]]]] = {}
            for j_idx in job_indices:
                _di, st_k, qs_k, _idxs = kev_jobs[j_idx]
                if not qs_k:
                    continue
                skey = json.dumps(st_k, sort_keys=True, ensure_ascii=False)
                if skey not in state_buckets:
                    state_buckets[skey] = (st_k, [], [])
                _, q_acc, m_acc = state_buckets[skey]
                for q_pos, q in enumerate(qs_k):
                    q_acc.append(q)
                    m_acc.append((j_idx, q_pos))
            for st_u, qs_u, map_u in state_buckets.values():
                dedup_batch.append((st_u, qs_u))
                dedup_map.append(map_u)
        stats["prefix_groups"] = len(dedup_batch)
        if dedup_batch:
            raw_outs = kev_teacher.score_multi_states_noul(dedup_batch, batch_docs=batch_docs)
            for map_u, out_u in zip(dedup_map, raw_outs):
                for (j_idx, q_pos), res_item in zip(map_u, out_u):
                    outs_per_job[j_idx][q_pos] = (float(res_item[0]), list(res_item[1]))
        return outs_per_job, stats

    from fast_decision_models.kev_mlx import _build_branch_attn_mask, _build_state_attn_mask

    mx = kev_teacher._mx
    backbone = kev_teacher.backbone
    pad_id = int(kev_teacher.pad_id)
    eff_b = max(1, int(batch_docs or kev_teacher.batch_docs))
    br_chunk_lim = max(eff_b, int(kev_teacher.max_branch_batch))
    stats["used_prefix_reuse"] = 1

    # Build prefix groups (one shared document prefix per doc_idx whenever token LCP >= 4).
    # Each group is `(prefix_ids, branch_rows)` where each branch is
    # `{"ids": suffix + q_ids, "decide": int, "opts": list[int], "job_idx": int, "q_pos": int}`.
    prefix_groups: list[tuple[list[int], list[dict[str, Any]]]] = []
    for _doc_idx, job_indices in by_doc.items():
        encoded_jobs: list[tuple[int, list[int], list[dict[str, Any]]]] = []
        for j_idx in job_indices:
            _di, st_k, qs_k, _idxs = kev_jobs[j_idx]
            if not qs_k:
                continue
            st_ids, rows_k = kev_teacher.encode_questions(st_k, qs_k)
            stats["naive_state_tokens"] += len(st_ids)
            encoded_jobs.append((j_idx, st_ids, rows_k))
        if not encoded_jobs:
            continue

        prefix_clusters: list[list[tuple[int, list[int], list[dict[str, Any]]]]] = []
        for job_tup in encoded_jobs:
            _ji, st_ids, _rq = job_tup
            placed = False
            for cl in prefix_clusters:
                if _longest_common_prefix_len([cl[0][1], st_ids]) >= 16:
                    cl.append(job_tup)
                    placed = True
                    break
            if not placed:
                prefix_clusters.append([job_tup])

        for cl_jobs in prefix_clusters:
            lcp = _longest_common_prefix_len([st_ids for _, st_ids, _ in cl_jobs])
            if lcp >= 4:
                prefix_ids = cl_jobs[0][1][:lcp]
                doc_branches: list[dict[str, Any]] = []
                for j_idx, st_ids, rows_k in cl_jobs:
                    suffix_ids = st_ids[lcp:]
                    suf_len = len(suffix_ids)
                    stats["suffix_tokens"] += suf_len
                    for q_pos, r_q in enumerate(rows_k):
                        doc_branches.append(
                            {
                                "ids": suffix_ids + list(r_q["ids"]),
                                "decide": suf_len + int(r_q["decide"]),
                                "opts": [suf_len + int(o) for o in r_q["opts"]],
                                "job_idx": j_idx,
                                "q_pos": q_pos,
                            }
                        )
                stats["shared_prefix_tokens"] += len(prefix_ids)
                prefix_groups.append((prefix_ids, doc_branches))
            else:
                for j_idx, st_ids, rows_k in cl_jobs:
                    stats["shared_prefix_tokens"] += len(st_ids)
                    solo_branches = [
                        {
                            "ids": list(r_q["ids"]),
                            "decide": int(r_q["decide"]),
                            "opts": [int(o) for o in r_q["opts"]],
                            "job_idx": j_idx,
                            "q_pos": q_pos,
                        }
                        for q_pos, r_q in enumerate(rows_k)
                    ]
                    prefix_groups.append((st_ids, solo_branches))

    stats["prefix_groups"] = len(prefix_groups)
    order = sorted(range(len(prefix_groups)), key=lambda idx: len(prefix_groups[idx][0]))

    for wave_start in range(0, len(order), eff_b):
        wave_idxs = order[wave_start : wave_start + eff_b]
        B = len(wave_idxs)
        prefixes = [prefix_groups[gi][0] for gi in wave_idxs]
        p_lens = [len(p) for p in prefixes]
        p_max = max(p_lens)
        pad_lens = [p_max - ln for ln in p_lens]
        all_unpadded = all(pl == 0 for pl in pad_lens)

        st_np = np.full((B, p_max), pad_id, dtype=np.int32)
        for b_i in range(B):
            pl = pad_lens[b_i]
            st_np[b_i, pl:] = prefixes[b_i]

        if all_unpadded:
            valid_scale_mx = None
            pos_st_mx = None
            mask_st_mx: Any = "causal"
        else:
            pl_mx = mx.array(pad_lens, dtype=mx.int32)[:, None]
            seq_pos = mx.arange(p_max, dtype=mx.int32)[None, :]
            valid_scale_mx = mx.where(
                seq_pos >= pl_mx,
                mx.array(1.0, dtype=mx.bfloat16),
                mx.array(0.0, dtype=mx.bfloat16),
            )[:, :, None]
            pos_st_mx = mx.maximum(seq_pos - pl_mx, 0)
            mask_st_mx = _build_state_attn_mask(mx, pad_lens, p_max, mx.bfloat16)

        cache = backbone.make_cache()
        h_st = backbone(
            mx.array(st_np, dtype=mx.int32),
            cache,
            valid_token_scale=valid_scale_mx,
            attn_mask=mask_st_mx,
            pos_2d=pos_st_mx,
            write_state=True,
        )
        mx.eval(h_st)

        # Sort wave branches by length so right-padding inside each branch chunk is minimized.
        wave_branches: list[tuple[int, dict[str, Any]]] = []
        for b_i, gi in enumerate(wave_idxs):
            for br in prefix_groups[gi][1]:
                wave_branches.append((b_i, br))
        wave_branches.sort(key=lambda pair: len(pair[1]["ids"]))

        n_br = len(wave_branches)
        for c0 in range(0, n_br, br_chunk_lim):
            sub_pairs = wave_branches[c0 : min(n_br, c0 + br_chunk_lim)]
            sub_owner = [p[0] for p in sub_pairs]
            sub_rows = [p[1] for p in sub_pairs]
            n_sub = len(sub_rows)
            max_br = max(len(r["ids"]) for r in sub_rows)
            br_np = np.full((n_sub, max_br), pad_id, dtype=np.int32)
            for r_i, r in enumerate(sub_rows):
                bl = len(r["ids"])
                br_np[r_i, :bl] = r["ids"]

            sub_pads = [pad_lens[b_i] for b_i in sub_owner]
            sub_plens = [p_lens[b_i] for b_i in sub_owner]
            sub_unpadded = all(pl == 0 for pl in sub_pads)
            if sub_unpadded:
                pos_br_mx = None
                mask_br_mx: Any = "causal"
            else:
                pos_br_mx = (
                    mx.array(sub_plens, dtype=mx.int32)[:, None]
                    + mx.arange(max_br, dtype=mx.int32)[None, :]
                )
                mask_br_mx = _build_branch_attn_mask(mx, sub_pads, p_max, max_br, mx.bfloat16)

            owner_is_identity = (n_sub == B) and (sub_owner == list(range(B)))
            owner_mx = mx.array(sub_owner, dtype=mx.int32)
            h_br = backbone(
                mx.array(br_np, dtype=mx.int32),
                cache,
                valid_token_scale=None,
                attn_mask=mask_br_mx,
                pos_2d=pos_br_mx,
                owner_idx=owner_mx,
                owner_is_identity=owner_is_identity,
                write_state=False,
            )
            mx.eval(h_br)
            h_br_np = np.asarray(h_br.astype(mx.float32))
            for ri, br in enumerate(sub_rows):
                probs, raw_z = kev_teacher._pointer_logits_and_probs(
                    h_br_np[ri], br["decide"], br["opts"]
                )
                p1 = probs[1] if len(probs) >= 2 else probs[0]
                outs_per_job[br["job_idx"]][br["q_pos"]] = (float(p1), raw_z)

        del cache, h_st
        maybe_clear = getattr(kev_teacher, "_maybe_clear_wave_cache", None)
        if callable(maybe_clear):
            maybe_clear()

    return outs_per_job, stats


def synthesize_training_examples(
    train_records: list[dict[str, Any]],
    oof_top6_by_idx: list[list[str]],
    laya_tok_helper: LayaAneBackend,
    kev_teacher: Kev08bMlxBackend | None,
    *,
    distill_docs: int = 360,
    seed: int = 20261116,
    reuse_doc_prefix: bool = True,
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
        enc_r = laya_encode_ignore_truncation(laya_tok_helper, r_state, r_q)
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
            enc_q = laya_encode_ignore_truncation(laya_tok_helper, st_clean, q)
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
        corrupt_qs_pick: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []

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

        # 3d. Genre-conditional `q4` & omission `q5` corruptions (independent `if`s for multi-field docs)
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
        if gold.get("correspondence_flow"):
            bad_cf_doc = json.loads(json.dumps(gold))
            bad_cf_doc.pop("disclosure", None)
            bad_cf_doc.pop("action_summary", None)
            if bad_cf_doc.get("primary_kind") in (
                "truth_in_testimony_disclosure",
                "committee_vote",
                "meeting_results",
                "revenue_or_cost_estimate",
            ):
                bad_cf_doc["primary_kind"] = "oversight_letter"
            cf_orig = str(gold["correspondence_flow"])
            alt_cfs = [c for c in ALL_CFLOWS if c != cf_orig]
            bad_cf_doc["correspondence_flow"] = rng.choice(alt_cfs)
            st_bcf, qs_bcf = build_atomic_doc_questions_v6(
                bad_cf_doc, rec, head_chars=950, tail_chars=350, include_genre_check=True
            )
            for qx in qs_bcf:
                if qx.get("field") == "correspondence_flow":
                    corrupt_qs_pick.append((st_bcf, bad_cf_doc, qx))
        if pk in ("committee_vote", "meeting_results") or gold.get("action_summary"):
            bad_act_doc = json.loads(json.dumps(gold))
            bad_act_doc.pop("disclosure", None)
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
            enc_c = laya_encode_ignore_truncation(laya_tok_helper, st_c, q_c)
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
            enc_pp = laya_encode_ignore_truncation(laya_tok_helper, pst_pos, pq_pos)
            pp_idx = len(items)
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
            if i in distill_set and kev_teacher is not None:
                kev_jobs.append((i, pst_pos, [pq_pos], [pp_idx]))
            # 4b. Persona `Choice(16)` Role Classification
            pst_rc, pq_rc = build_persona_role_choice_item(gold, rec, px)
            enc_rc = laya_encode_ignore_truncation(laya_tok_helper, pst_rc, pq_rc)
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
            enc_pn = laya_encode_ignore_truncation(laya_tok_helper, pst_neg, pq_neg)
            pn_idx = len(items)
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
            if i in distill_set and kev_teacher is not None:
                kev_jobs.append((i, pst_neg, [pq_neg], [pn_idx]))

    if kev_teacher is not None and kev_jobs:
        t0 = time.perf_counter()
        if reuse_doc_prefix:
            print(f"[DISTILL] Scoring {len(kev_jobs)} state jobs with W8 Kev-0.8B teacher (doc prefix reuse)...")
            outs, kev_stats = score_kev_teacher_jobs_with_prefix_reuse(kev_teacher, kev_jobs)
            naive_toks = max(1, kev_stats["naive_state_tokens"])
            kept_toks = kev_stats["shared_prefix_tokens"] + kev_stats["suffix_tokens"]
            saved_pct = 100.0 * (1.0 - kept_toks / float(naive_toks)) if kev_stats["used_prefix_reuse"] else 0.0
            print(
                f"[DISTILL] Kev-0.8B prefix reuse: {kev_stats['unique_docs']} docs / {kev_stats['total_jobs']} jobs "
                f"({kev_stats['prefix_groups']} prefix prefills, state tokens {kev_stats['naive_state_tokens']} -> "
                f"{kept_toks} = -{saved_pct:.1f}%) in {time.perf_counter() - t0:.1f}s."
            )
        else:
            print(f"[DISTILL] Scoring {len(kev_jobs)} state batches with W8 Kev-0.8B teacher (naive)...")
            batch_in = [(st_k, qs_k) for (_di, st_k, qs_k, _idxs) in kev_jobs]
            outs = kev_teacher.score_multi_states_noul(batch_in)
            print(f"[DISTILL] Kev-0.8B teacher labeling finished in {time.perf_counter() - t0:.1f}s.")
        for (_di, _st_k, _qs_k, item_idxs), out_list in zip(kev_jobs, outs):
            for it_idx, (p1_val, _rz) in zip(item_idxs, out_list):
                items[it_idx]["soft_p1"] = float(p1_val)

    return items


def pack_validator_items(
    items: Sequence[Mapping[str, Any]],
    *,
    pack_tokens: int,
    max_item_len: int = 512,
    item_indices: Sequence[int] | None = None,
    window_size: int = 64,
    seed: int | None = None,
    shuffle: bool = False,
) -> list[list[tuple[int, Mapping[str, Any]]]]:
    """Pack variable-length validator items into fixed-capacity `pack_tokens` bins via windowed FFD.

    Preserves each item's original dataset index `orig_idx` and clamps per-item length to
    `min(pack_tokens, max_item_len)` so packed batches compose safely with `FrozenTrunkActivationCache`
    and `S <= 512` ANE buckets. Items with `< 2` valid markers within the clamped length are skipped.
    """
    cap = int(pack_tokens)
    if cap <= 0:
        raise ValueError(f"pack_tokens must be positive, got {pack_tokens}")
    item_cap = int(max_item_len)
    if item_cap <= 0:
        raise ValueError(f"max_item_len must be positive, got {max_item_len}")

    indexed: list[tuple[int, Mapping[str, Any], int]] = []
    for pos, it in enumerate(items):
        orig_idx = int(item_indices[pos]) if item_indices is not None else pos
        ln = min(cap, item_cap, len(it["ids"]))
        if ln <= 0:
            continue
        valid_mks = [m for m in it["markers"] if m < ln]
        if len(valid_mks) < 2:
            continue
        indexed.append((orig_idx, it, ln))

    if not indexed:
        return []

    if shuffle:
        rng = random.Random(seed)
        rng.shuffle(indexed)

    win = len(indexed) if (not shuffle or window_size <= 0) else max(1, int(window_size))
    all_bins: list[list[tuple[int, Mapping[str, Any]]]] = []
    for w0 in range(0, len(indexed), win):
        chunk = sorted(indexed[w0 : w0 + win], key=lambda rec: rec[2], reverse=True)
        bin_items: list[list[tuple[int, Mapping[str, Any]]]] = []
        bin_used: list[int] = []
        for orig_idx, it, ln in chunk:
            placed = False
            for bi in range(len(bin_used)):
                if bin_used[bi] + ln <= cap:
                    bin_items[bi].append((orig_idx, it))
                    bin_used[bi] += ln
                    placed = True
                    break
            if not placed:
                bin_items.append([(orig_idx, it)])
                bin_used.append(ln)
        all_bins.extend(bin_items)

    if shuffle:
        rng_b = random.Random(None if seed is None else int(seed) ^ 0x9E3779B9)
        rng_b.shuffle(all_bins)
    return all_bins


def compute_packing_stats(
    bins: Sequence[Sequence[tuple[int, Mapping[str, Any]]]],
    pack_tokens: int,
    *,
    max_item_len: int = 512,
) -> dict[str, float | int]:
    """Return bin count, packed item count, real token utilization, and pad fraction."""
    cap = int(pack_tokens)
    item_cap = int(max_item_len)
    n_bins = len(bins)
    n_items = sum(len(b) for b in bins)
    real_toks = sum(min(cap, item_cap, len(it["ids"])) for b in bins for (_oi, it) in b)
    total_toks = n_bins * cap
    util = float(real_toks) / float(total_toks) if total_toks > 0 else 0.0
    return {
        "num_bins": n_bins,
        "num_items": n_items,
        "real_tokens": real_toks,
        "total_tokens": total_toks,
        "utilization": round(util, 4),
        "pad_fraction": round(1.0 - util, 4) if total_toks > 0 else 0.0,
    }


def build_packed_batch(
    bins: Sequence[Sequence[tuple[int, Mapping[str, Any]]]],
    *,
    pack_tokens: int,
    pad_id: int = 50283,
    k_max: int = 16,
    max_item_len: int = 512,
) -> dict[str, Any]:
    """Materialize packed bins into fixed-shape `[B_bins, pack_tokens]` arrays with per-segment RoPE & masks."""
    S_pack = int(pack_tokens)
    item_cap = int(max_item_len)
    if item_cap <= 0:
        raise ValueError(f"max_item_len must be positive, got {max_item_len}")
    B_bins = len(bins)
    if B_bins == 0:
        raise ValueError("build_packed_batch requires at least one bin")

    ids_np = np.full((B_bins, S_pack), int(pad_id), dtype=np.int32)
    pos_np = np.zeros((B_bins, S_pack), dtype=np.int32)
    seg_np = np.zeros((B_bins, S_pack), dtype=np.int32)
    tok_qt_np = np.zeros((B_bins, S_pack), dtype=np.int32)

    flat_mk_list: list[list[int]] = []
    mkv_list: list[list[bool]] = []
    tgt_list: list[int] = []
    sp1_list: list[float] = []
    hsp_list: list[bool] = []
    invt_list: list[float] = []
    item_spans: list[tuple[int, int, int, int]] = []
    real_tokens = 0

    for bi, bin_entries in enumerate(bins):
        cursor = 0
        seg_num = 0
        for orig_idx, it in bin_entries:
            ln = min(S_pack - cursor, item_cap, len(it["ids"]))
            if ln <= 0:
                continue
            mks = [m for m in it["markers"] if m < ln][:k_max]
            k_i = len(mks)
            if k_i < 2:
                continue
            seg_num += 1
            ids_np[bi, cursor : cursor + ln] = it["ids"][:ln]
            pos_np[bi, cursor : cursor + ln] = np.arange(ln, dtype=np.int32)
            seg_np[bi, cursor : cursor + ln] = seg_num
            qt_val = int(it["qtype"])
            tok_qt_np[bi, cursor : cursor + ln] = qt_val

            base_flat = bi * S_pack + cursor
            mk_row = [0] * k_max
            mkv_row = [False] * k_max
            for j, local_m in enumerate(mks):
                mk_row[j] = base_flat + int(local_m)
                mkv_row[j] = True
            flat_mk_list.append(mk_row)
            mkv_list.append(mkv_row)
            tgt_list.append(min(int(it["target"]), k_i - 1))
            if qt_val == 2:
                invt_list.append(1.0 / 1.5)
                if it.get("soft_p1") is not None:
                    sp1_list.append(float(it["soft_p1"]))
                    hsp_list.append(True)
                else:
                    sp1_list.append(0.5)
                    hsp_list.append(False)
            else:
                invt_list.append(1.0)
                sp1_list.append(0.5)
                hsp_list.append(False)

            item_spans.append((int(orig_idx), bi, cursor, ln))
            cursor += ln
            real_tokens += ln

    n_items = len(tgt_list)
    if n_items == 0:
        raise ValueError("build_packed_batch found 0 valid items with >= 2 markers")

    return {
        "packed": True,
        "ids": ids_np,
        "valid_lens": None,
        "qtypes": None,
        "pos_ids": pos_np,
        "seg_ids": seg_np,
        "token_qtypes": tok_qt_np,
        "flat_mk_idx": np.asarray(flat_mk_list, dtype=np.int32),
        "mk_valid": np.asarray(mkv_list, dtype=bool),
        "targets": np.asarray(tgt_list, dtype=np.int32),
        "soft_p1": np.asarray(sp1_list, dtype=np.float32),
        "has_soft": np.asarray(hsp_list, dtype=bool),
        "inv_temp": np.asarray(invt_list, dtype=np.float32),
        "item_valid": np.ones((n_items,), dtype=bool),
        "item_spans": item_spans,
        "num_items": n_items,
        "real_tokens": real_tokens,
        "total_tokens": B_bins * S_pack,
    }


def build_unpacked_batch(
    items: Sequence[Mapping[str, Any]],
    *,
    seq_len: int | None = None,
    pad_id: int = 50283,
    k_max: int = 16,
    item_indices: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Materialize unpacked validator items into standard `[B, S_b]` arrays sharing the unified loss schema."""
    B = len(items)
    if B == 0:
        raise ValueError("build_unpacked_batch requires at least one item")
    if seq_len is None:
        max_len = min(512, max(len(it["ids"]) for it in items))
        S_b = 256 if max_len <= 256 else 512
    else:
        S_b = int(seq_len)

    ids_np = np.full((B, S_b), int(pad_id), dtype=np.int32)
    vl_np = np.zeros((B,), dtype=np.int32)
    qt_np = np.zeros((B,), dtype=np.int32)
    flat_mk_np = np.zeros((B, k_max), dtype=np.int32)
    mkv_np = np.zeros((B, k_max), dtype=bool)
    tgt_np = np.zeros((B,), dtype=np.int32)
    sp1_np = np.full((B,), 0.5, dtype=np.float32)
    hsp_np = np.zeros((B,), dtype=bool)
    invt_np = np.ones((B,), dtype=np.float32)
    item_valid_np = np.zeros((B,), dtype=bool)
    item_spans: list[tuple[int, int, int, int]] = []
    real_tokens = 0

    for bi, it in enumerate(items):
        orig_idx = int(item_indices[bi]) if item_indices is not None else bi
        ln = min(S_b, len(it["ids"]))
        ids_np[bi, :ln] = it["ids"][:ln]
        vl_np[bi] = max(1, ln)
        qt_val = int(it["qtype"])
        qt_np[bi] = qt_val
        mks = [m for m in it["markers"] if m < ln][:k_max]
        k_i = len(mks)
        base_flat = bi * S_b
        if k_i >= 2:
            for j, local_m in enumerate(mks):
                flat_mk_np[bi, j] = base_flat + int(local_m)
                mkv_np[bi, j] = True
            tgt_np[bi] = min(int(it["target"]), k_i - 1)
            item_valid_np[bi] = True
        else:
            # Keep dummy slot finite so autograd never encounters 0 * NaN.
            flat_mk_np[bi, 0] = base_flat
            flat_mk_np[bi, 1] = base_flat
            mkv_np[bi, 0] = True
            mkv_np[bi, 1] = True
            tgt_np[bi] = 0
            item_valid_np[bi] = False

        if qt_val == 2:
            invt_np[bi] = 1.0 / 1.5
            if it.get("soft_p1") is not None:
                sp1_np[bi] = float(it["soft_p1"])
                hsp_np[bi] = True
        else:
            invt_np[bi] = 1.0

        item_spans.append((orig_idx, bi, 0, ln))
        real_tokens += ln

    return {
        "packed": False,
        "ids": ids_np,
        "valid_lens": vl_np,
        "qtypes": qt_np,
        "pos_ids": None,
        "seg_ids": None,
        "token_qtypes": None,
        "flat_mk_idx": flat_mk_np,
        "mk_valid": mkv_np,
        "targets": tgt_np,
        "soft_p1": sp1_np,
        "has_soft": hsp_np,
        "inv_temp": invt_np,
        "item_valid": item_valid_np,
        "item_spans": item_spans,
        "num_items": int(np.sum(item_valid_np)),
        "real_tokens": real_tokens,
        "total_tokens": B * S_b,
    }


class LayaMlxModel:
    """MLX `Laya-Typed-421M` ModernBERT + 2-layer Head + Scorer with BF16 head, varlen packing & frozen trunk split.

    Fixes Audit P0.1 (no FP32 SDPA spill in `head.layers.{0,1}`), P0.2 (frozen trunk weights & RoPE/SWA
    tables pre-cast ONCE to `mx.bfloat16` at init, `@mx.compile` fused elementwise ops & pointer loss),
    P1.5 (varlen packing with per-segment RoPE position reset and block-diagonal segment masks), and
    P2.8 (clean frozen `L0..freeze_below_layer-1` boundary split outside autograd).
    """

    def __init__(
        self,
        raw_weights: Mapping[str, Any],
        enc_cfg: Mapping[str, Any],
        *,
        freeze_below_layer: int = 18,
        max_pos_len: int = 512,
    ) -> None:
        import mlx.core as mx
        import mlx.nn as nn

        self._mx = mx
        self._nn = nn
        self.enc_cfg = dict(enc_cfg)
        self.hidden_size = int(enc_cfg["hidden_size"])
        self.n_layers = int(enc_cfg["num_hidden_layers"])
        self.n_heads = int(enc_cfg["num_attention_heads"])
        self.head_dim = self.hidden_size // self.n_heads
        self.attn_scale = 1.0 / math.sqrt(self.head_dim)
        self.layer_types = list(enc_cfg["layer_types"])
        self.local_window = int(enc_cfg.get("local_attention", 128))
        self.half_local_window = self.local_window // 2
        self.norm_eps = float(enc_cfg.get("norm_eps", enc_cfg.get("layer_norm_eps", 1e-5)))
        self.freeze_below_layer = max(0, min(int(freeze_below_layer), self.n_layers))

        rope_params = enc_cfg.get("rope_parameters", {})
        self.theta_full = float(rope_params.get("full_attention", {}).get("rope_theta", 160000.0))
        self.theta_swa = float(rope_params.get("sliding_attention", {}).get("rope_theta", 10000.0))

        self._max_pos_len = max(1024, int(max_pos_len))
        self._swa_max_len = max(512, int(max_pos_len))
        self._cos_full, self._sin_full = self._build_rope_tables_bf16(self._max_pos_len, self.theta_full)
        self._cos_swa, self._sin_swa = self._build_rope_tables_bf16(self._max_pos_len, self.theta_swa)
        self._swa_bias_bf16 = self._build_swa_bias_bf16(self._swa_max_len)

        # Pre-cast ALL frozen weights (`0..freeze_below_layer-1`) to `mx.bfloat16` ONCE at initialization.
        # Keep trainable master weights (`freeze_below_layer..27` + head + scorer) in `mx.float32` for AdamW.
        self.frozen: dict[str, Any] = {}
        self.trainable: dict[str, Any] = {}
        for k, v in raw_weights.items():
            is_train = False
            if k.startswith(("head.", "scorer.", "type_emb.", "encoder.final_norm.")):
                is_train = True
            elif k.startswith("encoder.layers."):
                li = int(k.split(".")[2])
                if li >= self.freeze_below_layer:
                    is_train = True
            if is_train:
                self.trainable[k] = v.astype(mx.float32)
            else:
                self.frozen[k] = v.astype(mx.bfloat16)

        self._emb_w = self.frozen["encoder.embeddings.tok_embeddings.weight"]
        self._emb_norm_w = self.frozen["encoder.embeddings.norm.weight"]
        self._frozen_layers: list[tuple[bool, Any, Any, Any, Any, Any, Any]] = []
        for i in range(self.freeze_below_layer):
            px = f"encoder.layers.{i}."
            self._frozen_layers.append(
                (
                    self.layer_types[i] == "full_attention",
                    None if i == 0 else self.frozen[px + "attn_norm.weight"],
                    self.frozen[px + "attn.Wqkv.weight"],
                    self.frozen[px + "attn.Wo.weight"],
                    self.frozen[px + "mlp_norm.weight"],
                    self.frozen[px + "mlp.Wi.weight"],
                    self.frozen[px + "mlp.Wo.weight"],
                )
            )

        @partial(mx.compile, shapeless=True)
        def _compiled_geglu(val_h: Any, gate_h: Any) -> Any:
            return nn.gelu(val_h) * gate_h

        @partial(mx.compile, shapeless=True)
        def _compiled_rope_pair(x0: Any, x1: Any, cos_a: Any, sin_a: Any) -> tuple[Any, Any]:
            return x0 * cos_a - x1 * sin_a, x1 * cos_a + x0 * sin_a

        @partial(mx.compile, shapeless=True)
        def _compiled_relu_bias(x: Any, b: Any) -> Any:
            return nn.relu(x + b)

        @partial(mx.compile, shapeless=True)
        def _compiled_gelu_bias(x: Any, b: Any) -> Any:
            return nn.gelu(x + b)

        @partial(mx.compile, shapeless=True)
        def _compiled_pointer_loss(
            pos_logits: Any,
            flat_mk_idx: Any,
            mk_valid: Any,
            targets: Any,
            soft_p1: Any,
            has_soft: Any,
            inv_temp: Any,
            item_valid: Any,
        ) -> Any:
            flat_logits = pos_logits.reshape(-1)
            gathered = mx.take(flat_logits, flat_mk_idx, axis=0)
            scaled = gathered * inv_temp[:, None]
            masked = mx.where(mk_valid, scaled, mx.array(-1e9, dtype=mx.float32))
            lse = mx.logsumexp(masked, axis=-1)
            log_probs = masked - lse[:, None]
            gold_nll = -mx.take_along_axis(log_probs, targets[:, None], axis=-1).squeeze(-1)
            lp0 = log_probs[:, 0]
            lp1 = log_probs[:, 1]
            kl_soft = -((mx.array(1.0, dtype=mx.float32) - soft_p1) * lp0 + soft_p1 * lp1)
            combined = mx.where(
                has_soft,
                mx.array(0.65, dtype=mx.float32) * gold_nll + mx.array(0.35, dtype=mx.float32) * kl_soft,
                gold_nll,
            )
            valid_f = item_valid.astype(mx.float32)
            return mx.sum(combined * valid_f) / mx.maximum(mx.sum(valid_f), mx.array(1.0, dtype=mx.float32))

        self._geglu = _compiled_geglu
        self._rope_pair = _compiled_rope_pair
        self._relu_bias = _compiled_relu_bias
        self._gelu_bias = _compiled_gelu_bias
        self._pointer_loss = _compiled_pointer_loss

        mx.eval(
            self.frozen,
            self.trainable,
            self._cos_full,
            self._sin_full,
            self._cos_swa,
            self._sin_swa,
            self._swa_bias_bf16,
        )

    def _build_rope_tables_bf16(self, max_s: int, theta: float) -> tuple[Any, Any]:
        mx = self._mx
        half = self.head_dim // 2
        inv_freq = 1.0 / (theta ** (np.arange(half, dtype=np.float64) / half))
        angles = np.arange(max_s, dtype=np.float64)[:, None] * inv_freq[None, :]
        cos = mx.array(np.cos(angles).astype(np.float32)).astype(mx.bfloat16)
        sin = mx.array(np.sin(angles).astype(np.float32)).astype(mx.bfloat16)
        return cos, sin

    def _build_swa_bias_bf16(self, max_s: int) -> Any:
        mx = self._mx
        idx_s = np.arange(max_s, dtype=np.int32)
        swa_allow = np.abs(idx_s[:, None] - idx_s[None, :]) <= self.half_local_window
        return mx.array(np.where(swa_allow, 0.0, -10000.0).astype(np.float32)[None, None, :, :]).astype(mx.bfloat16)

    def _ensure_pos_capacity(self, needed: int, *, need_swa_bias: bool = False) -> None:
        eval_list: list[Any] = []
        if needed > self._max_pos_len:
            self._max_pos_len = int(needed)
            self._cos_full, self._sin_full = self._build_rope_tables_bf16(self._max_pos_len, self.theta_full)
            self._cos_swa, self._sin_swa = self._build_rope_tables_bf16(self._max_pos_len, self.theta_swa)
            eval_list.extend([self._cos_full, self._sin_full, self._cos_swa, self._sin_swa])
        if need_swa_bias and needed > self._swa_max_len:
            self._swa_max_len = int(needed)
            self._swa_bias_bf16 = self._build_swa_bias_bf16(self._swa_max_len)
            eval_list.append(self._swa_bias_bf16)
        if eval_list:
            self._mx.eval(*eval_list)

    def _ln_nobias(self, x: Any, w: Any) -> Any:
        return self._mx.fast.layer_norm(x, w, None, self.norm_eps)

    def _ln_bias(self, x: Any, w: Any, b: Any) -> Any:
        return self._mx.fast.layer_norm(x, w, b, self.norm_eps)

    def _apply_rope(self, x: Any, cos_a: Any, sin_a: Any) -> Any:
        x0, x1 = self._mx.split(x, 2, axis=-1)
        y0, y1 = self._rope_pair(x0, x1, cos_a, sin_a)
        return self._mx.concatenate([y0, y1], axis=-1)

    def prepare_rope(self, seq_len: int, pos_ids: Any | None = None) -> tuple[Any, Any, Any, Any]:
        """Precompute `[B|1, 1, S, hd/2]` BF16 RoPE `(cos_full, sin_full, cos_swa, sin_swa)` once per forward."""
        mx = self._mx
        if seq_len > self._max_pos_len:
            self._ensure_pos_capacity(seq_len)
        if pos_ids is None:
            return (
                self._cos_full[:seq_len][None, None, :, :],
                self._sin_full[:seq_len][None, None, :, :],
                self._cos_swa[:seq_len][None, None, :, :],
                self._sin_swa[:seq_len][None, None, :, :],
            )
        return (
            mx.take(self._cos_full, pos_ids, axis=0)[:, None, :, :],
            mx.take(self._sin_full, pos_ids, axis=0)[:, None, :, :],
            mx.take(self._cos_swa, pos_ids, axis=0)[:, None, :, :],
            mx.take(self._sin_swa, pos_ids, axis=0)[:, None, :, :],
        )

    def build_attention_masks(
        self,
        seq_len: int,
        *,
        valid_lens: Any | None = None,
        pos_ids: Any | None = None,
        seg_ids: Any | None = None,
    ) -> tuple[Any, Any]:
        """Build additive `mx.bfloat16` `(full_mask, swa_mask)` for unpacked or varlen-packed sequences.

        In packed mode (`seg_ids is not None`), enforces strict block-diagonal segment isolation
        (`seg_q == seg_k`) on both full attention (including `head.layers.{0,1}`) and sliding-window
        attention (`same_seg & (|pos_q - pos_k| <= local_window // 2)`). Trailing pad tokens (`seg == 0`)
        attend only to pad tokens so every softmax row has at least one `0.0` diagonal entry and never
        leaks into or receives gradient from any valid segment.
        """
        mx = self._mx
        zero_bf16 = mx.array(0.0, dtype=mx.bfloat16)
        neg_bf16 = mx.array(-10000.0, dtype=mx.bfloat16)
        if seg_ids is not None:
            if pos_ids is None:
                raise ValueError("Packed attention masks require `pos_ids` alongside `seg_ids`.")
            seg_q = seg_ids[:, None, :, None]
            seg_k = seg_ids[:, None, None, :]
            same_seg = seg_q == seg_k
            pos_q = pos_ids[:, None, :, None]
            pos_k = pos_ids[:, None, None, :]
            allow_swa = same_seg & (mx.abs(pos_q - pos_k) <= self.half_local_window)
            full_mask = mx.where(same_seg, zero_bf16, neg_bf16)
            swa_mask = mx.where(allow_swa, zero_bf16, neg_bf16)
            return full_mask, swa_mask

        if valid_lens is None:
            raise ValueError("Unpacked attention masks require `valid_lens`.")
        if seq_len > self._swa_max_len:
            self._ensure_pos_capacity(seq_len, need_swa_bias=True)
        pos = mx.arange(seq_len, dtype=mx.int32)[None, :]
        valid_2d = pos < valid_lens[:, None]
        full_mask = mx.where(valid_2d[:, None, None, :], zero_bf16, neg_bf16)
        swa_mask = full_mask + self._swa_bias_bf16[:, :, :seq_len, :seq_len]
        return full_mask, swa_mask

    def run_frozen_trunk(
        self,
        ids: Any,
        valid_lens: Any | None = None,
        *,
        pos_ids: Any | None = None,
        seg_ids: Any | None = None,
        full_mask: Any | None = None,
        swa_mask: Any | None = None,
        rope_tables: tuple[Any, Any, Any, Any] | None = None,
    ) -> Any:
        """Execute frozen embeddings + `L0..freeze_below_layer-1` strictly in pre-cast `BF16` outside autograd."""
        mx = self._mx
        B, S = ids.shape
        H = self.hidden_size
        n_heads = self.n_heads
        hd = self.head_dim
        attn_scale = self.attn_scale

        if full_mask is None or swa_mask is None:
            full_mask, swa_mask = self.build_attention_masks(
                S, valid_lens=valid_lens, pos_ids=pos_ids, seg_ids=seg_ids
            )
        cos_f, sin_f, cos_s, sin_s = (
            rope_tables if rope_tables is not None else self.prepare_rope(S, pos_ids=pos_ids)
        )

        tok_emb = mx.take(self._emb_w, ids, axis=0)
        cur = self._ln_nobias(tok_emb, self._emb_norm_w)

        for is_full, attn_norm_w, wqkv, wo, mlp_norm_w, wi, wom in self._frozen_layers:
            x_attn = cur if attn_norm_w is None else self._ln_nobias(cur, attn_norm_w)
            qkv = x_attn @ wqkv.T
            qt, kt, vt = mx.split(qkv, 3, axis=-1)
            qh = qt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            kh = kt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            vh = vt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            c_t, s_t = (cos_f, sin_f) if is_full else (cos_s, sin_s)
            qrp = self._apply_rope(qh, c_t, s_t)
            krp = self._apply_rope(kh, c_t, s_t)
            att = mx.fast.scaled_dot_product_attention(
                qrp, krp, vh, scale=attn_scale, mask=(full_mask if is_full else swa_mask)
            )
            att_flat = att.transpose(0, 2, 1, 3).reshape(B, S, H)
            cur = cur + (att_flat @ wo.T)

            x_mlp = self._ln_nobias(cur, mlp_norm_w)
            val_h, gate_h = mx.split(x_mlp @ wi.T, 2, axis=-1)
            geglu = self._geglu(val_h, gate_h)
            cur = cur + (geglu @ wom.T)

        return cur  # [B, S, H] mx.bfloat16

    def forward_from_frozen(
        self,
        params: Mapping[str, Any],
        h_frozen: Any,
        valid_lens: Any | None = None,
        qtypes: Any | None = None,
        *,
        pos_ids: Any | None = None,
        seg_ids: Any | None = None,
        token_qtypes: Any | None = None,
        full_mask: Any | None = None,
        swa_mask: Any | None = None,
        rope_tables: tuple[Any, Any, Any, Any] | None = None,
    ) -> Any:
        """Execute trainable upper trunk `L{freeze_below_layer}..27` + `BF16` `head.layers.{0,1}` + `FP32` logits."""
        mx = self._mx
        B, S, H = h_frozen.shape
        n_heads = self.n_heads
        hd = self.head_dim
        attn_scale = self.attn_scale

        if full_mask is None or swa_mask is None:
            full_mask, swa_mask = self.build_attention_masks(
                S, valid_lens=valid_lens, pos_ids=pos_ids, seg_ids=seg_ids
            )
        cos_f, sin_f, cos_s, sin_s = (
            rope_tables if rope_tables is not None else self.prepare_rope(S, pos_ids=pos_ids)
        )

        cur = h_frozen
        for i in range(self.freeze_below_layer, self.n_layers):
            px = f"encoder.layers.{i}."
            is_full = self.layer_types[i] == "full_attention"
            x_attn = cur if i == 0 else self._ln_nobias(cur, params[px + "attn_norm.weight"].astype(mx.bfloat16))
            wqkv = params[px + "attn.Wqkv.weight"].astype(mx.bfloat16)
            qkv = x_attn @ wqkv.T
            qt, kt, vt = mx.split(qkv, 3, axis=-1)
            qh = qt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            kh = kt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            vh = vt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            c_t, s_t = (cos_f, sin_f) if is_full else (cos_s, sin_s)
            qrp = self._apply_rope(qh, c_t, s_t)
            krp = self._apply_rope(kh, c_t, s_t)
            att = mx.fast.scaled_dot_product_attention(
                qrp, krp, vh, scale=attn_scale, mask=(full_mask if is_full else swa_mask)
            )
            att_flat = att.transpose(0, 2, 1, 3).reshape(B, S, H)
            wo = params[px + "attn.Wo.weight"].astype(mx.bfloat16)
            cur = cur + (att_flat @ wo.T)

            x_mlp = self._ln_nobias(cur, params[px + "mlp_norm.weight"].astype(mx.bfloat16))
            wi = params[px + "mlp.Wi.weight"].astype(mx.bfloat16)
            val_h, gate_h = mx.split(x_mlp @ wi.T, 2, axis=-1)
            geglu = self._geglu(val_h, gate_h)
            wom = params[px + "mlp.Wo.weight"].astype(mx.bfloat16)
            cur = cur + (geglu @ wom.T)

        # Keep `h` and `full_mask` strictly in `mx.bfloat16` through `head.layers.{0,1}` (no FP32 SDPA spill!).
        h = self._ln_nobias(cur, params["encoder.final_norm.weight"].astype(mx.bfloat16))
        type_w_bf16 = params["type_emb.weight"].astype(mx.bfloat16)
        if token_qtypes is not None:
            t_vec = mx.take(type_w_bf16, token_qtypes, axis=0)
        elif qtypes is not None:
            t_vec = mx.take(type_w_bf16, qtypes, axis=0)[:, None, :]
        else:
            raise ValueError("forward_from_frozen requires either `qtypes` or `token_qtypes`.")
        h = h + t_vec

        for hi in range(2):
            hp = f"head.layers.{hi}."
            hn1 = self._ln_bias(
                h,
                params[hp + "norm1.weight"].astype(mx.bfloat16),
                params[hp + "norm1.bias"].astype(mx.bfloat16),
            )
            in_w = params[hp + "self_attn.in_proj_weight"].astype(mx.bfloat16)
            in_b = params[hp + "self_attn.in_proj_bias"].astype(mx.bfloat16)
            hqkv = hn1 @ in_w.T + in_b
            hqt, hkt, hvt = mx.split(hqkv, 3, axis=-1)
            hqh = hqt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            hkh = hkt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            hvh = hvt.reshape(B, S, n_heads, hd).transpose(0, 2, 1, 3)
            hatt = mx.fast.scaled_dot_product_attention(
                hqh, hkh, hvh, scale=attn_scale, mask=full_mask
            )
            hatt_flat = hatt.transpose(0, 2, 1, 3).reshape(B, S, H)
            out_w = params[hp + "self_attn.out_proj.weight"].astype(mx.bfloat16)
            out_b = params[hp + "self_attn.out_proj.bias"].astype(mx.bfloat16)
            h = h + (hatt_flat @ out_w.T + out_b)
            hn2 = self._ln_bias(
                h,
                params[hp + "norm2.weight"].astype(mx.bfloat16),
                params[hp + "norm2.bias"].astype(mx.bfloat16),
            )
            l1_w = params[hp + "linear1.weight"].astype(mx.bfloat16)
            l1_b = params[hp + "linear1.bias"].astype(mx.bfloat16)
            hl1 = self._relu_bias(hn2 @ l1_w.T, l1_b)
            l2_w = params[hp + "linear2.weight"].astype(mx.bfloat16)
            l2_b = params[hp + "linear2.bias"].astype(mx.bfloat16)
            h = h + (hl1 @ l2_w.T + l2_b)

        # Cast to `mx.float32` strictly at final pointer/choice scorer logits.
        sn = self._ln_bias(
            h,
            params["scorer.0.weight"].astype(mx.bfloat16),
            params["scorer.0.bias"].astype(mx.bfloat16),
        )
        s1_w = params["scorer.1.weight"].astype(mx.bfloat16)
        s1_b = params["scorer.1.bias"].astype(mx.bfloat16)
        sg = self._gelu_bias(sn @ s1_w.T, s1_b)
        s3_w = params["scorer.3.weight"].astype(mx.float32)
        s3_b = params["scorer.3.bias"].astype(mx.float32)
        pos_logits = (sg.astype(mx.float32) @ s3_w.T + s3_b).squeeze(-1)
        return pos_logits  # [B, S] float32

    def forward_logits(
        self,
        params: Mapping[str, Any],
        ids: Any,
        valid_lens: Any | None = None,
        qtypes: Any | None = None,
        *,
        pos_ids: Any | None = None,
        seg_ids: Any | None = None,
        token_qtypes: Any | None = None,
    ) -> Any:
        """Full forward pass (frozen `L0..k-1` + trainable `Lk..27` + `BF16` head -> `[B, S]` `FP32` logits)."""
        S = int(ids.shape[1])
        full_mask, swa_mask = self.build_attention_masks(
            S, valid_lens=valid_lens, pos_ids=pos_ids, seg_ids=seg_ids
        )
        rope_tables = self.prepare_rope(S, pos_ids=pos_ids)
        h_frozen = self._mx.stop_gradient(
            self.run_frozen_trunk(
                ids,
                valid_lens=valid_lens,
                pos_ids=pos_ids,
                seg_ids=seg_ids,
                full_mask=full_mask,
                swa_mask=swa_mask,
                rope_tables=rope_tables,
            )
        )
        return self.forward_from_frozen(
            params,
            h_frozen,
            valid_lens=valid_lens,
            qtypes=qtypes,
            pos_ids=pos_ids,
            seg_ids=seg_ids,
            token_qtypes=token_qtypes,
            full_mask=full_mask,
            swa_mask=swa_mask,
            rope_tables=rope_tables,
        )

    def compute_pointer_loss(
        self,
        pos_logits: Any,
        flat_mk_idx: Any,
        mk_valid: Any,
        targets: Any,
        soft_p1: Any,
        has_soft: Any,
        inv_temp: Any,
        item_valid: Any,
    ) -> Any:
        """Compiled per-item normalized pointer/choice + Kev soft-target distillation loss."""
        return self._pointer_loss(
            pos_logits, flat_mk_idx, mk_valid, targets, soft_p1, has_soft, inv_temp, item_valid
        )


def build_mlx_laya_trainer(
    raw_weights: dict[str, Any],
    enc_cfg: dict[str, Any],
    freeze_below_layer: int = 18,
    max_pos_len: int = 512,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """Build exact MLX ModernBERT-large + 2-layer Head + Scorer matching `_compile_laya_seq_bundle`."""
    model = LayaMlxModel(
        raw_weights,
        enc_cfg,
        freeze_below_layer=freeze_below_layer,
        max_pos_len=max_pos_len,
    )

    def forward_logits(
        params: dict[str, Any],
        ids: Any,
        valid_lens: Any | None = None,
        qtypes: Any | None = None,
        *,
        pos_ids: Any | None = None,
        seg_ids: Any | None = None,
        token_qtypes: Any | None = None,
    ) -> Any:
        return model.forward_logits(
            params,
            ids,
            valid_lens=valid_lens,
            qtypes=qtypes,
            pos_ids=pos_ids,
            seg_ids=seg_ids,
            token_qtypes=token_qtypes,
        )

    forward_logits.model = model  # type: ignore[attr-defined]
    return model.frozen, model.trainable, forward_logits


def compute_frozen_trunk_fingerprint(
    enc_cfg: Mapping[str, Any],
    frozen_weights: Mapping[str, Any],
    freeze_below_layer: int,
    items: Sequence[Mapping[str, Any]],
    *,
    max_seq_len: int = 512,
    pad_id: int = 50283,
) -> dict[str, str]:
    """Compute SHA-256 cache fingerprint invalidating on sequence, model config, or frozen weight changes."""
    import mlx.core as mx

    cfg_subset = {
        "hidden_size": int(enc_cfg["hidden_size"]),
        "num_hidden_layers": int(enc_cfg["num_hidden_layers"]),
        "num_attention_heads": int(enc_cfg["num_attention_heads"]),
        "intermediate_size": int(enc_cfg.get("intermediate_size", 0)),
        "local_attention": int(enc_cfg.get("local_attention", 128)),
        "layer_types": list(enc_cfg["layer_types"]),
        "rope_parameters": enc_cfg.get("rope_parameters", {}),
        "norm_eps": float(enc_cfg.get("norm_eps", enc_cfg.get("layer_norm_eps", 1e-5))),
        "vocab_size": int(enc_cfg.get("vocab_size", 0)),
        "freeze_below_layer": int(freeze_below_layer),
    }
    enc_cfg_sha = hashlib.sha256(
        json.dumps(cfg_subset, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    w_hasher = hashlib.sha256()
    for k in sorted(frozen_weights):
        v = frozen_weights[k]
        w_hasher.update(k.encode("utf-8"))
        w_hasher.update(b"\x00")
        w_hasher.update(str(tuple(v.shape)).encode("utf-8"))
        w_hasher.update(str(v.dtype).encode("utf-8"))
        if v.dtype == mx.bfloat16:
            arr_bytes = np.ascontiguousarray(np.asarray(v.view(mx.uint16))).tobytes()
        else:
            arr_bytes = np.ascontiguousarray(np.asarray(v)).tobytes()
        w_hasher.update(arr_bytes)
    weights_sha = w_hasher.hexdigest()

    it_hasher = hashlib.sha256()
    it_hasher.update(f"n={len(items)};max_s={int(max_seq_len)};pad={int(pad_id)};".encode("utf-8"))
    for it in items:
        ids_s = it["ids"][:max_seq_len]
        it_hasher.update(len(ids_s).to_bytes(4, "little"))
        it_hasher.update(np.asarray(ids_s, dtype=np.int32).tobytes())
    items_sha = it_hasher.hexdigest()

    combined_payload = {
        "format": "laya_frozen_trunk_bf16_v1",
        "freeze_below_layer": int(freeze_below_layer),
        "enc_cfg_sha256": enc_cfg_sha,
        "weights_sha256": weights_sha,
        "items_sha256": items_sha,
    }
    cache_key = hashlib.sha256(
        json.dumps(combined_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "cache_key": cache_key,
        "enc_cfg_sha256": enc_cfg_sha,
        "weights_sha256": weights_sha,
        "items_sha256": items_sha,
    }


class FrozenTrunkActivationCache:
    """NVMe-backed lossless `BF16` (`uint16` raw bit-pattern) cache for frozen `ModernBERT` `L0..k-1` states.

    Stores variable-length per-item boundary activations contiguously with `offsets.npy` + `meta.json`
    SHA-256 fingerprint validation, enabling `0` redundant lower-trunk FLOPs across epochs/sweeps for
    both unpacked and varlen-packed batches.
    """

    def __init__(self, cache_dir: Path | str, *, hidden_size: int, freeze_below_layer: int = 18) -> None:
        self.cache_dir = Path(cache_dir).expanduser().resolve()
        self.hidden_size = int(hidden_size)
        self.freeze_below_layer = int(freeze_below_layer)
        self.meta_path = self.cache_dir / "meta.json"
        self.offsets_path = self.cache_dir / "offsets.npy"
        self.hidden_path = self.cache_dir / "hidden_bf16.bin"
        self._offsets: np.ndarray | None = None
        self._mm: np.memmap | None = None
        self.meta: dict[str, Any] = {}
        self.cache_hit: bool = False

    def _try_open_valid(self, fp: Mapping[str, str], num_items: int) -> bool:
        if not (self.meta_path.exists() and self.offsets_path.exists() and self.hidden_path.exists()):
            return False
        try:
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        if meta.get("cache_key") != fp["cache_key"]:
            return False
        if int(meta.get("hidden_size", -1)) != self.hidden_size:
            return False
        if int(meta.get("freeze_below_layer", -1)) != self.freeze_below_layer:
            return False
        if int(meta.get("num_items", -1)) != num_items:
            return False
        total_tokens = int(meta.get("total_tokens", -1))
        expected_bytes = total_tokens * self.hidden_size * 2
        if total_tokens < 0 or self.hidden_path.stat().st_size != expected_bytes:
            return False
        offsets = np.load(self.offsets_path)
        if offsets.shape != (num_items + 1,) or int(offsets[-1]) != total_tokens:
            return False
        self._offsets = offsets.astype(np.int64, copy=False)
        self._mm = (
            np.memmap(self.hidden_path, dtype=np.uint16, mode="r", shape=(total_tokens, self.hidden_size))
            if total_tokens > 0
            else None
        )
        self.meta = meta
        return True

    def ensure_populated(
        self,
        model: LayaMlxModel,
        items: Sequence[Mapping[str, Any]],
        *,
        pad_id: int = 50283,
        max_seq_len: int = 512,
        pack_tokens: int = 1024,
        pack_bins: int = 8,
    ) -> bool:
        """Load valid cache on hit (returns `True`) or build atomically via packed frozen trunk (returns `False`)."""
        import mlx.core as mx

        self.close()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        fp = compute_frozen_trunk_fingerprint(
            model.enc_cfg,
            model.frozen,
            self.freeze_below_layer,
            items,
            max_seq_len=max_seq_len,
            pad_id=pad_id,
        )
        if self._try_open_valid(fp, len(items)):
            self.cache_hit = True
            return True

        lengths = np.array([min(max_seq_len, len(it["ids"])) for it in items], dtype=np.int64)
        offsets = np.zeros((len(items) + 1,), dtype=np.int64)
        if len(items):
            np.cumsum(lengths, out=offsets[1:])
        total_tokens = int(offsets[-1])

        tmp_hidden = self.cache_dir / f".hidden_bf16_{os.getpid()}.bin.tmp"
        tmp_offsets = self.cache_dir / f".offsets_{os.getpid()}.npy.tmp"
        tmp_meta = self.cache_dir / f".meta_{os.getpid()}.json.tmp"
        eff_pack = max(int(max_seq_len), int(pack_tokens))
        eff_bins = max(1, int(pack_bins))

        try:
            mm_w = (
                np.memmap(tmp_hidden, dtype=np.uint16, mode="w+", shape=(total_tokens, self.hidden_size))
                if total_tokens > 0
                else None
            )
            if mm_w is None:
                tmp_hidden.write_bytes(b"")

            # Pack ALL items (`>= 1` token) greedily into `eff_pack` bins so cache population has minimal pad waste.
            indexed = [(idx, min(max_seq_len, len(it["ids"]))) for idx, it in enumerate(items) if len(it["ids"]) > 0]
            indexed.sort(key=lambda pair: pair[1], reverse=True)
            bins: list[list[tuple[int, int]]] = []
            used: list[int] = []
            for orig_idx, ln in indexed:
                placed = False
                for bi in range(len(used)):
                    if used[bi] + ln <= eff_pack:
                        bins[bi].append((orig_idx, ln))
                        used[bi] += ln
                        placed = True
                        break
                if not placed:
                    bins.append([(orig_idx, ln)])
                    used.append(ln)

            for b0 in range(0, len(bins), eff_bins):
                chunk_bins = bins[b0 : b0 + eff_bins]
                B_c = len(chunk_bins)
                ids_np = np.full((B_c, eff_pack), int(pad_id), dtype=np.int32)
                pos_np = np.zeros((B_c, eff_pack), dtype=np.int32)
                seg_np = np.zeros((B_c, eff_pack), dtype=np.int32)
                spans: list[tuple[int, int, int, int]] = []
                for bi, entries in enumerate(chunk_bins):
                    cursor = 0
                    for seg_i, (orig_idx, ln) in enumerate(entries, start=1):
                        ids_np[bi, cursor : cursor + ln] = items[orig_idx]["ids"][:ln]
                        pos_np[bi, cursor : cursor + ln] = np.arange(ln, dtype=np.int32)
                        seg_np[bi, cursor : cursor + ln] = seg_i
                        spans.append((orig_idx, bi, cursor, ln))
                        cursor += ln

                h_bf16 = model.run_frozen_trunk(
                    mx.array(ids_np),
                    pos_ids=mx.array(pos_np),
                    seg_ids=mx.array(seg_np),
                )
                mx.eval(h_bf16)
                h_u16 = np.asarray(h_bf16.view(mx.uint16))
                if mm_w is not None:
                    for orig_idx, bi, cursor, ln in spans:
                        dst0 = int(offsets[orig_idx])
                        mm_w[dst0 : dst0 + ln, :] = h_u16[bi, cursor : cursor + ln, :]
                del h_bf16, h_u16
                if mx.get_cache_memory() > (256 << 20):
                    mx.clear_cache()

            if mm_w is not None:
                mm_w.flush()
                del mm_w

            with open(tmp_offsets, "wb") as f_off:
                np.save(f_off, offsets)

            meta = {
                "format": "laya_frozen_trunk_bf16_v1",
                "cache_key": fp["cache_key"],
                "enc_cfg_sha256": fp["enc_cfg_sha256"],
                "weights_sha256": fp["weights_sha256"],
                "items_sha256": fp["items_sha256"],
                "hidden_size": self.hidden_size,
                "freeze_below_layer": self.freeze_below_layer,
                "num_items": len(items),
                "total_tokens": total_tokens,
                "max_seq_len": int(max_seq_len),
                "dtype": "bfloat16",
            }
            tmp_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")

            os.replace(tmp_hidden, self.hidden_path)
            os.replace(tmp_offsets, self.offsets_path)
            os.replace(tmp_meta, self.meta_path)
        except Exception:
            for p_tmp in (tmp_hidden, tmp_offsets, tmp_meta):
                if p_tmp.exists():
                    try:
                        p_tmp.unlink()
                    except OSError:
                        pass
            raise

        self._offsets = offsets
        self._mm = (
            np.memmap(self.hidden_path, dtype=np.uint16, mode="r", shape=(total_tokens, self.hidden_size))
            if total_tokens > 0
            else None
        )
        self.meta = meta
        self.cache_hit = False
        return False

    def gather_batch(
        self,
        item_spans: Sequence[tuple[int, int, int, int]],
        batch_rows: int,
        seq_len: int,
    ) -> Any:
        """Assemble cached `[batch_rows, seq_len, H]` `mx.bfloat16` frozen boundary activations."""
        import mlx.core as mx

        if self._offsets is None:
            raise RuntimeError("FrozenTrunkActivationCache must be populated before gather_batch().")
        buf_u16 = np.zeros((int(batch_rows), int(seq_len), self.hidden_size), dtype=np.uint16)
        if self._mm is not None:
            for orig_idx, row_i, off, ln in item_spans:
                if ln <= 0:
                    continue
                src0 = int(self._offsets[orig_idx])
                src1 = int(self._offsets[orig_idx + 1])
                if src0 + ln > src1:
                    raise ValueError(
                        f"FrozenTrunkActivationCache over-read for item {orig_idx}: requested ln={ln} "
                        f"exceeds cached length {src1 - src0} (align pack max_item_len <= cache max_seq_len)."
                    )
                buf_u16[row_i, off : off + ln, :] = self._mm[src0 : src0 + ln, :]
        return mx.array(buf_u16).view(mx.bfloat16)

    def close(self) -> None:
        self._mm = None
        self._offsets = None


def make_compiled_optimizer_step(
    params: dict[str, Any],
    opt: Any,
    *,
    max_grad_norm: float = 1.0,
) -> tuple[Any, list[Any]]:
    """Create `@mx.compile` GPU global-norm clipping + AdamW update step (zero per-tensor host syncs)."""
    import mlx.core as mx

    opt.init(params)
    mx.eval(params, opt.state)
    state = [params, opt.state]
    max_norm_arr = mx.array(float(max_grad_norm), dtype=mx.float32)
    eps_arr = mx.array(1e-12, dtype=mx.float32)
    one_arr = mx.array(1.0, dtype=mx.float32)

    @partial(mx.compile, inputs=state, outputs=state)
    def _compiled_clip_and_update(g_dict: dict[str, Any]) -> Any:
        sq_norm = mx.array(0.0, dtype=mx.float32)
        for g in g_dict.values():
            sq_norm = sq_norm + mx.sum(g * g)
        scale = mx.minimum(one_arr, max_norm_arr * mx.rsqrt(mx.maximum(sq_norm, eps_arr)))
        clipped = {k: g * scale for k, g in g_dict.items()}
        opt.update(params, clipped)
        return sq_norm

    return _compiled_clip_and_update, state


def make_validator_train_step(
    model: LayaMlxModel,
    params: dict[str, Any],
    opt: Any,
    *,
    max_grad_norm: float = 1.0,
) -> Any:
    """Create a unified fast training step supporting unpacked/packed batches and live/cached frozen trunks."""
    import mlx.core as mx

    def _loss_from_frozen(
        p: dict[str, Any],
        h_frozen: Any,
        qtypes_mx: Any,
        tok_qtypes_mx: Any,
        full_mask: Any,
        swa_mask: Any,
        cos_f: Any,
        sin_f: Any,
        cos_s: Any,
        sin_s: Any,
        flat_mk_mx: Any,
        mkv_mx: Any,
        tgt_mx: Any,
        sp1_mx: Any,
        hsp_mx: Any,
        invt_mx: Any,
        item_valid_mx: Any,
    ) -> Any:
        pos_logits = model.forward_from_frozen(
            p,
            h_frozen,
            qtypes=qtypes_mx,
            token_qtypes=tok_qtypes_mx,
            full_mask=full_mask,
            swa_mask=swa_mask,
            rope_tables=(cos_f, sin_f, cos_s, sin_s),
        )
        return model.compute_pointer_loss(
            pos_logits, flat_mk_mx, mkv_mx, tgt_mx, sp1_mx, hsp_mx, invt_mx, item_valid_mx
        )

    vg_from_frozen = mx.value_and_grad(_loss_from_frozen)
    compiled_opt_step, opt_state = make_compiled_optimizer_step(params, opt, max_grad_norm=max_grad_norm)

    def run_step(
        batch: Mapping[str, Any],
        *,
        frozen_cache: FrozenTrunkActivationCache | None = None,
        cur_lr: float | None = None,
    ) -> tuple[float, int, int]:
        if cur_lr is not None:
            opt.learning_rate = float(cur_lr)

        ids_np = batch["ids"]
        B_rows, S_len = int(ids_np.shape[0]), int(ids_np.shape[1])
        is_packed = bool(batch["packed"])
        if is_packed:
            vl_mx = None
            qt_mx = None
            pos_mx = mx.array(batch["pos_ids"])
            seg_mx = mx.array(batch["seg_ids"])
            tok_qt_mx = mx.array(batch["token_qtypes"])
        else:
            vl_mx = mx.array(batch["valid_lens"])
            qt_mx = mx.array(batch["qtypes"])
            pos_mx = None
            seg_mx = None
            tok_qt_mx = None

        full_mask, swa_mask = model.build_attention_masks(
            S_len, valid_lens=vl_mx, pos_ids=pos_mx, seg_ids=seg_mx
        )
        cos_f, sin_f, cos_s, sin_s = model.prepare_rope(S_len, pos_ids=pos_mx)

        if frozen_cache is not None:
            h_frozen = frozen_cache.gather_batch(batch["item_spans"], B_rows, S_len)
        else:
            h_frozen = mx.stop_gradient(
                model.run_frozen_trunk(
                    mx.array(ids_np),
                    valid_lens=vl_mx,
                    pos_ids=pos_mx,
                    seg_ids=seg_mx,
                    full_mask=full_mask,
                    swa_mask=swa_mask,
                    rope_tables=(cos_f, sin_f, cos_s, sin_s),
                )
            )

        loss_v, grads = vg_from_frozen(
            params,
            h_frozen,
            qt_mx,
            tok_qt_mx,
            full_mask,
            swa_mask,
            cos_f,
            sin_f,
            cos_s,
            sin_s,
            mx.array(batch["flat_mk_idx"]),
            mx.array(batch["mk_valid"]),
            mx.array(batch["targets"]),
            mx.array(batch["soft_p1"]),
            mx.array(batch["has_soft"]),
            mx.array(batch["inv_temp"]),
            mx.array(batch["item_valid"]),
        )
        compiled_opt_step(grads)
        mx.eval(opt_state, loss_v)
        return float(loss_v.item()), int(batch["num_items"]), int(batch["real_tokens"])

    return run_step


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


def _fit_monotonic_router_thresholds(
    probs: np.ndarray,
    y_true: np.ndarray,
    class_names: Sequence[str],
) -> tuple[float, float, float, float, float]:
    """Fit calibrated Top-1 lock & Top-2/Top-3 set thresholds enforcing tau1 <= tau2 <= tau3."""
    n = len(y_true)
    if n == 0:
        return 0.88, 0.90, 0.92, 0.0, 1.0

    usable_mask = np.array(
        [not str(class_names[int(np.argmax(probs[i]))]).startswith("status:") for i in range(n)],
        dtype=bool,
    )
    p_top1 = np.max(probs, axis=-1)
    pred_top1 = np.argmax(probs, axis=-1)

    min_n1 = min(25, max(3, n // 18))
    tau_top1 = 0.88
    for cand_tau in np.linspace(0.50, 0.96, 93):
        sel = usable_mask & (p_top1 >= cand_tau)
        if int(np.sum(sel)) < min_n1:
            continue
        if float(np.mean(pred_top1[sel] == y_true[sel])) >= 0.960:
            tau_top1 = round(float(cand_tau), 4)
            break

    sorted_p = np.sort(probs, axis=-1)[:, ::-1]
    sorted_i = np.argsort(-probs, axis=-1)
    p_top2 = sorted_p[:, 0] + sorted_p[:, 1]
    p_top3 = p_top2 + sorted_p[:, 2]

    tau_top2 = round(max(tau_top1, 0.88), 4)
    valid_k2 = np.array(
        [
            all(not str(class_names[int(sorted_i[r_i, j])]).startswith("status:") for j in range(2))
            for r_i in range(n)
        ],
        dtype=bool,
    )
    min_n2 = min(15, max(2, n // 25))
    for cand_tau in np.linspace(max(0.60, tau_top1), 0.98, 77):
        sel = (p_top1 < tau_top1) & (p_top2 >= cand_tau) & valid_k2
        if int(np.sum(sel)) < min_n2:
            continue
        cov2 = float(np.mean([y_true[r_i] in sorted_i[r_i, :2] for r_i in np.where(sel)[0]]))
        if cov2 >= 0.975:
            tau_top2 = round(max(tau_top1, float(cand_tau)), 4)
            break

    tau_top3 = round(max(tau_top2, 0.90), 4)
    valid_k3 = np.array(
        [
            all(not str(class_names[int(sorted_i[r_i, j])]).startswith("status:") for j in range(3))
            for r_i in range(n)
        ],
        dtype=bool,
    )
    min_n3 = min(10, max(2, n // 35))
    for cand_tau in np.linspace(max(0.65, tau_top2), 0.98, 67):
        sel = (p_top1 < tau_top1) & (p_top2 < tau_top2) & (p_top3 >= cand_tau) & valid_k3
        if int(np.sum(sel)) < min_n3:
            continue
        cov3 = float(np.mean([y_true[r_i] in sorted_i[r_i, :3] for r_i in np.where(sel)[0]]))
        if cov3 >= 0.980:
            tau_top3 = round(max(tau_top2, float(cand_tau)), 4)
            break

    sel1 = usable_mask & (p_top1 >= tau_top1)
    prec1 = float(np.mean(pred_top1[sel1] == y_true[sel1])) if np.any(sel1) else 1.0
    cov1 = float(np.mean(sel1))
    return tau_top1, tau_top2, tau_top3, cov1, prec1


def fit_fused_router_calibration(
    cal_lin_probs: np.ndarray,
    ane_top6_logits: np.ndarray,
    top6_order: np.ndarray,
    y_cal: np.ndarray,
    class_names: Sequence[str],
    *,
    train_docs: int = 0,
    top1_acc: float | None = None,
    top6_rec: float | None = None,
) -> tuple[dict[str, Any], np.ndarray]:
    """Fit normalized conditional PoE router fusion and monotonic ANE/fast thresholds."""
    n = len(y_cal)
    lin_acc = (
        float(top1_acc)
        if top1_acc is not None
        else float(np.mean(np.argmax(cal_lin_probs, axis=-1) == y_cal))
    )
    lin_rec6 = (
        float(top6_rec)
        if top6_rec is not None
        else float(np.mean([y_cal[i] in top6_order[i] for i in range(n)]))
    )

    best_alpha = 0.5
    best_t_r = 1.0
    best_score = (-1.0, -1e9)
    best_fused_probs = cal_lin_probs.copy()
    row_idxs = list(range(n))

    for alpha in np.linspace(0.15, 0.85, 15):
        for t_ane in np.linspace(0.5, 2.5, 21):
            ane_p6 = softmax_np(ane_top6_logits, float(t_ane))
            f_probs = fuse_top6_router_probs(
                cal_lin_probs,
                top6_order,
                row_idxs,
                ane_p6.tolist(),
                float(alpha),
            )
            acc_c = float(np.mean(np.argmax(f_probs, axis=-1) == y_cal))
            p_true = np.clip(f_probs[np.arange(n), y_cal], 1e-7, 1.0)
            nll_c = float(-np.mean(np.log(p_true)))
            score = (round(acc_c, 6), -nll_c)
            if score > best_score:
                best_score = score
                best_alpha = round(float(alpha), 3)
                best_t_r = round(float(t_ane), 3)
                best_fused_probs = f_probs

    best_acc = best_score[0]
    tau_top1, tau_top2, tau_top3, cov1, prec1 = _fit_monotonic_router_thresholds(
        best_fused_probs, y_cal, class_names
    )
    lin_tau1, lin_tau2, lin_tau3, _, _ = _fit_monotonic_router_thresholds(
        cal_lin_probs, y_cal, class_names
    )

    router_cal = {
        "version": "v6_3",
        "train_docs": int(train_docs),
        "cal_docs": int(n),
        "num_classes": len(class_names),
        "linear_top1_acc_cal500": round(lin_acc, 4),
        "linear_top6_recall_cal500": round(lin_rec6, 4),
        "ane_fused_top1_acc_cal500": round(best_acc, 4),
        "fusion_linear_alpha": best_alpha,
        "ane_choice_temperature": best_t_r,
        "ane_tau_top1": tau_top1,
        "ane_tau_top2": tau_top2,
        "ane_tau_top3": tau_top3,
        "ane_lock1_coverage_cal500": round(cov1, 4),
        "ane_lock1_precision_cal500": round(prec1, 4),
        "fast_linear_tau_top1": lin_tau1,
        "fast_linear_tau_top2": lin_tau2,
        "fast_linear_tau_top3": lin_tau3,
    }
    return router_cal, best_fused_probs


def fit_validator_fusion_calibration(
    v0_u_scores: Sequence[float],
    laya_raw_scores: Sequence[float],
    y_is_corrupt: Sequence[int],
    *,
    role_probs: np.ndarray | None = None,
    role_y: np.ndarray | None = None,
    persona_v0_scores: Sequence[float] | None = None,
    persona_laya_scores: Sequence[float] | None = None,
    persona_y_bad: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Fit `laya_raw_offset`, `laya_raw_scale`, `v0_laya_weights`, and escalation/repair gates."""
    v0 = np.asarray(v0_u_scores, dtype=np.float64)
    l_raw = np.asarray(laya_raw_scores, dtype=np.float64)
    y = np.asarray(y_is_corrupt, dtype=np.int32)

    clean_l = l_raw[y == 0]
    bad_l = l_raw[y == 1]
    off, scale = 0.38, 0.48
    best_wv0 = 0.62
    if len(clean_l) > 0 and len(bad_l) > 0:
        off_cands = sorted(
            {round(float(np.clip(np.quantile(clean_l, q), 0.18, 0.38)), 4) for q in (0.20, 0.30, 0.35)}
            | {0.38}
        )
        wv0_cands = sorted({round(float(w), 4) for w in np.linspace(0.42, 0.64, 12)} | {0.62})
        hi_bad = float(np.quantile(bad_l, 0.90))
        v0_bad, v0_clean = v0[y == 1], v0[y == 0]
        l_bad, l_clean = bad_l, clean_l
        best_auc_key = (-1.0, -1e9, -1e9)
        for off_c in off_cands:
            scale_cands = sorted({round(float(np.clip(hi_bad - off_c, 0.38, 0.68)), 4), 0.48})
            for scale_c in scale_cands:
                inv_s = 1.0 / max(scale_c, 1e-4)
                lc_bad = np.clip((l_bad - off_c) * inv_s, 0.0, 1.0)
                lc_clean = np.clip((l_clean - off_c) * inv_s, 0.0, 1.0)
                for w_c in wv0_cands:
                    c_bad = w_c * v0_bad + (1.0 - w_c) * lc_bad
                    c_clean = w_c * v0_clean + (1.0 - w_c) * lc_clean
                    diff = c_bad[:, None] - c_clean[None, :]
                    auc = float(np.mean((diff > 1e-12) + 0.5 * (np.abs(diff) <= 1e-12)))
                    sep = float(np.mean(c_bad) - np.mean(c_clean))
                    prox = -(abs(off_c - 0.38) + abs(scale_c - 0.48) + abs(w_c - 0.62))
                    key = (round(auc, 6), round(sep, 6), round(prox, 6))
                    if key > best_auc_key:
                        best_auc_key = key
                        off, scale, best_wv0 = off_c, scale_c, w_c

    l_cal = np.clip((l_raw - off) / max(scale, 1e-4), 0.0, 1.0)
    best_th = 0.45
    best_score = (-1.0, -1e9)
    n_clean = max(1, int(np.sum(y == 0)))
    if len(y) >= 4 and np.any(y == 1) and np.any(y == 0):
        # Precision-first (clean FP <= 5%) escalation sweep after AUROC-preserving (off, scale, w_v0) fit
        found_low_fp = False
        for w_v0 in (best_wv0,):
            comb = w_v0 * v0 + (1.0 - w_v0) * l_cal
            for th in np.linspace(0.38, 0.65, 28):
                pred = comb >= th
                tp = int(np.sum(pred & (y == 1)))
                fp = int(np.sum(pred & (y == 0)))
                fn = int(np.sum((~pred) & (y == 1)))
                fp_rate = fp / float(n_clean)
                f1 = (2.0 * tp) / float(max(1, 2 * tp + fp + fn))
                f05 = (1.25 * tp) / float(max(1, 1.25 * tp + 0.25 * fp + fn))
                if fp_rate <= 0.05:
                    found_low_fp = True
                    obj = (2.0 + round(f1, 6), -abs(float(w_v0) - 0.62) - abs(float(th) - 0.45))
                elif not found_low_fp:
                    obj = (round(f05, 6), -fp_rate - 0.01 * abs(float(th) - 0.45))
                else:
                    continue
                if obj > best_score:
                    best_score = obj
                    best_wv0 = round(float(w_v0), 4)
                    best_th = round(float(th), 4)

    casc_low = round(float(np.clip(best_th * 0.50, 0.16, 0.30)), 4)
    casc_high = round(float(np.clip(max(best_th + 0.17, 0.55), 0.52, 0.78)), 4)

    role_min_prob = 0.45
    if role_probs is not None and role_y is not None and len(role_y) >= 20:
        rp_max = np.max(role_probs, axis=-1)
        rp_pred = np.argmax(role_probs, axis=-1)
        picked = False
        best_fb = (-1.0, -1e9)
        for cand_p in np.linspace(0.45, 0.78, 34):
            sel = rp_max >= cand_p
            cov = float(np.mean(sel))
            if cov < 0.15:
                continue
            acc_sel = float(np.mean(rp_pred[sel] == role_y[sel]))
            if acc_sel >= 0.90:
                role_min_prob = round(float(cand_p), 4)
                picked = True
                break
            fb_obj = (round(acc_sel * 0.75 + cov * 0.25, 6), -abs(float(cand_p) - 0.45))
            if fb_obj > best_fb:
                best_fb = fb_obj
                role_min_prob = round(float(cand_p), 4)
        if not picked:
            role_min_prob = round(float(np.clip(role_min_prob, 0.45, 0.75)), 4)

    role_min_defect = 0.48
    if (
        persona_v0_scores is not None
        and persona_laya_scores is not None
        and persona_y_bad is not None
        and len(persona_y_bad) >= 10
    ):
        pv0 = np.asarray(persona_v0_scores, dtype=np.float64)
        pl = np.asarray(persona_laya_scores, dtype=np.float64)
        py = np.asarray(persona_y_bad, dtype=np.int32)
        n_p_clean = max(1, int(np.sum(py == 0)))
        if np.any(py == 1) and np.any(py == 0):
            p_def = 0.55 * pv0 + 0.45 * pl
            best_p_obj = (-1.0, -1e9)
            found_p_low_fp = False
            for th_p in np.linspace(0.45, 0.68, 24):
                pred_p = p_def >= th_p
                tp = int(np.sum(pred_p & (py == 1)))
                fp = int(np.sum(pred_p & (py == 0)))
                fn = int(np.sum((~pred_p) & (py == 1)))
                fp_rate_p = fp / float(n_p_clean)
                f1_p = (2.0 * tp) / float(max(1, 2 * tp + fp + fn))
                f05_p = (1.25 * tp) / float(max(1, 1.25 * tp + 0.25 * fp + fn))
                if fp_rate_p <= 0.05:
                    found_p_low_fp = True
                    p_obj = (2.0 + round(f1_p, 6), -abs(float(th_p) - 0.48))
                elif not found_p_low_fp:
                    p_obj = (round(f05_p, 6), -fp_rate_p - 0.01 * abs(float(th_p) - 0.48))
                else:
                    continue
                if p_obj > best_p_obj:
                    best_p_obj = p_obj
                    role_min_defect = round(float(th_p), 4)

    out_f1 = None
    if len(y) >= 4 and np.any(y == 1) and np.any(y == 0):
        pred_f = (best_wv0 * v0 + (1.0 - best_wv0) * l_cal) >= best_th
        tp_f = int(np.sum(pred_f & (y == 1)))
        fp_f = int(np.sum(pred_f & (y == 0)))
        fn_f = int(np.sum((~pred_f) & (y == 1)))
        out_f1 = round((2.0 * tp_f) / float(max(1, 2 * tp_f + fp_f + fn_f)), 4)

    return {
        "v0_laya_weights": [best_wv0, round(1.0 - best_wv0, 4)],
        "laya_raw_offset": off,
        "laya_raw_scale": scale,
        "cascade_low": casc_low,
        "cascade_high": casc_high,
        "escalate_threshold": best_th,
        "role_repair_min_defect": role_min_defect,
        "role_repair_min_prob": role_min_prob,
        "stage1_cal_f1": out_f1,
    }


def build_corrupt_validation_docs(
    usable_records: Sequence[dict[str, Any]],
    *,
    max_docs: int = 180,
    seed: int = 20261120,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Build deterministic single-fault corrupted docs paired with usable held-out records."""
    rng = random.Random(seed)
    titles = [str(r["gold"].get("composed_title") or "") for r in usable_records if r["gold"].get("composed_title")]
    gists = [str(r["gold"].get("gist") or "") for r in usable_records if r["gold"].get("gist")]
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for idx, rec in enumerate(usable_records[:max_docs]):
        gold = rec["gold"]
        pk = str(gold.get("primary_kind") or "witness_statement")
        bad = json.loads(json.dumps(gold))
        mode_k = idx % 3
        if mode_k == 1 and (gold.get("committees") or DECOY_COMMITTEES):
            existing = {str(c).lower() for c in (gold.get("committees") or ())}
            pool = [c for c in DECOY_COMMITTEES if c.lower() not in existing]
            if pool:
                bad["committees"] = [rng.choice(pool)]
            else:
                mode_k = 0
        if mode_k == 2:
            if len(gists) > 1:
                alt_i = (idx + 1) % len(gists)
                bad["composed_title"] = titles[alt_i] if alt_i < len(titles) else bad.get("composed_title")
                bad["gist"] = gists[alt_i]
            else:
                bad["gist"] = str(gold.get("gist") or "") + " Mandates $84 billion under H.R. 9942."
        if mode_k == 0:
            neighs = CONFUSABLE_KIND_NEIGHBORS.get(pk) or [k for k in ALL_DOC_KINDS if k != pk]
            bad["primary_kind"] = rng.choice(neighs)
        pairs.append((rec, bad))
    return pairs


def calibrate_stage6_bundle(
    artifacts_dir: Path,
    *,
    train_count: int,
    cal_thresh_records: Sequence[dict[str, Any]],
    W_full: np.ndarray,
    b_full: np.ndarray,
    lin_temp: float,
    laya_v63: LayaAneBackend,
    bundle_version: str = "v6_3",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run live ANE Stage-6 calibration on held-out `cal_thresh_records` and write manifest."""
    laya_out_dir = artifacts_dir / "laya_typed"
    X_cal = build_dense_feature_matrix(list(cal_thresh_records), dim=12288)
    y_cal = np.array([ROUTER_CLASS_TO_IDX[r["router_class"]] for r in cal_thresh_records], dtype=np.int32)
    cal_lin_logits = X_cal @ W_full.T + b_full
    cal_lin_probs = softmax_np(cal_lin_logits, lin_temp)
    top1_acc = float(np.mean(np.argmax(cal_lin_probs, axis=-1) == y_cal))
    top6_Order = np.argsort(-cal_lin_probs, axis=-1)[:, :6]
    top6_rec = float(np.mean([y_cal[i] in top6_Order[i] for i in range(len(y_cal))]))
    cal_top6 = [
        [ROUTER_CLASSES[idx_c] for idx_c in top6_Order[row_i]]
        for row_i in range(len(cal_thresh_records))
    ]

    r_encs = []
    for ci, rec in enumerate(cal_thresh_records):
        st_r, q_r = build_router_choice_item(rec, cal_top6[ci])
        r_encs.append(laya_encode_ignore_truncation(laya_v63, st_r, q_r))

    out_512 = laya_v63._exec_bucket(r_encs, 512, laya_v63._h512)
    ane_top6_logits = np.zeros((len(cal_thresh_records), 6), dtype=np.float32)
    for ci, enc_it in enumerate(r_encs):
        mks = enc_it["markers"]
        for j in range(len(mks)):
            ane_top6_logits[ci, j] = float(out_512[ci, mks[j]])

    router_cal, _ = fit_fused_router_calibration(
        cal_lin_probs,
        ane_top6_logits,
        top6_Order,
        y_cal,
        ROUTER_CLASSES,
        train_docs=train_count,
        top1_acc=top1_acc,
        top6_rec=top6_rec,
    )
    (artifacts_dir / "router_v63_calibration.json").write_text(json.dumps(router_cal, indent=2), encoding="utf-8")
    print(
        f"      [Fused ANE Router on cal={len(cal_thresh_records)}] Top-1 Acc={router_cal['ane_fused_top1_acc_cal500']:.4f} "
        f"(vs {top1_acc:.4f} linear) | tau=({router_cal['ane_tau_top1']}, {router_cal['ane_tau_top2']}, {router_cal['ane_tau_top3']})"
    )

    cal_items = synthesize_training_examples(
        list(cal_thresh_records),
        cal_top6,
        laya_v63,
        None,
        distill_docs=0,
        seed=20261119,
        reuse_doc_prefix=False,
    )
    noul_pool = [it for it in cal_items if it["qtype"] == 2]
    random.Random(20261120).shuffle(noul_pool)
    noul_cal = noul_pool[:900]

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

    cfg_final = json.loads((laya_out_dir / "rl_agent_config.json").read_text(encoding="utf-8"))
    cfg_final["temperature_by_options"]["noul:2"] = best_tn
    laya_v63.temperature_by_options["noul:2"] = best_tn

    role_pool = [it for it in cal_items if it["task"] == "persona_role_choice"]
    random.Random(20261121).shuffle(role_pool)
    role_cal = role_pool[:400]
    role_acc_ane = 0.0
    best_tr_role = float(cfg_final["temperature_by_options"].get("choice:11+", 1.0))
    rc_probs: np.ndarray | None = None
    rc_y: np.ndarray | None = None
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

    # Held-out clean vs hard-corrupt Stage-1 V0 + live ANE Laya validation calibration
    usable_cal = [
        r
        for r in cal_thresh_records
        if str(r["gold"].get("status") or "usable") == "usable" and r.get("p12_clean_text")
    ]
    corrupt_pairs = build_corrupt_validation_docs(usable_cal, max_docs=180, seed=20261120)
    doc_eval_rows: list[tuple[dict[str, Any], dict[str, Any], int]] = []
    for rec, bad_doc in corrupt_pairs:
        doc_eval_rows.append((rec, rec["gold"], 0))
        doc_eval_rows.append((rec, bad_doc, 1))

    v0_scores: list[float] = []
    laya_q3_encs: list[dict[str, Any]] = []
    for rec, doc_obj, _lbl in doc_eval_rows:
        v0 = dict(score_atomic_stdlib_v6(doc_obj, rec))
        txt = rec.get("p12_clean_text") or rec.get("p12_raw_text") or ""
        if txt.strip():
            g_rep = check_gist_title_grounding_v6(doc_obj, text=txt, filename=rec["filename"], known=rec["known"])
            if g_rep.get("ungrounded_citations") or g_rep.get("ungrounded_modality"):
                v0["atomic_risk_score"] = round(float(v0["atomic_risk_score"]) + 0.65, 4)
        v0_scores.append(min(1.0, float(v0["atomic_risk_score"]) / 1.50))
        st_d, qs_d = build_atomic_doc_questions_v6(doc_obj, rec, head_chars=950, tail_chars=350)
        for q3 in qs_d[:3]:
            laya_q3_encs.append(laya_encode_ignore_truncation(laya_v63, st_d, q3))

    laya_raw_scores: list[float] = []
    if laya_q3_encs:
        p1_flat = laya_v63.score_noul_batch(laya_q3_encs)
        for idx_d in range(len(doc_eval_rows)):
            base = idx_d * 3
            laya_raw_scores.append(
                AtomicOutputValidatorV6._agg_defect(p1_flat[base], p1_flat[base + 1], p1_flat[base + 2])
            )

    # Also fit persona role_repair_min_defect from held-out clean vs swapped persona Noul items
    pers_v0: list[float] = []
    pers_encs: list[dict[str, Any]] = []
    pers_y: list[int] = []
    rng_p = random.Random(20261122)
    for rec, _bad in corrupt_pairs[:90]:
        g = rec["gold"]
        ps = [px for px in (g.get("personas") or ()) if isinstance(px, dict) and px.get("name") and px.get("role") in ROLE_TO_IDX]
        if not ps:
            continue
        px = ps[0]
        v0_pos = score_atomic_stdlib_v6(g, rec)
        pv0_pos_list = list(v0_pos.get("persona_defect_scores") or ())
        idx_px = list(g.get("personas") or ()).index(px)
        pv0_p = float(pv0_pos_list[idx_px]) if idx_px < len(pv0_pos_list) else 0.0
        pst_p, pq_p = build_atomic_persona_question_v6(g, rec, px)
        pers_v0.append(pv0_p)
        pers_encs.append(laya_encode_ignore_truncation(laya_v63, pst_p, pq_p))
        pers_y.append(0)

        bad_px = dict(px)
        alts = CONFUSABLE_ROLE_SWAPS.get(str(px["role"])) or [r for r in ALL_ROLES if r != px["role"]]
        bad_px["role"] = rng_p.choice(alts)
        bad_gp = json.loads(json.dumps(g))
        bad_gp["personas"] = [bad_px] + [p for p in ps if p is not px][:4]
        v0_neg = score_atomic_stdlib_v6(bad_gp, rec)
        pv0_n = float((v0_neg.get("persona_defect_scores") or [0.0])[0])
        pst_n, pq_n = build_atomic_persona_question_v6(bad_gp, rec, bad_px)
        pers_v0.append(pv0_n)
        pers_encs.append(laya_encode_ignore_truncation(laya_v63, pst_n, pq_n))
        pers_y.append(1)

    pers_laya = [1.0 - p for p in laya_v63.score_noul_batch(pers_encs)] if pers_encs else []

    fitted_val = fit_validator_fusion_calibration(
        v0_scores,
        laya_raw_scores,
        [lbl for _, _, lbl in doc_eval_rows],
        role_probs=rc_probs,
        role_y=rc_y,
        persona_v0_scores=pers_v0,
        persona_laya_scores=pers_laya,
        persona_y_bad=pers_y,
    )
    val_cal_meta = {
        "version": "v6_3",
        "noul_temperature_cal500": best_tn,
        "noul_brier_cal500": round(best_brier, 4),
        "persona_role_choice16_temperature": best_tr_role,
        "persona_role_choice16_acc_cal500": round(role_acc_ane, 4),
        "v0_laya_weights": fitted_val["v0_laya_weights"],
        "v0_laya_kev_weights": [0.44, 0.20, 0.36],
        "laya_raw_offset": fitted_val["laya_raw_offset"],
        "laya_raw_scale": fitted_val["laya_raw_scale"],
        "cascade_low": fitted_val["cascade_low"],
        "cascade_high": fitted_val["cascade_high"],
        "escalate_threshold": fitted_val["escalate_threshold"],
        "role_repair_min_defect": fitted_val["role_repair_min_defect"],
        "role_repair_min_prob": fitted_val["role_repair_min_prob"],
    }
    if fitted_val.get("stage1_cal_f1") is not None:
        val_cal_meta["stage1_cal_f1"] = fitted_val["stage1_cal_f1"]
    (artifacts_dir / "validator_v63_calibration.json").write_text(json.dumps(val_cal_meta, indent=2), encoding="utf-8")
    manifest_path = write_validators_manifest(artifacts_dir, bundle_version=bundle_version)
    print(
        f"      [Validator Cal={len(cal_thresh_records)}] Noul T={best_tn} (Brier={best_brier:.4f}) | "
        f"ANE Choice(16) Role Acc={role_acc_ane:.4f} | off={val_cal_meta['laya_raw_offset']} scale={val_cal_meta['laya_raw_scale']}"
    )
    print(f"      [Manifest] Wrote checksum manifest: {manifest_path}")
    return router_cal, val_cal_meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--train-jsonl",
        default=None,
        help="Path to train_v6_3_complete_ssot_gold.jsonl (required unless --write-manifest-only)",
    )
    ap.add_argument(
        "--base-laya-dir",
        default=None,
        help="Directory containing base Laya-Typed model.safetensors, encoder/config.json, rl_agent_config.json",
    )
    ap.add_argument(
        "--coreml-python",
        default=None,
        help="Python executable with coremltools installed for W8A16 ANE compilation",
    )
    ap.add_argument("--home", default=None, help="Package root override (defaults to packages/congress_docmeta)")
    ap.add_argument("--artifacts-dir", default=None, help="Override atomic_validators output directory")
    ap.add_argument(
        "--write-manifest-only",
        action="store_true",
        help="Compute and write atomic_validators_manifest.json checksums for an existing bundle without retraining",
    )
    ap.add_argument("--bundle-version", default="v6_3", help="Version tag written into atomic_validators_manifest.json")
    ap.add_argument(
        "--recalibrate-only",
        action="store_true",
        help="Re-run grouped split, Tier-0 linear router, live ANE Stage-6 calibration, and manifest without retraining Laya",
    )
    ap.add_argument(
        "--keep-linear-router",
        action="store_true",
        help="With --recalibrate-only, reuse existing router_v63_linear.npz instead of refitting it on train_split",
    )
    ap.add_argument("--steps", type=int, default=420, help="MLX fine-tuning steps on train_split")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--lr", type=float, default=3.5e-5)
    ap.add_argument("--distill-docs", type=int, default=320)
    ap.add_argument(
        "--pack-tokens",
        type=int,
        default=0,
        help="Enable varlen sequence packing into fixed token bins (e.g., 512 or 1024; 0 = unpacked)",
    )
    ap.add_argument(
        "--pack-bins",
        type=int,
        default=0,
        help="Packed bins per optimizer step when --pack-tokens > 0 (0 = auto-match --batch-size budget)",
    )
    ap.add_argument(
        "--cache-frozen-trunk",
        default=None,
        help="Optional directory to cache/stream frozen ModernBERT L0..17 BF16 boundary activations across epochs/sweeps",
    )
    ap.add_argument(
        "--freeze-below-layer",
        type=int,
        default=18,
        help="Freeze ModernBERT encoder layers below this index (default: 18 = 64%% frozen)",
    )
    ap.add_argument(
        "--no-teacher-prefix-reuse",
        action="store_true",
        help="Disable document-grouped prefix reuse for Kev-0.8B teacher scoring",
    )
    args = ap.parse_args()

    artifacts_dir = resolve_docmeta_validators_dir(args.artifacts_dir, home=args.home)
    if args.write_manifest_only:
        manifest_path = write_validators_manifest(artifacts_dir, bundle_version=args.bundle_version)
        print(f"[MANIFEST] Wrote checksum manifest: {manifest_path}")
        return 0

    req_flags: list[tuple[str, Any]] = [("--train-jsonl", args.train_jsonl)]
    if not args.recalibrate_only:
        req_flags.extend(
            [
                ("--base-laya-dir", args.base_laya_dir),
                ("--coreml-python", args.coreml_python),
            ]
        )
    for req_flag, req_val in req_flags:
        if not req_val:
            ap.error(f"{req_flag} is required unless --write-manifest-only is given")

    import mlx.core as mx
    import mlx.optimizers as optim

    repo_root = resolve_docmeta_pkg_root(args.home)
    laya_out_dir = artifacts_dir / "laya_typed"

    print(f"[1/6] Loading and splitting {args.train_jsonl} ...")
    raw_lines = Path(args.train_jsonl).expanduser().resolve().read_text(encoding="utf-8").splitlines()
    all_records = [parse_v4_prompt_row(json.loads(ln)) for ln in raw_lines if ln.strip()]
    print(f"      Parsed {len(all_records)} gold records across {len({r['router_class'] for r in all_records})} router classes.")

    train_records, cal_records = split_records_grouped_stratified(
        all_records, target_cal=560, seed=20261116, min_train_per_class=1
    )
    cal_thresh_records, early_stop_records = split_cal_records_disjoint(
        cal_records, early_stop_frac=0.25, seed=20261117
    )
    print(
        f"      Split: train={len(train_records)} docs | early_stop={len(early_stop_records)} docs | "
        f"cal_thresh={len(cal_thresh_records)} docs (0 group/text overlap)."
    )

    router_npz_path = artifacts_dir / "router_v63_linear.npz"
    if args.recalibrate_only and args.keep_linear_router and router_npz_path.is_file():
        npz_r = np.load(router_npz_path, allow_pickle=False)
        W_full = np.asarray(npz_r["W_f16"], dtype=np.float32)
        b_full = np.asarray(npz_r["b_f32"], dtype=np.float32)
        lin_temp = float(npz_r["temperature"])
        print(f"[2/6] Reusing existing {router_npz_path} (T={lin_temp:.4f}).")
    else:
        print("[2/6] Training Tier-0 Linear Router (`router_v63_linear.npz`, D=12,288, C=54)...")
        X_train = build_dense_feature_matrix(train_records, dim=12288)
        y_train = np.array([ROUTER_CLASS_TO_IDX[r["router_class"]] for r in train_records], dtype=np.int32)
        oof_logits = np.zeros((len(train_records), len(ROUTER_CLASSES)), dtype=np.float32)
        with acquire_hw_lock("train_v63_linear_router"):
            for fold in range(5):
                val_m = (np.arange(len(train_records)) % 5) == fold
                tr_m = ~val_m
                W_f, b_f = train_linear_router_mlx(X_train[tr_m], y_train[tr_m], len(ROUTER_CLASSES))
                oof_logits[val_m] = X_train[val_m] @ W_f.T + b_f
            lin_temp = fit_temperature_np(oof_logits, y_train)
            W_full, b_full = train_linear_router_mlx(X_train, y_train, len(ROUTER_CLASSES))

        np.savez_compressed(
            router_npz_path,
            W_f16=W_full.astype(np.float16),
            b_f32=b_full.astype(np.float32),
            classes=np.array(ROUTER_CLASSES),
            dim=np.int32(12288),
            temperature=np.float32(lin_temp),
        )

    dylib_p = ensure_laya_dylib()
    if args.recalibrate_only:
        with acquire_hw_lock("recalibrate_v63_live_ane"):
            laya_v63 = LayaAneBackend(laya_out_dir, dylib_p, pipe_depth=4)
            try:
                plans = laya_v63.inspect_compute_plans()
                print(f"      Live CoreML ANE Plans: {plans}")
                for btag, (ane_ops, gpu_ops, _cpu) in plans.items():
                    assert gpu_ops == 0 and ane_ops > 1000, f"Invalid plan on {btag}: {plans}"
                calibrate_stage6_bundle(
                    artifacts_dir,
                    train_count=len(train_records),
                    cal_thresh_records=cal_thresh_records,
                    W_full=W_full,
                    b_full=b_full,
                    lin_temp=lin_temp,
                    laya_v63=laya_v63,
                    bundle_version=args.bundle_version,
                )
            finally:
                laya_v63.close()
        print("[DONE] V6.3 bundle recalibrated on held-out split and manifest updated!")
        return 0

    base_laya_dir = Path(args.base_laya_dir).expanduser().resolve()
    X_es = build_dense_feature_matrix(early_stop_records, dim=12288)
    es_probs = softmax_np(X_es @ W_full.T + b_full, lin_temp)
    es_top6_Order = np.argsort(-es_probs, axis=-1)[:, :6]
    oof_top6: list[list[str]] = [
        [ROUTER_CLASSES[idx_c] for idx_c in np.argsort(-oof_logits[row_i])[:6]]
        for row_i in range(len(train_records))
    ]
    es_top6: list[list[str]] = [
        [ROUTER_CLASSES[idx_c] for idx_c in es_top6_Order[row_i]]
        for row_i in range(len(early_stop_records))
    ]

    # [3/6] Parity check + Build Multi-Task Dataset + Kev-0.8B W8 Teacher Distillation
    with acquire_hw_lock("train_v63_distill_and_lora"):
        laya_ane = LayaAneBackend(laya_out_dir, dylib_p, pipe_depth=4)
        enc_cfg = json.loads((base_laya_dir / "encoder" / "config.json").read_text(encoding="utf-8"))
        rl_cfg = json.loads((base_laya_dir / "rl_agent_config.json").read_text(encoding="utf-8"))
        raw_mx = mx.load(str(base_laya_dir / "model.safetensors"))
        frozen_w, train_params, forward_fn = build_mlx_laya_trainer(
            raw_mx, enc_cfg, freeze_below_layer=args.freeze_below_layer
        )
        laya_model: LayaMlxModel = forward_fn.model

        # Verify MLX forward parity against live CoreML ANE W8A16 before training!
        probe_st, probe_qs = build_atomic_doc_questions_v6(train_records[0]["gold"], train_records[0])
        probe_enc = laya_encode_ignore_truncation(laya_ane, probe_st, probe_qs[0])
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

        kev_teacher = Kev08bMlxBackend(artifacts_dir / "kev_08b", quant_mode="w8", batch_docs=8) if args.distill_docs > 0 else None
        train_items = synthesize_training_examples(
            train_records,
            oof_top6,
            laya_ane,
            kev_teacher,
            distill_docs=args.distill_docs,
            seed=20261116,
            reuse_doc_prefix=not args.no_teacher_prefix_reuse,
        )
        early_stop_items = synthesize_training_examples(
            early_stop_records,
            es_top6,
            laya_ane,
            None,
            distill_docs=0,
            seed=20261117,
            reuse_doc_prefix=False,
        )
        random.Random(20261118).shuffle(early_stop_items)
        if kev_teacher is not None:
            kev_teacher.close()
            del kev_teacher
        laya_ane.close()

        print(f"      Built {len(train_items)} multi-task train items & {len(early_stop_items)} early-stop items.")
        temps_init = dict(rl_cfg["temperature_by_options"])
        temps_init["choice:11+"] = 1.0  # normal logit scale for 16-way role training!

        pre_metrics = eval_multi_task_loss(train_params, forward_fn, early_stop_items[:900], 50283, temps_init)
        print(f"      [Pre-Train early_stop metrics] {pre_metrics}")

        # [4/6] Fine-tune upper ModernBERT layers (freeze_below_layer..27) + BF16 Head + Scorer in MLX
        pack_tokens = int(args.pack_tokens)
        mode_desc = (
            f"varlen pack_tokens={pack_tokens}"
            if pack_tokens > 0
            else f"unpacked B={args.batch_size}"
        )
        cache_desc = f", frozen_cache={args.cache_frozen_trunk}" if args.cache_frozen_trunk else ""
        print(
            f"[4/6] Fine-tuning Laya-Typed-421M ({args.steps} steps, {mode_desc}, "
            f"freeze<{args.freeze_below_layer}, lr={args.lr}{cache_desc})..."
        )
        opt = optim.AdamW(learning_rate=args.lr, weight_decay=0.01)
        run_train_step = make_validator_train_step(laya_model, train_params, opt, max_grad_norm=1.0)

        valid_train_items = [it for it in train_items if len(it["markers"]) >= 2]
        frozen_cache: FrozenTrunkActivationCache | None = None
        if args.cache_frozen_trunk:
            t_c0 = time.perf_counter()
            frozen_cache = FrozenTrunkActivationCache(
                args.cache_frozen_trunk,
                hidden_size=laya_model.hidden_size,
                freeze_below_layer=args.freeze_below_layer,
            )
            hit = frozen_cache.ensure_populated(
                laya_model,
                valid_train_items,
                pad_id=50283,
                max_seq_len=512,
                pack_tokens=max(512, pack_tokens or 1024),
            )
            c_state = "HIT (0 frozen trunk FLOPs)" if hit else "BUILT"
            print(
                f"      [FrozenTrunkCache] {c_state} at {frozen_cache.cache_dir} "
                f"({len(valid_train_items)} items, {frozen_cache.meta.get('total_tokens', 0)} toks) "
                f"in {time.perf_counter() - t_c0:.1f}s."
            )

        short_indices = [idx for idx, it in enumerate(valid_train_items) if len(it["ids"]) <= 256]
        long_indices = [idx for idx, it in enumerate(valid_train_items) if len(it["ids"]) > 256]
        rng_tr = random.Random(20261116)

        B = args.batch_size
        K_MAX = 16
        pack_bins_per_step = (
            int(args.pack_bins)
            if args.pack_bins > 0
            else max(1, (B * 256) // max(1, pack_tokens))
        )
        packed_bins_pool: list[list[tuple[int, Mapping[str, Any]]]] = []
        packed_cursor = 0
        pack_epoch = 0

        best_nll = pre_metrics["mean_nll"]
        best_params = {k: np.asarray(v).copy() for k, v in train_params.items()}
        t_tr0 = time.perf_counter()
        tot_items_seen = 0
        tot_real_toks = 0

        try:
            for step in range(1, args.steps + 1):
                # Cosine LR decay with 30-step linear warmup
                if step <= 30:
                    cur_lr = args.lr * (step / 30.0)
                else:
                    prog_f = (step - 30) / float(max(1, args.steps - 30))
                    cur_lr = args.lr * (0.10 + 0.90 * 0.5 * (1.0 + math.cos(math.pi * prog_f)))

                if pack_tokens > 0:
                    if packed_cursor + pack_bins_per_step > len(packed_bins_pool):
                        pack_epoch += 1
                        packed_bins_pool = pack_validator_items(
                            valid_train_items,
                            pack_tokens=pack_tokens,
                            window_size=max(64, pack_bins_per_step * 16),
                            seed=20261116 + pack_epoch,
                            shuffle=True,
                        )
                        packed_cursor = 0
                        if pack_epoch == 1:
                            p_stats = compute_packing_stats(packed_bins_pool, pack_tokens)
                            print(f"      [VarlenPack] {p_stats} | bins/step={pack_bins_per_step}")
                    step_bins = packed_bins_pool[packed_cursor : packed_cursor + pack_bins_per_step]
                    packed_cursor += len(step_bins)
                    batch_dict = build_packed_batch(step_bins, pack_tokens=pack_tokens, pad_id=50283, k_max=K_MAX)
                else:
                    use_short = (step % 3 != 0 and len(short_indices) >= B) or len(long_indices) < B
                    idx_pool = short_indices if use_short else long_indices
                    S_b = 256 if use_short else 512
                    picked_idxs = rng_tr.sample(idx_pool, B)
                    picked_items = [valid_train_items[idx_i] for idx_i in picked_idxs]
                    batch_dict = build_unpacked_batch(
                        picked_items,
                        seq_len=S_b,
                        pad_id=50283,
                        k_max=K_MAX,
                        item_indices=picked_idxs,
                    )

                loss_val, n_step_items, n_step_toks = run_train_step(
                    batch_dict,
                    frozen_cache=frozen_cache,
                    cur_lr=cur_lr,
                )
                tot_items_seen += n_step_items
                tot_real_toks += n_step_toks

                if step % 105 == 0 or step == args.steps:
                    m_cal = eval_multi_task_loss(
                        train_params,
                        forward_fn,
                        early_stop_items[:900],
                        50283,
                        {"noul:2": 1.5, "choice:6-10": 1.0, "choice:11+": 1.0},
                    )
                    el = time.perf_counter() - t_tr0
                    print(
                        f"      step {step:3d}/{args.steps} ({el:.1f}s, {tot_items_seen / max(el, 1e-6):.1f} items/s, "
                        f"{tot_real_toks / max(el, 1e-6):.0f} tok/s) | train_loss={loss_val:.4f} | cal={m_cal}"
                    )
                    if m_cal["mean_nll"] < best_nll:
                        best_nll = m_cal["mean_nll"]
                        best_params = {k: np.asarray(v).copy() for k, v in train_params.items()}
        finally:
            if frozen_cache is not None:
                frozen_cache.close()

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

    # [6/6] Live ANE Verification + Fit `router_v63_calibration.json` & `validator_v63_calibration.json` on held-out slice!
    print("[6/6] Fitting live ANE calibration & precision-coverage thresholds on held-out cal_thresh split...")
    with acquire_hw_lock("calibrate_v63_live_ane"):
        laya_v63 = LayaAneBackend(laya_out_dir, dylib_p, pipe_depth=4)
        try:
            plans = laya_v63.inspect_compute_plans()
            print(f"      Live CoreML ANE Plans: {plans}")
            for btag, (ane_ops, gpu_ops, _cpu) in plans.items():
                assert gpu_ops == 0 and ane_ops > 1000, f"Invalid plan on {btag}: {plans}"

            calibrate_stage6_bundle(
                artifacts_dir,
                train_count=len(train_records),
                cal_thresh_records=cal_thresh_records,
                W_full=W_full,
                b_full=b_full,
                lin_temp=lin_temp,
                laya_v63=laya_v63,
                bundle_version=args.bundle_version,
            )
        finally:
            laya_v63.close()

    print("[DONE] All V6.3 artifacts trained, distilled, calibrated, and compiled to Pure ANE!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
