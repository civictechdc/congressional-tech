#!/usr/bin/env python3
"""Pythonic V5 Unified Deterministic Wrapper (`pythonic_v5.py`).

100.0%-precision, 100%-stdlib deterministic domain architecture around the frozen Fused V4 LoRA
(`FastQATEngineV4`), unifying all 5 phases of Deterministic V5 with zero external runtime packages
(except lazy `llguidance` when `PerDocGrammarHelperV5` / `PythonicEngineV5` runs constrained decode):

  1. `triage_non_usable_v5`:
     - Deterministically triages explicit HTTP 401/403/404/405/410/429/5xx response envelopes,
       certified unreadable containers (`ocr_unreadable`), certified empty/media stubs (`stub_or_blank`),
       0-alnum extracted containers, and unmistakable short HTML WAF/404/block shells (`error_or_block`),
       while preserving cold-R2 metadata-only rows, short usable notices/amendments, and hearings titled
       `"Access Denied: ..."`.
  2. `resolve_provenance_v5` + Post-LLM Fill Guards (`provenance/provenance_rules_v5.py`):
     - Unwraps Wayback/WebHarvest/GovInfo URLs, maps 60+ House/Senate domains, official Clerk/GPO slugs,
       `docs.house.gov/meetings/<CMT>/<YYYYMMDD>/<EventID>`, and `congress.gov` paths, rescues stripped
       slugs/Congress/meeting-dates while blocking CMS upload & Wayback date traps, detects 12 body-
       corroborated `link_text` structural genre anchors, and enforces strict Host-vs-Author separation.
  3. `extract_multipage_signals_v5` (`corpus/multipage_rules_v5.py`):
     - Rescues `p3..p8` GPO/stenographic `CONTENTS` / witness panels / opening gavel slices when `p1-2`
       is cover + standing roster only, and detects stapled back-page (`p3..N`) Truth-in-Testimony
       disclosures (with unambiguous disclosure booleans), Committee Roll-Call Votes, and QFR appendices
       without polluting `p1-2` `DocMetaV4Causal` persona/kind evaluation invariants.
  4. Expanded Text Rules (`clustering/expanded_rules_v5.py` + V5 masthead hardening):
     - `strip_html_cms_nav_v5` across 11 CMS wrapper/right-rail families (eliminating CMS time-travel
       Congress pollution while preserving `docs.house.gov` weekly schedules & GPO HTML transcripts).
     - OCR-tolerant `extract_pdf_masthead_congress_v5` & hardened `extract_formal_committee_masthead_v5`
       (blocking embargo witness headers, biographical prose lookbacks, and cross-committee Clerk slugs).
     - All 32 mutually-exclusive 100.0%-precision Tier-1 `doc_kind` signatures (`21` V4 + `11` new V5)
       plus non-locking `detect_tier2_sidecar_hints_v5`.
  5. `PythonicEngineV5` + `PerDocGrammarHelperV5` + `SyncKindMatcher` + `post_pass_v5` + `derive_sidecar_v5`:
     - Preserves 100% shared `SYS_DOCMETA_V4` `EarlyExit14` `prefix_kv` (`1,368` tokens), unlocked
       `chamber` in per-kind `LLMatcher` schemas, `SyncKindMatcher` zero-jitter batch alignment,
       `<NONE>` pre-LLM prompt distribution, raw HTML prompt distribution, and strict `DocMetaV4Causal`
       causal key ordering and schema validity.
"""

from __future__ import annotations

import copy
import datetime
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Sequence

DOCMETA_DIR = Path(__file__).resolve().parent
DET_V5_DIR = DOCMETA_DIR
V4_DIR = DOCMETA_DIR

SCHEMA_V4_STR = (DOCMETA_DIR / "docmeta_v4_causal.schema.json").read_text(encoding="utf-8")
SCHEMA_OBJ: dict[str, Any] = json.loads(SCHEMA_V4_STR)

TOP_KEYS_ORDER = list(SCHEMA_OBJ["properties"].keys())
PERSONA_KEYS_ORDER = list(SCHEMA_OBJ["properties"]["personas"]["items"]["properties"].keys())
DISCLOSURE_KEYS_ORDER = list(SCHEMA_OBJ["properties"]["disclosure"]["properties"].keys())

DOC_KINDS_SET = set(SCHEMA_OBJ["$defs"]["doc_kind"]["enum"])
STATUS_SET = set(SCHEMA_OBJ["properties"]["status"]["enum"])
TEXT_QUALITY_SET = set(SCHEMA_OBJ["properties"]["text_quality"]["enum"])
ROLES_SET = set(SCHEMA_OBJ["properties"]["personas"]["items"]["properties"]["role"]["enum"])
ETYPES_SET = set(SCHEMA_OBJ["properties"]["personas"]["items"]["properties"]["entity_type"]["enum"])

from .prompt_v4 import SYS_DOCMETA_V4, build_prompt_v4
from . import expanded_rules_v5 as _exv5
from . import multipage_rules_v5 as _mpv5
from . import provenance_rules_v5 as _prv5
from .expanded_rules_v5 import (
    CANONICAL_COMMITTEES_V5,
    CMS_STRIPPER_FAMILIES_V5,
    NEW_TIER1_SIGNATURE_TO_KIND_V5,
    TIER1_SIGNATURE_IDS_V5,
    TIER1_SIGNATURE_TO_KIND_V5,
    TIER1_TARGET_KINDS_V5,
    V4_TIER1_SIGNATURE_TO_KIND,
    detect_all_tier1_signatures_v5,
    detect_exact_tier1_signature_v5,
    detect_new_tier1_signatures_v5,
    detect_tier2_sidecar_hints_v5,
    detect_v4_tier1_signatures,
    extract_official_slug_congress,
    extract_pdf_masthead_congress_v5,
    infer_is_html_v5,
    iso_date_to_congress,
    strip_html_cms_nav_v5,
)
from .multipage_rules_v5 import (
    detect_stapled_backpage_packets,
    detect_ttf_page_signature,
    detect_vote_page_signature,
    extract_gpo_p3_p8_rescue,
    extract_multipage_signals_v5,
    extract_ttf_disclosure_booleans,
    is_gpo_cover_roster_only_p12,
    is_qfr_appendix_page,
    is_steno_cover_roster_only_p12,
    match_qfr_appendix_page,
    split_pdf_pages,
    triage_unwrapped_http_or_empty,
)
from .provenance_rules_v5 import (
    DOMAIN_TO_COMMITTEE_CODE,
    HOUSE_CLERK_2LETTER_TO_CODE,
    PROVENANCE_SAFE_COMMITTEE_KINDS,
    can_fill_docmeta_chamber_v5,
    can_fill_docmeta_committees_v5,
    can_fill_docmeta_congress_v5,
    can_fill_docmeta_event_date_v5,
    committee_code_to_canonical,
    detect_provenance_link_anchor,
    extract_url_dates_and_congress,
    extract_url_official_slug_info,
    norm_committee_compare,
    normalize_parent_committee_code,
    resolve_provenance_v5,
    unwrap_archive_url,
)

TOP_ORDER_IDX = {k: i for i, k in enumerate(TOP_KEYS_ORDER)}
PERSONA_ORDER_IDX = {k: i for i, k in enumerate(PERSONA_KEYS_ORDER)}
DISCLOSURE_ORDER_IDX = {k: i for i, k in enumerate(DISCLOSURE_KEYS_ORDER)}

WS_RE = re.compile(r"[ \t\r\n]+")
_ALNUM_RE = re.compile(r"[A-Za-z0-9]")

# Document kinds authored contemporaneously within a specific Congressional session.
CONTEMPORARY_CONGRESSIONAL_KINDS = frozenset(
    {
        "hearing_transcript",
        "witness_statement",
        "member_opening_statement",
        "member_or_floor_statement",
        "truth_in_testimony_disclosure",
        "witness_biography",
        "witness_list",
        "member_roster",
        "attendance_quorum_sheet",
        "nominee_questionnaire_apq",
        "hearing_notice",
        "markup_notice",
        "hearing_memo_or_charter",
        "meeting_results",
        "committee_vote",
        "bill_or_draft",
        "committee_amendment",
        "comparative_print",
        "section_by_section",
        "committee_report",
        "explanatory_statement",
        "committee_resolution",
        "committee_rules",
        "oversight_plan",
        "budget_views_and_estimates",
        "revenue_or_cost_estimate",
        "treaty_document",
        "gsa_prospectus_or_property",
        "oversight_letter",
        "witness_invitation",
        "nomination_or_support_letter",
        "external_submission_letter",
        "legislative_schedule_or_calendar",
        "event_web_page",
    }
)

# Committee-proceeding genres that have 100.0% non-empty `committees` attribution in Gold360.
FORMAL_COMMITTEE_KINDS = frozenset(
    {
        "hearing_transcript",
        "truth_in_testimony_disclosure",
        "witness_biography",
        "witness_list",
        "member_roster",
        "attendance_quorum_sheet",
        "qfr_request",
        "nominee_questionnaire_apq",
        "hearing_notice",
        "markup_notice",
        "hearing_memo_or_charter",
        "meeting_results",
        "committee_vote",
        "bill_or_draft",
        "comparative_print",
        "committee_report",
        "committee_resolution",
        "committee_rules",
        "oversight_plan",
        "budget_views_and_estimates",
        "witness_invitation",
    }
)

VOTE_ALLOWED_ROLES = frozenset(
    {"chair", "ranking_member", "presiding", "amendment_offeror", "sponsor", "nominee"}
)
GPO_COVER_ROSTER_ALLOWED_ROLES = frozenset(
    {"chair", "ranking_member", "presiding", "witness", "nominee", "staff"}
)
QUORUM_ROSTER_ALLOWED_ROLES = frozenset(
    {"chair", "ranking_member", "presiding", "staff"}
)

EVAL_KIND_FAMILIES = {
    "qfr_request": "qfr",
    "qfr_response": "qfr",
    "witness_statement": "statement",
    "member_opening_statement": "statement",
    "member_or_floor_statement": "statement",
    "hearing_notice": "notice",
    "markup_notice": "notice",
    "committee_vote": "vote_or_results",
    "meeting_results": "vote_or_results",
    "oversight_letter": "letter_or_submission",
    "witness_invitation": "letter_or_submission",
    "nomination_or_support_letter": "letter_or_submission",
    "external_submission_letter": "letter_or_submission",
    "public_comment_or_submission": "letter_or_submission",
    "agency_or_gao_crs_report": "report",
    "external_report_or_whitepaper": "report",
    "committee_report": "report",
    "bill_or_draft": "legislative_text",
    "committee_amendment": "legislative_text",
    "comparative_print": "legislative_text",
    "section_by_section": "legislative_text",
    "explanatory_statement": "legislative_text",
    "investigative_exhibit": "investigative",
    "legal_or_investigative_filing": "investigative",
}

