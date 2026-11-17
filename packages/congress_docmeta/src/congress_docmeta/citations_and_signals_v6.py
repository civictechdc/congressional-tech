#!/usr/bin/env python3
"""Unified Hybrid `RefSpec` Oracles + `spicy-docs` Stdlib Citation & Signal Engine (`citations_and_signals_v6.py`).

Stage 3 (`N8-N9`) deterministic runtime module for `DocMetaV4Causal`:
- 100% Python stdlib at module import and runtime (`/usr/bin/python3 -B -I -S` compatible across Python 3.9-3.13).
- Optional fast SHA256-pinned `pyarrow.parquet` / `csv` / `json` loader (`load_refspec_oracles_v6`) reading
  `RefSpec`'s 6 local statutory & regulatory oracles (`ActIndex`, `SourceCreditIndex`, `UscSectionOracle`,
  `UscDispositionTables`, `EoRosterOracle`, and optional `CfrAuthorityNotes`) with zero `refspec` package dependency.
- Enforces all 5 empirical `RefSpec` safeguards:
  1. `TRAP_1`: Never drop `UscSectionOracle == 'absent'` on `bill_or_draft` / `committee_amendment` / legislative
     drafts proposing brand-new U.S.C. sections (e.g., `41 U.S.C. 8302A`); filter & flag `absent` U.S.C. cites
     strictly on non-drafting genres (`witness_statement`, `qfr_response`, notices, letters, etc.).
  2. `TRAP_2`: Gate `EoRosterOracle` with `1 <= eo_num <= 14420` (`EO_HIGHEST_KNOWN`) AND block XML/file path
     patterns (e.g., `\\E043025.003.xml`).
  3. `TRAP_3`: Maximal uninterrupted capitalized `... Act` noun-phrase matching only (`Kelsey Smith Act` is never
     sub-sliced into `Smith Act of 1940`).
  4. `TRAP_4`: Separate `ActRelative` (`refs['law:...']` + `det_act_iris`) from standalone `short_titles[]`.
  5. `TRAP_5`: Strip left-margin bill line numbers before CFR/U.S.C. longhand scans and allow optional subsection
     pinpoints before `of title N` (`section 552b(c) of title 5`).
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import csv
from dataclasses import dataclass, field, replace
import hashlib
from itertools import accumulate
import json
import os
from pathlib import Path
import re
from string import ascii_lowercase
import sys
from typing import Any, Callable, Container, Iterable, Mapping, NamedTuple, Sequence

__all__ = [
    "DEFAULT_REFSPEC_ROOT",
    "DOCMETA_REF_PREFIXES_V6",
    "EO_HIGHEST_KNOWN_V6",
    "LEGISLATIVE_DRAFT_KINDS_V6",
    "PL_FIRST_NUMBERED_CONGRESS_V6",
    "ActIndexV6",
    "ActRelativeCitationV6",
    "ActResolutionV6",
    "CfrAuthorityNotesV6",
    "DispositionV6",
    "EoRosterOracleV6",
    "EoVerdictV6",
    "RefSpecOraclesV6",
    "SectionVerdictV6",
    "SourceCreditIndexV6",
    "UscDispositionTablesV6",
    "UscSectionOracleV6",
    "bill_type_and_number_v6",
    "canonical_usc_iri_v6",
    "extract_citations_and_signals_v6",
    "extract_fiscal_years_v6",
    "extract_short_titles_v6",
    "find_act_relative_occurrences_v6",
    "find_bill_citations_v6",
    "find_cfr_citations_v6",
    "find_federal_register_citations_v6",
    "find_maximal_popular_acts_v6",
    "find_public_law_citations_v6",
    "find_statute_citations_v6",
    "find_usc_citations_v6",
    "get_cached_refspec_oracles_v6",
    "is_legislative_draft_context_v6",
    "load_refspec_oracles_v6",
    "merge_citations_post_pass_v6",
    "normalize_docket_reference_v6",
    "normalize_gpo_glyphs_v6",
    "normalize_popular_name_v6",
    "normalize_ref_key_v6",
    "published_rin_v6",
    "resolve_act_name_v6",
    "resolve_act_relative_citation_v6",
    "strip_bill_margin_line_numbers_v6",
]

# ---------------------------------------------------------------------------
# Constants & Python 3.9-3.13 Portable Regex Primitives
# ---------------------------------------------------------------------------

DEFAULT_REFSPEC_ROOT_STR = "/Users/mikewolfd/Work/spicy-stack/RefSpec"
DEFAULT_REFSPEC_ROOT = Path(os.environ.get("REFSPEC_ROOT", DEFAULT_REFSPEC_ROOT_STR))

_ATOMIC = "(?>" if sys.version_info >= (3, 11) else "(?:"

DASH_SPELLINGS_V6 = "‐‑‒–—―−\x96\x97"
_DASH_MAP = str.maketrans(dict.fromkeys(DASH_SPELLINGS_V6, "-"))

DOCMETA_REF_PREFIXES_V6 = frozenset(
    {
        "bill",
        "amdt",
        "law",
        "usc",
        "cfr",
        "fr",
        "docket",
        "eo",
        "rule",
        "treaty",
        "nom",
        "rept",
        "hrg",
        "jct",
        "gao",
        "crs",
        "cbo",
        "olc",
        "gsa",
        "sudoc",
        "gpo",
        "grant",
        "advisory",
        "exhibit",
        "id",
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

EO_HIGHEST_KNOWN_V6 = 14_420
PL_FIRST_NUMBERED_CONGRESS_V6 = 57
CONGRESS_CURRENT_V6 = 120
USC_TITLE_COUNT_V6 = 54
USC_RESERVED_TITLES_V6 = frozenset({53})
CFR_TITLE_COUNT_V6 = 50
CFR_RESERVED_TITLES_V6 = frozenset({35})
APPENDIX_TITLES_PUBLISHED_V6 = frozenset({5, 10, 11, 18, 26, 28, 38, 40, 46, 50})

# Sealed SHA256 artifact pins from RefSpec
_ACT_ARTIFACT_REL = "output/usc-act-index-2026-08-22"
_SOURCE_CREDIT_REL = "output/usc-source-credit-index-2026-08-02"
_USC_ORACLE_REL = "research/evidence/usc-section-oracle-2026-08-24"
_USC_DISP_REL = "research/evidence/usc-disposition-tables-2026-08-23"
_EO_ROSTER_REL = "research/evidence/eo-roster-2026-08-31/derived/roster.csv"
_CFR_NOTES_REL = "research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl"

_SEALED_SHA256_PINS: Mapping[str, str] = {
    "usc-popular-names.parquet": "sha256:603d5b072133d8fe6802736aeaa70b9fb9832e4fb996158a083fae3ce1026a9a",
    "usc-act-sections.parquet": "sha256:9040d4460e90704aef911b4d4f704e9f432cebd7b58717f31f090a3008ca6159",
    "quarantine.parquet": "sha256:a89305172a27e682488e05e8fc82d8b0521d20a8fcee7d97a00331e8527acfac",
    "usc-source-credits.parquet": "sha256:d377545fe60d592a120bda30dffba665380cf82f826ae06cb327a581f0af9d8a",
    "usc-oracle-sections.parquet": "sha256:bbb450afb00cc7a28e2fcab7943d47207e8c1899f1e83209bd92d893fe39daac",
    "usc-oracle-ranges.parquet": "sha256:070226e36d324a15226bd84ce9f5e4a297b43ff83365dba37ed281d3186cd736",
    "usc-oracle-annual-sections.parquet": "sha256:4757327d2bbcd5258d0fc51f0658df7fc9999c21d5a40dbe0c2d466cf25e7323",
    "usc-oracle-annual-ranges.parquet": "sha256:c8cd96e1d13e4f429e1024f3a9fe25b8527036eae0adfd9ad29d9656522b43a3",
    "usc-oracle-subsections.parquet": "sha256:d7502945223eed92bdeb65e6a73cf52240febefe9814180675fc4df512cd08ed",
    "usc-oracle-chapters.parquet": "sha256:031ae7f3435f7ba2969bdf2c94b699170a63fe3183dd289ca23fa0ce45e90cb3",
    "usc-1994-title49-disposition.parquet": "sha256:8403212c0193b3361accf7ff4be238420634beb5aa5740d78b9960fef5b2aedd",
    "roster.csv": "sha256:967ad595326ea37bb368357f7da6253fe292123e305c95c346bf152254e20c9d",
}


def _normalize_dashes(text: str) -> str:
    return (text or "").translate(_DASH_MAP)


def _verify_sha256(path: Path, expected_key: str | None = None) -> None:
    key = expected_key or path.name
    expected = _SEALED_SHA256_PINS.get(key)
    if expected is None:
        return
    digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    if digest != expected:
        raise ValueError(f"Pinned RefSpec artifact drifted: {path} (expected {expected}, got {digest})")


# ---------------------------------------------------------------------------
# GPO Glyph Normalization & Bill Margin Line-Number Hygiene (`TRAP_5`)
# ---------------------------------------------------------------------------

_CURLY_SINGLE_RE = re.compile(r"[\u2018\u2019\u201b\u2032]")
_CURLY_DOUBLE_RE = re.compile(r"[\u201c\u201d\u201f\u2033]")

# Strips standalone bill margin line numbers (1..26) both on multi-line pages and
# inside single-line flattened longhand statutory/regulatory phrases ("title 14, 9 Code of Federal Regulations").
_BILL_MARGIN_LINE_NUM_RE = re.compile(
    r"(?<=,\s)(?:[1-9]|1\d|2[0-6])\s+(?=Code\s+of\s+Federal\s+Regulations\b|United\s+States\s+Code\b)"
    r"|(?<=\bof\s)(?:[1-9]|1\d|2[0-6])\s+(?=title\s+[1-9]\d?\b)"
    r"|(?m:^[ \t]*(?:[1-9]|1\d|2[0-6])[ \t]+(?=[A-Za-z\"(‘“—§(-]))"
)


def normalize_gpo_glyphs_v6(raw: str) -> str:
    """Normalize GPO curly/doubled single-quote conventions (`‘‘...’’` / ````...''`` -> `\"...\"`)."""
    if not raw:
        return ""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _CURLY_SINGLE_RE.sub("'", text)
    text = _CURLY_DOUBLE_RE.sub('"', text)
    text = text.replace("\u00a0", " ")
    return text.replace("``", '"').replace("''", '"')


def strip_bill_margin_line_numbers_v6(text: str) -> str:
    """Strip bill margin line numbers (`1..26`) that split multi-line or flattened CFR/U.S.C. citations."""
    if not text:
        return ""
    return _BILL_MARGIN_LINE_NUM_RE.sub("", text)


# ---------------------------------------------------------------------------
# Boundary Guards & Statutory/Regulatory Citation Grammars (`spicy-docs` / `RefSpec`)
# ---------------------------------------------------------------------------

_LEFT = r"(?<![0-9A-Za-z])(?<!\d-)"
_RIGHT = r"(?![0-9A-Za-z])"

_ANOTHER_CITATION_AHEAD = (
    r"(?!\s*(?:U\.?\s*S\.?\s*C|C\.?\s*F\.?\s*R|Stat\b|FR\b|Fed\.?\s?Reg"
    r"|U\.?\s?S\.?\s?T\b|U\.?\s?N\.?\s?T\.?\s?S\b|T\.?\s?I\.?\s?A\.?\s?S\b"
    r"|U\.\s?S\.\s*\d|S\.\s?Ct\b|F\.?\s?(?:2d|3d|4th)\b|F\.?\s?Supp\b|Cl\.?\s?Ct\b))"
)

_DOT_TRUNCATION_SIGNATURE = rf"\.{_ATOMIC}\d+)(?!\s*C\.?\s*F\.?\s*R\.?{_RIGHT})"
_A_DOTTED_NUMBER_IS_A_CFR_SECTION = rf"(?!{_DOT_TRUNCATION_SIGNATURE})"
_DOT_TRUNCATES_A_SECTION_RE = re.compile(_DOT_TRUNCATION_SIGNATURE)

_SECTION_MARKER = r"(?:sec(?:tion)?s?\.?(?![A-Za-z])|§{1,2})"
_LIST_SEPARATOR = r"\s*(?:,\s*(?:and\s+)?|and\s+)"
_RANGE_SEPARATOR = r"\s*(?:to|through|thru)\s*"
_SPACED_DASH = r"\s+-\s+"
_LOOSE_DASH = r"(?:\s*--\s*|\s+-\s*|\s*-\s+)"
_CITATION_PARAGRAPH_BREAK = re.compile(r"\r?\n[ \t]*\r?\n")

_MONTH_NAME = (
    r"(?<![A-Za-z])(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_SPELLED_DATE = re.compile(rf"{_MONTH_NAME}\.?\s+\d{{1,2}}\s*,\s*(?:1[789]|20)\d{{2}}", re.IGNORECASE)
_ACT_NAMED_YEAR = re.compile(r"\bAct\s*,\s*(?:1[789]|20)\d{2}", re.IGNORECASE)
_RIN_TOKEN = re.compile(r"(?<![0-9A-Za-z])\d{4}-[A-Z]{2}\d{2}(?![0-9A-Za-z])")

# --- U.S.C. Grammar ---
_USC_CODE_NAME = r"U\.?\s*S\.?\s*(?:Code\b|C\.?(?:\s*[AS]\.?)?)"
_ONE_REPEATED_LETTER = "(?:" + "|".join(f"[{low}{low.upper()}]+" for low in ascii_lowercase) + ")"
_USC_SECTION_TOKEN = rf"\d+(?:{_ONE_REPEATED_LETTER}(?![A-Za-z]))?"
_USC_SECTION_SPAN = rf"{_USC_SECTION_TOKEN}(?:-{_USC_SECTION_TOKEN}|-[ \t]{_ATOMIC}{_USC_SECTION_TOKEN})(?!-\d))?"
_USC_SECTION_SPAN_UNTRUNCATED = (
    rf"{_USC_SECTION_TOKEN}-{_USC_SECTION_TOKEN}"
    rf"|{_USC_SECTION_TOKEN}-[ \t]{_ATOMIC}{_USC_SECTION_TOKEN})(?!-\d)"
    rf"|{_ATOMIC}{_USC_SECTION_TOKEN}){_A_DOTTED_NUMBER_IS_A_CFR_SECTION}"
)
_APPENDIX_MARKER = r"(?i:app(?:endix|x?\.?)?)"

_USC_STANDARD = re.compile(
    rf"{_LEFT}(?P<title>\d+)\.?\s*{_USC_CODE_NAME}"
    r"(?:\s*subtitles?\s+[IVXLC]+\s*,?)?"
    rf"(?:\s*{_SECTION_MARKER})?\s*"
    rf"(?P<section>{_USC_SECTION_SPAN})"
    rf"(?:(?:\s*\([0-9A-Za-z]{{1,4}}\))*(?:{_RANGE_SEPARATOR}|{_SPACED_DASH}|{_LOOSE_DASH})"
    rf"(?P<range_end>{_ATOMIC}{_USC_SECTION_SPAN}))"
    rf"{_ANOTHER_CITATION_AHEAD})?",
    re.IGNORECASE,
)
_USC_SECTION_FIRST = re.compile(
    rf"{_LEFT}(?i:section|sec)\.?[ \t]+(?P<section>{_USC_SECTION_SPAN_UNTRUNCATED})"
    rf"(?:\([0-9A-Za-z]{{1,4}}\))*[ \t]+(?i:of)[ \t]+(?P<title>\d+)[ \t]+"
    rf"{_USC_CODE_NAME}(?![A-Za-z_])"
)
_INTERNAL_REVENUE_CODE = re.compile(
    rf"\bI\.?\s*R\.?\s*C\.?(?:\s*{_SECTION_MARKER})?\s*(?P<section>{_USC_SECTION_SPAN})",
    re.IGNORECASE,
)
_USC_APPENDIX = re.compile(
    rf"{_LEFT}(?P<title>\d+)\s*"
    rf"(?:{_USC_CODE_NAME}\s*(?:§{{1,2}}\s*)?{_APPENDIX_MARKER}|{_APPENDIX_MARKER}\s*{_USC_CODE_NAME})\s*"
    rf"(?P<section>{_USC_SECTION_SPAN_UNTRUNCATED})?"
)
_USC_TRANSPOSED_LABEL = re.compile(
    rf"{_LEFT}(?P<title>\d{{1,2}})\s+UCS\s+(?P<section>{_USC_SECTION_SPAN_UNTRUNCATED})"
)
# Includes TRAP_5 fix: optional subsection pinpoint `(?:\([0-9A-Za-z]{1,4}\))*` before `\s+of\s+title`!
_USC_TITLE_FORM = re.compile(
    rf"{_LEFT}{_SECTION_MARKER}\s*"
    rf"(?P<first>{_USC_SECTION_SPAN_UNTRUNCATED})(?P<pin>(?:\([0-9A-Za-z]{{1,4}}\))*)"
    rf"(?P<items>(?:{_LIST_SEPARATOR}{_USC_SECTION_TOKEN}(?:\([0-9A-Za-z]{{1,4}}\))*{_A_DOTTED_NUMBER_IS_A_CFR_SECTION})*)"
    rf"\s+of\s+title\s+(?P<title>[1-9]\d*){_RIGHT}",
    re.IGNORECASE,
)
_USC_TITLE_FORM_ITEM = re.compile(
    rf"{_LIST_SEPARATOR}(?P<section>{_USC_SECTION_TOKEN})(?:\([0-9A-Za-z]{{1,4}}\))*{_A_DOTTED_NUMBER_IS_A_CFR_SECTION}"
)
_USC_LIST_TAIL = re.compile(
    rf"(?:,|\band\b|\bor\b)\s*(?P<section>{_USC_SECTION_SPAN_UNTRUNCATED})\b"
    rf"{_ANOTHER_CITATION_AHEAD}"
    rf"(?:(?:\s*\([0-9A-Za-z]{{1,4}}\))*(?:{_RANGE_SEPARATOR}|{_SPACED_DASH}|{_LOOSE_DASH})"
    rf"(?P<range_end>{_ATOMIC}{_USC_SECTION_SPAN}))"
    rf"{_ANOTHER_CITATION_AHEAD})?",
    re.IGNORECASE,
)
# Positive-law U.S.C. amendatory new-section addition (`Chapter 83 of title 41, United States Code, is amended ... "§ 8302A.`)
_USC_AMEND_NEW_SEC_RE = re.compile(
    r"\b(?:Chapter|Subchapter|Part|Subtitle)\s+[0-9A-Za-z-]+\s+of\s+title\s+(?P<title>[1-9]\d?),\s+United\s+States\s+Code,\s+is\s+amended\b[^.]{0,140}?[\"“‘']*§\s*(?P<sec>\d+[A-Za-z0-9-]*)",
    re.I,
)
_IRC_LONGHAND_RE = re.compile(
    r"\b(?:Internal\s+Revenue\s+Code(?:\s+of\s+(?:1986|1954))?)\s*,?\s*(?:§+|sec(?:tion)?\.?)\s*(?P<sec>[1-9]\d*[A-Za-z]?)"
    r"|\b(?:§+|sec(?:tion)?\.?)\s*(?P<sec2>[1-9]\d*[A-Za-z]?)(?:\([0-9A-Za-z]{1,4}\))*\s+of\s+the\s+(?:I\.?\s*R\.?\s*C\.?|Internal\s+Revenue\s+Code(?:\s+of\s+(?:1986|1954))?)\b",
    re.I,
)
_USC_APP_BARE_RE = re.compile(
    r"\b(?P<title>5|10|11|18|26|28|38|40|46|50)\s+U\.?\s*S\.?\s*C\.?\s+App(?:endix|\.)?(?!\s*\d)",
    re.I,
)
_USC_DAMAGED_COORD_TAIL_RE = re.compile(r"(?:\d+|-[A-Za-z]+\d+)(?!\w)")
_USC_SECTION_ATOM_RE = re.compile(r"^(?P<number>\d+)(?P<suffix>[a-z]*)$")


def _usc_title_is_possible(title: int | None) -> bool:
    return title is not None and 1 <= title <= USC_TITLE_COUNT_V6 and title not in USC_RESERVED_TITLES_V6


def _usc_clean_sec(raw: str | None) -> str | None:
    if not raw:
        return None
    s = _normalize_dashes(raw).replace(" ", "").replace("\t", "").strip()
    s = re.sub(r"\([^)]*\)", "", s).strip(".")
    return s.lower() if s else None


def _usc_section_order(sec: str | None) -> tuple[int, str] | None:
    if not sec or "-" in sec:
        return None
    m = _USC_SECTION_ATOM_RE.match(sec.lower())
    return (int(m.group("number")), m.group("suffix")) if m else None


def _abbreviated_span(token: str) -> tuple[str, str] | None:
    if token.count("-") != 1:
        return None
    left, right = token.split("-")
    if not (left.isdigit() and right.isdigit() and len(right) >= 2 and len(right) < len(left)):
        return None
    expanded = left[: len(left) - len(right)] + right
    if 0 < int(expanded) - int(left) < 100:
        return left, expanded
    return None


def _usc_split_span(section: str | None, range_end: str | None = None) -> tuple[str | None, str | None, str | None]:
    sec = _usc_clean_sec(section)
    rend = _usc_clean_sec(range_end)
    if not sec:
        return None, None, None
    if rend is not None:
        start, end = sec, rend
    elif sec.count("-") == 1:
        start, end = sec.split("-")
    else:
        return sec, None, None
    lo, hi = _usc_section_order(start), _usc_section_order(end)
    if lo is not None and hi is not None and lo < hi:
        return start, end, "stated"
    exp = _abbreviated_span(sec if rend is None else f"{start}-{end}")
    if exp is not None:
        return exp[0], exp[1], "abbreviated"
    return sec, None, None


@dataclass(frozen=True)
class UscHitV6:
    title: int
    section: str
    section_end: str | None
    span_rule: str | None
    appendix: bool
    is_irc: bool
    start: int
    end: int
    matched_text: str


def find_usc_citations_v6(text: str, *, allow_proposed_amendatory: bool = False) -> tuple[UscHitV6, ...]:
    """Prose-bounded U.S.C. + I.R.C. citation scanner with `spicy-docs` / `RefSpec` fences."""
    if not text:
        return ()
    norm = _normalize_dashes(text)
    hits: list[UscHitV6] = []
    covered_spans: list[tuple[int, int]] = []

    def _overlaps(s: int, e: int) -> bool:
        return any(not (e <= cs or s >= ce) for cs, ce in covered_spans)

    # 1. Appendix form first (so `50 U.S.C. App. 2401` keeps appendix=True)
    for m in _USC_APPENDIX.finditer(norm):
        title = int(m.group("title"))
        if not _usc_title_is_possible(title):
            continue
        raw_sec = m.group("section")
        if raw_sec:
            if _USC_DAMAGED_COORD_TAIL_RE.match(norm, m.end("section")):
                continue
            sec, sec_end, srule = _usc_split_span(raw_sec)
            if sec:
                hits.append(UscHitV6(title, sec, sec_end, srule, True, False, m.start(), m.end(), text[m.start() : m.end()]))
                covered_spans.append((m.start(), m.end()))
        elif title in APPENDIX_TITLES_PUBLISHED_V6:
            hits.append(UscHitV6(title, "App.", None, None, True, False, m.start(), m.end(), text[m.start() : m.end()]))
            covered_spans.append((m.start(), m.end()))

    # 2. Standard, Section-First, IRC, and Transposed UCS forms
    for pat, fixed_title, is_irc_pat in (
        (_USC_STANDARD, None, False),
        (_USC_SECTION_FIRST, None, False),
        (_INTERNAL_REVENUE_CODE, 26, True),
        (_USC_TRANSPOSED_LABEL, None, False),
    ):
        for m in pat.finditer(norm):
            if _overlaps(m.start(), m.end()):
                continue
            title = fixed_title if fixed_title is not None else int(m.group("title"))
            if not _usc_title_is_possible(title):
                continue
            # Left token boundary check
            if m.start() > 0 and norm[m.start()].isalnum() and (norm[m.start() - 1].isalnum() or norm[m.start() - 1] == "_"):
                continue
            sec_raw = m.group("section")
            # Dot truncation fence (`26 USC 1.104-1` is a CFR typo, not 26 U.S.C. 1!)
            if "-" not in sec_raw and _DOT_TRUNCATES_A_SECTION_RE.match(norm, m.end("section")):
                continue
            if _USC_DAMAGED_COORD_TAIL_RE.match(norm, m.end("section")):
                continue
            rend_raw = m.groupdict().get("range_end")
            sec, sec_end, srule = _usc_split_span(sec_raw, rend_raw)
            if not sec:
                continue
            hits.append(
                UscHitV6(title, sec, sec_end, srule, False, is_irc_pat, m.start(), m.end(), text[m.start() : m.end()])
            )
            covered_spans.append((m.start(), m.end()))

            # Prose-adjacent list tail walk (`42 U.S.C. 1395, 1396`) stopping at paragraph break, RIN, date, or other cite
            if pat is _USC_STANDARD:
                pos = m.end()
                # Skip adjacent subsection pinpoints like `(b)(1)(A)`
                while True:
                    pm = re.match(r"[ \t]*\([0-9A-Za-z]{1,4}\)", norm[pos:])
                    if not pm:
                        break
                    pos += pm.end()
                while True:
                    # Refuse date/act-year commas or RIN tokens immediately ahead
                    if _SPELLED_DATE.match(norm, max(0, pos - 20)) or _ACT_NAMED_YEAR.match(norm, max(0, pos - 12)):
                        break
                    lm = _USC_LIST_TAIL.match(norm, pos)
                    if lm is None or _CITATION_PARAGRAPH_BREAK.search(norm, pos, lm.end()):
                        break
                    if _RIN_TOKEN.match(norm, lm.start("section")):
                        break
                    if _USC_DAMAGED_COORD_TAIL_RE.match(norm, lm.end("section")):
                        break
                    lsec, lrend, lsrule = _usc_split_span(lm.group("section"), lm.group("range_end"))
                    if lsec:
                        hits.append(
                            UscHitV6(
                                title,
                                lsec,
                                lrend,
                                lsrule,
                                False,
                                False,
                                lm.start("section"),
                                lm.end(),
                                text[lm.start("section") : lm.end()],
                            )
                        )
                    pos = lm.end()
                    while True:
                        pm = re.match(r"[ \t]*\([0-9A-Za-z]{1,4}\)", norm[pos:])
                        if not pm:
                            break
                        pos += pm.end()

    # 3. `section X(c) of title Y` form (with TRAP_5 pinpoint support)
    for m in _USC_TITLE_FORM.finditer(norm):
        if _overlaps(m.start(), m.end()):
            continue
        title = int(m.group("title"))
        if not _usc_title_is_possible(title):
            continue
        sec, sec_end, srule = _usc_split_span(m.group("first"))
        if sec:
            hits.append(UscHitV6(title, sec, sec_end, srule, False, False, m.start(), m.end(), text[m.start() : m.end()]))
        if m.group("items"):
            for im in _USC_TITLE_FORM_ITEM.finditer(m.group("items")):
                isec, _, _ = _usc_split_span(im.group("section"))
                if isec:
                    hits.append(UscHitV6(title, isec, None, None, False, False, m.start(), m.end(), text[m.start() : m.end()]))
        covered_spans.append((m.start(), m.end()))

    # 4. Longhand IRC mentions (`Internal Revenue Code Section 6103` / `Section 6103 of the IRC`)
    for m in _IRC_LONGHAND_RE.finditer(norm):
        if _overlaps(m.start(), m.end()):
            continue
        sec = _usc_clean_sec(m.group("sec") or m.group("sec2"))
        if sec:
            hits.append(UscHitV6(26, sec, None, None, False, True, m.start(), m.end(), text[m.start() : m.end()]))
            covered_spans.append((m.start(), m.end()))

    # 5. Bare published Appendix (`5 U.S.C. App.`) when not already covered
    for m in _USC_APP_BARE_RE.finditer(norm):
        if not _overlaps(m.start(), m.end()):
            hits.append(UscHitV6(int(m.group("title")), "App.", None, None, True, False, m.start(), m.end(), text[m.start() : m.end()]))

    # 6. Proposed new U.S.C. section in positive-law amendatory bills/amendments (`TRAP_1` companion)
    if allow_proposed_amendatory:
        for m in _USC_AMEND_NEW_SEC_RE.finditer(norm):
            title = int(m.group("title"))
            sec = _usc_clean_sec(m.group("sec"))
            if _usc_title_is_possible(title) and sec:
                hits.append(UscHitV6(title, sec, None, None, False, False, m.start(), m.end(), text[m.start() : m.end()]))

    hits.sort(key=lambda h: (h.start, h.end))
    return tuple(hits)


# --- CFR Grammar (with 3 CFR Compilation Diversion & Heading-Dash Fix) ---
_COMPILATION_YEAR = r"(?:1[789]|20)\d{2}"
_COMPILATION_WORD = r"(?:Comp|Supp)\.?(?!\w)"
_EO_COMPILATION_RE = re.compile(
    rf"\b3\s*C\.?\s*F\.?\s*R\.?\s*[,;:]?\s*(?:parts\s+)?"
    rf"(?:\d+(?:\s*-\s*\d+)?\s*\(\s*)?"
    rf"(?:{_COMPILATION_YEAR}\s*,\s*(?={_COMPILATION_YEAR}\s*,?\s*{_COMPILATION_WORD}))?"
    rf"{_COMPILATION_YEAR}"
    rf"(?:\s*(?:(?:-\s*){{1,2}}|/|to|thru|through|and)\s*(?:{_COMPILATION_YEAR}|\d{{4}}(?=\s*,?\s*{_COMPILATION_WORD})|\d{{2}}(?!\d))\s*,?\s*(?:{_COMPILATION_WORD})?"
    rf"|\s*,?\s*{_COMPILATION_WORD}"
    rf"|(?=\s*,?\s*(?:pp?\.?|pages?)\s*\d))"
    rf"(?:\s*\)|(?:\s*,?\s*(?:pp?\.?|pages?)?\s*\d+(?!\w)(?:\s*-\s*\d+(?!\w))?{_ANOTHER_CITATION_AHEAD})?)",
    re.IGNORECASE,
)

_CFR_HEADING_DASH = r"-{1,2}[ \t]*(?:\r?\n[ \t]*)?(?-i:[A-Z][a-z])"
_CFR_SECTION_CAPTURE = rf"[A-Za-z0-9](?:(?:(?!{_CFR_HEADING_DASH})[A-Za-z0-9.-])*[A-Za-z0-9])?"
_CFR_PART_CAPTURE = rf"\d+[A-Za-z]?(?:-[ \t]?\d+[A-Za-z]?)*(?:(?![\w-])|(?={_CFR_HEADING_DASH}))"
_CFR_UNIT_LABEL = rf"(?:parts?|pts?\.?|{_SECTION_MARKER})"

_CFR_STANDARD_RE = re.compile(
    rf"{_LEFT}(?P<title>\d+)\s*C\.?\s*F\.?\s*R\.?(?![A-Za-z_])"
    rf"\s*(?:,\s*(?={_CFR_UNIT_LABEL}))?(?P<label>{_CFR_UNIT_LABEL})?\s*"
    rf"(?P<part>{_CFR_PART_CAPTURE})(?:\.(?P<section>{_CFR_SECTION_CAPTURE}))?"
    rf"(?![\w]|\.[A-Za-z0-9]){_ANOTHER_CITATION_AHEAD}",
    re.IGNORECASE,
)
_CFR_LONGHAND_FWD_RE = re.compile(
    rf"{_LEFT}title\s+(?P<title>\d+),?\s+Code\s+of\s+Federal\s+Regulations\s*,\s*(?P<label>{_CFR_UNIT_LABEL})\s*"
    rf"(?P<part>{_CFR_PART_CAPTURE})(?:\.(?P<section>{_CFR_SECTION_CAPTURE}))?",
    re.IGNORECASE,
)
_CFR_LONGHAND_REV_RE = re.compile(
    rf"{_LEFT}(?P<label>{_CFR_UNIT_LABEL})\s*(?P<part>{_CFR_PART_CAPTURE})(?:\.(?P<section>{_CFR_SECTION_CAPTURE}))?"
    rf"(?:\([0-9A-Za-z]{{1,4}}\))*\s+of\s+title\s+(?P<title>\d+)\s*,?\s*(?:C\.?\s*F\.?\s*R\.?|Code\s+of\s+Federal\s+Regulations)\b",
    re.IGNORECASE,
)
_CFR_PLURAL_TAIL_RE = re.compile(
    rf"{_LIST_SEPARATOR}(?P<part>{_CFR_PART_CAPTURE})(?:\.(?P<section>{_CFR_SECTION_CAPTURE}))?(?![\w]|\.[A-Za-z0-9]){_ANOTHER_CITATION_AHEAD}",
    re.IGNORECASE,
)
_CFR_RANGE_TAIL_RE = re.compile(
    rf"\s+(?:(?i:to|through)\b\s*|-\s+)(?P<part>{_CFR_PART_CAPTURE})(?:\.(?P<section>{_CFR_SECTION_CAPTURE}))?(?![\w]|\.[A-Za-z0-9]){_ANOTHER_CITATION_AHEAD}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CfrHitV6:
    title: int
    part: str
    section: str | None
    start: int
    end: int


def _cfr_valid(title: int, part: str) -> bool:
    if not (1 <= title <= CFR_TITLE_COUNT_V6 and title not in CFR_RESERVED_TITLES_V6):
        return False
    digits = re.match(r"^\d+", part)
    return digits is not None and len(digits.group(0)) <= 5


def find_cfr_citations_v6(text: str) -> tuple[CfrHitV6, ...]:
    """Prose-bounded CFR part & section scanner excising `3 CFR ... Comp.` EO locators."""
    if not text:
        return ()
    norm = _normalize_dashes(text)
    excised = _EO_COMPILATION_RE.sub(lambda m: " " * (m.end() - m.start()), norm)
    hits: list[CfrHitV6] = []

    def _emit_coord(title: int, part_raw: str, sec_raw: str | None, plural: bool, s: int, e: int) -> None:
        part = re.sub(r"\s+", "", part_raw).lstrip("0") or "0"
        if "-" in part and sec_raw is None:
            if plural and re.fullmatch(r"\d+-\d+", part):
                p1, p2 = part.split("-")
                for ep in (p1.lstrip("0") or "0", p2.lstrip("0") or "0"):
                    if _cfr_valid(title, ep):
                        hits.append(CfrHitV6(title, ep, None, s, e))
                return
            if not (title == 41 and re.fullmatch(r"\d+-\d+", part)):
                return
        if sec_raw and re.search(r"-\d+\.", sec_raw):
            return
        if _cfr_valid(title, part):
            hits.append(CfrHitV6(title, part, sec_raw, s, e))

    for pat in (_CFR_STANDARD_RE, _CFR_LONGHAND_FWD_RE, _CFR_LONGHAND_REV_RE):
        for m in pat.finditer(excised):
            title = int(m.group("title"))
            lbl = m.group("label") or ""
            plural = lbl == "§§" or lbl.rstrip(".").lower().endswith("s")
            # Reverse section label requires dotted section
            if pat is _CFR_LONGHAND_REV_RE and re.fullmatch(_SECTION_MARKER, lbl, re.I) and not m.group("section"):
                continue
            _emit_coord(title, m.group("part"), m.group("section"), plural, m.start(), m.end())
            pos = m.end()
            # Range endpoint (`40 CFR parts 60 through 63`)
            rm = _CFR_RANGE_TAIL_RE.match(excised, pos)
            if rm and not _CITATION_PARAGRAPH_BREAK.search(excised, pos, rm.end()):
                _emit_coord(title, rm.group("part"), rm.group("section"), False, m.start(), rm.end())
                pos = rm.end()
            elif plural and pat is not _CFR_LONGHAND_REV_RE:
                while True:
                    tm = _CFR_PLURAL_TAIL_RE.match(excised, pos)
                    if not tm or _CITATION_PARAGRAPH_BREAK.search(excised, pos, tm.end()):
                        break
                    _emit_coord(title, tm.group("part"), tm.group("section"), True, tm.start("part"), tm.end())
                    pos = tm.end()

    hits.sort(key=lambda h: (h.start, h.end))
    return tuple(hits)


# --- Public Laws, Statutes at Large & Federal Register ---
_PUBLIC_LAW_LEFT = rf"(?:{_LEFT}|(?m:^[ \t]*\d+-))"
_PUBLIC_LAW_RE = re.compile(
    rf"{_PUBLIC_LAW_LEFT}(?P<label>pub(?:lic)?\.?\s*l(?:aw)?\.?|p\.?\s*l\.?)[\s-]*(?:no\.?:?\s*)?"
    rf"0*(?P<congress>[1-9]\d*)(?:\s*-\s*){{1,2}}0*(?P<number>[1-9]\d*){_RIGHT}",
    re.IGNORECASE,
)
_PUBLIC_LAW_DOT_RE = re.compile(
    rf"{_PUBLIC_LAW_LEFT}(?P<label>pub(?:lic)?\.?\s*l(?:aw)?\.?|p\.?\s*l\.?)\s*(?:no\.?\s*)?"
    rf"(?P<congress>[1-9]\d{{1,2}})\.(?P<number>[1-9]\d{{0,2}})(?![.\-]?\d)",
    re.IGNORECASE,
)
_STATUTE_LETTERED_PAGE_RE = re.compile(
    rf"{_LEFT}(?P<volume>[1-9]\d{{0,3}})\s*Stat\.?\s*(?P<base>[1-9]\d{{0,3}}[A-Za-z])\s*[-,]\s*-?(?P<leaf>\d{{1,4}})"
    r"(?:\s*(?:to|through|-)\s*(?:(?P<end_base>[1-9]\d{0,3}[A-Za-z])\s*[-,]\s*)?-?(?P<leaf_end>\d{1,4})(?![0-9A-Za-z]))?"
)
_STATUTE_LETTERED_VOL_RE = re.compile(
    rf"{_LEFT}(?P<volume>[1-9]\d{{0,2}}[A-Z])\s*Stat(?:utes?|ue)?\.{{0,2}}\s*(?P<page>[1-9]\d{{0,4}}){_RIGHT}"
)
_STATUTE_AT_LARGE_RE = re.compile(
    rf"{_LEFT}(?P<volume>[1-9]\d{{0,3}})\s*Stat(?:utes?|ue)?\.{{0,2}}\s*(?P<page>[1-9]\d{{0,4}})(?:{_RIGHT}|(?=as\s+amended\b))"
)
_PUBLIC_LAW_TO_STATUTE_RE = re.compile(rf"[\s,;:()\[\]]*(?:(?:{_SPELLED_DATE.pattern})[\s,;:()\[\]]*)?", re.IGNORECASE)

_FR_CITATION_RE = re.compile(
    rf"{_LEFT}(?P<volume>[1-9]\d{{0,2}})\s*-?\s*(?:FR|F[Ee][Dd]\.?\s?R[Ee][Gg]\.?)\s*-?\s*"
    rf"(?P<page>\d{{1,3}},\d{{3}}(?!\d|,\d)|\d{{1,6}}(?!,\d{{3}}(?!\d))){_RIGHT}"
)


def _statutes_volume_matches_congress(congress: int | None, volume: int | None) -> bool | None:
    if congress is None or volume is None:
        return None
    if not (PL_FIRST_NUMBERED_CONGRESS_V6 <= congress <= CONGRESS_CURRENT_V6):
        return None
    if congress < 74:
        return congress - 26 <= volume <= congress - 24
    return 2 * congress - 100 <= volume <= 2 * congress - 97


@dataclass(frozen=True)
class PublicLawHitV6:
    congress: int
    number: int
    start: int
    end: int


@dataclass(frozen=True)
class StatuteHitV6:
    volume: str
    page: str
    matches_adjacent_pl: bool | None
    adjacent_pl_exists: bool
    start: int
    end: int


@dataclass(frozen=True)
class FederalRegisterHitV6:
    volume: int
    page: int
    start: int
    end: int


def find_public_law_citations_v6(text: str) -> tuple[PublicLawHitV6, ...]:
    if not text:
        return ()
    norm = _normalize_dashes(text)
    out: list[PublicLawHitV6] = []
    for pat in (_PUBLIC_LAW_RE, _PUBLIC_LAW_DOT_RE):
        for m in pat.finditer(norm):
            c_n, l_n = int(m.group("congress")), int(m.group("number"))
            if c_n >= PL_FIRST_NUMBERED_CONGRESS_V6:
                out.append(PublicLawHitV6(c_n, l_n, m.start("label"), m.end()))
    out.sort(key=lambda x: (x.start, x.end))
    return tuple(out)


def find_statute_citations_v6(text: str) -> tuple[StatuteHitV6, ...]:
    if not text:
        return ()
    norm = _normalize_dashes(text)
    pl_matches = sorted(
        [m for pat in (_PUBLIC_LAW_RE, _PUBLIC_LAW_DOT_RE) for m in pat.finditer(norm)],
        key=lambda m: m.end(),
    )
    pl_ends = [m.end() for m in pl_matches]

    def _beside_congress(stat_start: int) -> tuple[int | None, bool]:
        beside = []
        latest_s = -1
        for idx in range(bisect_right(pl_ends, stat_start) - 1, -1, -1):
            pm = pl_matches[idx]
            if pm.end() <= latest_s:
                break
            if _PUBLIC_LAW_TO_STATUTE_RE.fullmatch(norm, pm.end(), stat_start):
                beside.append(pm)
            latest_s = max(latest_s, pm.start())
        if len(beside) == 1:
            return int(beside[0].group("congress")), True
        return None, bool(beside)

    out: list[StatuteHitV6] = []
    covered: list[tuple[int, int]] = []
    for m in _STATUTE_LETTERED_PAGE_RE.finditer(norm):
        vol_i = int(m.group("volume"))
        base, leaf = m.group("base").upper(), m.group("leaf")
        adj_c, adj_ok = _beside_congress(m.start())
        verdict = _statutes_volume_matches_congress(adj_c, vol_i)
        out.append(StatuteHitV6(str(vol_i), f"{base}-{leaf}", verdict, adj_ok, m.start(), m.end()))
        covered.append((m.start(), m.end()))
    for m in _STATUTE_LETTERED_VOL_RE.finditer(norm):
        if any(not (m.end() <= cs or m.start() >= ce) for cs, ce in covered):
            continue
        out.append(StatuteHitV6(m.group("volume").upper(), str(int(m.group("page"))), None, False, m.start(), m.end()))
        covered.append((m.start(), m.end()))
    for m in _STATUTE_AT_LARGE_RE.finditer(norm):
        if any(not (m.end() <= cs or m.start() >= ce) for cs, ce in covered):
            continue
        vol_i = int(m.group("volume"))
        adj_c, adj_ok = _beside_congress(m.start())
        verdict = _statutes_volume_matches_congress(adj_c, vol_i)
        out.append(StatuteHitV6(str(vol_i), str(int(m.group("page"))), verdict, adj_ok, m.start(), m.end()))
    out.sort(key=lambda x: (x.start, x.end))
    return tuple(out)


def find_federal_register_citations_v6(text: str) -> tuple[FederalRegisterHitV6, ...]:
    if not text:
        return ()
    norm = _normalize_dashes(text)
    out = [
        FederalRegisterHitV6(int(m.group("volume")), int(m.group("page").replace(",", "")), m.start(), m.end())
        for m in _FR_CITATION_RE.finditer(norm)
    ]
    return tuple(out)


# ---------------------------------------------------------------------------
# Bills (`citations.py:bill_number` v006 + Pipe-OCR Fix & ALL-CAPS Res Support)
# ---------------------------------------------------------------------------

BILL_TYPES_BY_LENGTH_V6: tuple[str, ...] = ("hconres", "sconres", "hjres", "sjres", "hres", "sres", "hr", "s")
BILL_DISPLAY_MAP_V6: Mapping[str, str] = {
    "hr": "H.R.",
    "s": "S.",
    "hres": "H. Res.",
    "sres": "S. Res.",
    "hjres": "H.J. Res.",
    "sjres": "S.J. Res.",
    "hconres": "H. Con. Res.",
    "sconres": "S. Con. Res.",
}

_BILL_SPLIT_RE = re.compile(r"^([A-Z]+)(\d+)$")
_CONGRESS_CHAMBER_V6 = (
    r"(?<![A-Za-z]\.)(?<!U\.\s)(?<![A-Za-z])"
    r"(?:H\.?\s?R|H\.?\s?J\.?\s?(?:Res|RES)|H\.?\s?(?:Con|CON)\.?\s?(?:Res|RES)|H\.?\s?(?:Res|RES)"
    r"|S\.?\s?J\.?\s?(?:Res|RES)|S\.?\s?(?:Con|CON)\.?\s?(?:Res|RES)|S\.?\s?(?:Res|RES)|S)"
)
# Refuses `(`, `|` (OCR-corrupted trailing digit '1' on H.R.39|), and `YYYY:` line headings
_BILL_NUMBER_END_V6 = r"\b(?![|(])(?!(?<=\n(?:19|20)\d\d):)"
_BILL_NUMBER_RE_V6 = re.compile(rf"{_CONGRESS_CHAMBER_V6}[.\s]\s?[1-9]\d{{0,4}}{_BILL_NUMBER_END_V6}")
_BILL_PLURAL_LIST_RE_V6 = re.compile(
    r"(?<![A-Za-z]\.)(?<!U\.\s)(?<![A-Za-z])"
    r"(?P<desig>H\.?\s?R\.?|S\.?)\s*(?P<n1>[1-9]\d{0,4})\s+and\s+(?P<n2>[1-9]\d{0,4})\b(?![|(])"
)
_INLINE_CONGRESS_RE = re.compile(
    r"(?:,\s*|\s+(?:of|in)\s+the\s+)(?P<congress>\d{1,3})(?:st|nd|rd|th|d)\s+Cong(?:ress\b|\.)"
    r"|[ \t]*\(\s*(?P<parenthesized>\d{1,3})(?:st|nd|rd|th|d)\s+Cong(?:ress|\.)\s*\)"
)
_BILL_LIST_JOIN_RE = re.compile(r"\s+and\s+|\s*/\s*")

_UNNUMBERED_DRAFT_RE = re.compile(
    r"\(Original\s+Signature\s+of\s+Member\)|\[DISCUSSION\s+DRAFT\]|M_\.\s*_{2,}\s+introduced",
    re.I,
)
_FILENAME_AMDT_BILL_RE = re.compile(
    r"(?:^|/)BILLS-(?P<cong>\d{2,3})-(?P<btype>HR|S|HRes|SRes|HJRes|SJRes|HConRes|SConRes)?(?P<num>[1-9]\d{0,4})-[A-Z]\d{6}-Amdt-",
    re.I,
)
_FILENAME_EXPLICIT_BILL_RE = re.compile(
    r"(?:^|[-_])(?P<btype>h\.r\.|s\.|h\.res\.|s\.res\.|h\.con\.res\.|s\.con\.res\.|h\.j\.res\.|s\.j\.res\.)[-_]?(?P<num>[1-9]\d{0,4})(?:[-_.]|$)",
    re.I,
)


def bill_type_and_number_v6(value: str) -> tuple[str, str] | None:
    alnum = re.sub(r"[^A-Z0-9]", "", (value or "").upper())
    m = _BILL_SPLIT_RE.fullmatch(alnum)
    if m is None:
        return None
    letters, num = m.group(1).lower(), str(int(m.group(2)))
    kind = next((name for name in BILL_TYPES_BY_LENGTH_V6 if letters == name), None)
    return (kind, num) if kind is not None else None


@dataclass(frozen=True)
class BillHitV6:
    bill_type: str
    number: str
    congress: int | None
    display_ref: str
    source: str


def find_bill_citations_v6(
    text: str,
    *,
    filename: str = "",
    congress: int | None = None,
    measure_keys: Sequence[str] | None = None,
) -> tuple[BillHitV6, ...]:
    """Extract Congressional bill citations from prose (with strict official-slug fallback when text omits the number)."""
    norm = _normalize_dashes(text or "")
    matches = [(m.group(0), m.start(), m.end()) for m in _BILL_NUMBER_RE_V6.finditer(norm)]
    spans = [(s, e) for _, s, e in matches]

    inline_cong: dict[int, int] = {}
    carried: int | None = None
    for idx in range(len(spans) - 1, -1, -1):
        s, e = spans[idx]
        qm = _INLINE_CONGRESS_RE.match(norm, e)
        if qm is not None:
            carried = int(qm.group("congress") or qm.group("parenthesized"))
        elif carried is None or not _BILL_LIST_JOIN_RE.fullmatch(norm, e, spans[idx + 1][0]):
            carried = None
        if carried is not None:
            inline_cong[s] = carried

    out: list[BillHitV6] = []
    seen: set[tuple[str, str]] = set()
    for matched_s, s, _ in matches:
        bt = bill_type_and_number_v6(matched_s)
        if bt is None:
            continue
        btype, bnum = bt
        if (btype, bnum) not in seen:
            seen.add((btype, bnum))
            c_val = inline_cong.get(s, congress)
            out.append(BillHitV6(btype, bnum, c_val, f"bill:{BILL_DISPLAY_MAP_V6[btype]} {bnum}", "prose"))

    for pm in _BILL_PLURAL_LIST_RE_V6.finditer(norm):
        bt = bill_type_and_number_v6(f"{pm.group('desig')} {pm.group('n1')}")
        if bt is None:
            continue
        btype = bt[0]
        for n_raw in (pm.group("n1"), pm.group("n2")):
            bnum = str(int(n_raw))
            if (btype, bnum) not in seen:
                seen.add((btype, bnum))
                out.append(BillHitV6(btype, bnum, congress, f"bill:{BILL_DISPLAY_MAP_V6[btype]} {bnum}", "prose_plural"))

    # Strict filename / measure_keys fallback ONLY when prose had 0 bills and doc is NOT an unnumbered signature draft
    if not out and not _UNNUMBERED_DRAFT_RE.search(norm):
        m_amdt = _FILENAME_AMDT_BILL_RE.search(filename or "")
        if m_amdt:
            btype = (m_amdt.group("btype") or "hr").lower()
            bnum = str(int(m_amdt.group("num")))
            c_val = int(m_amdt.group("cong"))
            if btype in BILL_DISPLAY_MAP_V6 and (btype, bnum) not in seen:
                seen.add((btype, bnum))
                out.append(BillHitV6(btype, bnum, c_val, f"bill:{BILL_DISPLAY_MAP_V6[btype]} {bnum}", "filename_amdt_slug"))
        if not out:
            for m_fb in _FILENAME_EXPLICIT_BILL_RE.finditer(filename or ""):
                btype = re.sub(r"[^a-z]", "", m_fb.group("btype").lower())
                bnum = str(int(m_fb.group("num")))
                if btype in BILL_DISPLAY_MAP_V6 and (btype, bnum) not in seen:
                    seen.add((btype, bnum))
                    out.append(BillHitV6(btype, bnum, congress, f"bill:{BILL_DISPLAY_MAP_V6[btype]} {bnum}", "filename_explicit"))
        if not out and measure_keys:
            for mk in measure_keys:
                parts = str(mk).strip().lower().split("-")
                if len(parts) == 3 and parts[0].isdigit() and parts[1] in BILL_DISPLAY_MAP_V6 and parts[2].isdigit():
                    btype, bnum = parts[1], str(int(parts[2]))
                    if (btype, bnum) not in seen:
                        seen.add((btype, bnum))
                        out.append(
                            BillHitV6(
                                btype,
                                bnum,
                                int(parts[0]),
                                f"bill:{BILL_DISPLAY_MAP_V6[btype]} {bnum}",
                                "detail_measure_keys",
                            )
                        )

    return tuple(out)


# ---------------------------------------------------------------------------
# Dockets, RINs, GAO & CRS (`identifier_shapes.py` + `ferc_elibrary_codes`)
# ---------------------------------------------------------------------------

_LABEL_COUNTER_WORD = r"(?:nos?(?:\.|\b)|numbers?\b|ids?\b)"
_DOCKET_MONTH_STOP = r"(?!(?:JAN|JANUARY|FEB|FEBRUARY|MAR|MARCH|APR|APRIL|MAY|JUN|JUNE|JUL|JULY|AUG|AUGUST|SEP|SEPT|SEPTEMBER|OCT|OCTOBER|NOV|NOVEMBER|DEC|DECEMBER)[-_])"
_DOCKET_ORGANIZATION_UPPER = rf"{_DOCKET_MONTH_STOP}[A-Z]{{2,6}}(?:-[A-Z0-9]{{1,8}}){{0,2}}"
_DOCKET_OFFICE_UPPER = r"(?:(?P<office>[A-Z]{1,8}(?:-[A-Z]{1,8})?)-)?"
_DOCKET_ORGANIZATION = rf"{_DOCKET_MONTH_STOP}[A-Za-z]{{2,6}}(?:[-_][A-Za-z0-9]{{1,8}}){{0,2}}"
_DOCKET_OFFICE = r"(?:(?P<office>[A-Za-z]{1,8}(?:[-_][A-Za-z]{1,8})?)[-_])?"
_DOCKET_SEGMENT_TOKENS = "NONRULEMAKING|RULEMAKING|NONRULE|RULE|DRAFT"
_DOCKET_SEGMENT_SET = frozenset(_DOCKET_SEGMENT_TOKENS.split("|"))
_DOCKET_SEGMENT = rf"(?:[-_](?P<segment>{_DOCKET_SEGMENT_TOKENS}))?"
_DOCKET_LABEL = rf"(?:dockets?|docs?)\b\.?\s*{_LABEL_COUNTER_WORD}?\s*[:#\-]*\s*"

# Bare Regulations.gov dockets in prose must be ALL-CAPS hyphenated agency identifiers (never mixed-case file names)
_DOCKET_BARE_RE = re.compile(
    rf"{_LEFT}(?P<value>(?P<organization>{_DOCKET_ORGANIZATION_UPPER})-(?P<year>(?:19|20)\d{{2}})-{_DOCKET_OFFICE_UPPER}(?P<sequence>\d{{3,5}}){_DOCKET_SEGMENT}){_RIGHT}"
)
_DOCKET_LABELED_RE = re.compile(
    rf"\b{_DOCKET_LABEL}(?P<value>(?P<organization>{_DOCKET_ORGANIZATION})[-_](?P<year>\d{{4}}|\d{{2}})[-_]{_DOCKET_OFFICE}(?P<sequence>\d{{3,5}}){_DOCKET_SEGMENT}){_RIGHT}",
    re.IGNORECASE,
)
_REGSGOV_DOC_RE = re.compile(
    rf"{_LEFT}(?P<value>(?P<organization>{_DOCKET_ORGANIZATION})[-_](?P<year>\d{{4}})[-_]{_DOCKET_OFFICE}(?P<docket_sequence>\d{{3,5}}){_DOCKET_SEGMENT}[-_](?P<document_sequence>\d{{3,6}})){_RIGHT}"
)
_REGSGOV_VALID_RE = re.compile(r"[A-Z0-9]+(?:[-_][A-Z0-9]+)*")
_REGSGOV_FRDOC_RE = re.compile(r"[A-Z][A-Z0-9]{1,9}_FRDOC_\d{4}")
_DOCKET_LABEL_PREFIX_RE = re.compile(rf"^\s*(?:[A-Za-z]{{2,6}}\s+)?{_DOCKET_LABEL}", re.IGNORECASE)

_FERC_DOCKET_PREFIXES = (
    "AC AD AI CD CE CP CX DI DO DR DV EC EF EG EL EM EP ER ES ET EX EY FA FC GP GT GX HC IN IS "
    "JR LA LP MC MD MG ML MO MT NJ NL NP NR OA OR OT PA PF PH PL PR QF QM RA RC RD RM RO RP RR "
    "RS RT SA SC TC TF TM TQ TS TX UL ZZ"
).split()
_FERC_DOCKET_FULL_RE = re.compile(rf"(?:{'|'.join(_FERC_DOCKET_PREFIXES)})\d{{2}}-\d+(?:-\d{{3}})?")
# Prose FERC docket requires 3-digit sub-docket (`CP26-20-000`) or explicit `FERC Docket` label to prevent `FC`/`SC` collisions
_FERC_PROSE_SUBDOCKET_RE = re.compile(
    rf"{_LEFT}(?:FERC\s+Docket\s+{_LABEL_COUNTER_WORD}?\s*)?(?P<docket>(?:{'|'.join(_FERC_DOCKET_PREFIXES)})\d{{2}}-\d{{1,5}}-\d{{3}}){_RIGHT}",
    re.IGNORECASE,
)

_RIN_RE = re.compile(rf"{_LEFT}(?P<value>\d{{4}}-[A-Za-z]{{2}}[A-Za-z0-9]{{2}}){_RIGHT}")
_PUBLISHED_RIN_RE = re.compile(r"^\d{4}-[A-Z]{2}\d{2}$")
_OMB_NUMBER_LABEL_RE = re.compile(r"\bOMB\s+(?:control\s+)?(?:numbers?|nos?\.?|#)\s*[:#]?\s*$", re.IGNORECASE)

_GAO_ID_RE = re.compile(r"\bGAO-\d{2}-\d{3,6}(?:[A-Z]{1,3})?\b")
_CRS_ID_RE = re.compile(r"\b(?:R|RL|RS|IF|IN|LSB)\d{4,6}\b")
_CASE_REPORTER_RE = re.compile(
    rf"{_LEFT}(?P<volume>[1-9]\d{{0,3}})\s+(?P<reporter>F\.?\s?(?:2d|3d|4th)|F\.?\s?Supp\.?\s?(?:2d|3d)?|U\.\s?S\.|S\.\s?Ct\.|Cl\.?\s?Ct\.?)\s+(?P<page>[1-9]\d{{0,4}}){_RIGHT}"
)


def published_rin_v6(value: object) -> str | None:
    s = _normalize_dashes(str(value or "")).strip().upper()
    return s if _PUBLISHED_RIN_RE.fullmatch(s) else None


def _has_regsgov_docket_shape(identifier: str) -> bool:
    if _REGSGOV_FRDOC_RE.fullmatch(identifier):
        return True
    org, *segments = re.split(r"[-_]", identifier)
    if segments and segments[-1] in _DOCKET_SEGMENT_SET:
        segments.pop()
    if not org[:1].isalpha() or len(segments) < 2 or not segments[-1].isdigit():
        return False
    return any(len(seg) in (2, 4) and seg.isdigit() for seg in segments[:-1])


def normalize_docket_reference_v6(reference: object) -> str | None:
    raw = str(reference or "").strip()
    if not raw or raw in {"None", "nan", "null"}:
        return None
    stripped = _DOCKET_LABEL_PREFIX_RE.sub("", raw, count=1).strip()
    for cand in (raw, stripped):
        folded = _normalize_dashes(cand).strip().upper()
        if not _REGSGOV_VALID_RE.fullmatch(folded) or not _has_regsgov_docket_shape(folded):
            continue
        if _FERC_DOCKET_FULL_RE.fullmatch(folded):
            return None
        return folded
    return None


def _in_slash_token(text: str, start: int, end: int) -> bool:
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    return "/" in text[start:end]


def _detect_dockets_and_rins_v6(text: str) -> tuple[list[str], list[str]]:
    if not text:
        return [], []
    norm = _normalize_dashes(text)
    # Arbitrate overlaps longest-first, RIN > REGSGOV_DOC > DOCKET (matching identifier_shapes.py)
    raw_cands: list[tuple[int, int, int, str, str]] = []
    for m in _RIN_RE.finditer(norm):
        s, e = m.span("value")
        if not _in_slash_token(norm, s, e):
            raw_cands.append((s, -(e - s), 0, "rin", m.group("value").upper()))
    for m in _REGSGOV_DOC_RE.finditer(norm):
        s, e = m.span("value")
        raw_cands.append((s, -(e - s), 2, "regdoc", m.group("value").upper()))
    for pat in (_DOCKET_BARE_RE, _DOCKET_LABELED_RE):
        for m in pat.finditer(norm):
            s, e = m.span("value")
            raw_cands.append((s, -(e - s), 3, "docket", m.group("value").upper()))

    raw_cands.sort()
    dockets: list[str] = []
    rins: list[str] = []
    reach = 0
    seen_exact: set[tuple[int, int, str, str]] = set()
    for s, neg_len, _prio, kind, val in raw_cands:
        e = s - neg_len
        if (s, e, kind, val) in seen_exact:
            continue
        seen_exact.add((s, e, kind, val))
        if s < reach:
            continue
        reach = max(reach, e)
        if kind == "docket":
            dk = normalize_docket_reference_v6(val)
            if dk and dk not in dockets:
                dockets.append(dk)
        elif kind == "rin":
            if not _OMB_NUMBER_LABEL_RE.search(norm, max(0, s - 40), s):
                rv = published_rin_v6(val)
                if rv and rv not in rins:
                    rins.append(rv)

    for m in _FERC_PROSE_SUBDOCKET_RE.finditer(norm):
        fdk = m.group("docket").upper()
        if fdk not in dockets:
            dockets.append(fdk)

    return dockets, rins


# ---------------------------------------------------------------------------
# `RefSpec` 6 SHA256-Pinned Statutory & Regulatory Oracles (`pyarrow` / `csv` / `json`)
# ---------------------------------------------------------------------------

_NAME_EDGE_RE = re.compile(r"^[\s(\"'“”]+|[\s,;:.)\"'“”]+$")
_CURLY_APOSTROPHE_RE = re.compile(r"[’‘`]")
_YEAR_PREFIXED_NAME_RE = re.compile(r"^\s*(?:the\s+)?((?:18|19|20)\d{2})\s+(\S.*)$", re.IGNORECASE)
_YEAR_SUFFIX_RE = re.compile(r"\s+of\s+(?:1[789]|20)\d{2}$")
_LEADING_ARTICLE_RE = re.compile(r"^the\s+")
_RKAF_USC_IRI_RE = re.compile(r"^urn:rkaf:us:usc:[1-9][0-9]*:[1-9][0-9]*[a-z]*(?:-[0-9a-z]+)*$")
_PAGE_RANGE_OPEN_END = 1 << 30
_ALIAS_MAX_DEPTH = 8


def normalize_popular_name_v6(name: object) -> str:
    text = _CURLY_APOSTROPHE_RE.sub("'", _normalize_dashes(str(name or "")))
    text = _NAME_EDGE_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _act_name_with_trailing_year(name: str) -> str | None:
    m = _YEAR_PREFIXED_NAME_RE.match(name)
    return f"{m.group(2)} of {m.group(1)}" if m else None


def canonical_usc_iri_v6(title: object, section: object) -> str:
    t_str = str(title or "").strip().lstrip("0")
    s_str = re.sub(r"\([^)]*\)", "", _normalize_dashes(str(section or "")).strip().lower())
    iri = f"urn:rkaf:us:usc:{t_str}:{s_str}"
    if not _RKAF_USC_IRI_RE.fullmatch(iri):
        raise ValueError(f"Invalid U.S.C. IRI components: title={title!r}, section={section!r}")
    return iri


class _ClassificationRow(NamedTuple):
    usc_title: str | None
    usc_section: str | None
    status: str | None
    statutes_at_large_page: int | None


@dataclass(frozen=True)
class ActRelativeCitationV6:
    act_name: str
    act_key: str
    section: str
    division: str | None = None
    start: int = 0
    end: int = 0


@dataclass(frozen=True)
class ActResolutionV6:
    citation: ActRelativeCitationV6
    act_key: str | None = None
    table3_key: str | None = None
    usc_title: str | None = None
    usc_section: str | None = None
    iri: str | None = None
    unresolved_reason: str | None = None
    answered_by: str | None = None


@dataclass(frozen=True)
class ActIndexV6:
    table3_key_by_name: Mapping[str, str | None]
    alias_by_name: Mapping[str, str]
    classifications: Mapping[str, Mapping[str, tuple[_ClassificationRow, ...]]]
    cited_names: frozenset[str]
    division_by_name: Mapping[str, tuple[str, int | None]]
    division_starts: Mapping[str, tuple[tuple[str, int], ...]]
    narrowed_page_sections: frozenset[tuple[str, str]]
    acts_supplying_year: Mapping[str, tuple[str, ...]]
    canonical_display_by_key: Mapping[str, str]
    stat_to_pl: Mapping[tuple[str, str], str]

    @property
    def all_act_names(self) -> frozenset[str]:
        return self.cited_names | frozenset(self.alias_by_name.keys()) | frozenset(self.table3_key_by_name.keys())

    def act_page_range(self, act_key: str) -> tuple[int, int] | None:
        if self.table3_key_by_name.get(act_key) is None:
            return None
        stated = self.division_by_name.get(act_key)
        if stated is None:
            return None
        div = stated[0]
        t3 = self.table3_key_by_name.get(act_key)
        starts = self.division_starts.get(t3 or "", ())
        start = min((p for n, p in starts if n == div), default=None)
        if start is None:
            return None
        return (start, min((p for _, p in starts if p > start), default=_PAGE_RANGE_OPEN_END))

    @classmethod
    def from_directory(cls, directory: Path, *, verify_pins: bool = True) -> ActIndexV6:
        import pyarrow.parquet as pq

        if verify_pins:
            for fn in ("usc-popular-names.parquet", "usc-act-sections.parquet", "quarantine.parquet"):
                _verify_sha256(directory / fn, fn)

        q_tbl = pq.read_table(directory / "quarantine.parquet", columns=["reason", "table3_key", "raw_value"])
        narrowed = frozenset(
            (t3, rv.partition(" -> ")[0])
            for rsn, t3, rv in zip(
                q_tbl["reason"].to_pylist(), q_tbl["table3_key"].to_pylist(), q_tbl["raw_value"].to_pylist()
            )
            if rsn == "statutes_at_large_page_span_narrowed" and t3 and rv
        )

        pn_tbl = pq.read_table(
            directory / "usc-popular-names.parquet",
            columns=[
                "name",
                "name_key",
                "content_type",
                "table3_key",
                "see_also_key",
                "division",
                "statutes_at_large_volume",
                "statutes_at_large_page",
            ],
        )
        alias_by_name: dict[str, str] = {}
        cited_names: set[str] = set()
        laws_by_name: dict[str, set[str]] = {}
        identities_by_name: dict[str, set[tuple[str, str | None]]] = {}
        pages_by_name: dict[str, list[int]] = {}
        starts: dict[str, dict[str, int]] = {}
        canonical_display_by_key: dict[str, str] = {}
        stat_to_pl: dict[tuple[str, str], str] = {}

        for raw_name, nk, ctype, t3, sak, div, svol, spage in zip(
            pn_tbl["name"].to_pylist(),
            pn_tbl["name_key"].to_pylist(),
            pn_tbl["content_type"].to_pylist(),
            pn_tbl["table3_key"].to_pylist(),
            pn_tbl["see_also_key"].to_pylist(),
            pn_tbl["division"].to_pylist(),
            pn_tbl["statutes_at_large_volume"].to_pylist(),
            pn_tbl["statutes_at_large_page"].to_pylist(),
        ):
            name = normalize_popular_name_v6(nk)
            if raw_name and name not in canonical_display_by_key:
                canonical_display_by_key[name] = str(raw_name).strip()
            if sak:
                alias_by_name.setdefault(name, normalize_popular_name_v6(sak))
            if ctype != "cite":
                continue
            cited_names.add(name)
            if t3:
                laws_by_name.setdefault(name, set()).add(t3)
                identities_by_name.setdefault(name, set()).add((t3, div))
                if spage and str(spage).isdigit():
                    p_int = int(spage)
                    pages_by_name.setdefault(name, []).append(p_int)
                    if div:
                        by_div = starts.setdefault(t3, {})
                        by_div[div] = min(by_div.get(div, p_int), p_int)
                if svol and spage and re.fullmatch(r"[1-9]\d{1,2}-[1-9]\d*", t3):
                    stat_to_pl.setdefault((str(svol).strip(), str(spage).strip()), t3)

        table3_key_by_name: dict[str, str | None] = {}
        division_by_name: dict[str, tuple[str, int | None]] = {}
        for name, laws in laws_by_name.items():
            table3_key_by_name[name] = next(iter(laws)) if len(laws) == 1 else None
            idents = identities_by_name[name]
            if len(idents) == 1:
                only_div = next(iter(idents))[1]
                if only_div:
                    division_by_name[name] = (only_div, min(pages_by_name.get(name, ()), default=None))

        by_stem: dict[str, list[str]] = {}
        for known in table3_key_by_name:
            stem = _YEAR_SUFFIX_RE.sub("", known)
            if stem != known:
                by_stem.setdefault(stem, []).append(known)
        acts_supplying_year = {stem: tuple(acts) for stem, acts in by_stem.items()}

        sec_tbl = pq.read_table(
            directory / "usc-act-sections.parquet",
            columns=["table3_key", "act_section", "usc_title", "usc_section", "status", "statutes_at_large_page"],
        )
        classifications: dict[str, dict[str, list[_ClassificationRow]]] = {}
        for t3, asec, ut, us, st, sp in zip(
            sec_tbl["table3_key"].to_pylist(),
            sec_tbl["act_section"].to_pylist(),
            sec_tbl["usc_title"].to_pylist(),
            sec_tbl["usc_section"].to_pylist(),
            sec_tbl["status"].to_pylist(),
            sec_tbl["statutes_at_large_page"].to_pylist(),
        ):
            p_i = int(sp) if sp and str(sp).isdigit() else None
            classifications.setdefault(t3, {}).setdefault(asec, []).append(_ClassificationRow(ut, us, st, p_i))

        return cls(
            table3_key_by_name=table3_key_by_name,
            alias_by_name=alias_by_name,
            classifications={k: {sk: tuple(sv) for sk, sv in v.items()} for k, v in classifications.items()},
            cited_names=frozenset(cited_names),
            division_by_name=division_by_name,
            division_starts={
                k: tuple(sorted(by_d.items(), key=lambda it: (it[1], it[0]))) for k, by_d in starts.items()
            },
            narrowed_page_sections=narrowed,
            acts_supplying_year=acts_supplying_year,
            canonical_display_by_key=canonical_display_by_key,
            stat_to_pl=stat_to_pl,
        )


@dataclass(frozen=True)
class SourceCreditIndexV6:
    targets: Mapping[tuple[str, str, str], tuple[tuple[str, str], ...]]

    @classmethod
    def from_directory(cls, directory: Path, *, verify_pins: bool = True) -> SourceCreditIndexV6:
        import pyarrow.parquet as pq

        path = directory / "usc-source-credits.parquet"
        if verify_pins:
            _verify_sha256(path, "usc-source-credits.parquet")
        tbl = pq.read_table(path, columns=["public_law", "division", "act_section", "usc_title", "usc_section"])
        buckets: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
        for pl, div, asec, ut, us in zip(
            tbl["public_law"].to_pylist(),
            tbl["division"].to_pylist(),
            tbl["act_section"].to_pylist(),
            tbl["usc_title"].to_pylist(),
            tbl["usc_section"].to_pylist(),
        ):
            if pl and div and asec and ut and us:
                pair = (str(ut), str(us))
                b = buckets.setdefault((str(pl), str(div), str(asec)), [])
                if pair not in b:
                    b.append(pair)
        return cls(targets={k: tuple(v) for k, v in buckets.items()})

    def lookup(self, public_law: str | None, division: str | None, act_section: str) -> tuple[str, str | None, str | None]:
        if not public_law or not division:
            return "no_key", None, None
        found = self.targets.get((public_law, division, act_section), ())
        if not found:
            return "absent", None, None
        if len(found) > 1:
            return "multi_target", None, None
        return "resolved", found[0][0], found[0][1]


def _stated_name_chain(name: str, index: ActIndexV6) -> tuple[str, ...]:
    chain: list[str] = []
    seen: set[str] = set()
    cur = normalize_popular_name_v6(name)
    while cur not in seen and len(chain) < _ALIAS_MAX_DEPTH:
        chain.append(cur)
        seen.add(cur)
        nxt = index.alias_by_name.get(cur)
        if nxt is None:
            break
        cur = nxt
    return tuple(chain)


def resolve_act_name_v6(name: str, index: ActIndexV6) -> str | None:
    """Resolve an Act popular name or alias following `ALIAS_PRECEDENCE_RULE` then `ALIAS_YEAR_RULE`."""
    chain = _stated_name_chain(name, index)
    for step in chain:
        if step in index.table3_key_by_name:
            return step
    for step in chain:
        stripped = _LEADING_ARTICLE_RE.sub("", step)
        if stripped != step and stripped in index.table3_key_by_name:
            return stripped
    for step in chain:
        supplied = index.acts_supplying_year.get(step, ())
        if len(supplied) == 1:
            return supplied[0]
    return None


def resolve_act_relative_citation_v6(
    citation: ActRelativeCitationV6,
    *,
    index: ActIndexV6,
    source_credits: SourceCreditIndexV6 | None = None,
) -> ActResolutionV6:
    """Resolve `(Act, section[, division])` via OLRC Table III + USLM Source Credits (`SOURCE_COMPOSITION_RULE`)."""
    act_key = resolve_act_name_v6(citation.act_key, index)
    if act_key is None:
        return ActResolutionV6(citation, unresolved_reason="act_not_in_index")
    t3_key = index.table3_key_by_name.get(act_key)
    if t3_key is None:
        return ActResolutionV6(citation, act_key=act_key, unresolved_reason="act_name_ambiguous")

    stated_div = index.division_by_name.get(act_key)
    eff_div = stated_div[0] if stated_div else citation.division
    if citation.division and stated_div and citation.division != stated_div[0]:
        return ActResolutionV6(citation, act_key=act_key, table3_key=t3_key, unresolved_reason="act_division_conflict")

    # 1. Table III lookup
    t3_iri: str | None = None
    t3_ut: str | None = None
    t3_us: str | None = None
    t3_reason: str | None = None
    rows = index.classifications.get(t3_key, {}).get(citation.section, ())
    if not rows:
        t3_reason = "act_section_not_classified"
    else:
        pr = index.act_page_range(act_key)
        if pr is not None and (t3_key, citation.section) not in index.narrowed_page_sections:
            lo, hi = pr
            if all(r.statutes_at_large_page is not None and not (lo <= r.statutes_at_large_page <= hi) for r in rows):
                t3_reason = "act_section_outside_act"
        if t3_reason is None:
            if len(rows) > 1:
                t3_reason = "act_section_ambiguous"
            elif rows[0].status:
                t3_reason = "classification_not_current"
            elif not (rows[0].usc_title and rows[0].usc_section):
                t3_reason = "act_section_not_classified"
            else:
                t3_ut, t3_us = rows[0].usc_title, rows[0].usc_section
                try:
                    t3_iri = canonical_usc_iri_v6(t3_ut, t3_us)
                except ValueError:
                    t3_reason = "usc_section_not_expressible"

    # 2. Source Credits lookup (for division-scoped omnibus laws)
    sc_status = "not_consulted"
    sc_iri: str | None = None
    sc_ut: str | None = None
    sc_us: str | None = None
    if source_credits is not None and re.fullmatch(r"[1-9]\d{0,2}-[1-9]\d*", t3_key):
        sc_status, sc_ut, sc_us = source_credits.lookup(t3_key, eff_div, citation.section)
        if sc_status == "resolved" and sc_ut and sc_us:
            try:
                sc_iri = canonical_usc_iri_v6(sc_ut, sc_us)
            except ValueError:
                sc_status = "not_expressible"

    if sc_status == "multi_target":
        return ActResolutionV6(citation, act_key=act_key, table3_key=t3_key, unresolved_reason="act_section_ambiguous")
    if t3_iri and sc_iri:
        if t3_iri != sc_iri:
            return ActResolutionV6(citation, act_key=act_key, table3_key=t3_key, unresolved_reason="sources_disagree")
        return ActResolutionV6(
            citation, act_key=act_key, table3_key=t3_key, usc_title=t3_ut, usc_section=t3_us, iri=t3_iri, answered_by="both"
        )
    if t3_iri:
        return ActResolutionV6(
            citation, act_key=act_key, table3_key=t3_key, usc_title=t3_ut, usc_section=t3_us, iri=t3_iri, answered_by="table3"
        )
    if sc_iri:
        return ActResolutionV6(
            citation,
            act_key=act_key,
            table3_key=t3_key,
            usc_title=sc_ut,
            usc_section=sc_us,
            iri=sc_iri,
            answered_by="source_credits",
        )
    return ActResolutionV6(
        citation, act_key=act_key, table3_key=t3_key, unresolved_reason=t3_reason or "act_section_not_classified"
    )


# --- Act-Relative & Maximal-NP Popular Name Scanners (`TRAP_3` & `TRAP_4`) ---
_ACT_SECTION_RE = re.compile(r"(?:sec(?:tion)?s?\.?|§{1,2})\s*(?P<section>\d+[A-Za-z]?)", re.IGNORECASE)
_CITED_DIVISION_RE = re.compile(r"(?i:\bdiv(?:ision)?\.?)\s+(?P<division>[A-Z]{1,3})\b")
_ACT_SECTION_OF_THE_RE = re.compile(r"\s*(?:of\s+(?:the\s+)?|,\s*(?:the\s+)?|\s+)", re.IGNORECASE)
_ACT_SPACE_RE = re.compile(r"\s*")
_ACT_PARENTHETICAL_RE = re.compile(r"\([^()]{1,12}\)")
_ACT_DIVISION_OF_RE = re.compile(r"\s+of\s+(?:the\s+)?", re.IGNORECASE)
_ACT_NAME_GAP_RE = re.compile(r"[\s,:\"'”’)]*")
_MAX_ACT_NAME_WORDS = 24


def _act_name_span(
    document: str, words: list[re.Match[str]], act_names: Container[str], *, before: bool
) -> tuple[int, int, str, str] | None:
    for length in range(len(words), 0, -1):
        selected = words[-length:] if before else words[:length]
        start, end = selected[0].start(), selected[-1].end()
        raw = document[start:end]
        if _CITATION_PARAGRAPH_BREAK.search(raw):
            continue
        candidate = " ".join(raw.split())
        key = normalize_popular_name_v6(candidate)
        if key not in act_names:
            reordered = _act_name_with_trailing_year(key)
            if reordered is None or reordered not in act_names:
                continue
            key = reordered
        edges = list(_NAME_EDGE_RE.finditer(raw))
        left = edges[0].end() if edges and edges[0].start() == 0 else 0
        right = edges[-1].start() if edges and edges[-1].end() == len(raw) else len(raw)
        return start + left, start + right, _NAME_EDGE_RE.sub("", candidate), key
    return None


def find_act_relative_occurrences_v6(
    text: str, *, act_names: Container[str]
) -> tuple[ActRelativeCitationV6, ...]:
    """O(tokens) bounded 24-word lookaround scanner for `section X of the Y Act` / `Y Act Sec. X`."""
    if not text or not act_names:
        return ()
    words = list(re.finditer(r"\S+", text))
    starts, ends = [w.start() for w in words], [w.end() for w in words]
    found: list[ActRelativeCitationV6] = []
    for marker in _ACT_SECTION_RE.finditer(text):
        sec = _usc_clean_sec(marker.group("section"))
        if not sec:
            continue
        end = marker.end()
        while True:
            pos = _ACT_SPACE_RE.match(text, end).end()
            if _CITATION_PARAGRAPH_BREAK.search(text, end, pos):
                break
            par = _ACT_PARENTHETICAL_RE.match(text, pos)
            if par is None:
                break
            end = par.end()
        left = bisect_right(ends, marker.start())
        named = _act_name_span(text, words[max(0, left - _MAX_ACT_NAME_WORDS) : left], act_names, before=True)
        if named is not None and (
            not _ACT_NAME_GAP_RE.fullmatch(text, named[1], marker.start())
            or _CITATION_PARAGRAPH_BREAK.search(text, named[1], marker.start())
        ):
            named = None
        if named is None:
            opening = _ACT_SECTION_OF_THE_RE.match(text, end)
            if opening is None or _CITATION_PARAGRAPH_BREAK.search(text, end, opening.end()):
                continue
            right = bisect_left(starts, opening.end())
            named = _act_name_span(text, words[right : right + _MAX_ACT_NAME_WORDS], act_names, before=False)
        if named is None:
            continue
        n_start, n_end, name, key = named
        s_off, e_off = min(marker.start(), n_start), max(end, n_end)
        division = None
        if n_start == s_off:
            prefix = words[max(0, bisect_right(ends, s_off) - 4)].start()
            for stated in _CITED_DIVISION_RE.finditer(text, prefix, s_off):
                if _ACT_DIVISION_OF_RE.fullmatch(text, stated.end(), s_off):
                    division, s_off = stated.group("division"), stated.start()
                    break
        found.append(ActRelativeCitationV6(name, key, sec, division, s_off, e_off))
    return tuple(found)


_ACT_NP_CONNECTORS = frozenset({"of", "for", "and", "the", "to", "on", "in", "with", "&", "by", "against"})
_ACT_NP_STOP = frozenset(
    {
        "USC",
        "USCA",
        "CFR",
        "STAT",
        "FR",
        "PL",
        "EO",
        "APP",
        "SEC",
        "SECS",
        "SECTION",
        "PUB",
        "L",
        "AMEND",
        "AMENDING",
        "UNDER",
        "PURSUANT",
        "ENACTED",
        "TITLED",
        "ENTITLED",
    }
)
_ACT_NP_WORD_BACK_RE = re.compile(r"[\w'\-&]+\.?$")
_ACT_NP_CAP_TOK_RE = re.compile(r"[A-Z0-9][\w'\-&]*")
_ACT_NP_AMEND_TAIL_RE = re.compile(r"\s+Amendments?\b")
_ACT_NP_YEAR_TAIL_RE = re.compile(r"\s*(?:,\s*)?of\s+(?P<year>1[7-9]\d\d|20\d\d)\b")


def find_maximal_popular_acts_v6(text: str, act_index: ActIndexV6 | None = None) -> list[dict[str, Any]]:
    """Scan for maximal uninterrupted capitalized `... Act` noun phrases (`TRAP_3`: never sub-slice inner suffixes)."""
    if not text or act_index is None:
        return []
    norm = _normalize_dashes(text)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in re.finditer(r"\bAct\b", norm):
        head = norm[: m.start()].rstrip()
        tokens: list[tuple[str, int]] = []
        while head:
            tm = _ACT_NP_WORD_BACK_RE.search(head)
            if tm is None:
                break
            w = tm.group(0).rstrip(".")
            if w.upper() in _ACT_NP_STOP:
                break
            if _ACT_NP_CAP_TOK_RE.fullmatch(w) or w.lower() in _ACT_NP_CONNECTORS:
                tokens.append((w, tm.start()))
                head = head[: tm.start()].rstrip()
                continue
            break
        while tokens and tokens[-1][0].lower() in _ACT_NP_CONNECTORS:
            tokens.pop()
        while tokens and re.fullmatch(r"[A-Z]|[IVXLC]{1,5}", tokens[-1][0]):
            tokens.pop()
            while tokens and tokens[-1][0].lower() in _ACT_NP_CONNECTORS:
                tokens.pop()
        if not tokens or not any(w[:1].isupper() for w, _ in tokens):
            continue
        span_start = tokens[-1][1]
        cur = m.end()
        name = re.sub(r"\s+", " ", norm[span_start:cur]).strip()
        am = _ACT_NP_AMEND_TAIL_RE.match(norm, cur)
        if am:
            name = f"{name} {am.group(0).strip()}"
            cur = am.end()
        yr = _ACT_NP_YEAR_TAIL_RE.match(norm, cur)
        if yr:
            name = f"{name} of {yr.group('year')}"
            cur = yr.end()
        # TRAP_3: Only query the maximal uninterrupted NP; never slice inner suffixes!
        resolved = resolve_act_name_v6(name, act_index)
        if resolved and resolved not in seen:
            seen.add(resolved)
            results.append(
                {
                    "surface": name,
                    "resolved_act_key": resolved,
                    "table3_key": act_index.table3_key_by_name.get(resolved),
                    "start": span_start,
                    "end": cur,
                }
            )
    return results


# --- UscSectionOracleV6 + UscDispositionTablesV6 ---
_LEADING_DIGITS_RE = re.compile(r"^(\d+)(.*)$")


def _oracle_section_key(sec: str) -> tuple[int, str] | None:
    m = _LEADING_DIGITS_RE.match(sec)
    return (int(m.group(1)), m.group(2)) if m else None


@dataclass(frozen=True)
class _SpanIndexV6:
    lows: tuple[tuple[int, str], ...]
    highs: tuple[tuple[int, str], ...]
    prefix_max_high: tuple[tuple[int, str], ...]

    @classmethod
    def build(cls, spans: Iterable[tuple[tuple[int, str], tuple[int, str]]]) -> _SpanIndexV6:
        ordered = sorted(set(spans), key=lambda sp: sp[0])
        if not ordered:
            return cls((), (), ())
        highs = tuple(sp[1] for sp in ordered)
        return cls(
            lows=tuple(sp[0] for sp in ordered),
            highs=highs,
            prefix_max_high=tuple(accumulate(highs, max)),
        )

    def contains(self, key: tuple[int, str]) -> bool:
        if not self.lows:
            return False
        limit = bisect_right(self.lows, key)
        if limit == 0 or self.prefix_max_high[limit - 1] < key:
            return False
        for i in range(limit):
            if self.highs[i] >= key:
                return True
        return False


@dataclass(frozen=True)
class DispositionV6:
    former_title: int
    former_section: str
    verdict: str
    successors: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True)
class UscDispositionTablesV6:
    by_section: Mapping[tuple[int, str], tuple[tuple[str, int | None, str | None], ...]]

    @classmethod
    def from_directory(cls, directory: Path, *, verify_pins: bool = True) -> UscDispositionTablesV6:
        import pyarrow.parquet as pq

        path = directory / "usc-1994-title49-disposition.parquet"
        if verify_pins:
            _verify_sha256(path, "usc-1994-title49-disposition.parquet")
        tbl = pq.read_table(path, columns=["former_title", "former_section", "status", "new_title", "new_section"])
        buckets: dict[tuple[int, str], list[tuple[str, int | None, str | None]]] = {}
        for ft, fs, st, nt, ns in zip(
            tbl["former_title"].to_pylist(),
            tbl["former_section"].to_pylist(),
            tbl["status"].to_pylist(),
            tbl["new_title"].to_pylist(),
            tbl["new_section"].to_pylist(),
        ):
            key = (int(ft), _normalize_dashes(str(fs)).strip().lower())
            buckets.setdefault(key, []).append((str(st or ""), int(nt) if nt is not None else None, ns))
        return cls(by_section={k: tuple(v) for k, v in buckets.items()})

    def disposition(self, title: int, section: str) -> DispositionV6:
        sec_norm = _normalize_dashes(section).strip().lower()
        if title != 49:
            return DispositionV6(title, sec_norm, "no-table-for-title")
        rows = self.by_section.get((49, sec_norm))
        if not rows:
            return DispositionV6(49, sec_norm, "not-in-table")
        with_succ = {"restated", "restated-as-note"}
        succ = tuple(
            dict.fromkeys(
                (nt, _normalize_dashes(str(ns)).strip().lower())
                for st, nt, ns in rows
                if st in with_succ and nt is not None and ns
            )
        )
        if succ:
            return DispositionV6(49, sec_norm, "exists-as-recodified", succ)
        if all(st in {"repealed", "eliminated"} for st, _, _ in rows):
            return DispositionV6(49, sec_norm, "repealed-no-successor")
        return DispositionV6(49, sec_norm, "stated-without-successor")


@dataclass(frozen=True)
class SectionVerdictV6:
    title: int
    section: str
    appendix: bool
    verdict: str
    reason: str | None = None
    disposition: DispositionV6 | None = None

    @property
    def exists(self) -> bool:
        return self.verdict == "exists"


@dataclass(frozen=True)
class UscSectionOracleV6:
    rp_sections: frozenset[tuple[int, str]]
    annual_sections: frozenset[tuple[int, bool, str]]
    rp_ranges: Mapping[int, _SpanIndexV6]
    annual_ranges: Mapping[tuple[int, bool], _SpanIndexV6]
    subsections: Mapping[tuple[int, str], frozenset[str]]
    chapters: frozenset[tuple[int, str]]
    dispositions: UscDispositionTablesV6 | None = None

    @classmethod
    def from_directory(
        cls,
        directory: Path,
        *,
        dispositions: UscDispositionTablesV6 | None = None,
        verify_pins: bool = True,
    ) -> UscSectionOracleV6:
        import pyarrow.parquet as pq

        files = (
            "usc-oracle-sections.parquet",
            "usc-oracle-ranges.parquet",
            "usc-oracle-annual-sections.parquet",
            "usc-oracle-annual-ranges.parquet",
            "usc-oracle-subsections.parquet",
            "usc-oracle-chapters.parquet",
        )
        if verify_pins:
            for fn in files:
                _verify_sha256(directory / fn, fn)

        sec_t = pq.read_table(directory / "usc-oracle-sections.parquet", columns=["title", "section"])
        rp_sections = frozenset(
            (int(t), _normalize_dashes(str(s)).strip().lower())
            for t, s in zip(sec_t["title"].to_pylist(), sec_t["section"].to_pylist())
        )

        # Deduplicate 1.57M annual rows in C++ Arrow before converting to Python (~10x faster!)
        ann_t = pq.read_table(
            directory / "usc-oracle-annual-sections.parquet", columns=["title", "appendix", "section"]
        ).group_by(["title", "appendix", "section"]).aggregate([])
        annual_sections = frozenset(
            (int(t), bool(a), _normalize_dashes(str(s)).strip().lower())
            for t, a, s in zip(ann_t["title"].to_pylist(), ann_t["appendix"].to_pylist(), ann_t["section"].to_pylist())
        )

        rpr_t = pq.read_table(directory / "usc-oracle-ranges.parquet", columns=["title", "lo", "hi"])
        rpr_buckets: dict[int, list[tuple[tuple[int, str], tuple[int, str]]]] = {}
        for t, lo, hi in zip(rpr_t["title"].to_pylist(), rpr_t["lo"].to_pylist(), rpr_t["hi"].to_pylist()):
            kl = _oracle_section_key(_normalize_dashes(str(lo)).strip().lower())
            kh = _oracle_section_key(_normalize_dashes(str(hi)).strip().lower())
            if kl and kh:
                rpr_buckets.setdefault(int(t), []).append((kl, kh))

        anr_t = pq.read_table(
            directory / "usc-oracle-annual-ranges.parquet", columns=["title", "appendix", "lo", "hi"]
        ).group_by(["title", "appendix", "lo", "hi"]).aggregate([])
        anr_buckets: dict[tuple[int, bool], list[tuple[tuple[int, str], tuple[int, str]]]] = {}
        for t, a, lo, hi in zip(
            anr_t["title"].to_pylist(), anr_t["appendix"].to_pylist(), anr_t["lo"].to_pylist(), anr_t["hi"].to_pylist()
        ):
            kl = _oracle_section_key(_normalize_dashes(str(lo)).strip().lower())
            kh = _oracle_section_key(_normalize_dashes(str(hi)).strip().lower())
            if kl and kh:
                anr_buckets.setdefault((int(t), bool(a)), []).append((kl, kh))

        sub_t = pq.read_table(directory / "usc-oracle-subsections.parquet", columns=["title", "section", "sub"])
        sub_b: dict[tuple[int, str], set[str]] = {}
        for t, s, sub in zip(sub_t["title"].to_pylist(), sub_t["section"].to_pylist(), sub_t["sub"].to_pylist()):
            sub_b.setdefault((int(t), _normalize_dashes(str(s)).strip().lower()), set()).add(str(sub))

        ch_t = pq.read_table(directory / "usc-oracle-chapters.parquet", columns=["title", "chapter"])
        chapters = frozenset(
            (int(t), str(ch).strip().lower())
            for t, ch in zip(ch_t["title"].to_pylist(), ch_t["chapter"].to_pylist())
        )

        return cls(
            rp_sections=rp_sections,
            annual_sections=annual_sections,
            rp_ranges={k: _SpanIndexV6.build(v) for k, v in rpr_buckets.items()},
            annual_ranges={k: _SpanIndexV6.build(v) for k, v in anr_buckets.items()},
            subsections={k: frozenset(v) for k, v in sub_b.items()},
            chapters=chapters,
            dispositions=dispositions,
        )

    @staticmethod
    def c9_title_49_pre_1996(title: int, sec: str) -> bool:
        if title != 49:
            return False
        if sec.isdigit():
            return int(sec) < 2000 or 10_000 <= int(sec) <= 11_999
        return bool(re.match(r"^\d{1,4}[a-z]", sec))

    def section_verdict(
        self,
        title: int,
        section: str,
        edition_year: int | None = None,
        *,
        appendix: bool = False,
    ) -> SectionVerdictV6:
        sec = _normalize_dashes(str(section or "")).strip().lower()
        sec = re.sub(r"\([^)]*\)", "", sec)
        if edition_year is not None and not (1994 <= edition_year <= 2026):
            return SectionVerdictV6(title, sec, appendix, "unknown", "edition_outside_oracle_window")

        in_rp = not appendix and (title, sec) in self.rp_sections
        in_ann = (title, appendix, sec) in self.annual_sections
        sk = _oracle_section_key(sec)
        in_rp_r = bool(not appendix and sk and title in self.rp_ranges and self.rp_ranges[title].contains(sk))
        in_ann_r = bool(sk and (title, appendix) in self.annual_ranges and self.annual_ranges[(title, appendix)].contains(sk))

        if in_rp or in_ann or in_rp_r or in_ann_r:
            return SectionVerdictV6(title, sec, appendix, "exists")

        if appendix and title not in APPENDIX_TITLES_PUBLISHED_V6:
            if title == 49:
                disp = self.dispositions.disposition(49, sec) if self.dispositions else None
                return SectionVerdictV6(title, sec, True, "unknown", "title_49_appendix_not_published", disp)
            return SectionVerdictV6(title, sec, True, "unknown", "appendix_title_not_published")

        if not appendix and self.c9_title_49_pre_1996(title, sec):
            disp = self.dispositions.disposition(49, sec) if self.dispositions else None
            return SectionVerdictV6(title, sec, False, "unknown", "title_49_appendix_not_published", disp)

        return SectionVerdictV6(title, sec, appendix, "absent")


# --- EoRosterOracleV6 (100% stdlib `csv`!) & CfrAuthorityNotesV6 (`json`!) ---
@dataclass(frozen=True)
class EoVerdictV6:
    eo_number: int
    verdict: str
    window: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class EoRosterOracleV6:
    known_eos: frozenset[int]
    dense_min: int = 12_890
    dense_max: int = 14_420

    @classmethod
    def from_csv(cls, path: Path, *, verify_pins: bool = True) -> EoRosterOracleV6:
        if verify_pins:
            _verify_sha256(path, "roster.csv")
        nums: set[int] = set()
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                nums.add(int(row["eo_number"]))
        return cls(known_eos=frozenset(nums))

    def verdict(self, eo_number: int) -> EoVerdictV6:
        if eo_number in self.known_eos:
            win = (
                "fr_api"
                if self.dense_min <= eo_number <= self.dense_max
                else ("nara_disposition" if 12_668 <= eo_number <= 12_889 else "nara_codification")
            )
            return EoVerdictV6(eo_number, "exists", win)
        if self.dense_min <= eo_number <= self.dense_max:
            return EoVerdictV6(eo_number, "absent", "fr_api")
        if 9 <= eo_number <= 12_889:
            return EoVerdictV6(eo_number, "unknown", "nara_codification", "nara_window_miss")
        return EoVerdictV6(eo_number, "unknown", None, "outside_known_windows")


@dataclass(frozen=True)
class CfrAuthorityNotesV6:
    notes_by_part: Mapping[tuple[int, str], str]

    @classmethod
    def from_jsonl(cls, path: Path) -> CfrAuthorityNotesV6:
        mapping: dict[tuple[int, str], str] = {}
        with path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                obj = json.loads(line)
                t = obj.get("title")
                p = obj.get("part")
                note = obj.get("authority_note") or obj.get("authority") or ""
                if t is not None and p and note:
                    mapping.setdefault((int(t), str(p).strip()), str(note))
        return cls(notes_by_part=mapping)


@dataclass(frozen=True)
class RefSpecOraclesV6:
    act_index: ActIndexV6 | None = None
    source_credits: SourceCreditIndexV6 | None = None
    usc_oracle: UscSectionOracleV6 | None = None
    usc_dispositions: UscDispositionTablesV6 | None = None
    eo_oracle: EoRosterOracleV6 | None = None
    cfr_notes: CfrAuthorityNotesV6 | None = None


_CACHED_ORACLES_BY_ROOT: dict[str, RefSpecOraclesV6] = {}


def load_refspec_oracles_v6(
    refspec_root: str | Path | None = None,
    *,
    include_cfr_notes: bool = False,
    verify_pins: bool = True,
) -> RefSpecOraclesV6:
    """Load `RefSpec`'s local SHA256-pinned statutory & regulatory oracles (gracefully degrading if absent)."""
    root = (
        Path(refspec_root)
        if refspec_root is not None
        else Path(os.environ.get("REFSPEC_ROOT", DEFAULT_REFSPEC_ROOT_STR))
    )
    if not root.exists():
        return RefSpecOraclesV6()
    eo_oracle: EoRosterOracleV6 | None = None
    eo_path = root / _EO_ROSTER_REL
    if eo_path.exists():
        eo_oracle = EoRosterOracleV6.from_csv(eo_path, verify_pins=verify_pins)

    cfr_notes: CfrAuthorityNotesV6 | None = None
    if include_cfr_notes and (root / _CFR_NOTES_REL).exists():
        cfr_notes = CfrAuthorityNotesV6.from_jsonl(root / _CFR_NOTES_REL)

    try:
        import pyarrow.parquet  # noqa: F401
    except ImportError:
        return RefSpecOraclesV6(eo_oracle=eo_oracle, cfr_notes=cfr_notes)

    act_index: ActIndexV6 | None = None
    sc_index: SourceCreditIndexV6 | None = None
    usc_disp: UscDispositionTablesV6 | None = None
    usc_oracle: UscSectionOracleV6 | None = None

    if (root / _ACT_ARTIFACT_REL).exists():
        act_index = ActIndexV6.from_directory(root / _ACT_ARTIFACT_REL, verify_pins=verify_pins)
    if (root / _SOURCE_CREDIT_REL).exists():
        sc_index = SourceCreditIndexV6.from_directory(root / _SOURCE_CREDIT_REL, verify_pins=verify_pins)
    if (root / _USC_DISP_REL).exists():
        usc_disp = UscDispositionTablesV6.from_directory(root / _USC_DISP_REL, verify_pins=verify_pins)
    if (root / _USC_ORACLE_REL).exists():
        usc_oracle = UscSectionOracleV6.from_directory(
            root / _USC_ORACLE_REL, dispositions=usc_disp, verify_pins=verify_pins
        )

    return RefSpecOraclesV6(
        act_index=act_index,
        source_credits=sc_index,
        usc_oracle=usc_oracle,
        usc_dispositions=usc_disp,
        eo_oracle=eo_oracle,
        cfr_notes=cfr_notes,
    )


