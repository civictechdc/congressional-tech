#!/usr/bin/env python3
"""Pure-Python Post-Extraction Cross-Check & Teacher Escalation Router (`anomaly_router_v6.py`).

100% Python stdlib at import and runtime (`/usr/bin/python3 -B -I -S` verified).
Cross-checks extracted `DocMetaV4Causal` records against Constitutional calendar rules,
genre actor invariants, relational graph truth (`meetings`, `witnesses`, `members`, `rosters`),
and statutory U.S.C. section existence (`UscSectionOracle` precomputed flags or optional live oracle)
to route anomalous 2B LLM outputs to teacher review or deterministic repair:

  (a) `zero_personas_on_actor_kind`:
      `0` personas on `witness_statement`, `member_opening_statement`, `oversight_letter`,
      or `nomination_or_support_letter`.
  (b) `persona_roster_leak`:
      `len(personas) > 10` (or raw pre-cap `> 10`), `committee_vote` / `attendance_quorum_sheet` /
      `member_roster` `> 4` personas, or `>= 3` verified standing backbench roster members leaked.
  (c) `fallback_primary_kind_other`:
      `primary_kind == "other"` (or missing/invalid `primary_kind` on a `usable` document).
  (d) `relational_*_contradiction`:
      Contradiction against relational `witness_keys` (core single-witness kinds, excluding `-SD00x`
      supplemental exhibits), `meeting_keys` (`congress`, host-safe `chamber`, author-safe `committees`),
      `bioguide_ids` (text-grounded Member author/offeror surname or `party_state` mismatch),
      or deterministic grammar-locked `primary_kind`.
  (e) `invalid_usc_section_non_draft`:
      Non-existent or pre-1994 repealed-no-successor `usc:` section (`UscSectionOracle` or reserved/
      impossible U.S.C. title) on non-legislative-drafting genres (never penalizing proposed new
      sections like `41 U.S.C. 8302A` or `38 U.S.C. 1730D` on bills/amendments/prints/reports).
  (f) `date_congress_calendar_mismatch`:
      Constitutional Congress calendar mismatch between `congress` and `event_date`, contemporary
      `doc_date`, or official GPO/Clerk filename slug Congress.
"""

from __future__ import annotations

import datetime
import math
import os
from pathlib import Path
import re
import sys
import unicodedata
from typing import Any, Mapping, Sequence

ACTOR_REQUIRED_KINDS_V6 = frozenset(
    {
        "witness_statement",
        "member_opening_statement",
        "oversight_letter",
        "nomination_or_support_letter",
    }
)

LEGISLATIVE_DRAFT_KINDS_V6 = frozenset(
    {
        "bill_or_draft",
        "committee_amendment",
        "comparative_print",
        "section_by_section",
        "committee_report",
        "explanatory_statement",
        "committee_resolution",
    }
)

CORE_WITNESS_AUTHOR_KINDS_V6 = frozenset(
    {
        "witness_statement",
        "truth_in_testimony_disclosure",
        "witness_biography",
    }
)

BIOGUIDE_AUTHOR_KINDS_V6 = frozenset(
    {
        "member_opening_statement",
        "member_or_floor_statement",
        "committee_amendment",
    }
)

CONTEMPORARY_CONGRESSIONAL_KINDS_V6 = frozenset(
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

FORMAL_COMMITTEE_KINDS_V6 = frozenset(
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

HOST_CHAMBER_EXEMPT_KINDS_V6 = frozenset(
    {
        "external_report_or_whitepaper",
        "agency_or_gao_crs_report",
        "member_or_floor_statement",
        "witness_statement",
        "external_submission_letter",
        "public_comment_or_submission",
        "investigative_exhibit",
        "legal_or_investigative_filing",
        "news_clip_or_article",
        "press_release_or_fact_sheet",
    }
)

BACKBENCH_LEAK_TARGET_KINDS_V6 = frozenset(
    {
        "hearing_transcript",
        "hearing_notice",
        "markup_notice",
        "hearing_memo_or_charter",
        "committee_vote",
        "attendance_quorum_sheet",
        "member_roster",
    }
)

NON_USABLE_STATUSES_V6 = frozenset(
    {"error_or_block", "stub_or_blank", "ocr_unreadable"}
)

_SD_SUPPLEMENTAL_RE = re.compile(r"(?:^|[-_])SD\d{2,4}(?:[-_.]|$)", re.I)
_EXHIBIT_FILENAME_RE = re.compile(
    r"(?:^|[^a-zA-Z])exhibit(?:[^a-zA-Z]|$)|redacted|sanitized|\b302\b",
    re.I,
)
_OFFICIAL_SLUG_CONGRESS_RE = re.compile(
    r"(?:^|/)(?:HHRG|HMTG|HMKP|CHRG|BILLS|CRPT|CREC|CDOC|CPRT)-(\d{2,3})(?=[A-Za-z-]|$)",
    re.I,
)
_USC_REF_RE = re.compile(
    r"^usc:\s*(\d+)\s*(?:U\.?S\.?C\.?|USC)?(\s+App\.?)?\s*(?:§+\s*|sec(?:tion)?\.?\s*)?(\d+[A-Za-z0-9-]*)",
    re.I,
)
_CMT_STOPWORDS_RE = re.compile(
    r"\b(?:u\.?s\.?|united states|house|senate|committee|subcommittee|full|standing|on|the|of|and|select|permanent|special|joint)\b",
    re.I,
)
_HONORIFIC_SUFFIX_RE = re.compile(
    r"\b(?:Jr\.?|Sr\.?|II|III|IV|V|M\.?D\.?|Ph\.?D\.?|Esq\.?|Hon\.?|Rep\.?|Sen\.?|Mr\.?|Ms\.?|Mrs\.?|Dr\.?)\b",
    re.I,
)

# ---------------------------------------------------------------------------
# Pure-Stdlib `C0_Stdlib` `gist` / `composed_title` Grounding Gate (`0` ML/Jev Weights)
# ---------------------------------------------------------------------------

_GROUNDING_STOPWORDS_V6 = frozenset(
    {
        "the", "of", "and", "to", "in", "for", "on", "a", "an", "by", "with", "from", "at", "as",
        "is", "are", "was", "were", "be", "been", "being", "that", "this", "these", "those", "or",
        "it", "its", "their", "his", "her", "our", "into", "over", "under", "about", "between",
        "through", "during", "before", "after", "above", "below", "out", "off", "all", "any",
        "both", "each", "more", "most", "other", "some", "such", "than", "too", "very", "can",
        "will", "may", "would", "should", "could", "also", "not", "new", "use", "used", "using",
        # Domain framing words common in abstractive titles/gists even when abbreviated in body
        "committee", "subcommittee", "house", "senate", "congress", "congressional", "united",
        "states", "federal", "national", "government", "hearing", "markup", "document", "statement",
        "testimony", "witness", "member", "senator", "representative", "chair", "chairman",
        "chairwoman", "ranking", "letter", "report", "bill", "draft", "act", "legislation",
        "legislative", "measure", "amendment", "resolution", "notice", "summary", "overview",
        "examines", "examining", "discusses", "discussing", "explores", "reviews", "reviewing",
        "evaluates", "considers", "addresses", "addressing", "focuses", "highlights", "proposes",
        "proposing", "seeks", "aims", "urges", "requests", "requesting", "calls", "recommends",
        "regarding", "concerning", "related", "relating", "prepared", "remarks", "panel",
        "session", "first", "second", "full", "form", "disclosure", "truth", "filed",
    }
)

_HARD_MODALITY_STEMS_V6: dict[str, str] = {
    "mandates": "mandat",
    "compulsory": "compuls",
    "prohibits": "prohibit",
    "prohibition": "prohibit",
    "criminalizes": "criminal",
    "abolishes": "abolish",
    "abolish": "abolish",
    "vetoes": "veto",
    "cancels": "cancel",
    "subpoenas": "subpoena",
    "unanimously": "unanim",
    "unconditionally": "uncondit",
    "appropriates": "appropriat",
    "withdraws": "withdraw",
    "withdrawal": "withdraw",
    "retracts": "retract",
    "termination": "terminat",
    "repeal": "repeal",
    "repeals": "repeal",
    "immunity": "immun",
    "overturning": "overturn",
    "defeated": "defeat",
    "unfavorable": "unfavor",
}

_POLARITY_PHRASES_V6: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"\brejected\s+on\s+roll\s+call\b", re.I), ("rejected", "roll")),
    (re.compile(r"\badopted\s+unanimously\b", re.I), ("adopted", "unanim")),
    (re.compile(r"\bstriking\s+all\s+text\s+via\s+substitute\b", re.I), ("striking", "substitute")),
    (re.compile(r"\brefuses\s+to\s+answer\b", re.I), ("refus",)),
    (re.compile(r"\binvokes\s+executive\s+immunity\b", re.I), ("immun",)),
)