DOC_FAMILY_MAP = {
    **EVAL_KIND_FAMILIES,
    "hearing_transcript": "transcript",
    "truth_in_testimony_disclosure": "disclosure",
    "witness_biography": "biography",
    "nominee_questionnaire_apq": "disclosure",
    "witness_list": "roster_or_quorum",
    "member_roster": "roster_or_quorum",
    "attendance_quorum_sheet": "roster_or_quorum",
    "hearing_memo_or_charter": "charter_or_memo",
    "committee_resolution": "committee_governance",
    "committee_rules": "committee_governance",
    "oversight_plan": "committee_governance",
    "budget_views_and_estimates": "budget_or_estimate",
    "revenue_or_cost_estimate": "budget_or_estimate",
    "gsa_prospectus_or_property": "property_or_prospectus",
    "treaty_document": "treaty",
    "news_clip_or_article": "media_or_press",
    "press_release_or_fact_sheet": "media_or_press",
    "legislative_schedule_or_calendar": "web_or_schedule",
    "event_web_page": "web_or_schedule",
    "slides_or_visual": "visual_or_packet",
    "multi_doc_packet": "visual_or_packet",
    "error_or_non_document": "non_document",
    "other": "other",
}

TIER1_SIGNATURE_TO_KIND = TIER1_SIGNATURE_TO_KIND_V5
TIER1_SIGNATURE_IDS = TIER1_SIGNATURE_IDS_V5
TIER1_TARGET_KINDS = TIER1_TARGET_KINDS_V5


def _norm_ws_prefix(text: str, limit: int = 2600) -> str:
    sub = text[:limit]
    if "\n" in sub or "\r" in sub or "\t" in sub or "  " in sub:
        return WS_RE.sub(" ", sub).strip()
    return sub.strip()


# ---------------------------------------------------------------------------
# 1. Layer 1: Deterministic Non-Usable Triage (`triage_non_usable_v5`)
# ---------------------------------------------------------------------------

_WAF_OR_HTTP_ERROR_SHELL_RE = re.compile(
    r"(?:"
    r"^(?:404\s+Not\s+Found|403\s+Forbidden|401\s+Unauthorized|410\s+Gone|"
    r"500\s+Internal\s+Server\s+Error|502\s+Bad\s+Gateway|503\s+Service\s+Unavailable|"
    r"Page\s+Not\s+Found\s*[-|:]|The\s+page\s+cannot\s+be\s+found\b|"
    r"The\s+requested\s+URL\s+\S+\s+was\s+not\s+found\s+on\s+this\s+server\b)"
    r"|^Access\s+Denied\s+You\s+don't\s+have\s+permission\s+to\s+access\b"
    r"|^Attention\s+Required!\s*\|\s*Cloudflare\b"
    r"|^Just\s+a\s+moment\.\.\.\s*Enable\s+JavaScript\s+and\s+cookies\b"
    r"|\bWe're\s+sorry,\s+this\s+site\s+is\s+currently\s+experiencing\s+technical\s+difficulties\."
    r".{0,140}?\bException:\s*(?:request\s+blocked|forbidden|access\s+denied)\b"
    r")",
    re.I,
)
_USABLE_CONGRESSIONAL_CUE_RE = re.compile(
    r"\b(?:committee|subcommittee|hearing|markup|senate|house\s+of\s+representatives|"
    r"congress|testimony|statement\s+of|memorandum|amendment|witness|roll\s+call|bill)\b",
    re.I,
)


def _build_triage_result(status: str, text_quality: str, reason: str) -> dict[str, Any]:
    clean_reason = (reason or status).strip()[:200]
    docmeta = {
        "status": status,
        "text_quality": text_quality,
        "error_reason": clean_reason,
    }
    return {
        "status": status,
        "text_quality": text_quality,
        "error_reason": clean_reason,
        "docmeta": docmeta,
    }


def triage_non_usable_v5(
    text: str | None,
    *,
    filename: str | None = None,
    http_status: int | None = None,
    known_valid_empty: bool = False,
    body_state: str | None = None,
    text_source: str | None = None,
    sub_disposition: str | None = None,
    triage_status: str | None = None,
) -> dict[str, Any] | None:
    """Return deterministic non-usable triage dict (`error_or_block` | `stub_or_blank` | `ocr_unreadable`)
    ONLY when 100.0% unrecoverable; return `None` for all usable docs and cold-R2 metadata-only rows.

    Never misclassifies hearings titled `"Access Denied: Challenges for Women- and Minority-Owned..."`
    or short usable committee notices/amendments (`BILLS-117-CP-...`, `140` chars).
    """
    if triage_status == "ocr_unreadable":
        return _build_triage_result("ocr_unreadable", "garbled", "Certified unreadable container")
    if triage_status == "error_or_block":
        return _build_triage_result("error_or_block", "native", "Certified error or blocked container")
    if triage_status == "stub_or_blank":
        return _build_triage_result("stub_or_blank", "native", "Certified empty stub container")

    if (
        not isinstance(http_status, bool)
        and isinstance(http_status, int)
        and (http_status in (401, 403, 404, 405, 410, 429) or 500 <= http_status <= 599)
    ):
        return _build_triage_result(
            "error_or_block",
            "native",
            f"HTTP {http_status} response envelope",
        )

    # Cold R2 uncached rows (`detail_metadata_only`) lack local extracted text by storage tier, NOT blankness
    if text_source == "detail_metadata_only":
        if body_state == "unreadable":
            return _build_triage_result("ocr_unreadable", "garbled", "Certified unreadable container")
        if body_state == "error":
            return _build_triage_result("error_or_block", "native", "Upstream capture error")
        if known_valid_empty:
            return _build_triage_result("stub_or_blank", "native", "Certified empty page")
        return None

    t_str = text if isinstance(text, str) else ""
    has_alnum = bool(_ALNUM_RE.search(t_str[:4000]) or (len(t_str) > 4000 and _ALNUM_RE.search(t_str)))

    if not has_alnum:
        if body_state == "unreadable":
            return _build_triage_result(
                "ocr_unreadable",
                "garbled",
                "Corrupt or unreadable binary container",
            )
        if body_state == "error":
            return _build_triage_result(
                "error_or_block",
                "native",
                "Upstream capture error without document body",
            )
        if known_valid_empty or sub_disposition in (
            "wvx_video_playlist",
            "wmv_video_container",
            "container_image",
        ):
            return _build_triage_result(
                "stub_or_blank",
                "native",
                "Certified empty or non-textual media container",
            )
        if text is not None:
            fn_low = (filename or "").strip().lower()
            if fn_low.endswith(".pdf"):
                return _build_triage_result(
                    "ocr_unreadable",
                    "garbled",
                    "Unrecoverable 0-character scanned or empty PDF",
                )
            return _build_triage_result(
                "stub_or_blank",
                "native",
                "Empty 0-character document body",
            )
        return None

    t_norm = _norm_ws_prefix(t_str, 420)
    if len(t_norm) < 320 and _WAF_OR_HTTP_ERROR_SHELL_RE.search(t_norm):
        if not _USABLE_CONGRESSIONAL_CUE_RE.search(t_norm):
            return _build_triage_result("error_or_block", "native", t_norm[:160])

    return None


# ---------------------------------------------------------------------------
# 2. Hardened Masthead & `hsru00` Host-vs-Author Helpers (`#64` + `#66` Safe)
# ---------------------------------------------------------------------------

_RX_EXHIBIT_FN = re.compile(
    r"(?:^|[^a-zA-Z])exhibit(?:[^a-zA-Z]|$)|redacted|sanitized|\b302\b",
    re.I,
)
_BIO_NARRATIVE_START_RE = re.compile(
    r"^(?:\d+\s+|Page\s+\d+(?:\s+of\s+\d+)?\s+)?"
    r"(?:(?:Biography|Biographical\s+Sketch|Curriculum\s+Vitae|Resume)\s+(?:of|for)\s+|"
    r"(?:Mr\.|Ms\.|Mrs\.|Dr\.|Prof\.|The\s+Honorable|Hon\.)\s+[A-Z][a-z]+|"
    r"[A-Z][a-z]+\s+(?:[A-Z]\.\s+)?[A-Z][a-z]+\s+(?:is\s+|serves\s+as\s+|currently\s+|joined\s+|leads\s+|was\s+|has\s+served\s+))",
)
_MASTHEAD_SENTENCE_PROSE_LOOKBACK_RE = re.compile(
    r"(?:\b(?:counsel|staff|advisor|adviser|fellow|intern|director|clerk|assistant|liaison|member|chair(?:man|woman)?)\s+"
    r"(?:to|on|of|for|with)\s+(?:the\s+)?|"
    r"\b(?:worked|served|testified|appeared|speaking|testifying|appearing)\s+"
    r"(?:for|on|with|before|at|to)\s+(?:the\s+)?|"
    r"\b(?:prior\s+to\s+joining|before\s+joining|formerly\s+with)\b.{0,90}?|"
    r"\b(?:report|submitted?|pursuant|referred|courtesy|released)\s+(?:to|by|of)\s+(?:the\s+)?)"
    r"(?:Subcommittee\s+on\s+[A-Za-z0-9 ,&'-]{2,95}\s+of\s+the\s+)?"
    r"(?:U\.?S\.?\s+)?(?:House(?:\s+of\s+Representatives)?\s*,?\s*|United\s+States\s+Senate\s*,?\s*|Senate\s+)?$",
    re.I,
)


def extract_formal_committee_masthead_v5(
    filename: str | None,
    text: str | None,
    is_html: bool | None = None,
) -> list[dict[str, str]]:
    """Extract unmistakable formal Congressional committee mastheads (`0` mismatches on `Gold360` & `260K` `S_raw`)."""
    raw_hits = _exv5.extract_formal_committee_masthead_v5(filename, text, is_html=is_html)
    if not raw_hits or not text:
        return []

    head = _norm_ws_prefix(_exv5._collapse_letter_spaced_caps(text[:950]), 880)
    base_fn = (filename or "").strip().rsplit("/", 1)[-1]
    is_bio_fn = bool(re.search(r"(?:^|[-_.\s])bio(?:graphy)?(?:$|[-_.\s])", base_fn, re.I))
    is_bio_narrative = _BIO_NARRATIVE_START_RE.match(head[:220]) is not None

    filtered: list[dict[str, str]] = []
    for item in raw_hits:
        code = item["code"]
        matched_rx = [rx for c_k, _, _, rx in CANONICAL_COMMITTEES_V5 if c_k == code]
        keep_item = False
        if not matched_rx:
            keep_item = not (is_bio_fn or is_bio_narrative)
        else:
            for rx in matched_rx:
                for m in rx.finditer(head):
                    if (is_bio_fn or is_bio_narrative) and m.start() > 140:
                        continue
                    pre_long = head[max(0, m.start() - 180) : m.start()]
                    if _MASTHEAD_SENTENCE_PROSE_LOOKBACK_RE.search(pre_long):
                        continue
                    keep_item = True
                    break
                if keep_item:
                    break
        if keep_item:
            filtered.append(item)

    return filtered