def get_cached_refspec_oracles_v6(refspec_root: str | Path | None = None) -> RefSpecOraclesV6:
    """Process-singleton oracle bundle keyed by `refspec_root` (CoW-shared across `fork` workers)."""
    resolved = (
        Path(refspec_root)
        if refspec_root is not None
        else Path(os.environ.get("REFSPEC_ROOT", DEFAULT_REFSPEC_ROOT_STR))
    )
    key = str(resolved)
    if key not in _CACHED_ORACLES_BY_ROOT:
        _CACHED_ORACLES_BY_ROOT[key] = load_refspec_oracles_v6(
            refspec_root=resolved, include_cfr_notes=False, verify_pins=True
        )
    return _CACHED_ORACLES_BY_ROOT[key]


# ---------------------------------------------------------------------------
# Executive Orders (`TRAP_2`) & 8 Congressional-Procedural Regex Families
# ---------------------------------------------------------------------------

# TRAP_2: Reject `\`/`:`/`/` file path prefixes & `.003.xml` suffixes (`\E043025.003.xml`), and disallow `E0` zero-homoglyph!
_EO_SPELLED_RE = re.compile(
    r"(?<![0-9A-Za-z_\\/:])(?:Executive\s+Orders?|Exec\.?\s*(?:Orders?|Ord\.?))\s*(?:Nos?\.?\s*)?(?P<num>[1-9]\d{0,4})(?![0-9A-Za-z_\\/.])",
    re.I,
)
_EO_ABBR_RE = re.compile(
    r"(?<![0-9A-Za-z_\\/:])(?:EOs?\.?|E\.\s*O\.?s?)\s*(?:No\.?s?\.?\s*)?(?P<num>[1-9]\d{3,4})(?![0-9A-Za-z_\\/.])"
)
_EO_TAIL_RE = re.compile(r"\s*(?:,\s*(?:and\s+)?|\s+and\s+)(?P<num>[1-9]\d{3,4})(?![0-9A-Za-z_\\/.])")

