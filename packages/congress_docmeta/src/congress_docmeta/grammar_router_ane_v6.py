#!/usr/bin/env python3
"""Pre-Decode Calibrated `Choice(47)` + `status(8)` Grammar Router (`grammar_router_ane_v6.py`).

Top-level import is 100% Python standard library (`/usr/bin/python3 -B -I -S` clean);
`numpy` and `fast_decision_models.LayaAneBackend` (`CoreML` Pure ANE `W8A16`, `0` Metal GPU ops) are loaded lazily.

Trained and out-of-fold calibrated on `train_v6_3_complete_ssot_gold.jsonl` (2,917 docs across all
47 `primary_kind` enums and 8 `status` enums, 100% disjoint from `val_48` and `docs_8`):
  - `"fast"` mode (`< 0.3 ms/doc` CPU): L2-regularized hashed masthead/slug/metadata/body n-gram
    classifier (`router_v63_linear.npz`) with temperature scaling.
  - `"ane"` mode (`0` GPU ops, Pure Apple Neural Engine): Tier-0 narrows 54 classes to Top-6
    confusable candidates, then `Laya-Typed-v63` runs 1 single-pass `Choice(6)` ANE forward pass on
    ambiguous open-kind rows and fuses calibrated probabilities to emit:
      * Single-kind `llguidance` lock (`"witness_statement"`) when `P(top1) >= tau_top1`
      * Narrowed Top-2 / Top-3 enum schema (`"external_submission_letter|oversight_letter"`) when
        cumulative probability exceeds calibrated `tau_top2` / `tau_top3`
      * Open `SCHEMA_V4_STR` (`None`) when genuinely ambiguous or predicted non-usable.
"""

from __future__ import annotations

import collections
import copy
from dataclasses import dataclass
from decimal import Decimal
import json
import math
from pathlib import Path
import re
from typing import Any, Literal, Mapping, Sequence

from .atomic_validator_v6 import (
    ALL_KIND_DESC_V6,
    _supports_kwarg,
    laya_encode_ignore_truncation,
    verify_validators_manifest,
)
from .pythonic_v5 import DOC_KINDS_SET, SCHEMA_OBJ
from .pythonic_v6 import clean_html_and_cms_v6, infer_is_html_v6

RouterMode = Literal["fast", "ane"]
ScoreMode = Literal["aps_det", "lac", "raps_det"]
CANONICAL_CROQ_KINDS: tuple[str, ...] = tuple(sorted(DOC_KINDS_SET))
_TOK_RE = re.compile(r"[a-z0-9_]{2,}")


