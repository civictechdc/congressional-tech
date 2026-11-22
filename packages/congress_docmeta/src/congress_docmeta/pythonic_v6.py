#!/usr/bin/env python3
"""Pythonic V6 Unified Deterministic Wrapper (`pythonic_v6.py`).

100.0%-precision, 100%-stdlib deterministic domain architecture around the frozen Fused V4 LoRA
(`FastQATEngineV4`), unifying all 5 stages of Deterministic V6 with zero external runtime packages
at import/pre/post/bypass/sweep time (verified under `/usr/bin/python3 -B -I -S`; lazy `llguidance`
import only inside `PerDocGrammarHelperV6` / `PythonicEngineV6`):

  1. Stage 1 (`hygiene/hygiene_and_line_parsers_v6.py`):
     - `\\n`-preserved `p12_lines` + GPO header/footer normalization (`gpo_blank_after_strip`),
       `BGsddV01` PDF mojibake repair, HTML `<script>`/`<style>` event-stream stripping,
       HTML-gated WAF/DataDome/CloudFront/S3/GovInfo `error_pages` triage (never firing on PDFs
       titled `"Access Denied: ..."`), bare-UUID Senate HTML & `&download=1` URL fixes,
       and line-anchored GPO/witness-list/CBO/GAO parsers.
  2. Stage 2 (`relational/relational_rules_v6.py`):
     - Full Congressional-Tech relational graph join (`meetings`, `witnesses`, `people`, `rosters`,
       `members`, `committee_records`, `bills`, `nominations`), `18` House Select `hl..00` codes,
       `5` statutory Commissions + `scnc00`, `84` human-adjudicated `saved-name-decisions.json`
       SHA overrides, deterministic title waterfall, and strict Host-vs-Author / `-SD00x` /
       cross-chamber / backbench-subtraction guards.
  3. Stage 3 (`citations/citations_and_signals_v6.py`):
     - Hybrid `RefSpec` statutory/EO/Act oracles + `spicy-docs` linear prose citation finders +
       8 Congressional-procedural citation families (`refs[]`), proposed-bill `short_titles[]`,
       and case-insensitive `fiscal_years[]` (enforcing all 5 `RefSpec` production safeguards).
  4. Stage 4 (`bypass/cover_locks_v6.py` + `bypass/zero_llm_bypass_v6.py`):
     - Expanded `100%`-precision cover genre locks (Senate `witness_statement`, Member-verified
       `member_opening_statement` with SFRC nominee guard, CBO cost estimates, GAO reports,
       human-verified SHA overrides) and pure-Python `0`-GPU-token complete `DocMetaV4Causal`
       synthesis across high-confidence boilerplate genres (`truth_in_testimony_disclosure`,
       `attendance_quorum_sheet`, `witness_list`, `legislative_schedule_or_calendar`).
  5. Stage 5 (`PythonicEngineV6` + `PerDocGrammarHelperV6` + `SyncKindMatcher` + `post_pass_v6`
     + `anomaly_router_v6`):
     - Preserves 100% shared `SYS_DOCMETA_V4` `EarlyExit14` `prefix_kv` (`1,368` tokens),
       unlocked `chamber` in per-kind `LLMatcher` schemas, `SyncKindMatcher` zero-jitter batch
       alignment, `<NONE>` & raw-HTML pre-LLM prompt distribution, zero-LLM pre-engine short-circuit,
       strict `DocMetaV4Causal` causal key order, and post-extraction `anomaly_router_v6` scoring.
"""

from __future__ import annotations

import copy
import importlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Mapping, Sequence

DOCMETA_DIR = Path(__file__).resolve().parent
DET_V6_DIR = DOCMETA_DIR
V4_DIR = DOCMETA_DIR
DET_V5_DIR = DOCMETA_DIR

from .relational_rules_v6 import (
    HOUSE_SELECT_2LETTER_CODES_V6 as _HOUSE_SELECT_2LETTER_CODES_V6,
    resolve_docmeta_v6_data_dir,
)

DEFAULT_DOCMETA_V6_DATA_DIR = resolve_docmeta_v6_data_dir()
DEFAULT_DOCMETA_V6_DATA_DIR_STR = str(DEFAULT_DOCMETA_V6_DATA_DIR)

from . import pythonic_v5 as _pv5
from .schema_v4 import MAX_OUTPUT_TOKENS, MAX_PERSONAS, SCHEMA_PATH as DOCMETA_V4_SCHEMA_PATH
from .pythonic_v5 import (
    CANONICAL_COMMITTEES_V5,
    CMS_STRIPPER_FAMILIES_V5,
    CONTEMPORARY_CONGRESSIONAL_KINDS,
    DISCLOSURE_KEYS_ORDER,
    DISCLOSURE_ORDER_IDX,
    DOC_FAMILY_MAP,
    DOC_KINDS_SET,
    DOMAIN_TO_COMMITTEE_CODE,
    DocMetaValidationError,
    ETYPES_SET,
    EVAL_KIND_FAMILIES,
    FORMAL_COMMITTEE_KINDS,
    GPO_COVER_ROSTER_ALLOWED_ROLES,
    HOUSE_CLERK_2LETTER_TO_CODE,
    NEW_TIER1_SIGNATURE_TO_KIND_V5,
    NON_USABLE_TRIAGE_STATUSES,
    PERSONA_KEYS_ORDER,
    PERSONA_ORDER_IDX,
    PROVENANCE_SAFE_COMMITTEE_KINDS,
    QUORUM_ROSTER_ALLOWED_ROLES,
    ROLES_SET,
    SCHEMA_OBJ,
    SCHEMA_V4_STR,
    STATUS_SET,
    SYS_DOCMETA_V4,
    TEXT_QUALITY_SET,
    TIER1_SIGNATURE_IDS_V5,
    TIER1_SIGNATURE_TO_KIND_V5,
    TIER1_TARGET_KINDS_V5,
    TOP_KEYS_ORDER,
    TOP_ORDER_IDX,
    TTF_SCHEMA_V4_OBJ,
    TTF_SCHEMA_V4_STR,
    V4_TIER1_SIGNATURE_TO_KIND,
    VOTE_ALLOWED_ROLES,
    _build_triage_result,
    _extract_bulleted_witness_personas,
    _has_congressional_proceeding_cue,
    _is_empty_val,
    _is_exhibit_or_external_artifact,
    _is_gpo_cover_roster_only_p12,
    _nfkc_fold,
    _norm_cmt_compare,
    _norm_ws_prefix,
    _parse_single_ref,
    _salvage_truncated_docmeta_v4,
    has_structural_docmeta_corruption_v4,
    repair_clean_docmeta_budget_v4,
    _surname_token,
    _text_mentions_explicit_congress,
    _year_grounded_in_context,
    build_doc_kind_schema_v5,
    build_prompt_v4,
    build_ttf_schema_v5,
    can_fill_docmeta_chamber_v5,
    can_fill_docmeta_committees_v5,
    can_fill_docmeta_congress_v5,
    can_fill_docmeta_event_date_v5,
    canonicalize_docmeta_v4,
    classify_hsru_host_status,
    committee_code_to_canonical,
    detect_all_tier1_signatures_v5,
    detect_exact_tier1_signature_v5,
    detect_exact_ttf_form,
    detect_new_tier1_signatures_v5,
    detect_provenance_link_anchor,
    detect_stapled_backpage_packets,
    detect_tier2_sidecar_hints_v5,
    detect_ttf_page_signature,
    detect_v4_tier1_signatures,
    detect_vote_page_signature,
    extract_formal_committee_masthead_v5,
    extract_gpo_p3_p8_rescue,
    extract_multipage_signals_v5,
    extract_official_slug_congress,
    extract_pdf_masthead_congress_v5,
    extract_ttf_disclosure_booleans,
    extract_url_dates_and_congress,
    extract_url_official_slug_info,
    infer_is_html_v5,
    is_gpo_cover_roster_only_p12,
    is_qfr_appendix_page,
    is_steno_cover_roster_only_p12,
    iso_date_to_congress,
    match_qfr_appendix_page,
    norm_committee_compare,
    normalize_parent_committee_code,
    resolve_provenance_v5,
    split_pdf_pages,
    strip_html_cms_nav_v5,
    triage_non_usable_v5,
    triage_unwrapped_http_or_empty,
    unwrap_archive_url,
    validate_docmeta_v4,
    validate_docmeta_v4_all,
)
from .anomaly_router_v6 import (
    ACTOR_REQUIRED_KINDS_V6,
    CORE_WITNESS_AUTHOR_KINDS_V6,
    HOST_CHAMBER_EXEMPT_KINDS_V6,
    LEGISLATIVE_DRAFT_KINDS_V6,
    check_gist_title_grounding_v6,
    load_default_usc_oracle_v6,
    norm_committee_token_v6,
    route_batch_anomalies_v6,
    score_docmeta_anomalies_v6,
    surname_token_v6,
)

strict_validate_v4 = validate_docmeta_v4

# ---------------------------------------------------------------------------
# Stage 1-4 sibling modules, imported on first use
# ---------------------------------------------------------------------------

_SUBMODULES: dict[str, str] = {
    "hygiene": "hygiene_and_line_parsers_v6",
    "relational": "relational_rules_v6",
    "citations": "citations_and_signals_v6",
    "cover_locks": "cover_locks_v6",
    "zero_llm_bypass": "zero_llm_bypass_v6",
}


def _load_optional_submodule(key: str) -> Any:
    return importlib.import_module(f".{_SUBMODULES[key]}", __package__)


# ---------------------------------------------------------------------------
# 1. Stage 1 Hygiene, Bare-UUID HTML, `&download=1` & Non-Usable Triage V6
# ---------------------------------------------------------------------------

_DOWNLOAD_AMP_SUFFIX_RE = re.compile(r"&download=1(?:&.*)?$", re.I)
_SD_SUB_SLUG_RE = re.compile(r"(?:^|[-_])SD\d{2,4}(?:[-_.]|$)", re.I)
_PHONE_ID_REF_RE = re.compile(r"^id:\s*(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}$", re.I)
_SLUG_ID_REF_RE = re.compile(r"^id:\s*(?:QFR\d+|Wstate|Bio|TTF|SD\d+)$", re.I)
_EO_NUM_REF_RE = re.compile(r"^eo:\s*(?:Executive\s+Order\s+|E\.?O\.?\s*)?0*(\d+)\b", re.I)
_BILL_CANON_RE = re.compile(
    r"^bill:\s*(?:(\d{2,3}):)?(h\.?\s*r\.?|s\.?|h\.?\s*res\.?|s\.?\s*res\.?|"
    r"h\.?\s*j\.?\s*res\.?|s\.?\s*j\.?\s*res\.?|h\.?\s*con\.?\s*res\.?|s\.?\s*con\.?\s*res\.?|"
    r"hr|s|hres|sres|hjres|sjres|hconres|sconres)[\s:.-]*(\d+)$",
    re.I,
)
_BILL_TYPE_DISPLAY = {
    "hr": "H.R.",
    "s": "S.",
    "hres": "H.Res.",
    "sres": "S.Res.",
    "hjres": "H.J. Res.",
    "sjres": "S.J. Res.",
    "hconres": "H.Con. Res.",
    "sconres": "S.Con. Res.",
}

# Derived from single owner `relational_rules_v6.HOUSE_SELECT_2LETTER_CODES_V6` (`ct-pzaz`).
_V5_SELECT_2LETTER = frozenset({"cn", "ef", "fd", "gw", "ig", "ij", "mh", "qj", "vc", "zi", "zs"})
HOUSE_SELECT_2LETTER_EXTRA_V6: dict[str, str] = {
    c: f"hl{c}00" for c in sorted(_HOUSE_SELECT_2LETTER_CODES_V6 - _V5_SELECT_2LETTER)
}

# 5 Statutory/Chamber Commissions missing in V5 (`rulespec_and_specs_capabilities.md` §4.1)
COMMISSION_MASTHEAD_PATTERNS_V6: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "jcce00",
        "Congressional-Executive Commission on China",
        re.compile(r"\bCongressional[-–\s]+Executive\s+Commission\s+on\s+China\b", re.I),
    ),
    (
        "cybersolarium",
        "Cyberspace Solarium Commission",
        re.compile(r"\b(?:U\.?S\.?\s+)?Cyberspace\s+Solarium\s+Commission\b", re.I),
    ),
    (
        "biotechcomm",
        "National Security Commission on Emerging Biotechnology",
        re.compile(r"\bNational\s+Security\s+Commission\s+on\s+Emerging\s+Biotechnology\b", re.I),
    ),
    (
        "semiquin",
        "United States Semiquincentennial Commission",
        re.compile(r"\b(?:U\.?S\.?|United\s+States)\s+Semiquincentennial\s+Commission\b", re.I),
    ),
    (
        "eisenhower",
        "Dwight D. Eisenhower Memorial Commission",
        re.compile(r"\bDwight\s+D\.?\s+Eisenhower\s+Memorial\s+Commission\b", re.I),
    ),
)


def strip_creative_engine_download_suffix(url_or_fn: str | None) -> str:
    """Repair or strip glued `&download=1` suffix without `?` on CreativeEngine House URLs & filenames."""
    if not url_or_fn:
        return ""
    if "://" in url_or_fn:
        h_mod = _load_optional_submodule("hygiene")
        if h_mod is not None and hasattr(h_mod, "strip_creative_engine_download_suffix"):
            res = h_mod.strip_creative_engine_download_suffix(url_or_fn)
            s_url = str(res[0]) if isinstance(res, tuple) else str(res)
            return s_url.split("?download=1", 1)[0] if s_url.endswith("?download=1") else s_url
    if "?" not in url_or_fn and "&download=1" in url_or_fn.lower():
        return _DOWNLOAD_AMP_SUFFIX_RE.sub("", url_or_fn)
    return url_or_fn