# 1. `rule:` — House/Senate/Committee Rules, Federal Rules of Procedure, OMB Circulars/Memos, DoD & FERC Orders
_HOUSE_RULE_FWD_RE = re.compile(
    r"\bHouse\s+Rule\s+(?P<rule>[IVXLCDM]+)(?:\s*,?\s*(?:[Cc]lause|[Cc]l\.)\s*(?P<cl>\d+(?:\([0-9A-Za-z]{1,4}\))*))?"
)
_HOUSE_RULE_INV_RE = re.compile(
    r"\b(?:(?P<cl_pre>[Cc]?lause)\s+(?P<cl1>\d+(?:\([0-9A-Za-z]{1,4}\))*)\s+of\s+)?"
    r"[Rr]ule\s+(?P<rule>[IVXLCDM]+)"
    r"(?:\s*,?\s*(?:[Cc]lause|[Cc]l\.)\s*(?P<cl2>\d+(?:\([0-9A-Za-z]{1,4}\))*)\*?)?"
    r"(?:\s+and\s+[Cc]lause\s+(?P<cl3>\d+(?:\([0-9A-Za-z]{1,4}\))*)\s+of\s+[Rr]ule\s+(?P<rule2>[IVXLCDM]+))?"
    r"\s*,?\s*of\s+the\s+(?:Rules\s+of\s+the\s+)?(?:U\.?\s*S\.?\s+)?House(?:\s+of\s+Representatives)?\b"
)
_SENATE_RULE_RE = re.compile(
    r"\bSenate\s+Rules?\s+(?P<r1>[IVXLCDM]+|\d{1,2})(?:\s+and\s+(?P<r2>[IVXLCDM]+|\d{1,2}))?\b"
    r"|\bRules?\s+(?P<sr1>[IVXLCDM]+|\d{1,2})(?:\s+and\s+(?P<sr2>[IVXLCDM]+|\d{1,2}))?\s+of\s+the\s+Standing\s+Rules\s+of\s+the\s+Senate\b"
)
_CMTE_RULE_RE = re.compile(
    r"\b(?:(?P<cmte>Judiciary|Finance|Appropriations|Armed\s+Services|Foreign\s+Relations|Foreign\s+Affairs|Energy\s+and\s+Commerce|Ways\s+and\s+Means|Oversight|Homeland\s+Security|Budget|Rules)\s+)?Committee\s+Rule\s+(?P<r1>\d{1,2}(?:\([a-z0-9]+\))*)"
    r"|\bRule\s+(?P<cr1>\d{1,2}(?:\([a-z0-9]+\))*)(?:\s+and\s+Rule\s+(?P<cr2>\d{1,2}(?:\([a-z0-9]+\))*))?\s+of\s+the\s+(?:Committee\s+Rules|Committee\s+on\s+[A-Z][A-Za-z\s,&]+?|Rules\s+of\s+Procedure\s+(?:of\s+the\s+)?(?:United\s+States\s+)?(?:Senate|House)?\s*Committee\s+on\s+(?:the\s+)?(?P<proc_cmte>[A-Z][A-Za-z]+))"
)
_FED_PROC_RULE_RE = re.compile(
    r"\b(?:Fed\.?\s*R\.?\s*(?P<abbr>Civ|Crim|Evid|App|Bankr)\.?\s*P\.?|Federal\s+Rules?\s+of\s+(?P<full>Civil|Criminal|Evidence|Appellate|Bankruptcy)\s+Procedure)\s*(?:Rule\s*)?(?P<num>\d{1,3}(?:\.\d+)?(?:\([0-9A-Za-z]+\))*)"
)
_FED_PROC_MAP: Mapping[str, str] = {
    "civ": "Civ.",
    "civil": "Civ.",
    "crim": "Crim.",
    "criminal": "Crim.",
    "evid": "Evid.",
    "evidence": "Evid.",
    "app": "App.",
    "appellate": "App.",
    "bankr": "Bankr.",
    "bankruptcy": "Bankr.",
}
_DODI_RULE_RE = re.compile(
    r"\b(?:DoDI|DODI|Department\s+of\s+Defense\s+Instruction)\s+(?P<num>\d{4}\.\d{2}[A-Za-z]?)\b"
)
_DODD_RULE_RE = re.compile(
    r"\b(?:DoDD|DODD|DoD\s+Directive|DOD\s+Directive|Department\s+of\s+Defense\s+Directive)\s+(?P<num>\d{4}\.\d{1,3}[A-Za-z]?)\b"
)
_OMB_RULE_RE = re.compile(
    r"\b(?:OMB|Office\s+of\s+Management\s+and\s+Budget)\s+(?P<kind>Circular|Bulletin|Memorandum|Memoranda)\s*(?:No\.?\s*)?(?P<num>[AM]-\d{1,4}(?:-\d{1,4})?|\d{2}-\d{2})\b"
)
_FERC_ORDER_RE = re.compile(
    r"\b(?:FERC|Federal\s+Energy\s+Regulatory\s+Commission(?:\s*\(FERC\))?)(?:\s+issued)?\s+Order\s+(?:No\.?\s*)?(?P<num>\d{3,4}[A-Z]?)\b"
)

