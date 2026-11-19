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
import json
import math
from pathlib import Path
import re
from typing import Any, Literal, Mapping, Sequence

from .atomic_validator_v6 import ALL_KIND_DESC_V6, verify_validators_manifest
from .pythonic_v5 import DOC_KINDS_SET, SCHEMA_OBJ
from .pythonic_v6 import clean_html_and_cms_v6, infer_is_html_v6

RouterMode = Literal["fast", "ane"]
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


class PreDecodeGrammarRouterV6:
    """Calibrated Pre-Decode Grammar Router (`fast` linear CPU or `ane` Top-6 `Laya-Typed` ANE)."""

    def __init__(
        self,
        mode: RouterMode = "ane",
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
    ) -> None:
        import numpy as np

        if mode not in ("fast", "ane"):
            raise ValueError(f"Unsupported router mode={mode!r}; expected 'fast' or 'ane'.")
        self._np = np
        self.mode: RouterMode = mode
        self.allow_multi_kind_set = bool(allow_multi_kind_set)
        from fast_decision_models import LayaAneBackend
        from fast_decision_models.paths import ensure_laya_dylib

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
            self.tau_top1 = float(tau_top1 if tau_top1 is not None else cal.get("ane_tau_top1", 0.85))
        else:
            self.tau_top1 = float(tau_top1 if tau_top1 is not None else cal.get("fast_linear_tau_top1", 0.90))
        self.tau_top2 = float(tau_top2 if tau_top2 is not None else cal.get("ane_tau_top2", 0.90))
        self.tau_top3 = float(tau_top3 if tau_top3 is not None else cal.get("ane_tau_top3", 0.93))

        self._owns_laya = False
        self.laya_backend: Any = None
        if mode == "ane":
            if shared_laya_backend is not None:
                self.laya_backend = shared_laya_backend
            else:
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
            ane_ois: list[int] = []
            ane_encs: list[dict[str, Any]] = []
            for oi in range(len(open_indices)):
                if float(np.max(probs[oi])) >= 0.985:
                    continue
                fn, kn_s, _r_txt, c_txt = open_fields[oi]
                cand6 = [self.classes[int(c_i)] for c_i in top6_order[oi]]
                st_r, q_r = _build_router_choice_query(fn, kn_s, c_txt, cand6)
                ane_encs.append(self.laya_backend.encode_item(st_r, q_r))
                ane_ois.append(oi)

            if ane_encs:
                ane_p_list = self.laya_backend.score_choice_batch(ane_encs, temperature_override=self.ane_choice_temp)
                lin_logp = np.log(np.clip(probs, 1e-8, 1.0))
                alpha = self.fusion_alpha
                for oi, p6 in zip(ane_ois, ane_p_list):
                    fused = lin_logp[oi].copy() - (1.0 - alpha) * 6.0
                    for j, p_val in enumerate(p6[:6]):
                        c_idx = int(top6_order[oi, j])
                        fused[c_idx] = alpha * lin_logp[oi, c_idx] + (1.0 - alpha) * math.log(max(p_val, 1e-8))
                    probs[oi] = self._softmax_rows(fused[None, :], 1.0)[0]

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

            results[orig_i] = {
                "lock_spec": lock_spec,
                "lock_type": lock_type,
                "top1_class": c0,
                "top1_prob": round(p0, 4),
                "top_candidates": [
                    (self.classes[int(order[k])], round(float(p_row[int(order[k])]), 4))
                    for k in range(min(3, len(order)))
                ],
            }

        return results

    def close(self) -> None:
        if self._owns_laya and self.laya_backend is not None:
            self.laya_backend.close()
            self.laya_backend = None

    def __enter__(self) -> "PreDecodeGrammarRouterV6":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


__all__ = [
    "PreDecodeGrammarRouterV6",
    "RouterMode",
    "build_doc_kind_set_schema_v6",
    "extract_router_sparse_features_v6",
    "is_valid_kind_lock_spec_v6",
]
