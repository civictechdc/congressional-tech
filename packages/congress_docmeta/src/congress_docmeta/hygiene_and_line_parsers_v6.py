#!/usr/bin/env python3
"""Stage 1 (`N1–N4`) Text Hygiene & `N11` Line-Anchored Parsers (`hygiene_and_line_parsers_v6.py`).

100% Python standard-library runtime module (`/usr/bin/python3 -B -I -S` verified, zero third-party
dependencies) providing:
  - `N1`: `\n`-preserved `p12` GPO page & quote-glyph normalization (`normalize_gpo_pages`,
    `normalize_gpo_glyphs`, `normalize_p12_pages_v6`) exposing blank scans disguised by GPO
    `VerDate`/`Jkt`/`PO 00000` footers (`gpo_blank_after_strip`).
  - `N2`: GPO symbol-font (`BGsddV01` / `AGsddV01` / `CGsddV01`) mojibake repair (`map_line`,
    `page_counts` for span geometry + `repair_bgsdd_mojibake_v6` verified 0-FP text rules).
  - `N3`: Event-stream HTML `<script>/<style>/<noscript>/<template>` stripper preserving `<pre>`
    transcripts (`rendition_text`, `extract_clean_html_v6`), strictly HTML/non-`%PDF-`-gated WAF &
    soft-404 detector (`detect_error_page`, `detect_waf_or_error_page_v6`), bare-UUID HTML
    detection (`infer_is_html_v6`), and `url-rules.json` `&download=1` / wrapper normalizer
    (`normalize_congressional_url_v6`, `strip_creative_engine_download_suffix`).
  - `N4`: Cold-R2 object key builder (`build_r2_body_key`).
  - `N11`: Deterministic line-anchored parsers on `\n`-preserved text:
      * GPO printed hearing leadership, proceedings speakers & `p3..p8` TOC/panel personas
        (`transcript_entries`, `parse_gpo_p12_personas_v6`, `parse_gpo_p3_slice_personas_v6`),
      * Witness-list PDF multi-line & bulleted witness parser + SHA overrides
        (`parse_document_witnesses`, `parse_witness_list_personas_v6`),
      * CBO `"At a Glance"` page-1 cost-estimate card parser (`parse_pdf_card_text`,
        `parse_cbo_cost_estimate_v6`),
      * GAO report front-matter requester, committee & Member addressee parser with lowercase
        `product_id` normalization (`read_requesters`, `parse_gao_requesters_v6`).
"""

from __future__ import annotations

import datetime
import html as _html_mod
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import unquote, urlsplit, urlunsplit

from .schema_v4 import MAX_PERSONAS

__all__ = [
    # N1: GPO page & glyph normalization
    "METADATA_RULES",
    "BareNumberEvidence",
    "FontGlyphCount",
    "GpoCleanupRecord",
    "GpoPageCleanup",
    "MetadataRule",
    "is_gpo_layout",
    "normalize_gpo_glyphs",
    "normalize_gpo_pages",
    "normalize_p12_pages_v6",
    # N2: BGsddV01 mojibake repair
    "FONT_GLYPHS",
    "MINUS",
    "UNDERSCORE",
    "map_line",
    "page_counts",
    "repair_bgsdd_mojibake_v6",
    # N3: HTML rendition_text, WAF error_pages, infer_is_html_v6, URL rules
    "BodyText",
    "BodyTextError",
    "ErrorPageMarker",
    "GOVINFO_ERROR_PAGE_URL",
    "HTML_VOID_TAGS",
    "HTM_BLOCK_ELEMENTS",
    "HTM_DROPPED_ELEMENTS",
    "MAX_EVENTS",
    "METADATA_ELEMENTS",
    "MarkupEvent",
    "MarkupRead",
    "MarkupReadError",
    "PDF_MAGIC",
    "RenditionCleanup",
    "SNIFF_BYTES",
    "detect_error_page",
    "detect_spa_shell",
    "detect_waf_or_error_page_v6",
    "detect_wall",
    "error_page_title",
    "extract_clean_html_v6",
    "has_govinfo_error_marker",
    "infer_is_html_v6",
    "is_govinfo_error_url",
    "normalize_congressional_url_v6",
    "read_html_events",
    "rendition_text",
    "sniff",
    "strip_creative_engine_download_suffix",
    # N4: Cold-R2 helper
    "build_r2_body_key",
    # N11: Line-anchored GPO / Witness-List / CBO / GAO parsers
    "CboPdfCard",
    "CboSourceError",
    "DocumentWitness",
    "GaoProductSourceError",
    "GaoReportRequesterError",
    "GaoReportRequesters",
    "REVIEWED_WITNESS_LISTS",
    "RequesterEvidence",
    "gao_product_id",
    "gpo_name_key",
    "gpo_roster",
    "harvest_tail_and_toc_personas_v6",
    "names_page",
    "parse_cbo_cost_estimate_v6",
    "parse_document_witnesses",
    "parse_gao_requesters_v6",
    "parse_gpo_p12_personas_v6",
    "parse_gpo_p3_slice_personas_v6",
    "parse_pdf_card_text",
    "parse_witness_list_personas_v6",
    "peel_leading_position_credentials",
    "person_key",
    "read_requesters",
    "transcript_entries",
    "witness_line_parse",
]

_ALNUM_RE = re.compile(r"[A-Za-z0-9]")
_WS_COLLAPSE_RE = re.compile(r"[ \t\r\n]+")


# ===========================================================================
# N2 (Part A): GPO Symbol-Font Span Mapper (`spicy_docs/extraction/font_glyphs.py`)
# ===========================================================================

MINUS = "gpo-sdd-minus"
UNDERSCORE = "gpo-sdd-underscore"

FONT_GLYPHS: Mapping[str, Mapping[str, tuple[str | None, str]]] = {
    "BGsddV01": {
        "¥": ("-", MINUS),
        "ø": ("[", "gpo-sdd-bold-bracket"),
        "¿": ("]", "gpo-sdd-bold-bracket"),
        "ƒ": ("[", "gpo-sdd-italic-bracket"),
        "≈": ("]", "gpo-sdd-italic-bracket"),
        "∂": ("+", "gpo-sdd-plus"),
        "d": ("¾", "gpo-sdd-fraction"),
        "o": ("⅔", "gpo-sdd-fraction"),
        "»": ("◦", "gpo-sdd-sub-bullet"),
        "Æ": ("○", "gpo-sdd-end-mark"),
        "Ø": (None, "gpo-sdd-unresolved"),
        "◊": (None, "gpo-sdd-unresolved"),
    },
    "AGsddV01": {
        "B": ("⅓", "gpo-sdd-fraction"),
        "(": ("", "gpo-sdd-ornament"),
    },
    "CGsddV01": {
        "Ö": ("€", "gpo-sdd-euro"),
        "÷": ("€", "gpo-sdd-euro"),
        "#": ("æ", "gpo-sdd-ligature"),
    },
}


@dataclass(frozen=True)
class FontGlyphCount:
    page: int
    font: str
    original: str
    replacement: str | None
    rule: str
    count: int


_SUBSET_FONT_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")


def _underscore(spans: Sequence[Mapping[str, Any]], k: int, direction: Sequence[float]) -> bool:
    span = spans[k]
    cos, sin = direction[0], direction[1]
    neighbours = [
        n
        for n in (
            spans[k - 1] if k else None,
            spans[k + 1] if k + 1 < len(spans) else None,
        )
        if n
    ]
    neighbours = [n for n in neighbours if _SUBSET_FONT_PREFIX_RE.sub("", str(n.get("font", ""))) not in FONT_GLYPHS]
    if not neighbours:
        return False
    x, y = span["origin"]
    return all(
        span["size"] < 0.8 * n["size"] and (y - n["origin"][1]) * cos - (x - n["origin"][0]) * sin > 0
        for n in neighbours
    )


def map_line(
    spans: Sequence[Mapping[str, Any]],
    tally: Counter,
    direction: Sequence[float] = (1.0, 0.0),
    *,
    mappings: Mapping[str, Mapping[str, tuple[str | None, str]]] = FONT_GLYPHS,
) -> str:
    """Map GPO symbol-font glyphs in one PyMuPDF `dict` line using span font + baseline geometry."""
    norm_fonts = [_SUBSET_FONT_PREFIX_RE.sub("", str(s.get("font", ""))) for s in spans]
    text = "".join(str(s.get("text", "")) for s in spans)
    if not any(f in mappings for f in norm_fonts):
        return text
    out = list(text)
    position = 0
    for k, (span, fname) in enumerate(zip(spans, norm_fonts)):
        stxt = str(span.get("text", ""))
        table = mappings.get(fname)
        if table:
            for i, char in enumerate(stxt, position):
                entry = table.get(char)
                if entry is None:
                    continue
                replacement, rule = entry
                if rule == MINUS and _underscore(spans, k, direction):
                    replacement, rule = "_", UNDERSCORE
                if replacement is not None:
                    out[i] = replacement
                tally[(fname, char, replacement, rule)] += 1
        position += len(stxt)
    return "".join(out)


def page_counts(page: int, raw: Mapping[str, Any]) -> tuple[FontGlyphCount, ...]:
    tally: Counter = Counter()
    for block in raw.get("blocks", ()):
        for line in block.get("lines", ()):
            map_line(line.get("spans", ()), tally, line.get("dir", (1.0, 0.0)))
    return tuple(
        FontGlyphCount(page, key[0], key[1], key[2], key[3], count)
        for key, count in sorted(tally.items(), key=lambda kv: str(kv[0]))
    )


# ===========================================================================
# N2 (Part B): Verified 0-FP Text-Level `BGsddV01` Mojibake Repair
# ===========================================================================

_OCR_GARBLE_CHARS_RE = re.compile(r"[¡ßþùüêîôûãåæçèìñòõ÷@]")
_GPO_EVIDENCE_TEXT_RE = re.compile(
    r"(?:"
    r"U\.?\s*S\.?\s+GOVERNMENT\s+(?:PUBLISHING|PRINTING)\s+OFFICE"
    r"|\bVerDate\b|\bJkt\s+\d{3,8}\b|\bPO\s+00000\b|\bSfmt\s+\d{4}\b"
    r"|\bPrinted\s+for\s+the\s+use\s+of\s+the\s+(?:Select\s+|Permanent\s+|Special\s+|Joint\s+)?Committee\b"
    r"|\bPUBLIC\s+LAW\s+\d{2,3}[–—-]\d+\b"
    r"|\b\d{2,3}(?:ST|ND|RD|TH)\s+CONGRESS\b.*\b(?:SESSION| H\.\s*R\.| S\.)\b"
    r")",
    re.I | re.S,
)
_GPO_EVIDENCE_FN_RE = re.compile(
    r"^(?:[0-9a-fA-F]{64}\.)?(?:CHRG|CRPT|BILLS|HRPT|SRPT|SHRG|PLAW|STATUTE)-",
    re.I,
)

# 1) STAT¥UNUSED -> STAT_UNUSED (uppercase identifiers joined by BGsddV01 dropped-baseline ¥)
_BGSDD_UPPER_UNDERSCORE_RE = re.compile(r"(?<![\\/~A-Za-z])([A-Z][A-Z0-9]{1,}(?:¥[A-Z0-9]{2,})+)(?![A-Za-z'])")
# 2) hearings¥markups¥details.aspx -> hearings_markups_details.aspx (URL/file snake_case identifiers)
_BGSDD_PATH_UNDERSCORE_RE = re.compile(
    r"((?:https?://|[a-z0-9_-]+/)[A-Za-z0-9./%_-]*?[A-Za-z0-9]¥[A-Za-z0-9¥._/-]+"
    r"|\b[a-z]{3,}(?:¥[a-z0-9]{2,})+\.(?:aspx?|html?|pdf|xml|jsp|cfm|php|txt|doc)\b)",
    re.I,
)
# 3) ø...¿ -> [...] (BGsddV01 bold brackets for omitted statutory/report text)
_BGSDD_BOLD_BRACKETS_RE = re.compile(r"(?<![A-Za-z])ø([^ø¿\n]{1,320})¿(?![A-Za-z])")
# 4) ƒ...≈ -> [...] (BGsddV01 italic brackets)
_BGSDD_ITALIC_BRACKETS_RE = re.compile(r"(?<![A-Za-z])ƒ([^ƒ≈\n]{1,320})≈(?![A-Za-z])")
# 5) Unclosed GPO report italic-bracket paragraph lead `ƒ(B) that the State...` on GPO prints
_BGSDD_GPO_ITALIC_OPEN_RE = re.compile(r"(?:(?<=^)|(?<=[\s\n]))ƒ(\([A-Za-z0-9]{1,3}\)\s+[A-Za-z])")
# 6) ¥<digits> -> -<digits> on GPO documents when NOT currency context
_BGSDD_GPO_MINUS_RE = re.compile(r"(?:(?<=^)|(?<=[\s(\[\t]))¥(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\b")
_CURRENCY_LOOKBACK_RE = re.compile(
    r"\b(?:at|of|price|priced|closed|opened|traded|worth|valued|approx\.?|approximately|"
    r"RMB|CNY|JPY|yen|yuan|renminbi)\s+$",
    re.I,
)
_CURRENCY_LOOKAHEAD_RE = re.compile(
    r"^\s*(?:billion|million|trillion|thousand)?\s*(?:\(\s*(?:US\$|USD|\$)|per\s+share\b|yen\b|yuan\b)",
    re.I,
)
# 7) Medicare∂Choice -> Medicare+Choice and `(∂ ~ $60,000,000)` -> `(+ ~ $60,000,000)`
_BGSDD_MEDICARE_PLUS_RE = re.compile(r"\bMedicare∂Choice\b")
_BGSDD_PAREN_PLUS_RE = re.compile(r"\(\s*∂(?=\s*(?:~|\$|\d))")
# 8) GPO trailing end-of-document mark `. Æ` -> `. ○`
_BGSDD_END_MARK_RE = re.compile(r"(?<=[.?!])\s+Æ(?=\s*$|\s*\n\s*$)")


def repair_bgsdd_mojibake_v6(
    text: str,
    *,
    filename: str | None = None,
    is_gpo: bool | None = None,
) -> tuple[str, list[str]]:
    """Apply high-precision `BGsddV01` GPO symbol-font mojibake repairs (`0` FPs on `Gold360` & currency/names).

    Never corrupts:
      - Scandinavian/European names (`Jørgensen`, `Bjørn`, `Sørensen`, `Møse`),
      - Real Yen/Yuan currency (`shares closed at ¥208.50 (US$29.90)`, `IPO price of ¥32.76`),
      - Math approximations (`≈ 30 centimeters`),
      - OCR noise (`\\¥I'l'IIDRAWAIJ`, `6 ¥2%`, `Tâouøe of ßepreøentatibes`).
    """
    if not text or not any(ch in text for ch in ("¥", "ø", "¿", "ƒ", "≈", "∂", "Æ")):
        return text, []

    rules_fired: list[str] = []
    out = text

    gpo_doc = (
        is_gpo
        if is_gpo is not None
        else bool(
            (filename and _GPO_EVIDENCE_FN_RE.search(filename.rsplit("/", 1)[-1]))
            or _GPO_EVIDENCE_TEXT_RE.search(out[:3000])
        )
    )

    # 1. STAT¥UNUSED -> STAT_UNUSED
    def _repl_upper_under(m: re.Match[str]) -> str:
        rules_fired.append("bgsdd_identifier_underscore")
        return m.group(1).replace("¥", "_")

    out = _BGSDD_UPPER_UNDERSCORE_RE.sub(_repl_upper_under, out)

    # 2. hearings¥markups¥details.aspx -> hearings_markups_details.aspx
    def _repl_path_under(m: re.Match[str]) -> str:
        rules_fired.append("bgsdd_path_underscore")
        return m.group(1).replace("¥", "_")

    out = _BGSDD_PATH_UNDERSCORE_RE.sub(_repl_path_under, out)

    # 3. ø...¿ -> [...] (guarded against noisy Acrobat OCR spans)
    def _repl_bold_brk(m: re.Match[str]) -> str:
        inner = m.group(1)
        if _OCR_GARBLE_CHARS_RE.search(inner) or "  ~  " in inner:
            return m.group(0)
        # Reject OCR words like `"øn¿o` where interior is 1-2 lowercase chars inside broken word
        if len(inner.strip()) <= 2 and not inner.strip().isalnum():
            return m.group(0)
        if len(inner) <= 3 and inner.isalpha() and inner.islower():
            return m.group(0)
        rules_fired.append("bgsdd_bold_brackets")
        return f"[{inner}]"

    out = _BGSDD_BOLD_BRACKETS_RE.sub(_repl_bold_brk, out)

    # 4. ƒ...≈ -> [...]
    def _repl_italic_brk(m: re.Match[str]) -> str:
        inner = m.group(1)
        if _OCR_GARBLE_CHARS_RE.search(inner):
            return m.group(0)
        rules_fired.append("bgsdd_italic_brackets")
        return f"[{inner}]"

    out = _BGSDD_ITALIC_BRACKETS_RE.sub(_repl_italic_brk, out)

    # 5. GPO-evidenced rules (`¥<digits> -> -<digits>`, `ƒ(B) ... -> [(B) ...`, `∂ -> +`, `. Æ -> . ○`)
    if "Medicare∂Choice" in out:
        out = _BGSDD_MEDICARE_PLUS_RE.sub("Medicare+Choice", out)
        rules_fired.append("bgsdd_plus")

    if gpo_doc:
        if "ƒ(" in out:
            new_out = _BGSDD_GPO_ITALIC_OPEN_RE.sub(r"[\1", out)
            if new_out != out:
                out = new_out
                rules_fired.append("bgsdd_italic_open_bracket")

        if "∂" in out:
            new_out = _BGSDD_PAREN_PLUS_RE.sub("(+", out)
            if new_out != out:
                out = new_out
                rules_fired.append("bgsdd_plus")

        if "¥" in out and not _OCR_GARBLE_CHARS_RE.search(out[:1200]):
            def _repl_minus(m: re.Match[str]) -> str:
                pre = out[max(0, m.start() - 40) : m.start()]
                post = out[m.end() : m.end() + 40]
                if _CURRENCY_LOOKBACK_RE.search(pre) or _CURRENCY_LOOKAHEAD_RE.search(post):
                    return m.group(0)
                # Reject OCR `6 ¥2%` (= `6 ½%`) where a standalone digit immediately precedes ` ¥2%`
                if re.search(r"\b\d\s+$", pre) and post.startswith("%"):
                    return m.group(0)
                rules_fired.append("bgsdd_minus")
                return f"-{m.group(1)}"

            out = _BGSDD_GPO_MINUS_RE.sub(_repl_minus, out)

        if "Æ" in out[-40:]:
            new_out = _BGSDD_END_MARK_RE.sub(" ○", out)
            if new_out != out:
                out = new_out
                rules_fired.append("bgsdd_end_mark")

    dedup_rules = list(dict.fromkeys(rules_fired))
    return out, dedup_rules


# ===========================================================================
# N1: GPO Multi-Line Page Normalizer (`spicy_docs/extraction/gpo_normalize.py`)
# ===========================================================================

_VERDATE_RE = re.compile(r"^(?:VerDate\s|Jkt\s+\d{4,8}\s+PO\s+\d{4,6}\b|PO\s+00000\s+Frm\s+\d{4,6}\b)")
_DSK_USER_RE = re.compile(r"^\w+ on \w*PROD\w* with \S+$")
_PAGE_NUM_RE = re.compile(r"^\d{1,4}\s*$")
_BULLET_BILL_RE = re.compile(r"^[•·]\s*[A-Z]")
_RUNNING_FOOTER_RE = re.compile(r"^(?:H|S|HR|HRES|SRES|HJRES|SJRES|HCONRES|SCONRES)\s+\d+\s+[A-Z]{2,4}$")
_BARE_GUTTER_NUMBER_RE = re.compile(r"^\d{1,2}$")
_HYPHEN_WRAP_RE = re.compile(r"[A-Za-z]-$")
_SINGLE_CAP_RE = re.compile(r"^[A-Z]$")
_STARTS_CAP_RE = re.compile(r"^[A-Z]")
_SPACE_COLLAPSE_RE = re.compile(r"  +")
_CURLY_SINGLE_RE = re.compile(r"[\u2018\u2019]")
_CURLY_DOUBLE_RE = re.compile(r"[\u201c\u201d]")

BareNumberEvidence = Literal["none", "page_footer", "gutter_layout", "both"]


@dataclass(frozen=True)
class MetadataRule:
    name: str
    artifact: str
    pattern: re.Pattern[str]


METADATA_RULES: tuple[MetadataRule, ...] = (
    MetadataRule("verdate_footer", "GPO print metadata footer (VerDate/Jkt/PO 00000 line)", _VERDATE_RE),
    MetadataRule("dsk_user", "Document-processing user/job-code line", _DSK_USER_RE),
    MetadataRule("bare_page_number", "Bare page number or per-line gutter number", _PAGE_NUM_RE),
    MetadataRule("bullet_bill_id", "Bullet-prefixed bill identifier", _BULLET_BILL_RE),
    MetadataRule("running_footer", "Unbulleted running bill-stage line (e.g. HR 5895 PCS)", _RUNNING_FOOTER_RE),
)


@dataclass(frozen=True)
class GpoPageCleanup:
    page: int
    verdate_footer_lines: int
    footer_continuation_lines: int
    dsk_user_lines: int
    running_footer_lines: int
    bare_page_number_lines: int
    bare_page_number_evidence: BareNumberEvidence
    bullet_bill_lines: int
    content_lines: int
    small_caps_merges: int
    hyphen_rejoin_count: int


@dataclass(frozen=True)
class GpoCleanupRecord:
    line_numbers: bool
    gpo_footers: bool
    spacing_normalized: bool
    running_footer_lines: int
    small_caps_merges: int
    hyphen_rejoin_count: int
    pages: tuple[GpoPageCleanup, ...]
    font_glyphs: tuple[FontGlyphCount, ...] = ()


@dataclass(frozen=True)
class _GpoLine:
    text: str
    gutter_adjacent: bool
    is_bare_digit: bool = False


@dataclass(frozen=True)
class _PageMetadataCounts:
    verdate_footer_lines: int
    footer_continuation_lines: int
    dsk_user_lines: int
    running_footer_lines: int
    bare_page_number_lines: int
    bullet_bill_lines: int
    content_lines: int
    gutter_adjacent_lines: int
    gutter_numbers: tuple[int, ...]