_CLAIM_BILL_OR_LAW_RE_V6 = re.compile(
    r"\b(?:H\.?\s*R\.?|S\.?|H\.?\s*Res\.?|S\.?\s*Res\.?|H\.?\s*J\.?\s*Res\.?|S\.?\s*J\.?\s*Res\.?|"
    r"H\.?\s*Con\.?\s*Res\.?|S\.?\s*Con\.?\s*Res\.?|P(?:ublic)?\.?\s*L(?:aw)?\.?\s*\d{2,3}\s*[-–])\s*(\d{1,5})\b",
    re.I,
)
_CLAIM_DOLLAR_RE_V6 = re.compile(
    r"\$\s*(\d+(?:\.\d+)?)\s*(million|billion|trillion)?\b",
    re.I,
)
_WORD_CONGRESS_ONES_V6: dict[str, int] = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15,
    "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20,
}
_WORD_CONGRESS_TENS_V6: dict[str, int] = {
    "tenth": 10, "twentieth": 20, "twenty": 20,
}
_SPELLED_CONG_RE_V6 = re.compile(
    r"\bone\s+hundred\s+(?:and\s+)?([a-z]+)(?:[-\s]+([a-z]+))?\s+congress\b",
    re.I,
)
_SRC_NUM_1_5_RE_V6 = re.compile(r"(?<!\d)\d{1,5}(?!\d)")
_SRC_YYYYMMDD_RE_V6 = re.compile(r"(?<!\d)(19[3-9]\d|20[0-3]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")
_SRC_YEAR4_RE_V6 = re.compile(r"(?<!\d)(19[3-9]\d|20[0-3]\d)(?!\d)")
_SRC_FY2_RE_V6 = re.compile(r"(?:\bfy\s*['\u2019]?|['\u2019])(\d{2})(?!\d)")
_SRC_SLASH_YR2_RE_V6 = re.compile(r"(?<!\d)\d{1,2}[/-](?:\d{1,2}[/-])?(\d{2})(?!\d)")
_SRC_MONTH_YR2_RE_V6 = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z.]*\s*[-/']?\s*(\d{2})(?!\d)"
)
_DOC_TOK_RE_V6 = re.compile(r"[a-z0-9]{2,}")
_CLAIM_TOK_RE_V6 = re.compile(r"[a-z0-9]{3,}")
_CLAIM_NUM_RE_V6 = re.compile(r"\b\d{2,5}\b")
_CLAIM_ALPHA4_RE_V6 = re.compile(r"[a-z]{4,}")
_SUBSTANTIAL_FOREIGN_RE_V6 = re.compile(r"\bsubstantial\s+foreign\b")
_SUBSTANTIAL_FED_GRANTS_RE_V6 = re.compile(r"\bsubstantial\s+(?:foreign\s+and\s+)?federal\s+grants\b")
_WS_NORM_RE_V6 = re.compile(r"\s+")

_NON_PERSON_STOPWORDS_V6 = frozenset(
    {
        "building", "committee", "subcommittee", "house", "senate", "congress",
        "office", "room", "washington", "staff", "minority", "majority",
        "department", "agency", "united", "states", "hearing", "witnesses",
    }
)
_OFFICE_BUILDING_TOKENS_V6 = frozenset(
    {"building", "rayburn", "longworth", "dirksen", "hart", "cannon", "russell"}
)
_CMT_CODE_KEYWORDS_V6: dict[str, str] = {
    "ag": "agriculture nutrition forestry",
    "ap": "appropriations",
    "as": "armed services",
    "ba": "financial services banking housing urban",
    "bu": "budget",
    "ed": "education workforce labor health pensions",
    "ep": "environment public works",
    "fa": "foreign affairs relations",
    "fi": "finance",
    "fr": "foreign relations",
    "go": "oversight accountability reform governmental",
    "ha": "house administration",
    "hl": "intelligence",
    "hm": "homeland security governmental",
    "hr": "veterans affairs",
    "ia": "indian affairs",
    "if": "energy commerce",
    "ig": "intelligence",
    "ii": "natural resources energy",
    "jc": "joint",
    "je": "joint economic",
    "jt": "joint taxation",
    "ju": "judiciary",
    "pw": "transportation infrastructure",
    "ru": "rules",
    "sb": "small business entrepreneurship",
    "sc": "science space technology commerce",
    "sl": "intelligence",
    "sm": "small business",
    "so": "ethics standards official conduct",
    "sp": "aging",
    "sy": "science space technology",
    "vr": "veterans affairs",
    "wm": "ways means",
}
_SLUG_CMT_CODE_RE_V6 = re.compile(
    r"(?:HHRG|HMTG|HMKP|CHRG)-\d{2,3}-([A-Za-z]{2})\d{0,2}\b",
    re.I,
)
_KNOWN_CMT_CODE_RE_V6 = re.compile(r"\b(?:hs|ss|js|hl|sl)([a-z]{2})\d{2}\b", re.I)
_TTF_HEADER_RE_V6 = re.compile(
    r"truth\s+in\s+testimony|witness\s+disclosure\s+requirement|disclosure\s+form",
    re.I,
)
_QFR_Q_LINE_RE_V6 = re.compile(r"(?:^|\n)\s*(?:Q\.|Question\s*\d*|1\.\s+[A-Z])")
_QFR_HEADER_RE_V6 = re.compile(r"questions\s+for\s+the\s+record|responses?\s+to|answers\s+to", re.I)
_HEARING_SCHED_RE_V6 = re.compile(r"\b(?:witnesses|date:|time:|location:|committee\s+on)\b", re.I)
_DEAR_SALUTATION_RE_V6 = re.compile(
    r"\bdear\s+(?:chairman|chairwoman|chair|senator|rep\.?|representative|ranking|mr\.?|ms\.?|mrs\.?|dr\.?|hon\.?)\b",
    re.I,
)
_MEMBER_TITLE_RE_V6 = re.compile(r"\b(?:rep\.|representative|sen\.|senator)\b", re.I)
_CMT_GENERIC_TAIL_WORDS_V6 = frozenset(
    {"affairs", "services", "accountability", "reform", "governmental", "government", "operations", "related", "agencies"}
)
_ATOMIC_CLAIM_STOPWORDS_V6 = frozenset(
    {"house", "senate", "committee", "hearing", "statement", "testimony", "letter", "report"}
)
_MONTH_STEMS_BY_NUM_V6: dict[int, tuple[str, ...]] = {
    1: ("jan", "january"),
    2: ("feb", "february"),
    3: ("mar", "march"),
    4: ("apr", "april"),
    5: ("may",),
    6: ("jun", "june"),
    7: ("jul", "july"),
    8: ("aug", "august"),
    9: ("sep", "sept", "september"),
    10: ("oct", "october"),
    11: ("nov", "november"),
    12: ("dec", "december"),
}
_STRICT_NON_CORRESPONDENCE_KINDS_V6 = frozenset(
    {
        "truth_in_testimony_disclosure",
        "nominee_questionnaire_apq",
        "event_web_page",
        "committee_vote",
        "attendance_quorum_sheet",
        "member_roster",
        "witness_list",
        "committee_rules",
        "comparative_print",
        "bill_or_draft",
        "committee_amendment",
    }
)
_REQUIRED_CORRESPONDENCE_KINDS_V6 = frozenset(
    {
        "oversight_letter",
        "witness_invitation",
        "external_submission_letter",
        "qfr_request",
        "qfr_response",
    }
)
_VOTE_OUTCOME_RE_V6 = re.compile(
    r"\b(?:\d+\s*[-–]\s*\d+|yeas?|nays?|adopted|rejected|agreed|not\s+agreed|passed|defeated|approved|failed|unanimous|voice\s+vote|ordered\s+reported|tabled)\b",
    re.I,
)
_TALLY_PAIR_RE_V6 = re.compile(r"\b(\d{1,3})\s*[-–]\s*(\d{1,3})\b")
_EMAIL_HEADER_LINE_RE_V6 = re.compile(r"(?:^|\n)\s*(?:from|to|cc|sent):\s*([^\n]{3,120})", re.I)
_WITNESS_HON_LINE_RE_V6 = re.compile(
    r"(?:^|\n)\s*(?:the\s+honorable|hon\.|dr\.|mr\.|ms\.|mrs\.|prof\.|amb\.|gen\.|adm\.)\s+[A-Z][a-zA-Z'\u00C0-\u024F-]+",
    re.M,
)


def _expand_source_numbers_v6(doc_l: str, filename: str = "") -> set[str]:
    """Extract literal + calendar/ordinal/YYYYMMDD-implied integers from source text & filename."""
    nums = set(_SRC_NUM_1_5_RE_V6.findall(doc_l))
    # Unpack 8-digit YYYYMMDD dates (`20211215` -> `2021`, `12`, `15`)
    for m_ymd in _SRC_YYYYMMDD_RE_V6.finditer(doc_l):
        nums.add(m_ymd.group(1))
        nums.add(str(int(m_ymd.group(2))))
        nums.add(str(int(m_ymd.group(3))))
    slug_c = extract_slug_congress_v6(filename)
    if slug_c is not None:
        nums.add(str(slug_c))
    for m_sp in _SPELLED_CONG_RE_V6.finditer(doc_l):
        w1 = (m_sp.group(1) or "").lower()
        w2 = (m_sp.group(2) or "").lower()
        if w1 in _WORD_CONGRESS_ONES_V6 and not w2:
            nums.add(str(100 + _WORD_CONGRESS_ONES_V6[w1]))
        elif w1 in _WORD_CONGRESS_TENS_V6:
            extra = _WORD_CONGRESS_ONES_V6.get(w2, 0)
            nums.add(str(100 + _WORD_CONGRESS_TENS_V6[w1] + extra))
    # Derive implied Congress numbers from explicit 4-digit contemporary years in source text
    for yr_s in _SRC_YEAR4_RE_V6.findall(doc_l):
        yr = int(yr_s)
        c_even = ((yr - 1 if yr % 2 == 0 else yr) - 1789) // 2 + 1
        if 74 <= c_even <= 130:
            nums.add(str(c_even))
        if yr % 2 == 1 and 74 <= c_even - 1 <= 130:
            nums.add(str(c_even - 1))
    # Expand 2-digit slash/dash/month/apostrophe years (`05/22/18`, `May '18`, `FY24` -> `2018`, `2024`)
    for m_fy in _SRC_FY2_RE_V6.finditer(doc_l):
        yy = int(m_fy.group(1))
        nums.add(str(2000 + yy if yy <= 50 else 1900 + yy))
    for m_sl in _SRC_SLASH_YR2_RE_V6.finditer(doc_l):
        yy = int(m_sl.group(1))
        nums.add(str(2000 + yy if yy <= 50 else 1900 + yy))
    for m_my in _SRC_MONTH_YR2_RE_V6.finditer(doc_l):
        yy = int(m_my.group(1))
        nums.add(str(2000 + yy if yy <= 50 else 1900 + yy))
    return nums