def _is_exhibit_or_external_artifact(filename: str, text: str) -> bool:
    """Guard against enriching metadata on historical investigative exhibits, emails, or court filings."""
    fn = filename or ""
    if _RX_EXHIBIT_FN.search(fn):
        return True
    head = _norm_ws_prefix(text or "", 600)
    if re.search(
        r"^(?:From:\s+.{1,120}\bSent:\s+|FOR\s+IMMEDIATE\s+RELEASE\b|IN\s+THE\s+UNITED\s+STATES\s+(?:DISTRICT|CIRCUIT)\s+COURT)",
        head,
        re.I,
    ):
        return True
    return False


def _has_congressional_proceeding_cue(known_dict: dict[str, Any], filename: str, text: str) -> bool:
    """Verify positive Congressional proceeding context before inferring Congress from `known['date']`."""
    if known_dict.get("chambers") or known_dict.get("cmt"):
        return True
    fn = filename or ""
    if re.search(
        r"hearing|markup|testimony|witness|opening|statement|advisory|notice|memo|charter|amdt|amendment|vote|roll[\s_-]*call|disclosure|ttf|qfr|billsthisweek|subcommittee|committee",
        fn,
        re.I,
    ):
        return True
    head = _norm_ws_prefix(text or "", 1000)
    return bool(
        re.search(
            r"\b(?:House\s+of\s+Representatives|United\s+States\s+Senate|U\.?S\.?\s+Senate|U\.?S\.?\s+House|Committee\s+on|Subcommittee\s+on|Hearing|Markup|Testimony|Roll\s+Call|Amendment\s+to)\b",
            head,
            re.I,
        )
    )


_HSRU_AUTHOR_RE = re.compile(
    r"(?:^(?:Page \d+ of \d+\s+|\d+\s+)?MOTION BY\b|"
    r"\bI have an amendment to the rule\b|\bI move (?:that )?the [Cc]ommittee make in order\b|"
    r"\bProviding for consideration of the (?:bill|joint resolution|resolution|senate amendment)\b|"
    r"\bFROM THE COMMITTEE ON RULES\b|"
    r"\b(?:Mr\.|Ms\.|Mrs\.)\s+\w+,\s+from the Committee on Rules,\s+submitted|"
    r"\bRecord Vote No\.\s*\d+|\bCOMMITTEE VOTES\b|\bROLL CALL\b|"
    r"\bRULES OF THE COMMITTEE ON RULES\b|"
    r"(?<!\[Showing the text as )\bORDERED REPORTED\b.{0,40}?\bCommittee on Rules\b)",
    re.I,
)
_HSRU_AUTHOR_SLUG_RE = re.compile(r"^(?:HHRG|HMTG|HMKP|CRPT)-\d{3}-RU\d{2}-", re.I)
_HSRU_HOSTED_DOC_RE = re.compile(
    r"(?:\bRULES COMMITTEE PRINT\s+11\d[–-]\d+\b|"
    r"^(?:Report Generated:\s*.{5,65}?\s+)?(?:Comparative Print:|Comparing the base document )|"
    r"^AMENDMENT (?:\(IN THE NATURE OF A SUBSTITUTE\) |IN THE NATURE OF A SUBSTITUTE )?TO RULES COMMITTEE PRINT\b|"
    r"\bEXPLANATORY STATEMENT SUBMITTED BY\b.{0,180}?\bCHAIRMAN OF THE HOUSE COMMITTEE ON|"
    r"\bJOINT EXPLANATORY STATEMENT OF THE COMMITTEE OF CONFERENCE\b|"
    r"\bas (?:ordered )?reported by the Committee on (?!Rules\b)|"
    r"\breferred to the Committee on (?!Rules\b)|"
    r"^(?:[\s.]*(?:\[[^\]]{1,40}\][\s.]*)?(?:[IVX]{1,4}[\s.]+)?(?:\(Original Signature of Member\)\s+)?)?11\dTH CONGRESS\s+(?:1ST|2D|FIRST|SECOND)\s+SESSION\s+(?:H\.\s*R\.|S\.|H\.\s*J\.\s*RES\.|H\.\s*CON\.\s*RES\.|H\.\s*RES\.)\s*(?:\d+|ll+)\b(?!.{0,120}?\bProviding for consideration of\b))",
    re.I,
)
_HSRU_UNMISTAKABLE_PRINT_RE = re.compile(
    r"^(?:(?:Report Generated:\s*.{5,65}?\s+)?(?:Comparative Print:|Comparing the base document )|"
    r"(?:[A-Z]+ \d{1,2}, 20\d\d\s+)?RULES COMMITTEE PRINT\s+11\d[–-]\d+\b)",
    re.I,
)


def classify_hsru_host_status(
    known_dict: dict[str, Any] | None,
    filename: str | None,
    text: str | None,
) -> tuple[str, list[dict[str, str]]]:
    """Classify `hsru00` metadata as `('not_hsru' | 'rules_author' | 'rules_host', originating_cmts)`."""
    cmts = [str(c).lower() for c in ((known_dict or {}).get("cmt") or [])]
    has_hsru = any(c.startswith("hsru") for c in cmts)
    raw1800 = (text or "")[:1800]
    if not has_hsru and "rules committee print" not in raw1800[:350].lower():
        return "not_hsru", []

    t_ws = _norm_ws_prefix(raw1800, 1800)
    base = (filename or "").strip().rsplit("/", 1)[-1]
    if _HSRU_AUTHOR_SLUG_RE.match(base):
        return "rules_author", []
    if not _HSRU_UNMISTAKABLE_PRINT_RE.match(t_ws[:200]) and _HSRU_AUTHOR_RE.search(t_ws[:1000]):
        return "rules_author", []

    if _HSRU_HOSTED_DOC_RE.search(t_ws):
        orig: list[dict[str, str]] = []
        seen: set[str] = set()
        for code, ch, canon_name, rx in CANONICAL_COMMITTEES_V5:
            if code == "hsru00":
                continue
            if rx.search(t_ws[:1500]) and code[:4] not in seen:
                seen.add(code[:4])
                orig.append({"code": code, "chamber": ch, "name": canon_name})
        return "rules_host", orig

    return ("rules_author" if has_hsru else "not_hsru"), []


def _norm_cmt_compare(c: str) -> str:
    return norm_committee_compare(c)


def detect_exact_ttf_form(filename: str | None, text: str | None) -> bool:
    _, kind = detect_exact_tier1_signature_v5(filename, text)
    return kind == "truth_in_testimony_disclosure"


# Backwards-compatible V4 function aliases
infer_is_html = infer_is_html_v5
strip_html_cms_nav = strip_html_cms_nav_v5
extract_pdf_masthead_congress = extract_pdf_masthead_congress_v5
extract_formal_committee_masthead = extract_formal_committee_masthead_v5
detect_all_tier1_signatures = detect_all_tier1_signatures_v5
detect_exact_tier1_signature = detect_exact_tier1_signature_v5


# ---------------------------------------------------------------------------
# 3. Per-Doc Schemas, Pre-Pass V5, Validator, Post-Pass V5 & Sidecar V5
# ---------------------------------------------------------------------------