def infer_is_html_v6(
    filename: str | None,
    text: str | None,
    *,
    explicit_format: str | None = None,
    is_html: bool | None = None,
) -> bool:
    """Fix V5 bare-UUID Senate HTML blindspot by honoring `explicit_format == 'html'`."""
    if is_html is not None:
        return bool(is_html)
    if isinstance(explicit_format, str) and explicit_format.strip().lower() in ("html", "htm"):
        return True
    h_mod = _load_optional_submodule("hygiene")
    if h_mod is not None and hasattr(h_mod, "infer_is_html_v6"):
        try:
            return bool(h_mod.infer_is_html_v6(filename, text, explicit_format=explicit_format))
        except TypeError:
            pass
    return infer_is_html_v5(filename, text)


def clean_html_and_cms_v6(
    text: str | None,
    *,
    is_html: bool = False,
) -> tuple[str, str | None, bool]:
    """Run Stage 1 HTML `<script>`/`<style>` stripper + 11-family CMS nav stripper (`(clean_text, cms_family, script_stripped)`)."""
    t_str = text or ""
    if not is_html or not t_str:
        return t_str, None, False

    script_stripped = False
    h_mod = _load_optional_submodule("hygiene")
    if h_mod is not None and hasattr(h_mod, "extract_clean_html_v6"):
        try:
            has_raw_tags = any(tag in t_str.lower() for tag in ("<script", "<style", "<template", "<html", "<!doctype html"))
            arg_h: bytes | str = t_str.encode("utf-8", errors="replace") if has_raw_tags else t_str
            cand_txt, stripped_chars = h_mod.extract_clean_html_v6(arg_h)
            if stripped_chars > 0 and cand_txt:
                t_str = cand_txt
                script_stripped = True
        except Exception:
            pass

    cleaned, cms_family = strip_html_cms_nav_v5(t_str)
    return cleaned, cms_family, script_stripped


def triage_non_usable_v6(
    text: str | None,
    *,
    filename: str | None = None,
    explicit_format: str | None = None,
    http_status: int | None = None,
    known_valid_empty: bool = False,
    body_state: str | None = None,
    text_source: str | None = None,
    sub_disposition: str | None = None,
    triage_status: str | None = None,
    gpo_blank_after_strip: bool = False,
    raw_html_or_bytes: str | bytes | None = None,
) -> dict[str, Any] | None:
    """Deterministic V6 non-usable triage: V5 triage + HTML-gated WAF/DataDome/soft-404 + GPO blank scan check.

    CRITICAL INVARIANT: `error_pages` WAF/blockade detection NEVER runs on PDF text (preventing
    false positives on hearings legitimately titled `"Access Denied: ..."`).
    """
    base_triage = triage_non_usable_v5(
        text,
        filename=filename,
        http_status=http_status,
        known_valid_empty=known_valid_empty,
        body_state=body_state,
        text_source=text_source,
        sub_disposition=sub_disposition,
        triage_status=triage_status,
    )
    if base_triage is not None:
        return base_triage

    if text_source == "detail_metadata_only":
        return None

    if gpo_blank_after_strip:
        return _build_triage_result(
            "ocr_unreadable",
            "garbled",
            "Blank un-OCR'd PDF scan disguised only by GPO VerDate wrapper footer",
        )

    fmt_low = (explicit_format or "").strip().lower()
    fn_low = (filename or "").strip().lower()
    is_pdf = fmt_low == "pdf" or fn_low.endswith(".pdf")
    if isinstance(raw_html_or_bytes, bytes) and raw_html_or_bytes.lstrip().startswith(b"%PDF-"):
        is_pdf = True
    elif isinstance(text, str) and text.lstrip().startswith("%PDF-"):
        is_pdf = True

    if not is_pdf:
        is_h = infer_is_html_v6(filename, text, explicit_format=explicit_format)
        if is_h:
            h_mod = _load_optional_submodule("hygiene")
            if h_mod is not None and hasattr(h_mod, "detect_waf_or_error_page_v6"):
                err_hit = h_mod.detect_waf_or_error_page_v6(
                    raw_bytes=raw_html_or_bytes if isinstance(raw_html_or_bytes, bytes) else None,
                    html_text=raw_html_or_bytes if isinstance(raw_html_or_bytes, str) else (text or ""),
                    effective_format="html",
                    explicit_format="html",
                    filename=filename,
                    status_code=http_status,
                )
                if err_hit:
                    reason_s = (
                        err_hit.get("error_reason") or err_hit.get("reason") or err_hit.get("marker") or str(err_hit)
                        if isinstance(err_hit, Mapping)
                        else str(err_hit)
                    )
                    return _build_triage_result("error_or_block", "native", str(reason_s)[:180])

    return None


# ---------------------------------------------------------------------------
# 2. Stage 4 Expanded 100%-Precision Genre Locking (`detect_locked_primary_kind_v6`)
# ---------------------------------------------------------------------------


def _get_rosters_lookup_v6() -> dict[str, Any] | None:
    r_mod = _load_optional_submodule("relational")
    if r_mod is not None and hasattr(r_mod, "load_rosters_lookup_v6"):
        try:
            return r_mod.load_rosters_lookup_v6(required=False)
        except Exception:
            return None
    return None


def detect_cover_or_sha_lock_v6(
    filename: str | None,
    text: str | None,
    *,
    p12_lines: str | None = None,
    body_sha_hex: str | None = None,
    bioguide_ids: Sequence[str] | None = None,
    witness_keys: Sequence[str] | None = None,
    is_html: bool = False,
) -> tuple[str | None, str | None, str | None]:
    """Query Stage 4 `cover_locks_v6.py` (+ Stage 2 SHA overrides) when V5 Tier-1 returns `None`.

    Returns `(lock_id, target_doc_kind, lock_source)`.
    """
    # 1. Human-adjudicated SHA overrides (`saved-name-decisions.json`)
    for mod_key in ("cover_locks", "relational"):
        mod = _load_optional_submodule(mod_key)
        if mod is not None and body_sha_hex:
            for fn_name in (
                "resolve_saved_name_override_v6",
                "lookup_saved_name_sha_override_v6",
                "get_sha_kind_override_v6",
                "resolve_sha_override_v6",
            ):
                if hasattr(mod, fn_name):
                    hit = getattr(mod, fn_name)(body_sha_hex)
                    if isinstance(hit, tuple) and len(hit) >= 2 and hit[1] in DOC_KINDS_SET:
                        return str(hit[0]), str(hit[1]), "saved_name_sha_override"
                    if isinstance(hit, Mapping):
                        ov_k = hit.get("override_primary_kind") or hit.get("primary_kind")
                        if ov_k in DOC_KINDS_SET:
                            return (
                                str(hit.get("lock_id") or f"sha_override_{body_sha_hex[:10]}"),
                                str(ov_k),
                                "saved_name_sha_override",
                            )
                    if isinstance(hit, str) and hit in DOC_KINDS_SET:
                        return f"sha_override_{body_sha_hex[:10]}", hit, "saved_name_sha_override"

    # 2. `cover_locks_v6.py` (`document_cover.py` + CBO + GAO cover headers with SFRC nominee guard)
    cl_mod = _load_optional_submodule("cover_locks")
    if cl_mod is not None:
        for fn_name in (
            "detect_cover_lock_v6",
            "detect_exact_cover_lock_v6",
            "classify_cover_lock_v6",
        ):
            if hasattr(cl_mod, fn_name):
                fn_obj = getattr(cl_mod, fn_name)
                probe_txt = p12_lines if (isinstance(p12_lines, str) and p12_lines.strip()) else (text or "")
                kwargs_candidates = [
                    {
                        "filename": filename or "",
                        "text": text or probe_txt,
                        "p12_lines": p12_lines,
                        "body_sha_hex": body_sha_hex,
                        "bioguide_ids": list(bioguide_ids or []),
                        "witness_keys": list(witness_keys or []),
                        "is_html": is_html,
                    },
                    {
                        "filename": filename or "",
                        "text": probe_txt,
                        "body_sha_hex": body_sha_hex,
                        "bioguide_ids": list(bioguide_ids or []),
                        "witness_keys": list(witness_keys or []),
                        "is_html": is_html,
                    },
                    {
                        "filename": filename or "",
                        "text": probe_txt,
                        "is_html": is_html,
                    },
                ]
                res: Any = None
                for kw in kwargs_candidates:
                    try:
                        res = fn_obj(**kw)
                        break
                    except TypeError:
                        continue
                else:
                    try:
                        res = fn_obj(filename or "", probe_txt)
                    except Exception:
                        res = None

                if isinstance(res, tuple) and len(res) >= 2 and res[1] in DOC_KINDS_SET:
                    src = str(res[2]) if len(res) >= 3 and res[2] else "cover_lock_v6"
                    return str(res[0]), str(res[1]), src
                if isinstance(res, Mapping) and res.get("primary_kind") in DOC_KINDS_SET:
                    return (
                        str(res.get("signature_id") or res.get("lock_id") or "cover_lock_v6"),
                        str(res["primary_kind"]),
                        str(res.get("source") or "cover_lock_v6"),
                    )
                break

    return None, None, None