def check_gist_title_grounding_v6(
    docmeta: Mapping[str, Any] | None,
    *,
    text: str | None = None,
    filename: str = "",
    known: str | Mapping[str, Any] | None = None,
    min_text_chars_for_lexical: int = 160,
    threshold: float = 0.45,
) -> dict[str, Any]:
    """Pure-stdlib `C0_Stdlib` `composed_title` + `gist` faithfulness & grounding gate (`0` ML/Jev weights).

    Verifies numeric, citation/bill-ID/dollar-amount, hard legal-force modality, outcome polarity,
    and lexical/5-char-stem support against source document text (`~0.05 ms` CPU, `-B -I -S` stdlib clean).
    """
    if not isinstance(docmeta, Mapping) or docmeta.get("status") != "usable":
        return {
            "checked": False,
            "is_grounded": True,
            "grounding_score": 1.0,
            "tok_coverage": 1.0,
            "stem_coverage": 1.0,
            "num_coverage": 1.0,
            "ungrounded_numbers": [],
            "ungrounded_citations": [],
            "ungrounded_modality": [],
            "reasons": [],
        }

    raw_text = (text or "").strip()
    title = str(docmeta.get("composed_title") or "").strip()
    gist = str(docmeta.get("gist") or "").strip()
    if not raw_text or (not title and not gist):
        return {
            "checked": False,
            "is_grounded": True,
            "grounding_score": 1.0,
            "tok_coverage": 1.0,
            "stem_coverage": 1.0,
            "num_coverage": 1.0,
            "ungrounded_numbers": [],
            "ungrounded_citations": [],
            "ungrounded_modality": [],
            "reasons": [],
        }

    known_s = ""
    if isinstance(known, Mapping):
        known_s = " ".join(f"{k} {v}" for k, v in known.items() if v is not None)
    elif isinstance(known, str) and known.strip() != "<NONE>":
        known_s = known

    doc_l = _nfkc_lower(f"{filename} {known_s} {raw_text}")
    doc_tokens = set(_DOC_TOK_RE_V6.findall(doc_l))
    doc_stems5 = {w[:5] for w in doc_tokens if len(w) >= 5}
    doc_stems4 = {w[:4] for w in doc_tokens if len(w) >= 4}
    doc_prefixes = (
        doc_tokens
        | doc_stems4
        | doc_stems5
        | {w[:6] for w in doc_tokens if len(w) >= 6}
        | {w[:7] for w in doc_tokens if len(w) >= 7}
        | {w[:8] for w in doc_tokens if len(w) >= 8}
        | {w[:9] for w in doc_tokens if len(w) >= 9}
        | {w[:10] for w in doc_tokens if len(w) >= 10}
    )
    doc_nums = _expand_source_numbers_v6(doc_l, filename=filename)

    claim_raw = f"{title} {gist}".strip()
    claim_l = _nfkc_lower(claim_raw)

    c_tokens = [w for w in _CLAIM_TOK_RE_V6.findall(claim_l) if w not in _GROUNDING_STOPWORDS_V6]
    c_nums = _CLAIM_NUM_RE_V6.findall(claim_l)

    tok_cov = sum(1 for w in c_tokens if w in doc_tokens) / max(1, len(c_tokens))
    c_stems5 = [w[:5] for w in c_tokens if len(w) >= 5]
    stem5_cov = (sum(1 for s in c_stems5 if s in doc_stems5) / len(c_stems5)) if c_stems5 else tok_cov
    c_stems4 = [w[:4] for w in c_tokens if len(w) >= 4]
    stem4_cov = (sum(1 for s in c_stems4 if s in doc_stems4) / len(c_stems4)) if c_stems4 else tok_cov

    ungrounded_nums = list(dict.fromkeys(n for n in c_nums if n not in doc_nums))
    num_cov = (sum(1 for n in c_nums if n in doc_nums) / len(c_nums)) if c_nums else 1.0

    # Explicit bill/law/dollar citation check
    ungrounded_cits: list[str] = []
    for m_b in _CLAIM_BILL_OR_LAW_RE_V6.finditer(claim_raw):
        b_num = m_b.group(1)
        if b_num not in doc_nums:
            ungrounded_cits.append(m_b.group(0).strip())
    for m_d in _CLAIM_DOLLAR_RE_V6.finditer(claim_raw):
        amt_s = m_d.group(1)
        mag_s = (m_d.group(2) or "").lower()
        amt_parts = [p for p in amt_s.split(".") if p]
        if any(p not in doc_nums for p in amt_parts) or (mag_s and mag_s[:5] not in doc_stems5):
            ungrounded_cits.append(m_d.group(0).strip())
    ungrounded_cits = list(dict.fromkeys(ungrounded_cits))

    # Hard legal-force modality & outcome-polarity check (O(1) hash prefix lookup)
    ungrounded_mod: list[str] = []
    for w in _CLAIM_ALPHA4_RE_V6.findall(claim_l):
        req_stem = _HARD_MODALITY_STEMS_V6.get(w)
        if req_stem is not None and req_stem not in doc_prefixes:
            ungrounded_mod.append(w)
    for rx_pol, req_stems in _POLARITY_PHRASES_V6:
        m_pol = rx_pol.search(claim_raw)
        if m_pol:
            if not all(st in doc_prefixes for st in req_stems):
                ungrounded_mod.append(m_pol.group(0).strip().lower())
    # Disclosure contradiction: claim asserts foreign/federal grants when disclosure explicitly says False/None
    disc = docmeta.get("disclosure")
    if isinstance(disc, Mapping):
        if disc.get("has_foreign_payments") is False and _SUBSTANTIAL_FOREIGN_RE_V6.search(claim_l):
            ungrounded_mod.append("substantial foreign grants")
        if disc.get("has_federal_grants") is False and _SUBSTANTIAL_FED_GRANTS_RE_V6.search(claim_l):
            ungrounded_mod.append("substantial federal grants")
    ungrounded_mod = list(dict.fromkeys(ungrounded_mod))

    # Smooth analytic `C0_Stdlib` logistic faithfulness score in `[0.0, 1.0]`
    eff_cov = max(tok_cov, stem5_cov)
    z = (
        -1.35
        + 3.30 * stem5_cov
        + 1.90 * tok_cov
        - 2.65 * len(ungrounded_nums)
        - 2.85 * len(ungrounded_mod)
        - 2.95 * len(ungrounded_cits)
    )
    if len(raw_text) < min_text_chars_for_lexical and not (ungrounded_nums or ungrounded_mod or ungrounded_cits):
        z = max(z, 1.60)
    elif len(c_tokens) <= 3 and eff_cov >= 0.33 and not (ungrounded_nums or ungrounded_mod or ungrounded_cits):
        z = max(z, 0.85)
    score = round(1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, z)))), 4)

    reasons: list[str] = []
    if ungrounded_cits:
        reasons.append(f"ungrounded_citations:{ungrounded_cits[:3]}")
    if ungrounded_mod:
        reasons.append(f"ungrounded_modality:{ungrounded_mod[:3]}")
    if ungrounded_nums:
        reasons.append(f"ungrounded_numbers:{ungrounded_nums[:4]}")
    if (
        len(raw_text) >= min_text_chars_for_lexical
        and len(c_tokens) >= 5
        and stem4_cov < 0.25
        and tok_cov < 0.20
    ):
        reasons.append(f"low_lexical_overlap:tok={tok_cov:.2f},stem4={stem4_cov:.2f}")
    elif len(raw_text) >= min_text_chars_for_lexical and score < threshold and len(c_tokens) >= 4:
        reasons.append(f"low_grounding_score:{score:.3f}<{threshold:.2f}")

    return {
        "checked": True,
        "is_grounded": len(reasons) == 0,
        "grounding_score": score,
        "tok_coverage": round(tok_cov, 4),
        "stem_coverage": round(stem5_cov, 4),
        "stem4_coverage": round(stem4_cov, 4),
        "num_coverage": round(num_cov, 4),
        "ungrounded_numbers": ungrounded_nums,
        "ungrounded_citations": ungrounded_cits,
        "ungrounded_modality": ungrounded_mod,
        "reasons": reasons,
    }