# 2. `rept:` — House/Senate/Conference Committee Reports (`H. Rept. 118-253`, `S. Rept. 117-42`)
_REPT_RE = re.compile(
    r"\b(?P<ch>H\.?\s*Rept?\.?|S\.?\s*Rept?\.?|H\.?R\.?\s*Rep\.?|House\s+Report|Senate\s+Report|Conf\.?\s*Rept?\.?)\s*(?:No\.?\s*)?(?P<cong>[5-9]\d|1[0-3]\d)-(?P<num>[1-9]\d{0,3})\b"
)

# 3. `nom:` — Presidential Nominations (`PN1234`, `PN1234-118`)
_NOM_RE = re.compile(r"\bPN\s*(?P<num>[1-9]\d{0,4})(?:-(?P<cong>[89]\d|1[0-3]\d))?\b")

# 4. `treaty:` — Senate Treaty Docs & Treaty Series (`Treaty Doc. 112-1`, `U.S.T.`, `TIAS`, `U.N.T.S.`)
_TREATY_DOC_RE = re.compile(
    r"\b(?:S\.?\s*)?Treaty\s+Doc(?:ument)?\.?\s*(?:No\.?\s*)?(?P<cong>[89]\d|1[0-3]\d)-(?P<num>[1-9]\d{0,2})\b"
)
_TREATY_UST_RE = re.compile(r"\b(?P<vol>[1-9]\d?)\s+U\.?\s?S\.?\s?T\.?\s+(?P<page>[1-9]\d{0,4})\b")
_TREATY_TIAS_RE = re.compile(r"\bT\.?\s?I\.?\s?A\.?\s?S\.?\s*(?:No\.?\s*)?(?P<num>[1-9]\d{0,5})\b")
_TREATY_UNTS_RE = re.compile(r"\b(?P<vol>[1-9]\d{0,3})\s+U\.?\s?N\.?\s?T\.?\s?S\.?\s+(?P<page>[1-9]\d{0,4})\b")

