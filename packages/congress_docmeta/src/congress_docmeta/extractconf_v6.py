"""Pure-Python calibrated ``ExtractConf`` post-decode defect risk router (`extractconf_v6.py`).

Computes calibrated defect probabilities (`any_defect`, `personas`, `committees`,
`dates`, `primary_kind`) using zero-leakage structural, router, deterministic V0, and
optional pre-mask grammar telemetry (`FieldUncertaintySummary`) features at ~0 ms CPU
overhead and zero Stage-2 LLM/ANE calls.

Top-level import is 100% Python stdlib (``/usr/bin/python3 -B -I -S`` clean).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

DOCMETA_DIR = Path(__file__).resolve().parent
DEFAULT_EXTRACTCONF_CAL_PATH = DOCMETA_DIR / "extractconf_v64_calibration.json"

LENGTH_BUCKETS_V6: tuple[str, ...] = ("<=1.3k", "1.3k-3k", "3k-6k", ">6k")
EXTRACTCONF_FIELD_TARGETS_V6: tuple[str, ...] = ("personas", "committees", "dates", "primary_kind")

BASE_FEATURE_NAMES_V6: tuple[str, ...] = (
    "v0_risk_unit",
    "v0_kind_conflict",
    "v0_ungrounded_cmt",
    "v0_ungrounded_date",
    "v0_pers_max",
    "v0_act_err",
    "v0_cflow_err",
    "v0_omission_err",
    "v0_gist_miss",
    "laya_q1_logit",
    "laya_q2_logit",
    "laya_q3_logit",
    "laya_q4_min_logit",
    "laya_q5_logit",
    "laya_pers_max",
    "log1p_text_len",
    "is_kind_locked",
)

_TELEMETRY_FIELDS_V6: tuple[str, ...] = ("primary_kind", "committees", "date_spans", "doc_date", "personas")

EXTRACTCONF_EXTRA_FEATURES_V6: tuple[str, ...] = (
    "rf_top1_prob",
    "rf_margin_12",
    "rf_entropy_top3",
    "rf_mismatch_pass1",
    "rf_lock_is_top1",
    "ra_top1_prob",
    "ra_margin_12",
    "ra_entropy_top3",
    "ra_mismatch_pass1",
    "router_fast_ane_disagree",
    "ra_minus_rf_top1",
    "router_min_top1_prob",
    "has_mw_ane",
    "mw_ane_min_prob",
    "mw_ane_min_logit",
    "lb_le_1_3k",
    "lb_1_3k_3k",
    "lb_3k_6k",
    "lb_gt_6k",
    "is_long_gt_3000",
    "pred_empty_personas",
    "pred_empty_personas_on_hearing_or_witness",
    "pred_empty_committees",
    "pred_empty_committees_on_hearing",
    "pred_no_dates",
    "pred_no_doc_date",
    "pred_no_date_spans",
    "has_filename_date_cues",
    "filename_date_vs_missing_dates",
    "slug_kind_conflict",
    "n_personas",
    "log1p_n_personas",
    "n_personas_ge_2",
    "n_personas_ge_4",
    "has_unknown_role",
    "has_author_or_speaker_role",
    "has_witness_without_org_or_title",
    "n_committees",
    "has_subcommittees",
    "n_date_spans",
    "has_telemetry",
    "tel_mean_h_pre",
    "tel_max_h_pre",
    "tel_mean_neg_log_z",
    "tel_max_neg_log_z",
    "tel_min_z_valid",
    "tel_primary_kind_max_h",
    "tel_primary_kind_max_nlz",
    "tel_committees_max_h",
    "tel_committees_max_nlz",
    "tel_date_spans_max_h",
    "tel_date_spans_max_nlz",
    "tel_doc_date_max_h",
    "tel_doc_date_max_nlz",
    "tel_personas_max_h",
    "tel_personas_max_nlz",
)

EXTRACTCONF_FEATURE_NAMES_V6: tuple[str, ...] = BASE_FEATURE_NAMES_V6 + EXTRACTCONF_EXTRA_FEATURES_V6

_PERSONA_EXPECTED_KINDS = frozenset(
    {
        "hearing_transcript",
        "witness_statement",
        "member_opening_statement",
        "member_or_floor_statement",
        "qfr_request",
        "qfr_response",
        "letter_to_congress",
        "letter_from_members",
        "truth_in_testimony_disclosure",
        "witness_biography",
        "nominee_questionnaire_or_statement",
        "witness_list",
    }
)

_COMMITTEE_EXPECTED_KINDS = frozenset(
    {
        "hearing_transcript",
        "witness_statement",
        "member_opening_statement",
        "hearing_schedule_or_notice",
        "committee_report",
        "committee_print",
        "qfr_request",
        "qfr_response",
        "markup_transcript",
        "truth_in_testimony_disclosure",
        "committee_rules_or_roster",
        "subpoena_or_compulsory_process",
    }
)

_SPECIFIC_ROLE_KINDS = frozenset(
    {
        "hearing_transcript",
        "witness_statement",
        "letter_to_congress",
        "letter_from_members",
        "qfr_request",
        "qfr_response",
    }
)

_CANONICAL_ROLES = frozenset(
    {
        "witness",
        "author_or_speaker",
        "chair",
        "ranking_member",
        "presiding",
        "questioner",
        "sponsor",
        "cosponsor",
        "amendment_offeror",
        "nominee",
        "introducer",
        "sender",
        "recipient",
        "signatory",
        "staff",
        "party_or_investigator",
    }
)

_FILENAME_DATE_RE = re.compile(
    r"(?:19\d{2}|20\d{2})(?:[-_]?(?:0[1-9]|1[0-2])(?:[-_]?(?:0[1-9]|[12]\d|3[01]))?)?"
)
_SLUG_RULES: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = (
    (re.compile(r"(?:^|[-_])wstate(?:[-_.]|$)", re.I), frozenset({"witness_statement"})),
    (re.compile(r"(?:^|[-_])ttf(?:[-_.]|$)|truth[-_\s]+in[-_\s]+testimony", re.I), frozenset({"truth_in_testimony_disclosure"})),
    (re.compile(r"(?:^|[-_])bio(?:graphy)?(?:[-_.]|$)", re.I), frozenset({"witness_biography"})),
    (re.compile(r"^bills[-_]", re.I), frozenset({"bill_or_resolution_text", "amendment_text"})),
    (re.compile(r"^(?:h|s|c)rept[-_]|^crpt[-_]", re.I), frozenset({"committee_report", "conference_report"})),
    (re.compile(r"qfr|questions?[-_\s]+for[-_\s]+the[-_\s]+record", re.I), frozenset({"qfr_request", "qfr_response"})),
    (re.compile(r"opening[-_\s]+statement", re.I), frozenset({"member_opening_statement"})),
    (re.compile(r"witness[-_\s]+list", re.I), frozenset({"witness_list"})),
)


def _safe_logit(prob: float | None, default_prob: float = 0.5) -> float:
    p = float(default_prob if prob is None else prob)
    p = max(1e-4, min(1.0 - 1e-4, p))
    return float(math.log(p / (1.0 - p)))


def _length_bucket_from_len(text_len: int) -> str:
    if text_len <= 1300:
        return "<=1.3k"
    if text_len <= 3000:
        return "1.3k-3k"
    if text_len <= 6000:
        return "3k-6k"
    return ">6k"


def _detect_slug_kind_conflict(filename: str, primary_kind: str | None) -> float:
    fn = (filename or "").strip()
    pk = (primary_kind or "").strip()
    if not fn or not pk:
        return 0.0
    for rx, expected_kinds in _SLUG_RULES:
        if rx.search(fn) and pk not in expected_kinds:
            return 1.0
    return 0.0


def _router_stats(
    router_obj: Mapping[str, Any] | None,
    pass1_pk: str | None,
) -> tuple[float, float, float, float, float, str | None]:
    if not isinstance(router_obj, Mapping):
        return 0.5, 0.0, 0.5, 0.0, 0.0, None
    cands = router_obj.get("top_candidates") or []
    probs: list[float] = []
    for entry in cands:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            probs.append(max(0.0, float(entry[1])))
    top1_prob = float(
        router_obj.get("top1_prob")
        if router_obj.get("top1_prob") is not None
        else (probs[0] if probs else 0.5)
    )
    p2 = probs[1] if len(probs) >= 2 else max(0.0, 1.0 - top1_prob)
    margin_12 = max(0.0, top1_prob - p2)

    rem = max(0.0, 1.0 - sum(probs))
    dist = list(probs) + ([rem] if rem > 1e-9 else [])
    ent = 0.0
    for p in dist:
        if p > 1e-12:
            ent -= p * math.log(p)

    t1_cls = str(router_obj.get("top1_class") or "") or None
    mismatch = 1.0 if (t1_cls and pass1_pk and t1_cls != pass1_pk) else 0.0
    lock_type = str(router_obj.get("lock_type") or "")
    lock_is_top1 = 1.0 if ("top1" in lock_type or (lock_type == "croq_singleton" and top1_prob >= 0.90)) else 0.0
    return top1_prob, margin_12, ent, mismatch, lock_is_top1, t1_cls


def _extract_base_17_features(rec: Mapping[str, Any]) -> list[float]:
    v0 = rec.get("v0_raw") or {}
    lfp = rec.get("laya_field_probs") or {}
    l_pers = rec.get("laya_pers_defects") or []

    v0_risk = min(1.0, float(v0.get("atomic_risk_score") or 0.0) / 1.50)
    v0_pers = [float(x) for x in (v0.get("persona_defect_scores") or ())]
    q4_vals = [float(lfp[k]) for k in ("action_summary", "correspondence_flow", "disclosure") if k in lfp]

    return [
        v0_risk,
        1.0 if v0.get("kind_conflicts") else 0.0,
        1.0 if v0.get("ungrounded_committees") else 0.0,
        1.0 if v0.get("ungrounded_dates") else 0.0,
        max(v0_pers) if v0_pers else 0.0,
        1.0 if v0.get("action_summary_flags") else 0.0,
        1.0 if v0.get("correspondence_flow_flags") else 0.0,
        1.0 if v0.get("persona_omission_flags") else 0.0,
        float(v0.get("gist_miss_frac") or 0.0),
        _safe_logit(lfp.get("primary_kind"), 0.98),
        _safe_logit(lfp.get("committees"), 0.92),
        _safe_logit(lfp.get("gist"), 0.50),
        _safe_logit(min(q4_vals) if q4_vals else None, 0.90),
        _safe_logit(lfp.get("personas_omission"), 0.85),
        max([float(x) for x in l_pers], default=0.0),
        math.log1p(max(0, int(rec.get("text_len") or 0))),
        1.0 if rec.get("locked_primary_kind") else 0.0,
    ]


def extract_extractconf_features_v6(rec: Mapping[str, Any]) -> list[float]:
    """Extract 73-dimensional feature vector matching ``EXTRACTCONF_FEATURE_NAMES_V6``."""
    base_17 = _extract_base_17_features(rec)

    pred = rec.get("pass1_pred") if isinstance(rec.get("pass1_pred"), Mapping) else {}
    pk = str(pred.get("primary_kind") or "") or None
    fn = str(rec.get("filename") or "")
    text_len = max(0, int(rec.get("text_len") or 0))
    lb = str(rec.get("length_bucket") or _length_bucket_from_len(text_len))

    rf1, rfm, rfe, rf_mis, rf_lock1, rf_cls = _router_stats(rec.get("router_fast"), pk)
    ra1, ram, rae, ra_mis, _, ra_cls = _router_stats(rec.get("router_ane"), pk)
    r_disagree = 1.0 if (rf_cls and ra_cls and rf_cls != ra_cls) else 0.0

    mw_raw = rec.get("mw_ane_min_prob")
    if mw_raw is None and isinstance(rec.get("multi_window_ane"), Mapping):
        mw_obj = rec["multi_window_ane"]
        mw_raw = mw_obj.get("min_prob")
        if mw_raw is None and isinstance(mw_obj.get("field_probs"), Mapping):
            vals = [float(v) for v in mw_obj["field_probs"].values() if v is not None]
            mw_raw = min(vals) if vals else None
    has_mw = 1.0 if mw_raw is not None else 0.0
    mw_min_p = float(mw_raw) if mw_raw is not None else 0.5

    personas = pred.get("personas") if isinstance(pred.get("personas"), list) else []
    committees = pred.get("committees") if isinstance(pred.get("committees"), list) else []
    subcommittees = pred.get("subcommittees") if isinstance(pred.get("subcommittees"), list) else []
    date_spans = pred.get("date_spans") if isinstance(pred.get("date_spans"), list) else []
    doc_date = pred.get("doc_date")
    event_date = pred.get("event_date")
    due_date = pred.get("due_date")

    empty_personas = 1.0 if len(personas) == 0 else 0.0
    empty_personas_hw = 1.0 if (empty_personas and pk in _PERSONA_EXPECTED_KINDS) else 0.0
    empty_committees = 1.0 if len(committees) == 0 else 0.0
    empty_committees_h = 1.0 if (empty_committees and pk in _COMMITTEE_EXPECTED_KINDS) else 0.0

    no_doc_date = 1.0 if not (isinstance(doc_date, str) and doc_date.strip()) else 0.0
    no_date_spans = 1.0 if len(date_spans) == 0 else 0.0
    has_any_date = (not no_doc_date) or (not no_date_spans) or bool(event_date) or bool(due_date)
    no_dates = 0.0 if has_any_date else 1.0

    has_fn_date = 1.0 if _FILENAME_DATE_RE.search(fn) else 0.0
    fn_date_miss = 1.0 if (has_fn_date and (no_doc_date or no_date_spans)) else 0.0
    slug_conflict = _detect_slug_kind_conflict(fn, pk)

    n_p = len(personas)
    has_unknown_role = 0.0
    has_author_speaker = 0.0
    has_sparse_witness = 0.0
    for p in personas:
        if not isinstance(p, Mapping):
            has_unknown_role = 1.0
            continue
        role = p.get("role")
        if not isinstance(role, str) or role not in _CANONICAL_ROLES:
            has_unknown_role = 1.0
        elif role == "author_or_speaker":
            has_author_speaker = 1.0
            if pk in _SPECIFIC_ROLE_KINDS:
                has_unknown_role = 1.0
        if role == "witness" and not p.get("org") and not p.get("title"):
            has_sparse_witness = 1.0

    tel = rec.get("telemetry") if isinstance(rec.get("telemetry"), Mapping) else rec
    has_tel = 1.0 if (
        isinstance(rec.get("telemetry"), Mapping)
        or rec.get("tel_mean_h_pre") is not None
        or rec.get("tel_max_h_pre") is not None
    ) else 0.0

    def _tel_val(key: str) -> float:
        if not has_tel or not isinstance(tel, Mapping):
            return 0.0
        v = tel.get(key)
        return float(v) if v is not None else 0.0

    extra = [
        rf1,
        rfm,
        rfe,
        rf_mis,
        rf_lock1,
        ra1,
        ram,
        rae,
        ra_mis,
        r_disagree,
        ra1 - rf1,
        min(rf1, ra1),
        has_mw,
        mw_min_p,
        _safe_logit(mw_min_p, 0.5) if has_mw > 0.5 else 0.0,
        1.0 if lb == LENGTH_BUCKETS_V6[0] else 0.0,
        1.0 if lb == LENGTH_BUCKETS_V6[1] else 0.0,
        1.0 if lb == LENGTH_BUCKETS_V6[2] else 0.0,
        1.0 if lb == LENGTH_BUCKETS_V6[3] else 0.0,
        1.0 if text_len > 3000 else 0.0,
        empty_personas,
        empty_personas_hw,
        empty_committees,
        empty_committees_h,
        no_dates,
        no_doc_date,
        no_date_spans,
        has_fn_date,
        fn_date_miss,
        slug_conflict,
        float(n_p),
        math.log1p(n_p),
        1.0 if n_p >= 2 else 0.0,
        1.0 if n_p >= 4 else 0.0,
        has_unknown_role,
        has_author_speaker,
        has_sparse_witness,
        float(len(committees)),
        1.0 if len(subcommittees) > 0 else 0.0,
        float(len(date_spans)),
        has_tel,
        _tel_val("tel_mean_h_pre"),
        _tel_val("tel_max_h_pre"),
        _tel_val("tel_mean_neg_log_z"),
        _tel_val("tel_max_neg_log_z"),
        _tel_val("tel_min_z_valid"),
    ]
    for fk in _TELEMETRY_FIELDS_V6:
        extra.append(_tel_val(f"tel_{fk}_max_h"))
        extra.append(_tel_val(f"tel_{fk}_max_nlz"))

    feats = base_17 + extra
    if len(feats) != len(EXTRACTCONF_FEATURE_NAMES_V6):
        raise RuntimeError(f"ExtractConf feature length mismatch: {len(feats)} != {len(EXTRACTCONF_FEATURE_NAMES_V6)}")
    return feats


def build_extractconf_record_v6(
    *,
    filename: str = "",
    text_len: int = 0,
    pass1_pred: Mapping[str, Any] | None = None,
    pmeta: Mapping[str, Any] | None = None,
    anom: Mapping[str, Any] | None = None,
    router_decision: Mapping[str, Any] | None = None,
    telemetry: Any = None,
) -> dict[str, Any]:
    """Build a canonical feature input dict from live ``parquet_runner_v6`` row state."""
    locked_pk = pmeta.get("tier1_target_kind") if isinstance(pmeta, Mapping) else None
    locked_str = str(locked_pk) if isinstance(locked_pk, str) and locked_pk else None

    if router_decision is not None:
        rf_obj: Mapping[str, Any] | None = router_decision
    elif locked_str is not None:
        rf_obj = {
            "lock_spec": locked_str,
            "lock_type": "det_locked",
            "top1_class": locked_str,
            "top1_prob": 1.0,
            "top_candidates": [(locked_str, 1.0)],
        }
    else:
        rf_obj = None

    v0_raw: Mapping[str, Any] = {}
    if isinstance(anom, Mapping) and isinstance(anom.get("atomic_stdlib"), Mapping):
        v0_raw = anom["atomic_stdlib"]

    tel_flat: Mapping[str, Any] | None
    if telemetry is None:
        tel_flat = None
    elif hasattr(telemetry, "steps") and hasattr(telemetry, "to_flat_features"):
        tel_flat = telemetry.to_flat_features() if int(getattr(telemetry, "steps", 0)) > 0 else None
    elif isinstance(telemetry, Mapping):
        tel_flat = telemetry if int(telemetry.get("tel_steps", telemetry.get("steps", 1))) > 0 else None
    else:
        tel_flat = None

    return {
        "filename": str(filename or ""),
        "text_len": max(0, int(text_len)),
        "pass1_pred": pass1_pred if isinstance(pass1_pred, Mapping) else {},
        "locked_primary_kind": locked_str,
        "router_fast": rf_obj,
        "v0_raw": v0_raw,
        "telemetry": tel_flat,
    }


def _sigmoid_clamped(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, float(z)))))


def _predict_tree_one(node: Mapping[str, Any], feats: Sequence[float]) -> float:
    cur = node
    while not cur.get("is_leaf", False):
        idx = int(cur["feature_idx"])
        thr = float(cur["threshold"])
        cur = cur["left"] if feats[idx] <= thr else cur["right"]
    return float(cur.get("leaf_value", 0.0))


@dataclass(frozen=True)
class _CalibratedTargetHead:
    target_key: str
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    weights: tuple[float, ...]
    bias: float
    base_margin: float
    learning_rate: float
    trees: tuple[dict[str, Any], ...]
    gbdt_weight: float
    cal_temp: float
    cal_bias: float

    @classmethod
    def from_dict(cls, spec: Mapping[str, Any]) -> "_CalibratedTargetHead":
        lg = spec["logistic"]
        gb = spec["gbdt"]
        return cls(
            target_key=str(spec.get("target_key", "")),
            mean=tuple(float(x) for x in lg["mean"]),
            scale=tuple(float(x) if abs(float(x)) > 1e-12 else 1.0 for x in lg["scale"]),
            weights=tuple(float(x) for x in lg["weights"]),
            bias=float(lg["bias"]),
            base_margin=float(gb["base_margin"]),
            learning_rate=float(gb["learning_rate"]),
            trees=tuple(gb.get("trees") or ()),
            gbdt_weight=float(spec.get("gbdt_weight", 0.55)),
            cal_temp=float(spec.get("cal_temp", 1.0)),
            cal_bias=float(spec.get("cal_bias", 0.0)),
        )

    def predict_proba(self, feats: Sequence[float]) -> float:
        z_log = self.bias + sum(
            w * ((x - m) / s) for x, m, s, w in zip(feats, self.mean, self.scale, self.weights)
        )
        p_log = max(1e-5, min(1.0 - 1e-5, _sigmoid_clamped(z_log)))

        tree_sum = sum(_predict_tree_one(t, feats) for t in self.trees)
        z_gbdt = self.base_margin + self.learning_rate * tree_sum
        p_gbdt = max(1e-5, min(1.0 - 1e-5, _sigmoid_clamped(z_gbdt)))

        z_hyb = (1.0 - self.gbdt_weight) * math.log(p_log / (1.0 - p_log)) + self.gbdt_weight * math.log(
            p_gbdt / (1.0 - p_gbdt)
        )
        temp = self.cal_temp if abs(self.cal_temp) > 1e-6 else 1.0
        z_cal = (z_hyb / temp) + self.cal_bias
        return _sigmoid_clamped(z_cal)


class ExtractConfCalibratorV6:
    """Pure-Python inference runtime for calibrated ``ExtractConf`` per-doc & per-field risk."""

    def __init__(
        self,
        *,
        feature_names: Sequence[str],
        heads: Mapping[str, _CalibratedTargetHead],
        any_threshold: float = 0.65,
        field_thresholds: Mapping[str, float] | None = None,
        max_fields_per_doc: int = 2,
        source_telemetry: str = "",
    ) -> None:
        if tuple(feature_names) != EXTRACTCONF_FEATURE_NAMES_V6:
            raise ValueError(
                f"ExtractConf feature schema mismatch: expected {len(EXTRACTCONF_FEATURE_NAMES_V6)} features."
            )
        if "any_defect" not in heads:
            raise ValueError("ExtractConf calibration missing 'any_defect' target.")
        self.feature_names = tuple(feature_names)
        self._heads = dict(heads)
        self.any_threshold = float(any_threshold)
        self.field_thresholds = {
            fg: float((field_thresholds or {}).get(fg, 0.5))
            for fg in EXTRACTCONF_FIELD_TARGETS_V6
            if fg in self._heads
        }
        self.max_fields_per_doc = max(0, int(max_fields_per_doc))
        self.source_telemetry = str(source_telemetry)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExtractConfCalibratorV6":
        raw_targets = payload.get("targets") or {}
        heads = {name: _CalibratedTargetHead.from_dict(spec) for name, spec in raw_targets.items()}
        return cls(
            feature_names=payload.get("feature_names") or EXTRACTCONF_FEATURE_NAMES_V6,
            heads=heads,
            any_threshold=float(payload.get("any_threshold", 0.65)),
            field_thresholds=payload.get("field_thresholds") or {},
            max_fields_per_doc=int(payload.get("max_fields_per_doc", 2)),
            source_telemetry=str(payload.get("source_telemetry", "")),
        )

    def predict_features(self, feats: Sequence[float]) -> dict[str, Any]:
        if len(feats) != len(self.feature_names):
            raise ValueError(f"Expected {len(self.feature_names)} features, got {len(feats)}.")
        p_any = self._heads["any_defect"].predict_proba(feats)
        field_probs = {
            fg: round(float(self._heads[fg].predict_proba(feats)), 6)
            for fg in EXTRACTCONF_FIELD_TARGETS_V6
            if fg in self._heads
        }
        ranked = sorted(
            (fg for fg, p in field_probs.items() if p >= self.field_thresholds.get(fg, 0.5)),
            key=lambda fg: -(field_probs[fg] / max(self.field_thresholds.get(fg, 0.5), 1e-6)),
        )
        if not ranked and p_any >= self.any_threshold and field_probs:
            ranked = [max(field_probs.keys(), key=lambda fg: field_probs[fg])]
        selected_fields = ranked[: self.max_fields_per_doc]
        tel_idx = self.feature_names.index("has_telemetry")
        has_tel = bool(feats[tel_idx] > 0.5)
        return {
            "any_defect_prob": round(float(p_any), 6),
            "escalate_recommended": bool(p_any >= self.any_threshold or bool(selected_fields)),
            "flagged_fields": selected_fields,
            "field_probs": field_probs,
            "has_telemetry": has_tel,
            "source_regime": "fast+tel" if has_tel else "fast_no_tel",
        }

    def score_record(self, rec: Mapping[str, Any]) -> dict[str, Any]:
        feats = extract_extractconf_features_v6(rec)
        return self.predict_features(feats)

    def score_runtime_row(
        self,
        *,
        filename: str = "",
        text_len: int = 0,
        pass1_pred: Mapping[str, Any] | None = None,
        pmeta: Mapping[str, Any] | None = None,
        anom: Mapping[str, Any] | None = None,
        router_decision: Mapping[str, Any] | None = None,
        telemetry: Any = None,
    ) -> dict[str, Any]:
        rec = build_extractconf_record_v6(
            filename=filename,
            text_len=text_len,
            pass1_pred=pass1_pred,
            pmeta=pmeta,
            anom=anom,
            router_decision=router_decision,
            telemetry=telemetry,
        )
        return self.score_record(rec)


@lru_cache(maxsize=4)
def _load_cached_extractconf(path_str: str) -> ExtractConfCalibratorV6:
    payload = json.loads(Path(path_str).read_text(encoding="utf-8"))
    return ExtractConfCalibratorV6.from_dict(payload)


def load_bundled_extractconf_calibrator_v6(
    calibration_path: str | Path | None = None,
) -> ExtractConfCalibratorV6:
    """Load the bundled zero-leakage calibrated ``ExtractConfCalibratorV6`` (cached)."""
    resolved = Path(calibration_path) if calibration_path is not None else DEFAULT_EXTRACTCONF_CAL_PATH
    if not resolved.is_file():
        raise FileNotFoundError(f"Missing ExtractConf calibration artifact at {resolved}")
    return _load_cached_extractconf(str(resolved.resolve()))


__all__ = [
    "BASE_FEATURE_NAMES_V6",
    "DEFAULT_EXTRACTCONF_CAL_PATH",
    "EXTRACTCONF_EXTRA_FEATURES_V6",
    "EXTRACTCONF_FEATURE_NAMES_V6",
    "EXTRACTCONF_FIELD_TARGETS_V6",
    "ExtractConfCalibratorV6",
    "LENGTH_BUCKETS_V6",
    "build_extractconf_record_v6",
    "extract_extractconf_features_v6",
    "load_bundled_extractconf_calibrator_v6",
]