def _extract_row_text_v6(det: Mapping[str, Any]) -> str | None:
    for key in ("text", "p12_clean_text", "p12_text", "clean_text", "p12_raw_text"):
        val = det.get(key)
        if isinstance(val, str):
            return val
    return None


def _extract_entity_window_v6(text: str, name: str, window_chars: int = 160) -> str:
    if not text or not name:
        return ""
    sur = surname_token_v6(name)
    if len(sur) < 2:
        return text[: 2 * window_chars]
    tl = text.lower()
    pos = tl.find(sur)
    if pos < 0:
        return text[: 2 * window_chars]
    lo = max(0, pos - window_chars)
    hi = min(len(text), pos + len(sur) + window_chars)
    return text[lo:hi]


def _expand_known_committee_keywords_v6(filename: str, known_s: str) -> str:
    extras: list[str] = []
    for m_s in _SLUG_CMT_CODE_RE_V6.finditer(filename or ""):
        kw = _CMT_CODE_KEYWORDS_V6.get(m_s.group(1).lower())
        if kw:
            extras.append(kw)
    for m_k in _KNOWN_CMT_CODE_RE_V6.finditer(known_s or ""):
        kw = _CMT_CODE_KEYWORDS_V6.get(m_k.group(1).lower())
        if kw:
            extras.append(kw)
    return " ".join(extras)