# 5. `amdt:` — Floor & Committee Amendments
_FLOOR_AMDT_RE = re.compile(r"\b(?P<ch>H|S)\.?\s*Amdt\.?\s*(?:No\.?\s*)?(?P<num>[1-9]\d{0,4})\b")
_HEADER_AMDT_XML_RE = re.compile(r"G:\\M\\\d{1,2}\\[A-Z0-9_-]+\\(?P<code>[A-Z]{3,10}_\d{2,4})\.XML", re.I)
_VOTE_AMDT_CODE_RE = re.compile(
    r"\b(?:AMENDMENT\s*:\s*(?P<c1>[A-Z]{2,8}\d{0,5}_\d{1,3})\b"
    r"|Managers['’]?\s+Amendment\s+(?P<c2>[A-Z]{2,5}\d{4,6})\b"
    r"|AMENDMENT\s+NUMBER\s*:\s*(?P<n1>[1-9]\d{0,3})\b"
    r"|\bAMDT\s*#\s*(?P<n2>[1-9]\d{0,3})\b"
    r"|\bEn\s+Bloc\s*#\s*(?P<eb>[1-9]\d?)\b)",
    re.I,
)
_AMDT_WITH_OFFEROR_RE = re.compile(
    r"Amendment\s*#\s*:?\s*(?P<num>[1-9]\d{0,2}[A-Z]?)\*?(?:\s*\((?P<paren>\d{3})\))?\s+(?:Amendment\s+)?to\s+[^\n]{1,35}?\b[Oo]ffered\s+by\s+(?:Mr\.|Ms\.|Mrs\.|Rep\.|Sen\.)\s+(?P<who>[A-Z][A-Za-z]+(?:\s+[Ll]ee)?)\b"
)
_VOTE_OFFEROR_AMDT_RE = re.compile(
    r"(?:Vote\s+on|Subject|Description|Amendment)\s*:\s*(?:Ranking\s+Member\s+|Mr\.\s+|Ms\.\s+|Mrs\.\s+|Rep\.\s+|Sen\.\s+)?(?P<who>[A-Z][a-z]+(?:\s+Lee)?)\s+(?:[Aa]mendment\s*)?#\s*(?P<num>[1-9]\d{0,2}[A-Z]?)\b"
    r"|Amendment\s*#\s*:?\s*(?P<anum>[1-9]\d{0,2}[A-Z]?)\*?\s*(?:-\s*[A-Z][a-z]+|\(\d{3}\))?(?=\s+(?:Failed|Passed|Agreed))"
)