def build_doc_kind_schema_v6(
    target_doc_kind: str,
    base_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build specialized `DocMetaV4Causal` JSON schema locking `status='usable'` & `primary_kind=target_doc_kind`."""
    return build_doc_kind_schema_v5(target_doc_kind, base_schema=base_schema)


# ---------------------------------------------------------------------------
# 3. Pre-Pass V6 & Zero-LLM Synthesis Short-Circuit Hook
# ---------------------------------------------------------------------------


def try_zero_llm_bypass_v6(
    *,
    locked_primary_kind: str | None,
    tier1_signature_id: str | None,
    filename: str,
    text: str,
    p12_lines: str | None = None,
    known_dict: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    relational: Mapping[str, Any] | None = None,
    citations: Mapping[str, Any] | None = None,
    hygiene: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Attempt 100%-confidence zero-LLM `DocMetaV4Causal` synthesis via `zero_llm_bypass_v6.py`.

    Always validates the synthesized object through `canonicalize_docmeta_v4` + `validate_docmeta_v4`;
    returns `None` on any ambiguity or validation failure so the row falls back cleanly to the LLM queue.
    """
    if not locked_primary_kind:
        return None
    b_mod = _load_optional_submodule("zero_llm_bypass")
    if b_mod is None:
        return None

    synth_fn = None
    for cand in (
        "try_synthesize_zero_llm_docmeta_v6",
        "synthesize_zero_llm_docmeta_v6",
        "try_zero_llm_bypass_v6",
    ):
        if hasattr(b_mod, cand):
            synth_fn = getattr(b_mod, cand)
            break
    if synth_fn is None:
        return None

    ctx_row: dict[str, Any] = {
        "locked_primary_kind": locked_primary_kind,
        "v6_locked_primary_kind": locked_primary_kind,
        "v5_locked_primary_kind": locked_primary_kind,
        "tier1_signature_id": tier1_signature_id,
        "v5_tier1_signature_id": tier1_signature_id,
        "filename": filename,
        "text": text,
        "p12_text": text,
        "p12_lines": p12_lines or text,
        "known": dict(known_dict or {}),
        "provenance": dict(provenance or {}) if isinstance(provenance, Mapping) else None,
        "relational": dict(relational or {}) if isinstance(relational, Mapping) else None,
        "citations": dict(citations or {}) if isinstance(citations, Mapping) else None,
        "hygiene": dict(hygiene or {}) if isinstance(hygiene, Mapping) else None,
    }
    if isinstance(relational, Mapping):
        for rk, rv in relational.items():
            ctx_row.setdefault(rk, rv)
    if isinstance(citations, Mapping):
        for ck, cv in citations.items():
            ctx_row.setdefault(ck, cv)
    if isinstance(provenance, Mapping):
        for pk_k, pv_v in provenance.items():
            ctx_row.setdefault(pk_k, pv_v)

    raw_synth: Any = None
    for call_style in ("kwargs", "row_only"):
        try:
            if call_style == "kwargs":
                raw_synth = synth_fn(
                    locked_primary_kind=locked_primary_kind,
                    tier1_signature_id=tier1_signature_id,
                    filename=filename,
                    text=text,
                    p12_lines=p12_lines or text,
                    known_dict=dict(known_dict or {}),
                    provenance=provenance,
                    relational=relational,
                    citations=citations,
                    hygiene=hygiene,
                    row=ctx_row,
                )
            else:
                raw_synth = synth_fn(ctx_row)
            break
        except TypeError:
            continue
        except Exception:
            return None

    if raw_synth is None:
        return None
    if isinstance(raw_synth, tuple) and len(raw_synth) >= 1:
        raw_synth = raw_synth[0]
    if not isinstance(raw_synth, Mapping):
        return None
    doc_cand = raw_synth.get("docmeta") if isinstance(raw_synth.get("docmeta"), Mapping) else raw_synth
    try:
        clean = canonicalize_docmeta_v4(dict(doc_cand))
        ok, _ = validate_docmeta_v4(clean)
        if not ok:
            return None
        return clean
    except Exception:
        return None


def pre_pass_v6(
    known: str | dict[str, Any] | None,
    filename: str,
    text: str,
    *,
    p12_lines: str | None = None,
    explicit_format: str | None = None,
    body_sha_hex: str | None = None,
    provenance: dict[str, Any] | None = None,
    multipage: dict[str, Any] | None = None,
    relational: dict[str, Any] | None = None,
    citations: dict[str, Any] | None = None,
    hygiene: dict[str, Any] | None = None,
    http_status: int | None = None,
    known_valid_empty: bool = False,
    body_state: str | None = None,
    text_source: str | None = None,
    sub_disposition: str | None = None,
    triage_status: str | None = None,
    use_hygiene: bool = True,
    use_cover_locks: bool = True,
    use_provenance_link_anchor: bool = True,
    use_zero_llm_bypass: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Run deterministic V6 pre-pass while preserving 100% of V4/V5's pre-LLM prompt invariants."""
    clean_fn = strip_creative_engine_download_suffix(filename) if use_hygiene else filename
    eff_fmt = explicit_format or ((hygiene or {}).get("effective_format") if isinstance(hygiene, Mapping) else None)
    gpo_blank = bool((hygiene or {}).get("gpo_blank_after_strip")) if (use_hygiene and isinstance(hygiene, Mapping)) else False

    is_html = infer_is_html_v6(clean_fn, text, explicit_format=eff_fmt) if use_hygiene else infer_is_html_v5(filename, text)
    if (
        use_hygiene
        and isinstance(hygiene, Mapping)
        and hygiene.get("waf_or_error_detected")
        and (eff_fmt or "").lower() != "pdf"
        and not clean_fn.lower().endswith(".pdf")
    ):
        triage_res = _build_triage_result(
            str(hygiene.get("waf_error_status") or "error_or_block"),
            "native",
            str(hygiene.get("waf_error_reason") or hygiene.get("waf_error_family") or "WAF or error page"),
        )
    else:
        triage_res = (
            triage_non_usable_v6(
                text,
                filename=clean_fn,
                explicit_format=eff_fmt,
                http_status=http_status,
                known_valid_empty=known_valid_empty,
                body_state=body_state,
                text_source=text_source,
                sub_disposition=sub_disposition,
                triage_status=triage_status,
                gpo_blank_after_strip=gpo_blank,
            )
            if use_hygiene
            else triage_non_usable_v5(
                text,
                filename=filename,
                http_status=http_status,
                known_valid_empty=known_valid_empty,
                body_state=body_state,
                text_source=text_source,
                sub_disposition=sub_disposition,
                triage_status=triage_status,
            )
        )

    enr_known_str, meta = _pv5.pre_pass_v5(
        known,
        clean_fn,
        text,
        provenance=provenance,
        multipage=multipage,
        http_status=http_status,
        known_valid_empty=known_valid_empty,
        body_state=body_state,
        text_source=text_source,
        sub_disposition=sub_disposition,
        triage_status=triage_status,
        use_provenance_link_anchor=use_provenance_link_anchor,
    )

    if triage_res is not None and meta["triage"] is None:
        meta["triage"] = triage_res
        meta["tier1_signature_id"] = None
        meta["tier1_target_kind"] = None
        meta["grammar_lock_source"] = None

    script_stripped = False
    if use_hygiene and is_html and not meta["is_html"]:
        # Bare-UUID Senate HTML page newly recognized by `infer_is_html_v6`
        cleaned_h, cms_fam_h, script_stripped = clean_html_and_cms_v6(text, is_html=True)
        meta["is_html"] = True
        meta["cleaned_text"] = cleaned_h
        meta["cms_family"] = cms_fam_h
        meta["cms_nav_stripped"] = cms_fam_h is not None
        if meta["triage"] is None and meta["tier1_target_kind"] is None:
            s_id, t_k = detect_exact_tier1_signature_v5(clean_fn, cleaned_h, is_html=True)
            if t_k is not None:
                meta["tier1_signature_id"] = s_id
                meta["tier1_target_kind"] = t_k
                meta["grammar_lock_source"] = "tier1_text"
    elif use_hygiene and is_html:
        cleaned_h, cms_fam_h, script_stripped = clean_html_and_cms_v6(text, is_html=True)
        if script_stripped:
            meta["cleaned_text"] = cleaned_h
            if cms_fam_h is not None and meta["cms_family"] is None:
                meta["cms_family"] = cms_fam_h
                meta["cms_nav_stripped"] = True

    cover_lock_id: str | None = None
    if use_cover_locks and meta["triage"] is None:
        cl_mod = _load_optional_submodule("cover_locks")
        # Rescue V5 `stmt_member_opening_formal_v5` on SFRC / Senate / Executive Nominee `"Opening Statement"` covers
        if (
            meta["tier1_target_kind"] == "member_opening_statement"
            and cl_mod is not None
            and hasattr(cl_mod, "detect_nominee_opening_override_v6")
        ):
            nom_ov = cl_mod.detect_nominee_opening_override_v6(
                clean_fn,
                p12_lines or meta["cleaned_text"],
                is_html=bool(meta["is_html"]),
            )
            if nom_ov is not None and nom_ov[1] in DOC_KINDS_SET:
                cover_lock_id = str(nom_ov[0])
                meta["tier1_target_kind"] = str(nom_ov[1])
                meta["grammar_lock_source"] = "nominee_opening_override_v6"
                meta["is_exact_ttf"] = False

        if meta["tier1_target_kind"] is None or body_sha_hex:
            rel_bios = (relational or {}).get("bioguide_ids") if isinstance(relational, Mapping) else None
            rel_wks = (relational or {}).get("witness_keys") if isinstance(relational, Mapping) else None
            c_id, c_kind, c_src = detect_cover_or_sha_lock_v6(
                clean_fn,
                meta["cleaned_text"],
                p12_lines=p12_lines,
                body_sha_hex=body_sha_hex,
                bioguide_ids=rel_bios,
                witness_keys=rel_wks,
                is_html=bool(meta["is_html"]),
            )
            if c_kind in DOC_KINDS_SET and (
                meta["tier1_target_kind"] is None or c_src == "saved_name_sha_override"
            ):
                cover_lock_id = c_id
                meta["tier1_target_kind"] = c_kind
                meta["grammar_lock_source"] = c_src or "cover_lock_v6"
                meta["is_exact_ttf"] = c_kind == "truth_in_testimony_disclosure"

    zero_llm_obj: dict[str, Any] | None = None
    if use_zero_llm_bypass and meta["triage"] is None and meta["tier1_target_kind"] is not None:
        zero_llm_obj = try_zero_llm_bypass_v6(
            locked_primary_kind=meta["tier1_target_kind"],
            tier1_signature_id=meta["tier1_signature_id"] or cover_lock_id,
            filename=clean_fn,
            text=meta["cleaned_text"],
            p12_lines=p12_lines,
            known_dict=meta["known_dict"],
            provenance=meta["provenance"],
            relational=relational,
            citations=citations,
            hygiene=hygiene,
        )

    meta["cover_lock_id"] = cover_lock_id
    meta["html_script_stripped"] = script_stripped
    meta["p12_lines"] = p12_lines
    meta["relational"] = relational
    meta["citations"] = citations
    meta["hygiene"] = hygiene
    meta["zero_llm_docmeta"] = zero_llm_obj
    return enr_known_str, meta


# ---------------------------------------------------------------------------
# 4. Citation / Relational / Commission Post-Pass Helpers (`post_pass_v6`)
# ---------------------------------------------------------------------------


def _extract_commission_masthead_v6(text: str | None) -> tuple[str, str] | None:
    if not text:
        return None
    head = _norm_ws_prefix(text[:900], 850)
    for code, name, rx in COMMISSION_MASTHEAD_PATTERNS_V6:
        m = rx.search(head)
        if m and m.start() <= 260:
            return code, name
    return None


def _norm_ref_dedup_key(ref_str: str) -> str:
    s = ref_str.strip()
    m_b = _BILL_CANON_RE.match(s)
    if m_b:
        btype = re.sub(r"[^a-z]", "", m_b.group(2).lower())
        bnum = int(m_b.group(3))
        return f"bill:{btype}:{bnum}"
    return re.sub(r"\s+", " ", s.lower())


def _canonicalize_bill_ref_display(ref_str: str) -> str:
    s = ref_str.strip()
    m_b = _BILL_CANON_RE.match(s)
    if m_b and ":" in s[5:]:
        # Convert `bill:118:hr:2542` -> `bill:H.R. 2542` matching DocMetaV4Causal style
        btype = re.sub(r"[^a-z]", "", m_b.group(2).lower())
        disp = _BILL_TYPE_DISPLAY.get(btype)
        if disp:
            return f"bill:{disp} {int(m_b.group(3))}"
    return s


def _filter_hallucinated_llm_refs_v6(
    refs: Sequence[str],
    *,
    primary_kind: str | None,
    congress: int | None,
    text: str,
    usc_invalid_set: set[str],
) -> list[str]:
    """Prune proven 2B LLM citation hallucinations while keeping proposed USC sections on drafts."""
    is_draft = primary_kind in LEGISLATIVE_DRAFT_KINDS_V6
    text_low = text.lower()
    has_unnumbered_placeholder = bool(re.search(r"\b(?:H\.\s*R\.|S\.)\s*_{2,}|\[\s*DISCUSSION\s+DRAFT\s*\]", text, re.I))
    kept: list[str] = []
    seen_keys: set[str] = set()

    for r in refs:
        rs = r.strip()
        if not rs:
            continue
        if _PHONE_ID_REF_RE.match(rs) or _SLUG_ID_REF_RE.match(rs):
            continue
        m_eo = _EO_NUM_REF_RE.match(rs)
        if m_eo:
            eo_n = int(m_eo.group(1))
            if eo_n < 1 or eo_n > 16000:
                continue
        if not is_draft and rs in usc_invalid_set:
            continue
        m_b = _BILL_CANON_RE.match(rs)
        if m_b:
            bnum_s = str(int(m_b.group(3)))
            # Block `DRN24068 -> bill:H.R. 24068` when number only appears inside `DRN<num>`
            if f"drn{bnum_s}" in text_low or f"drn {bnum_s}" in text_low:
                if not re.search(rf"\b(?:H\.?\s*R\.?|S\.?)\s*{re.escape(bnum_s)}\b", text, re.I):
                    continue
            # Block `119th Congress H.R. ____ -> bill:H.R. 119` on unnumbered discussion drafts
            if (
                has_unnumbered_placeholder
                and congress is not None
                and int(bnum_s) == congress
                and not re.search(rf"\b(?:H\.?\s*R\.?|S\.?)\s*{congress}\b", text, re.I)
            ):
                continue

        dk = _norm_ref_dedup_key(rs)
        if dk not in seen_keys:
            seen_keys.add(dk)
            kept.append(rs)
    return kept


def _extract_citations_bundle_v6(
    text: str,
    *,
    p12_lines: str | None = None,
    filename: str = "",
    congress: int | None = None,
    primary_kind: str | None = None,
    precomputed: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(precomputed, Mapping) and (
        "det_refs" in precomputed or "det_fiscal_years" in precomputed or "det_short_titles" in precomputed
    ):
        return dict(precomputed)
    c_mod = _load_optional_submodule("citations")
    if c_mod is None:
        return {}
    probe = p12_lines if (isinstance(p12_lines, str) and p12_lines.strip()) else text
    for fn_name in (
        "extract_citations_and_signals_v6",
        "extract_all_citations_v6",
        "run_citations_on_doc_v6",
    ):
        if hasattr(c_mod, fn_name):
            fn_obj = getattr(c_mod, fn_name)
            for kw in (
                {
                    "text": probe,
                    "filename": filename,
                    "congress": congress,
                    "primary_kind": primary_kind,
                },
                {"text": probe, "congress": congress},
            ):
                try:
                    out = fn_obj(**kw)
                    if isinstance(out, Mapping):
                        return dict(out)
                except TypeError:
                    continue
            try:
                out = fn_obj(probe)
                if isinstance(out, Mapping):
                    return dict(out)
            except Exception:
                return {}
    return {}


_BIO_MONTH_NUMS_V6: dict[str, int] = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_BIO_MONTH_NAMES_V6: dict[int, tuple[str, ...]] = {
    1: ("january", "jan"),
    2: ("february", "feb"),
    3: ("march", "mar"),
    4: ("april", "apr"),
    5: ("may",),
    6: ("june", "jun"),
    7: ("july", "jul"),
    8: ("august", "aug"),
    9: ("september", "sept", "sep"),
    10: ("october", "oct"),
    11: ("november", "nov"),
    12: ("december", "dec"),
}
_BIO_MONTH_ALT_V6 = "|".join(sorted(_BIO_MONTH_NUMS_V6, key=len, reverse=True))
_BIO_CURRENT_AS_OF_RE_V6 = re.compile(
    rf"(?:\bcurrent\s+as\s+of|^\s*(?:as\s+of|updated(?:\s+as\s+of)?|date:))\s+"
    rf"({_BIO_MONTH_ALT_V6})\.?,?\s+(?:(\d{{1,2}}),?\s+)?((?:19|20)\d{{2}})\b",
    re.I | re.M,
)
_BIO_FOOTER_MONTH_YEAR_RE_V6 = re.compile(
    rf"^\s*({_BIO_MONTH_ALT_V6})\.?,?\s+((?:19|20)\d{{2}})\s*$",
    re.I,
)
_BARE_PERSONA_STOPWORDS_V6 = frozenset(
    {
        "president",
        "vice",
        "bill",
        "senator",
        "representative",
        "rep",
        "sen",
        "chairman",
        "chairwoman",
        "chairperson",
        "chair",
        "ranking",
        "member",
        "mr",
        "mrs",
        "ms",
        "miss",
        "dr",
        "hon",
        "honorable",
        "secretary",
        "director",
        "administrator",
        "commissioner",
        "governor",
        "judge",
        "justice",
        "general",
        "colonel",
        "admiral",
        "professor",
        "sir",
        "madam",
        "speaker",
        "leader",
        "whip",
        "counsel",
        "clerk",
        "witness",
        "witnesses",
        "panel",
        "staff",
        "committee",
        "subcommittee",
        "congress",
        "house",
        "senate",
    }
)
_PERSONA_HONORIFIC_STRIP_RE_V6 = re.compile(
    r"^(?:(?:hon|rep|sen|mr|mrs|ms|miss|dr|prof|rev|gov|gen|adm|col|amb|sec|dir)\.?|"
    r"president|senator|representative|chairman|chairwoman|chairperson|chair|"
    r"ranking\s+member|judge|justice|secretary|director|professor)\s+",
    re.I,
)


def _fix_ba_fd_committees_v6(
    obj: dict[str, Any],
    *,
    known_dict: Mapping[str, Any] | None,
    relational: Mapping[str, Any] | None,
    filename: str,
    norm_txt: str,
) -> None:
    """Fix House Banking (`BA00`) -> Financial Services and drop spurious `Foreign Affairs` on `FD00`."""
    cmts = obj.get("committees")
    if not isinstance(cmts, list) or not cmts:
        return
    codes: set[str] = set()
    for src in (known_dict, relational):
        if isinstance(src, Mapping):
            for key in ("cmt", "rel_host_committee_codes"):
                for code in src.get(key) or ():
                    if isinstance(code, str) and code.strip():
                        codes.add(code.strip().lower())
    fn_low = (filename or "").lower()
    is_house_ba = (
        obj.get("chamber") == "house"
        or any(c.startswith("hsba") or c.startswith("ba") for c in codes)
        or "hsba" in fn_low
        or "-ba" in fn_low
    )
    is_fd00 = any(c in ("hlfd00", "fd00") for c in codes) or "-fd00" in fn_low
    if not is_house_ba and not is_fd00:
        return
    updated: list[str] = []
    seen: set[str] = set()
    for raw_c in cmts:
        if not isinstance(raw_c, str) or not raw_c.strip():
            continue
        c = raw_c.strip()
        if is_house_ba and c == "House Committee on Banking, Housing, and Urban Affairs":
            c = "House Committee on Financial Services"
        elif is_fd00 and c == "House Committee on Foreign Affairs" and "foreign affairs" not in norm_txt:
            continue
        if c not in seen:
            seen.add(c)
            updated.append(c)
    if updated:
        obj["committees"] = updated
    else:
        obj.pop("committees", None)


def _bio_exact_date_is_printed_v6(iso_str: Any, raw_text: str) -> bool:
    if not isinstance(iso_str, str) or not raw_text:
        return False
    s = iso_str.strip()
    fold = _nfkc_fold(raw_text)
    m_full = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m_full:
        y, mo_s, dy_s = m_full.groups()
        mo, dy = int(mo_s), int(dy_s)
        if f"{y}-{mo_s}-{dy_s}" in fold or f"{y}/{mo_s}/{dy_s}" in fold:
            return True
        if re.search(rf"(?<!\d)0?{mo}[/\-]0?{dy}[/\-](?:{y}|{y[2:]})(?!\d)", fold):
            return True
        m_names = _BIO_MONTH_NAMES_V6.get(mo, ())
        if m_names:
            alt = "|".join(m_names)
            if re.search(rf"\b(?:{alt})\.?\s+0?{dy},?\s+{y}\b", fold) or re.search(
                rf"\b0?{dy}\s+(?:{alt})\.?\s+{y}\b", fold
            ):
                return True
        return False
    m_ym = re.fullmatch(r"(\d{4})-(\d{2})", s)
    if m_ym:
        y, mo_s = m_ym.groups()
        mo = int(mo_s)
        if f"{y}-{mo_s}" in fold or f"{y}/{mo_s}" in fold:
            return True
        if re.search(rf"(?<!\d)0?{mo}/{y}(?!\d)", fold):
            return True
        m_names = _BIO_MONTH_NAMES_V6.get(mo, ())
        if m_names:
            alt = "|".join(m_names)
            if re.search(rf"\b(?:{alt})\.?,?\s+{y}\b", fold):
                return True
        return False
    return False


def _extract_printed_bio_doc_date_v6(raw_text: str) -> str | None:
    if not raw_text:
        return None
    m_cur = _BIO_CURRENT_AS_OF_RE_V6.search(raw_text)
    if m_cur:
        mon_num = _BIO_MONTH_NUMS_V6.get(m_cur.group(1).lower())
        day_s, yr_s = m_cur.group(2), m_cur.group(3)
        if mon_num is not None:
            if day_s and 1 <= int(day_s) <= 31:
                return f"{yr_s}-{mon_num:02d}-{int(day_s):02d}"
            return f"{yr_s}-{mon_num:02d}"
    tail_lines = [ln.strip() for ln in raw_text[-600:].splitlines() if ln.strip()][-6:]
    for ln in reversed(tail_lines):
        m_ftr = _BIO_FOOTER_MONTH_YEAR_RE_V6.match(ln)
        if m_ftr:
            mon_num = _BIO_MONTH_NUMS_V6.get(m_ftr.group(1).lower())
            if mon_num is not None:
                return f"{m_ftr.group(2)}-{mon_num:02d}"
    return None


def _enforce_witness_bio_date_restraint_v6(obj: dict[str, Any], raw_text: str) -> None:
    """Strip unprinted leaked dates on `witness_biography` and recover explicit printed bio dates."""
    for dk in ("event_date", "doc_date"):
        if dk in obj and not _bio_exact_date_is_printed_v6(obj.get(dk), raw_text):
            obj.pop(dk, None)
    if "doc_date" not in obj:
        printed_dd = _extract_printed_bio_doc_date_v6(raw_text)
        if printed_dd is not None:
            obj["doc_date"] = printed_dd


def _persona_richness_score_v6(p: Mapping[str, Any]) -> tuple[int, int, int, int]:
    role = str(p.get("role") or "")
    specific_role = 1 if role and role not in ("author_or_speaker", "discussed") else 0
    has_etype = 1 if isinstance(p.get("entity_type"), str) and bool(p.get("entity_type")) else 0
    extra_fields = sum(
        1 for fk in ("org", "title", "party", "state", "bioguide_id", "role_detail", "work_addr") if p.get(fk)
    )
    name_toks = len(str(p.get("name") or "").split())
    return (specific_role, has_etype, extra_fields, name_toks)


def _merge_persona_pair_v6(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    winner, loser = (a, b) if _persona_richness_score_v6(a) >= _persona_richness_score_v6(b) else (b, a)
    merged = dict(winner)
    for k, v in loser.items():
        if v not in (None, "", []) and merged.get(k) in (None, "", []):
            merged[k] = v
    return merged


def _persona_dedup_key_v6(p: Mapping[str, Any], pkey_fn: Any) -> tuple[bool, str]:
    nm = str(p.get("name") or "").strip()
    if p.get("entity_type") == "organization":
        return True, "org:" + re.sub(r"\W+", " ", nm.lower()).strip()
    cleaned = _PERSONA_HONORIFIC_STRIP_RE_V6.sub("", nm).strip() or nm
    k = pkey_fn(cleaned) if callable(pkey_fn) else cleaned.lower()
    return False, k


def _clean_dedup_and_cap_personas_v6(
    obj: dict[str, Any],
    *,
    primary_kind: str | None,
    pkey_fn: Any,
) -> None:
    """Drop bare title stopwords, dedup by `person_key`, and cap multi-signer non-transcript lists at 10."""
    raw_ps = obj.get("personas")
    if not isinstance(raw_ps, list) or not raw_ps:
        return
    filtered: list[dict[str, Any]] = []
    for p in raw_ps:
        if not isinstance(p, dict):
            continue
        nm = str(p.get("name") or "").strip()
        if not nm:
            continue
        toks = [re.sub(r"^[^\w]+|[^\w]+$", "", t).lower() for t in nm.split()]
        toks = [t for t in toks if t]
        if not toks:
            continue
        if len(toks) == 1 and p.get("entity_type") != "organization" and toks[0] in _BARE_PERSONA_STOPWORDS_V6:
            continue
        if p.get("entity_type") != "organization":
            last_raw = nm.split()[-1]
            if re.search(r"\b[A-Z]{2,}[a-z]", nm) or (
                last_raw.endswith(".")
                and len(last_raw) > 3
                and last_raw.lower() not in ("jr.", "sr.", "esq.", "inc.", "corp.", "ltd.", "ph.d.", "m.d.")
            ):
                continue
        filtered.append(dict(p, name=nm))

    # Map bare surname entries (`Shimkus`) to a unique multi-token `surname-first` key when present.
    multi_keys: dict[str, list[str]] = {}
    raw_keys: list[tuple[bool, str]] = []
    for p in filtered:
        is_org, k = _persona_dedup_key_v6(p, pkey_fn)
        if not is_org and "-" in k:
            sur = k.split("-", 1)[0]
            multi_keys.setdefault(sur, []).append(k)
        raw_keys.append((is_org, k))

    deduped: list[dict[str, Any]] = []
    key_to_idx: dict[str, int] = {}
    for p, (is_org, k) in zip(filtered, raw_keys):
        if not is_org and "-" not in k and len(set(multi_keys.get(k, ()))) == 1:
            k = multi_keys[k][0]
        if k in key_to_idx:
            idx = key_to_idx[k]
            deduped[idx] = _merge_persona_pair_v6(deduped[idx], p)
        else:
            key_to_idx[k] = len(deduped)
            deduped.append(p)

    if primary_kind != "hearing_transcript" and len(deduped) > 10:
        signer_idxs = [i for i, p in enumerate(deduped) if p.get("role") in ("sender", "cosigner")]
        if len(signer_idxs) >= 3:
            indiv_sig = sum(1 for i in signer_idxs if deduped[i].get("entity_type") != "organization")
            sig_total = indiv_sig if indiv_sig >= 3 else len(signer_idxs)
            cur_sc = obj.get("signatory_count")
            if not isinstance(cur_sc, int) or isinstance(cur_sc, bool) or cur_sc < sig_total:
                obj["signatory_count"] = sig_total
            non_signers = [i for i, p in enumerate(deduped) if p.get("role") not in ("sender", "cosigner")]
            org_signers = [i for i in signer_idxs if deduped[i].get("entity_type") == "organization"]
            indiv_signers = [i for i in signer_idxs if deduped[i].get("entity_type") != "organization"]
            keep_idxs = sorted((non_signers + org_signers + indiv_signers)[:10])
            deduped = [deduped[i] for i in keep_idxs]

    if deduped:
        obj["personas"] = deduped[:MAX_PERSONAS]
    else:
        obj.pop("personas", None)


def post_pass_v6(
    raw_obj: dict[str, Any],
    known: str | dict[str, Any] | None = None,
    filename: str = "",
    text: str = "",
    *,
    p12_lines: str | None = None,
    explicit_format: str | None = None,
    pre_meta: Mapping[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    multipage: dict[str, Any] | None = None,
    triage: dict[str, Any] | None = None,
    relational: Mapping[str, Any] | None = None,
    citations: Mapping[str, Any] | None = None,
    hygiene: Mapping[str, Any] | None = None,
    use_citations: bool = True,
    use_relational: bool = True,
    use_hygiene: bool = True,
    usc_oracle: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply 100%-precision deterministic V6 post-pass enrichments and return `(clean_docmeta_v4, sidecar_v6)`."""
    raw_persona_count = (
        len(raw_obj.get("personas") or [])
        if isinstance(raw_obj, Mapping) and isinstance(raw_obj.get("personas"), list)
        else 0
    )

    clean_fn = strip_creative_engine_download_suffix(filename) if use_hygiene else filename
    eff_fmt = explicit_format or ((hygiene or {}).get("effective_format") if isinstance(hygiene, Mapping) else None)
    if isinstance(pre_meta, Mapping) and "is_html" in pre_meta:
        is_html_v6 = bool(pre_meta["is_html"])
    else:
        is_html_v6 = infer_is_html_v6(clean_fn, text, explicit_format=eff_fmt) if use_hygiene else _pv5.infer_is_html_v5(filename, text)

    text_for_v5 = text
    if use_hygiene and text:
        if is_html_v6:
            if isinstance(pre_meta, Mapping) and isinstance(pre_meta.get("cleaned_text"), str) and pre_meta.get("cleaned_text"):
                text_for_v5 = str(pre_meta["cleaned_text"])
            else:
                cleaned_h, _, _ = clean_html_and_cms_v6(text, is_html=True)
                if cleaned_h:
                    text_for_v5 = cleaned_h
        h_mod_pre = _load_optional_submodule("hygiene")
        if h_mod_pre is not None and hasattr(h_mod_pre, "repair_bgsdd_mojibake_v6"):
            try:
                text_for_v5, _ = h_mod_pre.repair_bgsdd_mojibake_v6(text_for_v5, filename=clean_fn)
            except Exception:
                pass

    clean_obj, sidecar = _pv5.post_pass_v5(
        raw_obj,
        known=known,
        filename=clean_fn,
        text=text_for_v5,
        provenance=provenance,
        multipage=multipage,
        triage=triage,
        is_html_override=is_html_v6,
        skip_sidecar=True,
        _defer_completeness=True,
    )

    if clean_obj.get("status") != "usable":
        clean_obj = canonicalize_docmeta_v4(clean_obj)
        if "_resolved_prov" in sidecar or "status" not in sidecar:
            sidecar = _pv5.derive_sidecar_v5(
                clean_obj,
                filename=clean_fn,
                text=text_for_v5,
                known=known,
                provenance=provenance,
                multipage=multipage,
                triage=triage,
            )
        sidecar["anomaly_routing"] = score_docmeta_anomalies_v6(
            clean_obj,
            {
                "filename": clean_fn,
                "text": text_for_v5,
                "known": known,
                **(dict(relational) if isinstance(relational, Mapping) else {}),
            },
            usc_oracle=usc_oracle,
        )
        return clean_obj, sidecar

    obj = copy.deepcopy(clean_obj)
    pk = obj.get("primary_kind")
    is_sd_sub = bool(_SD_SUB_SLUG_RE.search(clean_fn)) or bool(
        isinstance(relational, Mapping) and relational.get("slug_is_sd_submission")
    )
    is_exhibit = _is_exhibit_or_external_artifact(clean_fn, text)
    hsru_status = str(sidecar.get("hsru_host_status") or "not_hsru")
    norm_txt = _nfkc_fold(p12_lines or text or "")

    # (1) 5 Missing Statutory/Chamber Commissions masthead recovery (`+94` S_raw docs)
    if use_hygiene and not is_exhibit and not is_sd_sub:
        comm_hit = _extract_commission_masthead_v6(p12_lines or text)
        if comm_hit is not None:
            _, comm_name = comm_hit
            if "committees" not in obj and pk in FORMAL_COMMITTEE_KINDS:
                obj["committees"] = [comm_name]
            if "chamber" not in obj:
                obj["chamber"] = "commission"

    # (1b) Subcommittee-only `committees[]` structural repair (`Subcommittee on ...` -> `subcommittees[]` + parent `committees[]`)
    raw_cmts_list = obj.get("committees")
    if (
        isinstance(raw_cmts_list, list)
        and raw_cmts_list
        and all(isinstance(c, str) and re.match(r"^subcommittee\b", c.strip(), re.I) for c in raw_cmts_list)
    ):
        sub_moved = [c.strip() for c in raw_cmts_list if isinstance(c, str) and c.strip()]
        parent_cmts: list[str] = []
        probe_head = p12_lines or text or ""
        r_mod_c = _load_optional_submodule("relational")
        eff_c_for_cmt = (
            obj.get("congress")
            or iso_date_to_congress(obj.get("event_date"))
            or iso_date_to_congress(obj.get("doc_date"))
            or (relational.get("rel_congress") if (use_relational and isinstance(relational, Mapping)) else None)
        )
        if eff_c_for_cmt is None:
            m_yr = re.search(r"\b(199\d|20[0-2]\d)\b", probe_head[:900])
            if m_yr:
                eff_c_for_cmt = iso_date_to_congress(f"{m_yr.group(1)}-06-01")
        if (
            not is_exhibit
            and not is_sd_sub
            and r_mod_c is not None
            and hasattr(r_mod_c, "resolve_prose_committee_names_v6")
        ):
            try:
                prose_hits = r_mod_c.resolve_prose_committee_names_v6(probe_head[:1200], congress=eff_c_for_cmt)
                for ph in prose_hits or ():
                    nm_p = ph.get("name") if isinstance(ph, Mapping) else None
                    if isinstance(nm_p, str) and nm_p.strip() and nm_p.strip() not in parent_cmts:
                        parent_cmts.append(nm_p.strip())
            except Exception:
                pass
        if not parent_cmts and not is_exhibit and not is_sd_sub and isinstance(p12_lines, str) and "\n" in p12_lines:
            for ln_c in p12_lines[:900].splitlines():
                ln_s = ln_c.strip()
                if re.match(r"^(?:U\.?S\.?\s+|United\s+States\s+)?(?:House\s+|Senate\s+)?Committee\s+on\s+[A-Z][A-Za-z ,&'-]{3,75}$", ln_s):
                    parent_cmts.append(ln_s)
                    break
        if (
            not parent_cmts
            and use_relational
            and isinstance(relational, Mapping)
            and pk in FORMAL_COMMITTEE_KINDS
            and hsru_status != "rules_host"
            and not is_exhibit
            and not is_sd_sub
        ):
            for rc_name in relational.get("rel_committees") or relational.get("rel_host_committees") or ():
                if isinstance(rc_name, str) and rc_name.strip() and rc_name.strip() not in parent_cmts:
                    parent_cmts.append(rc_name.strip())
        if parent_cmts:
            cur_subs = [
                str(s).strip() for s in (obj.get("subcommittees") or []) if isinstance(s, str) and str(s).strip()
            ]
            seen_sub_low = {s.lower() for s in cur_subs}
            for sm in sub_moved:
                if sm.lower() not in seen_sub_low:
                    seen_sub_low.add(sm.lower())
                    cur_subs.append(sm)
            obj["subcommittees"] = cur_subs
            obj["committees"] = parent_cmts

    # (2) Stage 3 Citations (`refs[]` hallucination prune + high-precision union, `short_titles[]`, `fiscal_years[]`)
    cit_bundle: dict[str, Any] = {}
    if use_citations:
        cit_bundle = _extract_citations_bundle_v6(
            text,
            p12_lines=p12_lines,
            filename=clean_fn,
            congress=obj.get("congress"),
            primary_kind=pk if isinstance(pk, str) else None,
            precomputed=citations,
        )
        usc_inv_set = {
            str(x).strip()
            for x in (cit_bundle.get("usc_oracle_invalid_refs") or [])
            if isinstance(x, str) and str(x).strip()
        }
        cur_refs = [str(x) for x in (obj.get("refs") or []) if isinstance(x, str)]
        pruned_refs = _filter_hallucinated_llm_refs_v6(
            cur_refs,
            primary_kind=pk if isinstance(pk, str) else None,
            congress=obj.get("congress") if isinstance(obj.get("congress"), int) else None,
            text=p12_lines or text,
            usc_invalid_set=usc_inv_set,
        )
        if cur_refs:
            obj["refs"] = pruned_refs if pruned_refs else []
            if not obj["refs"]:
                obj.pop("refs", None)

        c_mod = _load_optional_submodule("citations")
        if c_mod is not None and hasattr(c_mod, "merge_citations_post_pass_v6"):
            # Only inject `det_short_titles` into `DocMetaV4Causal` on legislative drafts where grounded
            sig_for_merge = dict(cit_bundle)
            if pk not in LEGISLATIVE_DRAFT_KINDS_V6:
                sig_for_merge["det_short_titles"] = []
            else:
                sig_for_merge["det_short_titles"] = [
                    s for s in (cit_bundle.get("det_short_titles") or []) if isinstance(s, str) and _nfkc_fold(s) in norm_txt
                ]
            obj = c_mod.merge_citations_post_pass_v6(
                obj,
                sig_for_merge,
                primary_kind=pk if isinstance(pk, str) else None,
            )
        else:
            det_refs = [
                _canonicalize_bill_ref_display(str(x))
                for x in (cit_bundle.get("det_refs") or [])
                if isinstance(x, str) and str(x).strip()
            ]
            if det_refs or len(pruned_refs) != len(cur_refs):
                merged_refs = list(pruned_refs)
                seen_r = {_norm_ref_dedup_key(r) for r in merged_refs}
                for dr in det_refs:
                    if not (pk not in LEGISLATIVE_DRAFT_KINDS_V6 and dr in usc_inv_set):
                        dk = _norm_ref_dedup_key(dr)
                        if dk not in seen_r and len(merged_refs) < 25:
                            seen_r.add(dk)
                            merged_refs.append(dr)
                if merged_refs:
                    obj["refs"] = merged_refs[:25]
                else:
                    obj.pop("refs", None)

            det_st = [
                str(s).strip()
                for s in (cit_bundle.get("det_short_titles") or [])
                if isinstance(s, str) and str(s).strip()
            ]
            if det_st and pk in LEGISLATIVE_DRAFT_KINDS_V6:
                cur_st = [str(s) for s in (obj.get("short_titles") or []) if isinstance(s, str)]
                seen_st = {_nfkc_fold(s) for s in cur_st}
                for st_item in det_st:
                    if _nfkc_fold(st_item) not in seen_st and _nfkc_fold(st_item) in norm_txt and len(cur_st) < 8:
                        seen_st.add(_nfkc_fold(st_item))
                        cur_st.append(st_item)
                if cur_st:
                    obj["short_titles"] = cur_st[:8]

            det_fys = [
                int(y)
                for y in (cit_bundle.get("det_fiscal_years") or [])
                if not isinstance(y, bool) and isinstance(y, (int, str)) and str(y).isdigit() and 1900 <= int(y) <= 2100
            ]
            if det_fys:
                cur_fys = [int(y) for y in (obj.get("fiscal_years") or []) if isinstance(y, int)]
                merged_fys = sorted(set(cur_fys) | set(det_fys))[:12]
                if merged_fys:
                    obj["fiscal_years"] = merged_fys

    # (2b) Stage 1 `\n`-Line Parsers (`witness_list` empty-witness rescue + sidecar GPO/CBO/GAO enrichments)
    line_parser_sidecar: dict[str, Any] = {}
    if use_hygiene:
        h_mod = _load_optional_submodule("hygiene")
        if h_mod is not None:
            if (
                pk == "witness_list"
                and isinstance(p12_lines, str)
                and "\n" in p12_lines
                and not any(isinstance(p, dict) and p.get("role") == "witness" for p in (obj.get("personas") or []))
                and hasattr(h_mod, "parse_witness_list_personas_v6")
            ):
                try:
                    w_resc = h_mod.parse_witness_list_personas_v6(p12_lines)
                    if w_resc:
                        cur_p = [p for p in (obj.get("personas") or []) if isinstance(p, dict)]
                        seen_s = {_surname_token(str(p.get("name") or "")) for p in cur_p}
                        for wp in w_resc:
                            ws = _surname_token(str(wp.get("name") or ""))
                            if ws and ws not in seen_s and ws in norm_txt and len(cur_p) < MAX_PERSONAS:
                                seen_s.add(ws)
                                cur_p.append(wp)
                        if cur_p:
                            obj["personas"] = cur_p
                except Exception:
                    pass
            mp_slice = (multipage or {}).get("p3_toc_or_gavel_slice") if isinstance(multipage, Mapping) else None
            harvested_ps: dict[str, Any] = {}
            if hasattr(h_mod, "harvest_tail_and_toc_personas_v6"):
                try:
                    harvested_ps = h_mod.harvest_tail_and_toc_personas_v6(
                        text_for_v5 or p12_lines or text,
                        primary_kind=pk if isinstance(pk, str) else None,
                        p3_slice=mp_slice if isinstance(mp_slice, str) else None,
                    )
                except Exception:
                    harvested_ps = {}
            toc_ps = list(harvested_ps.get("toc_personas") or ())
            if not toc_ps and isinstance(mp_slice, str) and mp_slice.strip() and hasattr(h_mod, "parse_gpo_p3_slice_personas_v6"):
                try:
                    toc_ps = h_mod.parse_gpo_p3_slice_personas_v6(mp_slice)
                except Exception:
                    toc_ps = []
            if toc_ps:
                line_parser_sidecar["gpo_p3_p8_personas"] = toc_ps

            pkey_fn = getattr(h_mod, "person_key", None)
            cur_p_harv = [p for p in (obj.get("personas") or []) if isinstance(p, dict) and p.get("name")]
            seen_harv_keys = {_persona_dedup_key_v6(p, pkey_fn)[1] for p in cur_p_harv}
            harv_added = False
            if pk == "hearing_transcript" and toc_ps:
                for tp in toc_ps:
                    if not isinstance(tp, dict) or not tp.get("name"):
                        continue
                    if tp.get("role") not in ("witness", "nominee"):
                        continue
                    tk = _persona_dedup_key_v6(tp, pkey_fn)[1]
                    if tk and tk not in seen_harv_keys and len(cur_p_harv) < MAX_PERSONAS:
                        seen_harv_keys.add(tk)
                        cur_p_harv.append(dict(tp))
                        harv_added = True

            tail_ps = [
                dict(tp)
                for tp in (harvested_ps.get("tail_personas") or ())
                if isinstance(tp, Mapping) and tp.get("name")
            ]
            if tail_ps:
                tail_ordered = sorted(
                    tail_ps,
                    key=lambda x: (0 if x.get("entity_type") == "organization" else 1),
                )
                for tp in tail_ordered:
                    tk = _persona_dedup_key_v6(tp, pkey_fn)[1]
                    if tk and tk not in seen_harv_keys and len(cur_p_harv) < MAX_PERSONAS:
                        seen_harv_keys.add(tk)
                        if tp.get("entity_type") == "organization" and pk != "hearing_transcript":
                            cur_p_harv.insert(0, tp)
                        else:
                            cur_p_harv.append(tp)
                        harv_added = True
            if harv_added and cur_p_harv:
                obj["personas"] = cur_p_harv[:MAX_PERSONAS]
            harv_sig_cnt = harvested_ps.get("signatory_count")
            if (
                pk != "hearing_transcript"
                and isinstance(harv_sig_cnt, int)
                and not isinstance(harv_sig_cnt, bool)
                and harv_sig_cnt > (obj.get("signatory_count") or 0)
            ):
                obj["signatory_count"] = harv_sig_cnt
            if pk == "revenue_or_cost_estimate" and isinstance(p12_lines, str) and "\n" in p12_lines and hasattr(h_mod, "parse_cbo_cost_estimate_v6"):
                try:
                    cbo_d = h_mod.parse_cbo_cost_estimate_v6(p12_lines)
                    if cbo_d:
                        line_parser_sidecar["cbo_cost_card"] = cbo_d
                except Exception:
                    pass

    # (3) Stage 2 Relational Graph Enrichments (`use_relational=True`)
    rel_summary: dict[str, Any] | None = None
    if use_relational and isinstance(relational, Mapping) and relational:
        r_mod = _load_optional_submodule("relational")
        # Pre-clean 100%-ungrounded hallucinated witness names on single-witness core author kinds
        # so `apply_relational_post_pass_v6` stamps the verified `witnesses.parquet` persona cleanly.
        if not is_sd_sub and pk in CORE_WITNESS_AUTHOR_KINDS_V6:
            wks_pre = list(relational.get("witness_keys") or ())
            w_json_pre = relational.get("rel_witness_personas_json")
            has_single_rel_wit = False
            if len(wks_pre) == 1:
                if isinstance(w_json_pre, str) and w_json_pre.strip().startswith("["):
                    try:
                        has_single_rel_wit = len(json.loads(w_json_pre)) == 1
                    except Exception:
                        has_single_rel_wit = False
                elif isinstance(relational.get("rel_witness_persona"), Mapping):
                    has_single_rel_wit = True
            if has_single_rel_wit and isinstance(obj.get("personas"), list):
                cur_p_pre = [p for p in obj["personas"] if isinstance(p, dict)]
                wit_p_pre = [p for p in cur_p_pre if p.get("role") in ("witness", "nominee")]
                fn_fold_pre = _nfkc_fold(clean_fn)
                if wit_p_pre and all(
                    (
                        not surname_token_v6(str(p.get("name") or ""))
                        or (
                            surname_token_v6(str(p.get("name") or "")) not in norm_txt
                            and surname_token_v6(str(p.get("name") or "")) not in fn_fold_pre
                        )
                    )
                    for p in wit_p_pre
                ):
                    kept_non_wit = [p for p in cur_p_pre if p.get("role") not in ("witness", "nominee")]
                    if kept_non_wit:
                        obj["personas"] = kept_non_wit
                    else:
                        obj.pop("personas", None)

        # Prune provably hallucinated non-existent `member` personas (surname absent from text, filename, AND all `eff_cong` Members in `rosters_lookup_v6`)
        eff_cong_mem_chk = obj.get("congress") or relational.get("rel_congress")
        has_mem_persona = isinstance(obj.get("personas"), list) and any(
            isinstance(pm, dict) and pm.get("entity_type") == "member" for pm in obj["personas"]
        )
        if (
            has_mem_persona
            and isinstance(eff_cong_mem_chk, int)
            and not isinstance(eff_cong_mem_chk, bool)
        ):
            rl_db_chk = _get_rosters_lookup_v6()
            if r_mod is not None and hasattr(r_mod, "_valid_cong_surnames_with_lookup"):
                valid_cong_surs = r_mod._valid_cong_surnames_with_lookup(eff_cong_mem_chk, rl_db_chk)
            elif isinstance(rl_db_chk, Mapping) and isinstance(rl_db_chk.get("members_by_bioguide"), Mapping):
                valid_cong_surs = frozenset(
                    str(mv.get("surname") or "")
                    for mv in rl_db_chk["members_by_bioguide"].values()
                    if isinstance(mv, Mapping)
                    and any(
                        isinstance(tr, list) and len(tr) >= 2 and tr[0] <= eff_cong_mem_chk <= tr[1]
                        for tr in (mv.get("terms") or ())
                    )
                )
            else:
                valid_cong_surs = frozenset()
            if valid_cong_surs:
                fn_fold_chk = _nfkc_fold(clean_fn)
                pruned_mem_p = []
                changed_mem_p = False
                for p_m in obj["personas"]:
                    if isinstance(p_m, dict) and p_m.get("entity_type") == "member":
                        s_m = surname_token_v6(str(p_m.get("name") or ""))
                        if s_m and s_m not in norm_txt and s_m not in fn_fold_chk and s_m not in valid_cong_surs:
                            changed_mem_p = True
                            continue
                    pruned_mem_p.append(p_m)
                if changed_mem_p:
                    if pruned_mem_p:
                        obj["personas"] = pruned_mem_p
                    else:
                        obj.pop("personas", None)

        if r_mod is not None and hasattr(r_mod, "apply_relational_post_pass_v6"):
            try:
                obj = r_mod.apply_relational_post_pass_v6(
                    obj,
                    dict(relational),
                    filename=clean_fn,
                    text=p12_lines or text,
                    hsru_status=hsru_status,
                    lookup=_get_rosters_lookup_v6(),
                )
            except Exception:
                pass
        else:
            # Built-in guarded relational fill preserving all Gold360 / Host-vs-Author / p1-2 invariants
            rel_cong = relational.get("rel_congress")
            if (
                "congress" not in obj
                and isinstance(rel_cong, int)
                and not isinstance(rel_cong, bool)
                and 1 <= rel_cong <= 130
                and pk in CONTEMPORARY_CONGRESSIONAL_KINDS
                and not is_exhibit
                and not is_sd_sub
            ):
                obj["congress"] = rel_cong

            rel_cmts = relational.get("rel_committees")
            if (
                "committees" not in obj
                and isinstance(rel_cmts, (list, tuple))
                and rel_cmts
                and pk in FORMAL_COMMITTEE_KINDS
                and hsru_status != "rules_host"
                and not is_exhibit
                and not is_sd_sub
            ):
                obj["committees"] = [str(c) for c in rel_cmts if str(c).strip()]

            rel_ch = relational.get("rel_chamber")
            if (
                "chamber" not in obj
                and isinstance(rel_ch, str)
                and rel_ch in ("house", "senate", "joint", "commission")
                and pk in FORMAL_COMMITTEE_KINDS
                and pk not in HOST_CHAMBER_EXEMPT_KINDS_V6
                and hsru_status != "rules_host"
                and not is_exhibit
                and not is_sd_sub
            ):
                obj["chamber"] = rel_ch

            # Single-witness rescue ONLY on core single-witness kinds (`34/34` exact on Gold360) and never `-SD00x`
            if not is_sd_sub and pk in CORE_WITNESS_AUTHOR_KINDS_V6:
                wks = relational.get("witness_keys")
                rel_w_persona = relational.get("rel_witness_persona")
                if (
                    isinstance(wks, (list, tuple))
                    and len(wks) == 1
                    and isinstance(rel_w_persona, Mapping)
                    and isinstance(rel_w_persona.get("name"), str)
                ):
                    cur_pers = [p for p in (obj.get("personas") or []) if isinstance(p, dict)]
                    w_sur = surname_token_v6(str(rel_w_persona["name"]))
                    if not cur_pers and w_sur and (w_sur in norm_txt or pk == "truth_in_testimony_disclosure"):
                        obj["personas"] = [dict(rel_w_persona)]
                    else:
                        for p in cur_pers:
                            if surname_token_v6(str(p.get("name") or "")) == w_sur:
                                for wk_field in ("org", "title", "creds", "on_behalf_of"):
                                    if wk_field not in p and rel_w_persona.get(wk_field):
                                        p[wk_field] = rel_w_persona[wk_field]

            # Enrich missing `party_state` on already-extracted Member personas (`0` F1 risk)
            bio_map = relational.get("member_party_state_by_surname")
            if isinstance(bio_map, Mapping) and "personas" in obj:
                for p in obj["personas"]:
                    if isinstance(p, dict) and p.get("entity_type") == "member" and "party_state" not in p:
                        ps_val = bio_map.get(surname_token_v6(str(p.get("name") or "")))
                        if isinstance(ps_val, str) and ps_val:
                            p["party_state"] = ps_val

            # Text-grounded official bill `short_title` from `bills.parquet`
            rel_bill_sts = relational.get("rel_bill_short_titles")
            if isinstance(rel_bill_sts, (list, tuple)) and rel_bill_sts:
                cur_st = [str(s) for s in (obj.get("short_titles") or []) if isinstance(s, str)]
                seen_st = {_nfkc_fold(s) for s in cur_st}
                for bst in rel_bill_sts:
                    if isinstance(bst, str) and bst.strip():
                        nf = _nfkc_fold(bst)
                        if nf and nf not in seen_st and nf in norm_txt and len(cur_st) < 8:
                            seen_st.add(nf)
                            cur_st.append(bst.strip())
                if cur_st:
                    obj["short_titles"] = cur_st[:8]

        # Verified committee leadership salutation recovery on `witness_statement` (`100.0%` precision via `rosters_lookup_v6`)
        if (
            pk == "witness_statement"
            and not is_sd_sub
            and not is_exhibit
            and r_mod is not None
            and hasattr(r_mod, "lookup_committee_roster_v6")
        ):
            eff_cong_sal = obj.get("congress") or relational.get("rel_congress")
            eff_codes_sal = list(relational.get("rel_host_committee_codes") or ())
            if eff_cong_sal and eff_codes_sal:
                try:
                    roster_sal = r_mod.lookup_committee_roster_v6(
                        eff_cong_sal, eff_codes_sal, lookup=_get_rosters_lookup_v6()
                    )
                    cur_p_sal = [p for p in (obj.get("personas") or []) if isinstance(p, dict) and p.get("name")]
                    cur_roles_sal = {p.get("role") for p in cur_p_sal}
                    seen_surs_sal = {surname_token_v6(str(p.get("name") or "")) for p in cur_p_sal}
                    head_sal = _norm_ws_prefix(p12_lines or text or "", 850)
                    added_sal = False
                    if "chair" not in cur_roles_sal and "presiding" not in cur_roles_sal:
                        for m_ch in re.finditer(r"\bChair(?:man|woman|person)?\s+([A-Z][A-Za-z'\u00C0-\u024F-]+)", head_sal):
                            sur_ch = surname_token_v6(m_ch.group(1))
                            hits_ch = [x for x in roster_sal["chairs"] if x.get("surname") == sur_ch]
                            if len({x.get("bioguide_id") for x in hits_ch}) == 1 and sur_ch not in seen_surs_sal and len(cur_p_sal) < MAX_PERSONAS:
                                seen_surs_sal.add(sur_ch)
                                cur_p_sal.append({"name": hits_ch[0]["name"], "role": "chair", "entity_type": "member"})
                                added_sal = True
                    if "ranking_member" not in cur_roles_sal:
                        rl_db = _get_rosters_lookup_v6() or {}
                        mem_by_bg = rl_db.get("members_by_bioguide") if isinstance(rl_db, Mapping) else None
                        eff_ch_sal = obj.get("chamber") or relational.get("rel_host_chamber")
                        for m_rm in re.finditer(r"\bRanking\s+Member\s+([A-Z][A-Za-z'\u00C0-\u024F-]+)", head_sal):
                            sur_rm = surname_token_v6(m_rm.group(1))
                            hits_rm = [x for x in roster_sal["ranking_members"] if x.get("surname") == sur_rm]
                            if not hits_rm and not roster_sal["ranking_members"] and isinstance(mem_by_bg, Mapping):
                                cand_mems = [
                                    {"bioguide_id": bg_id, "name": mv.get("name")}
                                    for bg_id, mv in mem_by_bg.items()
                                    if isinstance(mv, Mapping)
                                    and mv.get("surname") == sur_rm
                                    and any(
                                        isinstance(tr, list)
                                        and len(tr) >= 4
                                        and tr[0] <= eff_cong_sal <= tr[1]
                                        and (not eff_ch_sal or tr[3] == eff_ch_sal)
                                        for tr in (mv.get("terms") or ())
                                    )
                                ]
                                if len(cand_mems) == 1 and isinstance(cand_mems[0]["name"], str):
                                    hits_rm = cand_mems
                            if len({x.get("bioguide_id") for x in hits_rm}) == 1 and sur_rm not in seen_surs_sal and len(cur_p_sal) < MAX_PERSONAS:
                                seen_surs_sal.add(sur_rm)
                                cur_p_sal.append({"name": hits_rm[0]["name"], "role": "ranking_member", "entity_type": "member"})
                                added_sal = True
                    if added_sal:
                        obj["personas"] = cur_p_sal[:MAX_PERSONAS]
                except Exception:
                    pass

        # Text-and-graph verified addressee committee repair on `-SD` `external_submission_letter` when LLM hallucinated an unprinted committee
        if (
            pk == "external_submission_letter"
            and is_sd_sub
            and hsru_status != "rules_host"
            and isinstance(obj.get("committees"), list)
            and obj["committees"]
        ):
            rel_host_cmts = [
                str(c).strip()
                for c in (relational.get("rel_host_committees") or ())
                if isinstance(c, str) and str(c).strip() and "rules" not in str(c).lower()
            ]
            if len(rel_host_cmts) == 1:
                head_fold_sd = _nfkc_fold(_norm_ws_prefix(p12_lines or text or "", 950))
                full_fold_sd = _nfkc_fold(p12_lines or text or "")
                strip_pref_re = re.compile(
                    r"^(?:u\.?s\.?\s+|united\s+states\s+)?(?:house\s+|senate\s+)?(?:permanent\s+select\s+|select\s+|special\s+)?committee\s+on\s+(?:the\s+)?",
                    re.I,
                )
                host_jur = strip_pref_re.sub("", rel_host_cmts[0]).strip().lower()
                pred_jurs = [strip_pref_re.sub("", str(pc)).strip().lower() for pc in obj["committees"] if isinstance(pc, str)]
                if (
                    len(host_jur) >= 6
                    and host_jur in head_fold_sd
                    and pred_jurs
                    and all(pj and pj != host_jur and pj not in full_fold_sd for pj in pred_jurs)
                ):
                    obj["committees"] = rel_host_cmts

        rel_summary = {
            k: relational.get(k)
            for k in (
                "rel_congress",
                "rel_chamber",
                "rel_committees",
                "rel_subcommittees",
                "rel_event_date",
                "rel_event_title",
                "rel_event_type",
                "rel_venue",
                "rel_witness_name",
                "rel_member_name",
                "rel_member_party_state",
                "rel_bill_short_titles",
                "rel_crs_policy_area",
            )
            if k in relational and relational.get(k) is not None
        }

    # (3a) R7: a subcommittee stays only if the page names it or the advisory committee code resolves to it
    if use_relational and isinstance(obj.get("subcommittees"), list) and obj["subcommittees"]:
        r_mod_subs = _load_optional_submodule("relational")
        if r_mod_subs is not None and hasattr(r_mod_subs, "ground_subcommittees_v6"):
            try:
                known_d = json.loads(known) if isinstance(known, str) else known
            except ValueError:
                known_d = None
            rel_d = relational if isinstance(relational, Mapping) else {}
            try:
                grounded_subs = r_mod_subs.ground_subcommittees_v6(
                    obj["subcommittees"],
                    text=p12_lines or text_for_v5 or text,
                    committee_codes=[
                        *((known_d or {}).get("cmt") or () if isinstance(known_d, Mapping) else ()),
                        *(rel_d.get("rel_host_committee_codes") or ()),
                    ],
                    congress=obj.get("congress") if isinstance(obj.get("congress"), int) else None,
                    trusted=rel_d.get("rel_subcommittees") or (),
                    lookup=_get_rosters_lookup_v6(),
                )
                if grounded_subs:
                    obj["subcommittees"] = grounded_subs
                else:
                    obj.pop("subcommittees", None)
            except Exception:
                pass

    # (3b) Deterministic `0`-FP persona role disambiguation (runs even when `relational` is absent)
    if use_relational and isinstance(obj.get("personas") or [], list) and obj.get("status", "usable") == "usable":
        r_mod_roles = _load_optional_submodule("relational")
        if r_mod_roles is not None and hasattr(r_mod_roles, "disambiguate_persona_roles_v6"):
            try:
                fixed_personas = r_mod_roles.disambiguate_persona_roles_v6(
                    obj.get("personas") or [],
                    primary_kind=pk if isinstance(pk, str) else None,
                    text=p12_lines or text_for_v5 or text,
                    congress=obj.get("congress") if isinstance(obj.get("congress"), int) else None,
                    lookup=_get_rosters_lookup_v6(),
                )
                if fixed_personas or "personas" in obj:
                    obj["personas"] = fixed_personas
            except Exception:
                pass

    # (3c) R8: a person named in the block above a postal address takes it as `work_addr`
    if use_relational and isinstance(obj.get("personas"), list) and obj["personas"]:
        r_mod_addr = _load_optional_submodule("relational")
        if r_mod_addr is not None and hasattr(r_mod_addr, "attach_work_addresses_v6"):
            try:
                obj["personas"] = r_mod_addr.attach_work_addresses_v6(
                    obj["personas"],
                    primary_kind=obj.get("primary_kind") if isinstance(obj.get("primary_kind"), str) else None,
                    text=p12_lines or text_for_v5 or text,
                )
            except ImportError:
                raise  # a missing address library is an installation fault, not a document the rule cannot read
            except Exception:
                pass

    known_d_final: Mapping[str, Any] | None = known if isinstance(known, Mapping) else None
    if known_d_final is None and isinstance(known, str) and known.strip():
        try:
            kd_tmp = json.loads(known)
            if isinstance(kd_tmp, Mapping):
                known_d_final = kd_tmp
        except Exception:
            known_d_final = None
    _fix_ba_fd_committees_v6(
        obj,
        known_dict=known_d_final,
        relational=relational if isinstance(relational, Mapping) else None,
        filename=clean_fn,
        norm_txt=_nfkc_fold(text_for_v5 or text or ""),
    )
    if obj.get("primary_kind") == "witness_biography":
        _enforce_witness_bio_date_restraint_v6(obj, text_for_v5 or text or "")
    h_mod_dedup = _load_optional_submodule("hygiene")
    _clean_dedup_and_cap_personas_v6(
        obj,
        primary_kind=obj.get("primary_kind") if isinstance(obj.get("primary_kind"), str) else None,
        pkey_fn=getattr(h_mod_dedup, "person_key", None) if h_mod_dedup is not None else None,
    )

    final_obj = canonicalize_docmeta_v4(obj)

    # Recompute sidecar + V6 citations, relational summary & anomaly router verdict
    final_sidecar = _pv5.derive_sidecar_v5(
        final_obj,
        filename=clean_fn,
        text=text_for_v5,
        known=known,
        provenance=sidecar.get("_resolved_prov", provenance),
        multipage=sidecar.get("_resolved_mp", multipage),
        triage=triage,
    )
    if cit_bundle:
        final_sidecar["citations_v6"] = {
            k: cit_bundle.get(k)
            for k in ("det_refs", "det_act_iris", "det_short_titles", "det_fiscal_years", "usc_oracle_invalid_refs")
            if k in cit_bundle
        }
    if line_parser_sidecar:
        final_sidecar["line_parsers_v6"] = line_parser_sidecar
    if rel_summary is not None:
        final_sidecar["relational_v6"] = rel_summary

    anom_ctx: dict[str, Any] = {
        "filename": clean_fn,
        "text": p12_lines or text_for_v5 or text,
        "known": known,
        "raw_persona_count": raw_persona_count,
        "hsru_host_status": hsru_status,
        "usc_oracle_invalid_refs": cit_bundle.get("usc_oracle_invalid_refs") if cit_bundle else None,
    }
    if isinstance(relational, Mapping):
        for rk, rv in relational.items():
            anom_ctx.setdefault(rk, rv)
    final_sidecar["anomaly_routing"] = score_docmeta_anomalies_v6(
        final_obj,
        anom_ctx,
        usc_oracle=usc_oracle,
    )
    return final_obj, final_sidecar


# ---------------------------------------------------------------------------
# 5. `PerDocGrammarHelperV6` & `PythonicEngineV6` (`FastGemma4Engine` Wrapper)
# ---------------------------------------------------------------------------


def kind_schema_str_v6(target_doc_kind: str) -> str:
    """JSON Schema for a V4-wire kind lock: one kind, or a pipe-delimited Top-K set of kinds."""
    if "|" in target_doc_kind:
        from .grammar_router_ane_v6 import build_doc_kind_set_schema_v6

        kinds = [k.strip() for k in target_doc_kind.split("|") if k.strip()]
        return json.dumps(build_doc_kind_set_schema_v6(kinds))
    return json.dumps(_pv5.build_doc_kind_schema_v5(target_doc_kind))


def kind_schema_str_v6_compact(target_doc_kind: str) -> str:
    """JSON Schema for a compact-wire (`C4`) kind lock: one kind or a pipe-delimited set."""
    from .compact_wire_v6 import build_doc_kind_compact_schema_v6

    return json.dumps(build_doc_kind_compact_schema_v6(target_doc_kind), separators=(",", ":"))


def per_doc_grammar_v6(
    gh_std: Any,
    doc_order: Sequence[int] = (),
    *,
    wire_format: str = "v4",
    doc_target_kinds: dict[int, str] | None = None,
    grammar_cache: dict[str, tuple[Any, list[int]]] | None = None,
    sync_ff_with_std: bool = False,
) -> Any:
    """The engine's per-document grammar helper with each listed document locked to its DocMeta kind."""
    from fast_gemma4.per_doc_grammar import PerDocGrammarHelper

    return PerDocGrammarHelper(
        gh_std,
        doc_order,
        doc_schema_keys=doc_target_kinds,
        schema_for_key=kind_schema_str_v6_compact if wire_format == "compact" else kind_schema_str_v6,
        grammar_cache=grammar_cache,
        sync_ff_with_std=sync_ff_with_std,
    )


def compute_shared_prefix_ids(
    encode_fn: Callable[[str], Sequence[int]],
    format_user_prompt_fn: Callable[[str, str, str], str],
) -> list[int]:
    """Compute token-level LCP across diverse metadata probes including empty `{}` / `none`.

    Probing only `'{"a": 1}'` vs `'{"b": 2}'` leaves a BPE-merged `' {"'` token in the shared
    prefix that fails when a real document row carries empty `known='{}'`.
    """
    probes = (
        ('{"a": 1}', "a.pdf", "Alpha"),
        ('{"b": 2}', "b.pdf", "Beta"),
        ('{"a":1}', "a.pdf", "Alpha"),
        ("{}", "c.pdf", "Gamma"),
        ("none", "d.pdf", "Delta"),
        ("", "e.pdf", "Epsilon"),
    )
    tok_lists = [list(encode_fn(format_user_prompt_fn(k_s, fn, txt))) for k_s, fn, txt in probes]
    if not tok_lists:
        return []
    lcp = min(len(ids) for ids in tok_lists)
    base = tok_lists[0]
    for ids in tok_lists[1:]:
        for k in range(lcp):
            if ids[k] != base[k]:
                lcp = k
                break
    return base[:lcp]


class PythonicEngineV6:
    """Unified V6 Pre-Pass -> Zero-LLM Short-Circuit -> Per-Doc `SyncKindMatcher` -> `FastGemma4Engine` -> Post-Pass V6."""

    def __init__(
        self,
        eng: Any,
        tok: Any = None,
        *,
        usc_oracle: Any = None,
        wire_format: str = "auto",
    ):
        from fast_gemma4.grammar import GrammarHelper

        from .compact_wire_v6 import (
            DOCMETA_V6_COMPACT_SCHEMA_STR,
            build_prompt_v6_compact,
            detect_checkpoint_wire_format,
        )

        self.eng = eng
        resolved_tok = tok if tok is not None else getattr(eng, "tokenizer", None)
        if resolved_tok is None:
            raise ValueError("PythonicEngineV6 requires either `tok` or `eng.tokenizer`.")
        self.tok = resolved_tok
        self.usc_oracle = usc_oracle

        wf_norm = str(wire_format or "auto").strip().lower()
        if wf_norm == "auto":
            m_dir = getattr(eng, "model_dir", getattr(getattr(eng, "model", None), "model_dir", None))
            wf_norm = detect_checkpoint_wire_format(m_dir)
        self.wire_format = "compact" if wf_norm in ("compact", "compact_v6") else "v4"
        self._schema_str = DOCMETA_V6_COMPACT_SCHEMA_STR if self.wire_format == "compact" else SCHEMA_V4_STR
        self._build_prompt_fn = build_prompt_v6_compact if self.wire_format == "compact" else build_prompt_v4

        new_to_old = getattr(eng, "new_to_old", getattr(eng, "_new_to_old", None))
        if new_to_old is None and hasattr(eng, "model"):
            new_to_old = getattr(eng.model, "new_to_old", None)
        from .silicon_runtime_v6 import format_chat_no_thinking, resolve_default_whitespace_flexible

        self.gh_std = GrammarHelper(
            resolved_tok,
            self._schema_str,
            new_to_old,
            whitespace_flexible=resolve_default_whitespace_flexible(eng),
        )
        self._kind_grammar_cache: dict[str, tuple[Any, list[int]]] = {}

        def _fmt_chat(msgs: list[dict[str, str]]) -> str:
            return format_chat_no_thinking(resolved_tok, msgs)

        self._fmt_chat = _fmt_chat
        self.shared_sys_ids: list[int] = compute_shared_prefix_ids(
            lambda text: resolved_tok.encode(text, add_special_tokens=False),
            lambda k_s, fn, txt: _fmt_chat([{"role": "user", "content": self._build_prompt_fn(k_s, fn, txt)}]),
        )

    def get_kind_grammar(self, target_doc_kind: str) -> tuple[Any, list[int]]:
        helper = per_doc_grammar_v6(
            self.gh_std,
            wire_format=self.wire_format,
            grammar_cache=self._kind_grammar_cache,
        )
        return helper.get_grammar_entry(target_doc_kind)

    def run_records(
        self,
        records: list[dict[str, Any]],
        max_tokens: int = MAX_OUTPUT_TOKENS,
        B_slots: int = 256,
        refill_min: int = 32,
        doc_cap_full: int = 2048,
        swa_ring_cap: int = 512,
        sort_by_length: bool = True,
        *,
        use_provenance: bool = True,
        use_multipage: bool = True,
        use_provenance_link_anchor: bool = True,
        use_hygiene: bool = True,
        use_cover_locks: bool = True,
        use_citations: bool = True,
        use_relational: bool = True,
        use_zero_llm_bypass: bool = True,
        short_circuit_triage: bool = True,
        use_ane_ring: bool | str = False,
    ) -> dict[str, Any]:
        """Run Pre-Pass V6 -> Zero-LLM / Triage Short-Circuit -> `FastQATEngineV4` -> Post-Pass V6."""
        t_pre0 = time.perf_counter()
        N = len(records)
        if N == 0:
            return {
                "clean_texts": [],
                "clean_objs": [],
                "sidecars": [],
                "anomaly_reports": [],
                "raw_llm_texts": [],
                "out_tok_lens": [],
                "pre_metas": [],
                "tier1_locked_indices": [],
                "tier1_locked_by_kind": {},
                "cover_locked_indices": [],
                "link_anchor_locked_indices": [],
                "triage_short_circuited_indices": [],
                "zero_llm_bypassed_indices": [],
                "ttf_locked_indices": [],
                "congress_enriched_indices": [],
                "cmt_enriched_indices": [],
                "cms_stripped_indices": [],
                "hsru_host_stripped_indices": [],
                "shared_prefix_len": len(self.shared_sys_ids),
                "pre_sec": 0.0,
                "prefill_sec": 0.0,
                "decode_sec": 0.0,
                "post_sec": 0.0,
                "llm_sec": 0.0,
                "total_sec": 0.0,
                "docs_per_sec": 0.0,
                "mask_fallbacks": 0,
                "llm_steps": 0,
                "ff_early14_steps": 0,
            }

        pre_metas: list[dict[str, Any]] = []
        active_indices: list[int] = []
        prompts: list[str] = []
        doc_target_kinds: dict[int, str] = {}
        all_locked_indices: list[int] = []
        cover_locked_indices: list[int] = []
        link_anchor_locked_indices: list[int] = []
        triage_short_circuited_indices: list[int] = []
        zero_llm_bypassed_indices: list[int] = []
        ttf_indices: list[int] = []
        tier1_by_kind: dict[str, list[int]] = {}

        for idx, r in enumerate(records):
            raw_known = r.get("known")
            known_arg = copy.deepcopy(raw_known) if isinstance(raw_known, dict) else raw_known
            fn_r = r.get("filename", "")
            txt_r = r.get("text", "")
            p12_lines_r = r.get("p12_lines") if use_hygiene else None

            prov_arg = (r.get("provenance") or r) if use_provenance else None
            mp_arg = r.get("multipage") if use_multipage else None
            if use_multipage and mp_arg is None and r.get("full_text") and r.get("page_offsets"):
                mp_arg = extract_multipage_signals_v5(
                    r["full_text"],
                    r["page_offsets"],
                    filename=fn_r,
                )
            rel_arg = r.get("relational") if use_relational else None
            cit_arg = r.get("citations") if use_citations else None
            hyg_arg = r.get("hygiene") if use_hygiene else None

            enr_known_str, pmeta = pre_pass_v6(
                known_arg,
                fn_r,
                txt_r,
                p12_lines=p12_lines_r,
                explicit_format=r.get("effective_format") or r.get("format"),
                body_sha_hex=r.get("body_sha_hex") or r.get("sha256"),
                provenance=prov_arg,
                multipage=mp_arg,
                relational=rel_arg,
                citations=cit_arg,
                hygiene=hyg_arg,
                http_status=r.get("http_status"),
                known_valid_empty=bool(r.get("known_valid_empty", False)),
                body_state=r.get("body_state"),
                text_source=r.get("text_source"),
                sub_disposition=r.get("sub_disposition"),
                triage_status=r.get("triage_status"),
                use_hygiene=use_hygiene,
                use_cover_locks=use_cover_locks,
                use_provenance_link_anchor=use_provenance and use_provenance_link_anchor,
                use_zero_llm_bypass=use_zero_llm_bypass,
            )
            pre_metas.append(pmeta)

            if short_circuit_triage and pmeta["triage"] is not None:
                triage_short_circuited_indices.append(idx)
                continue

            if use_zero_llm_bypass and pmeta["zero_llm_docmeta"] is not None:
                zero_llm_bypassed_indices.append(idx)
                tk_b = pmeta["tier1_target_kind"]
                if tk_b is not None:
                    all_locked_indices.append(idx)
                    tier1_by_kind.setdefault(tk_b, []).append(idx)
                    if tk_b == "truth_in_testimony_disclosure":
                        ttf_indices.append(idx)
                continue

            local_slot = len(active_indices)
            active_indices.append(idx)
            # Preserve V4/V5 raw prompt text distribution identically (`fn_r` & `txt_r`)!
            prompt_str = self._fmt_chat(
                [
                    {
                        "role": "user",
                        "content": self._build_prompt_fn(
                            enr_known_str,
                            fn_r,
                            txt_r,
                        ),
                    }
                ]
            )
            prompts.append(prompt_str)
            tkind = pmeta["tier1_target_kind"]
            if tkind is not None:
                doc_target_kinds[local_slot] = tkind
                all_locked_indices.append(idx)
                tier1_by_kind.setdefault(tkind, []).append(idx)
                lsrc = pmeta.get("grammar_lock_source")
                if lsrc == "provenance_link_anchor":
                    link_anchor_locked_indices.append(idx)
                elif lsrc not in (None, "tier1_text"):
                    cover_locked_indices.append(idx)
                if tkind == "truth_in_testimony_disclosure":
                    ttf_indices.append(idx)

        N_act = len(active_indices)
        raw_llm_texts: list[str] = [""] * N
        out_tok_lens: list[int] = [0] * N

        if N_act > 0:
            from fast_gemma4.per_doc_grammar import compute_rolling_doc_order

            prompts_ids = [self.tok.encode(p, add_special_tokens=False) for p in prompts]
            if N_act >= 2:
                lcp = min(len(x) for x in prompts_ids)
                for k in range(lcp):
                    if any(x[k] != prompts_ids[0][k] for x in prompts_ids[1:]):
                        lcp = k
                        break
                sys_ids = prompts_ids[0][:lcp]
            else:
                lcp = len(self.shared_sys_ids)
                assert prompts_ids[0][:lcp] == self.shared_sys_ids
                sys_ids = self.shared_sys_ids
            assert len(sys_ids) >= len(self.shared_sys_ids), (
                f"Shared SYS_DOCMETA_V4 prefix_kv broken: {len(sys_ids)} < {len(self.shared_sys_ids)}"
            )

            for k in set(doc_target_kinds.values()):
                self.get_kind_grammar(k)

            eff_b_slots = min(B_slots, N_act)
            gh_dispatch: Any = (
                per_doc_grammar_v6(
                    self.gh_std,
                    (),
                    wire_format=self.wire_format,
                    doc_target_kinds=doc_target_kinds,
                    grammar_cache=self._kind_grammar_cache,
                    sync_ff_with_std=True,
                )
                if doc_target_kinds
                else self.gh_std
            )
            up_fn = getattr(gh_dispatch, "upfront_ff_for_doc", None)
            std_up_ff = list(self.gh_std.upfront_ff)
            upfront_by_slot: list[list[int]] = [
                list(up_fn(doc_idx)) if callable(up_fn) else list(std_up_ff)
                for doc_idx in range(N_act)
            ]
            suf_ids: list[list[int]] = [x[lcp:] + upfront_by_slot[doc_idx] for doc_idx, x in enumerate(prompts_ids)]

            doc_order = compute_rolling_doc_order(
                suf_ids,
                b_slots=eff_b_slots,
                sort_by_length=sort_by_length,
            )
            if doc_target_kinds:
                if hasattr(gh_dispatch, "_doc_order"):
                    gh_dispatch._doc_order = list(doc_order)
                else:
                    gh_dispatch = per_doc_grammar_v6(
                        self.gh_std,
                        doc_order,
                        wire_format=self.wire_format,
                        doc_target_kinds=doc_target_kinds,
                        grammar_cache=self._kind_grammar_cache,
                        sync_ff_with_std=True,
                    )
            pre_sec = time.perf_counter() - t_pre0

            res = self.eng.run_rolling(
                sys_ids=sys_ids,
                suf_ids_list=suf_ids,
                schema_str=self._schema_str,
                tok=self.tok,
                max_tokens=max_tokens,
                B_slots=eff_b_slots,
                refill_min=min(refill_min, N_act),
                doc_cap_full=doc_cap_full,
                swa_ring_cap=swa_ring_cap,
                gh=gh_dispatch,
                sort_by_length=sort_by_length,
                use_ane_ring=use_ane_ring,
            )
            if doc_target_kinds:
                assert gh_dispatch._cursor == N_act, f"Dispatched {gh_dispatch._cursor}/{N_act} matchers"
                assert set(gh_dispatch.dispatched_doc_indices) == set(range(N_act))

            for slot_i, g in enumerate(res["gen_toks"]):
                orig_idx = active_indices[slot_i]
                full_toks = upfront_by_slot[slot_i] + list(g)
                raw_llm_texts[orig_idx] = self.tok.decode(full_toks, skip_special_tokens=True)
                out_tok_lens[orig_idx] = len(full_toks)

            tot_prefill_sec = res["prefill_sec"]
            tot_decode_sec = res["decode_sec"]
            mask_fallbacks = res["mask_fallbacks"]
            llm_steps = res["llm_steps"]
            ff_early14_steps = res.get("ff_early14_steps", 0)
            shared_prefix_len = len(sys_ids)
        else:
            pre_sec = time.perf_counter() - t_pre0
            tot_prefill_sec = 0.0
            tot_decode_sec = 0.0
            mask_fallbacks = 0
            llm_steps = 0
            ff_early14_steps = 0
            shared_prefix_len = len(self.shared_sys_ids)

        t_post0 = time.perf_counter()
        clean_objs: list[dict[str, Any]] = []
        clean_texts: list[str] = []
        sidecars: list[dict[str, Any]] = []
        anomaly_reports: list[dict[str, Any]] = []

        for idx, (raw_txt, r, pmeta) in enumerate(zip(raw_llm_texts, records, pre_metas)):
            target_pk = pmeta.get("tier1_target_kind")
            salvaged = False
            if short_circuit_triage and pmeta["triage"] is not None:
                parsed_raw = pmeta["triage"]["docmeta"]
                raw_llm_texts[idx] = json.dumps(parsed_raw, separators=(",", ":"), ensure_ascii=False)
            elif use_zero_llm_bypass and pmeta["zero_llm_docmeta"] is not None:
                parsed_raw = pmeta["zero_llm_docmeta"]
                raw_llm_texts[idx] = json.dumps(parsed_raw, separators=(",", ":"), ensure_ascii=False)
            else:
                try:
                    parsed_cand_obj = json.loads(raw_txt)
                    if isinstance(parsed_cand_obj, Mapping) and self.wire_format == "compact":
                        from .compact_wire_v6 import expand_compact_v6_to_v4

                        parsed_raw = expand_compact_v6_to_v4(parsed_cand_obj)
                    elif isinstance(parsed_cand_obj, dict):
                        parsed_raw = parsed_cand_obj
                    else:
                        parsed_raw = _salvage_truncated_docmeta_v4(
                            raw_txt,
                            filename=r.get("filename", ""),
                            wire_format=self.wire_format,
                            target_primary_kind=target_pk,
                        )
                        salvaged = True
                except Exception:
                    parsed_raw = _salvage_truncated_docmeta_v4(
                        raw_txt,
                        filename=r.get("filename", ""),
                        wire_format=self.wire_format,
                        target_primary_kind=target_pk,
                    )
                    salvaged = True

            def _run_post(cand: dict[str, Any], triage_val: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
                return post_pass_v6(
                    cand,
                    known=r.get("known"),
                    filename=r.get("filename", ""),
                    text=r.get("text", ""),
                    p12_lines=pmeta.get("p12_lines"),
                    explicit_format=r.get("effective_format") or r.get("format"),
                    pre_meta=pmeta,
                    provenance=pmeta["provenance"],
                    multipage=pmeta["multipage"],
                    triage=triage_val,
                    relational=pmeta.get("relational"),
                    citations=pmeta.get("citations"),
                    hygiene=pmeta.get("hygiene"),
                    use_citations=use_citations,
                    use_relational=use_relational,
                    use_hygiene=use_hygiene,
                    usc_oracle=self.usc_oracle,
                )

            triage_arg = pmeta["triage"] if short_circuit_triage else None
            clean_obj_pair: tuple[dict[str, Any], dict[str, Any]] | None = None
            try:
                clean_obj_pair = _run_post(parsed_raw, triage_arg)
            except DocMetaValidationError:
                if not has_structural_docmeta_corruption_v4(parsed_raw, require_primary_kind=not salvaged):
                    try:
                        repaired = repair_clean_docmeta_budget_v4(
                            parsed_raw,
                            filename=str(r.get("filename") or ""),
                            target_primary_kind=target_pk if salvaged else None,
                        )
                        clean_obj_pair = _run_post(repaired, triage_arg)
                    except DocMetaValidationError:
                        clean_obj_pair = None
            if clean_obj_pair is not None:
                clean_obj, sidecar = clean_obj_pair
            else:
                fn_rec = str(r.get("filename") or "")
                fallback_triage = _build_triage_result(
                    "stub_or_blank",
                    "garbled",
                    f"Malformed 2B extraction output salvaged to non-usable triage ({fn_rec[:60]})",
                )
                clean_obj, sidecar = _run_post(fallback_triage["docmeta"], fallback_triage)
            if use_zero_llm_bypass and pmeta["zero_llm_docmeta"] is not None:
                sidecar["zero_llm_bypassed"] = True
            clean_objs.append(clean_obj)
            clean_texts.append(json.dumps(clean_obj, separators=(",", ":"), ensure_ascii=False))
            sidecars.append(sidecar)
            anomaly_reports.append(sidecar["anomaly_routing"])

        post_sec = time.perf_counter() - t_post0
        tot_sec = pre_sec + tot_prefill_sec + tot_decode_sec + post_sec

        return {
            "clean_texts": clean_texts,
            "clean_objs": clean_objs,
            "sidecars": sidecars,
            "anomaly_reports": anomaly_reports,
            "raw_llm_texts": raw_llm_texts,
            "out_tok_lens": out_tok_lens,
            "pre_metas": pre_metas,
            "tier1_locked_indices": sorted(all_locked_indices),
            "tier1_locked_by_kind": tier1_by_kind,
            "cover_locked_indices": sorted(cover_locked_indices),
            "link_anchor_locked_indices": sorted(link_anchor_locked_indices),
            "triage_short_circuited_indices": sorted(triage_short_circuited_indices),
            "zero_llm_bypassed_indices": sorted(zero_llm_bypassed_indices),
            "ttf_locked_indices": ttf_indices,
            "congress_enriched_indices": [i for i, m in enumerate(pre_metas) if m["congress_enriched"]],
            "cmt_enriched_indices": [i for i, m in enumerate(pre_metas) if m["cmt_enriched"]],
            "cms_stripped_indices": [i for i, m in enumerate(pre_metas) if m["cms_nav_stripped"]],
            "hsru_host_stripped_indices": [i for i, m in enumerate(pre_metas) if m["hsru_host_stripped"]],
            "shared_prefix_len": shared_prefix_len,
            "pre_sec": pre_sec,
            "prefill_sec": tot_prefill_sec,
            "decode_sec": tot_decode_sec,
            "post_sec": post_sec,
            "llm_sec": tot_prefill_sec + tot_decode_sec,
            "total_sec": tot_sec,
            "docs_per_sec": N / tot_sec if tot_sec > 0 else 0.0,
            "mask_fallbacks": mask_fallbacks,
            "llm_steps": llm_steps,
            "ff_early14_steps": ff_early14_steps,
        }


# Backwards-compatible aliases
derive_sidecar_v6 = _pv5.derive_sidecar_v5
derive_sidecar_v5 = _pv5.derive_sidecar_v5
derive_sidecar_v4 = _pv5.derive_sidecar_v5
pre_pass_v5 = _pv5.pre_pass_v5
post_pass_v5 = _pv5.post_pass_v5
pre_pass_v4 = pre_pass_v6
post_pass_v4 = post_pass_v6

for _pv5_export in _pv5.__all__:
    if _pv5_export not in globals() and hasattr(_pv5, _pv5_export):
        globals()[_pv5_export] = getattr(_pv5, _pv5_export)

__all__ = [
    *list(_pv5.__all__),
    "ACTOR_REQUIRED_KINDS_V6",
    "COMMISSION_MASTHEAD_PATTERNS_V6",
    "CORE_WITNESS_AUTHOR_KINDS_V6",
    "DEFAULT_DOCMETA_V6_DATA_DIR",
    "DOCMETA_V4_SCHEMA_PATH",
    "HOST_CHAMBER_EXEMPT_KINDS_V6",
    "HOUSE_SELECT_2LETTER_EXTRA_V6",
    "LEGISLATIVE_DRAFT_KINDS_V6",
    "PythonicEngineV6",
    "build_doc_kind_schema_v6",
    "check_gist_title_grounding_v6",
    "clean_html_and_cms_v6",
    "compute_shared_prefix_ids",
    "derive_sidecar_v6",
    "detect_cover_or_sha_lock_v6",
    "infer_is_html_v6",
    "kind_schema_str_v6",
    "kind_schema_str_v6_compact",
    "load_default_usc_oracle_v6",
    "norm_committee_token_v6",
    "per_doc_grammar_v6",
    "post_pass_v6",
    "pre_pass_v6",
    "route_batch_anomalies_v6",
    "score_docmeta_anomalies_v6",
    "strict_validate_v4",
    "strip_creative_engine_download_suffix",
    "surname_token_v6",
    "triage_non_usable_v6",
    "try_zero_llm_bypass_v6",
]