def build_doc_kind_set_schema_v6(
    allowed_kinds: Sequence[str],
    base_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build `DocMetaV4Causal` JSON schema locking `status='usable'` and `primary_kind` to `allowed_kinds`."""
    deduped = list(dict.fromkeys(str(k).strip() for k in allowed_kinds if str(k).strip() in DOC_KINDS_SET))
    if not deduped:
        raise ValueError(f"allowed_kinds must contain >=1 valid doc_kind, got {allowed_kinds!r}")
    schema = copy.deepcopy(base_schema if base_schema is not None else SCHEMA_OBJ)
    if len(deduped) == 1 and deduped[0] == "truth_in_testimony_disclosure":
        schema["required"] = [
            "status",
            "text_quality",
            "primary_kind",
            "disclosure",
            "composed_title",
            "gist",
            "topics",
        ]
        schema["properties"]["disclosure"]["minProperties"] = 1
        schema["properties"]["disclosure"]["required"] = ["capacity", "gov_witness"]
    else:
        schema["required"] = [
            "status",
            "text_quality",
            "primary_kind",
            "composed_title",
            "gist",
            "topics",
        ]
    schema["properties"]["status"] = {"type": "string", "enum": ["usable"]}
    schema["properties"]["primary_kind"] = {"type": "string", "enum": deduped}
    if len(deduped) == 1:
        sec_enum = [k for k in schema["$defs"]["doc_kind"]["enum"] if k != deduped[0]]
        schema["properties"]["secondary_kinds"]["items"] = {"type": "string", "enum": sec_enum}
    return schema


def is_valid_kind_lock_spec_v6(spec: str | None) -> bool:
    if not spec or not isinstance(spec, str):
        return False
    parts = [p.strip() for p in spec.split("|") if p.strip()]
    return bool(parts) and all(p in DOC_KINDS_SET for p in parts)


def extract_router_sparse_features_v6(
    filename: str,
    known: str,
    raw_text: str,
    clean_text: str,
    dim: int = 12288,
) -> tuple[list[int], list[float]]:
    """Deterministic FNV-1a hashed masthead/slug/metadata/body feature extractor (`100%` stdlib)."""
    counts: dict[int, float] = {}

    def _add(feat: str, weight: float = 1.0) -> None:
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

    if n_chars >= 40:
        alpha_n = sum(1 for ch in clean_text[:800] if ch.isalpha())
        ratio = alpha_n / float(min(n_chars, 800))
        if ratio < 0.35:
            _add("__LOW_ALPHA_GARBLED__", 3.0)
        elif ratio < 0.55:
            _add("__MED_ALPHA_OCR__", 1.6)

    fn_parts = re.findall(r"[a-z]{2,}|[0-9]{3,4}", fn_l)
    for p in fn_parts[:24]:
        _add(f"fn:{p}", 2.2)
    for i in range(len(fn_parts) - 1):
        _add(f"fn2:{fn_parts[i]}_{fn_parts[i+1]}", 2.0)

    for kt in _TOK_RE.findall(kn_l)[:24]:
        _add(f"kn:{kt}", 1.4)

    mast_toks = _TOK_RE.findall(txt_l[:550])
    for w in mast_toks[:90]:
        _add(f"mh:{w}", 1.8)
    for i in range(min(85, len(mast_toks) - 1)):
        _add(f"mh2:{mast_toks[i]}_{mast_toks[i+1]}", 2.1)
    for i in range(min(60, len(mast_toks) - 2)):
        _add(f"mh3:{mast_toks[i]}_{mast_toks[i+1]}_{mast_toks[i+2]}", 1.9)

    body_sample = txt_l[:2400] + ("\n" + txt_l[-700:] if len(txt_l) > 2800 else "")
    b_toks = _TOK_RE.findall(body_sample)
    tf = collections.Counter(b_toks[:450])
    for w, c in tf.items():
        _add(f"bd:{w}", 1.0 + math.log(float(c)))
    b_seq = b_toks[:260]
    for i in range(len(b_seq) - 1):
        _add(f"bd2:{b_seq[i]}_{b_seq[i+1]}", 1.15)

    if not counts:
        return [], []
    idxs = list(counts.keys())
    vals = list(counts.values())
    norm = math.sqrt(sum(v * v for v in vals))
    if norm > 1e-6:
        inv = 1.0 / norm
        vals = [v * inv for v in vals]
    return idxs, vals


def _build_router_choice_query(
    filename: str,
    known_str: str,
    clean_text: str,
    top_classes: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    crit: dict[str, str] = {}
    for cls_name in top_classes:
        if cls_name.startswith("status:"):
            st_name = cls_name.split(":", 1)[1]
            crit[cls_name] = f"non-usable {st_name} container (blank, unreadable OCR, catalog XML, or error shell)"
        else:
            crit[cls_name] = ALL_KIND_DESC_V6.get(cls_name, cls_name)
    head = clean_text[:1000]
    tail = ("\n...\n" + clean_text[-320:]) if len(clean_text) > 1400 else ""
    state = {
        "filename": filename or "<NONE>",
        "known_metadata": known_str or "<NONE>",
        "text_chars": len(clean_text),
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


def fuse_top6_router_probs(
    probs: Any,
    top6_order: Any,
    ane_ois: Sequence[int],
    ane_p_list: Sequence[Sequence[float]],
    fusion_alpha: float,
) -> Any:
    """Blend linear Top-6 conditional posteriors with ANE `Choice(6)` probabilities, preserving tail mass."""
    import numpy as np

    out = np.array(probs, copy=True)
    alpha = max(0.0, min(1.0, float(fusion_alpha)))
    for oi, p6 in zip(ane_ois, ane_p_list):
        top6 = top6_order[oi]
        k = min(len(top6), len(p6))
        if k == 0:
            continue
        cand_idx = top6[:k]
        raw_lin = np.clip(out[oi, cand_idx].astype(np.float64), 1e-8, 1.0)
        m_top = float(np.sum(out[oi, cand_idx]))
        p_lin_cond = raw_lin / max(float(np.sum(raw_lin)), 1e-12)
        raw_ane = np.clip(np.asarray(p6[:k], dtype=np.float64), 1e-8, 1.0)
        p_ane_cond = raw_ane / max(float(np.sum(raw_ane)), 1e-12)
        log_blend = alpha * np.log(p_lin_cond) + (1.0 - alpha) * np.log(p_ane_cond)
        log_blend -= np.max(log_blend)
        p_post = np.exp(log_blend)
        p_post /= np.sum(p_post)
        out[oi, cand_idx] = (m_top * p_post).astype(out.dtype)
        row_sum = float(np.sum(out[oi]))
        if row_sum > 0.0:
            out[oi] = (out[oi] / row_sum).astype(out.dtype)
    return out


class PreDecodeGrammarRouterV6:
    """Calibrated Pre-Decode Grammar Router (`fast` linear CPU + CROQ or `ane` Top-6 `Laya-Typed` ANE)."""

    def __init__(
        self,
        mode: RouterMode = "fast",
        *,
        home: str | Path | None = None,
        artifacts_dir: str | Path | None = None,
        shared_laya_backend: Any = None,
        tau_top1: float | None = None,
        tau_top2: float | None = None,
        tau_top3: float | None = None,
        allow_multi_kind_set: bool = True,
        pipe_depth: int = 4,
        verify_manifest: bool | str = "if_present",
        use_croq: bool | str = "auto",
        croq_alpha: float = 0.05,
        croq_max_lock_k: int = 4,
        croq_calibration_path: str | Path | None = None,
    ) -> None:
        import numpy as np

        if mode not in ("fast", "ane"):
            raise ValueError(f"Unsupported router mode={mode!r}; expected 'fast' or 'ane'.")
        self._np = np
        self.mode: RouterMode = mode
        self.allow_multi_kind_set = bool(allow_multi_kind_set)

        from .atomic_validator_v6 import resolve_docmeta_pkg_root, resolve_docmeta_validators_dir

        self.home_dir = resolve_docmeta_pkg_root(home)
        self.artifacts_dir = resolve_docmeta_validators_dir(artifacts_dir, home=home)
        self.manifest_status = verify_validators_manifest(self.artifacts_dir, mode=verify_manifest)

        npz_path = self.artifacts_dir / "router_v63_linear.npz"
        cal_path = self.artifacts_dir / "router_v63_calibration.json"
        if not npz_path.is_file():
            raise FileNotFoundError(
                f"Missing {npz_path}. Run scripts/train_v63_validators.py to build V6.3 router artifacts."
            )
        npz = np.load(npz_path, allow_pickle=False)
        self.W_f32 = npz["W_f16"].astype(np.float32)
        self.b_f32 = npz["b_f32"].astype(np.float32)
        self.classes: list[str] = [str(x) for x in npz["classes"].tolist()]
        self.dim = int(npz["dim"])
        self.linear_temp = float(npz["temperature"])

        cal: dict[str, Any] = (
            json.loads(cal_path.read_text(encoding="utf-8")) if cal_path.is_file() else {}
        )
        self.fusion_alpha = float(cal.get("fusion_linear_alpha", 0.45))
        self.ane_choice_temp = float(cal.get("ane_choice_temperature", 1.0))
        if mode == "ane":
            t1_def = cal.get("ane_tau_top1", 0.85)
            t2_def = cal.get("ane_tau_top2", 0.90)
            t3_def = cal.get("ane_tau_top3", 0.93)
        else:
            t1_def = cal.get("fast_linear_tau_top1", 0.90)
            t2_def = cal.get("fast_linear_tau_top2", max(float(t1_def), 0.90))
            t3_def = cal.get("fast_linear_tau_top3", max(float(t2_def), 0.93))
        self.tau_top1 = float(tau_top1 if tau_top1 is not None else t1_def)
        self.tau_top2 = max(self.tau_top1, float(tau_top2 if tau_top2 is not None else t2_def))
        self.tau_top3 = max(self.tau_top2, float(tau_top3 if tau_top3 is not None else t3_def))

        self.croq_router: ConformalKindRouter | None = None
        self._croq_kind_indices: list[int] = []
        wants_croq: bool
        if isinstance(use_croq, str):
            if use_croq != "auto":
                raise ValueError(f"Unsupported use_croq={use_croq!r}; expected bool or 'auto'.")
            wants_croq = (
                mode == "fast"
                and self.allow_multi_kind_set
                and tau_top1 is None
                and tau_top2 is None
                and tau_top3 is None
                and set(CANONICAL_CROQ_KINDS).issubset(self.classes)
            )
        else:
            wants_croq = bool(use_croq)

        if wants_croq:
            missing_kinds = [k for k in CANONICAL_CROQ_KINDS if k not in self.classes]
            if missing_kinds:
                raise ValueError(
                    f"Conformal CROQ requires all 47 canonical kinds in router classes; missing {missing_kinds[:5]!r}"
                )
            self.croq_router = load_bundled_croq_router_v6(
                croq_calibration_path,
                alpha=croq_alpha,
                max_lock_k=croq_max_lock_k,
            )
            cls_idx = {c: i for i, c in enumerate(self.classes)}
            self._croq_kind_indices = [cls_idx[k] for k in self.croq_router.kinds]

        self._owns_laya = False
        self.laya_backend: Any = None
        if mode == "ane":
            if shared_laya_backend is not None:
                self.laya_backend = shared_laya_backend
            else:
                from fast_decision_models import LayaAneBackend
                from fast_decision_models.paths import ensure_laya_dylib

                dylib_p = ensure_laya_dylib()
                self.laya_backend = LayaAneBackend(
                    self.artifacts_dir / "laya_typed",
                    dylib_p,
                    pipe_depth=pipe_depth,
                )
                self._owns_laya = True

    @staticmethod
    def _extract_row_fields(
        row: Mapping[str, Any],
        pmeta: Mapping[str, Any] | None = None,
    ) -> tuple[str, str, str, str]:
        fn = str(row.get("filename") or "")
        kn_raw = row.get("known") if row.get("known") is not None else row.get("known_json")
        if kn_raw is None and isinstance(pmeta, Mapping) and isinstance(pmeta.get("known_dict"), Mapping):
            kn_raw = pmeta["known_dict"]
        if isinstance(kn_raw, Mapping):
            kn_str = json.dumps(dict(kn_raw), separators=(",", ":"), ensure_ascii=False) if kn_raw else "<NONE>"
        elif isinstance(kn_raw, str) and kn_raw.strip():
            kn_str = kn_raw.strip()
        else:
            kn_str = "<NONE>"
        raw_txt = str(row.get("p12_raw_text") or row.get("text") or row.get("p12_clean_text") or "")
        # Reuse precomputed V6 cleaned text from `pmetas[i]` when available instead of re-stripping HTML.
        clean_txt: Any = None
        if isinstance(pmeta, Mapping):
            clean_txt = pmeta.get("clean_text_v6") or pmeta.get("p12_lines")
        if not isinstance(clean_txt, str) or not clean_txt:
            clean_txt = row.get("p12_clean_text")
        if not isinstance(clean_txt, str) or not clean_txt:
            clean_txt = raw_txt
            is_h = (
                bool(pmeta.get("is_html"))
                if (isinstance(pmeta, Mapping) and "is_html" in pmeta)
                else infer_is_html_v6(fn, clean_txt, explicit_format=row.get("effective_format") or row.get("format"))
            )
            if is_h:
                stripped, _, _ = clean_html_and_cms_v6(clean_txt, is_html=True)
                if stripped:
                    clean_txt = stripped
            clean_txt = re.sub(r"[ \t]+", " ", clean_txt)
            clean_txt = re.sub(r"\n{3,}", "\n\n", clean_txt).strip()
        return fn, kn_str, raw_txt, clean_txt

    def _softmax_rows(self, logits_2d: Any, temp: float) -> Any:
        np = self._np
        z = logits_2d / max(temp, 1e-4)
        z = z - np.max(z, axis=-1, keepdims=True)
        ez = np.exp(z)
        return ez / np.sum(ez, axis=-1, keepdims=True)

    def route_chunk(
        self,
        chunk: Sequence[Mapping[str, Any]],
        pmetas: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Predict calibrated `lock_spec` (`str | None`) across `chunk`, preserving deterministic locks."""
        np = self._np
        n = len(chunk)
        if n == 0:
            return []

        results: list[dict[str, Any]] = [
            {"lock_spec": None, "lock_type": "open", "top1_class": None, "top1_prob": 0.0, "top_candidates": []}
            for _ in range(n)
        ]
        open_indices: list[int] = []
        open_fields: list[tuple[str, str, str, str]] = []

        for i in range(n):
            pm = pmetas[i] if (pmetas is not None and i < len(pmetas) and isinstance(pmetas[i], Mapping)) else {}
            row = chunk[i]
            if pm.get("triage") is not None:
                results[i] = {
                    "lock_spec": None,
                    "lock_type": "triage",
                    "top1_class": f"status:{pm['triage']['docmeta'].get('status', 'stub_or_blank')}",
                    "top1_prob": 1.0,
                    "top_candidates": [],
                }
                continue
            det_tk = pm.get("tier1_target_kind") or row.get("locked_primary_kind")
            if isinstance(det_tk, str) and det_tk in DOC_KINDS_SET:
                results[i] = {
                    "lock_spec": det_tk,
                    "lock_type": "det_locked",
                    "top1_class": det_tk,
                    "top1_prob": 1.0,
                    "top_candidates": [(det_tk, 1.0)],
                }
                continue
            open_indices.append(i)
            open_fields.append(self._extract_row_fields(row, pm))

        if not open_indices:
            return results

        X = np.zeros((len(open_indices), self.dim), dtype=np.float32)
        for oi, (fn, kn_s, r_txt, c_txt) in enumerate(open_fields):
            idxs, vals = extract_router_sparse_features_v6(fn, kn_s, r_txt, c_txt, dim=self.dim)
            if idxs:
                X[oi, idxs] = vals

        lin_logits = X @ self.W_f32.T + self.b_f32
        probs = self._softmax_rows(lin_logits, self.linear_temp)
        top6_order = np.argsort(-probs, axis=-1)[:, :6]

        if self.mode == "ane" and self.laya_backend is not None:
            # Skip ANE on open rows where Tier-0 linear router already has >=0.985 certainty!
            laya_enc_kw = (
                {"on_truncate": "ignore"}
                if _supports_kwarg(self.laya_backend.encode_item, "on_truncate")
                else {}
            )
            ane_ois: list[int] = []
            ane_encs: list[dict[str, Any]] = []
            for oi in range(len(open_indices)):
                if float(np.max(probs[oi])) >= 0.985:
                    continue
                fn, kn_s, _r_txt, c_txt = open_fields[oi]
                cand6 = [self.classes[int(c_i)] for c_i in top6_order[oi]]
                st_r, q_r = _build_router_choice_query(fn, kn_s, c_txt, cand6)
                ane_encs.append(
                    laya_encode_ignore_truncation(self.laya_backend, st_r, q_r, encode_kw=laya_enc_kw)
                )
                ane_ois.append(oi)

            if ane_encs:
                ane_p_list = self.laya_backend.score_choice_batch(ane_encs, temperature_override=self.ane_choice_temp)
                probs = fuse_top6_router_probs(probs, top6_order, ane_ois, ane_p_list, self.fusion_alpha)

        for oi, orig_i in enumerate(open_indices):
            p_row = probs[oi]
            order = np.argsort(-p_row)
            c0 = self.classes[int(order[0])]
            p0 = float(p_row[int(order[0])])
            c1 = self.classes[int(order[1])]
            p1 = float(p_row[int(order[1])])
            c2 = self.classes[int(order[2])]
            p2 = float(p_row[int(order[2])])

            lock_spec: str | None = None
            lock_type = "open"
            tag_prefix = "ane" if self.mode == "ane" else "fast"
            croq_dec_dict: dict[str, Any] | None = None

            if self.croq_router is not None:
                if c0.startswith("status:") or c0 not in DOC_KINDS_SET:
                    lock_type = "croq_open_status"
                else:
                    p47 = [float(p_row[idx_c]) for idx_c in self._croq_kind_indices]
                    croq_dec = self.croq_router.route_one(p47)
                    lock_spec = croq_dec.lock_spec
                    lock_type = croq_dec.lock_type
                    croq_dec_dict = croq_dec.to_dict()
            else:
                if not c0.startswith("status:") and c0 in DOC_KINDS_SET and p0 >= self.tau_top1:
                    lock_spec = c0
                    lock_type = f"{tag_prefix}_top1"
                elif (
                    self.allow_multi_kind_set
                    and not c0.startswith("status:")
                    and not c1.startswith("status:")
                    and (p0 + p1) >= self.tau_top2
                ):
                    lock_spec = "|".join(sorted((c0, c1)))
                    lock_type = f"{tag_prefix}_top2"
                elif (
                    self.allow_multi_kind_set
                    and not c0.startswith("status:")
                    and not c1.startswith("status:")
                    and not c2.startswith("status:")
                    and (p0 + p1 + p2) >= self.tau_top3
                ):
                    lock_spec = "|".join(sorted((c0, c1, c2)))
                    lock_type = f"{tag_prefix}_top3"

            row_res: dict[str, Any] = {
                "lock_spec": lock_spec,
                "lock_type": lock_type,
                "top1_class": c0,
                "top1_prob": round(p0, 4),
                "top_candidates": [
                    (self.classes[int(order[k])], round(float(p_row[int(order[k])]), 4))
                    for k in range(min(3, len(order)))
                ],
            }
            if croq_dec_dict is not None:
                row_res["conformal_set"] = croq_dec_dict["conformal_set"]
                row_res["set_size"] = croq_dec_dict["set_size"]
                row_res["set_prob_mass"] = croq_dec_dict["set_prob_mass"]
                row_res["q_hat"] = croq_dec_dict["q_hat"]
                row_res["croq_decision"] = croq_dec_dict
            results[orig_i] = row_res

        return results

    def close(self) -> None:
        if self._owns_laya and self.laya_backend is not None:
            self.laya_backend.close()
            self.laya_backend = None

    def __enter__(self) -> "PreDecodeGrammarRouterV6":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def split_conformal_quantile(scores: Sequence[float] | Any, alpha: float) -> float:
    """Exact finite-sample split conformal quantile `ceil((n + 1)(1 - alpha))`-th order statistic.

    Uses exact `Decimal` arithmetic so binary float rounding never under-selects the rank.
    Returns `+inf` when `ceil((n + 1)(1 - alpha)) > n` so finite-sample coverage
    `>= 1 - alpha` holds even on small calibration splits (`n < 1/alpha - 1`).
    """
    if hasattr(scores, "ravel"):
        flat = [float(x) for x in scores.ravel().tolist()]
    else:
        flat = [float(x) for x in scores]
    n = len(flat)
    if n == 0:
        raise ValueError("Calibration score sequence must be non-empty.")
    if not (0.0 < float(alpha) < 1.0):
        raise ValueError(f"alpha must lie strictly in (0, 1), got {alpha!r}.")
    if any(not math.isfinite(x) for x in flat):
        raise ValueError("Calibration scores must be finite.")

    target = Decimal(n + 1) * (Decimal("1") - Decimal(str(alpha)))
    rank = int(math.ceil(target))
    if rank <= 0:
        return float("-inf")
    if rank > n:
        return float("inf")
    flat.sort()
    return float(flat[rank - 1])


def _normalize_prob_row(row: Sequence[float] | Any, n_classes: int | None = None) -> list[float]:
    if hasattr(row, "tolist"):
        vals = [float(x) for x in row.tolist()]
    else:
        vals = [float(x) for x in row]
    k = n_classes if n_classes is not None else len(vals)
    if len(vals) != k:
        raise ValueError(f"Expected probability vector of length {k}, got {len(vals)}.")
    clean = [v if math.isfinite(v) and v > 0.0 else 0.0 for v in vals]
    s = sum(clean)
    if s > 0.0:
        return [v / s for v in clean]
    return [1.0 / max(1, k)] * k


def _row_nonconformity_scores(
    probs_row: list[float],
    *,
    score_mode: ScoreMode = "aps_det",
    k_reg: int = 4,
    lam: float = 0.05,
) -> tuple[list[float], list[int]]:
    """Return `(scores_by_class_idx, order_desc_indices)` for one normalized probability vector."""
    n_c = len(probs_row)
    order = sorted(range(n_c), key=lambda idx: (-probs_row[idx], idx))
    scores = [0.0] * n_c
    cprev = 0.0
    for rank_0, cls_idx in enumerate(order):
        p = probs_row[cls_idx]
        if score_mode == "lac":
            s_val = 1.0 - p
        elif score_mode == "aps_det":
            s_val = cprev
        elif score_mode == "raps_det":
            s_val = cprev + float(lam) * max(0.0, float(rank_0 + 1 - k_reg))
        else:
            raise ValueError(f"Unsupported score_mode={score_mode!r}")
        scores[cls_idx] = s_val
        cprev += p
    return scores, order


def compute_class_nonconformity_scores(
    probs: Sequence[Sequence[float]] | Any,
    *,
    score_mode: ScoreMode = "aps_det",
    k_reg: int = 4,
    lam: float = 0.05,
) -> Any:
    """Compute per-class nonconformity score matrix matching `probs` shape `(N, K)`."""
    if hasattr(probs, "ndim"):
        import numpy as np

        p_arr = np.asarray(probs, dtype=np.float64)
        if p_arr.ndim != 2:
            raise ValueError(f"Expected 2D probability matrix, got shape {p_arr.shape!r}.")
        out = np.empty_like(p_arr)
        n_c = p_arr.shape[1]
        for i in range(p_arr.shape[0]):
            norm_r = _normalize_prob_row(p_arr[i], n_c)
            row_s, _ = _row_nonconformity_scores(norm_r, score_mode=score_mode, k_reg=k_reg, lam=lam)
            out[i] = row_s
        return out

    rows_out: list[list[float]] = []
    for row in probs:
        norm_r = _normalize_prob_row(row)
        row_s, _ = _row_nonconformity_scores(norm_r, score_mode=score_mode, k_reg=k_reg, lam=lam)
        rows_out.append(row_s)
    return rows_out


def build_croq_union_schema(
    allowed_kinds: Sequence[str],
    *,
    wire_format: Literal["compact", "v4"] = "compact",
) -> dict[str, Any]:
    """Build a valid compact or V4 JSON schema constrained to surviving CROQ kinds `C(x)`."""
    deduped = list(dict.fromkeys(str(k).strip() for k in allowed_kinds if str(k).strip()))
    if not deduped:
        raise ValueError("allowed_kinds must contain at least 1 valid DocMeta kind.")
    unknown = [k for k in deduped if k not in DOC_KINDS_SET]
    if unknown:
        raise ValueError(f"Unknown DocMeta kinds for union schema: {unknown!r}")
    if wire_format == "compact":
        from .compact_wire_v6 import build_doc_kind_compact_schema_v6

        return build_doc_kind_compact_schema_v6(deduped)
    if wire_format == "v4":
        return build_doc_kind_set_schema_v6(deduped)
    raise ValueError(f"Unsupported wire_format={wire_format!r}")


@dataclass(frozen=True)
class ConformalRoutingDecision:
    """Per-document Conformal Risk-Controlled Routing (`CROQ`) decision."""

    conformal_set: list[str]
    set_size: int
    lock_type: Literal["croq_singleton", "croq_compact_set", "croq_open"]
    lock_spec: str | None
    top1_kind: str
    top1_prob: float
    set_prob_mass: float
    q_hat: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "conformal_set": list(self.conformal_set),
            "set_size": self.set_size,
            "lock_type": self.lock_type,
            "lock_spec": self.lock_spec,
            "top1_kind": self.top1_kind,
            "top1_prob": self.top1_prob,
            "set_prob_mass": self.set_prob_mass,
            "q_hat": self.q_hat,
        }