# 6. `hrg:` & `gpo:` — Hearing Serial Numbers & GPO Jacket Numbers
_HRG_SERIAL_RE = re.compile(r"\bSerial\s+No\.?\s*(?P<cong>[89]\d|1[0-3]\d)-(?P<num>[1-9]\d{0,3}[A-Za-z]?)\b")
_SENATE_HRG_RE = re.compile(r"\bS\.?\s*Hrg\.?\s*(?P<cong>[89]\d|1[0-3]\d)-(?P<num>[1-9]\d{0,4})\b")
_GPO_PDF_RE = re.compile(r"\b(?P<p1>\d{2})-(?P<p2>\d{3})\s*PDF\b")
_GPO_OFFICE_JACKET_RE = re.compile(
    r"U\.S\.\s+GOVERNMENT\s+P(?:RINTING|UBLISHING)\s+OFFICE(?:\s+WASHINGTON\s*:)?\s+(?P<p1>\d{2})-(?P<p2>\d{3})\b"
)

# 7. `jct:` — Joint Committee on Taxation Publications (`JCX-12-24`, `JCS-2-23`)
_JCT_RE = re.compile(r"\b(?P<id>JC[XS]-\d{1,3}-\d{2,4}[A-Za-z]?)\b")

# 8. `gsa:`, `id:` (Senate Legislative Counsel / FC Advisory stamps), `exhibit:`
_GSA_PROSPECTUS_RE = re.compile(r"\b(?P<id>P[A-Z]{2}-\d{2,4}(?:/\d{2,4})?-[A-Z]{2}\d{2})\b")
_SLC_STAMP_ID_RE = re.compile(r"^\s*(?P<slc>[A-Z]{3}\d{2}[A-Z0-9]{3})\s+S\.L\.C\.\b|^\s*(?P<drn>DRN\d{5})\b")
_ADVISORY_FC_ID_RE = re.compile(r"\bNo\.\s+(?P<fc>FC-\d{1,3})\b")
_VOTE_FC_ID_RE = re.compile(r"\bRecord\s+vote\s+no\.?\s*(?:No\s+Wdrn\s+Nays\s+\d+\s+Prsnt\s+)?(?P<fc>FC-\d{1,3})\b", re.I)
_EXHIBIT_FN_RE = re.compile(
    r"^(?:(?P<tab>T\d+)-)?(?:\d+-)?Exhibit[\s_-]+(?P<ex>(?=[A-Z0-9]*\d)[A-Z0-9]{1,5})(?:[\s_-]|$)", re.I
)
_EXHIBIT_HRG_TEXT_RE = re.compile(r"\b(?P<prefix>[A-Z]{2,6}\s+(?:[A-Z]{2,6}\s+)?Hearing\s+Exhibit\s+N\.?\s*\d{1,4})\b")