def _strip_metadata(lines: Sequence[str]) -> tuple[list[_GpoLine], _PageMetadataCounts]:
    kept: list[_GpoLine] = []
    verdate = footer_continuation = dsk = running_footer = page_num = bullet = 0
    content = gutter_adjacent = 0
    gutter_numbers: list[int] = []
    i, n = 0, len(lines)
    while i < n:
        t = lines[i].strip()
        if not t:
            kept.append(_GpoLine("", False))
            i += 1
            continue
        if _VERDATE_RE.match(t):
            verdate += 1
            tail = [line.strip() for line in lines[i + 1 :]]
            dsk_in_tail = sum(1 for line in tail if _DSK_USER_RE.match(line))
            dsk += dsk_in_tail
            footer_continuation += len(tail) - dsk_in_tail
            i = n
            continue
        if _DSK_USER_RE.match(t):
            dsk += 1
            i += 1
            continue
        following = lines[i + 1].strip() if i + 1 < n else ""
        gutter_follows = bool(_BARE_GUTTER_NUMBER_RE.match(following))
        if _RUNNING_FOOTER_RE.match(t) and not gutter_follows:
            running_footer += 1
            i += 1
            continue
        if _PAGE_NUM_RE.match(t):
            page_num += 1
            kept.append(_GpoLine(t, False, is_bare_digit=True))
            i += 1
            continue
        if _BULLET_BILL_RE.match(t):
            bullet += 1
            i += 1
            continue
        content += 1
        if gutter_follows:
            gutter_adjacent += 1
            gutter_numbers.append(int(following))
        kept.append(_GpoLine(t, gutter_follows))
        i += 1
    counts = _PageMetadataCounts(
        verdate,
        footer_continuation,
        dsk,
        running_footer,
        page_num,
        bullet,
        content,
        gutter_adjacent,
        tuple(gutter_numbers),
    )
    return kept, counts


def _gate_bare_digits(
    kept: list[_GpoLine], *, page_has_footer: bool, document_gpo_layout: bool
) -> tuple[list[_GpoLine], BareNumberEvidence]:
    if page_has_footer and document_gpo_layout:
        evidence: BareNumberEvidence = "both"
    elif page_has_footer:
        evidence = "page_footer"
    elif document_gpo_layout:
        evidence = "gutter_layout"
    else:
        evidence = "none"
    if evidence == "none":
        return kept, evidence
    return [line for line in kept if not line.is_bare_digit], evidence


_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT = 50
_MIN_GUTTER_RUN_LENGTH = 3


def _starts_consecutive_run_from_one(numbers: Sequence[int], minimum: int = _MIN_GUTTER_RUN_LENGTH) -> bool:
    run = 0
    for index, value in enumerate(numbers):
        if value != index + 1:
            break
        run += 1
    return run >= minimum


def _layout_verdict(page_counts_seq: Sequence[_PageMetadataCounts]) -> bool:
    content = sum(c.content_lines for c in page_counts_seq)
    if content == 0:
        return False
    numbered = sum(c.gutter_adjacent_lines for c in page_counts_seq)
    ratio_qualifies = numbered / content >= 0.3
    has_structural_run = any(_starts_consecutive_run_from_one(c.gutter_numbers) for c in page_counts_seq)
    if content >= _MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT:
        return ratio_qualifies or has_structural_run
    return ratio_qualifies and has_structural_run