def score_atomic_stdlib_v6(
    docmeta: Mapping[str, Any] | None,
    det_row: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure-stdlib zero-ML `V0_Stdlib_Atomic` output validator (`~0.06 ms` CPU, `-B -I -S` clean).

    Checks:
      1. Committee text/slug/relational grounding (catches hallucinated `Oversight`/`Judiciary` committees).
      2. False non-usable rejections on substantive (`>1,200` char) text & hard structural `primary_kind` conflicts
         (`witness_statement` on Truth-in-Testimony forms or QFR Q&A; `news_clip_or_article` on hearing schedules).
      3. Title + gist lexical/stem coverage (`gist_miss_frac`).
      4. Per-persona non-person tokens (`Building`, `Rayburn`), ungrounded surnames, and letter salutation role flips.
    """
    det: Mapping[str, Any] = det_row if isinstance(det_row, Mapping) else {}
    if not isinstance(docmeta, Mapping):
        return {
            "checked": False,
            "atomic_risk_score": 2.0,
            "persona_defect_scores": [],
            "ungrounded_committees": [],
            "kind_conflicts": ["invalid_or_missing_docmeta"],
            "persona_flags": [],
            "ungrounded_dates": [],
            "action_summary_flags": [],
            "correspondence_flow_flags": [],
            "persona_omission_flags": [],
            "gist_miss_frac": 1.0,
        }

    raw_text = (_extract_row_text_v6(det) or "").strip()
    filename = str(det.get("filename") or "")
    known = det.get("known") if det.get("known") is not None else det.get("known_json")
    known_s = ""
    if isinstance(known, Mapping):
        known_s = " ".join(f"{k} {v}" for k, v in known.items() if v is not None)
    elif isinstance(known, str) and known.strip() != "<NONE>":
        known_s = known

    if not raw_text:
        raw_p = docmeta.get("personas")
        n_p = len(raw_p) if isinstance(raw_p, list) else 0
        return {
            "checked": False,
            "atomic_risk_score": 0.0,
            "persona_defect_scores": [0.0] * n_p,
            "ungrounded_committees": [],
            "kind_conflicts": [],
            "persona_flags": [],
            "ungrounded_dates": [],
            "action_summary_flags": [],
            "correspondence_flow_flags": [],
            "persona_omission_flags": [],
            "gist_miss_frac": 0.0,
        }

    hsru_status = str(det.get("hsru_host_status") or "not_hsru")
    code_kw = _expand_known_committee_keywords_v6(filename, known_s)
    doc_l = _nfkc_lower(f"{filename} {known_s} {code_kw} {raw_text}")
    raw_masthead = str(det.get("p12_raw_text") or "")[:450]
    cmt_doc_l = _nfkc_lower(f"{doc_l} {raw_masthead}") if raw_masthead else doc_l

    rel_cmts_all: set[str] = set()
    for rk in ("rel_committees", "meeting_committees", "rel_host_committees"):
        rv = det.get(rk)
        if isinstance(rv, (list, tuple)):
            for c_item in rv:
                nc = norm_committee_token_v6(str(c_item))
                if nc:
                    rel_cmts_all.add(nc)

    risk = 0.0
    ungrounded_cmts: list[str] = []
    if hsru_status != "rules_host":
        for c in docmeta.get("committees") or ():
            if not isinstance(c, str) or not c.strip():
                continue
            core = norm_committee_token_v6(c)
            if core and core in rel_cmts_all:
                continue
            words = [w for w in core.split() if len(w) >= 4 and w not in _CMT_GENERIC_TAIL_WORDS_V6]
            if not words:
                words = [w for w in core.split() if len(w) >= 4]
            if words and not all(w[:5] in cmt_doc_l for w in words[:2]):
                ungrounded_cmts.append(c)
                risk += 0.65

    pk = docmeta.get("primary_kind")
    st = str(docmeta.get("status") or "usable")
    kind_conflicts: list[str] = []
    if (pk is None or st != "usable") and len(raw_text) > 600 and not det.get("triage_status"):
        head300 = raw_text[:300].lower()
        if "<?xml" not in head300 and "<mods" not in head300:
            kind_conflicts.append(f"false_non_usable:{st}:len={len(raw_text)}")
            risk += 0.70

    if st == "usable":
        if pk == "witness_statement":
            if _TTF_HEADER_RE_V6.search(raw_text[:900]):
                kind_conflicts.append("ttf_disclosure_header_on_witness_statement")
                risk += 0.65
            if len(_QFR_Q_LINE_RE_V6.findall(raw_text[:2500])) >= 2 and _QFR_HEADER_RE_V6.search(doc_l[:1500]):
                kind_conflicts.append("qfr_qa_structure_on_witness_statement")
                risk += 0.55
        elif pk == "news_clip_or_article":
            sched_hits = _HEARING_SCHED_RE_V6.findall(doc_l[:800])
            if len(sched_hits) >= 2:
                kind_conflicts.append("hearing_schedule_headers_on_news_clip")
                risk += 0.45

    miss_frac = 0.0
    if st == "usable":
        claim = _nfkc_lower(f"{docmeta.get('composed_title') or ''} {docmeta.get('gist') or ''}")
        doc_toks = set(re.findall(r"[a-z0-9]{3,}", doc_l))
        doc_p5 = {d[:5] for d in doc_toks if len(d) >= 5}
        c_toks = [
            w
            for w in re.findall(r"[a-z0-9]{4,}", claim)
            if w not in _ATOMIC_CLAIM_STOPWORDS_V6
        ]
        if c_toks:
            miss_frac = sum(1 for w in c_toks if w not in doc_toks and w[:5] not in doc_p5) / len(c_toks)
            risk += 0.80 * miss_frac

    # Relational known surnames exempted from OCR/missing-surname check
    rel_surnames: set[str] = set()
    w_single = _extract_single_witness_name(det)
    if w_single:
        rel_surnames.add(surname_token_v6(w_single))
    b_name, _ = _extract_single_bioguide_member(det)
    if b_name:
        rel_surnames.add(surname_token_v6(b_name))

    raw_personas = docmeta.get("personas")
    personas_list = raw_personas if isinstance(raw_personas, list) else []
    pers_scores: list[float] = []
    persona_flags: list[str] = []
    pk_str = str(pk or "")
    for px in personas_list:
        if not isinstance(px, Mapping):
            pers_scores.append(0.90)
            continue
        nm = str(px.get("name") or "").strip()
        rl = str(px.get("role") or "witness")
        stripped = _HONORIFIC_SUFFIX_RE.sub(" ", nm)
        toks = [w.lower() for w in re.findall(r"[A-Za-z\u00C0-\u024F]+", stripped) if len(w) > 1]
        pr = 0.0
        if not toks or toks[-1] in _NON_PERSON_STOPWORDS_V6 or any(w in _OFFICE_BUILDING_TOKENS_V6 for w in toks):
            pr += 0.90
            persona_flags.append(f"non_person_persona:{nm!r}")
        else:
            sur = surname_token_v6(nm)
            if len(raw_text) >= 60 and sur and sur not in doc_l and sur not in rel_surnames:
                pr += 0.75
                persona_flags.append(f"ungrounded_persona_surname:{nm!r}")
            elif len(raw_text) >= 80:
                ctx_l = _extract_entity_window_v6(raw_text, nm, window_chars=160).lower()
                if "letter" in pk_str and rl in ("chair", "ranking_member"):
                    pr += 0.65
                if _DEAR_SALUTATION_RE_V6.search(ctx_l) and rl in ("chair", "ranking_member", "sender"):
                    pr += 0.55
                if (
                    pk_str == "hearing_transcript"
                    and rl == "witness"
                    and _MEMBER_TITLE_RE_V6.search(f"{px.get('title') or ''} {ctx_l[:80]}")
                ):
                    pr += 0.55
        pers_scores.append(round(min(1.0, pr), 4))

    # Atomic Check 5: Intra-Congress ISO date text/slug/relational grounding
    ungrounded_dates: list[str] = []
    action_summary_flags: list[str] = []
    cflow_flags: list[str] = []
    omission_flags: list[str] = []

    if st == "usable":
        doc_nums = _expand_source_numbers_v6(doc_l, filename=filename)
        rel_dates = {
            str(det.get(dk)).strip()
            for dk in ("rel_event_date", "event_date", "doc_date")
            if isinstance(det.get(dk), str) and str(det.get(dk)).strip()
        }
        if isinstance(known, Mapping) and isinstance(known.get("date"), str):
            rel_dates.add(known["date"].strip())
        elif isinstance(known, str):
            for m_kd in re.finditer(r"\b(19\d\d|20\d\d)-(0[1-9]|1[0-2])(?:-([0-2]\d|3[01]))?\b", known):
                rel_dates.add(m_kd.group(0))

        for df_key in ("doc_date", "event_date", "due_date"):
            dv = docmeta.get(df_key)
            if not isinstance(dv, str) or not dv.strip():
                continue
            ds = dv.strip()
            if ds in rel_dates or any(rd.startswith(ds) or ds.startswith(rd) for rd in rel_dates):
                continue
            m_iso = re.fullmatch(r"(\d{4})-(\d{2})(?:-(\d{2}))?", ds)
            if not m_iso:
                continue
            yr_s, mo_s, dy_s = m_iso.group(1), m_iso.group(2), m_iso.group(3)
            mo_i = int(mo_s)
            yr_ok = (yr_s in doc_nums) or (yr_s in doc_l)
            mo_stems = _MONTH_STEMS_BY_NUM_V6.get(mo_i, ())
            mo_word_ok = any(re.search(r"\b" + st_m, doc_l) for st_m in mo_stems)
            mo_num_ok = bool(
                re.search(
                    rf"(?<!\d)0?{mo_i}[/-](?:0?{int(dy_s)}[/-])?(?:{yr_s}|{yr_s[2:]})(?!\d)",
                    doc_l,
                )
                if dy_s
                else re.search(rf"(?<!\d)0?{mo_i}[/-](?:{yr_s}|{yr_s[2:]})(?!\d)", doc_l)
            ) or (f"{yr_s}{mo_s}" in doc_l) or (f"{yr_s}-{mo_s}" in doc_l)
            if not yr_ok or not (mo_word_ok or mo_num_ok):
                ungrounded_dates.append(f"{df_key}={ds}")
            elif dy_s == "01" and mo_s == "01":
                # Catch fabricated YYYY-01-01 default dates when day '1' is absent next to Jan
                jan1_ok = bool(
                    re.search(r"\bjan(?:uary)?\.?\s+0?1\b|\b0?1\s+jan(?:uary)?\b|\b0?1[/-]0?1[/-]", doc_l)
                    or f"{yr_s}0101" in doc_l
                    or f"{yr_s}-01-01" in doc_l
                )
                if not jan1_ok:
                    ungrounded_dates.append(f"{df_key}={ds}:jan1_default")

        # Atomic Check 6: `committee_vote` action_summary completeness & tally grounding
        act_sum = str(docmeta.get("action_summary") or "").strip()
        if pk == "committee_vote":
            if not act_sum:
                action_summary_flags.append("missing_action_summary_on_committee_vote")
                risk += 0.60
            elif not _VOTE_OUTCOME_RE_V6.search(act_sum):
                action_summary_flags.append("vote_action_summary_missing_outcome_or_tally")
                risk += 0.50
        if act_sum and pk in ("committee_vote", "meeting_results"):
            for m_tal in _TALLY_PAIR_RE_V6.finditer(act_sum):
                t_a, t_b = m_tal.group(1), m_tal.group(2)
                if t_a not in doc_nums and t_b not in doc_nums:
                    action_summary_flags.append(f"ungrounded_vote_tally:{t_a}-{t_b}")
                    risk += 0.55

        # Atomic Check 7: `correspondence_flow` genre compatibility
        cflow = docmeta.get("correspondence_flow")
        if cflow is not None and pk in _STRICT_NON_CORRESPONDENCE_KINDS_V6:
            cflow_flags.append(f"spurious_correspondence_flow:{cflow}:on:{pk}")
        elif cflow is None and pk in _REQUIRED_CORRESPONDENCE_KINDS_V6:
            cflow_flags.append(f"missing_correspondence_flow_on:{pk}")

        # Atomic Check 8: Multi-actor omission detection (`investigative_exhibit` email chains & `witness_list` panels)
        n_valid_p = sum(1 for px in personas_list if isinstance(px, Mapping) and str(px.get("name") or "").strip())
        if len(raw_text) >= 200 and n_valid_p <= 1:
            if pk == "investigative_exhibit":
                hdr_matches = _EMAIL_HEADER_LINE_RE_V6.findall(raw_text[:2500])
                if len(hdr_matches) >= 3:
                    omission_flags.append(f"email_chain_actor_omission:extracted={n_valid_p},headers={len(hdr_matches)}")
                    risk += 0.45
            elif pk in ("witness_list", "hearing_notice"):
                hon_lines = _WITNESS_HON_LINE_RE_V6.findall(raw_text[:3000])
                if len(hon_lines) >= 3:
                    omission_flags.append(f"witness_panel_omission:extracted={n_valid_p},panel_lines={len(hon_lines)}")
                    risk += 0.50

    return {
        "checked": True,
        "atomic_risk_score": round(risk, 4),
        "persona_defect_scores": pers_scores,
        "ungrounded_committees": ungrounded_cmts,
        "kind_conflicts": kind_conflicts,
        "persona_flags": persona_flags,
        "ungrounded_dates": ungrounded_dates,
        "action_summary_flags": action_summary_flags,
        "correspondence_flow_flags": cflow_flags,
        "persona_omission_flags": omission_flags,
        "gist_miss_frac": round(miss_frac, 4),
    }


def _nfkc_lower(s: str) -> str:
    return _WS_NORM_RE_V6.sub(" ", unicodedata.normalize("NFKC", s)).strip().lower()


def surname_token_v6(name: str) -> str:
    s = _HONORIFIC_SUFFIX_RE.sub("", name or "")
    parts = [p for p in re.split(r"[^A-Za-z'\u00C0-\u024F-]+", s) if len(p) > 1]
    return unicodedata.normalize("NFKC", parts[-1]).lower() if parts else _nfkc_lower(name or "")


def norm_committee_token_v6(c: str) -> str:
    s = _CMT_STOPWORDS_RE.sub(" ", (c or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def iso_date_to_congress_v6(date_str: str | None) -> int | None:
    """Map `YYYY-MM-DD` or `YYYY-MM` to Constitutional Congress number (`None` on Jan 3 boundary)."""
    if not isinstance(date_str, str):
        return None
    s = date_str.strip()
    m_full = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m_full:
        yr, mo, dy = int(m_full.group(1)), int(m_full.group(2)), int(m_full.group(3))
        try:
            dt = datetime.date(yr, mo, dy)
        except ValueError:
            return None
        if yr >= 1935:
            if mo == 1 and dy == 3 and yr % 2 == 1:
                return None
            base_year = yr if (yr % 2 == 1 and (mo > 1 or dy > 3)) else (yr - 1 if yr % 2 == 0 else yr - 2)
            cong = ((base_year - 1789) // 2) + 1
            return cong if 1 <= cong <= 130 else None
        if yr >= 1789:
            if mo == 3 and dy == 4 and yr % 2 == 1:
                return None
            base_year = yr if (yr % 2 == 1 and (mo > 3 or (mo == 3 and dy > 4))) else (yr - 1 if yr % 2 == 0 else yr - 2)
            cong = ((base_year - 1789) // 2) + 1
            return cong if 1 <= cong <= 130 else None
        return None

    m_ym = re.fullmatch(r"(\d{4})-(\d{2})", s)
    if m_ym:
        yr, mo = int(m_ym.group(1)), int(m_ym.group(2))
        if not (1 <= mo <= 12):
            return None
        if yr >= 1935:
            if yr % 2 == 1 and mo == 1:
                return None
            base_year = yr if yr % 2 == 1 else yr - 1
            cong = ((base_year - 1789) // 2) + 1
            return cong if 1 <= cong <= 130 else None
    return None


def extract_slug_congress_v6(filename: str | None) -> int | None:
    if not filename:
        return None
    m = _OFFICIAL_SLUG_CONGRESS_RE.search(filename.strip())
    if not m:
        return None
    c = int(m.group(1))
    return c if 80 <= c <= 130 else None


def load_default_usc_oracle_v6(
    refspec_repo: str | Path | None = None,
) -> Any | None:
    """Optionally load SHA256-pinned `UscSectionOracle` (`citations_and_signals_v6` fast loader or `RefSpec`)."""
    resolved_repo = (
        Path(refspec_repo)
        if refspec_repo is not None
        else Path(os.environ.get("REFSPEC_ROOT", "/Users/mikewolfd/Work/spicy-stack/RefSpec"))
    )
    if not resolved_repo.exists():
        return None
    try:
        if __package__:
            from . import citations_and_signals_v6 as _cit_v6
        else:
            docmeta_dir = Path(__file__).resolve().parent
            if str(docmeta_dir) not in sys.path:
                sys.path.insert(0, str(docmeta_dir))
            import citations_and_signals_v6 as _cit_v6  # type: ignore

        orc = _cit_v6.get_cached_refspec_oracles_v6(resolved_repo)
        if orc is not None and getattr(orc, "usc_oracle", None) is not None:
            return orc.usc_oracle
    except Exception:
        pass

    src_path = resolved_repo / "src"
    if not src_path.exists():
        return None
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    try:
        from refspec.registry.usc_section_oracle import UscSectionOracle  # type: ignore

        return UscSectionOracle.from_repository(resolved_repo)
    except Exception:
        return None


def _extract_single_witness_name(det: Mapping[str, Any]) -> str | None:
    w_name = det.get("rel_witness_name")
    if isinstance(w_name, str) and w_name.strip():
        wks = det.get("witness_keys")
        if wks is None or (isinstance(wks, (list, tuple)) and len(wks) == 1):
            return w_name.strip()
    rel_wits = det.get("rel_witnesses") or det.get("witness_personas")
    if isinstance(rel_wits, (list, tuple)) and len(rel_wits) == 1:
        item = rel_wits[0]
        if isinstance(item, Mapping) and isinstance(item.get("name"), str) and item["name"].strip():
            return item["name"].strip()
    w_names = det.get("witness_names")
    if isinstance(w_names, (list, tuple)) and len(w_names) == 1 and isinstance(w_names[0], str):
        return w_names[0].strip()
    return None


def _extract_single_bioguide_member(det: Mapping[str, Any]) -> tuple[str | None, str | None]:
    bios = det.get("bioguide_ids")
    if isinstance(bios, (list, tuple)) and len(bios) > 1:
        return None, None
    m_name = det.get("rel_member_name")
    m_ps = det.get("rel_member_party_state")
    if isinstance(m_name, str) and m_name.strip():
        return m_name.strip(), (m_ps.strip() if isinstance(m_ps, str) and m_ps.strip() else None)
    rel_mems = det.get("rel_members") or det.get("bioguide_members")
    if isinstance(rel_mems, (list, tuple)) and len(rel_mems) == 1 and isinstance(rel_mems[0], Mapping):
        nm = rel_mems[0].get("name")
        ps = rel_mems[0].get("party_state")
        return (
            nm.strip() if isinstance(nm, str) and nm.strip() else None,
            ps.strip() if isinstance(ps, str) and ps.strip() else None,
        )
    return None, None


def _add_anomaly(
    anomalies: list[dict[str, Any]],
    *,
    code: str,
    category: str,
    severity: str,
    weight: float,
    detail: str,
) -> None:
    anomalies.append(
        {
            "code": code,
            "category": category,
            "severity": severity,
            "weight": round(float(weight), 3),
            "detail": detail,
        }
    )


def score_docmeta_anomalies_v6(
    docmeta: Mapping[str, Any] | None,
    det_row: Mapping[str, Any] | None = None,
    *,
    usc_oracle: Any = None,
) -> dict[str, Any]:
    """Score extracted `docmeta` against all 6 V6 deterministic anomaly & contradiction gates.

    Returns a JSON-serializable dict with `has_anomaly`, `escalate_to_teacher`, `severity`,
    `anomaly_score`, `anomaly_codes`, `anomalies`, and `recommended_action`.
    """
    det: Mapping[str, Any] = det_row if isinstance(det_row, Mapping) else {}
    anomalies: list[dict[str, Any]] = []

    if not isinstance(docmeta, Mapping):
        _add_anomaly(
            anomalies,
            code="invalid_or_missing_docmeta",
            category="schema",
            severity="high",
            weight=2.0,
            detail="Extracted docmeta is None or not a JSON object.",
        )
        return _finalize_anomaly_result(anomalies)

    status = docmeta.get("status")
    filename = str(det.get("filename") or "")
    text = _extract_row_text_v6(det)
    raw_text_stripped = (text or "").strip()

    if status in NON_USABLE_STATUSES_V6:
        # Check if deterministic lock proved document was actually usable
        locked_pk = det.get("v6_locked_primary_kind") or det.get("v5_locked_primary_kind") or det.get("locked_primary_kind")
        if isinstance(locked_pk, str) and locked_pk:
            _add_anomaly(
                anomalies,
                code="locked_kind_contradiction",
                category="relational_contradiction",
                severity="high",
                weight=1.5,
                detail=f"Predicted non-usable status={status!r} on grammar-locked usable kind {locked_pk!r}.",
            )
        elif len(raw_text_stripped) > 1200 and not det.get("triage_status"):
            head300 = raw_text_stripped[:300].lower()
            if "<?xml" not in head300 and "<mods" not in head300:
                _add_anomaly(
                    anomalies,
                    code="false_non_usable_on_substantive_text",
                    category="genre_uncertainty",
                    severity="high",
                    weight=1.25,
                    detail=f"Predicted non-usable status={status!r} despite {len(raw_text_stripped)} chars of substantive text.",
                )
        res_nu = _finalize_anomaly_result(anomalies)
        res_nu["atomic_stdlib"] = score_atomic_stdlib_v6(docmeta, det)
        return res_nu

    if status != "usable":
        # Non-usable structural statuses (`cover_or_toc`, `govinfo_wrapper`, `index_or_listing`, `catalog_xml`)
        if len(raw_text_stripped) > 1200 and not det.get("triage_status"):
            head300 = raw_text_stripped[:300].lower()
            if "<?xml" not in head300 and "<mods" not in head300:
                _add_anomaly(
                    anomalies,
                    code="false_non_usable_on_substantive_text",
                    category="genre_uncertainty",
                    severity="high",
                    weight=1.25,
                    detail=f"Predicted non-usable status={status!r} despite {len(raw_text_stripped)} chars of substantive text.",
                )
        res_nu2 = _finalize_anomaly_result(anomalies)
        res_nu2["atomic_stdlib"] = score_atomic_stdlib_v6(docmeta, det)
        return res_nu2

    pk = docmeta.get("primary_kind")
    is_sd_sub = bool(det.get("slug_is_sd_submission")) or bool(_SD_SUPPLEMENTAL_RE.search(filename))
    is_exhibit = bool(det.get("is_exhibit_or_external")) or bool(_EXHIBIT_FILENAME_RE.search(filename))
    hsru_status = str(det.get("hsru_host_status") or "not_hsru")

    raw_personas = docmeta.get("personas")
    personas_list = raw_personas if isinstance(raw_personas, list) else []
    valid_personas = [
        p
        for p in personas_list
        if isinstance(p, Mapping) and isinstance(p.get("name"), str) and p["name"].strip()
    ]
    pred_surnames = {surname_token_v6(str(p["name"])) for p in valid_personas if surname_token_v6(str(p["name"]))}

    # ------------------------------------------------------------------
    # (a) 0 personas on core actor-bearing document genres
    # ------------------------------------------------------------------
    if pk in ACTOR_REQUIRED_KINDS_V6 and len(valid_personas) == 0:
        _add_anomaly(
            anomalies,
            code="zero_personas_on_actor_kind",
            category="missing_actor",
            severity="high",
            weight=1.25,
            detail=f"0 personas extracted on actor-required genre {pk!r}.",
        )

    # ------------------------------------------------------------------
    # (b) Persona roster / voter-grid leak (`len > 10`, vote/quorum `> 4`, backbench spam)
    # ------------------------------------------------------------------
    raw_p_cnt = int(det.get("raw_persona_count") or len(valid_personas))
    if len(valid_personas) > 10 or raw_p_cnt > 10:
        _add_anomaly(
            anomalies,
            code="persona_roster_leak",
            category="roster_leak",
            severity="high",
            weight=1.25,
            detail=f"Persona count {max(len(valid_personas), raw_p_cnt)} exceeds 10-persona standing-roster cap.",
        )
    elif pk in ("committee_vote", "attendance_quorum_sheet", "member_roster") and len(valid_personas) > 4:
        _add_anomaly(
            anomalies,
            code="persona_roster_leak",
            category="roster_leak",
            severity="high",
            weight=1.0,
            detail=f"Persona count {len(valid_personas)} > 4 on {pk!r} (likely roll-call or attendance grid leak).",
        )
    elif pk in BACKBENCH_LEAK_TARGET_KINDS_V6:
        bb_raw = det.get("backbench_surnames")
        if isinstance(bb_raw, (list, tuple, set, frozenset)) and bb_raw:
            bb_set = {str(x).lower() for x in bb_raw if x}
            leaked_bb = [
                p["name"]
                for p in valid_personas
                if surname_token_v6(str(p["name"])) in bb_set
                and p.get("role") not in ("witness", "nominee", "amendment_offeror", "sponsor")
            ]
            if len(leaked_bb) >= 3:
                _add_anomaly(
                    anomalies,
                    code="persona_roster_leak",
                    category="roster_leak",
                    severity="high",
                    weight=1.0,
                    detail=f"Leaked {len(leaked_bb)} standing backbench roster members on {pk!r}: {leaked_bb[:4]}.",
                )

    # ------------------------------------------------------------------
    # (c) Catch-all `primary_kind == "other"` fallback
    # ------------------------------------------------------------------
    if not isinstance(pk, str) or pk == "other":
        _add_anomaly(
            anomalies,
            code="fallback_primary_kind_other",
            category="genre_uncertainty",
            severity="high",
            weight=1.0,
            detail=f"Ambiguous catch-all primary_kind={pk!r}.",
        )

    # ------------------------------------------------------------------
    # (d) Contradictions against relational `witness_keys`, `meeting_keys`, `bioguide_ids` & locks
    # ------------------------------------------------------------------
    locked_pk = (
        det.get("v6_locked_primary_kind")
        or det.get("v5_locked_primary_kind")
        or det.get("locked_primary_kind")
    )
    if isinstance(locked_pk, str) and locked_pk and pk != locked_pk:
        _add_anomaly(
            anomalies,
            code="locked_kind_contradiction",
            category="relational_contradiction",
            severity="high",
            weight=1.5,
            detail=f"Predicted primary_kind={pk!r} contradicts 100%-precision lock {locked_pk!r}.",
        )

    # d1. `witness_keys` check (strictly gated off `-SD00x` supplemental exhibits)
    if not is_sd_sub:
        wit_name = _extract_single_witness_name(det)
        if wit_name:
            wit_sur = surname_token_v6(wit_name)
            if wit_sur:
                if pk in CORE_WITNESS_AUTHOR_KINDS_V6 and wit_sur not in pred_surnames:
                    _add_anomaly(
                        anomalies,
                        code="relational_witness_contradiction",
                        category="relational_contradiction",
                        severity="high",
                        weight=1.25,
                        detail=f"Single witness_key {wit_name!r} (surname={wit_sur!r}) missing from {pk!r} personas.",
                    )
                elif pk == "qfr_response":
                    pred_wit_surs = {
                        surname_token_v6(str(p["name"]))
                        for p in valid_personas
                        if p.get("role") == "witness" and surname_token_v6(str(p["name"]))
                    }
                    if pred_wit_surs and wit_sur not in pred_wit_surs:
                        _add_anomaly(
                            anomalies,
                            code="relational_witness_contradiction",
                            category="relational_contradiction",
                            severity="high",
                            weight=1.0,
                            detail=f"Predicted QFR witness surnames {sorted(pred_wit_surs)} contradict witness_key {wit_name!r}.",
                        )

    # d2. `meeting_keys` check (`congress`, host-safe `chamber`, author-safe `committees`)
    rel_cong = det.get("rel_congress")
    if rel_cong is None:
        rel_cong = det.get("meeting_congress")
    pred_cong = docmeta.get("congress")
    if (
        isinstance(rel_cong, int)
        and not isinstance(rel_cong, bool)
        and isinstance(pred_cong, int)
        and not isinstance(pred_cong, bool)
        and not is_exhibit
        and not is_sd_sub
        and pk in CONTEMPORARY_CONGRESSIONAL_KINDS_V6
        and pred_cong != rel_cong
    ):
        _add_anomaly(
            anomalies,
            code="relational_meeting_congress_contradiction",
            category="relational_contradiction",
            severity="high",
            weight=1.25,
            detail=f"Predicted congress={pred_cong} contradicts relational meeting congress={rel_cong}.",
        )

    rel_ch = det.get("rel_chamber") or det.get("meeting_chamber")
    pred_ch = docmeta.get("chamber")
    if (
        isinstance(rel_ch, str)
        and rel_ch in ("house", "senate", "joint")
        and isinstance(pred_ch, str)
        and pk in FORMAL_COMMITTEE_KINDS_V6
        and pk not in HOST_CHAMBER_EXEMPT_KINDS_V6
        and hsru_status != "rules_host"
        and not is_sd_sub
        and not is_exhibit
        and pred_ch != rel_ch
    ):
        _add_anomaly(
            anomalies,
            code="relational_meeting_chamber_contradiction",
            category="relational_contradiction",
            severity="high",
            weight=1.0,
            detail=f"Predicted chamber={pred_ch!r} contradicts relational meeting chamber={rel_ch!r} on {pk!r}.",
        )

    rel_cmts_raw = det.get("rel_committees") or det.get("meeting_committees")
    pred_cmts_raw = docmeta.get("committees")
    if (
        isinstance(rel_cmts_raw, (list, tuple))
        and rel_cmts_raw
        and isinstance(pred_cmts_raw, list)
        and pred_cmts_raw
        and pk in FORMAL_COMMITTEE_KINDS_V6
        and hsru_status != "rules_host"
        and not is_sd_sub
        and not is_exhibit
    ):
        rel_cmts_norm = {norm_committee_token_v6(str(c)) for c in rel_cmts_raw if norm_committee_token_v6(str(c))}
        pred_cmts_norm = {norm_committee_token_v6(str(c)) for c in pred_cmts_raw if norm_committee_token_v6(str(c))}
        if rel_cmts_norm and pred_cmts_norm and pred_cmts_norm.isdisjoint(rel_cmts_norm):
            _add_anomaly(
                anomalies,
                code="relational_meeting_committee_contradiction",
                category="relational_contradiction",
                severity="medium",
                weight=0.75,
                detail=(
                    f"Predicted committees {list(pred_cmts_raw)} disjoint from relational meeting "
                    f"committees {list(rel_cmts_raw)}."
                ),
            )

    # d3. `bioguide_ids` check (text-grounded Member surname or explicit `party_state` mismatch)
    bio_name, bio_ps = _extract_single_bioguide_member(det)
    if bio_name:
        bio_sur = surname_token_v6(bio_name)
        if bio_sur:
            matched_personas = [
                p for p in valid_personas if surname_token_v6(str(p["name"])) == bio_sur
            ]
            if matched_personas and bio_ps and "-" in bio_ps:
                exp_party, exp_state = bio_ps.split("-", 1)
                exp_state2 = exp_state[:2].upper()
                for mp in matched_personas:
                    p_ps = mp.get("party_state")
                    if isinstance(p_ps, str) and "-" in p_ps:
                        got_party, got_state = p_ps.strip().split("-", 1)
                        got_state2 = got_state[:2].upper()
                        if got_state2 != exp_state2 or (
                            got_party.upper() != exp_party.upper()
                            and {got_party.upper(), exp_party.upper()} != {"I", "D"}
                        ):
                            _add_anomaly(
                                anomalies,
                                code="relational_bioguide_contradiction",
                                category="relational_contradiction",
                                severity="high",
                                weight=1.0,
                                detail=(
                                    f"Member {bio_name!r} party_state={p_ps!r} contradicts "
                                    f"members.parquet {bio_ps!r}."
                                ),
                            )
                            break
            elif (
                not matched_personas
                and pk in BIOGUIDE_AUTHOR_KINDS_V6
                and not is_sd_sub
                and (text is None or bio_sur in _nfkc_lower(text))
            ):
                _add_anomaly(
                    anomalies,
                    code="relational_bioguide_contradiction",
                    category="relational_contradiction",
                    severity="high",
                    weight=1.0,
                    detail=f"Text-grounded bioguide Member {bio_name!r} missing from {pk!r} personas.",
                )

    # ------------------------------------------------------------------
    # (e) `UscSectionOracle` invalid / non-existent U.S.C. section on non-drafts (`TRAP_1` safe)
    # ------------------------------------------------------------------
    if pk not in LEGISLATIVE_DRAFT_KINDS_V6:
        refs_raw = docmeta.get("refs")
        refs_list = [str(r) for r in refs_raw if isinstance(r, str)] if isinstance(refs_raw, list) else []
        pre_invalid = {
            str(r).strip()
            for r in (det.get("usc_oracle_invalid_refs") or [])
            if isinstance(r, str) and str(r).strip()
        }
        bad_usc: list[str] = []
        for r_str in refs_list:
            r_clean = r_str.strip()
            if r_clean in pre_invalid:
                bad_usc.append(f"{r_clean} (precomputed_absent)")
                continue
            m_u = _USC_REF_RE.match(r_clean)
            if not m_u:
                continue
            u_title = int(m_u.group(1))
            u_app = bool(m_u.group(2))
            u_sec = m_u.group(3).lower()
            if u_title < 1 or u_title > 54 or u_title == 53:
                bad_usc.append(f"{r_clean} (impossible_title={u_title})")
                continue
            if usc_oracle is not None:
                try:
                    sv = usc_oracle.section_verdict(u_title, u_sec, appendix=u_app)
                    verdict = getattr(sv, "verdict", None)
                    disp = getattr(sv, "disposition", None)
                    disp_v = getattr(disp, "verdict", None) if disp is not None else None
                    eff_cong = pred_cong if isinstance(pred_cong, int) else 118
                    if verdict == "absent":
                        bad_usc.append(f"{r_clean} (oracle=absent)")
                    elif verdict == "unknown" and disp_v == "repealed-no-successor" and eff_cong >= 105:
                        bad_usc.append(f"{r_clean} (oracle=repealed-no-successor)")
                except Exception:
                    pass
        if bad_usc:
            _add_anomaly(
                anomalies,
                code="invalid_usc_section_non_draft",
                category="citation_hallucination",
                severity="high",
                weight=1.25,
                detail=f"Non-existent U.S.C. section(s) on non-draft {pk!r}: {bad_usc[:4]}.",
            )

    # ------------------------------------------------------------------
    # (f) Constitutional Congress / calendar / official-slug mismatch
    # ------------------------------------------------------------------
    if isinstance(pred_cong, int) and not isinstance(pred_cong, bool) and 1 <= pred_cong <= 130:
        evt_date = docmeta.get("event_date")
        doc_date = docmeta.get("doc_date")
        evt_c = iso_date_to_congress_v6(evt_date) if isinstance(evt_date, str) else None
        doc_c = iso_date_to_congress_v6(doc_date) if isinstance(doc_date, str) else None
        slug_c = extract_slug_congress_v6(filename)

        if evt_c is not None and evt_c != pred_cong:
            _add_anomaly(
                anomalies,
                code="date_congress_calendar_mismatch",
                category="calendar_mismatch",
                severity="high",
                weight=1.25,
                detail=f"event_date={evt_date!r} (Congress {evt_c}) mismatches congress={pred_cong}.",
            )
        elif (
            doc_c is not None
            and doc_c != pred_cong
            and pk in CONTEMPORARY_CONGRESSIONAL_KINDS_V6
            and not is_sd_sub
            and not is_exhibit
        ):
            _add_anomaly(
                anomalies,
                code="date_congress_calendar_mismatch",
                category="calendar_mismatch",
                severity="high",
                weight=1.0,
                detail=f"Contemporary {pk!r} doc_date={doc_date!r} (Congress {doc_c}) mismatches congress={pred_cong}.",
            )
        elif slug_c is not None and slug_c != pred_cong and not is_exhibit:
            _add_anomaly(
                anomalies,
                code="date_congress_calendar_mismatch",
                category="calendar_mismatch",
                severity="high",
                weight=1.25,
                detail=f"Official filename slug Congress {slug_c} ({filename!r}) mismatches congress={pred_cong}.",
            )

    # ------------------------------------------------------------------
    # (g) Pure-stdlib `C0_Stdlib` `composed_title` / `gist` faithfulness gate
    # ------------------------------------------------------------------
    gist_grounding = check_gist_title_grounding_v6(
        docmeta,
        text=text,
        filename=filename,
        known=det.get("known") or det.get("known_json"),
    )
    if gist_grounding["checked"] and not gist_grounding["is_grounded"]:
        has_hard_halluc = bool(
            gist_grounding["ungrounded_citations"]
            or gist_grounding["ungrounded_modality"]
            or gist_grounding["ungrounded_numbers"]
        )
        _add_anomaly(
            anomalies,
            code="ungrounded_gist_or_title",
            category="faithfulness_hallucination",
            severity="high" if has_hard_halluc else "medium",
            weight=1.25 if has_hard_halluc else 1.0,
            detail=(
                f"Ungrounded composed_title/gist (score={gist_grounding['grounding_score']:.3f}): "
                f"{'; '.join(gist_grounding['reasons'])}"
            ),
        )

    # ------------------------------------------------------------------
    # (h) Pure-stdlib `V0_Stdlib_Atomic` checks (committee grounding, structural kind conflicts, persona stopword/surname)
    # ------------------------------------------------------------------
    atomic_v0 = score_atomic_stdlib_v6(docmeta, det)
    if atomic_v0["checked"]:
        if atomic_v0["ungrounded_committees"]:
            _add_anomaly(
                anomalies,
                code="ungrounded_committee_hallucination",
                category="committee_hallucination",
                severity="high",
                weight=1.0,
                detail=f"Predicted committee(s) lack text/slug/relational grounding: {atomic_v0['ungrounded_committees'][:4]}.",
            )
        if atomic_v0["kind_conflicts"]:
            _add_anomaly(
                anomalies,
                code="kind_structural_contradiction",
                category="genre_uncertainty",
                severity="high",
                weight=1.0,
                detail=f"Predicted primary_kind={pk!r} conflicts with structural headers: {atomic_v0['kind_conflicts']}.",
            )
        non_person_flags = [f for f in atomic_v0["persona_flags"] if f.startswith("non_person_persona:")]
        if non_person_flags:
            _add_anomaly(
                anomalies,
                code="invalid_or_misroled_persona",
                category="persona_hallucination",
                severity="medium",
                weight=0.5,
                detail=f"Non-person office/building token extracted as persona: {non_person_flags[:4]}.",
            )
        if atomic_v0["ungrounded_dates"]:
            _add_anomaly(
                anomalies,
                code="ungrounded_iso_date",
                category="date_hallucination",
                severity="medium",
                weight=0.0,
                detail=f"Predicted ISO date(s) lack text/slug/relational support: {atomic_v0['ungrounded_dates'][:3]}.",
            )
        if atomic_v0["action_summary_flags"]:
            _add_anomaly(
                anomalies,
                code="missing_or_ungrounded_vote_summary",
                category="action_summary_defect",
                severity="high",
                weight=1.0,
                detail=f"Vote/action_summary defect on {pk!r}: {atomic_v0['action_summary_flags']}.",
            )
        if atomic_v0["correspondence_flow_flags"]:
            _add_anomaly(
                anomalies,
                code="correspondence_flow_kind_conflict",
                category="genre_uncertainty",
                severity="medium",
                weight=0.0,
                detail=f"Correspondence flow vs primary_kind conflict: {atomic_v0['correspondence_flow_flags']}.",
            )
        if atomic_v0["persona_omission_flags"]:
            _add_anomaly(
                anomalies,
                code="suspected_persona_omission",
                category="missing_actor",
                severity="medium",
                weight=0.55,
                detail=f"Suspected multi-actor omission: {atomic_v0['persona_omission_flags']}.",
            )

    res = _finalize_anomaly_result(anomalies)
    if atomic_v0["checked"] and len(raw_text_stripped) >= 240:
        sub_risk = round(min(0.49, 0.45 * float(atomic_v0["gist_miss_frac"])), 4)
        if not res["has_anomaly"]:
            res["anomaly_score"] = sub_risk
        else:
            res["anomaly_score"] = round(float(res["anomaly_score"]) + sub_risk, 4)
    res["gist_grounding"] = gist_grounding
    res["atomic_stdlib"] = atomic_v0
    return res


def _finalize_anomaly_result(anomalies: list[dict[str, Any]]) -> dict[str, Any]:
    if not anomalies:
        return {
            "has_anomaly": False,
            "escalate_to_teacher": False,
            "severity": "none",
            "anomaly_score": 0.0,
            "anomaly_codes": [],
            "anomalies": [],
            "recommended_action": "accept",
        }

    score = round(sum(float(a["weight"]) for a in anomalies), 3)
    has_high = any(a["severity"] == "high" for a in anomalies)
    severity = "high" if has_high or score >= 1.0 else "medium"
    escalate = severity == "high" or score >= 1.0
    codes = list(dict.fromkeys(str(a["code"]) for a in anomalies))
    return {
        "has_anomaly": True,
        "escalate_to_teacher": escalate,
        "severity": severity,
        "anomaly_score": score,
        "anomaly_codes": codes,
        "anomalies": anomalies,
        "recommended_action": "escalate_teacher" if escalate else "deterministic_repair_or_teacher",
    }


def route_batch_anomalies_v6(
    docmetas: Sequence[Mapping[str, Any] | None],
    det_rows: Sequence[Mapping[str, Any] | None] | None = None,
    *,
    usc_oracle: Any = None,
) -> dict[str, Any]:
    """Score a batch of `DocMetaV4Causal` records and summarize anomaly/escalation rates."""
    n = len(docmetas)
    rows = det_rows if det_rows is not None else [None] * n
    results: list[dict[str, Any]] = []
    code_counts: dict[str, int] = {}
    flagged_indices: list[int] = []
    escalate_indices: list[int] = []

    for i in range(n):
        r = score_docmeta_anomalies_v6(
            docmetas[i],
            rows[i] if i < len(rows) else None,
            usc_oracle=usc_oracle,
        )
        results.append(r)
        if r["has_anomaly"]:
            flagged_indices.append(i)
            for c in r["anomaly_codes"]:
                code_counts[c] = code_counts.get(c, 0) + 1
        if r["escalate_to_teacher"]:
            escalate_indices.append(i)

    return {
        "n_docs": n,
        "flagged_count": len(flagged_indices),
        "flagged_pct": round(100.0 * len(flagged_indices) / max(n, 1), 2),
        "escalate_count": len(escalate_indices),
        "escalate_pct": round(100.0 * len(escalate_indices) / max(n, 1), 2),
        "counts_by_code": dict(sorted(code_counts.items(), key=lambda kv: -kv[1])),
        "flagged_indices": flagged_indices,
        "escalate_indices": escalate_indices,
        "per_doc": results,
    }


__all__ = [
    "ACTOR_REQUIRED_KINDS_V6",
    "BACKBENCH_LEAK_TARGET_KINDS_V6",
    "BIOGUIDE_AUTHOR_KINDS_V6",
    "CONTEMPORARY_CONGRESSIONAL_KINDS_V6",
    "CORE_WITNESS_AUTHOR_KINDS_V6",
    "FORMAL_COMMITTEE_KINDS_V6",
    "HOST_CHAMBER_EXEMPT_KINDS_V6",
    "LEGISLATIVE_DRAFT_KINDS_V6",
    "check_gist_title_grounding_v6",
    "extract_slug_congress_v6",
    "iso_date_to_congress_v6",
    "load_default_usc_oracle_v6",
    "norm_committee_token_v6",
    "route_batch_anomalies_v6",
    "score_atomic_stdlib_v6",
    "score_docmeta_anomalies_v6",
    "surname_token_v6",
]


if __name__ == "__main__":
    sample = score_docmeta_anomalies_v6(
        {
            "status": "usable",
            "text_quality": "native",
            "primary_kind": "witness_statement",
            "composed_title": "Testimony",
            "gist": "Summary.",
            "topics": ["oversight"],
        },
        {"filename": "HHRG-118-JU00-Wstate-SmithJ-20230510.pdf"},
    )
    print(sample)