_BILL_AMEND_ACT_HEAD_RE = re.compile(
    r"\bTo\s+amend\s+the\s+([A-Z][A-Za-z0-9'&,\-\s]{3,90}?\bAct(?:\s+of\s+(?:1[89]\d\d|20\d\d))?)\b"
)


# ---------------------------------------------------------------------------
# `N9` — Proposed-Bill `short_titles[]` & `fiscal_years[]` Extractors
# ---------------------------------------------------------------------------

_SHORT_TITLE_CITED_RE = re.compile(
    r'may\s+be\s+cited\s+as\s+(?:the\s+)?"([^"\n]{3,160}?)"'
    r'(?:\s+or\s+(?:as\s+)?(?:the\s+)?"([^"\n]{3,120}?)")?',
    re.IGNORECASE,
)
_FACILITY_DESIGNATION_RE = re.compile(
    r'To\s+designate\s+the\s+facility\s+of\s+the\s+United\s+States\s+Postal\s+Service\b[^."]{1,180}?\bas\s+the\s+"([^"\n]{5,140}?)"',
    re.IGNORECASE,
)

_FY_PATTERNS_V6: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:(?P<fy_caps>FY)|(?i:fiscal\s+years?))\s*['’]?(?P<y1>(?:19|20)\d{2}|\d{2})"
        r"(?:\s*(?:[-–—]|(?i:to|through|thru|and))\s*(?:(?i:FY|fiscal\s+year)\s*)?['’]?(?P<y2>(?:19|20)\d{2}|\d{2}))?\b"
    ),
    re.compile(r"\bfiscal\s+year\s+ending\s+September\s+30,\s*(?P<y1>(?:19|20)\d{2})\b", re.IGNORECASE),
)


def extract_short_titles_v6(text: str, filename: str = "") -> list[str]:
    """Extract `100%`-precision statutory/proposed short titles (`may be cited as "..."` + GPO quote normalization)."""
    if not text:
        return []
    norm = normalize_gpo_glyphs_v6(text)
    out: list[str] = []
    for m in _SHORT_TITLE_CITED_RE.finditer(norm):
        for grp in (1, 2):
            raw = m.group(grp)
            if not raw:
                continue
            val = re.sub(r"\s+", " ", raw).strip().rstrip(".,;:")
            val = re.sub(r"([A-Za-z])-\s+([a-z])", r"\1\2", val)
            if len(val) >= 3 and val not in out:
                out.append(val)
    if not out:
        for m in _FACILITY_DESIGNATION_RE.finditer(norm[:800]):
            val = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(".,;:")
            if len(val) >= 5 and val not in out:
                out.append(val)
    return out[:8]