def normalize_gpo_glyphs(raw: str) -> str:
    """Normalize line endings and GPO doubled curly/typewriter quote pairs."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _CURLY_SINGLE_RE.sub("'", text)
    text = _CURLY_DOUBLE_RE.sub('"', text)
    text = text.replace("\u00a0", " ")
    return text.replace("``", '"').replace("''", '"')


def is_gpo_layout(pages: Sequence[str]) -> bool:
    """Detect GPO per-line gutter numbering."""
    if not pages:
        return False
    return _layout_verdict([_strip_metadata(normalize_gpo_glyphs(page).split("\n"))[1] for page in pages])


def _merge_small_caps(lines: list[_GpoLine]) -> tuple[list[_GpoLine], int]:
    merged: list[_GpoLine] = []
    count = 0
    i, n = 0, len(lines)
    while i < n:
        cur = lines[i]
        if _SINGLE_CAP_RE.match(cur.text) and i + 1 < n and _STARTS_CAP_RE.match(lines[i + 1].text):
            nxt = lines[i + 1]
            merged.append(_GpoLine(cur.text + nxt.text, nxt.gutter_adjacent))
            count += 1
            i += 2
            continue
        merged.append(cur)
        i += 1
    return merged, count


def _rejoin_hyphens(lines: list[_GpoLine], gpo_layout: bool) -> tuple[list[str], int]:
    if not gpo_layout:
        return [line.text for line in lines], 0
    working = list(lines)
    count = 0
    for j in range(len(working) - 1):
        cur = working[j]
        if cur.gutter_adjacent and _HYPHEN_WRAP_RE.search(cur.text):
            nxt = working[j + 1]
            working[j + 1] = _GpoLine(cur.text[:-1] + nxt.text, nxt.gutter_adjacent)
            working[j] = _GpoLine("\x00", False)
            count += 1
    return [line.text for line in working if line.text != "\x00"], count


def normalize_gpo_pages(pages: Sequence[str]) -> tuple[tuple[str, ...], GpoCleanupRecord]:
    """Normalize GPO PDF page text, keeping page boundaries."""
    if not pages:
        raise ValueError("pages must be a nonempty sequence")
    per_page = [_strip_metadata(normalize_gpo_glyphs(raw_page).split("\n")) for raw_page in pages]
    gpo_layout = _layout_verdict([counts for _, counts in per_page])
    normalized: list[str] = []
    page_records: list[GpoPageCleanup] = []
    gpo_footers = False
    total_small_caps = total_hyphen = total_running_footer = 0

    for number, (kept, counts) in enumerate(per_page, start=1):
        page_has_footer = (
            counts.verdate_footer_lines > 0 or counts.dsk_user_lines > 0 or counts.running_footer_lines > 0
        )
        gated, evidence = _gate_bare_digits(kept, page_has_footer=page_has_footer, document_gpo_layout=gpo_layout)
        merged, small_caps = _merge_small_caps(gated)
        rejoined, hyphen_count = _rejoin_hyphens(merged, gpo_layout)
        collapsed = [_SPACE_COLLAPSE_RE.sub(" ", line) for line in rejoined]
        normalized.append("\n".join(collapsed))

        gpo_footers = gpo_footers or page_has_footer
        total_small_caps += small_caps
        total_hyphen += hyphen_count
        total_running_footer += counts.running_footer_lines
        page_records.append(
            GpoPageCleanup(
                page=number,
                verdate_footer_lines=counts.verdate_footer_lines,
                footer_continuation_lines=counts.footer_continuation_lines,
                dsk_user_lines=counts.dsk_user_lines,
                running_footer_lines=counts.running_footer_lines,
                bare_page_number_lines=counts.bare_page_number_lines,
                bare_page_number_evidence=evidence,
                bullet_bill_lines=counts.bullet_bill_lines,
                content_lines=counts.content_lines,
                small_caps_merges=small_caps,
                hyphen_rejoin_count=hyphen_count,
            )
        )

    record = GpoCleanupRecord(
        line_numbers=gpo_layout,
        gpo_footers=gpo_footers,
        spacing_normalized=True,
        running_footer_lines=total_running_footer,
        small_caps_merges=total_small_caps,
        hyphen_rejoin_count=total_hyphen,
        pages=tuple(page_records),
    )
    return tuple(normalized), record


def normalize_p12_pages_v6(
    pages: Sequence[str],
    *,
    filename: str | None = None,
    max_chars: int = 8000,
) -> dict[str, Any]:
    """Normalize `\n`-preserved `p1-2` pages via `normalize_gpo_pages` + `repair_bgsdd_mojibake_v6`.

    Returns `p12_lines` (`<= max_chars`, `\n`-preserved) and exposes `gpo_blank_after_strip` when a
    scanned page's only extractable characters were native GPO `VerDate`/`DSK`/`Jkt`/`PO 00000` chrome.
    """
    if not pages:
        return {
            "p12_lines": "",
            "gpo_blank_after_strip": False,
            "gpo_footers_stripped": False,
            "gpo_line_numbers_stripped": False,
            "bgsdd_rules_applied": [],
            "chars_removed": 0,
        }
    p12_in = [p or "" for p in pages[:2]]
    raw_joined = "\n".join(p12_in)
    had_raw_alnum = bool(_ALNUM_RE.search(raw_joined))

    norm_pages, record = normalize_gpo_pages(p12_in)
    joined = "\n".join(norm_pages).strip("\n")
    repaired, bgsdd_rules = repair_bgsdd_mojibake_v6(
        joined,
        filename=filename,
        is_gpo=(record.gpo_footers or record.line_numbers or None),
    )
    has_clean_alnum = bool(_ALNUM_RE.search(repaired))
    gpo_blank_after_strip = bool(had_raw_alnum and not has_clean_alnum and (record.gpo_footers or record.line_numbers))

    if len(repaired) > max_chars:
        cut = repaired.rfind("\n", max_chars - 240, max_chars + 1)
        repaired = repaired[:cut] if cut > 0 else repaired[:max_chars]

    return {
        "p12_lines": repaired,
        "gpo_blank_after_strip": gpo_blank_after_strip,
        "gpo_footers_stripped": bool(record.gpo_footers),
        "gpo_line_numbers_stripped": bool(record.line_numbers),
        "bgsdd_rules_applied": bgsdd_rules,
        "chars_removed": max(0, len(raw_joined) - len(joined)),
    }


# ===========================================================================
# N3 (Part A): Event-Stream HTML Reader (`spicy_docs/extraction/body_text.py` + `markup.py`)
# ===========================================================================

HTML_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
_HTML_FEED_CHARACTERS = 64 * 1024
MAX_EVENTS = 1_000_000

METADATA_ELEMENTS = frozenset({"title"})
HTM_DROPPED_ELEMENTS = METADATA_ELEMENTS | {"script", "style", "noscript", "template"}
HTM_BLOCK_ELEMENTS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "dd", "details", "dialog", "div", "dl", "dt",
        "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header",
        "hgroup", "hr", "li", "main", "nav", "ol", "option", "p", "pre", "section", "table", "td", "th", "tr", "ul",
    }
)
_VERBATIM_ELEMENTS = frozenset({"pre"})
_NAVIGATION_ELEMENTS = frozenset({"nav", "menu"})
_VISIBLE = re.compile(r"[^\s\x1a]")
_HTML_SPACE = re.compile(r"[ \t\r\n\f]+")


class MarkupReadError(ValueError):
    """Markup is malformed, undecodable, or outside bounds."""


class BodyTextError(ValueError):
    """A rendition cannot be turned into text under its derivation."""


@dataclass(frozen=True)
class MarkupEvent:
    kind: Literal["start", "empty", "end", "text", "comment", "pi", "declaration"]
    byte_start: int
    name: str | None = None
    attributes: tuple[tuple[str, str | None], ...] = ()
    text: str | None = None
    byte_end: int | None = None
    is_literal: bool = False


@dataclass(frozen=True)
class MarkupRead:
    events: tuple[MarkupEvent, ...]
    element_count: int
    root_name: str | None


@dataclass(frozen=True)
class RenditionCleanup:
    markup_events: int
    markup_elements: int
    text_events: int
    metadata_element_chars: int
    element_line_breaks: int
    whitespace_only_lines: int
    line_endings_normalized: int
    end_of_text_markers: int
    quote_pairs_collapsed: int
    trailing_space_lines: int


@dataclass(frozen=True)
class BodyText:
    text: str
    pages: tuple[str, ...] | None
    rendition: str
    media_type: str
    byte_size: int
    derivation: str
    record: GpoCleanupRecord | RenditionCleanup


class _Events:
    def __init__(self, max_events: int) -> None:
        if type(max_events) is not int or max_events <= 0:
            raise MarkupReadError("max_events must be a positive integer")
        self.max_events = max_events
        self.events: list[MarkupEvent] = []
        self.element_count = 0
        self.root_name: str | None = None
        self._text_parts: list[str] = []

    def _append(self, event: MarkupEvent) -> None:
        if len(self.events) >= self.max_events:
            raise MarkupReadError("markup exceeds max_events")
        self.events.append(event)

    def flush(self) -> None:
        if self._text_parts:
            self._append(MarkupEvent("text", 0, text="".join(self._text_parts)))
            self._text_parts.clear()

    def add(self, event: MarkupEvent) -> None:
        self.flush()
        self._append(event)
        if event.kind in {"start", "empty"}:
            self.element_count += 1
            if self.root_name is None:
                self.root_name = event.name

    def text(self, text: str) -> None:
        if not text:
            return
        if len(self.events) >= self.max_events and not self._text_parts:
            raise MarkupReadError("markup exceeds max_events")
        self._text_parts.append(text)

    def result(self) -> MarkupRead:
        self.flush()
        return MarkupRead(tuple(self.events), self.element_count, self.root_name)


class _HtmlEvents(HTMLParser):
    def __init__(self, *, max_events: int, max_depth: int) -> None:
        super().__init__(convert_charrefs=False)
        self.events = _Events(max_events)
        self.max_depth = max_depth
        self.stack: list[str] = []
        self._open: dict[str, list[int]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in HTML_VOID_TAGS:
            if len(self.stack) >= self.max_depth:
                raise MarkupReadError("HTML markup exceeds the supported nesting depth")
            self._open.setdefault(tag, []).append(len(self.stack))
            self.stack.append(tag)
        self.events.add(MarkupEvent("start", 0, name=tag, attributes=tuple(attrs)))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.stack) >= self.max_depth:
            raise MarkupReadError("HTML markup exceeds the supported nesting depth")
        self.events.add(MarkupEvent("empty", 0, name=tag, attributes=tuple(attrs)))

    def handle_endtag(self, tag: str) -> None:
        self.events.add(MarkupEvent("end", 0, name=tag))
        opened = self._open.get(tag)
        if opened:
            index = opened[-1]
            for name in reversed(self.stack[index:]):
                self._open[name].pop()
            del self.stack[index:]

    def handle_data(self, data: str) -> None:
        decoded = data if self.cdata_elem else _html_mod.unescape(data)
        self.events.text(decoded)

    def handle_entityref(self, name: str) -> None:
        self.events.text(_html_mod.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self.events.text(_html_mod.unescape(f"&#{name};"))


def read_html_events(
    body: bytes,
    *,
    max_bytes: int = 64 * 1024 * 1024,
    max_events: int = MAX_EVENTS,
    max_depth: int = MAX_EVENTS,
    errors: str = "strict",
) -> MarkupRead:
    """Read HTML using stdlib `HTMLParser` without building a DOM tree."""
    if not isinstance(body, bytes) or len(body) > max_bytes:
        raise MarkupReadError("HTML markup must be bytes within max_bytes")
    try:
        text = body.decode("utf-8", errors=errors)
    except UnicodeDecodeError as error:
        raise MarkupReadError("HTML markup must be UTF-8") from error
    parser = _HtmlEvents(max_events=max_events, max_depth=max_depth)
    try:
        for offset in range(0, len(text), _HTML_FEED_CHARACTERS):
            parser.feed(text[offset : offset + _HTML_FEED_CHARACTERS])
        parser.close()
    except (AssertionError, ValueError) as error:
        if isinstance(error, MarkupReadError):
            raise
        raise MarkupReadError(f"HTML markup cannot be parsed: {error}") from error
    return parser.events.result()


def _open_depth(depth: int, event: MarkupEvent, names: frozenset[str]) -> int:
    if event.name in names:
        if event.kind == "start":
            return depth + 1
        if event.kind == "end":
            return max(depth - 1, 0)
    return depth


def _cleanup_rendition_text(raw: str) -> tuple[str, dict[str, int]]:
    text = normalize_gpo_glyphs(raw)
    counts = {
        "line_endings_normalized": raw.count("\r"),
        "end_of_text_markers": text.count("\x1a"),
        "quote_pairs_collapsed": raw.count("``") + raw.count("''"),
        "trailing_space_lines": sum(1 for line in text.split("\n") if line.strip() and line != line.rstrip()),
    }
    text = text.replace("\x1a", "")
    return "\n".join(line.rstrip() for line in text.split("\n")), counts


def _marked_html_events(
    events: Iterable[MarkupEvent],
    *,
    dropped: frozenset[str],
    blocks: frozenset[str],
) -> Iterator[tuple[MarkupEvent, bool, bool]]:
    depth = verbatim = 0
    line_has_text = pending = False
    for event in events:
        if event.kind != "text" or event.text is None:
            was_verbatim = verbatim
            depth = _open_depth(depth, event, dropped)
            verbatim = _open_depth(verbatim, event, _VERBATIM_ELEMENTS)
            if line_has_text and not depth and event.name in blocks and not (was_verbatim and verbatim):
                pending = True
            yield event, False, False
            continue
        if depth or not blocks:
            yield event, bool(depth), False
            continue
        text = event.text
        first = _VISIBLE.search(text)
        lead = len(text) if first is None else first.start()
        source_break = "\n" in text[:lead] or "\r" in text[:lead]
        line_break = pending and lead < len(text) and not source_break
        if source_break or line_break:
            pending = False
        last = max(text.rfind("\n"), text.rfind("\r"))
        visible = _VISIBLE.search(text, last + 1) is not None
        line_has_text = visible if last >= 0 or line_break else line_has_text or visible
        yield event, False, line_break


def _verbatim_html_text(read: MarkupRead) -> tuple[str, dict[str, int]]:
    parts: list[str] = []
    text_events = metadata_chars = breaks = 0
    for event, left_out, line_break in _marked_html_events(
        read.events, dropped=HTM_DROPPED_ELEMENTS, blocks=HTM_BLOCK_ELEMENTS
    ):
        if event.kind == "text" and event.text is not None:
            if left_out:
                metadata_chars += len(event.text)
                continue
            if line_break:
                parts.append("\n")
                breaks += 1
            text_events += 1
            parts.append(event.text)
    text, counts = _cleanup_rendition_text("".join(parts))
    counts.update(
        {
            "markup_events": len(read.events),
            "markup_elements": read.element_count,
            "text_events": text_events,
            "metadata_element_chars": metadata_chars,
            "element_line_breaks": breaks,
            "whitespace_only_lines": 0,
        }
    )
    return text, counts


def _html_markup_text(read: MarkupRead) -> tuple[str, dict[str, int]]:
    if any(event.name == "pre" for event in read.events):
        return _verbatim_html_text(read)
    parts: list[str] = []
    text_events = metadata_chars = breaks = 0
    depth = verbatim = navigation = 0
    boundary = False
    adjacent_control = False
    for event in read.events:
        if event.kind != "text" or event.text is None:
            was_verbatim = verbatim
            depth = _open_depth(depth, event, HTM_DROPPED_ELEMENTS)
            verbatim = _open_depth(verbatim, event, _VERBATIM_ELEMENTS)
            navigation = _open_depth(navigation, event, _NAVIGATION_ELEMENTS)
            if not depth and not (was_verbatim and verbatim):
                if event.name in HTM_BLOCK_ELEMENTS:
                    boundary = True
                if event.name == "button" or (navigation and event.name == "a"):
                    adjacent_control = True
            continue
        if depth:
            metadata_chars += len(event.text)
            continue
        text_events += 1
        value = event.text if verbatim else _HTML_SPACE.sub(" ", event.text)
        if not verbatim and not value.strip():
            if parts and not parts[-1].endswith((" ", "\n")):
                parts.append(" ")
            continue
        if boundary and parts and not parts[-1].endswith("\n"):
            parts.append("\n")
            breaks += 1
        elif adjacent_control and parts and value and value[0].isalnum() and parts[-1][-1:].isalnum():
            parts.append(" ")
        if not verbatim and (not parts or parts[-1].endswith("\n")):
            value = value.lstrip(" ")
        parts.append(value)
        boundary = adjacent_control = False
    text, counts = _cleanup_rendition_text("".join(parts))
    text = text.strip()
    counts.update(
        {
            "markup_events": len(read.events),
            "markup_elements": read.element_count,
            "text_events": text_events,
            "metadata_element_chars": metadata_chars,
            "element_line_breaks": breaks,
            "whitespace_only_lines": 0,
        }
    )
    return text, counts


def rendition_text(
    data: bytes,
    *,
    rendition: str = "htm",
    media_type: str | None = None,
    byte_size: int | None = None,
    decode_errors: str = "strict",
) -> BodyText:
    """Stdlib port of `spicy_docs.extraction.body_text.rendition_text` (`htm` / `txt`).

    Drops `<title>`, `<script>`, `<style>`, `<noscript>`, and `<template>` during HTML event-stream
    walking (`0` JS/JSON-LD leakage) while preserving `<pre>` layout verbatim for GPO HTML hearings.
    """
    if not isinstance(data, bytes) or not data:
        raise BodyTextError("body must be nonempty bytes")
    size = len(data) if byte_size is None else byte_size
    if rendition == "txt":
        try:
            raw = data.decode("utf-8", errors=decode_errors)
        except UnicodeDecodeError as error:
            raise BodyTextError("txt body must be UTF-8") from error
        text, counts = _cleanup_rendition_text(raw)
        counts.update(
            {
                "markup_events": 0,
                "markup_elements": 0,
                "text_events": 0,
                "metadata_element_chars": 0,
                "element_line_breaks": 0,
                "whitespace_only_lines": 0,
            }
        )
        return BodyText(
            text=text,
            pages=None,
            rendition="txt",
            media_type=media_type or "text/plain",
            byte_size=size,
            derivation="text-rendition-cleanup",
            record=RenditionCleanup(**counts),
        )
    if rendition != "htm":
        raise BodyTextError("stdlib rendition_text supports 'htm' and 'txt'")
    exact_mt = "text/html"
    if media_type is not None:
        exact_mt = media_type.partition(";")[0].strip().casefold() or "text/html"
    read = read_html_events(data, max_depth=MAX_EVENTS, errors=decode_errors)
    text, counts = _html_markup_text(read)
    return BodyText(
        text=text,
        pages=None,
        rendition="htm",
        media_type=exact_mt,
        byte_size=size,
        derivation="markup-reader",
        record=RenditionCleanup(**counts),
    )


# Fallback scrubber for already-extracted plain-text HTML strings where raw HTML bytes weren't available
_EXTRACTED_HTML_SCRIPT_POLLUTION_RE = re.compile(
    r"(?:"
    r"<!--//--><!\[CDATA\[//><!--.*?//--><!\]\]>"
    r"|\{\s*\"@context\"\s*:\s*\"https?:\\?/\\?/schema\.org\".*?\}\s*(?=[A-Z]|Skip|Menu|Home|Toggle)"
    r"|\(window\.NREUM\|\|\(NREUM=\{\}\)\).*?(?=Skip\s+to|Toggle\s+navigation|Home\s+About|[A-Z][a-z]+\s+Committee)"
    r"|jQuery\.extend\(Drupal\.settings\s*,.*?\}\s*\)\s*;?"
    r"|\bDrupal\.settings\b[^\n]{0,4000}"
    r"|\(function\s*\(\s*d\s*,\s*s\s*,\s*id\s*\)\s*\{.*?\}\s*\(\s*document\s*,[^)]+\)\s*\)\s*;?"
    r"|window\.dataLayer\s*=\s*window\.dataLayer\s*\|\|\s*\[\]\s*;(?:\s*function\s+gtag\(\)\{[^}]*\}\s*;?)?(?:\s*gtag\([^)]*\)\s*;?)+"
    r"|if\s*\(\s*window\.document\.documentMode\s*\)\s*\{\s*\$\([^)]+\)\.html\([^)]+\)\s*;\s*\}"
    r")",
    re.S | re.I,
)


def extract_clean_html_v6(
    raw_html_or_text: bytes | str,
    *,
    max_chars: int = 8000,
) -> tuple[str, int]:
    """Extract `<script>/<style>/<noscript>/<template>`-free HTML text (`<= max_chars`).

    Returns `(clean_text, metadata_or_script_chars_dropped)`. Accepts raw HTML `bytes` (preferred:
    uses `rendition_text(..., rendition="htm")` with UTF-8 fallback to `latin-1` / `replace`) or
    pre-extracted HTML string (scrubbing residual JSON-LD / `Drupal.settings` / `NREUM` / `gtag` blocks).
    """
    if isinstance(raw_html_or_text, bytes):
        if not raw_html_or_text:
            return "", 0
        try:
            bt = rendition_text(raw_html_or_text, rendition="htm", decode_errors="strict")
        except (BodyTextError, MarkupReadError):
            bt = rendition_text(raw_html_or_text, rendition="htm", decode_errors="replace")
        dropped = bt.record.metadata_element_chars if isinstance(bt.record, RenditionCleanup) else 0
        txt = bt.text
    else:
        orig = raw_html_or_text or ""
        txt = _EXTRACTED_HTML_SCRIPT_POLLUTION_RE.sub(" ", orig)
        dropped = max(0, len(orig) - len(txt))
        txt = normalize_gpo_glyphs(txt).strip()

    if len(txt) > max_chars:
        cut = txt.rfind("\n", max_chars - 240, max_chars + 1)
        txt = txt[:cut] if cut > 0 else txt[:max_chars]
    return txt, dropped


# ===========================================================================
# N3 (Part B): Strictly Gated WAF & Soft-404 Detector (`spicy_docs/reading/error_pages.py`)
# ===========================================================================

PDF_MAGIC = b"%PDF-"
_WALL_FAMILIES = frozenset({"akamai", "cloudflare", "cloudfront", "datadome", "generic"})
_WALL_SCAN_BYTES = 64 * 1024

_BLOCK_PAGE_MARKERS: tuple[tuple[str, tuple[bytes, ...]], ...] = (
    ("akamai", (b"You don't have permission to access", b"errors.edgesuite.net", b"AkamaiGHost")),
    ("cloudflare", (b"Attention Required! | Cloudflare", b"Sorry, you have been blocked", b"Cloudflare Ray ID")),
    ("datadome", (b"captcha-delivery.com",)),
)
_REFUSAL_MARKERS: tuple[tuple[str, tuple[bytes, ...]], ...] = (
    ("akamai", (b"Access Denied",)),
    ("cloudflare", (b"You are unable to access", b"Attention Required", b"Just a moment", b"cf-ray")),
    ("cloudfront", (b"The request could not be satisfied", b"Request blocked")),
    ("generic", (b"captcha",)),
)
_SPA_SHELL_MARKERS = (b'<div id="root">', b"You need to enable JavaScript")

GOVINFO_ERROR_PAGE_URL = "https://www.govinfo.gov/error"
_GOVINFO_ERROR_PAGE = ("https", "www.govinfo.gov", "/error")
_GOVINFO_ERROR_MARKER = re.compile(rb"govinfo\.gov/error", re.IGNORECASE)
_S3_ACCESS_DENIED_MARKER = b"<Code>AccessDenied</Code>"

_ERROR_TITLES = frozenset(
    {
        "server error",
        "403 forbidden",
        "404 not found",
        "access denied",
        "request rejected",
        "just a moment",
        "just a moment...",
        "verify you are human",
    }
)
_TITLE_RE = re.compile(rb"<title(?:\s[^>]*)?>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)

SNIFF_BYTES = 4096
_PROLOG_RE = re.compile(rb"\s*(?:<\?.*?\?>|<!--.*?-->|<!doctype\s+([A-Za-z]+)[^>]*>)", re.IGNORECASE | re.DOTALL)
_ELEMENT_RE = re.compile(rb"\s*<(?:[A-Za-z_][\w.-]*:)?([A-Za-z_][\w.-]*)")
_HTML_ROOTS = frozenset(
    b"""a b body br center div em font form h1 h2 h3 h4 h5 h6 head hr html i iframe img li link meta
    noscript ol p pre script span strong style title u ul""".split()
)
UNDECODED_COMPRESSION = ((b"BZh", "bzip2"), (b"\xfd7zXZ\x00", "xz"), (b"\x28\xb5\x2f\xfd", "zstd"))
_HTML_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})


class ErrorPageMarker(str):
    family: str

    def __new__(cls, marker: str, family: str) -> ErrorPageMarker:
        match = super().__new__(cls, marker)
        match.family = family
        return match

    @property
    def wall(self) -> bool:
        return self.family in _WALL_FAMILIES


def detect_wall(body: bytes, *, refusal: bool | None = None) -> ErrorPageMarker | None:
    if body.startswith(PDF_MAGIC):
        return None
    head = body[:_WALL_SCAN_BYTES]
    vocabulary = _BLOCK_PAGE_MARKERS if refusal is False else _BLOCK_PAGE_MARKERS + _REFUSAL_MARKERS
    for family, markers in vocabulary:
        for marker in markers:
            if marker in head:
                return ErrorPageMarker(marker.decode("utf-8", "backslashreplace"), family)
    return None


def detect_spa_shell(body: bytes) -> bool:
    if body.startswith(PDF_MAGIC) or detect_wall(body) is not None:
        return False
    return any(marker in body for marker in _SPA_SHELL_MARKERS)


def is_govinfo_error_url(final_url: str) -> bool:
    parsed = urlsplit(final_url)
    return (parsed.scheme, parsed.netloc, parsed.path) == _GOVINFO_ERROR_PAGE


def has_govinfo_error_marker(body: bytes) -> bool:
    return _GOVINFO_ERROR_MARKER.search(body) is not None


def error_page_title(title: str) -> str | None:
    text = " ".join(title.split())
    return text if text.casefold() in _ERROR_TITLES else None


def _title_of(body: bytes) -> str | None:
    match = _TITLE_RE.search(body[:_WALL_SCAN_BYTES])
    return _html_mod.unescape(match.group(1).decode("utf-8", "replace")) if match else None


def sniff(head: bytes) -> str:
    text = head[3:] if head.startswith(b"\xef\xbb\xbf") else head
    text = text.lstrip()
    if not text:
        return "empty"
    for magic, kind in ((b"%PDF", "pdf"), (b"PK\x03\x04", "zip"), (b"\x1f\x8b", "gzip"), *UNDECODED_COMPRESSION):
        if text.startswith(magic):
            return kind
    if text[:1] in (b"{", b"["):
        return "json"
    if not text.startswith(b"<"):
        return "binary" if b"\x00" in text else "text"
    position, doctype = 0, b""
    while True:
        match = _PROLOG_RE.match(text, position)
        if not match:
            break
        doctype = doctype or (match.group(1) or b"")
        position = match.end()
    element = _ELEMENT_RE.match(text, position)
    root = element.group(1).lower() if element else b""
    return "html" if doctype.lower() == b"html" or root in _HTML_ROOTS else "xml"


def detect_error_page(
    body: bytes,
    *,
    status_code: int | None = None,
    url: str | None = None,
    media_types: tuple[str, ...] | None = None,
) -> ErrorPageMarker | None:
    """Stdlib port of `spicy_docs.reading.error_pages.detect_error_page`."""
    if not body or body.startswith(PDF_MAGIC):
        return None
    refusal = None if status_code is None else status_code in (401, 403, 429)
    if _S3_ACCESS_DENIED_MARKER in body[:_WALL_SCAN_BYTES]:
        return ErrorPageMarker(_S3_ACCESS_DENIED_MARKER.decode(), "s3-access-denied")
    wall = detect_wall(body, refusal=refusal)
    if wall is not None:
        return wall
    if url is not None and (
        is_govinfo_error_url(url)
        or (urlsplit(url).netloc == _GOVINFO_ERROR_PAGE[1] and has_govinfo_error_marker(body))
    ):
        return ErrorPageMarker("govinfo.gov/error", "govinfo-error")
    if refusal:
        return None
    if sniff(body[:SNIFF_BYTES]) != "html":
        return None
    title = _title_of(body)
    if title is not None:
        phrase = error_page_title(title)
        if phrase is not None:
            return ErrorPageMarker(phrase, "interstitial-title")
    expected = {mt.split(";", 1)[0].strip().lower() for mt in media_types or ()}
    if expected and not (expected & _HTML_MEDIA_TYPES):
        return ErrorPageMarker("html", "unexpected-html")
    return None


def detect_waf_or_error_page_v6(
    raw_bytes: bytes | None = None,
    *,
    html_text: str | None = None,
    effective_format: str | None = None,
    explicit_format: str | None = None,
    filename: str | None = None,
    status_code: int | None = None,
    url: str | None = None,
    expected_media_types: tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    """Strictly HTML / non-`%PDF-`-gated WAF, CDN challenge, S3 AccessDenied & GovInfo soft-404 detector.

    HARD INVARIANT (`0` FPs on PDF hearings titled `"Access Denied: ..."`):
      1. Raw `%PDF-` bytes ALWAYS return `None`.
      2. Confirmed `pdf` / `docx` / `doc` / `zip` / `image` / `video` rows WITHOUT raw HTML/XML bytes
         ALWAYS return `None` — `html_text` fallback NEVER runs on extracted PDF plain text!
      3. On raw HTML/XML capture bytes, runs `detect_error_page` (with `status_code=200` default when
         archive capture status is unrecorded so generic refusal-only phrases like bare `"Access Denied"`
         never trigger on legitimate publisher HTML quoting the phrase, while `<title>Access Denied</title>`,
         `captcha-delivery.com`, `errors.edgesuite.net`, `Cloudflare Ray ID`, `<Code>AccessDenied</Code>`,
         and `govinfo.gov/error` fire at 100% precision).
    """
    if raw_bytes is not None:
        if not raw_bytes or raw_bytes.startswith(PDF_MAGIC):
            return None
        sniffed = sniff(raw_bytes[:SNIFF_BYTES])
        if sniffed in ("pdf", "zip", "gzip", "bzip2", "xz", "zstd", "binary"):
            return None
        eff_status = 200 if status_code is None else status_code
        marker = detect_error_page(
            raw_bytes,
            status_code=eff_status,
            url=url,
            media_types=expected_media_types,
        )
        if marker is not None:
            return {
                "status": "error_or_block",
                "family": marker.family,
                "marker": str(marker),
                "is_wall": marker.wall,
                "error_reason": f"WAF/error page ({marker.family}): {marker}",
            }
        # Empty client-rendered SPA shell (`<div id="root">` with <120 visible chars outside script/style)
        if sniffed == "html" and detect_spa_shell(raw_bytes):
            clean_txt, _ = extract_clean_html_v6(raw_bytes, max_chars=600)
            if len(clean_txt.strip()) < 120:
                return {
                    "status": "stub_or_blank",
                    "family": "spa-shell",
                    "marker": '<div id="root">',
                    "is_wall": False,
                    "error_reason": "Unrendered client-side SPA shell (<div id=\"root\">)",
                }
        return None

    # No raw_bytes provided: STRICTLY gate on confirmed HTML format (NEVER PDF/office plain text!)
    fmt_eff = (effective_format or "").strip().lower()
    fmt_exp = (explicit_format or "").strip().lower()
    fn_low = (filename or "").strip().lower()
    if fmt_eff == "pdf" or fmt_exp == "pdf" or fn_low.endswith((".pdf", ".docx", ".doc", ".zip")):
        return None
    if fmt_eff not in ("html", "htm") and fmt_exp not in ("html", "htm"):
        return None

    if url is not None and is_govinfo_error_url(url):
        return {
            "status": "error_or_block",
            "family": "govinfo-error",
            "marker": "govinfo.gov/error",
            "is_wall": False,
            "error_reason": "GovInfo soft-404 error page",
        }

    if not html_text:
        return None

    probe_bytes = html_text[:16384].encode("utf-8", "replace")
    if _S3_ACCESS_DENIED_MARKER in probe_bytes:
        return {
            "status": "error_or_block",
            "family": "s3-access-denied",
            "marker": "<Code>AccessDenied</Code>",
            "is_wall": False,
            "error_reason": "S3 AccessDenied XML error response",
        }
    eff_status = 200 if status_code is None else status_code
    wall = detect_wall(probe_bytes, refusal=(eff_status in (401, 403, 429)))
    if wall is not None:
        return {
            "status": "error_or_block",
            "family": wall.family,
            "marker": str(wall),
            "is_wall": wall.wall,
            "error_reason": f"WAF/error page ({wall.family}): {wall}",
        }
    return None


# ===========================================================================
# N3 (Part C): Bare-UUID `infer_is_html_v6` + `url-rules.json` `&download=1`
# ===========================================================================

_PDF_DOC_EXT_RE = re.compile(r"\.(?:pdf_?|docx?|xlsx?|pptx?|rtf|csv)$", re.I)
_HTML_STRICT_EXT_RE = re.compile(r"\.(?:html?|php|cfm|jsp)$", re.I)
_ASPX_EXT_RE = re.compile(r"\.aspx?$", re.I)
_UUID_BASENAME_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_GPO_PDF_IMPRINT_RE = re.compile(
    r"U\.?\s*S\.?\s+GOVERNMENT\s+(?:PRINTING|PUBLISHING)\s+OFFICE\s+WASHINGTON\s*:",
    re.I,
)
_HTML_CHROME_CUE_RE = re.compile(
    r"(?:Skip to (?:main )?content|Skip to primary navigation|Skip Navigation|"
    r"Toggle navigation|Toggle Submenu|Report Waste, Fraud, and Abuse|"
    r"Drupal\.settings|<!--//--><!\[CDATA\[|\(window\.NREUM|"
    r"\{\"@context\":\"https?:|if\s*\(!application\)\s*var\s+application|"
    r"\(function\s*\(d,\s*s,\s*id\)|window\.dataLayer\s*=|"
    r"img:is\(\[sizes=|:root\s*\{--wp--preset|"
    r"Committee Repository Clerk of the House Majority Leader|"
    r"Open Submit Site Search Query|Upcoming Hearings There are no upcoming Hearings|"
    r"Media Center Press Releases Videos Statements|Stay connected with the Committee|"
    r"Internships News Listening To Americans|Open search form\s+search\s+Submit|"
    r"The Library of Congress\s*>\s*THOMAS Home|Post Log in\s*Sign up|"
    r"\[From the U\.S\. Government (?:Publishing|Printing) Office\]|"
    r"About Chairman Membership History Jurisdiction Rules|"
    r"About Jurisdiction and Rules Committee Membership|"
    r"The Chairman The Ranking Member FAQs Internships|"
    r"Committee Rules Clerkships Committee Activity|"
    r"History Rules Contact FAQs Whistleblower|"
    r"x\s+x\s+search\s+x\s+MENU)",
    re.I,
)
_URL_SLUG_BASENAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){1,}$")


def infer_is_html_v6(
    filename: str | None,
    text: str | None,
    *,
    is_html: bool | None = None,
    explicit_format: str | None = None,
) -> bool:
    """Infer whether `(filename, text, explicit_format)` is an HTML web page vs PDF/office document.

    Fixes V5's bare-UUID HTML blindspot (`expanded_rules_v5.py:150`): accepts `explicit_format == 'html'`
    (catching all Senate bare-UUID HTML event pages) and checks `_HTML_CHROME_CUE_RE` BEFORE
    `_UUID_BASENAME_RE` when `explicit_format` is omitted.
    """
    if is_html is not None:
        return bool(is_html)
    fmt = (explicit_format or "").strip().lower()
    if fmt in ("html", "htm", "xhtml"):
        return True
    if fmt in ("pdf", "docx", "doc", "xlsx", "pptx", "rtf", "csv", "zip", "image", "video"):
        return False

    base = (filename or "").strip().rsplit("/", 1)[-1]
    if _PDF_DOC_EXT_RE.search(base):
        return False
    if _HTML_STRICT_EXT_RE.search(base):
        return True

    t_sub = (text or "")[:1600]
    t_head = _WS_COLLAPSE_RE.sub(" ", t_sub).strip() if ("\n" in t_sub or "  " in t_sub) else t_sub.strip()
    if _HTML_CHROME_CUE_RE.search(t_head):
        return True
    if _UUID_BASENAME_RE.match(base):
        return False
    if _GPO_PDF_IMPRINT_RE.search(t_head[:400]):
        return False
    base_l = base.lower()
    if _ASPX_EXT_RE.search(base_l):
        return base_l not in ("documentsingle.aspx", "r.aspx")
    if _URL_SLUG_BASENAME_RE.match(base):
        return True
    return False


# Port of `congressional-tech/model/registries/url-rules.json`
_WAYBACK_WRAPPER_RE = re.compile(r"(?i)^https?://web\.archive\.org/web/[0-9]{14}(?:[a-z]+_)?/(https?://.+)$")
_LOC_WRAPPER_RE = re.compile(r"(?i)^https?://webarchive\.loc\.gov/all/[0-9]{14}(?:[a-z]+_)?/(https?://.+)$")
_LIS_GPO_WRAPPER_RE = re.compile(
    r"(?i)^https?://(?:www\.)?(?:lis|congress)\.gov/cgi-lis/t2GPO/(https?://(?:www\.)?gpo\.gov/fdsys/pkg/.+)$"
)
_PROOFPOINT_V2_RE = re.compile(r"(?i)^https?://(?:urldefense\.proofpoint\.com|urldefense\.com)/v2/url\?u=([^&]+).*$")
_SENATE_NOTFOUND_RE = re.compile(
    r"(?i)^(https?://(?:[a-z0-9-]+\.)+senate\.gov)/404\?notfound=(?:%2f|/)?([^#]+)(?:#.*)?$"
)
_CREATIVE_ENGINE_AMP_DOWNLOAD_RE = re.compile(
    r"(?i)^(https?://(?:[a-z0-9-]+\.)*(?:house|senate)\.gov/download/[^?#]+?)(?:%20|\s)*&download=1(?:#.*)?$"
)
_SENATE_CF_DOWNLOAD_HOST_RE = re.compile(
    r"(?i)^(?:.+\.)?(?:aging|appropriations|banking|budget|finance|veterans)\.senate\.gov$"
)


def strip_creative_engine_download_suffix(url: str) -> tuple[str, bool]:
    """Repair CreativeEngine `&download=1` appended without `?` (`4,862` docs in `sources.parquet`).

    Rewrites `.../download/<slug>&download=1` -> `.../download/<slug>?download=1` so URL path/slug
    parsers never glue `&download=1` onto the filename slug.
    """
    if not url or "&download=1" not in url.lower():
        return url, False
    m = _CREATIVE_ENGINE_AMP_DOWNLOAD_RE.match(url.strip())
    if m:
        return f"{m.group(1)}?download=1", True
    return url, False


def normalize_congressional_url_v6(url: str) -> tuple[str, list[str]]:
    """Port of `congressional-tech/model/registries/url-rules.json` URL wrapper & `&download=1` rules."""
    if not url:
        return "", []
    cur = url.strip()
    applied: list[str] = []

    for rule_id, rx in (
        ("wayback", _WAYBACK_WRAPPER_RE),
        ("loc", _LOC_WRAPPER_RE),
        ("lis-gpo", _LIS_GPO_WRAPPER_RE),
    ):
        m = rx.match(cur)
        if m:
            cur = m.group(1)
            applied.append(rule_id)

    m_pp = _PROOFPOINT_V2_RE.match(cur)
    if m_pp:
        encoded = _html_mod.unescape(m_pp.group(1))
        decoded = re.sub(
            r"-([0-9A-Fa-f]{2})",
            lambda hm: chr(int(hm.group(1), 16)),
            encoded.replace("_", "/"),
        )
        cur = decoded
        applied.append("proofpoint-v2")

    m_snf = _SENATE_NOTFOUND_RE.match(cur)
    if m_snf:
        cur = f"{m_snf.group(1)}/{unquote(m_snf.group(2))}"
        applied.append("senate-notfound")

    cur, dl_fixed = strip_creative_engine_download_suffix(cur)
    if dl_fixed:
        applied.append("download-ampersand-query")

    try:
        sp = urlsplit(cur)
        if sp.query and sp.hostname:
            host = sp.hostname
            is_cf_dl = bool(_SENATE_CF_DOWNLOAD_HOST_RE.match(host))
            is_cong = bool(re.match(r"(?i)^(?:www\.)?congress\.gov$", host))
            kept_q: list[str] = []
            dropped_any = False
            for pair in sp.query.split("&"):
                k = pair.split("=", 1)[0]
                if k.lower().startswith("utm_"):
                    dropped_any = True
                    if "trackers" not in applied:
                        applied.append("trackers")
                    continue
                if is_cong and k == "q":
                    dropped_any = True
                    if "congress-search" not in applied:
                        applied.append("congress-search")
                    continue
                if is_cf_dl and k.lower() == "download":
                    dropped_any = True
                    if "senate-coldfusion-download" not in applied:
                        applied.append("senate-coldfusion-download")
                    continue
                kept_q.append(pair)
            if dropped_any:
                cur = urlunsplit((sp.scheme, sp.netloc, sp.path, "&".join(kept_q), sp.fragment))
    except ValueError:
        pass

    return cur, applied


# ===========================================================================
# N4: Cold-R2 Object Key Builder
# ===========================================================================


def build_r2_body_key(body_sha_hex: str, saved_suffix: str | None = None) -> str:
    """Build canonical `congressional-tech` R2 object key: `bodies/sha256/<sha[:2]>/<sha><saved_suffix>`."""
    sha = (body_sha_hex or "").strip().lower()
    if len(sha) != 64:
        raise ValueError(f"Expected 64-char hex sha256, got {body_sha_hex!r}")
    suf = saved_suffix or ""
    return f"bodies/sha256/{sha[:2]}/{sha}{suf}"


# ===========================================================================
# N11 (Part A): Witness-Name & Witness-List PDF Parsers (`witness_names.py` + `witness_pdf.py`)
# ===========================================================================

MILITARY_RANK_PHRASE = (
    r"(?:Sergeant Major of the (?:Army|Marine Corps)"
    r"|Master Chief Petty Officer of the Navy"
    r"|Chief Master Sergeant of the (?:Air|Space) Force"
    r"|(?:Command |First )?Sergeant Major|(?:Chief |Senior )?Master Sergeant"
    r"|(?:Master |Senior )?Chief Petty Officer|Senior Chief|Petty Officer(?: (?:First|Second|Third) Class)?"
    r"|Chief Warrant Officer(?: [2-5]| (?:Two|Three|Four|Five))?|Warrant Officer(?: 1)?"
    r"|Rear Admiral(?: \(?(?:Upper|Lower) Half\)?)?|Vice Admiral"
    r"|(?:Lieutenant|Major|Brigadier) General|Lieutenant (?:Colonel|Commander|Junior Grade)"
    r"|(?:First|Second) Lieutenant|(?:Gunnery|Technical|Staff|First) Sergeant|Sergeant First Class"
    r"|Lance Corporal|Private First Class|Senior Airman|Airman First Class"
    r"|(?:Rear|Vice) (?:Adm\.?|Admiral)|(?:Lt|Maj|Brig)\.? (?:Gen\.?|General)|Lt\.? (?:Col\.?|Colonel|Cmdr\.?|Commander)|(?:1st|2nd) (?:Lt\.?|Lieutenant)"
    r"|(?:(?:Command )?Sgt\.? Maj|Master Sgt|Tech\.? Sgt|Staff Sgt|1st Sgt)\.?|CWO-?[2-5]|CW[2-5]"
    r"|General|Gen\.|GEN|LTG|MG|BG|LtGen|LTGEN|MajGen|MAJGEN|BrigGen|BRIGGEN|BGen|BGEN"
    r"|Admiral|Adm\.|ADM|VADM|RADM|RDML"
    r"|Colonel|Col\.|COL|LTC|LtCol|LTCOL"
    r"|Commander|Cmdr\.|CDR|LCDR"
    r"|Major|Maj\.|MAJ"
    r"|Captain|Capt\.|CAPT|CPT"
    r"|Lieutenant|Lt\.|LT|1LT|2LT|LTJG|Ensign|ENS"
    r"|Sergeant|Sgt\.|SGT|SMA|SMMC|CMSAF|MCPON|CSM|SGM|SgtMaj|SGTMAJ|MSG|MSgt|MSGT|GySgt|GYSGT|TSgt|TSGT|SSG|SSgt|SSGT|SFC|1SG|CMSgt|CMSGT|SMSgt|SMSGT"
    r"|MCPO|SCPO|CPO"
    r"|Corporal|Cpl\.|CPL|LCpl|LCPL|Specialist|Spc\.|SPC|Seaman|Private|Pvt\.|PFC|SrA|SRA)"
)

_CIVIL_OR_CIVIC_TITLE = (
    "(?:"
    + "|".join(
        """Hon Honorable Honorables Mr Ms Mrs Miss Mx Dr Prof Professor Rev Reverend Pastor Rabbi Sister Sir Senator Sen Representative Rep Ambassador Amb
    Governor Gov Mayor President Officer Detective Sheriff Chief""".split()
    )
    + r")\.?"
)
_TITLE_PART = r"(?:" + MILITARY_RANK_PHRASE + r"|" + _CIVIL_OR_CIVIC_TITLE + r")"
_PREFIX_BRANCH_RET = (
    r"(?: (?:USA|USN|USAF|USMC|USCG|USSF|USPHS|USAR|USNR|USAFR|USMCR|USCGR))?"
    r"(?: [(\[](?:(?:USA|USN|USAF|USMC|USCG|USSF|USPHS|USAR|USNR|USAFR|USMCR|USCGR),? )?(?:Dr|[Rr]et(?:ired)?|RET)\.?[)\]])?"
)
_WIT_TITLE_RE = re.compile(
    r"^(?:[Tt]he )?(" + _TITLE_PART + ")(?: " + _TITLE_PART + r")*" + _PREFIX_BRANCH_RET + r"(?: +|(?<=\.)(?=[A-Z]))"
)
_CIVIL_PREFIX_RE = re.compile(
    r"^(?:[Tt]he )?(?:Hon\.?|Honorables?|Mr\.?|Ms\.?|Mrs\.?|Miss|Mx\.?|Dr\.?|Prof\.?|Professor|Rev\.?|Reverend"
    r"|Pastor|Rabbi|Sister|Sir|Senator|Sen\.?|Representative|Rep\.?|Ambassador|Amb\.?|Governor|Gov\.?"
    r"|Mayor)(?: +|(?<=\.)(?=[A-Z]))"
)
_WIT_SUFFIX_RE = re.compile(r"^(Jr|Sr|II|III|IV)\.?$")
_PARTICLE_SURNAME_RE = re.compile(r"^(?:(?:van|von|de|den|del|der|della|di|da|du|la|le|ten|ter) )+[A-Z][\w'’-]*$")
_DEGREE_RE = re.compile(
    r"^(?:(?:Ph|PH|[Ee][Dd]|[Pp]sy|PSY|[Pp]harm|PHARM|[Ss][Cc])\.? ?D|[Dd][Rr]\.? ?P\.? ?H|D\.?P\.?H|D\.?D\.?S|D\.?M\.?D|D\.?V\.?M|V\.?M\.?D"
    r"|D\.?O|O\.?D|D\.?P\.?M|D\.?N\.?P|D\.?P\.?A|D\.?B\.?A|D\.?H\.?A|M\.?D|J\.?D|LL\.?[BM]|Esq"
    r"|M\.?P\.?H|M\.?S\.?P\.?H|M\.?H\.?S|M\.?H\.?A|M\.?B\.?A|M\.?P\.?A|M\.?P\.?P|M\.?S\.?W|M\.?S\.?N"
    r"|C\.?P\.?A|R\.?N)\.?$"
)
_BRANCH_ABBR = r"(?:USA|U\.S\.A\.|USN|U\.S\.N\.|USAF|U\.S\.A\.F\.|USMC|U\.S\.M\.C\.|USCG|U\.S\.C\.G\.|USSF|U\.S\.S\.F\.|USPHS|U\.S\.P\.H\.S\.|USAR|USNR|USAFR|USMCR|USCGR|ARNG|USARNG|ANG)"
_BRANCH_FULL = r"(?:U\.S\.|US|United States)\s+(?:Army|Navy|Air Force|Marine Corps|Coast Guard|Space Force|Public Health Service)(?: Reserve)?"
_RET_SUFFIX = r"[(\[]?(?:[Rr]et(?:ired)?\.?|RET)[)\]]?"
_SINGLE_CREDENTIAL = (
    r"(?:"
    r"(?:Ph|PH|[Ee][Dd]|[Pp]sy|PSY|[Pp]harm|PHARM|[Ss][Cc])\.? ?D\.?|D\.?Phil\.?|D\.?Sc\.?|[Dd][Rr]\.? ?P\.? ?H\.?|D\.?P\.?H\.?"
    r"|M\.?D\.?|M\.?B\.?B\.?S\.?|D\.?O\.?|J\.?D\.?|LL\.?[BM]\.?|S\.?J\.?D\.?|Esq\.?"
    r"|D\.?D\.?S\.?|D\.?M\.?D\.?|D\.?V\.?M\.?|V\.?M\.?D\.?|O\.?D\.?|D\.?P\.?M\.?"
    r"|D\.?N\.?P\.?|D\.?N\.?S\.?|D\.?S\.?W\.?|D\.?P\.?A\.?|D\.?B\.?A\.?|D\.?H\.?A\.?|Th\.?D\.?|D\.?Min\.?"
    r"|M\.?P\.?H\.?|M\.?S\.?P\.?H\.?|M\.?S\.?H\.?A\.?|M\.?H\.?S\.?|M\.?H\.?A\.?|M\.?B\.?A\.?|M\.?P\.?A\.?|M\.?P\.?P\.?"
    r"|M\.?S\.?W\.?|M\.?S\.?N\.?|M\.?Ed\.?|M\.?Div\.?|[Mm]\.?[Ss]c\.?|M\.?A\.?|M\.?S\.?|B\.?S\.?N\.?|B\.?A\.?|B\.?S\.?"
    r"|R\.?N\.?|R\.?N\.?P\.?|A\.?P\.?R\.?N\.?|F\.?N\.?P\.?|N\.?P\.?|P\.?A\.?-C\.?|L\.?C\.?S\.?W\.?"
    r"|C\.?P\.?A\.?|C\.?F\.?A\.?|P\.?E\.?|F\.?A\.?C\.?[A-Z]{1,4}\.?|F\.?A\.?A\.?P\.?|F\.?A\.?C\.?E\.?"
    r"|" + _BRANCH_ABBR + r"(?:,?\s*" + _RET_SUFFIX + r")?"
    + r"|" + _BRANCH_FULL + r"(?:,?\s*" + _RET_SUFFIX + r")?"
    + r"|[(\[](?:(?:" + _BRANCH_ABBR + r"|" + _BRANCH_FULL + r"),?\s+)?(?:[Rr]et(?:ired)?\.?|RET)[)\]]"
    + r")"
)
_CREDENTIAL_RE = re.compile(r"^" + _SINGLE_CREDENTIAL + r"(?:(?:\s+|,\s*)" + _SINGLE_CREDENTIAL + r")*\.?$")
_RET_PAREN_INLINE_RE = re.compile(
    r"[(\[](?:(?:" + _BRANCH_ABBR + r"|" + _BRANCH_FULL + r"),?\s+)?(?:[Rr]et(?:ired)?\.?|RET)[)\]]"
    r"|[(\[](?:[Rr]et(?:ired)?\.?|RET),?\s+(?:" + _BRANCH_ABBR + r"|" + _BRANCH_FULL + r")[)\]]"
)
_TRAILING_RET_PAREN_RE = re.compile(r"\s*(" + _RET_PAREN_INLINE_RE.pattern + r")$")
_TOP_COMMA_RE = re.compile(r",(?![^(\[]*[)\]])")
_LEADING_SEG_CREDENTIAL_RE = re.compile(
    r"^(" + _SINGLE_CREDENTIAL + r"(?:(?:\s+|,\s*)" + _SINGLE_CREDENTIAL + r")*)\.*"
    r"(?:\s+(?!(?:[Cc]andidate|[Ss]tudent)\b)(?=[A-Za-z(\[])|;\s*)"
)

_CONNECTIVE_WORDS = {"and", "of", "for", "the", "to", "in", "on", "from", "by", "with", "at"}
_NOT_A_NAME_WORDS = {
    "director", "manager", "officer", "president", "secretary", "administrator", "commissioner", "commissioners",
    "chairman", "chairwoman", "counsel", "attorney", "founder", "owner", "executive", "specialist", "professional",
    "coordinator", "advocate", "advocacy", "superintendent", "treasurer", "record", "testimony", "statement",
    "hearing", "panel", "witnesses", "committee", "subcommittee", "department", "office", "university", "institute",
}
_ORG_PREFIX_RE = re.compile(
    r"^(?:The\s+)?(?:U\.?S\.?\s+|United States\s+)?(?:(?:Department|Office|Bureau|Agency|Board|Commission|Committee"
    r"|Subcommittee|Court|House)\s+of\b|Senate\b|House of Representatives\b)"
)
_ORG_NOUN_RE = re.compile(
    r"\b(?:Departments?|Offices?|Administrations?|Agenc(?:y|ies)|Bureaus?|Services?|Commissions?|Associations?"
    r"|Institutes?|Institutions?|Foundations?|Federations?|Unions?|Leagues?|Societ(?:y|ies)|Coalitions?"
    r"|Committees?|Subcommittees?|Councils?|Boards?|Chambers?|Centers?|Clinics?|Hospitals?|Universit(?:y|ies)"
    r"|Colleges?|Schools?|Academ(?:y|ies)|Laborator(?:y|ies)|Labs?|Corporations?|Corp\b|Compan(?:y|ies)|Co\b|Inc\b"
    r"|L\.?L\.?C\b|Ltd\b|Groups?|Partnerships?|Banks?|Technologies|Systems|Solutions|Industries|Enterprises"
    r"|Airlines|Communications|Networks?|Alliances?|Funds?|Trusts?|Projects?|Programs?|Authorit(?:y|ies)"
    r"|Commands?|Air Force|Space Force|Armed Forces|Marine Corps|Coast Guard|National Guard|U\.?S\.?\s+(?:Army|Navy|Senate)"
    r"|House of Representatives|Courts?|Tribes?|Ministries|Veterans of|Paralyzed Veterans|American Legion"
    r"|AMVETS|AARP|AFL-CIO|NAACP|ACLU|NFIB|NASA|NOAA|EPA|FDA|FCC|FTC|GAO|CBO|OMB|FEMA|TSA|CDC|NIH)\b"
)
_PERSONAL_ROLE_RE = re.compile(
    r"\b(?:Directors?|Managers?|Officers?|Presidents?|Vice[- ]Presidents?|Secretar(?:y|ies)|Undersecretar(?:y|ies)"
    r"|Administrators?|Commissioners?|Chair(?:man|woman|person|s)?|Co-Chairs?|Ranking Member|Counsel|Attorney"
    r"|Lawyer|Founders?|Co-Founders?|Owner|Executive|CEO|CFO|COO|CIO|CTO|EVP|SVP|Specialists?|Coordinators?"
    r"|Advocate|Superintendents?|Treasurers?|Comptrollers?|Auditors?|Inspectors?|Generals?|Admirals?|Colonels?"
    r"|Commanders?|Majors?|Captains?|Lieutenants?|Sergeants?|Senators?|Representative|Delegates?|Congress(?:man|woman)"
    r"|Members?|Ambassadors?|Governors?|Mayors?|Sheriff|Judges?|Justices?|Deans?|Provosts?|Chancellors?|Principals?"
    r"|Professors?|Fellows?|Scholars?|Analysts?|Economists?|Scientist|Researchers?|Historians?|Physician|Doctor"
    r"|Partners?|Consultants?|Advis[eo]rs?|Chiefs?|Heads?|Leads?|Spokes(?:person|man|woman)|Trustees?"
    r"|Nominees?|to be\b|Acting\b|Former\b|Retired\b|Emeritus\b|Veteran|Landowner|Rancher|Farmer)\b",
    re.I,
)


def _is_organization_only(segment: str) -> bool:
    s = segment.strip()
    if not s:
        return False
    probe = s.title() if s.isupper() else s
    if (_ORG_PREFIX_RE.search(s) or _ORG_PREFIX_RE.search(probe)) and not re.match(
        r"^(?:a |the |former |acting )?(?:U\.?S\.? |United States )?(?:Senator|Representative|Delegate|Member)\b",
        s,
        re.I,
    ):
        return True
    return bool(_ORG_NOUN_RE.search(s) or _ORG_NOUN_RE.search(probe)) and not bool(
        _PERSONAL_ROLE_RE.search(s) or _PERSONAL_ROLE_RE.search(probe)
    )


def _is_person_name(text: str) -> bool:
    words = [w.strip(",.-/").lower() for w in text.split()]
    return (
        2 <= len(words) <= 6
        and bool(text[:1])
        and text[:1].isupper()
        and not any(c.isdigit() for c in text)
        and not ((_CONNECTIVE_WORDS | _NOT_A_NAME_WORDS) & set(words))
    )


_FOOTNOTE_RE = re.compile(r"\s*\\(?:\d+|\*)\\")
_LEADER_RE = re.compile(r"\s*\.{4,}\s*(?:\d+(?:-\d+)?(?:,\s*\d+(?:-\d+)?)*,?)?\s*")
_ANSWER_WORDS = (
    r"(?:answers? to (?:submitted |additional )?questions|submitted questions"
    r"|responses? to (?:(?:submitted |additional |written )?questions|question submitted for the record))"
)
_LABEL_WORDS = (
    r"(?:(?:supplement to |joint )?(?:opening |prepared |written )?statements?(?: and attachments)?(?: \d+)?(?: of)?"
    r"|" + _ANSWER_WORDS
    + r"|additional (?:information|materials?)(?: supplied)?(?: (?:submitted )?for the record)?)"
)
_LABEL_END = r"(?:\s*\\(?:\d+|\*)\\)*(?:\s*\.{3,}\s*(?:[\d\-]+\S*(?: deg\.)?)?)?"
_CONTENTS_LABEL_RE = re.compile(
    r"^\s*" + _LABEL_WORDS + r":?(?:(?:\s*\\(?:\d+|\*)\\)+" + _LABEL_END + r"|\s*\.{3,}\s*(?:[\d\-]+\S*(?: deg\.)?)?)\s*",
    re.I,
)
_UNMARKED_LABEL_RE = re.compile(
    r"^\s*(?:" + _ANSWER_WORDS + _LABEL_END + r",|" + _LABEL_WORDS + _LABEL_END + r"(?::|\s+(?:from|with|by))?)\s+(?=[A-Z])",
    re.I,
)
_ENTRY_WORDS_RE = re.compile(
    r"^\W*(?:" + _LABEL_WORDS + r"|insert for the record|letters?\b|response|charts?\b|slides?\b|articles?\b)",
    re.I,
)


def _split_witness_commas(text: str) -> list[str]:
    protected: list[str] = []

    def _stash(m: re.Match[str]) -> str:
        protected.append(m.group(0))
        return f"\x00RET{len(protected) - 1}\x00"

    masked = _RET_PAREN_INLINE_RE.sub(_stash, text)
    out: list[str] = []
    for seg in masked.split(","):
        s = seg.strip()
        if not s:
            continue
        for idx, val in enumerate(protected):
            s = s.replace(f"\x00RET{idx}\x00", val)
        out.append(s)
    return out


def _pop_trailing_credentials_from_words(words: list[str], *, min_words: int) -> list[str]:
    popped: list[str] = []
    while len(words) > min_words and _CREDENTIAL_RE.match(words[-1]) and not _WIT_SUFFIX_RE.match(words[-1]):
        popped.append(words.pop())
    popped.reverse()
    return popped


def peel_leading_position_credentials(
    position: str | None, credentials: str | None = None
) -> tuple[str | None, str | None]:
    pos = re.sub(r"\s+", " ", (position or "").strip())
    existing = [c.strip() for c in (credentials or "").split(",") if c.strip()]
    if not pos:
        return (None, ", ".join(existing) if existing else None)

    peeled: list[str] = []
    if _CREDENTIAL_RE.match(pos) and not re.fullmatch(_BRANCH_ABBR + r"|" + _BRANCH_FULL, pos):
        peeled.append(pos)
        pos = ""
    else:
        segs = _split_witness_commas(pos)
        while len(segs) >= 2:
            if (
                len(segs) >= 3
                and re.fullmatch(_BRANCH_ABBR + r"|" + _BRANCH_FULL, segs[0])
                and re.fullmatch(r"[Rr]et(?:ired)?\.?|RET", segs[1])
            ):
                peeled.append(f"{segs[0]}, {segs[1]}")
                segs = segs[2:]
                continue
            if _CREDENTIAL_RE.match(segs[0]):
                peeled.append(segs.pop(0))
                continue
            break
        if peeled and segs:
            lead_m = _LEADING_SEG_CREDENTIAL_RE.match(segs[0])
            if lead_m:
                tok = lead_m.group(1).strip()
                rem = segs[0][lead_m.end() :].strip()
                if rem and not re.fullmatch(_BRANCH_ABBR + r"|" + _BRANCH_FULL, tok):
                    peeled.append(tok)
                    segs[0] = rem
        if peeled:
            pos = ", ".join(segs)

    merged = list(existing)
    seen_norm = {m.replace(".", "").lower() for m in merged}
    for item in peeled:
        norm = item.replace(".", "").lower()
        if item and norm not in seen_norm:
            merged.append(item)
            seen_norm.add(norm)
    return (pos or None, ", ".join(merged) if merged else None)


def _split_leaders(text: str) -> str:
    items = [item.strip(" ,") for item in _LEADER_RE.split(text) if item.strip(" ,")]
    if len(items) <= 1:
        return items[0] if items else ""
    if not _ENTRY_WORDS_RE.match(items[0]) and _is_person_name(witness_line_parse(items[0], _raw=True)["name"]):
        return ", ".join([items[0], *(item for item in items[1:] if not _ENTRY_WORDS_RE.match(item))])
    people = [
        item
        for item in items[1:]
        if "," in item
        and not _ENTRY_WORDS_RE.match(item)
        and _is_person_name(witness_line_parse(item, _raw=True)["name"])
    ]
    return people[-1] if people else items[0]


def _strip_contents_markers(text: str) -> str:
    while True:
        label = _CONTENTS_LABEL_RE.match(text)
        if not label:
            break
        text = text[label.end() :]
    label2 = _UNMARKED_LABEL_RE.match(text)
    if label2 and _is_person_name(witness_line_parse(text[label2.end() :], _raw=True)["name"]):
        text = text[label2.end() :]
    return _split_leaders(_FOOTNOTE_RE.sub("", text)).strip()


def witness_line_parse(text: str, *, _raw: bool = False) -> dict[str, str]:
    """Stdlib port of `congress_api.parsers.witness_names.witness`."""
    if not _raw:
        text = _strip_contents_markers(text)
    text = re.sub(
        r"^\s*(?:(?:opening |prepared |written )?(?:statements?|testimony|remarks) (?:of|by|from)|accompanied by:?|witness(?:es)?:?|panel \w+:?)\s+",
        "",
        text.strip(),
        flags=re.I,
    )
    text = re.sub(r"\s*\([^)]*\d[^)]*\)|\s*[(\[](?:\w+ )?(?:fmr|former)\.?[)\]]", "", text, flags=re.I)

    pre_creds: list[str] = []
    post_creds: list[str] = []
    rank = ""

    title = _WIT_TITLE_RE.match(text)
    after_title = text[title.end() if title else 0 :]
    if title:
        p = re.sub(r"\s+", " ", title.group(0).strip())
        ret_m = re.search(
            r"\s*((?:" + _BRANCH_ABBR + r"\s+)?[(\[](?:(?:" + _BRANCH_ABBR + r"),?\s+)?(?:[Rr]et(?:ired)?\.?|RET)[)\]])$",
            p,
        )
        if ret_m:
            pre_creds.append(ret_m.group(1).strip())
            p = p[: ret_m.start()].strip()
        while True:
            cm = _CIVIL_PREFIX_RE.match(p + " ")
            if not cm:
                break
            p = (p + " ")[cm.end() :].strip()
        if p and re.fullmatch(MILITARY_RANK_PHRASE, p):
            rank = p

    parts = _split_witness_commas(after_title)
    name, rest = (parts[0] if parts else ""), parts[1:]
    if len(name.split()) == 2 and _WIT_SUFFIX_RE.match(name.split()[1]):
        name, rest = name.split()[0], [name.split()[1]] + rest
    elif len(name.split()) == 2 and _DEGREE_RE.match(name.split()[1]) and rest:
        name, rest = name.split()[0], [name.split()[1]] + rest

    is_particle_surname = bool(
        name
        and " " in name
        and _PARTICLE_SURNAME_RE.match(name)
        and rest
        and not _is_organization_only(rest[0])
        and rest[0].strip(",.-/").lower() not in _NOT_A_NAME_WORDS
    )
    is_leading_acronym = bool(
        re.fullmatch(r"[A-Z]{2,6}", name)
        and rest
        and any(c.islower() for c in rest[0])
        and (" " in rest[0] or rest[0].lower() == "resolution")
    )
    if name and (" " not in name or is_particle_surname) and rest and not is_leading_acronym:
        suffix = rest.pop(0) if _WIT_SUFFIX_RE.match(rest[0]) else ""
        if rest and _TRAILING_RET_PAREN_RE.fullmatch(rest[0]):
            pre_creds.append(rest.pop(0).strip())
        while rest and _DEGREE_RE.match(rest[0]) and len(rest) >= 2:
            pre_creds.append(rest.pop(0))
        given_raw = rest.pop(0) if rest else ""
        if given_raw:
            given_clean = _WIT_TITLE_RE.sub("", given_raw + " ").strip()
            ret_m = _TRAILING_RET_PAREN_RE.search(given_clean)
            if ret_m:
                post_creds.append(ret_m.group(1).strip())
                given_clean = given_clean[: ret_m.start()].strip()
            given = given_clean.split()
            given_space_creds = _pop_trailing_credentials_from_words(given, min_words=1)
            if given_space_creds:
                post_creds = [" ".join(given_space_creds), *post_creds]
            if given and _WIT_SUFFIX_RE.match(given[-1]):
                suffix = given.pop()
            if not suffix and rest and _WIT_SUFFIX_RE.match(rest[0]):
                suffix = rest.pop(0)
            name = " ".join(filter(None, [*given, name, suffix]))
        else:
            name = " ".join(filter(None, [name, suffix]))
    elif rest and _WIT_SUFFIX_RE.match(rest[0]):
        name = f"{name} {rest.pop(0)}"

    name_ret = ""
    ret_m = _TRAILING_RET_PAREN_RE.search(name)
    if ret_m:
        name_ret = ret_m.group(1).strip()
        name = name[: ret_m.start()].rstrip()
    name = re.sub(r"\s*[(\[][^)\]]*[)\]]?$", "", name)

    words = name.split()
    space_creds = _pop_trailing_credentials_from_words(words, min_words=2)
    name = " ".join(words)
    if space_creds and name_ret and re.fullmatch(_BRANCH_ABBR, space_creds[-1]):
        post_creds.append(" ".join(space_creds) + " " + name_ret)
    else:
        if space_creds:
            post_creds.append(" ".join(space_creds))
        if name_ret:
            post_creds.append(name_ret)

    while rest:
        if (
            len(rest) >= 2
            and re.fullmatch(_BRANCH_ABBR + r"|" + _BRANCH_FULL, rest[0])
            and re.fullmatch(r"[Rr]et(?:ired)?\.?|RET", rest[1])
        ):
            post_creds.append(f"{rest[0]}, {rest[1]}")
            rest = rest[2:]
            continue
        s0 = rest[0].rstrip(".") if rest[0].endswith("..") else rest[0]
        if _CREDENTIAL_RE.match(s0):
            post_creds.append(s0)
            rest.pop(0)
            continue
        lead_m = _LEADING_SEG_CREDENTIAL_RE.match(rest[0])
        if lead_m:
            cred_tok = lead_m.group(1).strip()
            rem_seg = rest[0][lead_m.end() :].strip()
            post_creds.append(cred_tok)
            if rem_seg:
                rest[0] = rem_seg
            else:
                rest.pop(0)
            continue
        break

    rest = [re.sub(r"\s*[(\[](?:\w+ )?ret(?:ired)?\.?[)\]]", "", s, flags=re.I).strip() for s in rest]
    rest = [s for s in rest if s]
    credentials = ", ".join([*pre_creds, *post_creds])
    honorific = title.group(1) if title else ""
    if len(rest) == 1 and (_is_person_name(name) or (name.isupper() and _is_person_name(name.title()))) and _is_organization_only(rest[0]):
        position, organization = "", rest[0]
    else:
        position, organization = (rest[0] if rest else ""), ", ".join(rest[1:])
    return {
        "name": name,
        "honorific": honorific,
        "rank": rank,
        "credentials": credentials,
        "position": position,
        "organization": organization,
    }


def person_key(name: str) -> str:
    parts = [
        p
        for p in re.sub(r"[^\w\s-]", "", name).lower().split()
        if p
        not in (
            "hon", "the", "mr", "ms", "mrs", "dr", "senator", "representative",
            "chairman", "chairwoman", "chair", "jr", "sr", "ii", "iii",
        )
    ]
    if not parts:
        return "unknown"
    return parts[-1] if len(parts) == 1 else f"{parts[-1]}-{parts[0]}"


# Port of `congress_api/parsers/reviewed_witness_lists.py`
REVIEWED_WITNESS_LISTS: dict[str, list[dict[str, Any]]] = {
    "8a42957a8037431ba5284e79cb3e09531f2b01473d2e5698d4504dd3aabec1d9": [
        {"name": "Vivek Wadhwa", "position": "Director of Research", "organization": "Pratt School of Engineering, Duke University", "panel": 1},
        {"name": "Michael Teitelbaum", "position": "Senior Advisor; Wertheim Fellow", "organization": "Alfred P. Sloan Foundation; Harvard Law School", "panel": 1},
        {"name": "Puneet S. Arora", "position": "Chairman of the Board", "organization": "Immigration Voice", "panel": 1},
        {"name": "Julian Castro", "position": "Mayor of San Antonio, Texas", "organization": "", "panel": 1},
        {"name": "Julie Myers Wood", "position": "President", "organization": "Guidepost Solutions LLC", "panel": 2},
        {"name": "Chris Crane", "position": "President", "organization": "National Immigration and Customs Enforcement Council 118, American Federation of Government Employees", "panel": 2},
        {"name": "Jessica Vaughan", "position": "Director of Policy Studies", "organization": "Center for Immigration Studies", "panel": 2},
        {"name": "Muzaffar Chishti", "position": "Director, Migration Policy Institute's Office", "organization": "New York University School of Law", "panel": 2},
    ],
    "c96bd593842c9462b364f5f50d05647855020a8f35f6b54f74b7e7ea35bb0838": [
        {"name": "Tim Spisak", "position": "Deputy Assistant Director", "organization": "Minerals and Realty Management, Bureau of Land Management, Department of the Interior", "panel": 1},
        {"name": "Daniel Garcia-Diaz", "position": "Director", "organization": "National Resources and Environment, U.S. Government Accountability Office", "panel": 1},
        {"name": "Kimberly Elmore", "position": "Assistant Inspector General for Audits, Inspections, and Evaluations", "organization": "U.S. Department of the Interior", "panel": 1},
        {"name": "Rodney Morgan", "position": "VP of Procurement", "organization": "Micron Technology", "panel": 2},
        {"name": "Brad Boersen", "position": "Director, Strategic Planning & Analysis for Optical Fiber", "organization": "Corning Incorporated", "panel": 2},
        {"name": "Gary Page", "position": "President", "organization": "Helium & Balloons Across America", "panel": 2},
        {"name": "Sam Aronson", "position": "Vice President", "organization": "APS Physics", "panel": 2},
        {"name": "David Joyner", "position": "President", "organization": "Air Liquide Helium America, Inc.", "panel": 3},
        {"name": "Tom Thoman", "position": "Division President – Gases Production", "organization": "Airgas, Inc.", "panel": 3},
        {"name": "Kevin Lynch", "position": "Sr. Vice President", "organization": "Specialty Gases & Helium, Matheson Tri-Gas", "panel": 3},
        {"name": "Walter Nelson", "position": "Director, Sourcing & Supply Chain", "organization": "Air Products and Chemicals, Inc.", "panel": 3},
        {"name": "Nick Haines", "position": "Head Global Helium Source Development", "organization": "Linde North America", "panel": 3},
        {"name": "Scott Kaltrider", "position": "VP, Business Management and Helium", "organization": "Praxair, Inc.", "panel": 3},
    ],
    "1e71b980a8979b5f804864a8ba47afa5357ee4ea49d99d1c9da6eba3f60a0525": [
        {"name": "Scott D. O’Malia", "position": "Commissioner", "organization": "U.S. Commodity Futures Trading Commission, Washington, DC", "panel": None},
        {"name": "Mark P. Wetjen", "position": "Commissioner", "organization": "U.S. Commodity Futures Trading Commission, Washington, DC", "panel": None},
    ],
    "665f835e1c345e962131b44956f31901723c54b314ce71e51b7252df340dfaa3": [
        {"name": "Maria Contreras-Sweet", "position": "Administrator", "organization": "United States Small Business Administration, Washington, DC", "panel": None},
    ],
    "ace2f3fa4c9b324c953716c1f8ec913966acace15fd279134a766585653a5a4c": [
        {"name": "Donald F. McGahn II", "position": "Former White House Counsel", "organization": "Office of White House Counsel", "panel": None},
    ],
}


@dataclass(frozen=True)
class DocumentWitness:
    name: str
    position: str
    organization: str
    credentials: str = ""
    honorific: str = ""
    rank: str = ""
    panel: int | None = None


_PANEL_HEADER_RE = re.compile(
    r"^panel\s+(?:(?P<num>\d+)|(?P<rom>I|II|III|IV|V|VI)|(?P<word>one|two|three|four|five))\b",
    re.I,
)
_ROMAN_TO_INT = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}
_WORD_TO_INT = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
_WIT_BLOCK_STOP_RE = re.compile(
    r"^(?:#{2,}|\*{3,}|-\s*-\s*-|Page\s+\d+\b|Accompanying\s+Witness(?:es)?:?\s*$|witness(?:es)?\b|\*+\s*$|Note:)",
    re.I,
)


_CONVERSATION_NAME_GUARD_RE = re.compile(
    r"(?i:\b(?:Mr|Mrs|Ms|Dr)\.\s*$|\b(?:good\s+copy|thank\s+you)\b)"
    r"|\b[a-z]{3,}\.\s+[A-Z][a-z]+",
)


def parse_document_witnesses(text: str) -> list[DocumentWitness]:
    """Stdlib port of `congress_api.parsers.witness_pdf.parse_document_witnesses` (+ panel & creds)."""
    out: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    active_panel: int | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(("•", "·", "▪", "◦")):
            line = line.lstrip("•·▪◦ \t").strip()

        m_pan = _PANEL_HEADER_RE.match(line)
        if m_pan:
            current = None
            if m_pan.group("num"):
                active_panel = int(m_pan.group("num"))
            elif m_pan.group("rom"):
                active_panel = _ROMAN_TO_INT.get(m_pan.group("rom").lower())
            elif m_pan.group("word"):
                active_panel = _WORD_TO_INT.get(m_pan.group("word").lower())
            continue

        if not line or _WIT_BLOCK_STOP_RE.match(line):
            current = None
            continue

        title_m = _WIT_TITLE_RE.match(line + " ")
        suffix = line.rsplit(",", 1)[-1].strip()
        credential = (
            "," in line
            and _DEGREE_RE.fullmatch(suffix) is not None
            and ("." in suffix or suffix.lower() in ("phd", "edd", "psyd", "pharmd", "scd"))
        )
        parsed = witness_line_parse(line) if (title_m or credential) else None
        nm = parsed["name"].rstrip("*†‡ ") if parsed else ""

        if (
            parsed
            and _is_person_name(nm)
            and not _CONVERSATION_NAME_GUARD_RE.search(nm)
            and (len(line.split()) <= 8 or "," in line)
            and not line.endswith(":")
        ):
            inline_details: list[str] = []
            if parsed["position"]:
                inline_details.append(parsed["position"])
            if parsed["organization"]:
                inline_details.append(parsed["organization"])
            current = {
                "name": nm,
                "details": inline_details,
                "credentials": parsed["credentials"],
                "honorific": parsed["honorific"],
                "rank": parsed["rank"],
                "panel": active_panel,
            }
            out.append(current)
            # Single-line comma-separated entry (`The Honorable X, Commissioner, CFTC`) needs no multi-line tail if >=2 details
            if len(inline_details) >= 2:
                current = None
        elif current is not None and len(current["details"]) < 4:
            current["details"].append(line)

    results: list[DocumentWitness] = []
    for w in out:
        details = w["details"]
        pos = details[0] if details else ""
        org = ", ".join(details[1:])
        results.append(
            DocumentWitness(
                name=w["name"],
                position=pos,
                organization=org,
                credentials=w["credentials"],
                honorific=w["honorific"],
                rank=w["rank"],
                panel=w["panel"],
            )
        )
    return results


_MEMBER_CHAMBER_ORG_RE = re.compile(
    r"^(?:U\.?S\.?\s+|United\s+States\s+)?(?:House\s+of\s+Representatives|Senate)\b"
    r"|^\d+(?:st|nd|rd|th)\s+Congressional\s+District\b",
    re.I,
)
_GOV_ORG_CUE_RE = re.compile(
    r"\b(?:(?:U\.?S\.?\s+|United\s+States\s+)?Department\s+of\s+(?:the\s+)?"
    r"(?:Interior|Agriculture|Commerce|Defense|Education|Energy|Health\s+and\s+Human\s+Services|"
    r"Homeland\s+Security|Housing\s+and\s+Urban\s+Development|Justice|Labor|State|Transportation|"
    r"Treasury|Veterans\s+Affairs|Army|Navy|Air\s+Force)|"
    r"U\.?S\.?\s+Department\b|United\s+States\s+Department\b|"
    r"Office\s+of\s+(?:the\s+)?(?:Inspector\s+General|Secretary|Management\s+and\s+Budget|White\s+House|Comptroller|Director|National\s+Drug|Special\s+Counsel|Personnel\s+Management|U\.?S\.?\s+Trade)|"
    r"Government\s+Accountability\s+Office|Congressional\s+Budget\s+Office|"
    r"Federal\s+[A-Z][A-Za-z]+\s+(?:Commission|Administration|Agency|Board|Bureau|Reserve|Deposit|Emergency|Aviation|Communications|Trade|Energy|Maritime|Highway|Railroad|Transit)|"
    r"Securities\s+and\s+Exchange\s+Commission|Commodity\s+Futures\s+Trading\s+Commission|"
    r"Environmental\s+Protection\s+Agency|Small\s+Business\s+Administration|Internal\s+Revenue\s+Service|"
    r"Social\s+Security\s+Administration|National\s+Aeronautics\s+and\s+Space\s+Administration|"
    r"Sheriff's\s+Office|Police\s+Department|Attorney\s+General|Mayor\s+of\b|Governor\s+of\b|"
    r"U\.?S\.?\s+(?:Army|Navy|Air\s+Force|Marine\s+Corps|Coast\s+Guard|Space\s+Force|Customs|Border\s+Patrol|Secret\s+Service|Marshals|Fish\s+and\s+Wildlife|Forest\s+Service|Geological\s+Survey|Postal\s+Service))\b",
    re.I,
)


def parse_witness_list_personas_v6(
    text: str,
    *,
    body_sha_hex: str | None = None,
) -> list[dict[str, Any]]:
    """Convert `\n`-preserved `witness_list` PDF text into `DocMetaV4Causal`-compatible `personas[]`."""
    if not text:
        return []
    sha = (body_sha_hex or "").strip().lower()
    if sha in REVIEWED_WITNESS_LISTS:
        raw_people = [
            DocumentWitness(
                name=p["name"],
                position=p.get("position", ""),
                organization=p.get("organization", ""),
                panel=p.get("panel"),
            )
            for p in REVIEWED_WITNESS_LISTS[sha]
        ]
    else:
        raw_people = parse_document_witnesses(text)

    personas: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for w in raw_people:
        nm_key = person_key(w.name)
        if nm_key in seen_names:
            continue
        seen_names.add(nm_key)

        pos = w.position.strip(" ,")
        org = w.organization.strip(" ,")
        hon_low = (w.honorific or "").lower().rstrip(".")

        # Check if testifying Member of Congress (`U.S. House of Representatives` / `Senator` / `Representative`)
        if (
            hon_low in ("senator", "sen", "representative", "rep", "congressman", "congresswoman")
            or _MEMBER_CHAMBER_ORG_RE.match(pos)
            or _MEMBER_CHAMBER_ORG_RE.match(org)
        ):
            p_obj: dict[str, Any] = {
                "name": w.name,
                "role": "witness",
                "entity_type": "member",
            }
            if w.panel is not None and not isinstance(w.panel, bool):
                p_str = str(w.panel).strip()
                if p_str:
                    p_obj["panel"] = f"Panel {p_str}" if p_str.isdigit() else p_str
            personas.append(p_obj)
            continue

        # Peel any leading degree/branch credentials out of position
        clean_pos, merged_creds = peel_leading_position_credentials(pos, w.credentials or None)
        pos = clean_pos or ""

        # If `Professor X` had `Department of ...` on first detail line, keep `Professor` as title
        if hon_low in ("professor", "prof") and pos and _is_organization_only(pos):
            org = f"{pos}, {org}".strip(", ") if org else pos
            pos = "Professor"

        # If organization has `Sub-Agency, U.S. Department of ...`, keep top-level Department in `org` and sub-agency in `sub_org`
        sub_org: str | None = None
        if ", " in org:
            org_parts = [x.strip() for x in org.split(", ") if x.strip()]
            if len(org_parts) >= 2 and re.match(r"^(?:U\.?S\.?\s+|United\s+States\s+)?Department\s+of\b", org_parts[-1], re.I):
                sub_org = ", ".join(org_parts[:-1])
                org = org_parts[-1]

        etype = "gov_official" if (w.rank or _GOV_ORG_CUE_RE.search(f"{pos} {org}")) else "non_gov_person"
        p_obj = {"name": w.name}
        if merged_creds:
            p_obj["creds"] = merged_creds
        if pos:
            p_obj["title"] = pos
        if org:
            p_obj["org"] = org
        if sub_org:
            p_obj["sub_org"] = sub_org
        if w.panel is not None and not isinstance(w.panel, bool):
            p_str = str(w.panel).strip()
            if p_str:
                p_obj["panel"] = f"Panel {p_str}" if p_str.isdigit() else p_str
        p_obj["role"] = "witness"
        p_obj["entity_type"] = etype
        personas.append(p_obj)

    return personas[:MAX_PERSONAS]


# ===========================================================================
# N11 (Part B): GPO Headings, Cover Roster & `p3..p8` TOC Parser (`gpo_headings.py` + `gpo_text.py`)
# ===========================================================================

_GPO_ROSTER_LINE_RE = re.compile(
    r"^([A-Z][A-Za-z .'`\"’\-]+?(?:, (?:Jr|Sr|II|III|IV)\.?)?), "
    r"([A-Z][a-z]+(?: (?:of )?[A-Z][a-z]+)*)"
    r"(?:, ?([A-Za-z ]*(?:Chair|Ranking)[A-Za-z ]*))?,?\s*$"
)
_GPO_TWO_COL_SPLIT_RE = re.compile(
    r"\s{3,}|(?<=[a-z])\s{1,2}(?=[A-Z]{2,}(?:\s+[A-Z.'`\"’\-]+){0,5}(?:,\s+(?:Jr|Sr|II|III|IV)\.?)?,\s+[A-Z][a-z]+)"
)
_GPO_ROLE_WORDS = {
    "chair": "chair",
    "chairman": "chair",
    "chairwoman": "chair",
    "chairperson": "chair",
    "cochair": "chair",
    "cochairman": "chair",
    "ranking": "ranking_member",
}
_GPO_KIND_RE = re.compile(
    r"^\s*(?P<kind>(?:(?:OPENING|PREPARED|JOINT|ORAL|SUPPLEMENTAL)\s+)?(?:STATEMENTS?|TESTIMONY|REMARKS))"
    r"\s+(?:OF|BY)(?:\s+(?P<rest>\S.*))?\s*$"
)
_GPO_LOWER_RUN_RE = re.compile(r"[a-z]{3,}")
_GPO_CONTENTS_RE = re.compile(r"^\s*(?:C\s*O\s*N\s*T\s*E\s*N\s*T\s*S|CONTENTS)\s*$")
_GPO_CONVENING_RE = re.compile(
    r"^\s*(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY),\s+[A-Z]+\.?\s+\d{1,2},?\s+\d{4}\s*$",
    re.I,
)
_GPO_RESUMED_RE = re.compile(
    r"^\s*(?:MORNING|AFTERNOON|EVENING)\s+SESSION\s*$"
    r"|^\s+The\s+(?:Committee|Subcommittee|Commission|Caucus|Panel)\b[^.\[]{0,80}\breconvened\b",
    re.I,
)
_GPO_ADJOURNED_RE = re.compile(r"\[Whereupon\b[^\]]*?\b(?:adjourn|recess|conclu)", re.I)
_GPO_STAFF_RE = re.compile(r"Staff Director|Chief Counsel|Chief of Staff|Staff Member|Counsel\b|Clerk\b", re.I)
_GPO_GROUP_RE = re.compile(r"^(?:THE\s+)?(?:COMMITTEE\s+MEMBERS|MEMBERS|WITNESSES|SENATORS|REPRESENTATIVES|PANEL)\b")
_GPO_ACCOMPANIED_RE = re.compile(r"[;,]?\s*\bACCOMPANIED\s+BY:?\s*")
_GPO_ALSO_PRESENT_RE = re.compile(
    r"\bAlso\s+[Pp]resent:\s*(?P<names>.{0,600}?)(?<![\s.][A-Z])\.(?=[ \t]*(?:\n|$)|\s+[A-Z][a-z]+\s+[Pp]resent:)",
    re.S,
)
_GPO_PRESENT_TITLES_RE = re.compile(
    r"\b(?:Senators?|Representatives?|Delegates?|Resident Commissioner|Congress(?:man|woman)|Hon\.|"
    r"Honorable|Chairman|Chairwoman)\s+|\([^)]*\)|\[[^\]]*\]"
)
_GPO_TITLE_START = (
    r"(?:THE\s+)?(?:HON\.?|HONORABLE|MR\.|MS\.|MRS\.|DR\.|SENATOR|REPRESENTATIVE|CONGRESSMAN|CONGRESSWOMAN|"
    r"GOVERNOR|MAYOR|GENERAL|GEN\.?|ADMIRAL|ADM\.?|SECRETARY|AMBASSADOR|JUDGE)\b"
)
_GPO_TITLES = frozenset(
    "the hon honorable mr mrs ms miss mx dr senator sen representative rep congressman congresswoman delegate governor "
    "mayor gen general lt lieutenant col colonel maj major capt captain adm admiral vadm radm rear vice brigadier sgt "
    "sergeant rev reverend father sister rabbi judge secretary ambassador chief sheriff professor prof commissioner "
    "chairman chairwoman".split()
)
_GPO_SUFFIXES = frozenset("jr sr ii iii iv md phd esq ret".split())


def gpo_name_key(name: str) -> tuple[str, str]:
    """Stdlib port of `congress_api.parsers.gpo_headings.name_key`."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"``[^']*''|\"[^\"]*\"|\([^)]*\)", " ", text).replace("'", "")
    words = [w for w in re.findall(r"[a-z]+", text) if w not in _GPO_SUFFIXES]
    while len(words) > 1 and words[0] in _GPO_TITLES:
        words = words[1:]
    if not words:
        return "", ""
    return words[-1], words[0][0] if len(words) > 1 else ""


def _format_gpo_allcaps_name(raw: str) -> str:
    cleaned = raw.replace("``", '"').replace("''", '"').strip()
    out_words: list[str] = []
    for w in cleaned.split():
        if w.isupper() and len(w) > 2 and w not in ("II", "III", "IV"):
            if w.startswith("MC") and len(w) > 3:
                out_words.append("Mc" + w[2:].capitalize())
            else:
                out_words.append(w.capitalize())
        else:
            out_words.append(w)
    return " ".join(out_words)


def gpo_roster(lines: Sequence[str]) -> tuple[list[dict[str, str]], set[str]]:
    """Stdlib port of `congress_api.parsers.gpo_text.roster` (zero Pydantic dependency)."""
    people: list[dict[str, str]] = []
    seen: dict[str, dict[str, str]] = {}
    sub: set[str] = set()
    in_sub = False
    for idx, line in enumerate(lines):
        if re.search(r"^\s*(?:C\s*O\s*N\s*T\s*E\s*N\s*T\s*S|CONTENTS)\b", line):
            break
        if _GPO_STAFF_RE.search(line):
            continue
        if people and re.match(r"^\s*SUBCOMMITTEE\b", line):
            in_sub = True
        for col in _GPO_TWO_COL_SPLIT_RE.split(line.strip()):
            col_s = col.strip()
            m = _GPO_ROSTER_LINE_RE.match(col_s)
            if not m:
                continue
            name = _format_gpo_allcaps_name(m.group(1))
            role_str = (m.group(3) or "").strip()
            if not role_str and idx + 1 < len(lines):
                nxt = lines[idx + 1].strip()
                if re.fullmatch(
                    r"(?:Acting\s+|Vice\s+)?(?:Chair(?:man|woman|person)?|Ranking\s+(?:Minority\s+|Republican\s+|Democratic\s+)?Member)",
                    nxt,
                    re.I,
                ):
                    role_str = nxt
            role_clean = re.sub(r"\s", "", role_str.lower())
            if "vicechair" in role_clean:
                role = "member"
            else:
                role = next((r for w, r in _GPO_ROLE_WORDS.items() if w in role_clean), "member")
            k = person_key(name)
            if k in seen:
                if in_sub:
                    sub.add(k)
                    if role != "member" and seen[k]["role"] == "member":
                        sub_copy = {"name": name, "role": role, "state": m.group(2), "subcommittee": "true"}
                        people.append(sub_copy)
                continue
            p = {"name": name, "role": role, "state": m.group(2)}
            people.append(p)
            seen[k] = p
            if in_sub:
                sub.add(k)
    return people, sub


def _gpo_capitals(line: str) -> bool:
    return bool(re.search(r"[A-Z]", line)) and not _GPO_LOWER_RUN_RE.search(line)


def _gpo_pieces(text: str, *, bare_and: bool) -> list[str]:
    pieces: list[str] = []
    for piece in re.split(r";\s*", text):
        piece = re.sub(r"^AND\s+", "", piece.strip(" ,."))
        for part in re.split(rf",?\s+AND\s+(?={_GPO_TITLE_START})", piece):
            pieces += re.split(r"\s+AND\s+", part) if bare_and and "," not in part else [part]
    return [p.strip(" ,.") for p in pieces if p.strip(" ,.")]


def _gpo_people(rest: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    parts = _GPO_ACCOMPANIED_RE.split(rest, maxsplit=1)
    main = parts[0]
    accompanied = parts[1:]
    named: list[tuple[str, str]] = []
    for piece in _gpo_pieces(main, bare_and=False):
        if named and re.match(r"(?:ON BEHALF|REPRESENTING|FORMERLY)\b", piece):
            named[-1] = (named[-1][0], f"{named[-1][1]}; {piece}".strip("; "))
            continue
        name, _, style = piece.partition(",")
        named.append((name.strip(), style.strip()))
    with_table = [
        (name.strip(), style.strip())
        for name, _, style in (
            piece.partition(",") for piece in (_gpo_pieces(accompanied[0], bare_and=True) if accompanied else ())
        )
    ]
    return named, with_table


def _gpo_present(lines: list[str], i: int) -> list[tuple[str, int]]:
    found = _GPO_ALSO_PRESENT_RE.search("\n".join(lines[i : i + 8]))
    if not found:
        return []
    names = _GPO_PRESENT_TITLES_RE.sub(" ", re.sub(r"\s+", " ", found.group("names")))
    return [
        (name, i + 1)
        for name in (n.strip(" ,.") for n in re.split(r",\s*(?:and\s+)?|\s+and\s+|;\s*", names))
        if name and len(name.split()) <= 4
    ]


def _gpo_roster_columns(front: list[str]) -> list[str]:
    columns: list[str] = []
    for line in front:
        if _GPO_STAFF_RE.search(line):
            continue
        for column in re.split(r"\s{3,}|(?<=[a-z.])\s{2,}(?=[A-Z])", line.strip()):
            name, _, rest = column.partition(",")
            if (
                rest
                and re.match(r"(?:\s(?:Jr|Sr|II|III|IV)\.?,)?\s[A-Z][a-z]", rest)
                and re.search(r"[A-Z]{2}", name)
                and not _GPO_LOWER_RUN_RE.search(name)
            ):
                columns.append(column)
    return columns


def _gpo_entry(kind: str, name: str, style: str | None, line: int | None) -> dict[str, Any]:
    family, given = gpo_name_key(name)
    return {"kind": kind, "name": name, "family": family, "given": given, "style": style or None, "line": line}


def transcript_entries(text: str) -> list[dict[str, Any]]:
    """Stdlib port of `congress_api.parsers.gpo_headings.transcript_entries`."""
    lines = text.replace("\r", "").split("\n")
    contents = next((i for i, line in enumerate(lines) if _GPO_CONTENTS_RE.match(line)), None)
    start = contents + 1 if contents is not None else 0
    first = next((i for i in range(start, len(lines)) if _GPO_CONVENING_RE.match(lines[i])), None)
    front = lines[: contents if contents is not None else (first if first is not None else len(lines))]
    roster_list, _ = gpo_roster(_gpo_roster_columns(front))
    entries = [
        _gpo_entry(
            "roster",
            person["name"],
            ", ".join(filter(None, (person["state"], None if person["role"] == "member" else person["role"]))),
            None,
        )
        for person in roster_list
    ]
    on = first is None and contents is not None
    i = start if (contents is not None or first is not None) else len(lines)
    while i < len(lines):
        line = lines[i]
        if _GPO_CONVENING_RE.match(line) or _GPO_RESUMED_RE.search(line):
            on = True
        if _GPO_ADJOURNED_RE.search(line):
            on = False
        if on and "resent:" in line and re.search(r"\bAlso\s+[Pp]resent:", line):
            entries += [_gpo_entry("present", name, None, n) for name, n in _gpo_present(lines, i)]
        found = _GPO_KIND_RE.match(line) if on and _gpo_capitals(line) else None
        if not found:
            i += 1
            continue
        rest, j = found.group("rest") or "", i + 1
        while j < len(lines) and j - i < 6 and lines[j].strip() and _gpo_capitals(lines[j]) and not _GPO_KIND_RE.match(lines[j]):
            rest += " " + lines[j].strip()
            j += 1
        rest = re.sub(r"\s+", " ", rest).strip()
        word = found.group("kind")
        kind = (
            "opening"
            if word.startswith("OPENING")
            else "prepared"
            if word.startswith(("PREPARED", "SUPPLEMENTAL"))
            else "statement"
        )
        if not _GPO_GROUP_RE.match(rest):
            named, with_table = _gpo_people(rest)
            entries += [_gpo_entry(kind, name, style, i + 1) for name, style in named]
            entries += [_gpo_entry("accompanying", name, style, i + 1) for name, style in with_table]
        i = j
    return entries


def parse_gpo_p12_personas_v6(p12_lines: str) -> list[dict[str, Any]]:
    """Extract `p1-2` GPO leadership (`chair`, `ranking_member`) + `p1-2` speakers (`0` backbench FPs on `Gold360`)."""
    if not p12_lines or "\n" not in p12_lines:
        return []
    lines = p12_lines.replace("\r", "").split("\n")
    roster_people, _ = gpo_roster(lines)
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for p in roster_people:
        if p["role"] in ("chair", "ranking_member"):
            key = (person_key(p["name"]), p["role"])
            if key not in seen:
                seen.add(key)
                out.append(
                    {
                        "name": p["name"],
                        "role": p["role"],
                        "entity_type": "member",
                    }
                )

    for ent in transcript_entries(p12_lines):
        if ent["kind"] in ("opening", "statement", "accompanying"):
            parsed = witness_line_parse(f"{ent['name']}, {ent['style'] or ''}".strip(", "))
            nm = _format_gpo_allcaps_name(parsed["name"] or ent["name"])
            if not _is_person_name(nm):
                continue
            style_up = (ent["style"] or "").upper()
            is_mem = bool(
                re.search(r"\b(?:SENATOR|REPRESENTATIVE|DELEGATE|CONGRESS(?:MAN|WOMAN)|IN CONGRESS FROM)\b", style_up)
            )
            is_nom = bool(re.search(r"\bNOMINEE\s+TO\s+BE\b|\bTO\s+BE\s+(?:AMBASSADOR|ASSISTANT\s+SECRETARY|UNDER\s+SECRETARY|MEMBER)\b", style_up))
            role = "author_or_speaker" if is_mem else ("nominee" if is_nom else "witness")
            etype = "member" if is_mem else ("gov_official" if _GOV_ORG_CUE_RE.search(ent["style"] or "") else "non_gov_person")
            key = (person_key(nm), role)
            if key not in seen and not any(person_key(nm) == k[0] for k in seen):
                seen.add(key)
                p_obj: dict[str, Any] = {"name": nm, "role": role, "entity_type": etype}
                if parsed["position"] and not is_mem:
                    p_obj["title"] = _format_gpo_allcaps_name(parsed["position"]) if parsed["position"].isupper() else parsed["position"]
                if parsed["organization"] and not is_mem:
                    p_obj["org"] = _format_gpo_allcaps_name(parsed["organization"]) if parsed["organization"].isupper() else parsed["organization"]
                out.append(p_obj)
    return out[:MAX_PERSONAS]


_TOC_STOP_SECTION_RE = re.compile(
    r"^\s*(?:SUBMISSIONS?\s+FOR\s+THE\s+RECORD|ADDITIONAL\s+MATERIAL|APPENDIX(?:ES)?:?|"
    r"LETTERS?,?\s+STATEMENTS?,?\s+ETC\.|MATERIAL\s+SUBMITTED|QUESTIONS\s+(?:AND\s+ANSWERS|SUBMITTED))\b",
    re.I,
)
_TOC_WITNESS_HEADER_RE = re.compile(
    r"^\s*(?:WITNESS(?:ES)?|CHRONOLOGICAL\s+LIST\s+OF\s+WITNESSES|LIST\s+OF\s+WITNESSES|"
    r"PANEL\s+OF\s+WITNESSES|PANEL\s+(?:I|II|III|IV|1|2|3|4|ONE|TWO|THREE|\w+)):?\s*$",
    re.I,
)
_TOC_SECTION_HEADER_RE = re.compile(
    r"^\s*(?:C\s*O\s*N\s*T\s*E\s*N\s*T\s*S|CO|NT|EN|TS|Pages?|Page|"
    r"(?:OPENING\s+|PREPARED\s+)?STATEMENTS?\s+OF:?|WITNESS(?:ES)?:?|"
    r"CHRONOLOGICAL\s+LIST\s+OF\s+WITNESSES|LIST\s+OF\s+WITNESSES|"
    r"PANEL\s+OF\s+WITNESSES|PANEL\s+(?:I|II|III|IV|1|2|3|4|ONE|TWO|THREE)|"
    r"(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY),\s+[A-Z]+\s+\d{1,2},\s+\d{4})\s*$",
    re.I,
)
_TOC_FRESH_ENTRY_START_RE = re.compile(
    r"^(?:[A-Z][a-zA-Z'\u00C0-\u024F-]+,\s+(?:[A-Z]\.?\s+){0,2}[A-Z][a-zA-Z'\u00C0-\u024F.-]+,|"
    r"(?:The\s+Honorable|Hon\.|Mr\.|Mrs\.|Ms\.|Dr\.|Senator|Representative)\s+[A-Z])"
)
_TOC_CONTINUATION_TAIL_RE = re.compile(r"(?:,|-|\b(?:and|of|for|the|or|in|at|on|by|to|U\.S\.|Inc\.|Co\.))\s*$", re.I)


def parse_gpo_p3_slice_personas_v6(p3_slice: str) -> list[dict[str, Any]]:
    """Extract deterministic speaker/member/witness `personas[]` from rescued `\n`-preserved `p3..p8` GPO slices.

    Handles both GPO dotted-leader `CONTENTS` / `WITNESSES` TOC pages (`4,450+` rescued GPO slices)
    and post-convening ALL-CAPS proceedings headings (`transcript_entries`), stopping cleanly before
    `SUBMISSIONS FOR THE RECORD` / `APPENDIX` / `QUESTIONS SUBMITTED`.
    """
    if not p3_slice:
        return []

    out: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    # 1. Reconstruct wrapped dotted-leader TOC entries (joining hyphen-wraps + multi-line entries ending in `.... <page>`)
    raw_lines = [ln.strip() for ln in p3_slice.replace("\r", "").split("\n")]
    stitched: list[tuple[str, bool]] = []
    buf = ""
    in_opening_section = False
    in_witness_section = False
    has_later_witness_hdr = [False] * (len(raw_lines) + 1)
    for idx_rev in range(len(raw_lines) - 1, -1, -1):
        has_later_witness_hdr[idx_rev] = has_later_witness_hdr[idx_rev + 1] or bool(
            _TOC_WITNESS_HEADER_RE.match(raw_lines[idx_rev])
        )

    for idx_ln, ln in enumerate(raw_lines):
        if not ln or ln == ")" or re.fullmatch(r"\([IVXLCDM]+\)|\d{1,4}", ln):
            continue
        if _TOC_STOP_SECTION_RE.match(ln):
            if not stitched and not in_opening_section and has_later_witness_hdr[idx_ln + 1]:
                buf = ""
                continue
            if buf and in_witness_section and "," in buf:
                stitched.append((buf, False))
                buf = ""
            break
        if re.match(r"^\s*OPENING\s+STATEMENTS?\s+OF:?\s*$", ln, re.I):
            if buf and in_witness_section and "," in buf:
                stitched.append((buf, False))
            in_opening_section = True
            in_witness_section = False
            buf = ""
            continue
        if _TOC_WITNESS_HEADER_RE.match(ln):
            if buf and in_witness_section and "," in buf:
                stitched.append((buf, False))
            in_opening_section = False
            in_witness_section = True
            buf = ""
            continue
        if _TOC_SECTION_HEADER_RE.match(ln):
            if buf and in_witness_section and "," in buf:
                stitched.append((buf, False))
            buf = ""
            continue

        if buf and in_witness_section and "," in buf and not _TOC_CONTINUATION_TAIL_RE.search(buf):
            is_fresh = bool(_TOC_FRESH_ENTRY_START_RE.match(ln))
            if not is_fresh and "," in ln:
                cand_w = witness_line_parse(ln)
                cand_nm = (cand_w.get("name") or "").strip()
                if (
                    cand_nm
                    and _is_person_name(cand_nm)
                    and not _ENTRY_WORDS_RE.match(cand_nm)
                    and not _TAIL_TITLE_OR_ORG_REJECT_RE.search(cand_nm)
                ):
                    is_fresh = True
            if is_fresh:
                stitched.append((buf, in_opening_section))
                buf = ""

        if buf:
            if buf.endswith("-"):
                buf = buf[:-1] + ln
            else:
                buf = f"{buf} {ln}"
        else:
            buf = ln

        if re.search(r"\.{4,}\s*(?:\d+|[IVXLCDM]+)?\s*$", buf):
            stitched.append((buf, in_opening_section))
            buf = ""
        elif len(buf) > 260:
            buf = ""

    if buf and in_witness_section and "," in buf:
        stitched.append((buf, in_opening_section))

    for entry_tuple in stitched:
        entry_line, is_open_sec = entry_tuple  # type: ignore[misc]
        cleaned = _strip_contents_markers(entry_line)
        if not cleaned or _ENTRY_WORDS_RE.match(cleaned):
            continue
        parsed = witness_line_parse(cleaned)
        nm = parsed["name"].rstrip("*†‡ ").strip()
        if not _is_person_name(nm):
            continue
        pk = person_key(nm)
        if pk in seen_keys:
            continue

        full_low = cleaned.lower()
        is_member = bool(
            re.search(
                r"\b(?:a\s+(?:u\.?s\.?|united\s+states)\s+(?:senator|representative)|"
                r"(?:representative|senator|delegate|resident\s+commissioner)\s+in\s+congress|"
                r"chairman|chairwoman|ranking\s+member)\b",
                full_low,
            )
            or parsed["honorific"].lower().rstrip(".") in ("senator", "sen", "representative", "rep")
        )
        is_nominee = bool(re.search(r"\bnominee\s+to\s+be\b|\bto\s+be\s+(?:a\s+member|ambassador|assistant\s+secretary|under\s+secretary)", full_low))

        if is_member:
            if re.search(r"\bchair(?:man|woman|person)?\b", full_low) and "vice" not in full_low:
                role = "chair"
            elif re.search(r"\branking\s+(?:minority\s+)?member\b", full_low):
                role = "ranking_member"
            else:
                role = "author_or_speaker" if is_open_sec else "questioner"
            seen_keys.add(pk)
            out.append({"name": nm, "role": role, "entity_type": "member"})
        else:
            role = "nominee" if is_nominee else "witness"
            pos = parsed["position"].strip(" ,")
            org = parsed["organization"].strip(" ,")
            pos_clean, creds = peel_leading_position_credentials(pos, parsed["credentials"] or None)
            etype = "gov_official" if (is_nominee or parsed["rank"] or _GOV_ORG_CUE_RE.search(f"{pos} {org}")) else "non_gov_person"
            p_obj: dict[str, Any] = {"name": nm}
            if creds:
                p_obj["creds"] = creds
            if pos_clean:
                p_obj["title"] = pos_clean
            if org:
                p_obj["org"] = org
            p_obj["role"] = role
            p_obj["entity_type"] = etype
            seen_keys.add(pk)
            out.append(p_obj)

    # 2. Also run `transcript_entries` in case `p3_slice` is a post-convening gavel/proceedings page
    for ent in transcript_entries(p3_slice):
        if ent["kind"] in ("opening", "statement", "accompanying"):
            parsed = witness_line_parse(f"{ent['name']}, {ent['style'] or ''}".strip(", "))
            nm = _format_gpo_allcaps_name(parsed["name"] or ent["name"])
            if not _is_person_name(nm):
                continue
            pk = person_key(nm)
            if pk in seen_keys:
                continue
            style_up = (ent["style"] or "").upper()
            is_mem = bool(re.search(r"\b(?:SENATOR|REPRESENTATIVE|DELEGATE|IN CONGRESS FROM|CHAIRMAN|CHAIRWOMAN|RANKING MEMBER)\b", style_up))
            is_nom = bool(re.search(r"\bNOMINEE\s+TO\s+BE\b", style_up))
            role = "author_or_speaker" if is_mem else ("nominee" if is_nom else "witness")
            etype = "member" if is_mem else ("gov_official" if _GOV_ORG_CUE_RE.search(ent["style"] or "") else "non_gov_person")
            seen_keys.add(pk)
            p_obj = {"name": nm, "role": role, "entity_type": etype}
            if parsed["position"] and not is_mem:
                p_obj["title"] = _format_gpo_allcaps_name(parsed["position"]) if parsed["position"].isupper() else parsed["position"]
            if parsed["organization"] and not is_mem:
                p_obj["org"] = _format_gpo_allcaps_name(parsed["organization"]) if parsed["organization"].isupper() else parsed["organization"]
            out.append(p_obj)

    return out[:MAX_PERSONAS]


_TAIL_MEMO_WITNESS_HDR_RE = re.compile(
    r"(?:^|\n)\s*(?:[IVXLC]+\.\s*\n\s*)?WITNESS(?:ES)?\s*:?\s*\n"
    r"(?:\s*The\s+following\s+witnesses\s+have\s+been\s+invited\s+to\s+testify:?\s*\n)?",
    re.I,
)
_TAIL_TITLE_OR_ORG_REJECT_RE = re.compile(
    r"\b(?:Chief|Officer|Principal|Vice\s+President|President|Director|Professor|Manager|Counsel|"
    r"Attorney|Commissioner|Executive|Fellow|Partner|Founder|Chair(?:man|woman)?|Secretary|"
    r"Administrator|Coordinator|Specialist|Correspondent|Reporter|Journalist|Economist|Analyst|"
    r"Member|Trustee|Advis[eo]r|Consultant|Delegate|Designee|Witness|Speaker|Moderator|Panelist|"
    r"University|College|Corporation|Consulting|Association|Institute|Company|Enterprise|"
    r"Agency|System|Bureau|Administration|Board|Program|Division|Authority|Commission|"
    r"Conservancy|Foundation|Initiative|Coalition|Hospital|School|Refuge|Wildlife|"
    r"Environmental|Protection|Channel|Broadcasting|United\s+States|U\.S\.|"
    r"Public\s+(?:Justice|Citizen|Interest|Policy|Health|Affairs|Defender|Utilities)|"
    r"Inc\.|LLC|LLP|Network|Group|Club|Council|Alliance|Center|Fund|Federation|Committee|Department|Office)\b",
    re.I,
)
_TAIL_HONORIFIC_LINE_START_RE = re.compile(
    r"^(?:The\s+Honorable|Hon\.|Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.|Senator|Sen\.|"
    r"Representative|Rep\.|Ambassador|General|Gen\.|Admiral|Adm\.|Brig\.|Col\.|Maj\.|Capt\.|Cmdr\.|Lt\.)\b",
    re.I,
)
_TAIL_CLOSING_SAL_RE = re.compile(
    r"(?:^|\n)\s*(?:Most\s+)?(?:Respectfully(?:\s+submitted)?|Sincerely|Very\s+truly\s+yours),?\s*\n",
    re.I,
)
_TAIL_ORG_LINE_CUE_RE = re.compile(
    r"\b(?:Network|Place|Club|Council|Federation|Collaborative|Alliance|Group|Waste|Coal|"
    r"Environment|Issues|Mining|Association|Center|Institute|Committee|Foundation|"
    r"League|Union|Project|Society|Coalition|Chapter|Trust|Partners|Inc\.|LLC)\b",
    re.I,
)
_TAIL_PERSON_TITLE_FOLLOW_RE = re.compile(
    r"\b(?:VP|Vice\s+President|President|Director|Chief|CEO|CFO|Chair|Counsel|Professor|Executive|Secretary|Manager|Partner|Founder|Fellow)\b",
    re.I,
)


def _is_clean_person_token_shape_v6(nm: str) -> bool:
    """Reject Caesar-shifted font garble (`WKe`, `VLdeOLQeV.`) and sentence-final periods on harvested names."""
    if not nm or re.search(r"\b[A-Z]{2,}[a-z]", nm):
        return False
    toks = nm.split()
    if not toks:
        return False
    last_tok = toks[-1]
    if (
        last_tok.endswith(".")
        and len(last_tok) > 3
        and last_tok.lower() not in ("jr.", "sr.", "esq.", "inc.", "corp.", "ltd.", "ph.d.", "m.d.")
    ):
        return False
    return True


def _extract_gpo_toc_slice_from_text(text: str) -> str:
    """Locate an in-body GPO `CONTENTS` / `WITNESSES` TOC region when `\f` page breaks are absent."""
    head = text[:7500]
    m_start = re.search(
        r"(?:^|\n)\s*(?:C\s*O\s*N\s*T\s*E\s*N\s*T\s*S|WITNESS(?:ES)?|PANEL\s+OF\s+WITNESSES)\b",
        head,
        re.I,
    )
    if not m_start:
        return ""
    sub = head[m_start.start() : m_start.start() + 4500]
    m_end = re.search(
        r"(?:^|\n)\s*(?:The\s+(?:committee|subcommittee)\s+met,\s*pursuant\s+to\s+call|SUBMISSIONS?\s+FOR\s+THE\s+RECORD|QUESTIONS\s+(?:AND\s+ANSWERS|SUBMITTED))\b",
        sub,
        re.I,
    )
    if m_end:
        sub = sub[: m_end.start()]
    return sub if ("." in sub or "WITNESS" in sub.upper()) else ""


def _extract_memo_witness_block_personas(text: str) -> list[dict[str, Any]]:
    """Parse `WITNESSES` sections (including `>6k` tails) in hearing memos, notices, and witness lists."""
    out: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for m_hdr in _TAIL_MEMO_WITNESS_HDR_RE.finditer(text):
        tail_block = text[m_hdr.end() : m_hdr.end() + 2600]
        cur_p: dict[str, Any] | None = None
        details: list[str] = []

        def _flush() -> None:
            nonlocal cur_p, details
            if cur_p is None:
                return
            pos = details[0] if len(details) >= 1 else ""
            org = ", ".join(details[1:2]) if len(details) >= 2 else ""
            pos_clean, creds = peel_leading_position_credentials(pos, cur_p.pop("_creds", None))
            if creds:
                cur_p["creds"] = creds
            if pos_clean:
                cur_p["title"] = pos_clean
            if org:
                cur_p["org"] = org
            if _GOV_ORG_CUE_RE.search(f"{pos_clean} {org}"):
                cur_p["entity_type"] = "gov_official"
            out.append(cur_p)
            cur_p = None
            details = []

        for raw_ln in tail_block.splitlines():
            ln = raw_ln.strip()
            if not ln:
                continue
            if re.match(r"^Panel\s+(?:[IVXLC]+|\d+|One|Two|Three)\s*:?$", ln, re.I):
                _flush()
                continue
            if re.match(
                r"^(?:[IVXLC]+\.|APPENDIX|ATTACHMENTS?|NOTES?:|BACKGROUND:|THEMES\s+FOR\b|\d{1,2}\s+See\b|Endnotes?|###|Unsubscribe\b)",
                ln,
                re.I,
            ):
                break
            parsed = witness_line_parse(ln)
            nm = parsed["name"].rstrip("*†‡ ").strip()
            looks_person = (
                bool(nm)
                and _is_person_name(nm)
                and _is_clean_person_token_shape_v6(nm)
                and not _CONVERSATION_NAME_GUARD_RE.search(ln)
                and not _TAIL_TITLE_OR_ORG_REJECT_RE.search(nm)
                and len(nm.split()) <= 4
                and not parsed["position"]
            )
            has_explicit_cue = bool(
                parsed["honorific"] or parsed["credentials"] or _TAIL_HONORIFIC_LINE_START_RE.match(ln)
            )
            if looks_person and (cur_p is None or len(details) >= 2 or has_explicit_cue):
                _flush()
                pk = person_key(nm)
                if pk in seen_keys:
                    continue
                seen_keys.add(pk)
                cur_p = {
                    "name": nm,
                    "role": "witness",
                    "entity_type": "non_gov_person",
                    "_creds": parsed["credentials"] or None,
                }
            elif cur_p is not None and len(details) < 2 and len(ln) <= 140:
                details.append(ln)
        _flush()
        if out:
            break
    return out[:MAX_PERSONAS]


def _extract_tail_letter_close_personas(
    text: str,
    *,
    primary_kind: str | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """Harvest signatory/sender and undersigned counts from `>5.5k` closing signature blocks."""
    if len(text) <= 5500:
        return [], None
    base_off = max(0, len(text) - 2500)
    tail = text[base_off:]
    matches = list(_TAIL_CLOSING_SAL_RE.finditer(tail))
    if not matches:
        return [], None
    sal_m = matches[-1]
    if base_off + sal_m.start() < 5200:
        return [], None

    raw_sig_lines = [ln.strip() for ln in tail[sal_m.end() :].splitlines()]
    clean_lines: list[str] = []
    for ln in raw_sig_lines:
        if not ln:
            continue
        if re.match(r"^(?:Printed\s+on\s+Recycle|cc:|Page\s+\d+|_+$|[-=]{3,}$|\[\d+\])", ln, re.I):
            continue
        clean_lines.append(ln)
    if not clean_lines:
        return [], None

    # Multi-organization coalition close (e.g. `Respectfully,\nPrairie Rivers Network\n...`)
    org_hits = sum(1 for ln in clean_lines if _TAIL_ORG_LINE_CUE_RE.search(ln))
    if (
        len(clean_lines) >= 5
        and org_hits >= max(3, len(clean_lines) // 2)
        and primary_kind in ("external_submission_letter", "oversight_letter")
    ):
        first_org = clean_lines[0].strip()
        m_cnt = re.search(
            r"\bundersigned\s+(\d{1,4})\b|\bwe,\s+the\s+(\d{1,4})\s+undersigned\b|\b(\d{1,4})\s+(?:coalition|member|public\s+interest)\s+groups\b",
            text,
            re.I,
        )
        sig_cnt: int | None = None
        if m_cnt:
            grp = next((g for g in m_cnt.groups() if g), None)
            if grp and grp.isdigit() and int(grp) >= 2:
                sig_cnt = int(grp)
        if sig_cnt is None and len(clean_lines) >= 5:
            sig_cnt = len(clean_lines) - 1 if len(clean_lines) >= 10 else len(clean_lines)
        return [{"name": first_org[:120], "role": "sender", "entity_type": "organization"}], sig_cnt

    # Personal letter close in transcript/letter tail (`Sincerely,\n[signature OCR]\nJeanne de Cervens\nVP and Director...`)
    if primary_kind in ("hearing_transcript", "external_submission_letter"):
        for idx in range(min(4, len(clean_lines) - 1)):
            cand_nm = clean_lines[idx]
            nxt = clean_lines[idx + 1]
            if (
                _is_person_name(cand_nm)
                and not _CONVERSATION_NAME_GUARD_RE.search(cand_nm)
                and not _TAIL_TITLE_OR_ORG_REJECT_RE.search(cand_nm)
                and len(cand_nm.split()) <= 4
                and _TAIL_PERSON_TITLE_FOLLOW_RE.search(nxt)
            ):
                role = "author_or_speaker" if primary_kind == "hearing_transcript" else "sender"
                p_obj: dict[str, Any] = {
                    "name": cand_nm,
                    "title": nxt.rstrip("., ")[:140],
                    "role": role,
                    "entity_type": "gov_official" if _GOV_ORG_CUE_RE.search(nxt) else "non_gov_person",
                }
                if idx + 2 < len(clean_lines) and len(clean_lines[idx + 2]) <= 120:
                    org_ln = re.sub(r"^(?:Part\s+of\s+the|Member\s+of)\s+", "", clean_lines[idx + 2], flags=re.I).strip()
                    if org_ln:
                        p_obj["org"] = org_ln
                return [p_obj], None
    return [], None


def harvest_tail_and_toc_personas_v6(
    text: str,
    *,
    primary_kind: str | None = None,
    p3_slice: str | None = None,
) -> dict[str, Any]:
    """Extract deterministic witness/letter personas from GPO TOC slices and `>6k` document tails."""
    toc_personas: list[dict[str, Any]] = []
    tail_personas: list[dict[str, Any]] = []
    signatory_count: int | None = None

    eff_p3 = (p3_slice or "").strip()
    if not eff_p3 and primary_kind == "hearing_transcript" and text:
        eff_p3 = _extract_gpo_toc_slice_from_text(text)
    if eff_p3:
        toc_personas = parse_gpo_p3_slice_personas_v6(eff_p3)

    if text and primary_kind in ("hearing_memo_or_charter", "hearing_notice", "witness_list"):
        tail_personas.extend(_extract_memo_witness_block_personas(text))

    if text and primary_kind in ("hearing_transcript", "external_submission_letter", "oversight_letter"):
        close_p, sig_n = _extract_tail_letter_close_personas(text, primary_kind=primary_kind)
        if close_p:
            tail_personas.extend(close_p)
        if sig_n is not None:
            signatory_count = sig_n

    return {
        "toc_personas": toc_personas,
        "tail_personas": tail_personas,
        "signatory_count": signatory_count,
    }


# ===========================================================================
# N11 (Part C): CBO Page-1 `"At a Glance"` Cost Card Parser (`spicy_docs/sources/cbo_pdf_cards.py`)
# ===========================================================================

_CBO_MEASURES = {
    "direct_spending_outlays": r"Direct Spending \(Outlays\)",
    "revenues": r"Revenues",
    "increase_or_decrease_in_the_deficit": r"(?:(?:Net )?Increase or Decrease \(-\) in the Deficit|Deficit Effect)",
    "spending_subject_to_appropriation_outlays": r"Spending Subject to Appropriation \(Outlays\)",
}
_CBO_QUESTIONS = {
    "increase_net_spending": r"Increases net direct spending in any of the four consecutive 10-year periods beginning in [0-9]{4}\?",
    "pay_go": r"Statutory pay-as-you-go procedures apply\?",
    "increase_budget_deficits": r"Increases on-budget deficits in any of the four consecutive 10-year periods beginning in [0-9]{4}\?",
    "mandate_effect_intergovernmental": r"Contains intergovernmental mandate\?",
    "mandate_effect_private_sector": r"Contains private-sector mandate\?",
}
_CBO_CELL = r"(?:-?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|\*|[Nn]ot estimated|a)"
_CBO_DATE_LINE_RE = re.compile(r"^(?:Revised\s+)?([A-Z][a-z]+\s+[0-9]{1,2},\s+[0-9]{4})(?:\s*\(Revised\))?$")
_CBO_BILL_HEAD_RE = re.compile(
    r"^(H\.?\s*R\.?|S\.?|H\.?\s*J\.?\s*Res\.?|S\.?\s*J\.?\s*Res\.?|H\.?\s*Con\.?\s*Res\.?|S\.?\s*Con\.?\s*Res\.?|H\.?\s*Res\.?|S\.?\s*Res\.?)\s*(\d+)(?:\s*,\s*(.+))?$"
)
_BILL_CANON_PREFIX = {
    "hr": "H.R.",
    "s": "S.",
    "hjres": "H.J. Res.",
    "sjres": "S.J. Res.",
    "hconres": "H.Con. Res.",
    "sconres": "S.Con. Res.",
    "hres": "H.Res.",
    "sres": "S.Res.",
}


class CboSourceError(ValueError):
    """The text does not state a valid CBO page-1 cost-estimate card."""


@dataclass(frozen=True)
class CboPdfCard:
    publication_id: str
    date_str: str
    iso_date: str | None
    heading: str
    subtitle: str | None
    periods: tuple[str, str, str]
    measures: dict[str, tuple[str, str, str]]
    answers: dict[str, str]
    footnotes: tuple[str, ...]
    source_unit: str
    notes: tuple[str, ...]


def _parse_english_date_to_iso(date_str: str) -> str | None:
    try:
        return datetime.datetime.strptime(date_str.strip(), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def parse_pdf_card_text(text: str, *, publication_id: str = "archive") -> CboPdfCard:
    """Stdlib port of `spicy_docs.sources.cbo_pdf_cards.parse_pdf_card_text` on `\n`-preserved page 1."""
    if not text or "\n" not in text:
        raise CboSourceError("CBO PDF card parser requires newline-preserved page-1 text")
    flat = " ".join(text.split())
    unit = re.search(r"By Fiscal Year, (Millions|Billions) of Dollars\s+", flat)
    if unit is None or "Congressional Budget Office" not in flat or not re.search(r"(?:Cost|Dynamic) Estimate", flat):
        raise CboSourceError("PDF page does not state the expected CBO card and source unit")
    source_unit = "billions-usd" if unit.group(1) == "Billions" else "millions-usd"
    body = flat[unit.end() :]
    periods = re.match(r"([0-9]{4}(?:-[0-9]{4})?)\s+([0-9]{4}(?:-[0-9]{4})?)\s+([0-9]{4}(?:-[0-9]{4})?)\s+", body)
    if periods is None:
        raise CboSourceError("PDF card does not state three positional fiscal window headings")
    question_ends: list[int] = []
    for label in _CBO_QUESTIONS.values():
        m_q = re.search(label, body)
        if m_q:
            question_ends.append(m_q.end())
    table_end = max(question_ends) if question_ends else len(body)
    matches = sorted(
        (match.start(), match.end(), name, kind)
        for kind, labels in (("measure", _CBO_MEASURES), ("question", _CBO_QUESTIONS))
        for name, label in labels.items()
        for match in re.finditer(label, body)
        if match.start() < table_end
    )
    measures: dict[str, tuple[str, str, str]] = {}
    answers: dict[str, str] = {}
    tail = ""
    for position, (_, end, name, kind) in enumerate(matches):
        if name in measures or name in answers:
            raise CboSourceError("PDF first page repeats a card label")
        stop = matches[position + 1][0] if position + 1 < len(matches) else len(body)
        value = body[end:stop].strip()
        if kind == "measure":
            cells = re.fullmatch(rf"({_CBO_CELL})\s+({_CBO_CELL})\s+({_CBO_CELL})", value)
            if cells is None:
                raise CboSourceError(f"PDF card has unread or extra cells for {name}")
            g = cells.groups()
            measures[name] = (g[0], g[1], g[2])
        else:
            answer = re.match(
                r"(No|Yes(?:,\s*(?:Over Threshold|Under Threshold|Cannot Determine Costs))?|Excluded from UMRA|[<>] \$[0-9.]+ billion|\*|a|n\.a\.)(?=\s|$)",
                value,
            )
            if answer is None:
                raise CboSourceError(f"PDF card has an unread answer for {name}")
            answers[name] = answer.group(1)
            if position == len(matches) - 1:
                tail = value[answer.end() :].strip()
            elif value[answer.end() :].strip() not in {"", "Mandate Effects"}:
                raise CboSourceError(f"PDF card has extra answer content for {name}")
    if not measures or len(answers) < 2 or "pay_go" not in answers:
        raise CboSourceError("PDF card labels are incomplete")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    date_index: int | None = None
    date_clean = ""
    for index, line in enumerate(lines):
        m_dt = _CBO_DATE_LINE_RE.match(line)
        if m_dt:
            date_index = index
            date_clean = m_dt.group(1)
            break
    if date_index is None:
        raise CboSourceError("PDF estimate date heading is unread")
    unit_index = next(
        (index for index, line in enumerate(lines) if re.search(r"By Fiscal Year, (?:Millions|Billions) of Dollars", line)),
        None,
    )
    if unit_index is None or unit_index <= date_index:
        raise CboSourceError("PDF estimate unit heading is unread")
    header = [line for line in lines[date_index + 1 : unit_index] if line != "At a Glance"]
    if not header:
        raise CboSourceError("PDF estimate bill heading is unread")
    context_index = next((index for index, line in enumerate(header) if line.startswith("As ")), len(header))
    heading = " ".join(header[:context_index]).strip()
    subtitle = " ".join(header[context_index:]).strip() or None
    if not heading:
        heading = " ".join(header).strip()
        subtitle = None
    footnotes = tuple(line for line in lines if line.startswith("* =") or "table applies to each bill" in line.lower())
    p_groups = periods.groups()
    return CboPdfCard(
        publication_id=publication_id,
        date_str=date_clean,
        iso_date=_parse_english_date_to_iso(date_clean),
        heading=heading,
        subtitle=subtitle,
        periods=(p_groups[0], p_groups[1], p_groups[2]),
        measures=measures,
        answers=answers,
        footnotes=footnotes,
        source_unit=source_unit,
        notes=(tail,) if tail else (),
    )


def parse_cbo_cost_estimate_v6(text: str, *, publication_id: str = "archive") -> dict[str, Any] | None:
    """Parse `\n`-preserved CBO page-1 cost card into `DocMetaV4Causal` fields (`None` when not a CBO card)."""
    if not text or "Congressional Budget Office" not in text:
        return None
    # Pass page 1 (or up to first 4,500 chars if pages joined)
    p1 = text.split("\f", 1)[0][:4500]
    try:
        card = parse_pdf_card_text(p1, publication_id=publication_id)
    except CboSourceError:
        return None

    bill_ref: str | None = None
    short_title: str | None = None
    m_bh = _CBO_BILL_HEAD_RE.match(card.heading)
    if m_bh:
        b_key = re.sub(r"[^a-z]", "", m_bh.group(1).lower())
        b_disp = _BILL_CANON_PREFIX.get(b_key, m_bh.group(1).strip())
        bill_ref = f"bill:{b_disp} {m_bh.group(2)}"
        st = (m_bh.group(3) or "").strip()
        if st and not st.lower().startswith(("a bill ", "an act ", "a joint resolution ", "a resolution ")):
            short_title = st

    fys: list[int] = []
    for p in card.periods:
        for yr_s in p.split("-"):
            if yr_s.isdigit():
                yr = int(yr_s)
                if 1990 <= yr <= 2050 and yr not in fys:
                    fys.append(yr)
    fys.sort()

    unit_word = "billion" if card.source_unit == "billions-usd" else "million"
    w_10yr = card.periods[2]
    w_5yr = card.periods[1]
    summary_parts: list[str] = []
    def_vals = card.measures.get("increase_or_decrease_in_the_deficit")
    ds_vals = card.measures.get("direct_spending_outlays")
    rev_vals = card.measures.get("revenues")
    app_vals = card.measures.get("spending_subject_to_appropriation_outlays")
    if ds_vals and ds_vals[2] not in ("0", "*"):
        summary_parts.append(f"direct spending {ds_vals[2]} {unit_word} ({w_10yr})")
    if rev_vals and rev_vals[2] not in ("0", "*"):
        summary_parts.append(f"revenues {rev_vals[2]} {unit_word} ({w_10yr})")
    if def_vals:
        summary_parts.append(f"net deficit effect {def_vals[2]} {unit_word} ({w_10yr})")
    if app_vals and app_vals[1] not in ("not estimated", "Not estimated"):
        summary_parts.append(f"discretionary outlays {app_vals[1]} {unit_word} ({w_5yr})")
    paygo = card.answers.get("pay_go")
    if paygo:
        summary_parts.append(f"PAYGO: {paygo}")

    target_label = bill_ref.removeprefix("bill:") if bill_ref else card.heading[:80]
    action_summary = f"CBO cost estimate for {target_label}: " + "; ".join(summary_parts)

    return {
        "primary_kind": "revenue_or_cost_estimate",
        "doc_date": card.iso_date,
        "heading": card.heading,
        "subtitle": card.subtitle,
        "bill_ref": bill_ref,
        "short_title": short_title,
        "periods": list(card.periods),
        "fiscal_years": fys,
        "source_unit": card.source_unit,
        "measures": {k: list(v) for k, v in card.measures.items()},
        "answers": dict(card.answers),
        "action_summary": action_summary[:320],
    }


# ===========================================================================
# N11 (Part D): GAO Front-Matter Requester Parser (`spicy_docs/sources/gao/report_requesters.py`)
# ===========================================================================

REPORT_REQUESTERS_RULE = "gao-report-front-matter-requesters/1"
TESTIMONY = "testimony"
CG_INITIATED = "cg_initiated"
CORRESPONDENCE = "correspondence"
CONGRESSIONAL_REQUEST = "congressional_request"
NAMED = "named"
LISTED = "listed"
COVER = "cover"
COLLECTIVE = "collective"
UNREAD = "unread"
NOT_READ = "not-read"

MAX_PRODUCT_ID_LENGTH = 256
_GAO_PRODUCT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9.,-]*$")
_GAO_TOKENS_RE = re.compile(r"[a-z0-9]+")
_GAO_DUPLICATE_PATH_RE = re.compile(r"-\d{1,3}")
_GAO_TRAILING_DUP_RE = re.compile(r"-\d{1,3}\Z")

_GAO_NUMBER_PAGES = 3
_GAO_HEAD_PAGES = 30
_GAO_FORMAT_RE = re.compile("[\u00ad\u200b-\u200d\u2060\ufeff]")
_GAO_NUMBER_RE = re.compile(r"\b[A-Z]{2,5}-\d{2}-\d+[A-Z]{0,2}\b")
_GAO_STRICT_ID_EXTRACT_RE = re.compile(r"\b(GAO-\d{2}-\d{2,7}[A-Z]{0,2})\b", re.I)
_GAO_LETTER_NUMBER_RE = re.compile(r"\dR")
_GAO_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_GAO_DATE_RE = re.compile(rf"(?:{_GAO_MONTHS})(?: \d{{1,2}},)? \d{{4}}")
_GAO_COLLECTIVE_RE = re.compile(r"Congressional (?:Requesters?|Committees?|Addressees?)")
_GAO_CONGRESS_RE = re.compile(
    r"\b(?:Congressional|Congress|Subcommittees?|Committees?|Senate|House of Representatives|Senators?|Caucus)\b"
)
_GAO_COVER_BODY = (
    r"{kind} on [^;]+?),? "
    r"(?P<chamber>U\.S\. Senate|United States Senate|(?:U\.S\. |United States )?House of Representatives)"
)
_GAO_COVER_COMMITTEE_RE = re.compile(
    "(?P<body>(?:(?:Permanent Select|Select|Special|Joint) )?" + _GAO_COVER_BODY.format(kind="Committee")
)
_GAO_COVER_SUBCOMMITTEE_RE = re.compile("(?P<body>" + _GAO_COVER_BODY.format(kind="Subcommittee"))
_GAO_NOT_A_NAME_RE = re.compile(r"ommittee\b.*ommittee\b|\b(?:Chair|Ranking|Member)")
_GAO_TESTIMONY_RE = re.compile(r"Testimony(?: [Bb]efore\b.*)?|Statement for the Record\b.*")
_GAO_REPORT_TO_RE = re.compile(r"(?:\S+ )?Report to\b.*")
_GAO_BY_THE_CG_RE = re.compile(r"By the Comptroller General of the United States")
_GAO_COVER_END_RE = re.compile(
    rf"(?:{_GAO_MONTHS})\b|[A-Z]{{2,5}}-\d{{2}}-\d|United States Government|For Release|Revised\b|Accessible\b"
)
_GAO_CHAMBER_END_RE = re.compile(r"(?:Senate|House of Representatives)$")
_GAO_MAX_COVER_LINES = 8
_GAO_LETTERHEAD_RE = re.compile(r"441 G St")
_GAO_CG_LETTERHEAD_RE = re.compile(r"Comptroller General\b")
_GAO_MAX_HEAD_LINES = 6
_GAO_HONORABLE = "The Honorable "
_GAO_ROLE_RE = re.compile(
    r"(?:Acting |Interim )?(?:"
    r"(?:Co-|Vice[ -])?Chair(?:man|woman|person)?(?: Emeritus)?"
    r"|Ranking (?:Minority )?Member"
    r"|(?:Majority|Minority|Republican|Democratic) (?:Leader|Whip)"
    r"|Speaker(?: of the House(?: of Representatives)?)?"
    r"|President [Pp]ro [Tt]empore(?: of the Senate)?"
    r")"
)
_GAO_CHAMBERS = {
    "United States House of Representatives": "House",
    "U.S. House of Representatives": "House",
    "House of Representatives": "House",
    "United States Senate": "Senate",
    "U.S. Senate": "Senate",
}
_GAO_BODY_KIND_RE = re.compile(r"\b(?:Subcommittee|Committee|Commission|Caucus)\b")
_GAO_BODY_RE = re.compile(r"(?:[A-Z][\w.’'-]* ){0,4}(?:Subcommittee|Committee|Commission|Caucus)\b")
_GAO_BODY_START_RE = re.compile(
    r"(?<=\s)(?<!Permanent )(?<!Select )(?<!Special )(?<!Joint )"
    r"(?=(?:Permanent |Select )?Subcommittee on |(?:Permanent Select |Select |Special |Joint )?Committee on )"
)
_GAO_MAX_BODY_LINES = 6
_GAO_LIST_HEADING_RE = re.compile(
    r"\b(?:List of (?:Congressional )?\w+|Congressional (?:Requesters|Committees|Addressees))"
    r"(?: \(?[Cc]ontinued\)?)?$"
)
_GAO_PAGE_MARK_RE = re.compile(r"Page \w+\b")
_GAO_MAX_MARGIN_LINES = 8
_GAO_MAX_CUT_LINES = 4
_GAO_CONGRESS_RUN = "congress"
_GAO_OUTSIDE_RUN = "outside"
_GAO_UNREADABLE_RUN = "unreadable"


class GaoProductSourceError(ValueError):
    """GAO product identifier is invalid."""


class GaoReportRequesterError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"GAO report front matter: {message}")
        self.reason = reason


@dataclass(frozen=True)
class RequesterEvidence:
    kind: str
    page: int
    text: str


@dataclass(frozen=True)
class GaoReportRequesters:
    product_id: str
    requester_type: str
    committees: tuple[str, ...]
    members: tuple[str, ...]
    addressees: str
    evidence: tuple[RequesterEvidence, ...]
    rule: str = REPORT_REQUESTERS_RULE


@dataclass(frozen=True)
class _GaoLine:
    page: int
    text: str


@dataclass(frozen=True)
class _GaoBlock:
    honorees: tuple[tuple[str | None, str | None], ...]
    bodies: tuple[str, ...] | None
    chamber: str | None


@dataclass(frozen=True)
class _GaoRun:
    start: int
    end: int
    blocks: tuple[_GaoBlock, ...]
    state: str


@dataclass(frozen=True)
class _GaoHead:
    start: int
    end: int
    comptroller: bool
    collective: _GaoLine | None
    run: _GaoRun | None


def gao_product_id(value: object) -> str:
    if not isinstance(value, str) or len(value) > MAX_PRODUCT_ID_LENGTH or _GAO_PRODUCT_ID_RE.fullmatch(value) is None:
        raise GaoProductSourceError("GAO product IDs must be bounded lowercase ASCII ids of letters, digits, - . and ,")
    return value


def names_page(slug: str, number: str, *, exact: bool) -> bool:
    wanted = number.lower()
    if exact:
        return slug == wanted or (
            slug.startswith(wanted) and _GAO_DUPLICATE_PATH_RE.fullmatch(slug[len(wanted) :]) is not None
        )
    tokens = _GAO_TOKENS_RE.findall(wanted)
    if _GAO_TOKENS_RE.findall(slug) == tokens:
        return True
    suffix = _GAO_TRAILING_DUP_RE.search(slug)
    return suffix is not None and _GAO_TOKENS_RE.findall(slug[: suffix.start()]) == tokens


def _gao_lines(pages: Sequence[str]) -> list[_GaoLine]:
    out: list[_GaoLine] = []
    for number, page in enumerate(pages, 1):
        for raw in _GAO_FORMAT_RE.sub("", page).split("\n"):
            text = " ".join(raw.split())
            if text:
                out.append(_GaoLine(number, text))
    return out


def _gao_evidence(kind: str, lines: Sequence[_GaoLine]) -> RequesterEvidence:
    return RequesterEvidence(kind, lines[0].page, "\n".join(line.text for line in lines))


def _gao_stated_number(lines: Sequence[_GaoLine], product_id: str) -> tuple[str, _GaoLine]:
    seen: dict[str, None] = {}
    for line in lines:
        if line.page > _GAO_NUMBER_PAGES:
            break
        for number in _GAO_NUMBER_RE.findall(line.text):
            if names_page(product_id, number, exact=True):
                return number, line
            seen.setdefault(number)
    raise GaoReportRequesterError(
        "not-this-report", f"the first pages state {list(seen) or 'no number'}, not {product_id}'s"
    )


def _gao_statement(first: Sequence[_GaoLine], at: int) -> list[_GaoLine]:
    taken = [first[at]]
    if _GAO_COLLECTIVE_RE.search(first[at].text):
        return taken
    for line in first[at + 1 : at + _GAO_MAX_COVER_LINES]:
        if _GAO_CHAMBER_END_RE.search(taken[-1].text) or _GAO_COVER_END_RE.match(line.text):
            break
        taken.append(line)
    return taken


def _gao_cover(lines: Sequence[_GaoLine]) -> tuple[str, list[_GaoLine]] | None:
    first = [line for line in lines if line.page == 1]
    for at, line in enumerate(first):
        if _GAO_TESTIMONY_RE.fullmatch(line.text):
            return TESTIMONY, _gao_statement(first, at)
        if _GAO_REPORT_TO_RE.fullmatch(line.text):
            return "report", _gao_statement(first, at)
    for at in range(len(first)):
        if _GAO_BY_THE_CG_RE.match(" ".join(part.text for part in first[at : at + 3])):
            return CG_INITIATED, first[at : at + 2]
    return None


def _gao_cover_committees(statement: str) -> tuple[str, ...]:
    found = list(_GAO_COVER_COMMITTEE_RE.finditer(statement)) or list(_GAO_COVER_SUBCOMMITTEE_RE.finditer(statement))
    if any(_GAO_NOT_A_NAME_RE.search(match.group("body")) for match in found):
        return ()
    chambers = {"Senate": "Senate", "House of Representatives": "House"}
    out: dict[str, None] = {}
    for match in found:
        ch_m = _GAO_CHAMBER_END_RE.search(match.group("chamber"))
        if ch_m:
            out.setdefault(f"{match.group('body')} ({chambers[ch_m.group(0)]})")
    return tuple(out)


def _gao_starts_block(text: str) -> bool:
    return text.startswith(_GAO_HONORABLE) or _GAO_ROLE_RE.fullmatch(text) is not None


def _gao_honoree(text: str) -> tuple[str | None, str | None, str | None]:
    if not text.startswith(_GAO_HONORABLE):
        return None, text, None
    name = text[len(_GAO_HONORABLE) :]
    head, comma, tail = name.rpartition(", ")
    if comma and _GAO_ROLE_RE.fullmatch(tail):
        return head, tail, None
    if comma and tail in _GAO_CHAMBERS:
        return head, None, _GAO_CHAMBERS[tail]
    return name, None, None


def _gao_bodies(between: Sequence[str]) -> tuple[str, ...] | None:
    bodies: list[str] = []
    for text in between:
        for at, part in enumerate(_GAO_BODY_START_RE.split(text)):
            if at or _GAO_BODY_KIND_RE.search(part):
                bodies.append(part.strip(" ,"))
            elif bodies:
                bodies[-1] = f"{bodies[-1]} {part}"
            else:
                return None
    return tuple(bodies)


def _gao_chamber(lines: Sequence[_GaoLine], index: int, first: int) -> tuple[str, str] | None:
    text = lines[index].text.lstrip("|")
    for spelling, chamber in _GAO_CHAMBERS.items():
        if text == spelling:
            return "", chamber
        if text.endswith(f" {spelling}"):
            before = text[: -len(spelling)].rstrip(" ,")
            if _GAO_BODY_RE.match(before) or (index > first and _GAO_BODY_KIND_RE.search(lines[index - 1].text)):
                return before, chamber
    return None


def _gao_block(lines: Sequence[_GaoLine], at: int) -> tuple[_GaoBlock, int]:
    honorees: list[tuple[str | None, str | None]] = []
    while at < len(lines) and _gao_starts_block(lines[at].text):
        name, role, chamber = _gao_honoree(lines[at].text)
        width = 1
        if role is None and chamber is None and at + 1 < len(lines):
            wrapped = _gao_honoree(f"{lines[at].text} {lines[at + 1].text}")
            if wrapped[2] is not None:
                (name, role, chamber), width = wrapped, 2
        if chamber is not None and honorees:
            return _GaoBlock(tuple(honorees), (), None), at
        if chamber is not None:
            return _GaoBlock(((name, None),), (), chamber), at + width
        at += 1
        if role is None and at < len(lines) and _GAO_ROLE_RE.fullmatch(lines[at].text):
            role = lines[at].text
            at += 1
        honorees.append((name, role))
    for stop in range(at, min(at + _GAO_MAX_BODY_LINES + 1, len(lines))):
        ended = None if _gao_starts_block(lines[stop].text) else _gao_chamber(lines, stop, at)
        if ended is not None or _gao_starts_block(lines[stop].text):
            between = [line.text for line in lines[at:stop]] + ([ended[0]] if ended and ended[0] else [])
            return _GaoBlock(tuple(honorees), _gao_bodies(between), ended and ended[1]), stop + (1 if ended is not None else 0)
    stop = at
    while stop < len(lines) and stop < at + _GAO_MAX_BODY_LINES and _GAO_BODY_RE.match(lines[stop].text):
        stop += 1
    return _GaoBlock(tuple(honorees), tuple(line.text for line in lines[at:stop]), None), stop


def _gao_congress(block: _GaoBlock) -> bool:
    if block.bodies is None:
        return False
    if block.chamber is not None:
        return True
    return bool(block.bodies) and not any(
        (_GAO_BODY_KIND_RE.search(body).group(0).endswith("ommittee") if _GAO_BODY_KIND_RE.search(body) else False)  # type: ignore[union-attr]
        for body in block.bodies
    )


def _gao_page_line(text: str, number: str) -> bool:
    return _GAO_PAGE_MARK_RE.fullmatch(text) is not None or number in text


def _gao_past_page_lines(lines: Sequence[_GaoLine], at: int, number: str) -> int:
    while at < len(lines) and (_gao_page_line(lines[at].text, number) or _GAO_LIST_HEADING_RE.search(lines[at].text)):
        at += 1
    return at


def _gao_run(lines: Sequence[_GaoLine], at: int, number: str) -> _GaoRun:
    start = at
    blocks: list[_GaoBlock] = []
    while at < len(lines) and _gao_starts_block(lines[at].text):
        block, at = _gao_block(lines, at)
        blocks.append(block)
        after = _gao_past_page_lines(lines, at, number)
        if not (after < len(lines) and _gao_starts_block(lines[after].text)):
            turn = at
            while turn < len(lines) and lines[turn].page == lines[at - 1].page:
                turn += 1
            if turn - at <= _GAO_MAX_MARGIN_LINES:
                after = _gao_past_page_lines(lines, turn, number)
        if after < len(lines) and _gao_starts_block(lines[after].text):
            at = after
    cut = any(
        line.page == lines[at - 1].page and line.text.startswith(_GAO_HONORABLE)
        for line in lines[at : at + _GAO_MAX_CUT_LINES]
    )
    if not any(block.chamber for block in blocks):
        state = _GAO_OUTSIDE_RUN
    elif not cut and all(_gao_congress(block) for block in blocks):
        state = _GAO_CONGRESS_RUN
    else:
        state = _GAO_UNREADABLE_RUN
    return _GaoRun(start, at, tuple(blocks), state)


def _gao_head(lines: Sequence[_GaoLine], number: str) -> _GaoHead | None:
    for at, line in enumerate(lines):
        if line.page > _GAO_HEAD_PAGES:
            return None
        if not _GAO_LETTERHEAD_RE.match(line.text):
            continue
        start = at - 2 if any(_GAO_CG_LETTERHEAD_RE.match(part.text) for part in lines[max(at - 2, 0) : at]) else at
        window = [
            index
            for index in range(at + 1, min(at + 2 + _GAO_MAX_HEAD_LINES, len(lines)))
            if lines[index].page == line.page
        ]
        for index in window:
            comptroller = any(_GAO_CG_LETTERHEAD_RE.match(part.text) for part in lines[start:index])
            if _GAO_COLLECTIVE_RE.fullmatch(lines[index].text.rstrip(",:")):
                return _GaoHead(start, index + 1, comptroller, lines[index], None)
            if _gao_starts_block(lines[index].text):
                run = _gao_run(lines, index, number)
                return _GaoHead(start, run.end, comptroller, None, run)
        dated = [index for index in window if _GAO_DATE_RE.fullmatch(lines[index].text)]
        if dated:
            return _GaoHead(start, dated[0] + 1, False, None, None)
    return None


def _gao_heading(lines: Sequence[_GaoLine], at: int, number: str) -> int | None:
    back = at - 1
    while back >= 0 and lines[back].page == lines[at].page and _gao_page_line(lines[back].text, number):
        back -= 1
    for first in (back, back - 1):
        if first < 0 or lines[first].page != lines[at].page:
            return None
        if _GAO_LIST_HEADING_RE.search(" ".join(line.text for line in lines[first : back + 1])):
            return first
    return None


def _gao_listed(lines: Sequence[_GaoLine], begin: int, number: str, *, headed: bool) -> tuple[_GaoRun, int] | None:
    at = begin
    while at < len(lines):
        if not _gao_starts_block(lines[at].text):
            at += 1
            continue
        run = _gao_run(lines, at, number)
        heading = _gao_heading(lines, at, number)
        if run.state != _GAO_OUTSIDE_RUN and (heading is not None or not headed):
            return run, (at if heading is None else heading)
        at = max(run.end, at + 1)
    return None


def _gao_values(blocks: Sequence[_GaoBlock]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    committees: dict[str, None] = {}
    members: dict[str, None] = {}
    for block in blocks:
        chamber = "" if block.chamber is None else f" ({block.chamber})"
        for name, role in block.honorees:
            if name is not None:
                members.setdefault(f"{name}, {role}" if role else f"{name}{chamber}")
        kinds = [
            (_GAO_BODY_KIND_RE.search(body).group(0), body)  # type: ignore[union-attr]
            for body in (block.bodies or ())
            if _GAO_BODY_KIND_RE.search(body)
        ]
        named = [body for kind, body in kinds if kind == "Committee"] or [
            body for kind, body in kinds if kind == "Subcommittee"
        ]
        for body in named:
            committees.setdefault(f"{body}{chamber}")
    return tuple(committees), tuple(members)


def read_requesters(pages: Sequence[str], *, product_id: str) -> GaoReportRequesters:
    """Stdlib port of `spicy_docs.sources.gao.report_requesters.read_requesters`."""
    product_id = gao_product_id(product_id.strip().lower())
    lines = _gao_lines(pages)
    if not lines:
        raise GaoReportRequesterError("no-text", "the pages given hold no text")
    number, numbered = _gao_stated_number(lines, product_id)
    evidence = [_gao_evidence("number", [numbered])]

    def result(
        kind: str,
        committees: tuple[str, ...] = (),
        members: tuple[str, ...] = (),
        addressees: str = NOT_READ,
    ) -> GaoReportRequesters:
        return GaoReportRequesters(product_id, kind, committees, members, addressees, tuple(evidence))

    cover = _gao_cover(lines)
    if cover is not None:
        evidence.append(_gao_evidence("cover", cover[1]))
    if cover is not None and cover[0] in (TESTIMONY, CG_INITIATED):
        return result(cover[0])
    statement = "" if cover is None else " ".join(line.text for line in cover[1])
    letter = _GAO_LETTER_NUMBER_RE.search(number) is not None
    kind = CORRESPONDENCE if letter else CONGRESSIONAL_REQUEST
    head = _gao_head(lines, number)
    run = None if head is None else head.run
    if run is not None and run.state == _GAO_OUTSIDE_RUN:
        evidence.append(_gao_evidence("letter", lines[head.start : head.end]))
        if letter or head.comptroller:
            return result(CORRESPONDENCE if letter else CG_INITIATED)
        raise GaoReportRequesterError(
            "addressee-not-congressional", f"the letter is addressed to {lines[run.start].text!r}"
        )
    if run is not None:
        evidence.append(_gao_evidence("letter", lines[run.start : run.end]))
        if run.state != _GAO_CONGRESS_RUN:
            return result(kind, addressees=UNREAD)
        cmts, mems = _gao_values(run.blocks)
        return result(kind, cmts, mems, NAMED)
    collective = statement if _GAO_COLLECTIVE_RE.search(statement) else ""
    if head is not None and head.collective is not None:
        collective = head.collective.text
        evidence.append(_gao_evidence("letter", [head.collective]))
    if not collective and not _GAO_CONGRESS_RE.search(statement):
        if letter:
            return result(CORRESPONDENCE)
        if cover is None:
            raise GaoReportRequesterError(
                "no-addressee-read", "no cover statement and no addressee the reader knows in a letter's head"
            )
        raise GaoReportRequesterError("addressee-not-congressional", f"the cover states {statement!r}")
    found = _gao_listed(lines, 0 if head is None else head.end, number, headed=head is not None)
    if found is not None:
        evidence.append(_gao_evidence("list", lines[found[1] : found[0].end]))
        if found[0].state != _GAO_CONGRESS_RUN:
            return result(kind, addressees=UNREAD)
        cmts, mems = _gao_values(found[0].blocks)
        return result(kind, cmts, mems, LISTED)
    if collective:
        return result(kind, addressees=COLLECTIVE)
    return result(kind, _gao_cover_committees(statement), (), COVER)


def _canonicalize_gao_committee(raw_cmt: str) -> str:
    m = re.match(r"^(.+?)\s*\((House|Senate)\)$", raw_cmt.strip())
    if not m:
        return raw_cmt.strip()
    body, ch = m.group(1).strip(), m.group(2)
    if body.startswith(("Joint ", "Commission ", "Special Committee", "Select Committee", "Permanent Select")):
        if not body.lower().startswith((ch.lower(), "joint")):
            return f"{ch} {body}"
        return body
    if body.startswith("Committee on "):
        return f"{ch} {body}"
    return f"{ch} {body}"


_GAO_AUTHENTIC_FRONT_RE = re.compile(
    r"(?:^|\n)\s*(?:United\s+States\s+Government\s+Accountability\s+Office|"
    r"U\.?S\.?\s+Government\s+Accountability\s+Office|"
    r"United\s+States\s+General\s+Accounting\s+Office|"
    r"Comptroller\s+General\s+of\s+the\s+United\s+States|"
    r"441\s+G\s+St\.?\s*N\.?W\.?)\s*(?:\n|$)",
    re.I,
)


def parse_gao_requesters_v6(
    pages: Sequence[str],
    *,
    filename: str | None = None,
    explicit_product_id: str | None = None,
) -> dict[str, Any] | None:
    """Parse `\n`-preserved GAO report pages with automatic lowercase `product_id` normalization."""
    if not pages:
        return None
    joined_head = "\n".join(pages[:3])
    # Require standalone GAO cover/letterhead banner (blocks Congressional memos citing `GAO-97-120R` in prose!)
    if not _GAO_AUTHENTIC_FRONT_RE.search(joined_head):
        return None

    pid = (explicit_product_id or "").strip().lower()
    if not pid:
        m = _GAO_STRICT_ID_EXTRACT_RE.search(joined_head)
        if not m and filename:
            m = _GAO_STRICT_ID_EXTRACT_RE.search(filename)
        if not m:
            return None
        pid = m.group(1).lower()

    try:
        req = read_requesters(pages, product_id=pid)
    except (GaoProductSourceError, GaoReportRequesterError):
        return None

    canon_cmts = [_canonicalize_gao_committee(c) for c in req.committees]
    personas: list[dict[str, Any]] = []
    for mem in req.members[:MAX_PERSONAS]:
        if ", " in mem:
            nm, rl = mem.rsplit(", ", 1)
            personas.append({"name": nm.strip(), "title": rl.strip(), "role": "recipient", "entity_type": "member"})
        else:
            nm = re.sub(r"\s*\((?:House|Senate)\)$", "", mem).strip()
            personas.append({"name": nm, "role": "recipient", "entity_type": "member"})

    is_testimony = req.requester_type == TESTIMONY or pid.endswith("t")
    flow = (
        "agency_to_congress"
        if (not is_testimony and req.requester_type in (CONGRESSIONAL_REQUEST, CORRESPONDENCE))
        else None
    )
    return {
        "product_id": req.product_id,
        "gao_ref": f"gao:{req.product_id.upper()}",
        "requester_type": req.requester_type,
        "is_testimony": is_testimony,
        "addressees_source": req.addressees,
        "committees": canon_cmts,
        "personas": personas,
        "correspondence_flow": flow,
    }