def build_doc_kind_schema_v5(
    target_doc_kind: str,
    base_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build specialized `DocMetaV4Causal` JSON schema locking `status='usable'` & `primary_kind=target_doc_kind`.

    Preserves `chamber` unlocked across all genres so House, Senate, Joint, and omitted-chamber
    records never fail `LLMatcher` token acceptance; additionally requires non-empty `disclosure`
    (`capacity`, `gov_witness`) when `target_doc_kind == 'truth_in_testimony_disclosure'`.
    """
    if target_doc_kind not in DOC_KINDS_SET:
        raise ValueError(f"Unknown target_doc_kind: {target_doc_kind!r}")
    schema = copy.deepcopy(base_schema if base_schema is not None else SCHEMA_OBJ)
    if target_doc_kind == "truth_in_testimony_disclosure":
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
    schema["properties"]["primary_kind"] = {"type": "string", "enum": [target_doc_kind]}
    sec_enum = [k for k in schema["$defs"]["doc_kind"]["enum"] if k != target_doc_kind]
    schema["properties"]["secondary_kinds"]["items"] = {"type": "string", "enum": sec_enum}
    return schema


def build_ttf_schema_v5(base_schema: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_doc_kind_schema_v5("truth_in_testimony_disclosure", base_schema=base_schema)


build_doc_kind_schema_v4 = build_doc_kind_schema_v5
build_ttf_schema_v4 = build_ttf_schema_v5
TTF_SCHEMA_V4_OBJ = build_ttf_schema_v5()
TTF_SCHEMA_V4_STR = json.dumps(TTF_SCHEMA_V4_OBJ)


def _resolve_record_provenance(
    record_or_prov: dict[str, Any] | None,
    *,
    known_dict: dict[str, Any],
    filename: str,
    text: str,
    tier1_target_kind: str | None,
) -> dict[str, Any] | None:
    """Resolve or normalize provenance dictionary from either precomputed `provenance` or raw URL fields."""
    if not record_or_prov or not isinstance(record_or_prov, dict):
        return None
    if "host_committee_codes" in record_or_prov and "url_slug_congress" in record_or_prov:
        return record_or_prov
    if any(
        k in record_or_prov
        for k in ("urls", "listed_ons", "member_paths", "link_texts", "page_metadata", "publisher_labels")
    ):
        return resolve_provenance_v5(
            urls=record_or_prov.get("urls"),
            listed_ons=record_or_prov.get("listed_ons"),
            member_paths=record_or_prov.get("member_paths"),
            link_texts=record_or_prov.get("link_texts"),
            page_metadata=record_or_prov.get("page_metadata"),
            publisher_labels=record_or_prov.get("publisher_labels"),
            filename=filename,
            text=text,
            known_congress=known_dict.get("congress"),
            known_date=known_dict.get("date"),
            known_committee_keys=known_dict.get("cmt"),
            tier1_target_kind=tier1_target_kind,
            event_id_committee_map=record_or_prov.get("event_id_committee_map"),
        )
    return None


def _resolve_record_multipage(
    multipage_or_record: dict[str, Any] | None,
    *,
    filename: str,
    full_text: str | None = None,
    page_offsets: Sequence[int] | None = None,
) -> dict[str, Any] | None:
    """Resolve or normalize Phase 4 multipage signals from precomputed cache or `(full_text, page_offsets)`."""
    if isinstance(multipage_or_record, dict) and (
        "is_cover_roster_p12" in multipage_or_record or "stapled_ttf_page" in multipage_or_record
    ):
        mp = dict(multipage_or_record)
        if "stapled_ttf_disclosure" not in mp and mp.get("stapled_ttf_disclosure_json"):
            try:
                mp["stapled_ttf_disclosure"] = json.loads(mp["stapled_ttf_disclosure_json"])
            except Exception:
                mp["stapled_ttf_disclosure"] = None
        return mp
    if full_text and page_offsets and len(page_offsets) > 2:
        return extract_multipage_signals_v5(full_text, page_offsets, filename=filename)
    return None


def pre_pass_v5(
    known: str | dict[str, Any] | None,
    filename: str,
    text: str,
    *,
    provenance: dict[str, Any] | None = None,
    multipage: dict[str, Any] | None = None,
    http_status: int | None = None,
    known_valid_empty: bool = False,
    body_state: str | None = None,
    text_source: str | None = None,
    sub_disposition: str | None = None,
    triage_status: str | None = None,
    use_provenance_link_anchor: bool = True,
) -> tuple[str, dict[str, Any]]:
    """Run deterministic V5 pre-pass: triage, 11-family CMS nav strip, `hsru00` host guard,
    OCR-tolerant masthead enrichment, 32-signature Tier-1 match + optional provenance `link_anchor`.

    Preserves 100% of V4's pre-LLM prompt invariants (`<NONE>` `known` distribution and raw HTML body).
    """
    if isinstance(known, dict):
        known_dict = copy.deepcopy(known)
    elif isinstance(known, str) and known.strip():
        try:
            parsed = json.loads(known)
            known_dict = parsed if isinstance(parsed, dict) else {}
        except Exception:
            known_dict = {}
    else:
        known_dict = {}

    triage_res = triage_non_usable_v5(
        text,
        filename=filename,
        http_status=http_status,
        known_valid_empty=known_valid_empty,
        body_state=body_state,
        text_source=text_source,
        sub_disposition=sub_disposition,
        triage_status=triage_status,
    )

    is_html = infer_is_html_v5(filename, text)
    if is_html:
        cleaned_text, cms_family = strip_html_cms_nav_v5(text)
    else:
        cleaned_text, cms_family = text, None
    cms_nav_stripped = cms_family is not None

    orig_has_cmt = bool(known_dict.get("cmt"))
    orig_has_chambers = bool(known_dict.get("chambers"))
    in_dist_known_ctx = (not is_html) and orig_has_chambers and orig_has_cmt
    known_mutated = False

    # 1. `hsru00` Host-vs-Author classification
    hsru_status, hsru_orig_cmts = classify_hsru_host_status(known_dict, filename, cleaned_text)
    raw_cmts = known_dict.get("cmt")
    hsru_stripped = bool(
        hsru_status == "rules_host"
        and isinstance(raw_cmts, list)
        and raw_cmts
        and all(str(c).lower().startswith("hsru") for c in raw_cmts)
    )

    # 2. Hardened Formal Committee Masthead detection on `<NONE>` PDFs
    masthead_cmts = extract_formal_committee_masthead_v5(filename, cleaned_text, is_html=is_html)
    cmt_enriched = bool(
        not is_html
        and not orig_has_cmt
        and hsru_status != "rules_host"
        and masthead_cmts
        and not _is_exhibit_or_external_artifact(filename, cleaned_text)
    )

    # 3. Exact in-distribution `congress` enrichment (`official_slug` -> `known_date` -> `pdf_masthead`)
    #    Preserves `<NONE>` prompt `known` distribution identically to V4 (`valid[5]` invariant).
    slug_c = extract_official_slug_congress(filename)
    masthead_c = extract_pdf_masthead_congress_v5(filename, cleaned_text, is_html=is_html)
    congress_enriched = False
    congress_source: str | None = None

    if known_dict.get("congress") is None:
        if slug_c is not None:
            known_dict["congress"] = slug_c
            congress_enriched = True
            congress_source = "official_slug"
            known_mutated = True
        elif in_dist_known_ctx and not _is_exhibit_or_external_artifact(filename, cleaned_text):
            kd = known_dict.get("date")
            date_c = iso_date_to_congress(kd) if isinstance(kd, str) else None
            if date_c is not None and _has_congressional_proceeding_cue(known_dict, filename, cleaned_text):
                known_dict["congress"] = date_c
                congress_enriched = True
                congress_source = "known_date"
                known_mutated = True
            elif masthead_c is not None:
                known_dict["congress"] = masthead_c
                congress_enriched = True
                congress_source = "pdf_masthead"
                known_mutated = True

    # 4. All-32 Tier-1 structural genre detection (`21` V4 + `11` new V5)
    if triage_res is not None:
        sig_id, target_kind = None, None
    else:
        sig_id, target_kind = detect_exact_tier1_signature_v5(filename, cleaned_text, is_html=is_html)

    # 5. Optional Provenance & Link-Anchor resolution (`0` conflicts across 260,156 `S_raw` docs)
    resolved_prov = _resolve_record_provenance(
        provenance,
        known_dict=known_dict,
        filename=filename,
        text=text,
        tier1_target_kind=target_kind,
    )
    link_anchor_id: str | None = None
    link_anchor_kind: str | None = None
    grammar_lock_source: str | None = "tier1_text" if target_kind is not None else None

    if resolved_prov is not None and triage_res is None:
        link_anchor_id = resolved_prov.get("link_anchor_id")
        link_anchor_kind = resolved_prov.get("link_anchor_target_kind")
        if (
            target_kind is None
            and use_provenance_link_anchor
            and link_anchor_kind in DOC_KINDS_SET
        ):
            target_kind = link_anchor_kind
            grammar_lock_source = "provenance_link_anchor"

    resolved_mp = _resolve_record_multipage(multipage, filename=filename)

    if not known_mutated and isinstance(known, str) and known.strip():
        enriched_known_str = known
    else:
        enriched_known_str = json.dumps(known_dict)

    meta = {
        "known_dict": known_dict,
        "cleaned_text": cleaned_text,
        "is_html": is_html,
        "cms_nav_stripped": cms_nav_stripped,
        "cms_family": cms_family,
        "triage": triage_res,
        "congress_enriched": congress_enriched,
        "congress_source": congress_source,
        "slug_congress": slug_c,
        "masthead_congress": masthead_c,
        "cmt_enriched": cmt_enriched,
        "masthead_committees": masthead_cmts,
        "hsru_host_status": hsru_status,
        "hsru_host_stripped": hsru_stripped,
        "hsru_originating_committees": hsru_orig_cmts,
        "tier1_signature_id": sig_id,
        "link_anchor_id": link_anchor_id,
        "link_anchor_target_kind": link_anchor_kind,
        "grammar_lock_source": grammar_lock_source,
        "tier1_target_kind": target_kind,
        "is_exact_ttf": target_kind == "truth_in_testimony_disclosure",
        "provenance": resolved_prov,
        "multipage": resolved_mp,
    }
    return enriched_known_str, meta


pre_pass_v4 = pre_pass_v5


def _is_empty_val(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and v.strip() in (
        "",
        "N/A",
        "n/a",
        "None",
        "none",
        "null",
        "unknown",
        "Unknown",
    ):
        return True
    if isinstance(v, (list, dict)) and len(v) == 0:
        return True
    return False


def _validate_node(val: Any, sub: dict[str, Any], root: dict[str, Any], path: str = "$") -> None:
    if "$ref" in sub:
        ref = sub["$ref"]
        sub = root["$defs"][ref.split("/")[-1]]
    if val is None:
        raise ValueError(f"{path}: null not allowed")
    tp = sub.get("type")
    if tp == "object":
        if not isinstance(val, dict):
            raise ValueError(f"{path}: expected object")
        for req in sub.get("required", []):
            if req not in val:
                raise ValueError(f"{path}: missing required {req}")
        if "minProperties" in sub and len(val) < sub["minProperties"]:
            raise ValueError(f"{path}: fewer than {sub['minProperties']} properties")
        props = sub.get("properties", {})
        if sub.get("additionalProperties") is False:
            for k in val:
                if k not in props:
                    raise ValueError(f"{path}: unknown key {k}")
        for k, v in val.items():
            if k in props:
                _validate_node(v, props[k], root, f"{path}.{k}")
    elif tp == "array":
        if not isinstance(val, list):
            raise ValueError(f"{path}: expected array")
        if "minItems" in sub and len(val) < sub["minItems"]:
            raise ValueError(f"{path}: len {len(val)} < minItems {sub['minItems']}")
        if "maxItems" in sub and len(val) > sub["maxItems"]:
            raise ValueError(f"{path}: len {len(val)} > maxItems {sub['maxItems']}")
        if "items" in sub:
            for i, item in enumerate(val):
                _validate_node(item, sub["items"], root, f"{path}[{i}]")
    elif tp == "string":
        if not isinstance(val, str):
            raise ValueError(f"{path}: expected string")
        if "minLength" in sub and len(val) < sub["minLength"]:
            raise ValueError(f"{path}: len {len(val)} < minLength {sub['minLength']}")
        if "enum" in sub and val not in sub["enum"]:
            raise ValueError(f"{path}: {val!r} not in enum")
    elif tp == "integer":
        if isinstance(val, bool) or not isinstance(val, int):
            raise ValueError(f"{path}: expected integer")
        if "minimum" in sub and val < sub["minimum"]:
            raise ValueError(f"{path}: {val} < {sub['minimum']}")
        if "maximum" in sub and val > sub["maximum"]:
            raise ValueError(f"{path}: {val} > {sub['maximum']}")
    elif tp == "boolean":
        if not isinstance(val, bool):
            raise ValueError(f"{path}: expected boolean")


def validate_docmeta_v4(obj: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate `obj` against `docmeta_v4_causal.schema.json` and all 3 causal key orders (100% stdlib)."""
    if not isinstance(obj, dict):
        return False, "not_dict"
    try:
        _validate_node(obj, SCHEMA_OBJ, SCHEMA_OBJ)
    except Exception as e:
        return False, str(e).splitlines()[0][:160]

    top_idxs = [TOP_ORDER_IDX[k] for k in obj.keys() if k in TOP_ORDER_IDX]
    if len(top_idxs) != len(obj) or top_idxs != sorted(top_idxs):
        return False, f"top_key_order_violation: {list(obj.keys())}"

    for p in obj.get("personas", []):
        if not isinstance(p, dict):
            return False, "persona_not_dict"
        p_idxs = [PERSONA_ORDER_IDX[k] for k in p.keys() if k in PERSONA_ORDER_IDX]
        if len(p_idxs) != len(p) or p_idxs != sorted(p_idxs):
            return False, f"persona_key_order_violation: {list(p.keys())}"

    if "disclosure" in obj:
        d = obj["disclosure"]
        if not isinstance(d, dict):
            return False, "disclosure_not_dict"
        d_idxs = [DISCLOSURE_ORDER_IDX[k] for k in d.keys() if k in DISCLOSURE_ORDER_IDX]
        if len(d_idxs) != len(d) or d_idxs != sorted(d_idxs):
            return False, f"disclosure_key_order_violation: {list(d.keys())}"

    return True, None


def canonicalize_docmeta_v4(raw_obj: dict[str, Any]) -> dict[str, Any]:
    """Order keys causally at all levels, strip empty/null values, enforce caps, and validate."""
    out: dict[str, Any] = {}
    st = raw_obj.get("status", "usable")
    tq = raw_obj.get("text_quality", "native")
    out["status"] = st if st in STATUS_SET else "usable"
    out["text_quality"] = tq if tq in TEXT_QUALITY_SET else "native"

    if out["status"] in ("error_or_block", "stub_or_blank", "ocr_unreadable"):
        er = raw_obj.get("error_reason")
        if isinstance(er, str) and er.strip():
            out["error_reason"] = er.strip()[:200]
        ok, err = validate_docmeta_v4(out)
        if not ok:
            raise ValueError(f"Invalid error-status DocMetaV4: {err}")
        return out

    max_caps = {
        "short_titles": 8,
        "date_spans": 8,
        "personas": 10,
        "refs": 25,
        "programs": 10,
        "orgs_mentioned": 12,
        "places": 10,
        "fiscal_years": 12,
        "topics": 6,
    }

    for k in TOP_KEYS_ORDER:
        if k in ("status", "text_quality", "error_reason") or k not in raw_obj:
            continue
        val = raw_obj[k]
        if _is_empty_val(val):
            continue

        if k == "personas" and isinstance(val, list):
            clean_p = []
            for item in val:
                if not isinstance(item, dict) or _is_empty_val(item.get("name")):
                    continue
                role = item.get("role", "witness")
                if role == "member":
                    role = "author_or_speaker"
                elif role == "submitter":
                    role = "sender"
                if role not in ROLES_SET:
                    continue
                etype = item.get("entity_type", "non_gov_person")
                if etype not in ETYPES_SET:
                    etype = "non_gov_person"
                p_item: dict[str, Any] = {}
                for pk in PERSONA_KEYS_ORDER:
                    if pk == "role":
                        p_item["role"] = role
                    elif pk == "entity_type":
                        p_item["entity_type"] = etype
                    elif pk in item and not _is_empty_val(item[pk]):
                        pv = item[pk]
                        if pk == "prior_roles" and isinstance(pv, list):
                            pv = [str(x).strip() for x in pv if not _is_empty_val(x)][:8]
                            if not pv:
                                continue
                        elif pk == "education" and isinstance(pv, list):
                            pv = [str(x).strip() for x in pv if not _is_empty_val(x)][:5]
                            if not pv:
                                continue
                        elif pk == "secondary_orgs" and isinstance(pv, list):
                            pv = [str(x).strip() for x in pv if not _is_empty_val(x)]
                            if not pv:
                                continue
                        elif pk == "redacted_personal_pii":
                            if pv is not True:
                                continue
                        elif pk == "panel":
                            if isinstance(pv, bool):
                                continue
                            sv = str(pv).strip()
                            if not sv:
                                continue
                            pv = f"Panel {sv}" if sv.isdigit() else sv
                        elif isinstance(pv, str):
                            pv = pv.strip()
                            if not pv:
                                continue
                        p_item[pk] = pv
                if "name" in p_item and "role" in p_item and "entity_type" in p_item:
                    clean_p.append(p_item)
                if len(clean_p) >= 10:
                    break
            if clean_p:
                out["personas"] = clean_p

        elif k == "disclosure" and isinstance(val, dict):
            d_tmp: dict[str, Any] = {}
            for dk in DISCLOSURE_KEYS_ORDER:
                if dk not in val or val[dk] is None:
                    continue
                dv = val[dk]
                if dk in ("represented_orgs", "fiduciary_orgs", "federal_grants", "foreign_payments"):
                    if isinstance(dv, list):
                        cleaned_list = [
                            str(x).strip()
                            for x in dv
                            if not _is_empty_val(x)
                            and str(x).strip().lower() not in ("no", "no.", "none.", "not applicable")
                        ]
                        if cleaned_list:
                            d_tmp[dk] = cleaned_list
                elif dk == "capacity":
                    if dv in ("self", "organization", "government"):
                        d_tmp[dk] = dv
                elif isinstance(dv, bool):
                    d_tmp[dk] = dv
            if d_tmp.get("federal_grants"):
                d_tmp["has_federal_grants"] = True
            if d_tmp.get("foreign_payments"):
                d_tmp["has_foreign_payments"] = True
            if d_tmp:
                out["disclosure"] = {
                    dk: d_tmp[dk] for dk in DISCLOSURE_KEYS_ORDER if dk in d_tmp
                }

        elif k == "primary_kind":
            out[k] = val if val in DOC_KINDS_SET else "other"

        elif k == "secondary_kinds" and isinstance(val, list):
            sk = []
            seen_sk = set()
            for x in val:
                if x in DOC_KINDS_SET and x != out.get("primary_kind") and x not in seen_sk:
                    sk.append(x)
                    seen_sk.add(x)
            if sk:
                out[k] = sk

        elif k == "fiscal_years" and isinstance(val, list):
            fys = []
            for x in val:
                if not isinstance(x, bool) and isinstance(x, int) and 1900 <= x <= 2100:
                    fys.append(x)
                elif isinstance(x, str) and re.fullmatch(r"\d{4}", x.strip()):
                    yr = int(x.strip())
                    if 1900 <= yr <= 2100:
                        fys.append(yr)
            if fys:
                out[k] = fys[:12]

        elif k == "congress":
            if not isinstance(val, bool) and isinstance(val, int) and 1 <= val <= 130:
                out[k] = val
            elif isinstance(val, str) and val.strip().isdigit() and 1 <= int(val.strip()) <= 130:
                out[k] = int(val.strip())

        elif k == "signatory_count":
            if not isinstance(val, bool) and isinstance(val, int) and val >= 1:
                out[k] = val

        elif isinstance(val, list):
            arr = [str(x).strip() for x in val if not _is_empty_val(x)]
            if k in max_caps:
                arr = arr[: max_caps[k]]
            if arr:
                out[k] = arr

        elif isinstance(val, str):
            s = val.strip()
            if not s:
                continue
            if k in ("chamber", "event_type", "venue_kind", "correspondence_flow"):
                if s in SCHEMA_OBJ["properties"][k]["enum"]:
                    out[k] = s
            else:
                out[k] = s

    ok, err = validate_docmeta_v4(out)
    if not ok:
        raise ValueError(f"Canonicalized DocMetaV4 failed validation: {err}")
    return out


def _text_mentions_explicit_congress(
    text: str,
    cong: int,
    *,
    is_html: bool = False,
) -> bool:
    """Check whether `text` explicitly prints `<cong>th Congress` AFTER stripping all 11 HTML CMS nav families."""
    if not text or not (1 <= cong <= 130):
        return False
    body = strip_html_cms_nav_v5(text)[0] if is_html else text
    rx = re.compile(rf"\b{cong}\s*(?:st|nd|rd|th)\s+Congress\b", re.I)
    if not is_html:
        return bool(rx.search(body))
    for m in rx.finditer(body):
        ctx = _norm_ws_prefix(body[max(0, m.start() - 40) : m.end() + 50], 140)
        if re.search(
            r"\b(?:Toggle|Submenu|Skip to|Search|Menu|Privacy Policy|Browse Archived)\b",
            ctx,
            re.I,
        ):
            continue
        return True
    return False


def _year_grounded_in_context(date_str: str | None, text: str, known_dict: dict[str, Any]) -> bool:
    if not date_str or len(date_str) < 4 or not date_str[:4].isdigit():
        return False
    yr = date_str[:4]
    kd = str(known_dict.get("date") or "")
    return (yr in (text or "")) or (yr in kd)


def _is_gpo_cover_roster_only_p12(text: str) -> bool:
    return is_gpo_cover_roster_only_p12(text)


def _parse_single_ref(ref_str: str) -> dict[str, Any]:
    s = ref_str.strip()
    if ":" not in s:
        return {"raw": s, "prefix": None, "value": s}
    prefix, rest = s.split(":", 1)
    prefix_l = prefix.strip().lower()
    val = rest.strip()
    entry: dict[str, Any] = {"raw": s, "prefix": prefix_l, "value": val}
    if prefix_l == "bill":
        m = re.match(
            r"^(?:(\d{2,3}):)?(hr|s|hres|sres|hjres|sjres|hconres|sconres|h\.?\s*r\.?|s\.?\s*res\.?|h\.?\s*res\.?|h\.?\s*j\.?\s*res\.?|s\.?\s*j\.?\s*res\.?|h\.?\s*con\.?\s*res\.?|s\.?\s*con\.?\s*res\.?)[\s:.-]*(\d+)$",
            val,
            re.I,
        )
        if m:
            if m.group(1):
                entry["congress"] = int(m.group(1))
            entry["bill_type"] = re.sub(r"[^a-z]", "", m.group(2).lower())
            entry["number"] = int(m.group(3))
    elif prefix_l == "law":
        m = re.search(r"(\d{2,3})\s*[-–:]\s*(\d+)", val)
        if m:
            entry["congress"] = int(m.group(1))
            entry["law_number"] = int(m.group(2))
    elif prefix_l in ("rept", "report"):
        m = re.search(r"(\d{2,3})\s*[-–:]\s*(\d+)", val)
        if m:
            entry["congress"] = int(m.group(1))
            entry["report_number"] = int(m.group(2))
    elif prefix_l == "usc":
        m = re.match(
            r"^(\d+[A-Za-z]?)\s*(?:U\.?S\.?C\.?\s*|:\s*)?(?:§+\s*)?([0-9A-Za-z.-]+)",
            val,
            re.I,
        )
        if m:
            entry["title"] = m.group(1)
            entry["section"] = m.group(2)
    return entry


def _nfkc_fold(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip().lower()


def _surname_token(name: str) -> str:
    s = re.sub(
        r"\b(Jr\.?|Sr\.?|II|III|IV|M\.?D\.?|Ph\.?D\.?|Esq\.?|Hon\.?|Rep\.?|Sen\.?|Mr\.?|Ms\.?|Mrs\.?|Dr\.?)\b",
        "",
        name,
        flags=re.I,
    )
    parts = [p for p in re.split(r"[^A-Za-z'\u00C0-\u024F-]+", s) if len(p) > 1]
    return unicodedata.normalize("NFKC", parts[-1]).lower() if parts else _nfkc_fold(name)


def derive_sidecar_v5(
    clean_obj: dict[str, Any],
    filename: str = "",
    text: str = "",
    known: str | dict[str, Any] | None = None,
    *,
    provenance: dict[str, Any] | None = None,
    multipage: dict[str, Any] | None = None,
    triage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute `$0` deterministic derived sidecar (including V5 provenance, multipage & Tier-2 signals)."""
    if isinstance(known, dict):
        known_dict = known
    elif isinstance(known, str) and known.strip():
        try:
            parsed = json.loads(known)
            known_dict = parsed if isinstance(parsed, dict) else {}
        except Exception:
            known_dict = {}
    else:
        known_dict = {}

    pk = clean_obj.get("primary_kind")
    doc_family = DOC_FAMILY_MAP.get(pk, "other") if isinstance(pk, str) else None
    eval_family = EVAL_KIND_FAMILIES.get(pk, pk) if isinstance(pk, str) else None

    is_html = infer_is_html_v5(filename, text)
    cleaned_text, cms_family = strip_html_cms_nav_v5(text) if is_html else (text, None)
    sig_id, sig_kind = detect_exact_tier1_signature_v5(filename, cleaned_text, is_html=is_html)
    tier2_hints = detect_tier2_sidecar_hints_v5(filename, cleaned_text, is_html=is_html)
    masthead_cmts = extract_formal_committee_masthead_v5(filename, cleaned_text, is_html=is_html)
    masthead_c = extract_pdf_masthead_congress_v5(filename, cleaned_text, is_html=is_html)
    hsru_status, hsru_orig = classify_hsru_host_status(known_dict, filename, cleaned_text)

    refs_list = clean_obj.get("refs", [])
    parsed_refs = [_parse_single_ref(r) for r in refs_list if isinstance(r, str)]

    norm_text = _nfkc_fold(text or "")
    vt = clean_obj.get("verbatim_title")
    vt_grounded: bool | None = None
    if isinstance(vt, str) and vt.strip():
        vt_grounded = _nfkc_fold(vt) in norm_text if norm_text else False

    date_spans = [s for s in clean_obj.get("date_spans", []) if isinstance(s, str)]
    ds_ungrounded = (
        [s for s in date_spans if _nfkc_fold(s) not in norm_text] if norm_text else list(date_spans)
    )

    short_titles = [s for s in clean_obj.get("short_titles", []) if isinstance(s, str)]
    st_ungrounded = (
        [s for s in short_titles if _nfkc_fold(s) not in norm_text]
        if norm_text
        else list(short_titles)
    )

    personas = [
        p
        for p in clean_obj.get("personas", [])
        if isinstance(p, dict) and isinstance(p.get("name"), str)
    ]
    p_ungrounded = (
        [
            p["name"]
            for p in personas
            if _surname_token(p["name"]) and _surname_token(p["name"]) not in norm_text
        ]
        if norm_text
        else [p["name"] for p in personas]
    )

    prov_summary: dict[str, Any] | None = None
    if provenance is not None:
        prov_summary = {
            "primary_url_host": provenance.get("primary_url_host"),
            "host_committee_codes": provenance.get("host_committee_codes") or [],
            "host_committee_names": provenance.get("host_committee_names") or [],
            "host_chamber": provenance.get("host_chamber"),
            "authoring_committee_fill_safe": bool(provenance.get("authoring_committee_fill_safe")),
            "authoring_committees": provenance.get("authoring_committees") or [],
            "host_vs_author_reason": provenance.get("host_vs_author_reason"),
            "official_slug": provenance.get("official_slug"),
            "slug_rescued_from_provenance": bool(provenance.get("slug_rescued_from_provenance")),
            "url_slug_congress": provenance.get("url_slug_congress"),
            "url_congress": provenance.get("url_congress"),
            "url_meeting_date": provenance.get("url_meeting_date"),
            "link_anchor_id": provenance.get("link_anchor_id"),
            "link_anchor_target_kind": provenance.get("link_anchor_target_kind"),
            "blocked_date_traps": provenance.get("blocked_date_traps") or [],
        }

    mp_summary: dict[str, Any] | None = None
    if multipage is not None:
        mp_summary = {
            "num_pages": multipage.get("num_pages"),
            "is_cover_roster_p12": bool(multipage.get("is_cover_roster_p12")),
            "cover_roster_kind": multipage.get("cover_roster_kind"),
            "p3_toc_or_gavel_page": multipage.get("p3_toc_or_gavel_page"),
            "p3_toc_or_gavel_slice": multipage.get("p3_toc_or_gavel_slice"),
            "has_gpo_p3_witness_panel": bool(multipage.get("has_gpo_p3_witness_panel")),
            "stapled_ttf_page": multipage.get("stapled_ttf_page"),
            "stapled_ttf_sig_id": multipage.get("stapled_ttf_sig_id"),
            "stapled_ttf_disclosure": multipage.get("stapled_ttf_disclosure"),
            "stapled_vote_page": multipage.get("stapled_vote_page"),
            "stapled_vote_sig_id": multipage.get("stapled_vote_sig_id"),
            "stapled_qfr_page": multipage.get("stapled_qfr_page"),
        }

    return {
        "doc_family": doc_family,
        "eval_kind_family": eval_family,
        "tier1_signature_id": sig_id,
        "tier1_target_kind": sig_kind,
        "tier2_hints": tier2_hints,
        "triage": triage,
        "masthead_committees": masthead_cmts,
        "masthead_congress": masthead_c,
        "hsru_host_status": hsru_status,
        "hsru_originating_committees": hsru_orig,
        "cms_nav_stripped": cms_family,
        "provenance": prov_summary,
        "multipage_signals": mp_summary,
        "parsed_refs": parsed_refs,
        "span_grounding": {
            "verbatim_title_grounded": vt_grounded,
            "date_spans": {
                "grounded": len(date_spans) - len(ds_ungrounded),
                "total": len(date_spans),
                "all_grounded": len(ds_ungrounded) == 0,
                "ungrounded": ds_ungrounded,
            },
            "short_titles": {
                "grounded": len(short_titles) - len(st_ungrounded),
                "total": len(short_titles),
                "all_grounded": len(st_ungrounded) == 0,
                "ungrounded": st_ungrounded,
            },
            "personas_surnames": {
                "grounded": len(personas) - len(p_ungrounded),
                "total": len(personas),
                "all_grounded": len(p_ungrounded) == 0,
                "ungrounded": p_ungrounded,
            },
        },
        "calendar_audit": {
            "slug_congress": extract_official_slug_congress(filename),
            "url_slug_congress": prov_summary["url_slug_congress"] if prov_summary else None,
            "masthead_congress": masthead_c,
            "event_date_congress": iso_date_to_congress(clean_obj.get("event_date")),
            "doc_date_congress": iso_date_to_congress(clean_obj.get("doc_date")),
            "ttf_template_detected": sig_kind == "truth_in_testimony_disclosure",
            "tier1_signature_id": sig_id,
        },
    }


derive_sidecar_v4 = derive_sidecar_v5

_RX_BULLETED_WITNESS_BLOCK = re.compile(
    r"\b(?:following\s+)?witnesses(?:\s*\([^)]{1,40}\))?\s*:\s*"
    r"(?:Panel\s+(?:I+|1|One)\s*[:.-]?\s*)?"
    r"((?:[•\uf0b7▪◦]\s*[^\n•\uf0b7▪◦]{5,360}\s*){1,12})",
    re.I,
)
_RX_WITNESS_SECTION_TAIL = re.compile(
    r"(?:;\s*and\b|\.\s+[A-Z]|\s+(?:Background|Purpose|Overview|Summary|Legislation|Issues|Charter|"
    r"Page\s+\d+\s+of\s+\d+|Panel\s+(?:II|III|2|3|Two|Three)\b|"
    r"\*+\s*NOTE|\*+\s*Witness|Witness\s+List\s+is\s+Subject|"
    r"By\s+Direction\s+of\s+the\s+Chair(?:man|woman)?|"
    r"The\s+(?:Subcommittee|Committee|hearing|purpose)\b|"
    r"Please\s+note|For\s+further\s+information|Staff\s+Contact)\b).*$",
    re.I | re.S,
)
_RX_WITNESS_HONORIFIC = re.compile(
    r"^(?:The\s+Honorable|The\s+Hon\.|Hon\.|Dr\.|Mr\.|Ms\.|Mrs\.|Miss|Prof\.|Professor|Ambassador|"
    r"Secretary|Deputy\s+Secretary|Assistant\s+Secretary|Under\s+Secretary|"
    r"General|Gen\.|Lt\.\s+Gen\.|Maj\.\s+Gen\.|Brig\.\s+Gen\.|Admiral|Adm\.|Vice\s+Admiral|Rear\s+Admiral|"
    r"Chief|Commissioner|Director|Governor|Mayor|Judge|Reverend|Rev\.)\s+",
    re.I,
)
_RX_WITNESS_DEGREE_SUFFIX = re.compile(
    r"^(?:Jr\.?|Sr\.?|II|III|IV|V|M\.?D\.?|Ph\.?D\.?|M\.?P\.?H\.?|J\.?D\.?|Esq\.?|CPA|RN|"
    r"USA|USN|USAF|USMC|USCG|Ret\.?|Retired)(?:\s*\([^)]*\))?$",
    re.I,
)
_WITNESS_NON_PERSON_WORDS = frozenset(
    {
        "committee",
        "subcommittee",
        "department",
        "agency",
        "university",
        "institute",
        "institution",
        "council",
        "panel",
        "witness",
        "witnesses",
        "hearing",
        "markup",
        "office",
        "bureau",
        "commission",
        "association",
        "federation",
        "coalition",
        "alliance",
        "foundation",
        "center",
        "centre",
        "corporation",
        "company",
        "inc",
        "llc",
        "room",
        "building",
        "house",
        "senate",
        "congress",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "january",
        "february",
        "march",
        "april",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "additional",
        "tbd",
        "tba",
        "none",
    }
)


def _extract_bulleted_witness_personas(text: str | None) -> list[dict[str, Any]]:
    """Deterministically parse explicit `witnesses: • Name, Title, Org` blocks (0 FPs across 260K S_raw)."""
    if not text or "witness" not in text.lower():
        return []
    m = _RX_BULLETED_WITNESS_BLOCK.search(text)
    if not m:
        return []
    norm_full = _nfkc_fold(text)
    items = [x.strip() for x in re.split(r"[•\uf0b7▪◦]\s*", m.group(1)) if x.strip()]
    out: list[dict[str, Any]] = []
    for it in items:
        it_clean = _RX_WITNESS_SECTION_TAIL.sub("", it).strip()
        it_clean = re.sub(r"\s+", " ", it_clean).strip(" .;,-")
        if not it_clean or len(it_clean) < 5:
            continue
        if re.match(
            r"^(?:TBD|TBA|To\s+be\s+announced|None|N/A|Panel\s+[I1V23]|Additional\s+witness)",
            it_clean,
            re.I,
        ):
            continue
        parts = [p.strip() for p in it_clean.split(",") if p.strip()]
        if len(parts) < 2:
            continue
        orig_first = parts[0]
        raw_name = orig_first
        for _ in range(2):
            raw_name = _RX_WITNESS_HONORIFIC.sub("", raw_name).strip()
        rest_idx = 1
        while rest_idx < len(parts) and _RX_WITNESS_DEGREE_SUFFIX.match(parts[rest_idx]):
            suf = parts[rest_idx].strip()
            if re.match(r"^(?:Jr\.?|Sr\.?|II|III|IV|V)$", suf, re.I):
                raw_name = f"{raw_name} {suf}"
            rest_idx += 1
        if rest_idx >= len(parts):
            continue
        ntoks = raw_name.split()
        if len(ntoks) < 2 or len(ntoks) > 5:
            continue
        if any(any(ch.isdigit() for ch in t) for t in ntoks):
            continue
        if not all(
            t[0].isupper()
            for t in ntoks
            if t[0].isalpha() and t.lower() not in {"de", "del", "la", "van", "von", "da", "di", "al", "bin"}
        ):
            continue
        if any(re.sub(r"[^a-z]", "", w.lower()) in _WITNESS_NON_PERSON_WORDS for w in ntoks):
            continue
        sur = _surname_token(raw_name)
        if not sur or sur not in norm_full:
            continue
        rem = parts[rest_idx:]
        rem_join = ", ".join(rem)
        is_mil = bool(
            re.search(
                r"\b(?:General|Gen\.|Lt\.\s+Gen\.|Maj\.\s+Gen\.|Brig\.\s+Gen\.|Admiral|Adm\.|Vice\s+Admiral|Rear\s+Admiral)\b",
                orig_first,
                re.I,
            )
        )
        is_gov = (not is_mil) and bool(
            re.search(
                r"\b(?:The\s+Honorable|The\s+Hon\.|Hon\.|Ambassador|Secretary|Administrator|Commissioner|Inspector\s+General)\b",
                orig_first + " " + rem_join,
                re.I,
            )
            or re.search(
                r"\b(?:U\.?S\.?\s+Department|Department\s+of\s+(?:State|Defense|Treasury|Justice|Interior|Agriculture|"
                r"Commerce|Labor|Health|Housing|Transportation|Energy|Education|Veterans|Homeland)|"
                r"Agency\s+for\s+International|Environmental\s+Protection\s+Agency|"
                r"Federal\s+(?:Trade|Communications|Reserve|Deposit|Aviation|Energy|Bureau|Emergency|Maritime)|"
                r"Securities\s+and\s+Exchange|Government\s+Accountability\s+Office|Congressional\s+Research\s+Service|"
                r"Congressional\s+Budget\s+Office|Executive\s+Office\s+of\s+the\s+President|"
                r"National\s+(?:Science|Security|Aeronautics|Oceanic|Institutes|Coordination\s+Office))\b",
                rem_join,
                re.I,
            )
        )
        etype = "military_officer" if is_mil else ("gov_official" if is_gov else "non_gov_person")
        p_entry: dict[str, Any] = {
            "name": raw_name[:120],
            "role": "witness",
            "entity_type": etype,
        }
        if len(rem) >= 2:
            t_str = ", ".join(rem[:-1]).strip()[:160]
            o_str = rem[-1].strip()[:160]
            if t_str:
                p_entry["title"] = t_str
            if o_str:
                p_entry["org"] = o_str
        elif len(rem) == 1 and rem[0].strip():
            p_entry["title"] = rem[0].strip()[:160]
        out.append(p_entry)
    return out


def post_pass_v5(
    raw_obj: dict[str, Any],
    known: str | dict[str, Any] | None = None,
    filename: str = "",
    text: str = "",
    *,
    provenance: dict[str, Any] | None = None,
    multipage: dict[str, Any] | None = None,
    triage: dict[str, Any] | None = None,
    is_html_override: bool | None = None,
    skip_sidecar: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply 100%-precision deterministic V5 post-pass rules and return `(clean_docmeta_v4, sidecar)`."""
    if isinstance(known, dict):
        known_dict = known
    elif isinstance(known, str) and known.strip():
        try:
            parsed = json.loads(known)
            known_dict = parsed if isinstance(parsed, dict) else {}
        except Exception:
            known_dict = {}
    else:
        known_dict = {}

    # Enforce certified non-usable triage if raw container had 0 alnum chars or explicit HTTP 4xx/5xx error
    if triage is not None and isinstance(triage.get("docmeta"), dict):
        t_doc = canonicalize_docmeta_v4(triage["docmeta"])
        return t_doc, derive_sidecar_v5(
            t_doc,
            filename=filename,
            text=text,
            known=known_dict,
            provenance=provenance,
            multipage=multipage,
            triage=triage,
        )

    obj = canonicalize_docmeta_v4(raw_obj)

    if obj["status"] in ("error_or_block", "stub_or_blank", "ocr_unreadable"):
        return obj, derive_sidecar_v5(
            obj,
            filename=filename,
            text=text,
            known=known_dict,
            provenance=provenance,
            multipage=multipage,
            triage=triage,
        )

    pk = obj.get("primary_kind")
    is_html = bool(is_html_override) if is_html_override is not None else infer_is_html_v5(filename, text)
    cleaned_text, _ = strip_html_cms_nav_v5(text) if is_html else (text, None)
    resolved_prov = _resolve_record_provenance(
        provenance,
        known_dict=known_dict,
        filename=filename,
        text=text,
        tier1_target_kind=pk if isinstance(pk, str) else None,
    )
    resolved_mp = _resolve_record_multipage(multipage, filename=filename)

    # (a0) House Rule XI Truth-in-Testimony forms: 100% House chamber + unambiguous missing disclosure booleans
    if pk == "truth_in_testimony_disclosure":
        if "chamber" not in obj:
            obj["chamber"] = "house"
        det_disc = extract_ttf_disclosure_booleans(text)
        if det_disc:
            cur_disc = dict(obj.get("disclosure") or {})
            for dk, dv in det_disc.items():
                if dk not in cur_disc:
                    cur_disc[dk] = dv
            obj["disclosure"] = cur_disc

    # (a1) Formal Committee Masthead Recovery, `hsru00` Host-vs-Author Guard & Provenance Committee/Chamber Fill
    hsru_status, hsru_orig_cmts = classify_hsru_host_status(known_dict, filename, cleaned_text)
    prov_floor_block = bool(
        resolved_prov is not None
        and resolved_prov.get("is_floor_repo_host")
        and not resolved_prov.get("hsru_is_author")
    )
    if hsru_status == "rules_host" or prov_floor_block:
        cur_cmts = obj.get("committees")
        if isinstance(cur_cmts, list) and cur_cmts:
            non_rules = [c for c in cur_cmts if _norm_cmt_compare(c) != "rules"]
            if len(non_rules) < len(cur_cmts):
                if non_rules:
                    obj["committees"] = non_rules
                elif hsru_orig_cmts:
                    obj["committees"] = [c["name"] for c in hsru_orig_cmts]
        elif "committees" not in obj and hsru_orig_cmts and pk in FORMAL_COMMITTEE_KINDS:
            obj["committees"] = [c["name"] for c in hsru_orig_cmts]

    masthead_cmts = extract_formal_committee_masthead_v5(filename, cleaned_text, is_html=is_html)
    if (
        masthead_cmts
        and pk in FORMAL_COMMITTEE_KINDS
        and hsru_status != "rules_host"
        and not prov_floor_block
        and not _is_exhibit_or_external_artifact(filename, cleaned_text)
    ):
        if "committees" not in obj:
            obj["committees"] = [m["name"] for m in masthead_cmts]
        if "chamber" not in obj:
            chs = list(dict.fromkeys(m["chamber"] for m in masthead_cmts))
            obj["chamber"] = "joint" if len(chs) > 1 else chs[0]

    # (a2) Exact `congress` fill & nav-stripped multi-signal reconciliation (+ URL slug Congress rescue)
    slug_c = extract_official_slug_congress(filename)
    prov_slug_c = (
        can_fill_docmeta_congress_v5(
            resolved_prov,
            pk if isinstance(pk, str) else None,
            filename=filename,
            text=cleaned_text,
        )
        if resolved_prov is not None
        else None
    )
    eff_slug_c = slug_c if slug_c is not None else prov_slug_c

    masthead_c = extract_pdf_masthead_congress_v5(filename, cleaned_text, is_html=is_html)
    kc_raw = known_dict.get("congress")
    known_c = (
        kc_raw
        if (not isinstance(kc_raw, bool) and isinstance(kc_raw, int) and 1 <= kc_raw <= 130)
        else None
    )
    if eff_slug_c is not None and known_c is not None and known_c < 100:
        known_c = eff_slug_c

    # (a2b) Optional Provenance Meeting Date Rescue (ONLY when both doc_date & event_date are absent)
    if resolved_prov is not None and "doc_date" not in obj and "event_date" not in obj:
        rescued_ed = can_fill_docmeta_event_date_v5(
            resolved_prov,
            pk if isinstance(pk, str) else None,
            existing_doc_date=obj.get("doc_date"),
            existing_event_date=obj.get("event_date"),
            text=cleaned_text,
        )
        if rescued_ed is not None:
            obj["event_date"] = rescued_ed

    evt_date = obj.get("event_date")
    doc_date = obj.get("doc_date")
    evt_c = iso_date_to_congress(evt_date)
    doc_c = iso_date_to_congress(doc_date)
    kd_str = known_dict.get("date")
    known_date_c = iso_date_to_congress(kd_str) if isinstance(kd_str, str) else None

    if "congress" not in obj:
        if eff_slug_c is not None:
            obj["congress"] = eff_slug_c
        elif known_c is not None:
            obj["congress"] = known_c
        elif evt_c is not None:
            obj["congress"] = evt_c
        elif doc_c is not None and pk in CONTEMPORARY_CONGRESSIONAL_KINDS:
            obj["congress"] = doc_c
        elif (
            known_date_c is not None
            and pk in CONTEMPORARY_CONGRESSIONAL_KINDS
            and not _is_exhibit_or_external_artifact(filename, cleaned_text)
        ):
            obj["congress"] = known_date_c
        elif (
            masthead_c is not None
            and pk in CONTEMPORARY_CONGRESSIONAL_KINDS
            and not _is_exhibit_or_external_artifact(filename, cleaned_text)
        ):
            obj["congress"] = masthead_c
    else:
        llm_c = obj["congress"]
        if eff_slug_c is not None and eff_slug_c in (known_c, evt_c, doc_c) and llm_c != eff_slug_c:
            obj["congress"] = eff_slug_c
        elif known_c is not None and known_c >= 100 and known_c in (evt_c, doc_c) and llm_c != known_c:
            obj["congress"] = known_c
        elif eff_slug_c is None and known_c is None and pk in CONTEMPORARY_CONGRESSIONAL_KINDS:
            target_c = evt_c if evt_c is not None else doc_c
            target_d = evt_date if evt_c is not None else doc_date
            if (
                target_c is not None
                and llm_c != target_c
                and _year_grounded_in_context(target_d, cleaned_text, known_dict)
                and not _text_mentions_explicit_congress(text, llm_c, is_html=is_html)
            ):
                obj["congress"] = target_c

    # (a3) Post-Congress Provenance Committee & Chamber Fill (era-aware using resolved `obj["congress"]`)
    if resolved_prov is not None:
        eff_hsru_for_prov = "rules_host" if (hsru_status == "rules_host" or prov_floor_block) else hsru_status
        if "committees" not in obj:
            prov_cmts = can_fill_docmeta_committees_v5(
                resolved_prov,
                pk if isinstance(pk, str) else None,
                filename=filename,
                text=cleaned_text,
                hsru_status=eff_hsru_for_prov,
                target_congress=obj.get("congress"),
            )
            if prov_cmts:
                obj["committees"] = prov_cmts
        if "chamber" not in obj:
            prov_ch = can_fill_docmeta_chamber_v5(
                resolved_prov,
                pk if isinstance(pk, str) else None,
                filename=filename,
                text=cleaned_text,
                hsru_status=eff_hsru_for_prov,
            )
            if prov_ch is not None:
                obj["chamber"] = prov_ch

    # (b) Correspondence Addressee Role Canonicalization (100%-precision verified subset)
    if (
        pk == "oversight_letter"
        and obj.get("correspondence_flow") in ("agency_to_congress", "foreign_gov_to_congress")
        and "personas" in obj
    ):
        head_sal = (cleaned_text or "")[:1200]
        has_cong_salutation = bool(
            re.search(
                r"\bDear\s+(?:Mr\.?\s+|Madam\s+|The\s+Honorable\s+)?"
                r"(?:Chair(?:man|woman|person)?|Ranking\s+Member|Senator|Representative|Congress(?:man|woman))\b",
                head_sal,
                re.I,
            )
        )
        has_exec_salutation = bool(
            re.search(
                r"\bDear\s+(?:Mr\.?\s+|Madam\s+)?(?:Secretary|Director|Administrator|Attorney\s+General|Commissioner|Inspector\s+General|Ambassador)\b",
                head_sal,
                re.I,
            )
        )
        if has_cong_salutation and not has_exec_salutation:
            for p in obj["personas"]:
                if (
                    p.get("entity_type") == "member"
                    and p.get("role") in ("chair", "ranking_member")
                ):
                    p["role"] = "recipient"

    # (c) Per-Kind `personas[]` Structural Guards
    if "personas" in obj and isinstance(obj["personas"], list):
        pers = obj["personas"]

        if pk == "committee_vote":
            filtered = [p for p in pers if p.get("role") in VOTE_ALLOWED_ROLES]
            if len(filtered) > 4:
                dedup_vote: list[dict[str, Any]] = []
                has_chair = False
                has_rm = False
                n_subj = 0
                for p in filtered:
                    r_p = p.get("role")
                    if r_p in ("chair", "presiding") and not has_chair:
                        dedup_vote.append(p)
                        has_chair = True
                    elif r_p == "ranking_member" and not has_rm:
                        dedup_vote.append(p)
                        has_rm = True
                    elif r_p in ("amendment_offeror", "sponsor", "nominee") and n_subj < 2:
                        dedup_vote.append(p)
                        n_subj += 1
                filtered = dedup_vote
            if filtered:
                obj["personas"] = filtered
            else:
                obj.pop("personas", None)

        elif pk == "witness_biography":
            subjects = [p for p in pers if p.get("role") in ("witness", "nominee")]
            if subjects:
                obj["personas"] = subjects

        elif pk == "hearing_transcript":
            if _is_gpo_cover_roster_only_p12(cleaned_text):
                ct_str = cleaned_text or ""
                has_explicit_rm = bool(re.search(r",\s*[A-Za-z .]{2,25},\s*Ranking\b", ct_str, re.I))
                max_rm = 2 if "subcommittee" in ct_str[300:].lower() else 1
                rm_kept = 0
                filtered = []
                for p in pers:
                    r_p = p.get("role")
                    if r_p not in GPO_COVER_ROSTER_ALLOWED_ROLES:
                        continue
                    if r_p == "ranking_member":
                        if has_explicit_rm:
                            sur = _surname_token(str(p.get("name") or ""))
                            if sur and not any(
                                re.search(
                                    r"^\s*(?:,\s*(?:Jr\.?|Sr\.?|II|III|IV)\s*)?,\s*[A-Za-z .]{2,25},\s*Ranking\b",
                                    ct_str[m.end() : m.end() + 65],
                                    re.I,
                                )
                                for m in re.finditer(re.escape(sur), ct_str, re.I)
                            ):
                                continue
                        if rm_kept >= max_rm:
                            continue
                        rm_kept += 1
                    filtered.append(p)
                if filtered:
                    obj["personas"] = filtered
                else:
                    obj.pop("personas", None)

        elif pk in ("attendance_quorum_sheet", "member_roster"):
            filtered = [p for p in pers if p.get("role") in QUORUM_ROSTER_ALLOWED_ROLES]
            if filtered:
                obj["personas"] = filtered
            else:
                obj.pop("personas", None)

    # Rescue explicit bulleted witness panels when BF16 logit tie closes `personas[]` after masthead Chair/RM
    if pk in ("hearing_memo_or_charter", "hearing_notice", "witness_list", "event_web_page"):
        cur_pers = [p for p in (obj.get("personas") or []) if isinstance(p, dict)]
        has_any_witness = any(p.get("role") == "witness" for p in cur_pers)
        if not has_any_witness:
            rescued_w = _extract_bulleted_witness_personas(cleaned_text)
            if rescued_w:
                seen_surnames = {_surname_token(str(p.get("name") or "")) for p in cur_pers}
                for wp in rescued_w:
                    if len(cur_pers) >= 16:
                        break
                    wsur = _surname_token(wp["name"])
                    if wsur and wsur not in seen_surnames:
                        seen_surnames.add(wsur)
                        cur_pers.append(wp)
                if cur_pers:
                    obj["personas"] = cur_pers

    clean_obj = canonicalize_docmeta_v4(obj)
    if skip_sidecar:
        hsru_st = (
            resolved_prov.get("hsru_host_status")
            if isinstance(resolved_prov, dict) and resolved_prov.get("hsru_host_status")
            else classify_hsru_host_status(known_dict, filename, text)[0]
        )
        return clean_obj, {
            "hsru_host_status": hsru_st,
            "_resolved_prov": resolved_prov,
            "_resolved_mp": resolved_mp,
        }
    sidecar = derive_sidecar_v5(
        clean_obj,
        filename=filename,
        text=text,
        known=known_dict,
        provenance=resolved_prov,
        multipage=resolved_mp,
        triage=triage,
    )
    return clean_obj, sidecar


post_pass_v4 = post_pass_v5


# ---------------------------------------------------------------------------
# 4. End-to-End Engine Wrapper (`PythonicEngineV5` + `SyncKindMatcher`)
# ---------------------------------------------------------------------------


def _salvage_truncated_docmeta_v4(raw_txt: str, filename: str = "") -> dict[str, Any]:
    """Deterministically close a `max_tokens`-truncated JSON prefix into a valid `DocMetaV4Causal` dict."""
    s = raw_txt.strip()
    for cut in range(len(s), 1, -1):
        if cut < len(s) and s[cut] not in (",", "{", "["):
            continue
        cand = s[:cut].rstrip(",")
        in_str = False
        esc = False
        stack: list[str] = []
        valid_scan = True
        for ch in cand:
            if esc:
                esc = False
                continue
            if ch == "\\":
                if in_str:
                    esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if not in_str:
                if ch == "{":
                    stack.append("}")
                elif ch == "[":
                    stack.append("]")
                elif ch in ("}", "]"):
                    if not stack or stack[-1] != ch:
                        valid_scan = False
                        break
                    stack.pop()
        if in_str or not valid_scan or not stack:
            continue
        closed = cand + "".join(reversed(stack))
        try:
            obj = json.loads(closed)
            if isinstance(obj, dict):
                obj.setdefault("status", "usable")
                obj.setdefault("text_quality", "native")
                if obj["status"] not in ("error_or_block", "stub_or_blank", "ocr_unreadable"):
                    obj.setdefault("primary_kind", "other")
                    obj.setdefault("composed_title", (filename or "Congressional Document")[:100])
                    obj.setdefault("gist", "Congressional committee document.")
                    obj.setdefault("topics", ["congressional operations"])
                return obj
        except Exception:
            continue
    return {
        "status": "usable",
        "text_quality": "native",
        "primary_kind": "other",
        "composed_title": (filename or "Congressional Document")[:100],
        "gist": "Congressional committee document.",
        "topics": ["congressional operations"],
    }


__all__ = [
    "CANONICAL_COMMITTEES_V5",
    "CMS_STRIPPER_FAMILIES_V5",
    "CONTEMPORARY_CONGRESSIONAL_KINDS",
    "DOC_FAMILY_MAP",
    "DOMAIN_TO_COMMITTEE_CODE",
    "EVAL_KIND_FAMILIES",
    "FORMAL_COMMITTEE_KINDS",
    "HOUSE_CLERK_2LETTER_TO_CODE",
    "NEW_TIER1_SIGNATURE_TO_KIND_V5",
    "PROVENANCE_SAFE_COMMITTEE_KINDS",
    "SCHEMA_V4_STR",
    "TIER1_SIGNATURE_IDS",
    "TIER1_SIGNATURE_IDS_V5",
    "TIER1_SIGNATURE_TO_KIND",
    "TIER1_SIGNATURE_TO_KIND_V5",
    "TIER1_TARGET_KINDS",
    "TIER1_TARGET_KINDS_V5",
    "TTF_SCHEMA_V4_OBJ",
    "TTF_SCHEMA_V4_STR",
    "V4_TIER1_SIGNATURE_TO_KIND",
    "build_doc_kind_schema_v4",
    "build_doc_kind_schema_v5",
    "build_ttf_schema_v4",
    "build_ttf_schema_v5",
    "can_fill_docmeta_chamber_v5",
    "can_fill_docmeta_committees_v5",
    "can_fill_docmeta_congress_v5",
    "can_fill_docmeta_event_date_v5",
    "canonicalize_docmeta_v4",
    "classify_hsru_host_status",
    "committee_code_to_canonical",
    "derive_sidecar_v4",
    "derive_sidecar_v5",
    "detect_all_tier1_signatures",
    "detect_all_tier1_signatures_v5",
    "detect_exact_tier1_signature",
    "detect_exact_tier1_signature_v5",
    "detect_exact_ttf_form",
    "detect_new_tier1_signatures_v5",
    "detect_provenance_link_anchor",
    "detect_stapled_backpage_packets",
    "detect_tier2_sidecar_hints_v5",
    "detect_ttf_page_signature",
    "detect_v4_tier1_signatures",
    "detect_vote_page_signature",
    "extract_formal_committee_masthead",
    "extract_formal_committee_masthead_v5",
    "extract_gpo_p3_p8_rescue",
    "extract_multipage_signals_v5",
    "extract_official_slug_congress",
    "extract_pdf_masthead_congress",
    "extract_pdf_masthead_congress_v5",
    "extract_ttf_disclosure_booleans",
    "extract_url_dates_and_congress",
    "extract_url_official_slug_info",
    "infer_is_html",
    "infer_is_html_v5",
    "is_gpo_cover_roster_only_p12",
    "is_qfr_appendix_page",
    "is_steno_cover_roster_only_p12",
    "iso_date_to_congress",
    "match_qfr_appendix_page",
    "norm_committee_compare",
    "normalize_parent_committee_code",
    "post_pass_v4",
    "post_pass_v5",
    "pre_pass_v4",
    "pre_pass_v5",
    "resolve_provenance_v5",
    "split_pdf_pages",
    "strip_html_cms_nav",
    "strip_html_cms_nav_v5",
    "triage_non_usable_v5",
    "triage_unwrapped_http_or_empty",
    "unwrap_archive_url",
    "validate_docmeta_v4",
]