def extract_fiscal_years_v6(text: str, filename: str = "") -> list[int]:
    """Extract `100%`-precision `fiscal_years[]` (`FY 2024`, `Fiscal Year 2025`, `September 30, YYYY`, range expansion)."""
    if not text:
        return []
    norm = _normalize_dashes(text)
    out: list[int] = []
    for pat in _FY_PATTERNS_V6:
        for m in pat.finditer(norm):
            gd = m.groupdict()
            y1_s = gd["y1"]
            if len(y1_s) == 2:
                if not gd.get("fy_caps"):
                    continue
                y1_i = int(y1_s)
                y1 = (2000 + y1_i) if y1_i <= 40 else (1900 + y1_i if y1_i >= 80 else None)
                if y1 is None:
                    continue
            else:
                y1 = int(y1_s)
            if not (1950 <= y1 <= 2050):
                continue
            y2_s = gd.get("y2")
            if y2_s:
                y2 = ((y1 // 100) * 100 + int(y2_s)) if len(y2_s) == 2 else int(y2_s)
                if y1 <= y2 <= y1 + 11:
                    for yr in range(y1, y2 + 1):
                        if yr not in out:
                            out.append(yr)
                    continue
            if y1 not in out:
                out.append(y1)
    return out[:12]


# ---------------------------------------------------------------------------
# Unified Citation & Signal Engine (`extract_citations_and_signals_v6`)
# ---------------------------------------------------------------------------


def is_legislative_draft_context_v6(filename: str, text: str, primary_kind: str | None = None) -> bool:
    """Detect legislative drafting genres where proposed new U.S.C. sections (`TRAP_1`) are legitimate."""
    if primary_kind in LEGISLATIVE_DRAFT_KINDS_V6:
        return True
    fn_u = (filename or "").upper()
    if fn_u.startswith("BILLS-") or "AMDT" in fn_u or "AMEND" in fn_u:
        return True
    head = (text or "")[:1200]
    return bool(
        re.search(r"\b(?:A\s+BILL|AN\s+ACT|AMENDMENT\s+(?:IN\s+THE\s+NATURE|TO\b)|may\s+be\s+cited\s+as)\b", head, re.I)
    )


def _is_committee_rules_context(filename: str, text: str, primary_kind: str | None = None) -> bool:
    if primary_kind == "committee_rules":
        return True
    if "rules_of_the_committee" in (filename or "").lower():
        return True
    return bool(
        re.search(r"^\s*RULES\s+OF\s+(?:THE\s+)?(?:PROCEDURE\s+OF\s+THE\s+)?COMMITTEE\s+ON\b", (text or "")[:400], re.I)
    )


def normalize_ref_key_v6(ref_str: str, act_index: ActIndexV6 | None = None) -> str:
    """Canonical semantic identity key for deduplicating and comparing `DocMetaV4Causal.refs[]` items."""
    s = _normalize_dashes((ref_str or "").strip())
    if ":" not in s:
        return s.lower()
    pref, val = s.split(":", 1)
    pref = pref.strip().lower()
    val = val.strip()
    if pref == "bill":
        val_c = re.sub(r"^\d{2,3}[:\-]", "", val)
        bt = bill_type_and_number_v6(val_c)
        if bt:
            return f"bill:{bt[0]}-{int(bt[1])}"
    elif pref == "law":
        m_pl = re.search(r"(?:pub(?:lic)?\.?\s*l(?:aw)?\.?|p\.?\s*l\.?)\s*(?:no\.?\s*)?(\d{2,3})\s*-\s*(\d+)", val, re.I)
        if m_pl:
            return f"law:pl-{int(m_pl.group(1))}-{int(m_pl.group(2))}"
        m_st = re.match(r"^([1-9]\d{0,3}[A-Z]?)\s*Stat\.?\s*([1-9]\d{0,4}(?:[A-Z]-\d{1,4})?)", val, re.I)
        if m_st:
            return f"law:stat-{m_st.group(1).upper()}-{m_st.group(2).upper()}"
        m_actsec = re.match(r"^(.+?)(?:,?\s*(?:sec(?:tion)?\.?|§)\s*)(\d+[A-Za-z0-9()-]*)$", val, re.I)
        if m_actsec:
            ak = normalize_popular_name_v6(re.sub(r"\([^)]*\)", "", m_actsec.group(1)))
            rk = (resolve_act_name_v6(ak, act_index) if act_index else None) or ak
            sec_b = re.match(r"^(\d+[A-Za-z]*)", m_actsec.group(2))
            sec_k = sec_b.group(1).lower() if sec_b else m_actsec.group(2).lower()
            return f"law:actsec-{rk}-{sec_k}"
        ak = normalize_popular_name_v6(re.sub(r"\([^)]*\)", "", val))
        rk = (resolve_act_name_v6(ak, act_index) if act_index else None) or ak
        return f"law:act-{rk}"
    elif pref == "usc":
        if re.match(r"^(?:I\.?R\.?C\.?|Internal\s+Revenue\s+Code)", val, re.I):
            m_s = re.search(r"(\d+[A-Za-z]*)", val)
            if m_s:
                return f"usc:26-{m_s.group(1).lower()}"
        m_app = re.match(r"^(\d+)\s*U\.?S\.?C\.?\s*App(?:endix|\.)?\s*$", val, re.I)
        if m_app:
            return f"usc:{int(m_app.group(1))}a-app"
        m_u = re.match(r"^(\d+)\s*U\.?S\.?C\.?(\s+App\.?)?\s*(?:§+\s*)?(\d+[A-Za-z0-9-]*)", val, re.I)
        if m_u:
            return f"usc:{int(m_u.group(1))}{'a' if m_u.group(2) else ''}-{m_u.group(3).lower()}"
    elif pref == "cfr":
        m_c = re.match(r"^(\d+)\s*C\.?\s*F\.?\s*R\.?\s*(?:Part\s*)?(\d+[A-Za-z]?)(?:\.(\d+[A-Za-z0-9-]*))?", val, re.I)
        if m_c:
            if m_c.group(3):
                return f"cfr:{int(m_c.group(1))}-{m_c.group(2).lower()}.{m_c.group(3).lower()}"
            return f"cfr:{int(m_c.group(1))}-part-{m_c.group(2).lower()}"
    elif pref == "rule":
        m_hr = re.search(r"Rule\s+([IVXLCDM]+)(?:.*?(?:clause|cl\.)\s*(\d+(?:\([0-9A-Za-z]+\))*))?", val, re.I)
        if m_hr and ("house" in val.lower() or "clause" in val.lower()):
            r_rom = m_hr.group(1).lower()
            cl = m_hr.group(2)
            if not cl:
                m_cpre = re.search(r"clause\s+(\d+(?:\([0-9A-Za-z]+\))*)", val, re.I)
                cl = m_cpre.group(1) if m_cpre else None
            return f"rule:house-{r_rom}-{cl.lower()}" if cl else f"rule:house-{r_rom}"
        m_cm = re.search(r"Committee\s+Rule\s+(\d+(?:\([a-z0-9]+\))*)", val, re.I)
        if m_cm:
            return f"rule:cmte-{m_cm.group(1).lower()}"
    elif pref == "gpo":
        m_g = re.search(r"(\d{2}-\d{3})", val)
        if m_g:
            return f"gpo:{m_g.group(1)}"
    elif pref == "hrg":
        m_h = re.search(r"Serial\s+No\.?\s*(\d+-\d+[A-Za-z]?)", val, re.I)
        if m_h:
            return f"hrg:serial-{m_h.group(1).lower()}"
    elif pref == "id":
        m_rc = re.search(r"Roll\s+Call(?:\s+Vote)?\s*#?\s*(\d+)", val, re.I)
        if m_rc:
            return f"id:rollcall-{int(m_rc.group(1))}"
        m_fc = re.search(r"(FC-\d+)", val, re.I)
        if m_fc:
            return f"id:{m_fc.group(1).lower()}"
    elif pref == "amdt":
        m_eb = re.search(r"En\s+Bloc\s*#?\s*(\d+)", val, re.I)
        if m_eb:
            return f"amdt:enbloc-{int(m_eb.group(1))}"
        m_an = re.match(r"^Amendment\s*#?\s*(\d+[A-Za-z]?)$", val, re.I)
        if m_an:
            return f"amdt:num-{m_an.group(1).lower()}"
        m_wh = re.match(r"^([A-Za-z]+(?:\s+Lee)?)\s+(?:[Aa]mendment\s*)?(?:#|No\.?\s*)(\d+[A-Za-z]?)", val, re.I)
        if m_wh:
            return f"amdt:{m_wh.group(1).lower()}-{m_wh.group(2).lower()}"
    elif pref == "exhibit":
        m_ex = re.search(r"(?:Exhibit[\s_-]+|N\.?\s*)([A-Z0-9]{1,5})$", val, re.I)
        if m_ex:
            return f"exhibit:{m_ex.group(1).lower()}"
    norm_val = " ".join(val.lower().split())
    return f"{pref}:{norm_val}"


def extract_citations_and_signals_v6(
    text: str | None,
    *,
    filename: str = "",
    congress: int | None = None,
    primary_kind: str | None = None,
    measure_keys: Sequence[str] | None = None,
    oracles: RefSpecOraclesV6 | None = None,
    auto_load_oracles: bool = True,
) -> dict[str, Any]:
    """Run unified `N8-N9` deterministic citation, `urn:rkaf` cross-walk, `short_titles[]` & `fiscal_years[]` extraction."""
    raw_text = text or ""
    if oracles is None and auto_load_oracles:
        oracles = get_cached_refspec_oracles_v6()
    orc = oracles or RefSpecOraclesV6()

    glyph_text = normalize_gpo_glyphs_v6(raw_text)
    clean_text = strip_bill_margin_line_numbers_v6(glyph_text)
    dash_text = _normalize_dashes(clean_text)

    draft_ctx = is_legislative_draft_context_v6(filename, dash_text, primary_kind)
    cmte_rules_ctx = _is_committee_rules_context(filename, dash_text, primary_kind)

    det_refs: list[str] = []
    seen_keys: set[str] = set()
    det_act_iris: list[str] = []
    usc_oracle_invalid_refs: list[str] = []

    def _add_ref(ref_str: str, dedup_key: str | None = None) -> None:
        k = dedup_key or normalize_ref_key_v6(ref_str, orc.act_index)
        if k not in seen_keys and len(det_refs) < 25:
            seen_keys.add(k)
            det_refs.append(ref_str)

    # 1. Bills (`N8a`)
    for bh in find_bill_citations_v6(clean_text, filename=filename, congress=congress, measure_keys=measure_keys):
        _add_ref(bh.display_ref, f"bill:{bh.bill_type}-{bh.number}")

    # 2. U.S.C. + I.R.C. + `UscSectionOracle` (`N8b` + `TRAP_1` + `TRAP_5`)
    for uh in find_usc_citations_v6(clean_text, allow_proposed_amendatory=draft_ctx):
        if uh.appendix and uh.section == "App.":
            _add_ref(f"usc:{uh.title} U.S.C. App.", f"usc:{uh.title}a-app")
            continue
        endpoints = [uh.section]
        if uh.section_end and uh.span_rule == "stated":
            endpoints.append(uh.section_end)
        for sec_tok in endpoints:
            disp_str = (
                f"usc:IRC Section {sec_tok}"
                if uh.is_irc
                else f"usc:{uh.title} U.S.C.{' App.' if uh.appendix else ''} {sec_tok}"
            )
            if orc.usc_oracle is not None:
                sv = orc.usc_oracle.section_verdict(uh.title, sec_tok, appendix=uh.appendix)
                disp_v = sv.disposition.verdict if sv.disposition is not None else None
                eff_cong = congress if isinstance(congress, int) else 118
                is_invalid_non_draft = sv.verdict == "absent" or (
                    sv.verdict == "unknown"
                    and disp_v in {"repealed-no-successor", "not-in-table"}
                    and eff_cong >= 105
                )
                # TRAP_1: Filter absent / post-1994 repealed U.S.C. cites ONLY on non-legislative-drafting genres!
                if is_invalid_non_draft and not draft_ctx:
                    if disp_str not in usc_oracle_invalid_refs:
                        usc_oracle_invalid_refs.append(disp_str)
                    continue
            _add_ref(disp_str, f"usc:{uh.title}{'a' if uh.appendix else ''}-{sec_tok.lower()}")

    # 3. CFR (`N8b` + `TRAP_5`)
    for ch in find_cfr_citations_v6(clean_text):
        if ch.section:
            _add_ref(f"cfr:{ch.title} CFR {ch.part}.{ch.section}", f"cfr:{ch.title}-{ch.part.lower()}.{ch.section.lower()}")
        else:
            _add_ref(f"cfr:{ch.title} CFR Part {ch.part}", f"cfr:{ch.title}-part-{ch.part.lower()}")

    # 4. Public Laws & Statutes at Large (`N8b` + `N8c`)
    pl_hits = find_public_law_citations_v6(clean_text)
    for pl in pl_hits:
        _add_ref(f"law:Pub. L. {pl.congress}-{pl.number}", f"law:pl-{pl.congress}-{pl.number}")

    for st in find_statute_citations_v6(clean_text):
        if st.matches_adjacent_pl is False:
            continue
        # Skip redundant parallel Stat. cite immediately adjacent to an already-extracted Public Law
        if st.adjacent_pl_exists or any(0 <= st.start - pl.end <= 24 for pl in pl_hits):
            continue
        # If OLRC Popular Names maps this exact (vol, page) to a numbered Pub. L. (e.g. OCR-corrupted `Public La1'r 9 113-66; 127 Stat. 1047`), emit Pub. L.!
        mapped_pl = orc.act_index.stat_to_pl.get((st.volume, st.page)) if orc.act_index is not None else None
        if mapped_pl and "-" in mapped_pl:
            c_s, _, n_s = mapped_pl.partition("-")
            _add_ref(f"law:Pub. L. {int(c_s)}-{int(n_s)}", f"law:pl-{int(c_s)}-{int(n_s)}")
        else:
            _add_ref(f"law:{st.volume} Stat. {st.page}", f"law:stat-{st.volume.upper()}-{st.page.upper()}")

    # 5. `RefSpec` Act-Relative Citations + OLRC Table III / SourceCredit Crosswalk + Maximal-NP Acts (`TRAP_3` & `TRAP_4`)
    emitted_act_roots: set[str] = set()
    if orc.act_index is not None:
        act_names = orc.act_index.all_act_names
        for ar in find_act_relative_occurrences_v6(clean_text, act_names=act_names):
            # Internal Revenue Code sections belong under `usc:IRC Section N`, never `law:`!
            if ar.act_key.startswith("internal revenue code") or ar.act_key == "i.r.c":
                if orc.usc_oracle is None or orc.usc_oracle.section_verdict(26, ar.section).verdict != "absent" or draft_ctx:
                    _add_ref(f"usc:IRC Section {ar.section}", f"usc:26-{ar.section.lower()}")
                continue
            res = resolve_act_relative_citation_v6(ar, index=orc.act_index, source_credits=orc.source_credits)
            if res.iri and res.iri not in det_act_iris:
                det_act_iris.append(res.iri)
            rk = resolve_act_name_v6(ar.act_key, orc.act_index) or ar.act_key
            emitted_act_roots.add(rk)
            clean_act = re.sub(r"^(?:the|The)\s+", "", ar.act_name).strip()
            _add_ref(f"law:{clean_act}, section {ar.section}", f"law:actsec-{rk}-{ar.section.lower()}")

    resolved_popular_acts = find_maximal_popular_acts_v6(clean_text, orc.act_index)
    if draft_ctx and orc.act_index is not None:
        for m_am in _BILL_AMEND_ACT_HEAD_RE.finditer(clean_text[:700]):
            cand = re.sub(r"\s+", " ", m_am.group(1)).strip()
            rk = resolve_act_name_v6(cand, orc.act_index)
            if rk and rk not in emitted_act_roots:
                emitted_act_roots.add(rk)
                _add_ref(f"law:{cand}", f"law:act-{rk}")

    # 6. Federal Register (`N8b`)
    for frh in find_federal_register_citations_v6(clean_text):
        _add_ref(f"fr:{frh.volume} FR {frh.page}", f"fr:{frh.volume}-{frh.page}")

    # 7. Agency / Regulatory IDs (`gao:`, `crs:`, `docket:`, `id:RIN`) (`N8c`)
    for m in _GAO_ID_RE.finditer(dash_text):
        gid = m.group(0).upper()
        _add_ref(f"gao:{gid}", f"gao:{gid.lower()}")
    for m in _CRS_ID_RE.finditer(dash_text):
        cid = m.group(0)
        _add_ref(f"crs:{cid}", f"crs:{cid.lower()}")
    dockets, rins = _detect_dockets_and_rins_v6(clean_text)
    for dk in dockets:
        _add_ref(f"docket:{dk}", f"docket:{dk.lower()}")
    for rv in rins:
        _add_ref(f"id:RIN {rv}", f"id:rin-{rv.lower()}")

    # 8. Executive Orders (`N8d` + `TRAP_2`: `1 <= eo_num <= 14420`, XML path block, `EoRosterOracle`)
    for pat in (_EO_SPELLED_RE, _EO_ABBR_RE):
        for m in pat.finditer(dash_text):
            nums = [int(m.group("num"))]
            pos = m.end()
            while (tm := _EO_TAIL_RE.match(dash_text, pos)) is not None:
                nums.append(int(tm.group("num")))
                pos = tm.end()
            for eo_n in nums:
                if 1 <= eo_n <= EO_HIGHEST_KNOWN_V6:
                    if orc.eo_oracle is not None and orc.eo_oracle.verdict(eo_n).verdict == "absent":
                        continue
                    _add_ref(f"eo:E.O. {eo_n}", f"eo:{eo_n}")

    # 9. 8 Ultra-Strict Congressional-Procedural Regex Families (`N8e`)
    # 9a. `rule:`
    house_rules_cl: list[tuple[str, str]] = []
    house_rules_bare: list[str] = []
    for m in _HOUSE_RULE_FWD_RE.finditer(dash_text):
        r_rom, cl = m.group("rule"), m.group("cl")
        if cl and not cmte_rules_ctx:
            house_rules_cl.append((r_rom, re.sub(r"\(S\)", "(5)", cl)))
        else:
            house_rules_bare.append(r_rom)
    for m in _HOUSE_RULE_INV_RE.finditer(dash_text):
        r_rom = m.group("rule")
        cl = m.group("cl1") or m.group("cl2")
        if cl and not cmte_rules_ctx:
            house_rules_cl.append((r_rom, re.sub(r"\(S\)", "(5)", cl)))
        else:
            house_rules_bare.append(r_rom)
        if m.group("rule2") and m.group("cl3") and not cmte_rules_ctx:
            house_rules_cl.append((m.group("rule2"), m.group("cl3")))

    cl_roms = {r_rom.lower() for r_rom, _ in house_rules_cl}
    for r_rom, cl in house_rules_cl:
        _add_ref(f"rule:House Rule {r_rom}, clause {cl}", f"rule:house-{r_rom.lower()}-{cl.lower()}")
    for r_rom in house_rules_bare:
        if r_rom.lower() not in cl_roms:
            _add_ref(f"rule:House Rule {r_rom}", f"rule:house-{r_rom.lower()}")

    for m in _SENATE_RULE_RE.finditer(dash_text):
        r1 = m.group("r1") or m.group("sr1")
        r2 = m.group("r2") or m.group("sr2")
        if r2:
            _add_ref(f"rule:Senate Rules {r1} and {r2}", f"rule:senate-{r1.lower()}-{r2.lower()}")
        else:
            _add_ref(f"rule:Senate Rule {r1}", f"rule:senate-{r1.lower()}")

    for m in _CMTE_RULE_RE.finditer(dash_text):
        if m.group("r1"):
            cm = (m.group("cmte") or "").strip()
            pref = f"{cm} Committee Rule" if cm else "Committee Rule"
            _add_ref(f"rule:{pref} {m.group('r1')}", f"rule:cmte-{m.group('r1').lower()}")
        else:
            p_cm = (m.group("proc_cmte") or "").strip()
            pref = f"{p_cm} Committee Rule" if p_cm else "Committee Rule"
            _add_ref(f"rule:{pref} {m.group('cr1')}", f"rule:cmte-{m.group('cr1').lower()}")
            if m.group("cr2"):
                _add_ref(f"rule:{pref} {m.group('cr2')}", f"rule:cmte-{m.group('cr2').lower()}")

    for m in _FED_PROC_RULE_RE.finditer(dash_text):
        k = (m.group("abbr") or m.group("full")).lower()
        num = m.group("num")
        _add_ref(f"rule:Fed. R. {_FED_PROC_MAP[k]} P. {num}", f"rule:frp-{_FED_PROC_MAP[k].lower()}-{num.lower()}")

    for m in _DODI_RULE_RE.finditer(dash_text):
        _add_ref(f"rule:DoDI {m.group('num')}", f"rule:dodi-{m.group('num').lower()}")
    for m in _DODD_RULE_RE.finditer(dash_text):
        _add_ref(f"rule:DoDD {m.group('num')}", f"rule:dodd-{m.group('num').lower()}")
    for m in _OMB_RULE_RE.finditer(dash_text):
        k = "Memorandum" if m.group("kind").startswith("Memorand") else m.group("kind")
        _add_ref(f"rule:OMB {k} {m.group('num')}", f"rule:omb-{m.group('num').lower()}")
    for m in _FERC_ORDER_RE.finditer(dash_text):
        _add_ref(f"rule:FERC Order {m.group('num')}", f"rule:ferc-order-{m.group('num').lower()}")

    # 9b. `rept:`
    for m in _REPT_RE.finditer(dash_text):
        ch_raw = m.group("ch").lower()
        lbl = (
            "S. Rept."
            if ch_raw.startswith(("s", "senate"))
            else ("Conf. Rept." if ch_raw.startswith("conf") else "H. Rept.")
        )
        c_n, r_n = int(m.group("cong")), int(m.group("num"))
        _add_ref(f"rept:{lbl} {c_n}-{r_n}", f"rept:{lbl[0].lower()}-{c_n}-{r_n}")

    # 9c. `nom:`
    for m in _NOM_RE.finditer(dash_text):
        n_num = int(m.group("num"))
        _add_ref(f"nom:PN{n_num}", f"nom:pn{n_num}")

    # 9d. `treaty:`
    for m in _TREATY_DOC_RE.finditer(dash_text):
        c_n, t_n = int(m.group("cong")), int(m.group("num"))
        _add_ref(f"treaty:Treaty Doc. {c_n}-{t_n}", f"treaty:tdoc-{c_n}-{t_n}")
    for m in _TREATY_UST_RE.finditer(dash_text):
        _add_ref(f"treaty:{m.group('vol')} U.S.T. {m.group('page')}", f"treaty:ust-{m.group('vol')}-{m.group('page')}")
    for m in _TREATY_TIAS_RE.finditer(dash_text):
        _add_ref(f"treaty:TIAS {m.group('num')}", f"treaty:tias-{m.group('num')}")
    for m in _TREATY_UNTS_RE.finditer(dash_text):
        _add_ref(f"treaty:{m.group('vol')} U.N.T.S. {m.group('page')}", f"treaty:unts-{m.group('vol')}-{m.group('page')}")

    # 9e. `amdt:`
    for m in _FLOOR_AMDT_RE.finditer(dash_text):
        ch = m.group("ch").upper()
        n = int(m.group("num"))
        _add_ref(f"amdt:{ch}. Amdt. {n}", f"amdt:{ch.lower()}amdt-{n}")
    if "Amdt-" in (filename or "") or primary_kind == "committee_amendment":
        for m in _HEADER_AMDT_XML_RE.finditer(dash_text[:450]):
            code = m.group("code").upper()
            _add_ref(f"amdt:{code}", f"amdt:{code.lower()}")

    offeror_matched = False
    for m in _AMDT_WITH_OFFEROR_RE.finditer(dash_text[:500]):
        who = m.group("who").title()
        num = m.group("num")
        paren = f" ({m.group('paren')})" if m.group("paren") else ""
        _add_ref(f"amdt:{who} #{num}{paren}", f"amdt:{who.lower()}-{num.lower()}")
        offeror_matched = True

    for m in _VOTE_AMDT_CODE_RE.finditer(dash_text):
        if m.group("c1"):
            _add_ref(f"amdt:{m.group('c1')}", f"amdt:{m.group('c1').lower()}")
        elif m.group("c2"):
            _add_ref(f"amdt:{m.group('c2')}", f"amdt:{m.group('c2').lower()}")
        elif m.group("n1"):
            _add_ref(f"amdt:Amendment {m.group('n1')}", f"amdt:num-{int(m.group('n1'))}")
        elif m.group("n2"):
            _add_ref(f"amdt:Amendment #{m.group('n2')}", f"amdt:num-{int(m.group('n2'))}")
        elif m.group("eb"):
            _add_ref(f"amdt:En Bloc #{m.group('eb')}", f"amdt:enbloc-{int(m.group('eb'))}")

    for m in _VOTE_OFFEROR_AMDT_RE.finditer(dash_text):
        if m.group("who") and m.group("num"):
            w, n = m.group("who"), m.group("num")
            _add_ref(f"amdt:{w} #{n}", f"amdt:{w.lower()}-{n.lower()}")
        elif m.group("anum") and not offeror_matched:
            n = m.group("anum")
            _add_ref(f"amdt:Amendment #{n}", f"amdt:num-{n.lower()}")

    # 9f. `hrg:` & `gpo:`
    for m in _HRG_SERIAL_RE.finditer(dash_text):
        _add_ref(
            f"hrg:Serial No. {int(m.group('cong'))}-{m.group('num')}",
            f"hrg:serial-{int(m.group('cong'))}-{m.group('num').lower()}",
        )
    for m in _SENATE_HRG_RE.finditer(dash_text):
        _add_ref(
            f"hrg:S. Hrg. {int(m.group('cong'))}-{m.group('num')}",
            f"hrg:shrg-{int(m.group('cong'))}-{m.group('num').lower()}",
        )
    for m in _GPO_PDF_RE.finditer(dash_text):
        _add_ref(f"gpo:{m.group('p1')}-{m.group('p2')} PDF", f"gpo:{m.group('p1')}-{m.group('p2')}")
    for m in _GPO_OFFICE_JACKET_RE.finditer(dash_text):
        _add_ref(f"gpo:{m.group('p1')}-{m.group('p2')}", f"gpo:{m.group('p1')}-{m.group('p2')}")

    # 9g. `jct:`
    for m in _JCT_RE.finditer(dash_text):
        jid = m.group("id").upper()
        _add_ref(f"jct:{jid}", f"jct:{jid.lower()}")

    # 9h. `gsa:`, `id:` (SLC / FC stamps), `exhibit:`
    for m in _GSA_PROSPECTUS_RE.finditer(dash_text):
        gid = m.group("id").upper()
        _add_ref(f"gsa:{gid}", f"gsa:{gid.lower()}")
    for m in _VOTE_FC_ID_RE.finditer(dash_text):
        fc = m.group("fc").upper()
        _add_ref(f"id:{fc}", f"id:{fc.lower()}")
    for m in _SLC_STAMP_ID_RE.finditer(dash_text[:200]):
        st = (m.group("slc") or m.group("drn")).upper()
        _add_ref(f"id:{st}", f"id:{st.lower()}")
    if "advisory" in (filename or "").lower():
        for m in _ADVISORY_FC_ID_RE.finditer(dash_text[:400]):
            fc = m.group("fc").upper()
            _add_ref(f"id:{fc}", f"id:{fc.lower()}")

    m_ex_fn = _EXHIBIT_FN_RE.search(filename or "")
    if m_ex_fn:
        ex_id = m_ex_fn.group("ex").upper()
        _add_ref(f"exhibit:Exhibit {ex_id}", f"exhibit:{ex_id.lower()}")
    else:
        for m_ex_t in _EXHIBIT_HRG_TEXT_RE.finditer(dash_text[:500]):
            p_str = re.sub(r"\s+", " ", m_ex_t.group("prefix")).strip()
            m_n = re.search(r"N\.?\s*(\d+)", p_str)
            _add_ref(f"exhibit:{p_str}", f"exhibit:{m_n.group(1) if m_n else p_str.lower()}")

    # Sidecar: Federal Court Reporter citations (kept out of `refs[]` per `refspec_capabilities.md` §2)
    parsed_case_citations: list[str] = []
    for m in _CASE_REPORTER_RE.finditer(dash_text):
        rep = re.sub(r"\s+", " ", m.group("reporter")).strip()
        cs_str = f"{m.group('volume')} {rep} {m.group('page')}"
        if cs_str not in parsed_case_citations:
            parsed_case_citations.append(cs_str)

    # N9: Proposed-bill `short_titles[]` & `fiscal_years[]`
    det_short_titles = extract_short_titles_v6(raw_text, filename=filename)
    det_fiscal_years = extract_fiscal_years_v6(raw_text, filename=filename)

    return {
        "det_refs": det_refs,
        "det_act_iris": det_act_iris,
        "det_short_titles": det_short_titles,
        "det_fiscal_years": det_fiscal_years,
        "usc_oracle_invalid_refs": usc_oracle_invalid_refs,
        "resolved_popular_acts": resolved_popular_acts,
        "parsed_case_citations": parsed_case_citations,
        "is_legislative_draft": draft_ctx,
    }


def merge_citations_post_pass_v6(
    docmeta: dict[str, Any],
    signals: Mapping[str, Any],
    *,
    primary_kind: str | None = None,
    oracles: RefSpecOraclesV6 | None = None,
) -> dict[str, Any]:
    """Post-pass helper merging deterministic `refs`, `short_titles`, and `fiscal_years` while pruning absent U.S.C. hallucinations."""
    if docmeta.get("status") in {"error_or_block", "stub_or_blank", "ocr_unreadable"}:
        return docmeta

    pk = primary_kind or docmeta.get("primary_kind")
    draft_ctx = pk in LEGISLATIVE_DRAFT_KINDS_V6 or bool(signals.get("is_legislative_draft"))
    orc = oracles or next(iter(_CACHED_ORACLES_BY_ROOT.values()), None)
    act_idx = orc.act_index if orc is not None else None
    usc_orc = orc.usc_oracle if orc is not None else None
    invalid_set = set(signals.get("usc_oracle_invalid_refs") or ())

    # 1. Merge `refs[]` (<= 25), filtering non-draft absent U.S.C. hallucinations
    existing_refs = [str(r).strip() for r in (docmeta.get("refs") or ()) if isinstance(r, str) and str(r).strip()]
    merged_refs: list[str] = []
    seen_ref_keys: set[str] = set()

    for r_str in existing_refs:
        if not draft_ctx:
            if r_str in invalid_set:
                continue
            m_u = re.match(r"^usc:\s*(\d+)\s*(?:U\.?S\.?C\.?)?(\s+App\.?)?\s*(?:§+\s*)?(\d+[A-Za-z0-9-]*)", r_str, re.I)
            if m_u:
                u_t, u_app, u_s = int(m_u.group(1)), bool(m_u.group(2)), m_u.group(3)
                if not _usc_title_is_possible(u_t):
                    continue
                if usc_orc is not None:
                    sv = usc_orc.section_verdict(u_t, u_s, appendix=u_app)
                    disp_v = sv.disposition.verdict if sv.disposition is not None else None
                    eff_cong = docmeta.get("congress") if isinstance(docmeta.get("congress"), int) else 118
                    if sv.verdict == "absent" or (
                        sv.verdict == "unknown"
                        and disp_v in {"repealed-no-successor", "not-in-table"}
                        and eff_cong >= 105
                    ):
                        continue
        rk = normalize_ref_key_v6(r_str, act_idx)
        if rk not in seen_ref_keys and len(merged_refs) < 25:
            seen_ref_keys.add(rk)
            merged_refs.append(r_str)

    for d_ref in signals.get("det_refs") or ():
        if not isinstance(d_ref, str) or not d_ref.strip():
            continue
        rk = normalize_ref_key_v6(d_ref, act_idx)
        if rk not in seen_ref_keys and len(merged_refs) < 25:
            seen_ref_keys.add(rk)
            merged_refs.append(d_ref)

    if merged_refs:
        docmeta["refs"] = merged_refs[:25]
    elif "refs" in docmeta:
        del docmeta["refs"]

    # 2. Merge `short_titles[]` (<= 8)
    existing_st = [str(x).strip() for x in (docmeta.get("short_titles") or ()) if isinstance(x, str) and str(x).strip()]
    seen_st = {x.lower() for x in existing_st}
    for st in signals.get("det_short_titles") or ():
        if isinstance(st, str) and st.strip() and st.strip().lower() not in seen_st and len(existing_st) < 8:
            seen_st.add(st.strip().lower())
            existing_st.append(st.strip())
    if existing_st:
        docmeta["short_titles"] = existing_st[:8]

    # 3. Merge `fiscal_years[]` (<= 12)
    existing_fy = [int(x) for x in (docmeta.get("fiscal_years") or ()) if isinstance(x, int) and not isinstance(x, bool)]
    for fy in signals.get("det_fiscal_years") or ():
        if isinstance(fy, int) and 1900 <= fy <= 2100 and fy not in existing_fy and len(existing_fy) < 12:
            existing_fy.append(fy)
    if existing_fy:
        docmeta["fiscal_years"] = existing_fy[:12]

    return docmeta