class ConformalKindRouter:
    """Distribution-free split-conformal class-set router over the 47 usable DocMeta kinds."""

    def __init__(
        self,
        *,
        alpha: float = 0.05,
        score_mode: ScoreMode = "aps_det",
        k_reg: int = 4,
        lam: float = 0.05,
        max_lock_k: int = 4,
        allow_empty: bool = True,
        kinds: Sequence[str] = CANONICAL_CROQ_KINDS,
        q_hat: float | None = None,
        n_cal: int = 0,
        cal_summary: Mapping[str, Any] | None = None,
    ) -> None:
        if not (0.0 < float(alpha) < 1.0):
            raise ValueError(f"alpha must lie in (0, 1), got {alpha!r}.")
        if score_mode not in ("aps_det", "lac", "raps_det"):
            raise ValueError(f"Unsupported score_mode={score_mode!r}.")
        if int(max_lock_k) < 1:
            raise ValueError(f"max_lock_k must be >= 1, got {max_lock_k!r}.")
        self.alpha = float(alpha)
        self.score_mode: ScoreMode = score_mode
        self.k_reg = int(k_reg)
        self.lam = float(lam)
        self.max_lock_k = int(max_lock_k)
        self.allow_empty = bool(allow_empty)
        self.kinds: tuple[str, ...] = tuple(str(k) for k in kinds)
        if not self.kinds:
            raise ValueError("kinds must be non-empty.")
        self._kind_to_idx: dict[str, int] = {k: i for i, k in enumerate(self.kinds)}
        self.q_hat: float | None = float(q_hat) if q_hat is not None else None
        self.n_cal: int = int(n_cal)
        self.cal_summary: dict[str, Any] = dict(cal_summary or {})

    def _label_indices(self, labels: Sequence[int | str]) -> list[int]:
        out: list[int] = []
        n_c = len(self.kinds)
        for y in labels:
            if isinstance(y, str):
                if y not in self._kind_to_idx:
                    raise KeyError(f"Unknown label kind {y!r}")
                out.append(self._kind_to_idx[y])
            else:
                yi = int(y)
                if not (0 <= yi < n_c):
                    raise IndexError(f"Label index {yi} out of bounds [0, {n_c}).")
                out.append(yi)
        return out

    def fit(self, cal_probs: Sequence[Sequence[float]] | Any, cal_labels: Sequence[int | str]) -> "ConformalKindRouter":
        """Fit split-conformal quantile `q_hat` strictly on held-out calibration pairs."""
        rows = cal_probs.tolist() if hasattr(cal_probs, "tolist") else list(cal_probs)
        y_idx = self._label_indices(cal_labels)
        if len(rows) != len(y_idx):
            raise ValueError(f"cal_probs rows ({len(rows)}) != cal_labels ({len(y_idx)}).")
        if not rows:
            raise ValueError("Calibration set cannot be empty.")

        cal_scores: list[float] = []
        for row, yi in zip(rows, y_idx):
            norm_r = _normalize_prob_row(row, len(self.kinds))
            row_s, _ = _row_nonconformity_scores(norm_r, score_mode=self.score_mode, k_reg=self.k_reg, lam=self.lam)
            cal_scores.append(row_s[yi])

        self.q_hat = split_conformal_quantile(cal_scores, alpha=self.alpha)
        self.n_cal = len(rows)
        self.cal_summary = self.evaluate(rows, y_idx)
        return self

    def predict_set(self, probs_1d: Sequence[float] | Any) -> list[str]:
        """Predict ordered conformal class set `C(x)` (descending prob) for one distribution."""
        if self.q_hat is None:
            raise RuntimeError("ConformalKindRouter must be fit or loaded with q_hat before predicting.")
        norm_r = _normalize_prob_row(probs_1d, len(self.kinds))
        row_s, order = _row_nonconformity_scores(
            norm_r, score_mode=self.score_mode, k_reg=self.k_reg, lam=self.lam
        )
        c_set = [self.kinds[idx] for idx in order if row_s[idx] <= self.q_hat + 1e-12]
        if not c_set and not self.allow_empty:
            c_set = [self.kinds[order[0]]]
        return c_set

    def predict_sets(self, probs_2d: Sequence[Sequence[float]] | Any) -> list[list[str]]:
        rows = probs_2d.tolist() if hasattr(probs_2d, "tolist") else list(probs_2d)
        return [self.predict_set(row) for row in rows]

    def route_one(self, probs_1d: Sequence[float] | Any) -> ConformalRoutingDecision:
        """Route one distribution to `croq_singleton`, `croq_compact_set` (`<= max_lock_k`), or `croq_open`."""
        if self.q_hat is None:
            raise RuntimeError("ConformalKindRouter must be fit or loaded with q_hat before route_one().")
        norm_r = _normalize_prob_row(probs_1d, len(self.kinds))
        c_set = self.predict_set(norm_r)
        top1_idx = max(range(len(self.kinds)), key=lambda i: (norm_r[i], -i))
        top1_kind = self.kinds[top1_idx]
        top1_prob = float(norm_r[top1_idx])
        set_mass = float(sum(norm_r[self._kind_to_idx[k]] for k in c_set))
        n_set = len(c_set)
        if n_set == 1:
            lock_type: Literal["croq_singleton", "croq_compact_set", "croq_open"] = "croq_singleton"
            lock_spec: str | None = c_set[0]
        elif 1 < n_set <= self.max_lock_k:
            lock_type = "croq_compact_set"
            lock_spec = "|".join(sorted(c_set))
        else:
            lock_type = "croq_open"
            lock_spec = None
        return ConformalRoutingDecision(
            conformal_set=c_set,
            set_size=n_set,
            lock_type=lock_type,
            lock_spec=lock_spec,
            top1_kind=top1_kind,
            top1_prob=round(top1_prob, 6),
            set_prob_mass=round(set_mass, 6),
            q_hat=float(self.q_hat),
        )

    def evaluate(self, probs_2d: Sequence[Sequence[float]] | Any, labels: Sequence[int | str]) -> dict[str, Any]:
        rows = probs_2d.tolist() if hasattr(probs_2d, "tolist") else list(probs_2d)
        y_idx = self._label_indices(labels)
        if len(rows) != len(y_idx):
            raise ValueError(f"probs_2d rows ({len(rows)}) != labels ({len(y_idx)}).")
        if not rows:
            return {"n": 0, "empirical_coverage": 0.0, "mean_set_size": 0.0}
        covered = 0
        sizes: list[int] = []
        singletons = 0
        compacts = 0
        opens = 0
        for row, yi in zip(rows, y_idx):
            dec = self.route_one(row)
            y_kind = self.kinds[yi]
            if y_kind in dec.conformal_set:
                covered += 1
            sizes.append(dec.set_size)
            if dec.lock_type == "croq_singleton":
                singletons += 1
            elif dec.lock_type == "croq_compact_set":
                compacts += 1
            else:
                opens += 1
        n = len(rows)
        return {
            "n": n,
            "empirical_coverage": round(covered / n, 6),
            "target_coverage": round(1.0 - self.alpha, 6),
            "mean_set_size": round(sum(sizes) / n, 4),
            "singleton_rate": round(singletons / n, 6),
            "compact_rate": round((singletons + compacts) / n, 6),
            "open_fallback_rate": round(opens / n, 6),
        }

    def build_grammar_schema(
        self,
        decision_or_kinds: ConformalRoutingDecision | Sequence[str],
        *,
        wire_format: Literal["compact", "v4"] = "compact",
    ) -> dict[str, Any] | None:
        if isinstance(decision_or_kinds, ConformalRoutingDecision):
            if decision_or_kinds.lock_spec is None:
                return None
            kinds = decision_or_kinds.conformal_set
        else:
            kinds = list(decision_or_kinds)
            if not (1 <= len(kinds) <= self.max_lock_k):
                return None
        return build_croq_union_schema(kinds, wire_format=wire_format)

    def to_dict(self) -> dict[str, Any]:
        return {
            "alpha": self.alpha,
            "score_mode": self.score_mode,
            "k_reg": self.k_reg,
            "lam": self.lam,
            "max_lock_k": self.max_lock_k,
            "allow_empty": self.allow_empty,
            "kinds": list(self.kinds),
            "q_hat": self.q_hat,
            "n_cal": self.n_cal,
            "cal_summary": dict(self.cal_summary),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ConformalKindRouter":
        cal_summary = dict(payload.get("cal_summary") or {})
        if not cal_summary:
            for k_src, k_dst in (
                ("cal_empirical_coverage", "empirical_coverage"),
                ("cal_mean_set_size", "mean_set_size"),
                ("cal_singleton_rate", "singleton_rate"),
                ("cal_open_fallback_rate", "open_fallback_rate"),
            ):
                if k_src in payload and payload[k_src] is not None:
                    cal_summary[k_dst] = float(payload[k_src])
        obj = cls(
            alpha=float(payload["alpha"]),
            score_mode=payload["score_mode"],
            k_reg=int(payload.get("k_reg", 4)),
            lam=float(payload.get("lam", 0.05)),
            max_lock_k=int(payload.get("max_lock_k", 4)),
            allow_empty=bool(payload.get("allow_empty", True)),
            kinds=tuple(payload.get("kinds") or CANONICAL_CROQ_KINDS),
            q_hat=float(payload["q_hat"]) if payload.get("q_hat") is not None else None,
            n_cal=int(payload.get("n_cal", 0)),
            cal_summary=cal_summary,
        )
        return obj


DEFAULT_CROQ_CAL_PATH = Path(__file__).with_name("croq_v64_calibration.json")


def load_bundled_croq_router_v6(
    calibration_path: str | Path | None = None,
    *,
    alpha: float | None = None,
    max_lock_k: int | None = None,
) -> ConformalKindRouter:
    """Load pre-calibrated Conformal `CROQ` (`alpha=0.05, aps_det, max_lock_k=4`) router from package JSON."""
    c_path = Path(calibration_path) if calibration_path is not None else DEFAULT_CROQ_CAL_PATH
    if not c_path.is_file():
        raise FileNotFoundError(f"Missing CROQ calibration artifact: {c_path}")
    payload = json.loads(c_path.read_text(encoding="utf-8"))
    cal_alpha = float(payload["alpha"])
    if alpha is not None and abs(float(alpha) - cal_alpha) > 1e-9:
        raise ValueError(
            f"Bundled CROQ artifact {c_path.name} was calibrated at alpha={cal_alpha}, not alpha={alpha}; "
            "fit ConformalKindRouter explicitly for another alpha."
        )
    router = ConformalKindRouter.from_dict(payload)
    if max_lock_k is not None:
        if int(max_lock_k) < 1:
            raise ValueError(f"max_lock_k must be >= 1, got {max_lock_k!r}")
        router.max_lock_k = int(max_lock_k)
    return router


__all__ = [
    "CANONICAL_CROQ_KINDS",
    "DEFAULT_CROQ_CAL_PATH",
    "ConformalKindRouter",
    "ConformalRoutingDecision",
    "PreDecodeGrammarRouterV6",
    "RouterMode",
    "ScoreMode",
    "build_croq_union_schema",
    "build_doc_kind_set_schema_v6",
    "compute_class_nonconformity_scores",
    "extract_router_sparse_features_v6",
    "fuse_top6_router_probs",
    "is_valid_kind_lock_spec_v6",
    "load_bundled_croq_router_v6",
    "split_conformal_quantile",
]
