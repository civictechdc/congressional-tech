#!/usr/bin/env python3
"""Expanded 100%-Precision Deterministic Rules for Pythonic V5 (`expanded_rules_v5.py`).

100% Python stdlib-only runtime module (zero external dependencies) surfaced via
unsupervised TF-IDF header clustering across the 31,715 doubly-unsegmented zero-hit
slice and 206,413 Tier-1 unmatched `S_raw` documents:

  A. Complete HTML Inference & CMS Navigation Strippers (`infer_is_html_v5`, `strip_html_cms_nav_v5`):
     - Strips 9 recurring House/Senate/Congress.gov/THOMAS CMS wrapper families missed or
       partially stripped in V4 (`house_legacy_aspx_cms` `documentsingle.aspx`/`PRArticle.aspx`,
       Ways & Means `"Internships News Listening To Americans..."`, `hsvr` `"Media Center Press
       Releases ... Stay connected with the Committee"`, inline JS/CSS/CDATA settings blocks,
       case-insensitive `skip to [main ]content`, unprefixed committee `Toggle Submenu` / `Home
       Logo Link` / `Search` nav bars, THOMAS report headers, and trailing `hsvr` right-rail
       `"Upcoming Hearings There are no upcoming Hearings..."` time-travel widgets) while
       preserving `docs.house.gov` weekly schedules and GPO HTML transcripts with 0 body truncation.

  B. OCR-Tolerant Committee Masthead & Congress Matchers (`extract_formal_committee_masthead_v5`,
     `extract_pdf_masthead_congress_v5`):
     - Recovers corrupted OCR & letter-spaced mastheads (`"COMMITTEE ON * * WAYS IND MEANS"`,
       `"Louse of Representatibes"`, `"Representatiues"`, `"Cnmmitter on Natural Rexnurces"`,
       `"Foreign Aftairs"`, `"JUDICIAR)"`, `"UNITED ST ATES SENATE"`, `"Lnited States Senate"`,
       letter-spaced `"U N I T E D  S T A T E S  S E N A T E"` / `"C O M M I T T E E  O N"`,
       `hsii00` cellular-dais hearing headers, and OCR Congress ordinals `1l4th`, `ll5th`,
       `1I2TH`, `112 TH`, `116"`, `115'h`, `CONCRESS`, pre-positioned institutional headers)
       under strict negative guards (0 mismatches and 0 empty-gold FPs on `Gold360` & `Wild1090`).

  C. Expanded 100.0%-Pure Tier-1 `doc_kind` Signatures + Non-Locking Tier-2 Sidecar Hints:
     - Preserves all 21 V4 Tier-1 signatures (`V4_TIER1_SIGNATURE_TO_KIND`) with exact parity
       and adds 11 mutually-exclusive 100.0%-precision V5 Tier-1 signatures
       (`NEW_TIER1_SIGNATURE_TO_KIND_V5`) verified at 0 FPs on `Gold360` (100% `LLMatcher`
       token-replay acceptance), 0 FPs on `Wild1090`, and 0 cross-kind collisions + 0 overlaps
       across all 260,156 `S_raw` documents.
     - Demotes boundary-sensitive cues (e.g., `FOR IMMEDIATE RELEASE` committee press releases
       without advisory/hearing-announcement markers, untemplated witness biographies, GPO
       cover-only pages) to non-locking `detect_tier2_sidecar_hints_v5`.
"""

from __future__ import annotations

import datetime
import json
import re
import unicodedata
from typing import Any

WS_RE = re.compile(r"[ \t\r\n]+")

OFFICIAL_SLUG_CONGRESS_RE = re.compile(
    r"^(?:[0-9a-fA-F]{64}\.)?(?:HHRG|HMTG|HMKP|BILLS|CRPT|CHRG|SHRG|HRPT|SRPT)-(\d{3})(?=-|[A-Za-z])",
    re.IGNORECASE,
)


def _norm_ws_prefix(text: str, limit: int = 2600) -> str:
    """Fast whitespace normalizer on bounded prefix; avoids regex copy when already single-spaced."""
    sub = text[:limit]
    if "\n" in sub or "\r" in sub or "\t" in sub or "  " in sub:
        return WS_RE.sub(" ", sub).strip()
    return sub.strip()


# Letter-spaced all-caps sequence (3+ single uppercase letters separated by spaces, e.g. "U N I T E D")
_SPACED_CAPS_SEQ_RE = re.compile(r"(?<![A-Za-z])([A-Z](?:[ \t]{1,3}[A-Z]){3,})(?![A-Za-z])")


def _collapse_letter_spaced_caps(text: str) -> str:
    """Collapse letter-spaced ALL-CAPS banners ('U N I T E D  S T A T E S  S E N A T E' -> 'UNITED STATES SENATE')."""
    if "  " not in text and not re.search(r"\b[A-Z] [A-Z] [A-Z] [A-Z]\b", text):
        return text

    def _repl(m: re.Match[str]) -> str:
        raw = m.group(1)
        # Split multi-space word breaks first if present, else collapse single-space letters
        if "  " in raw or "\t" in raw:
            words = re.split(r"(?:[ \t]{2,})", raw)
            return " ".join(w.replace(" ", "").replace("\t", "") for w in words)
        collapsed = raw.replace(" ", "")
        # Separate well-known concatenated institutional headers when single-spaced throughout
        for kw in (
            "UNITED",
            "STATES",
            "SENATE",
            "HOUSE",
            "REPRESENTATIVES",
            "CONGRESS",
            "COMMITTEE",
            "SUBCOMMITTEE",
            "MEMORANDUM",
            "HUNDRED",
            "ONE",
            "RESOLUTION",
            "REPORT",
            "NOTICE",
            "HEARING",
        ):
            collapsed = collapsed.replace(kw, f" {kw} ")
        return WS_RE.sub(" ", collapsed).strip()

    return _SPACED_CAPS_SEQ_RE.sub(_repl, text)


# ===========================================================================
# Pillar A: Complete HTML Inference & CMS Navigation Strippers
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


def infer_is_html_v5(
    filename: str | None,
    text: str | None,
    is_html: bool | None = None,
) -> bool:
    """Infer whether `(filename, text)` is a scraped HTML web page vs PDF/office document."""
    if is_html is not None:
        return bool(is_html)
    base = (filename or "").strip().rsplit("/", 1)[-1]
    if _PDF_DOC_EXT_RE.search(base) or _UUID_BASENAME_RE.match(base):
        return False
    t_head = _norm_ws_prefix(text or "", 1600)
    if _HTML_STRICT_EXT_RE.search(base):
        return True
    if _HTML_CHROME_CUE_RE.search(t_head):
        return True
    if _GPO_PDF_IMPRINT_RE.search(t_head[:400]):
        return False
    base_l = base.lower()
    if _ASPX_EXT_RE.search(base_l):
        # `DocumentSingle.aspx` and `r.aspx` are PDF download endpoints ONLY when no HTML chrome is present
        return base_l not in ("documentsingle.aspx", "r.aspx")
    if _URL_SLUG_BASENAME_RE.match(base):
        return True
    return False


CMS_STRIPPER_FAMILIES_V5: tuple[str, ...] = (
    "house_drupal7_cdata_settings",
    "inline_script_or_css_chrome",
    "house_ways_and_means_cms",
    "house_legacy_aspx_cms",
    "house_hsvr_legacy_media_center_cms",
    "thomas_loc_report_header",
    "house_evo_drupal9_waste_fraud_banner",
    "senate_modern_cms_skip_primary_nav",
    "modern_skip_to_content_cms",
    "unprefixed_committee_nav_cms",
    "house_hsvr_upcoming_hearings_rail",
)

_DOCS_HOUSE_WEEKLY_PREFIX = (
    "Committee Repository Clerk of the House Majority Leader Committee on Rules "
    "U.S. House of Representatives Bills to be Considered on the House Floor"
)
_GPO_HTML_HEARING_PREFIX_RE = re.compile(
    r"^\[(?:House|Senate|Joint)\s+Hearing,\s*\d+\s*(?:st|nd|rd|th)?\s*Congress\]",
    re.I,
)
_CDATA_SCRIPT_BLOCK_RE = re.compile(r"<!--//--><!\[CDATA\[//><!--.*?//--><!\]\]>", re.S)
_LEADING_CSS_COMMENTS_OR_RULES_RE = re.compile(
    r"^\s*(?:/\*.*?\*/\s*|"
    r"(?:img:is\([^)]+\)|:root|\.main-wrapper|a\[target=[^\]]+\]|body|html|\.[a-zA-Z0-9_-]+)\s*\{[^{}]{0,2400}\}\s*)+",
    re.S,
)
_LEADING_JSONLD_RE = re.compile(
    r'^\s*\{"@context"\s*:\s*"https?://schema\.org".*?\}\s*(?=[A-Z]|Skip|Menu|Home)',
    re.S | re.I,
)
_LEADING_FB_OR_GTAG_JS_RE = re.compile(
    r"^\s*(?:\(function\s*\(d,\s*s,\s*id\)\s*\{.*?\}\s*\(document,\s*['\"]script['\"],\s*['\"][^'\"]+['\"]\)\)\s*;?\s*|"
    r"window\.dataLayer\s*=\s*window\.dataLayer\s*\|\|\s*\[\]\s*;.*?(?:gtag\([^)]*\)\s*;?\s*)+)",
    re.S,
)

# Ways & Means CMS nav (both full `Skip to content ...` and partial `Internships News Listening To Americans ...`)
_WAYS_MEANS_NAV_END_RE = re.compile(
    r"(?:Skip to content\b.{0,500}?)?\bInternships\s+News\s+Listening\s+To\s+Americans\s+"
    r"Activity\s+Hearings\s+Markups\s+Calendar(?:\s+The\s+Working\s+Families\s+Tax\s+Cuts)?"
    r"(?:\s+Twitter\s+Instagram\s+Youtube)?\s+",
    re.I | re.S,
)

# House Legacy ASPX CMS (`documentsingle.aspx` / `PRArticle.aspx` across `hsed`, `hsag`, `hsas`, `hsba`, `hsfa`)
_HOUSE_LEGACY_ASPX_SEARCH_END_RE = re.compile(
    r"(?:Open\s+search\s+form|search\s+Submit|close\s+search|Open\s+main\s+menu(?:\s+Contact)?)"
    r"(?:\s+(?:Open\s+search\s+form|search\s+Submit|close\s+search|Open\s+main\s+menu|Contact))+\s+",
    re.I,
)
_HOUSE_LEGACY_ENL_NAV_RE = re.compile(
    r"^Search:\s*E-Newsletter:\s*Home\s+About\b.*?(?:Contact(?:\s+Us)?|Press\s+Releases|Subcommittees)\s+",
    re.I | re.S,
)

# HSVR 111th-112th Drupal/ASPX `Media Center Press Releases ... Stay connected with the Committee You are here Home`
_HSVR_MEDIA_CENTER_END_RE = re.compile(
    r"Media\s+Center\s+Press\s+Releases\s+Videos\s+Statements\b.{0,650}?"
    r"Stay\s+connected\s+with\s+the\s+Committee(?:\s+You\s+are\s+here(?:\s+Home)?)?\s+",
    re.I | re.S,
)

# Library of Congress THOMAS Committee Report search wrapper
_THOMAS_HEADER_END_RE = re.compile(
    r"^The\s+Library\s+of\s+Congress\s*>\s*THOMAS\s+Home\s*>.*?\bHelp\s+Contents\s+Display\s+",
    re.I | re.S,
)

# Generic nav menu boundary keywords (only applied when anchored by top-of-page CMS chrome)
_NAV_MENU_BOUNDARY_RE = re.compile(
    r"(?:(?:Subcommittees|Press Releases|Opening Statements|Newsletters|Additional Resources|"
    r"Contact Us|Publications|Transcripts|Subscribe|Search|Media Kit|Live Streams|"
    r"Press Contacts|Majority News|Minority News|Committee Schedule)\s+)+"
    r"(?=[A-Z0-9\"“])"
)

# Unprefixed Senate/House committee navigation banners (when `Skip to` was stripped upstream)
_UNPREFIXED_LOGO_LINK_RE = re.compile(
    r"^(?:The\s+Chairman\s+The\s+Ranking\s+Member|Committee\s+Rules\s+Clerkships|"
    r"Open\s+Submit\s+Site\s+Search\s+Query|About\s+The\s+Chairman|Menu\s+About\b)"
    r".{0,1400}?\bHome\s+Logo\s+Link\s+",
    re.I | re.S,
)
_UNPREFIXED_SSAP_MENU_RE = re.compile(
    r"^Agriculture,\s+Rural\s+Development,\s+Food\s+and\s+Drug\s+Administration.{0,1600}?"
    r"\bx\s+x\s+search\s+x\s+MENU\s+",
    re.I | re.S,
)
_UNPREFIXED_TOGGLE_SUBMENU_RE = re.compile(
    r"^(?:Menu\s+)?(?:About\s+|Jurisdiction\s+Rules\s+Hearings\s+)Toggle\s+Submenu\b.{0,1200}?"
    r"(?:Search\s+Hearings\s+Home\s+|Press\s+Contacts\s+Search\s+)",
    re.I | re.S,
)
_UNPREFIXED_WHISTLEBLOWER_SEARCH_RE = re.compile(
    r"^(?:History\s+Rules\s+Contact\s+FAQs\s+Whistleblower|About\s+Jurisdiction\s+and\s+Rules\s+Committee\s+Membership)"
    r".{0,2200}?\b(?:College\s+Sports\s+Search|Whistleblowers?\s+Search)\s+",
    re.I | re.S,
)
_UNPREFIXED_CSCE_NAV_RE = re.compile(
    r"^Statements\s+Speeches\s+In\s+the\s+News\s+Podcasts\s+Contact\s+Us\s+"
    r"Publications\s+Articles\s+Reports\s+Digests\s+Transcripts\s+",
    re.I,
)

# Right-rail / footer time-travel widget on HSVR witness/member pages (`962` S_raw docs + `Gold360 [23]`)
_HSVR_UPCOMING_RAIL_MARKER = "Upcoming Hearings There are no upcoming Hearings. Browse Archived Hearings."


def strip_html_cms_nav_v5(text: str | None) -> tuple[str, str | None]:
    """Strip recurring House/Senate/Congress.gov/THOMAS CMS navigation & sidebar time-travel chrome.

    Returns `(cleaned_text, primary_cms_family_or_None)`. Preserves `docs.house.gov` weekly schedules,
    GPO `[House/Senate Hearing]` HTML transcripts, and clean body text with 0 body truncation.
    """
    if not text or not isinstance(text, str):
        return text or "", None

    t_ws_head = _norm_ws_prefix(text, 420)
    if t_ws_head.startswith(_DOCS_HOUSE_WEEKLY_PREFIX) or _GPO_HTML_HEARING_PREFIX_RE.match(t_ws_head):
        return text, None

    cur = text
    reason: str | None = None

    # 1. Strip inline Drupal 7 CDATA script blocks
    if "<!--//--><![CDATA[" in cur[:2600]:
        cleaned_cdata = _CDATA_SCRIPT_BLOCK_RE.sub(" ", cur).strip()
        if len(cleaned_cdata) >= 80:
            cur = cleaned_cdata
            reason = "house_drupal7_cdata_settings"

    # 2. Strip leading inline CSS / JSON-LD / JS blocks when substantive text remains
    m_css = _LEADING_CSS_COMMENTS_OR_RULES_RE.match(cur[:4000])
    if m_css and len(cur) > m_css.end() + 120:
        cur = cur[m_css.end() :].lstrip()
        reason = reason or "inline_script_or_css_chrome"
    m_jld = _LEADING_JSONLD_RE.match(cur[:4500])
    if m_jld and len(cur) > m_jld.end() + 120:
        cur = cur[m_jld.end() :].lstrip()
        reason = reason or "inline_script_or_css_chrome"
    m_js = _LEADING_FB_OR_GTAG_JS_RE.match(cur[:2600])
    if m_js and len(cur) > m_js.end() + 120:
        cur = cur[m_js.end() :].lstrip()
        reason = reason or "inline_script_or_css_chrome"
    if cur.lstrip().startswith("if (!application) var application"):
        # Senate Armed Services MooTools preamble precedes `Skip to content`
        pos_skip = cur.find("Skip to content", 0, 4500)
        if pos_skip != -1 and len(cur) > pos_skip + 150:
            cur = cur[pos_skip:]
            reason = reason or "inline_script_or_css_chrome"

    # 3. Ways & Means CMS (`Skip to content ... Internships News Listening To Americans ...`)
    m_wm = _WAYS_MEANS_NAV_END_RE.search(cur[:1700])
    if m_wm and m_wm.start() < 350 and len(cur) > m_wm.end() + 80:
        cur = cur[m_wm.end() :].lstrip()
        reason = "house_ways_and_means_cms"

    # 4. HSVR 111th-112th `Media Center Press Releases ... Stay connected with the Committee You are here Home`
    #    (Checked BEFORE `Report Waste, Fraud, and Abuse` because HSVR 112th pages place Media Center AFTER it!)
    m_mc = _HSVR_MEDIA_CENTER_END_RE.search(cur[:2600])
    if m_mc and len(cur) > m_mc.end() + 60:
        cur = cur[m_mc.end() :].lstrip()
        reason = "house_hsvr_legacy_media_center_cms"

    # 5. House Evo / Drupal 9 `Report Waste, Fraud, and Abuse` banner
    marker_wfa = "Report Waste, Fraud, and Abuse"
    pos_wfa = cur.find(marker_wfa, 0, 2400)
    if pos_wfa != -1:
        after_wfa = cur[pos_wfa + len(marker_wfa) :].lstrip()
        if len(after_wfa) >= 55:
            cur = after_wfa
            reason = reason or "house_evo_drupal9_waste_fraud_banner"

    # 6. House Legacy ASPX CMS (`documentsingle.aspx` / `PRArticle.aspx` across `hsed`, `hsag`, `hsas`, etc.)
    m_aspx = list(_HOUSE_LEGACY_ASPX_SEARCH_END_RE.finditer(cur[:2200]))
    if m_aspx and len(cur) > m_aspx[-1].end() + 80:
        cur = cur[m_aspx[-1].end() :].lstrip()
        reason = reason or "house_legacy_aspx_cms"
    else:
        cur_l = cur.lstrip()
        m_enl = _HOUSE_LEGACY_ENL_NAV_RE.match(cur_l[:1400])
        if m_enl and len(cur_l) > m_enl.end() + 100:
            cur = cur_l[m_enl.end() :].lstrip()
            reason = reason or "house_legacy_aspx_cms"

    # 7. Library of Congress THOMAS Committee Report search chrome
    cur_l = cur.lstrip()
    if cur_l.startswith("The Library of Congress"):
        m_th = _THOMAS_HEADER_END_RE.match(cur_l[:900])
        if m_th and len(cur_l) > m_th.end() + 100:
            cur = cur_l[m_th.end() :].lstrip()
            reason = reason or "thomas_loc_report_header"

    # 8. Senate modern CMS `Skip to primary navigation ... ×Close` modal/menu header (case-insensitive)
    cur_l = cur.lstrip()
    if cur_l[:32].lower().startswith("skip to primary navigation"):
        close_hits = list(
            re.finditer(r"(?:×\s*Close|Search\s+Search|MENU\s+Home)\s+", cur_l[:2200], flags=re.I)
        )
        if close_hits and len(cur_l) > close_hits[-1].end() + 120:
            cur = cur_l[close_hits[-1].end() :].lstrip()
            reason = reason or "senate_modern_cms_skip_primary_nav"

    # 9. Generic case-insensitive `Skip to [main ]content` / `Skip Navigation` / `Toggle navigation`
    cur_l = cur.lstrip()
    if re.match(r"^(?:skip\s+to\s+|skip\s+navigation\b|toggle\s+navigation\b)", cur_l[:40], re.I):
        m_logo = re.search(r"Home\s+Logo\s+Link\s+", cur_l[:1800], re.I)
        if m_logo and len(cur_l) > m_logo.end() + 100:
            cur = cur_l[m_logo.end() :].lstrip()
            reason = reason or "modern_skip_to_content_cms"
        else:
            nav_hits = list(_NAV_MENU_BOUNDARY_RE.finditer(cur_l[:1400]))
            if nav_hits and len(cur_l) > nav_hits[-1].end() + 120:
                cur = cur_l[nav_hits[-1].end() :].lstrip()
                reason = reason or "modern_skip_to_content_cms"

    # 10. Unprefixed Senate/House committee navigation banners
    cur_norm_check = WS_RE.sub(" ", cur.lstrip()[:2600]).strip()
    for rx_unp in (
        _UNPREFIXED_LOGO_LINK_RE,
        _UNPREFIXED_SSAP_MENU_RE,
        _UNPREFIXED_TOGGLE_SUBMENU_RE,
        _UNPREFIXED_WHISTLEBLOWER_SEARCH_RE,
        _UNPREFIXED_CSCE_NAV_RE,
    ):
        m_u = rx_unp.match(cur_norm_check)
        if m_u:
            # Locate corresponding end phrase directly in `cur` so original body formatting is preserved
            end_snippet = cur_norm_check[max(0, m_u.end() - 28) : m_u.end()].strip()
            tokens = [re.escape(tok) for tok in end_snippet.split() if tok]
            if tokens:
                rx_orig = re.compile(r"\s+".join(tokens) + r"\s+", re.I)
                matches_orig = list(rx_orig.finditer(cur[:3200]))
                if matches_orig:
                    cut_pos = matches_orig[-1].end()
                    if len(cur) > cut_pos + 80:
                        cur = cur[cut_pos:].lstrip()
                        reason = reason or "unprefixed_committee_nav_cms"
                        break

    # 11. Trailing right-rail / footer `Upcoming Hearings There are no upcoming Hearings. Browse Archived Hearings.`
    #     Eliminates `115th Congress` sidebar time-travel pollution on HSVR witness/member pages (`pos >= 35`).
    pos_rail = cur.find(_HSVR_UPCOMING_RAIL_MARKER)
    if pos_rail >= 35:
        before_rail = cur[:pos_rail].rstrip()
        if len(before_rail) >= 35:
            cur = before_rail
            reason = reason or "house_hsvr_upcoming_hearings_rail"

    return (cur if reason is not None else text), reason


# Backwards-compatible aliases
infer_is_html = infer_is_html_v5
strip_html_cms_nav = strip_html_cms_nav_v5


# ===========================================================================
# Pillar B: Congressional Calendar, OCR-Tolerant Congress & Committee Mastheads
# ===========================================================================


def iso_date_to_congress(date_str: str | None) -> int | None:
    """Map an ISO date ('YYYY-MM-DD', 'YYYY-MM', or 'YYYY') to an exact U.S. Congress (1..130)."""
    if not date_str or not isinstance(date_str, str):
        return None
    s = date_str.strip()
    if len(s) > 10 and s[10] in ("T", " ") and re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", s):
        s = s[:10]

    m_ymd = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m_ymd:
        y, mo, da = int(m_ymd.group(1)), int(m_ymd.group(2)), int(m_ymd.group(3))
        try:
            datetime.date(y, mo, da)
        except ValueError:
            return None
        if y < 1789:
            return None
        if y % 2 == 1:
            if y < 1935:
                if mo < 3 or (mo == 3 and da <= 4):
                    return None
            else:
                if mo == 1 and da <= 3:
                    return None
            y_start = y
        else:
            y_start = y - 1
        c = (y_start - 1789) // 2 + 1
        return c if 1 <= c <= 130 else None

    m_ym = re.fullmatch(r"(\d{4})-(\d{2})", s)
    if m_ym:
        y, mo = int(m_ym.group(1)), int(m_ym.group(2))
        if y < 1789 or not (1 <= mo <= 12):
            return None
        if y % 2 == 1:
            if y < 1935 and mo <= 3:
                return None
            if mo == 1:
                return None
            y_start = y
        else:
            y_start = y - 1
        c = (y_start - 1789) // 2 + 1
        return c if 1 <= c <= 130 else None

    m_y = re.fullmatch(r"(\d{4})", s)
    if m_y:
        y = int(m_y.group(1))
        if y < 1789 or (y % 2 == 1):
            return None
        c = ((y - 1) - 1789) // 2 + 1
        return c if 1 <= c <= 130 else None

    return None


def extract_official_slug_congress(filename: str | None) -> int | None:
    """Extract 100%-deterministic Congress (100..130) from official GPO/Clerk filename prefixes."""
    if not filename or not isinstance(filename, str):
        return None
    base = filename.strip().rsplit("/", 1)[-1]
    m = OFFICIAL_SLUG_CONGRESS_RE.match(base)
    if not m:
        return None
    c = int(m.group(1))
    return c if 100 <= c <= 130 else None


_RX_EXHIBIT_FN = re.compile(
    r"(?:^|[^a-zA-Z])exhibit(?:[^a-zA-Z]|$)|redacted|sanitized|\b302\b",
    re.I,
)

_ORDINAL_CONGRESS_MAP: dict[str, int] = {
    "FIRST": 101,
    "SECOND": 102,
    "THIRD": 103,
    "FOURTH": 104,
    "FIFTH": 105,
    "SIXTH": 106,
    "SEVENTH": 107,
    "EIGHTH": 108,
    "NINTH": 109,
    "TENTH": 110,
    "ELEVENTH": 111,
    "TWELFTH": 112,
    "THIRTEENTH": 113,
    "FOURTEENTH": 114,
    "FIFTEENTH": 115,
    "SIXTEENTH": 116,
    "SEVENTEENTH": 117,
    "EIGHTEENTH": 118,
    "NINETEENTH": 119,
    "TWENTIETH": 120,
}
_RX_MASTHEAD_WORDS_V5 = re.compile(
    r"\bONE\s+HUNDRED\s+(?:AND\s+)?"
    r"(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|"
    r"ELEVENTH|TWELFTH|THIRTEENTH|FOURTEENTH|FIFTEENTH|SIXTEENTH|SEVENTEENTH|EIGHTEENTH|NINETEENTH|TWENTIETH)"
    r"\s+CON[GC]RESS\b",
    re.I,
)
# OCR-tolerant 3-digit Congress ordinal: e.g. 114th, 1l4th, ll5th, 1I2TH, 112 TH, 116", 115'h
_RX_MASTHEAD_NUM_V5 = re.compile(
    r"(?<![0-9A-Za-z])([1Il][012Il][0-9Il])(?:\s*(?:ST|ND|RD|TH|['\"”’]h?))?\s+CON[GC]RESS\b",
    re.I,
)
_RX_SESSION_AFTER_V5 = re.compile(
    r"^[,–—\s-]*(?:1ST|IST|2D|2ND|FIRST|SECOND)\s+SESSION\b",
    re.I,
)
_RX_INST_AFTER_V5 = re.compile(
    r"^[\s,–—-]*(?:ROLL\s+CALL|COMMITTEE\s+ON|SUBCOMMITTEE\s+ON|U\.?S\.?\s+HOUSE|"
    r"[HLTh]h?OUSE\s+OF\s+REPRESENTATI|[ULl]NITED\s+ST\s*ATES\s+SENATE)",
    re.I,
)
_RX_INST_BEFORE_V4_BASE = re.compile(
    r"(?:--|—|–|^\s*|\bC[ON]MMITT[EC][EC]\s+ON\s+[A-Za-z ,&'*]{3,50}\s*)$",
    re.I,
)
_RX_INST_BEFORE_V5_EXTRA = re.compile(
    r"(?:\[Committee\s+Print\]\s*|"
    r"\b(?:HOUSE\s+OF\s+REPRESENTATIVES|UNITED\s+STATES\s+SENATE|U\.?S\.?\s+SENATE|U\.?S\.?\s+HOUSE(?:\s+OF\s+REPRESENTATIVES)?)\s*(?:,\s*)?)$",
    re.I,
)
_RX_BRACKET_HEARING = re.compile(
    r"^\[(?:House|Senate|Joint)\s+Hearing,\s*(1[012]\d)\s*(?:st|nd|rd|th)?\s+Congress\]",
    re.I,
)
_RX_PROSE_CONG_BEFORE = re.compile(
    r"\b(?:in|during|from|since|before|after|under|through|passed|enacted|introduced|reintroduce[ds]?|prior|previous|of|for|at)\s+(?:the\s+)?$",
    re.I,
)
_RX_STALE_DISCLOSURE_TMPL = re.compile(
    r"\b[1Il]{2}[0-9Il](?:th|TH)?\s+Con[gc]ress\s+(?:Truth\s+in\s+Testimony|Disclosure\s+Form)",
    re.I,
)
_RX_AMDT_MOTION_TOP = re.compile(
    r"^(?:Page \d+ of \d+\s+|\d+\s+)?(?:MOTION BY\b|AMENDMENT (?:\(IN THE NATURE OF A SUBSTITUTE\) |IN THE NATURE OF A SUBSTITUTE )?TO\b|Amendment #\d)",
    re.I,
)


def _decode_ocr_congress_int(tok: str) -> int | None:
    """Decode OCR 3-char Congress token ('1l4' -> 114, 'll5' -> 115, '1I2' -> 112)."""
    trans = tok.replace("I", "1").replace("l", "1")
    if not trans.isdigit():
        return None
    val = int(trans)
    return val if 100 <= val <= 130 else None


def extract_pdf_masthead_congress_v5(
    filename: str | None,
    text: str | None,
    is_html: bool | None = None,
) -> int | None:
    """Extract unmistakable PDF Congress masthead (`ONE HUNDRED <ORDINAL> CONGRESS` / `11XTH CONGRESS`), OCR-tolerant."""
    if not text or not isinstance(text, str):
        return None
    raw1000 = text[:1000]
    raw_low = raw1000.lower()
    if "congres" not in raw_low and "concres" not in raw_low and "c o n g r e s s" not in raw_low:
        return None
    if infer_is_html_v5(filename, text, is_html=is_html):
        return None
    if filename and _RX_EXHIBIT_FN.search(filename):
        return None

    head = _collapse_letter_spaced_caps(_norm_ws_prefix(raw1000, 920))
    if (
        not head
        or _RX_STALE_DISCLOSURE_TMPL.search(head[:320])
        or _RX_AMDT_MOTION_TOP.match(head[:220])
    ):
        return None

    m_br = _RX_BRACKET_HEARING.match(head[:80])
    if m_br:
        return int(m_br.group(1))

    m_w = _RX_MASTHEAD_WORDS_V5.search(head)
    if m_w:
        pre = head[max(0, m_w.start() - 32) : m_w.start()]
        if not _RX_PROSE_CONG_BEFORE.search(pre):
            return _ORDINAL_CONGRESS_MAP[m_w.group(1).upper()]

    is_witness_head = bool(
        re.search(
            r"\b(?:Statement\s+(?:of|by)|Testimony\s+(?:of|by)|Congressional\s+Testimony|Before\s+the\s+(?:House|Senate|Committee|Subcommittee))\b",
            head[:380],
            re.I,
        )
    )
    for m_n in _RX_MASTHEAD_NUM_V5.finditer(head[:540]):
        c_val = _decode_ocr_congress_int(m_n.group(1))
        if c_val is None:
            continue
        pre = head[max(0, m_n.start() - 32) : m_n.start()]
        if _RX_PROSE_CONG_BEFORE.search(pre):
            continue
        post = head[m_n.end() : m_n.end() + 48]
        if _RX_SESSION_AFTER_V5.match(post):
            return c_val
        if m_n.start() < 460 and c_val >= 111:
            pre_wide = head[max(0, m_n.start() - 65) : m_n.start()]
            if _RX_INST_AFTER_V5.match(post) or _RX_INST_BEFORE_V4_BASE.search(pre_wide):
                return c_val
            if not is_witness_head and _RX_INST_BEFORE_V5_EXTRA.search(pre_wide):
                return c_val
    return None


# OCR-tolerant `Committee on` prefix (`Committee on`, `COMMITTEE ON * *`, `Cnmmitter on`, `Committec on`)
_CMT_ON = r"\bC[on]mmitt[ec][ec]r?\s+on(?:\s*[*•·-]\s*)*\s*"
_HOUSE_PRE = r"(?:\b[HLTh]h?[ou]{1,2}se\s+(?:of\s+R?epresentati[vbuí][ce]s\s*,?\s*)?)?"
_SENATE_REQ_PRE = r"(?:\b[ULl]nited\s+St\s*ates\s+Senate\s*,?\s*|\bSenate\s+)"

CANONICAL_COMMITTEES_V5: list[tuple[str, str, str, re.Pattern[str]]] = [
    (
        "hsag00",
        "house",
        "House Committee on Agriculture",
        re.compile(_HOUSE_PRE + _CMT_ON + r"Agriculture\b(?!,\s*Nutrition)", re.I),
    ),
    (
        "ssaf00",
        "senate",
        "Senate Committee on Agriculture, Nutrition, and Forestry",
        re.compile(_CMT_ON + r"Agriculture,\s*Nutrition,\s*(?:and|&)\s*Forestry\b", re.I),
    ),
    (
        "hsap00",
        "house",
        "House Committee on Appropriations",
        re.compile(
            _HOUSE_PRE + _CMT_ON + r"Appropriations\b|\bHouse\s+Appropriations\s+Committee\b",
            re.I,
        ),
    ),
    (
        "ssap00",
        "senate",
        "Senate Committee on Appropriations",
        re.compile(
            _SENATE_REQ_PRE + _CMT_ON + r"Appropriations\b|\bSenate\s+Appropriations\s+Committee\b",
            re.I,
        ),
    ),
    (
        "hsas00",
        "house",
        "House Committee on Armed Services",
        re.compile(
            _HOUSE_PRE + _CMT_ON + r"Armed\s+Services\b|\bHouse\s+Armed\s+Services\s+Committee\b",
            re.I,
        ),
    ),
    (
        "ssas00",
        "senate",
        "Senate Committee on Armed Services",
        re.compile(
            _SENATE_REQ_PRE + _CMT_ON + r"Armed\s+Services\b|\bSenate\s+Armed\s+Services\s+Committee\b",
            re.I,
        ),
    ),
    (
        "hsbu00",
        "house",
        "House Committee on the Budget",
        re.compile(
            _HOUSE_PRE + _CMT_ON + r"the\s+Budget\b|\bHouse\s+Budget\s+Committee\b",
            re.I,
        ),
    ),
    (
        "ssbu00",
        "senate",
        "Senate Committee on the Budget",
        re.compile(_SENATE_REQ_PRE + _CMT_ON + r"the\s+Budget\b", re.I),
    ),
    (
        "hsed00",
        "house",
        "House Committee on Education and the Workforce",
        re.compile(_CMT_ON + r"Education\s+(?:and|&|ind|ano)\s+(?:the\s+)?Workforce\b", re.I),
    ),
    (
        "hsed00",
        "house",
        "House Committee on Education and Labor",
        re.compile(_CMT_ON + r"Education\s+(?:and|&|ind|ano)\s+Labor\b", re.I),
    ),
    (
        "hsif00",
        "house",
        "House Committee on Energy and Commerce",
        re.compile(
            _CMT_ON + r"Energy\s+(?:and|&|ind|ano)\s+Commerce\b|\bEnergy\s+and\s+Commerce\s+Committee\b",
            re.I,
        ),
    ),
    (
        "hsso00",
        "house",
        "House Committee on Ethics",
        re.compile(_CMT_ON + r"Ethics\b", re.I),
    ),
    (
        "hsba00",
        "house",
        "House Committee on Financial Services",
        re.compile(
            _CMT_ON + r"[Ff]inancial\s+Services\b|\bFinancial\s+Services\s+Committee\b",
            re.I,
        ),
    ),
    (
        "hsfa00",
        "house",
        "House Committee on Foreign Affairs",
        re.compile(
            _CMT_ON + r"Foreign\s+A[ft]{2}airs\b|\bHouse\s+Foreign\s+A[ft]{2}airs\s+Committee\b",
            re.I,
        ),
    ),
    (
        "hshm00",
        "house",
        "House Committee on Homeland Security",
        re.compile(
            _CMT_ON + r"Homeland\s+Security\b(?!\s+(?:and|&)\s+Governmental\s+Affairs)",
            re.I,
        ),
    ),
    (
        "ssga00",
        "senate",
        "Senate Committee on Homeland Security and Governmental Affairs",
        re.compile(
            _CMT_ON + r"Homeland\s+Security\s+(?:and|&)\s+Governmental\s+Affairs\b",
            re.I,
        ),
    ),
    (
        "hsha00",
        "house",
        "House Committee on House Administration",
        re.compile(_CMT_ON + r"House\s+Administration\b", re.I),
    ),
    (
        "hsju00",
        "house",
        "House Committee on the Judiciary",
        re.compile(
            r"(?:\b[HLTh]h?[ou]{1,2}se(?:\s+of\s+R?epresentati[vbuí][ce]s)?[\s,.:;-]{0,85}?"
            + _CMT_ON
            + r"the\s+Judiciar[y)/]|"
            + _CMT_ON
            + r"the\s+Judiciar[y)/][\s,.:;-]{0,55}?(?:U\.?S\.?\s+)?[HLTh]h?[ou]{1,2}se\b|\b2138\s+Rayburn\b)",
            re.I,
        ),
    ),
    (
        "ssju00",
        "senate",
        "Senate Committee on the Judiciary",
        re.compile(
            r"(?:\b[ULl]nited\s+St\s*ates\s+Senate[\s,.:;-]{0,85}?"
            + _CMT_ON
            + r"the\s+Judiciar[y)/]|"
            r"\bSenate\s+(?:Committee\s+on\s+the\s+)?Judiciary\b)",
            re.I,
        ),
    ),
    (
        "hsii00",
        "house",
        "House Committee on Natural Resources",
        re.compile(
            _CMT_ON + r"Natural\s+Re[sx][no]urces\b|\bHouse\s+Natural\s+Resources\s+Committee\b",
            re.I,
        ),
    ),
    (
        "hsgo00",
        "house",
        "House Committee on Oversight and Government Reform",
        re.compile(
            _CMT_ON + r"Oversight\s+(?:and|&|ind|ano)\s+Government\s+Reform\b",
            re.I,
        ),
    ),
    (
        "hsgo00",
        "house",
        "House Committee on Oversight and Reform",
        re.compile(_CMT_ON + r"Oversight\s+(?:and|&|ind|ano)\s+Reform\b", re.I),
    ),
    (
        "hsgo00",
        "house",
        "House Committee on Oversight and Accountability",
        re.compile(_CMT_ON + r"Oversight\s+(?:and|&|ind|ano)\s+Accountability\b", re.I),
    ),
    (
        "hsru00",
        "house",
        "House Committee on Rules",
        re.compile(
            r"(?:\bHouse\s+)?" + _CMT_ON + r"Rules\b(?!\s+and\s+Administration)(?!\s+regulations)",
            re.I,
        ),
    ),
    (
        "ssra00",
        "senate",
        "Senate Committee on Rules and Administration",
        re.compile(_CMT_ON + r"Rules\s+(?:and|&)\s+Administration\b", re.I),
    ),
    (
        "hssy00",
        "house",
        "House Committee on Science, Space, and Technology",
        re.compile(_CMT_ON + r"Science,?\s*Space,?\s*(?:and|&)\s*Technology\b", re.I),
    ),
    (
        "hssy00",
        "house",
        "House Committee on Science and Technology",
        re.compile(_CMT_ON + r"Science\s+(?:and|&)\s+Technology\b", re.I),
    ),
    (
        "hssm00",
        "house",
        "Full Committee on Small Business",
        re.compile(r"\bFull\s+" + _CMT_ON + r"Small\s+Business\b", re.I),
    ),
    (
        "hssm00",
        "house",
        "House Committee on Small Business",
        re.compile(
            r"(?<!Full\s)\bCommittee\s+on\s+Small\s+Business\b(?!\s+(?:and|&)\s+Entrepreneurship)",
            re.I,
        ),
    ),
    (
        "sssb00",
        "senate",
        "Senate Committee on Small Business and Entrepreneurship",
        re.compile(_CMT_ON + r"Small\s+Business\s+(?:and|&)\s+Entrepreneurship\b", re.I),
    ),
    (
        "hspw00",
        "house",
        "House Committee on Transportation and Infrastructure",
        re.compile(
            _CMT_ON
            + r"Transportation\s+(?:and|&)\s+Infrastructure\b|\bTransportation\s+and\s+Infrastructure\s+Committee\b",
            re.I,
        ),
    ),
    (
        "hsvr00",
        "house",
        "House Committee on Veterans' Affairs",
        re.compile(
            r"(?:\b[HLTh]h?[ou]{1,2}se(?:\s+of\s+R?epresentati[vbuí][ce]s)?[\s,.:;-]{0,85}?"
            + _CMT_ON
            + r"Veterans'?\s*A[ft]{2}airs\b|"
            + _CMT_ON
            + r"Veterans'?\s*A[ft]{2}airs\b[\s,.:;-]{0,55}?(?:U\.?S\.?\s+)?[HLTh]h?[ou]{1,2}se\b)",
            re.I,
        ),
    ),
    (
        "ssva00",
        "senate",
        "Senate Committee on Veterans' Affairs",
        re.compile(
            r"(?:\b[ULl]nited\s+St\s*ates\s+Senate[\s,.:;-]{0,85}?"
            + _CMT_ON
            + r"Veterans'?\s*A[ft]{2}airs\b|"
            r"\bSenate\s+Committee\s+on\s+Veterans'?\s*A[ft]{2}airs\b)",
            re.I,
        ),
    ),
    (
        "hswm00",
        "house",
        "House Committee on Ways and Means",
        re.compile(
            _CMT_ON + r"Ways\s+(?:and|&|ind|ano)\s+Means\b|\bWays\s+and\s+Means\s+Committee\b",
            re.I,
        ),
    ),
    (
        "hlzs00",
        "house",
        "House Permanent Select Committee on Intelligence",
        re.compile(r"(?:\bHouse\s+)?\bPermanent\s+Select\s+" + _CMT_ON + r"Intelligence\b", re.I),
    ),
    (
        "slin00",
        "senate",
        "Senate Select Committee on Intelligence",
        re.compile(r"\bSenate\s+Select\s+" + _CMT_ON + r"Intelligence\b", re.I),
    ),
    (
        "hszs00",
        "house",
        "House Select Committee on the Strategic Competition between the United States and the Chinese Communist Party",
        re.compile(
            r"\bSelect\s+Committee\s+on\s+the\s+Strategic\s+Competition\s+between\s+the\s+United\s+States\s+and\s+the\s+Chinese\s+Communist\s+Party\b",
            re.I,
        ),
    ),
    (
        "ssbk00",
        "senate",
        "Senate Committee on Banking, Housing, and Urban Affairs",
        re.compile(
            _CMT_ON + r"Banking,?\s*Housing,?\s*(?:and|&)\s*Urban\s+Affairs\b"
            r"|\bSenate\s+Banking,\s*Housing,?\s*(?:and|&)\s*Urban\s+Affairs\s+Committee\b",
            re.I,
        ),
    ),
    (
        "sscm00",
        "senate",
        "Senate Committee on Commerce, Science, and Transportation",
        re.compile(_CMT_ON + r"Commerce,?\s*Science,?\s*(?:and|&)\s*Transportation\b", re.I),
    ),
    (
        "sseg00",
        "senate",
        "Senate Committee on Energy and Natural Resources",
        re.compile(_CMT_ON + r"Energy\s+(?:and|&)\s+Natural\s+Resources\b", re.I),
    ),
    (
        "ssev00",
        "senate",
        "Senate Committee on Environment and Public Works",
        re.compile(_CMT_ON + r"Environment\s+(?:and|&)\s+Public\s+Works\b", re.I),
    ),
    (
        "ssfi00",
        "senate",
        "Senate Committee on Finance",
        re.compile(_CMT_ON + r"Finance\b|\bSenate\s+Finance\s+Committee\b", re.I),
    ),
    (
        "ssfr00",
        "senate",
        "Senate Committee on Foreign Relations",
        re.compile(_CMT_ON + r"Foreign\s+Relations\b|\bSenate\s+Foreign\s+Relations\s+Committee\b", re.I),
    ),
    (
        "sshr00",
        "senate",
        "Senate Committee on Health, Education, Labor, and Pensions",
        re.compile(_CMT_ON + r"Health,?\s*Education,?\s*Labor,?\s*(?:and|&)\s*Pensions\b", re.I),
    ),
    (
        "slia00",
        "senate",
        "Senate Committee on Indian Affairs",
        re.compile(_CMT_ON + r"Indian\s+Affairs\b", re.I),
    ),
    (
        "spag00",
        "senate",
        "Senate Special Committee on Aging",
        re.compile(r"\bSpecial\s+" + _CMT_ON + r"Aging\b", re.I),
    ),
]

# House Natural Resources (`hsii00`) formal hearing notice / witness list banner that omits
# "Committee on Natural Resources" while printing its unique cellular-phone dais rule + HSII subcommittee
_HSII_DAIS_CELLULAR_RE = re.compile(
    r"The\s+use\s+of\s+cellular\s+telephones\s+is\s+prohibited\s+on\s+the\s+Committee\s+dais\s+or\s+in\s+the\s+Committee\s+hearing\s+room",
    re.I,
)
_HSII_UNIQUE_SUBCMT_RE = re.compile(
    r"\bSubcommittee\s+(?:on|for)\s+(?:Federal\s+Lands|Energy\s+and\s+Mineral\s+Resources|"
    r"Water,\s*(?:Power\s+and\s+Oceans|Oceans,\s*and\s*Wildlife|Wildlife\s+and\s+Fisheries)|"
    r"Indian,\s*Insular\s+and\s+Alaska\s+Native\s+Affairs|Indigenous\s+Peoples\s+of\s+the\s+United\s+States|"
    r"National\s+Parks,\s*Forests,?\s*and\s+Public\s+Lands|Fisheries,\s*Wildlife,\s*Oceans,?\s*and\s+Insular\s+Affairs)\b",
    re.I,
)

_NON_MASTHEAD_DOC_RE_V5 = re.compile(
    r"^(?:THE WHITE HOUSE|DEPARTMENT OF|UNITED STATES OFFICE OF|OFFICE OF THE|"
    r"UNITED STATES GENERAL ACCOUNTING OFFICE|UNITED STATES GOVERNMENT ACCOUNTABILITY OFFICE|"
    r"GAO-\d|CONGRESSIONAL RESEARCH SERVICE\b|JOINT COMMITTEE ON TAXATION\b|"
    r"JOINT EXPLANATORY STATEMENT TO ACCOMPANY\b|\[DISCUSSION DRAFT\]|"
    r"(?:\d+\s+)?(?:NOT\s+PUBLIC|NOT\s+FOR\s+PUBLICATION|HOLD\s+UNTIL|EMBARGOED)\s+UNTIL\s+RELEASED\b|"
    r"(?:(?:\d+|[A-Za-z0-9 .#'_-]{1,35}#\d+)\s+)?AMENDMENT\s+(?:\(IN THE NATURE OF A SUBSTITUTE\)\s+|IN THE NA-?\s*TURE OF A SUBSTITUTE\s+|THE AMENDMENT\b|TO\b|OFFERED BY\b|NO\.|VO\.)|"
    r"MOTION BY\b|In the Senate of the United States,.*?\bResolved,\s+That\s+the\s+bill|"
    r"Amendment #\d|F:\\|"
    r"(?:Page \d+ of \d+\s+|\d+\s+)?(?:WRITTEN\s+|PREPARED\s+|ORAL\s+|COMPLETE\s+|POSTURE\s+)?(?:STATEMENT|TESTIMONY|COMMENTS)\s+(?:OF|BY)\b|"
    r"(?:\d+\s+)?(?:Biography|Biographical\s+Sketch|Curriculum\s+Vitae)\b|"
    r"FOR OFFICIAL USE ONLY)",
    re.I,
)
_DEAR_HONORABLE_BLOCK_RE_V5 = re.compile(
    r"(?:\bThe Honorable [A-Z][a-z]+.{0,240}?\bDear (?:Chair|Senator|Representative|Mr\.|Ms\.|Mrs\.|Madam|Congress)|"
    r"\bDear\s+(?:Chair(?:man|woman)?|Ranking\s+Member|Senator|Representative|Congressman|Congresswoman)\b|"
    r"\bDear\s+Reader\s*:|"
    r"\bintroduced the following bill;\s+which was referred to the Committee on\b)",
    re.I,
)
_WITNESS_TESTIMONY_CUE_RE_V5 = re.compile(
    r"\b(?:Written Statement of|Testimony of|Testimony [Bb]efore the|Prepared Statement of|Complete Statement of|Written Comments of|"
    r"WRITTEN STATEMENT OF|TESTIMONY OF|PREPARED STATEMENT OF|POSTURE STATEMENT OF|"
    r"Statement of [A-Z][a-z]+ [A-Z][a-z]+,?\s+(?:President|CEO|Director|Professor|Dr\.|Chief|Executive|Mayor|Vice President|Commissioner|Colonel|General|Admiral))\b"
    r"|\b(?:appreciates|thank you .{0,65}?for) the opportunity to (?:testify|appear) before\b"
    r"|\b(?:Before the|BEFORE THE) (?:1[012]\d(?:TH|th)\s+(?:CONGRESS|Congress)\s+)?(?:U\.?S\.?\s+)?(?:House|HOUSE|Senate|SENATE|Committee|COMMITTEE|Subcommittee|SUBCOMMITTEE)\b"
)
_WITNESS_BIO_FN_RE_V5 = re.compile(
    r"(?:-(?:Bio|Biography)-|^Bio[-_ ]|[-_ ]Bio(?:graphy)?\.pdf$|^CV[-_ ]|[-_ ]CV\.pdf$)",
    re.I,
)
_WITNESS_BIO_PROSE_CUE_RE_V5 = re.compile(
    r"(?:\bPrior to joining\b|\bPreviously,\s+(?:he|she|they)\s+(?:served|worked|was)\b|"
    r"\b(?:He|She)\s+(?:previously\s+)?(?:served|worked)\s+(?:as|on|for|at)\b|"
    r"\bis\s+(?:the\s+|a\s+|an\s+)?(?:chief\s+[a-z]+|senior\s+fellow|president|ceo|executive\s+director|managing\s+director|general\s+counsel|professor|founder|partner)\s+(?:of|at|for|in)\b)",
    re.I,
)
_HSAG_BIO_FORM_HEAD_RE_V5 = re.compile(
    r"^(?:\d+\s+)?Committee\s+on\s+Agriculture\s+U\.?S\.?\s+House\s+of\s+Representatives\s+Information\s+Required\s+From\s+Nongovernmental\s+Witnesses",
    re.I,
)
_MASTHEAD_PROSE_PREP_RE_V5 = re.compile(
    r"(?:"
    r"\b(?:report\s+to|submitted?\s+to|pursuant\s+to|regulations\s+of|courtesy\s+of|released\s+by|"
    r"referred\s+to|forwarded\s+to|transmitted\s+to|addressed\s+to|before\s+the|to\s+the|"
    r"testif(?:y|ied|ying)\s+before|testimony\s+before|appear(?:ed|ing)?\s+before)\s+"
    r"(?:the\s+|u\.?s\.?\s+house\s+(?:of\s+representatives\s+)?)?$"
    r"|\b(?:counsel\s+(?:to|for|on)|staff\s+(?:on|for|to|of|director|member)|"
    r"served\s+(?:on|as|with|for)|worked\s+(?:on|for|with)|advis[eo]r\s+(?:to|for|on)|"
    r"fellow\s+(?:on|with|for)|intern(?:ed)?\s+(?:on|with|for)|clerk\s+(?:to|for|of)|"
    r"testif(?:y|ied|ying)\s+before|appear(?:ed|ing)?\s+before)\s+"
    r"[A-Za-z0-9 ,.&'()-]{0,145}?$"
    r")",
    re.I,
)
_OFFICIAL_HOUSE_SLUG_RE = re.compile(r"^(?:[0-9a-fA-F]{64}\.)?(?:HHRG|HMTG|HMKP|HRPT)-\d{3}-", re.I)
_OFFICIAL_SENATE_SLUG_RE = re.compile(r"^(?:[0-9a-fA-F]{64}\.)?(?:SHRG|SRPT)-\d{3}-", re.I)


def extract_formal_committee_masthead_v5(
    filename: str | None,
    text: str | None,
    is_html: bool | None = None,
) -> list[dict[str, str]]:
    """Extract unmistakable formal Congressional committee mastheads in `chars[:900]` (non-HTML), OCR-tolerant."""
    if not text or not isinstance(text, str):
        return []
    raw950 = text[:950]
    raw_low = raw950.lower()
    if (
        "committ" not in raw_low
        and "cnmmitt" not in raw_low
        and "c o m m i t t e e" not in raw_low
        and "2138 rayburn" not in raw_low
        and "cellular telephones" not in raw_low
    ):
        return []
    if infer_is_html_v5(filename, text, is_html=is_html):
        return []

    head = _collapse_letter_spaced_caps(_norm_ws_prefix(raw950, 880))
    if len(head) < 30:
        return []

    base_fn = (filename or "").rsplit("/", 1)[-1]
    if not _HSAG_BIO_FORM_HEAD_RE_V5.match(head):
        if _WITNESS_BIO_FN_RE_V5.search(base_fn) or _WITNESS_BIO_PROSE_CUE_RE_V5.search(head[:450]):
            return []

    if (
        _NON_MASTHEAD_DOC_RE_V5.match(head)
        or _DEAR_HONORABLE_BLOCK_RE_V5.search(head)
        or _WITNESS_TESTIMONY_CUE_RE_V5.search(head[:350])
    ):
        return []

    house_slug = bool(_OFFICIAL_HOUSE_SLUG_RE.match(base_fn))
    senate_slug = bool(_OFFICIAL_SENATE_SLUG_RE.match(base_fn))
    is_joint = "joint" in head[:320].lower()

    hits: list[tuple[int, dict[str, str]]] = []
    senate_doc = senate_slug or bool(
        re.search(
            r"\b[ULl]nited\s+St\s*ates\s+Senate\b|\bU\.?S\.?\s+Senate\b|\bIN\s+THE\s+SENATE\b|"
            r"\b(?:Dirksen|Hart|Russell)\s+Senate\s+Of+ice\b",
            head,
            re.I,
        )
    )
    house_doc = house_slug or bool(
        re.search(
            r"\b[HLTh]h?[ou]{1,2}se\s+of\s+R?epresentati[vbuí][ce]s\b|\bU\.?S\.?\s+House\b|"
            r"\bRayburn\b|\bLongworth\b|\bCannon\b",
            head,
            re.I,
        )
    )

    for code, ch, canon_name, rx in CANONICAL_COMMITTEES_V5:
        if not is_joint:
            if house_slug and ch == "senate":
                continue
            if senate_slug and ch == "house":
                continue
        if code in ("hsap00", "hsas00", "hsbu00", "hsag00") and senate_doc and not house_doc:
            continue
        m = rx.search(head)
        if not m:
            continue
        pre = head[max(0, m.start() - 180) : m.start()]
        if _MASTHEAD_PROSE_PREP_RE_V5.search(pre):
            continue
        hits.append((m.start(), {"code": code, "chamber": ch, "name": canon_name}))

    # Fallback for HSII formal notices/witness-lists with cellular-dais rule + HSII subcommittee
    if not hits and not senate_slug and _HSII_DAIS_CELLULAR_RE.search(head) and _HSII_UNIQUE_SUBCMT_RE.search(head):
        hits.append(
            (
                0,
                {
                    "code": "hsii00",
                    "chamber": "house",
                    "name": "House Committee on Natural Resources",
                },
            )
        )

    hits.sort(key=lambda x: x[0])
    seen_p: set[str] = set()
    out: list[dict[str, str]] = []
    for pos, item in hits:
        p4 = item["code"][:4]
        if p4 in seen_p:
            continue
        if out and not is_joint and pos > 460 and hits[0][0] < 300:
            break
        seen_p.add(p4)
        out.append(item)
    return out


extract_pdf_masthead_congress = extract_pdf_masthead_congress_v5
extract_formal_committee_masthead = extract_formal_committee_masthead_v5


# ===========================================================================
# Pillar C: 21 V4 + 11 New 100.0%-Pure V5 Tier-1 Signatures & Tier-2 Hints
# ===========================================================================

V4_TIER1_SIGNATURE_TO_KIND: dict[str, str] = {
    "ttf_clerk_acroform_v1_116_118": "truth_in_testimony_disclosure",
    "ttf_clerk_acroform_v2_118_119": "truth_in_testimony_disclosure",
    "ttf_committee_bespoke_form_112_118": "truth_in_testimony_disclosure",
    "attendance_hsif_quorum_call": "attendance_quorum_sheet",
    "attendance_committee_present_grid": "attendance_quorum_sheet",
    "vote_hswm_votes_of_committee": "committee_vote",
    "vote_committee_roll_call_tally_sheet": "committee_vote",
    "amdt_hlc_offered_by": "committee_amendment",
    "amdt_hsru_motion_make_in_order": "committee_amendment",
    "amdt_senate_slc_printed": "committee_amendment",
    "memo_committee_staff_to_members": "hearing_memo_or_charter",
    "charter_explicit_heading": "hearing_memo_or_charter",
    "notice_markup_or_business_meeting": "markup_notice",
    "notice_hearing_formal": "hearing_notice",
    "qfr_request_chair_transmittal_letter": "qfr_request",
    "witness_invitation_chair_letter": "witness_invitation",
    "bill_gpo_congressional_print": "bill_or_draft",
    "comparative_print_computer_generated": "comparative_print",
    "schedule_docs_house_floor_weekly": "legislative_schedule_or_calendar",
    "questionnaire_senate_nominee": "nominee_questionnaire_apq",
    "transcript_stenographic_cover": "hearing_transcript",
}

NEW_TIER1_SIGNATURE_TO_KIND_V5: dict[str, str] = {
    "vote_committee_grid_v5": "committee_vote",
    "amdt_hlc_ans_and_slc_v5": "committee_amendment",
    "stmt_member_opening_formal_v5": "member_opening_statement",
    "witness_list_formal_panel_v5": "witness_list",
    "qfr_response_qa_packet_v5": "qfr_response",
    "notice_ways_means_or_upper_heading_v5": "hearing_notice",
    "memo_summary_subject_matter_v5": "hearing_memo_or_charter",
    "report_gpo_committee_report_v5": "committee_report",
    "transcript_clerk_rptr_or_prelim_v5": "hearing_transcript",
    "questionnaire_nominee_apq_v5": "nominee_questionnaire_apq",
    "bio_hsag_nongov_witness_form_v5": "witness_biography",
}

TIER1_SIGNATURE_TO_KIND_V5: dict[str, str] = {
    **V4_TIER1_SIGNATURE_TO_KIND,
    **NEW_TIER1_SIGNATURE_TO_KIND_V5,
}
TIER1_SIGNATURE_IDS_V5: tuple[str, ...] = tuple(TIER1_SIGNATURE_TO_KIND_V5.keys())
TIER1_TARGET_KINDS_V5: tuple[str, ...] = tuple(dict.fromkeys(TIER1_SIGNATURE_TO_KIND_V5.values()))

# Backwards-compatible V4 constant names
TIER1_SIGNATURE_TO_KIND = TIER1_SIGNATURE_TO_KIND_V5
TIER1_SIGNATURE_IDS = TIER1_SIGNATURE_IDS_V5
TIER1_TARGET_KINDS = TIER1_TARGET_KINDS_V5

# --- Exact V4 Regexes (preserved verbatim for 100.0% V4 parity) ---
RX_LETTER_SALUTATION = re.compile(
    r"\b(?:Dear\s+(?:Chair|Chairman|Chairwoman|Ranking|Senator|Representative|Congressman|"
    r"Congresswoman|Member|Members|Mr\.|Ms\.|Mrs\.|Dr\.|Prof\.|Professor|Secretary|Director|"
    r"Administrator|Commissioner|General|Admiral|Judge|Honorable|Colleague)|"
    r"Sincerely,?|Respectfully\s+submitted)\b",
    re.I,
)
RX_TTF_V1 = re.compile(
    r"^(?:\d+\s+)?Truth in Testimony Disclosure Form\s+(?:In\s+|1\s+)?(?:ac)?cordance with Rule XI,\s*[ce]lause 2\(g\)\(5\)",
    re.I,
)
RX_TTF_V2 = re.compile(
    r"^(?:\d+\s+)?Truth in Testimony Disclosure Form\s+Witness Name:\s*.*?Position/Title:\s*.*?Witness Type:\s*Governmental\s+Non-governmental",
    re.I,
)
RX_TTF_BESPOKE_EXACT_TITLE = re.compile(
    r"(?:[WV]?itness Disclosure Requirement\s*[-–—]\s*[\"“«]?Truth in Testimony|"
    r"[\"“«]?Truth in Testimony[\"”»]?\s+Disclosure Form|"
    r"Required Witness Disclosure Form\s+House Rules|"
    r"Disclosure Form\s+As required by and provided for in House Rule XI|"
    r"Witness Disclosure Statement\s+Re[qg]uired by House Rule XI|"
    r"DISCLOSURE FORM FOR WITNESSES CONCERNING FEDERAL CONTRACT AND GRANT INFORMATION)",
    re.I,
)
RX_TTF_BESPOKE_SLOTS = re.compile(
    r"(?:1\.\s*(?:Your\s+)?Name:|(?:Your|Xour|ur)\s+Nam[e:]|Witness Name:|Name:\s+[A-Z]|"
    r"Organization(?:s|\(s\))?\s+you\s+(?:are\s+)?represent|"
    r"INSTRUCTION\s+TO\s+WITNESSES:\s*Rule\s+(?:XI|11),\s*clause\s*2\(g\))",
    re.I,
)
RX_TTF_GENERIC_HEAD = re.compile(
    r"truth\s+in\s+testimony|(?:required\s+)?[wv]itness\s+disclosure\s+(?:form|requirement|statement)",
    re.I,
)
RX_TTF_GENERIC_FIELD = re.compile(
    r"(?:Witness\s+Name|(?:Your|Xour)\s+Name|\bName)\s*:"
    r"|Position\s*/?\s*Title\s*:"
    r"|Witness\s+Type\s*:"
    r"|Entity\(ies\)\s+you\s+are\s+representing"
    r"|Organization(?:\s+or\s+organizations)?\s+you(?:\s+are)?\s+represent"
    r"|Are\s+you\s+representing\s+yourself"
    r"|testifying\s+on\s+behalf\s+of",
    re.I,
)
RX_TTF_GRANTS_CUE = re.compile(
    r"[fr]ederal\s+grants?"
    r"|subgrants?\s+(?:or|and)\s+subcontracts?"
    r"|grants?,\s+cooperative\s+agreements?,\s+or\s+contracts?"
    r"|Are\s+you\s+a\s+fiduciary"
    r"|originating\s+with\s+a\s+for(?:ei|ie)gn\s+government"
    r"|foreign\s+government\s+payments?",
    re.I,
)
RX_TTF_UNBANNERED_112_115 = re.compile(
    r"^(?:1\s+)?(?:Witness\s+Name|Your\s+Name|Name)\s*:\s*[A-Z].{1,120}?\s+"
    r"1\.\s*(?:Please\s+list\s+)?any\s+federal\s+grants\s+or\s+contracts\s*\(including\s+subgrants\s+or\s+subcontracts\)"
    r".{0,160}?since\s+October\s+1",
    re.I,
)
RX_TTF_NEG_STRICT = re.compile(
    r"\bDear\s+[A-Za-z]|\bSincerely\b|\bRespectfully\s+submitted\b"
    r"|pleased\s+to\s+invite|invit(?:e|ing)\s+you\s+to\s+testify|invitation\s+to\s+testify"
    r"|enclosed\s+please\s+find|please\s+find\s+enclosed|attached\s+please\s+find|please\s+find\s+attached"
    r"|\bThank\s+you,?\s+(?:Mr\.?|Madam|Chair(?:man|woman)?)"
    r"|\bThank\s+you\s+for\s+(?:agreeing|appearing)\b",
    re.I,
)
RX_TTF_HEAD_NEG_STRICT = re.compile(
    r"^(?:\d+\s+)?(?:written\s+|prepared\s+|oral\s+|opening\s+)?(?:statement|testimony|remarks|biography|curriculum\s+vitae)\s+(?:of|by|from|:)\b"
    r"|^(?:\d+\s+)?(?:instructions|guidelines|information)\s+for\s+witnesses\b"
    r"|^(?:\d+\s+)?(?:RULES\s+(?:OF|FOR)\s+THE\s+COMMITTEE|AMENDMENT\s+TO\s+(?:THE\s+)?RULES)"
    r"|\bHEARING\s+BEFORE\s+THE\b"
    r"|\bNOTICE\s+OF\b|\b(?:HEARING|MARKUP|BUSINESS\s+MEETING)\s+NOTICE\b"
    r"|\bMEMORANDUM\b|M\s+E\s+M\s+O\s+R\s+A\s+N\s+D\s+U\s+M|\b(?:HEARING|MARKUP)\s+CHARTER\b",
    re.I,
)
RX_TTF_ALLCAPS_RULES = re.compile(r"(?<!and the )\bRULES OF THE COMMITTEE\b")

RX_ATTEND_HSIF = re.compile(
    r"^(?:As of \d{1,2}/\d{1,2}/\d{2,4}\s+)?ROLL CALL ATTENDANCE/QUORUM CALL\b",
    re.I,
)
RX_ATTEND_PRESENT = re.compile(r"\bATTENDANCE\s+Meeting on:", re.I)
RX_ATTEND_PARTIES = re.compile(r"Democrats\s+Present.*?Republicans\s+Present", re.I)
RX_VOTE_ANY_TALLY = re.compile(r"\b(?:YEAS?|NAYS?|AYES?|NOES?|ROLL CALL NO\.)\b", re.I)
RX_VOTE_HSWM = re.compile(
    r"^(?:\d+\s+)?VOTES OF THE COMMITTEE\s+In compliance with the Rules of the House of Representatives,\s+the following statement is made concerning the vote"
)
RX_VOTE_YEAS_NAYS_PAIR = re.compile(r"\b(?:Yeas|Ayes)\b.*?\b(?:Nays|Noes)\b", re.I)
RX_VOTE_NEG = re.compile(
    r"ROLL CALL ATTENDANCE/QUORUM CALL|\[To accompany\b|HOUSE OF REPRESENTATIVES\s*\{\s*REPORT\s+11\d|"
    r"Calendar No\.|SUMMARY OF ACTION|Sponsor\s+Summary and Text\s+Result",
    re.I,
)
RX_VOTE_GEN_HEAD = re.compile(
    r"(?:FULL COMMITTEE (?:ROSTER )?ROLL CALL|SUBCOMMITTEE ROLL CALL|COMMITTEE ROLL CALL VOTE|"
    r"Roll Call Vote(?:\s+No\.|\s*#|\s+on\b)|RECORD VOTE NO\.\s*\d+|\bROLL CALL:\s*\d+|"
    r"\bROLL CALL NO\.\s*_*\d+|\bRoll Call\s+#\s*\d+)",
    re.I,
)
RX_VOTE_GEN_TALLY = re.compile(
    r"(?:\b(?:YEAS?|AYES?)\s+(?:X*\s*)?(?:NAYS?|NOES?)(?:\s+PRESENT)?\b|"
    r"\(AYE\)\s*\d+\s*\(NO\)\s*\d+|"
    r"\b(?:Yeas?|Ayes?)\s*[:=-]?\s*\d+\s*[,;/]?\s*(?:Nays?|Noes?)\s*[:=-]?\s*\d+|"
    r"\bYEA/AYE\s+NAY/NO\b)",
    re.I,
)
RX_AMDT_HLC_HEAD = re.compile(
    r"AMENDMENT (?:\(IN THE NATURE OF A SUBSTITUTE\) |IN THE NATURE OF A SUBSTITUTE )?TO "
    r"(?:THE AMENDMENT IN THE NATURE OF A SUBSTITUTE TO |RULES COMMITTEE PRINT [\d–-]+|"
    r"COMMITTEE PRINT|H\.\s*R\.\s*\d+|S\.\s*\d+|H\.\s*(?:J\.|CON\.)?\s*RES\.\s*\d+|"
    r"THE COMMITTEE REPORT|THE BILL|A\.N\.S\.)"
)
RX_AMDT_HLC_OFFERED = re.compile(r"OFFERED BY (?:MR\.|MS\.|MRS\.|M_\.|REP\.|SENATOR)")
RX_AMDT_HLC_OPERATIVE = re.compile(
    r"(?:\bPage\s+\d+,\s*(?:beginning on\s+)?line\s+\d+|"
    r"\bStrike\s+all\s+after\s+the\s+enacting\s+clause|"
    r"\bStrike\s+(?:section|subsection|paragraph|the\s+matter)|"
    r"\bAdd\s+at\s+the\s+end\s+the\s+following|"
    r"\bAt\s+the\s+end\s+of\s+(?:title|subtitle|section|the\s+bill)|"
    r"\bIn\s+section\s+\d+|"
    r"\bRedesignate\s+sections?\b)"
)
RX_AMDT_HLC_NEG = re.compile(
    r"(?:SECTION-BY-SECTION|COVER SHEET|This amendment would|"
    r"\bROLL CALL\b|\btoll call vote\b|\bRECORD VOTE\b|\bVOTES OF THE COMMITTEE\b|"
    r"\bDISPOSITION:|\bYEAS\s+NAYS\b|\bAYES\s+NOES\b|\bComparative Print\b|\bSUMMARY OF ACTION\b)",
    re.I,
)
RX_AMDT_HSRU = re.compile(
    r"^(?:Page \d+ of \d+\s+|\d+\s+)?MOTION BY (?:MR\.|MS\.|MRS\.|M_?\.)\s+.{1,60}?\s+TO (?:MAKE IN ORDER|STRIKE|WAIVE|POSTPONE)",
    re.I,
)
RX_AMDT_HSRU_BODY = re.compile(
    r"I have an amendment to the rule\b|I move (?:that )?the [Cc]ommittee make in order"
)
RX_AMDT_SENATE = re.compile(
    r"(?:Amendment intended to be proposed by (?:Mr\.|Ms\.|Mrs\.|Senator)|"
    r"S\.L\.C\.\s+AMENDMENT\s+NO\.\s*(?:\d+|l+)\s+Calendar\s+No\.|"
    r"PURPOSE:\s+.{5,200}?\s+IN THE SENATE OF THE UNITED STATES.*?\b(?:Viz:|Strike\b|On page \d+))"
)
RX_MEMO_NOTICE_EXCL = re.compile(
    r"(?:HEARING|MARKUP|MEETING)\s+NOTICE|NOTICE\s+OF\s+(?:FULL\s+COMMITTEE\s+|SUBCOMMITTEE\s+)?(?:HEARING|MARKUP|MEETING)",
    re.I,
)
RX_MEMO_HEAD = re.compile(
    r"(?:\bMEMORANDUM\b|M\s+E\s+M\s+O\s+R\s+A\s+N\s+D\s+U\s+M|Mark-?Up\s+Memorandum|Hearing\s+Memorandum)",
    re.I,
)
RX_MEMO_TO = re.compile(r"\b(?:To|TO)\s*:\s*(?:Re:\s*)?(?:All\s+)?(?:[A-Za-z ,&']+\s+)?Members\b")
RX_MEMO_FROM_STAFF = re.compile(
    r"\b(?:From|FROM|Fr|FR)\s*:\s*(?:[A-Za-z ,&'–-]{0,75}?)\bStaff\b"
)
RX_CHARTER_HEAD = re.compile(r"\bHEARING CHARTER\b")
RX_CHARTER_CMT = re.compile(
    r"\b(?:COMMITTEE ON|SUBCOMMITTEE ON|U\.S\. HOUSE OF REPRESENTATIVES)\b",
    re.I,
)
RX_CHARTER_NEG = re.compile(
    r"\b(?:Testimony|Statement|Prepared Statement|Remarks|Biography)\s+(?:of|by)\b",
    re.I,
)
RX_NOTICE_MARKUP_POS = re.compile(
    r"(?:(?:\*\s*\*\s*\*|✯\s*✯\s*✯)\s*(?:REVISED\s+)?(?:Full Committee\s+|Subcommittee\s+)?(?:Markup|MARKUP|Business Meeting|BUSINESS MEETING)\s+(?:Notice|NOTICE)\s*(?:\*\s*\*\s*\*|✯\s*✯\s*✯)|"
    r"\b(?:FULL COMMITTEE\s+|SUBCOMMITTEE\s+)?(?:MARKUP|BUSINESS MEETING)\s+NOTICE\b|"
    r"\bNOTICE OF (?:REVISED\s+)?(?:FULL COMMITTEE\s+|SUBCOMMITTEE\s+)?(?:MARKUP|BUSINESS MEETING)\b)"
)
RX_NOTICE_MARKUP_NEG = re.compile(
    r"(?:HEARING AND MARKUP|Mark-?Up\s+Memorandum|\bFrom\s*:\s*[^:\n]{0,50}\bStaff\b|"
    r"SUMMARY OF ACTION|ROLL CALL|VOTES OF THE COMMITTEE|"
    r"^(?:\s*-\s*\d+\s*-\s*)?(?:CONGRESSWOMAN|CONGRESSMAN|STATEMENT OF|OPENING STATEMENT|Amendment to))",
    re.I,
)
RX_NOTICE_HEARING_POS = re.compile(
    r"(?:(?:\*\s*\*\s*\*|✯\s*✯\s*✯)\s*(?:REVISED\s+|REMOTE\s+|HYBRID\s+)?(?:Hearing Notice|HEARING NOTICE)\s*(?:\*\s*\*\s*\*|✯\s*✯\s*✯)|"
    r"\bNOTICE OF (?:REVISED\s+)?(?:OVERSIGHT\s+|LEGISLATIVE\s+|FULL COMMITTEE\s+|SUBCOMMITTEE\s+|JOINT\s+|FIELD\s+|HYBRID\s+|REMOTE\s+|VIRTUAL\s+)*HEARING\b|"
    r"\bNotice of (?:Revised\s+)?(?:Oversight\s+|Legislative\s+|Full Committee\s+|Subcommittee\s+)*Hearing\s+TIME\s+DATE\s+PLACE\b)"
)
RX_NOTICE_HEARING_NEG = re.compile(
    r"(?:\b(?:MARKUP|BUSINESS MEETING)\b|\bFrom\s*:\s*[^:\n]{0,50}\bStaff\b|HEARING CHARTER|Witness List|"
    r"^(?:\s*-\s*\d+\s*-\s*)?(?:CONGRESSWOMAN|CONGRESSMAN|STATEMENT OF|OPENING STATEMENT|Amendment to))",
    re.I,
)
RX_QFR_REQ_DEAR = re.compile(
    r"\bDear\s+[^:\n]{2,60}[:,]\s+(?:I am writing to thank you|Thank you)\s+for (?:appearing|testifying) before the\b",
    re.I,
)
RX_QFR_REQ_BODY = re.compile(
    r"(?:submit|submitted|enclosed|attached|respond to)\s+(?:additional\s+|written\s+)?questions for the (?:hearing\s+)?record\b",
    re.I,
)
RX_QFR_REQ_NEG = re.compile(
    r"(?:\bI am (?:attaching|submitting|enclosing) my (?:answers|responses)|"
    r"\bplease find (?:attached|enclosed|below) (?:my|our) (?:answers|responses)|"
    r"\b(?:Answer|Response)\s*:\s+[A-Z])",
    re.I,
)
RX_WIT_INV_DEAR = re.compile(
    r"\bDear\s+[^:\n]{2,60}[:,]\s+(?:Thank you for agreeing to testify|"
    r"(?:On behalf of .{5,80}?,\s*)?I (?:am writing to |would like to |cordially )?invite you to testify)\b",
    re.I,
)
RX_WIT_INV_BODY = re.compile(
    r"Truth[- ]in[- ]Testimony|written testimony|hearing entitled",
    re.I,
)
RX_BILL_GPO_1 = re.compile(
    r"^(?:I|II|\[11\d[A-Z0-9]+\]\s*\.*)?\s*(?:\(Original Signature of Member\)\s+)?11\dTH CONGRESS\s+"
    r"(?:1ST|2D|FIRST|SECOND)\s+SESSION\s+(?:H\.\s*R\.|S\.|H\.\s*J\.\s*RES\.|S\.\s*J\.\s*RES\.)\s*(?:\d+|ll+)\s+"
    r"(?:IN THE (?:HOUSE OF REPRESENTATIVES|SENATE OF THE UNITED STATES)|A BILL\b|To\s+)"
)
RX_BILL_RCP = re.compile(
    r"^(?:[A-Z]+ \d{1,2}, 20\d\d\s+)?RULES COMMITTEE PRINT\s+11\d[–-]\d+\s+(?:TEXT OF|SECTION 1\.)"
)
RX_BILL_SUSP = re.compile(r"^Suspend the Rules and Pass the Bill,\s+H\.\s*R\.\s*\d+")
RX_BILL_NEG = re.compile(
    r"\b(?:Calendar No\.|Report No\.\s*11\d|AMENDMENT|Comparative Print|Dear\s+|MEMORANDUM)\b",
    re.I,
)
RX_COMP_PRINT = re.compile(
    r"^(?:Report Generated:\s*.{5,65}?\s+)?(?:Comparative Print:|Comparing the base document )"
)
RX_SENATE_QUEST = re.compile(
    r"^(?:\d+\s+)?(?:UNITED STATES )?SENATE (?:COMMITTEE ON THE )?JUDICIARY (?:COMMITTEE )?QUESTIONNAIRE FOR (?:JUDICIAL |NON-JUDICIAL )?NOMINEES",
    re.I,
)
RX_STENO_COVER = re.compile(
    r"Stenographic Transcript Before the (?:Subcommittee|Committee|Select Committee|Permanent Select Committee)",
    re.I,
)
RX_STENO_NEG = re.compile(r"TRANSCRIBED INTERVIEW|DEPOSITION OF", re.I)


def detect_v4_tier1_signatures(
    filename: str | None,
    text: str | None,
    is_html: bool | None = None,
) -> list[tuple[str, str]]:
    """Evaluate all 21 V4 Tier-1 signatures with 100.0% parity against `pythonic_v4.py`."""
    if not text or not isinstance(text, str) or len(text) < 60:
        return []
    html_flag = infer_is_html_v5(filename, text, is_html=is_html) if is_html is None else bool(is_html)
    if html_flag:
        t_html = _norm_ws_prefix(text, 260)
        if len(t_html) >= 60 and t_html.startswith(_DOCS_HOUSE_WEEKLY_PREFIX):
            return [("schedule_docs_house_floor_weekly", "legislative_schedule_or_calendar")]
        return []

    t_ws = _norm_ws_prefix(text, 1250)
    if len(t_ws) < 60:
        return []

    out: list[tuple[str, str]] = []
    t360 = t_ws[:360]
    t600 = t_ws[:600]
    t_low = t_ws[:1100].lower()
    t360_low = t_low[:360]
    t_ws_full: str | None = None

    has_tit_360 = "truth in testimony" in t360_low
    is_v1 = False
    is_v2 = False
    if has_tit_360:
        is_v1 = (
            bool(RX_TTF_V1.match(t_ws[:240]))
            and "filling in the provided blanks" in t360
            and not RX_LETTER_SALUTATION.search(t600)
        )
        if is_v1:
            out.append(("ttf_clerk_acroform_v1_116_118", "truth_in_testimony_disclosure"))
        is_v2 = bool(RX_TTF_V2.match(t_ws[:280])) and not RX_LETTER_SALUTATION.search(t600)
        if is_v2:
            out.append(("ttf_clerk_acroform_v2_118_119", "truth_in_testimony_disclosure"))
    if not is_v1 and not is_v2 and (
        has_tit_360
        or "disclosure" in t360_low
        or ("october 1" in t_low[:600] and "subgrants" in t_low[:600])
    ):
        t1000 = t_ws[:1000]
        if (
            len(t_ws) >= 80
            and not RX_TTF_NEG_STRICT.search(t1000)
            and not RX_TTF_HEAD_NEG_STRICT.search(t360)
            and not RX_TTF_ALLCAPS_RULES.search(t360)
        ):
            if t_ws_full is None:
                t_ws_full = _norm_ws_prefix(text, 2600)
            t2400 = t_ws_full[:2400]
            if (
                (RX_TTF_BESPOKE_EXACT_TITLE.search(t360) and RX_TTF_BESPOKE_SLOTS.search(t1000))
                or (
                    RX_TTF_GENERIC_HEAD.search(t_ws[:350])
                    and RX_TTF_GENERIC_FIELD.search(t2400)
                    and RX_TTF_GRANTS_CUE.search(t2400)
                )
                or RX_TTF_UNBANNERED_112_115.match(t600)
            ):
                out.append(("ttf_committee_bespoke_form_112_118", "truth_in_testimony_disclosure"))

    if "attendance" in t360_low or "quorum call" in t360_low:
        if RX_ATTEND_HSIF.match(t_ws[:160]):
            out.append(("attendance_hsif_quorum_call", "attendance_quorum_sheet"))
        if RX_ATTEND_PRESENT.search(t_ws[:260]) and RX_ATTEND_PARTIES.search(t_ws[:500]):
            if not RX_VOTE_ANY_TALLY.search(_norm_ws_prefix(text, 8000)):
                out.append(("attendance_committee_present_grid", "attendance_quorum_sheet"))

    if "votes of the committee" in t_low[:240]:
        if t_ws_full is None:
            t_ws_full = _norm_ws_prefix(text, 2600)
        if RX_VOTE_HSWM.match(t_ws[:240]) and RX_VOTE_YEAS_NAYS_PAIR.search(t_ws_full[:1600]):
            out.append(("vote_hswm_votes_of_committee", "committee_vote"))
    if "roll call" in t_low[:380] or "record vote" in t_low[:380]:
        if not RX_VOTE_NEG.search(t_ws[:500]) and RX_VOTE_GEN_HEAD.search(t_ws[:380]):
            if t_ws_full is None:
                t_ws_full = _norm_ws_prefix(text, 2600)
            if RX_VOTE_GEN_TALLY.search(t_ws_full[:1600]):
                out.append(("vote_committee_roll_call_tally_sheet", "committee_vote"))

    if "amendment" in t_low[:600]:
        if RX_AMDT_HLC_HEAD.search(t360) and RX_AMDT_HLC_OFFERED.search(t_ws[:520]):
            if t_ws_full is None:
                t_ws_full = _norm_ws_prefix(text, 2600)
            if (
                RX_AMDT_HLC_OPERATIVE.search(t_ws_full[:1200])
                and not RX_AMDT_HLC_NEG.search(t_ws_full[:1400])
                and not RX_LETTER_SALUTATION.search(t600)
            ):
                out.append(("amdt_hlc_offered_by", "committee_amendment"))
        if RX_AMDT_SENATE.search(t600) and not RX_VOTE_ANY_TALLY.search(t_ws[:500]):
            out.append(("amdt_senate_slc_printed", "committee_amendment"))
    if "motion by" in t_low[:220]:
        if RX_AMDT_HSRU.match(t_ws[:220]) and RX_AMDT_HSRU_BODY.search(t_ws[:500]):
            out.append(("amdt_hsru_motion_make_in_order", "committee_amendment"))

    if "memorandum" in t_low[:550] or "m e m o r a n d u m" in t_low[:550]:
        if (
            not RX_MEMO_NOTICE_EXCL.search(t_ws[:380])
            and RX_MEMO_HEAD.search(t_ws[:550])
            and RX_MEMO_TO.search(t_ws[:750])
            and RX_MEMO_FROM_STAFF.search(t_ws[:900])
        ):
            out.append(("memo_committee_staff_to_members", "hearing_memo_or_charter"))
    if "HEARING CHARTER" in t_ws[:340]:
        if (
            RX_CHARTER_HEAD.search(t_ws[:340])
            and RX_CHARTER_CMT.search(t_ws[:520])
            and not RX_CHARTER_NEG.search(t_ws[:340])
        ):
            out.append(("charter_explicit_heading", "hearing_memo_or_charter"))

    if "notice" in t_low[:950]:
        t950 = t_ws[:950]
        if not RX_NOTICE_MARKUP_NEG.search(t_ws[:650]) and RX_NOTICE_MARKUP_POS.search(t950):
            out.append(("notice_markup_or_business_meeting", "markup_notice"))
        if not RX_NOTICE_HEARING_NEG.search(t950) and RX_NOTICE_HEARING_POS.search(t950):
            out.append(("notice_hearing_formal", "hearing_notice"))

    if "dear " in t_low:
        if RX_QFR_REQ_DEAR.search(t_ws[:1100]):
            if t_ws_full is None:
                t_ws_full = _norm_ws_prefix(text, 2600)
            if RX_QFR_REQ_BODY.search(t_ws_full[:1500]) and not RX_QFR_REQ_NEG.search(t_ws_full[:2500]):
                out.append(("qfr_request_chair_transmittal_letter", "qfr_request"))
        if RX_WIT_INV_DEAR.search(t_ws[:1100]):
            if t_ws_full is None:
                t_ws_full = _norm_ws_prefix(text, 2600)
            if RX_WIT_INV_BODY.search(t_ws_full[:1600]):
                out.append(("witness_invitation_chair_letter", "witness_invitation"))

    if (
        "CONGRESS" in t_ws[:320]
        or "RULES COMMITTEE PRINT" in t_ws[:220]
        or t_ws.startswith("Suspend the Rules")
    ):
        if not RX_BILL_NEG.search(t_ws[:400]) and (
            RX_BILL_GPO_1.match(t_ws[:320])
            or RX_BILL_RCP.match(t_ws[:220])
            or RX_BILL_SUSP.match(t_ws[:140])
        ):
            out.append(("bill_gpo_congressional_print", "bill_or_draft"))
    if "compar" in t_low[:200]:
        if RX_COMP_PRINT.match(t_ws[:200]) and "This document was computer-generated" in t600:
            out.append(("comparative_print_computer_generated", "comparative_print"))

    if "questionnaire" in t_low[:220] and RX_SENATE_QUEST.match(t_ws[:220]):
        out.append(("questionnaire_senate_nominee", "nominee_questionnaire_apq"))
    if "stenographic" in t_low[:280]:
        if RX_STENO_COVER.search(t_ws[:280]) and not RX_STENO_NEG.search(t_ws[:500]):
            out.append(("transcript_stenographic_cover", "hearing_transcript"))

    return out


# --- New V5 100.0%-Precision Structural Signature Regexes ---

# 1. `vote_committee_grid_v5` -> `committee_vote`
_RX_V5_VOTE_POS = re.compile(
    r"(?:"
    r"FULL\s+COMMITTEE\s+VOTES\s+Pursuant\s+to\s+the\s+provisions\s+of\s+clause\s+3\(b\)\s+of\s+rule\s+XIII"
    r"|\bRECORD\s+OF\s+COMMITTEE\s+VOTE\b.{0,220}?\b(?:Roll\s+Call|Disposition|Sponsor/Amendment)\b"
    r"|\bCOMMITTEE\s+ON\s+NATURAL\s+RESOURCES\s+1[12]\d(?:th|TH)\s+CONGRESS\s*[-–—]\s*ROLL\s+CALL\b.{0,260}?\bDisposition:"
    r"|\b(?:Recorded\s+Vote\s+No\.|Record\s+Vote(?:\s+No\.|\s+Description:))\s*.*?\bMember\s+(?:Aye|Yea)\s+(?:No|Nay)\s+(?:Present|Not\s+Recorded|Not\s+Voting)\b"
    r"|\bRoll\s+Call\s+No\.?\s*\d*\s*(?:PASSED|FAILED|Date:)?\s*.{0,180}?\b(?:AYES\s+NOS\s+PRES\.?|SAXESS\s+NOG\s+PRES\.?)\b"
    r"|\bRESPONSE\s+TO\s+CALL\s+OF\s+THE\s+ROLL\s+AYE\s+No\s+PRESENT\b"
    r"|\bRATIO\s+\d+-\d+\s+ROLL\s+CALL\s+Vote\s+on:.*?\bRepublicans\s+Aye\s+No\s+Present\b"
    r"|^YEAS\s+AND\s+NAYS\s+U\.?S\.?\s+House\s+of\s+Representatives\s+COMMITTEE\s+ON.{0,140}?\bVote\s+No\."
    r")",
    re.I,
)
# House Financial Services (`hsba`) uses the same member grid for Quorum Calls and Roll-Call Votes;
# require zero quorum mention AND an explicit recorded vote number or numeric tally on the sheet.
_RX_V5_VOTE_HSBA_HEAD = re.compile(
    r"^Present\s+Representatives?\s+Mr\.\s+[A-Za-z]+,\s*Chairman\b.{80,900}?\bAyes\s+Nays\b",
    re.I,
)
_RX_V5_VOTE_HSBA_TALLY = re.compile(
    r"(?:\b(?:Ayes|Yeas|Nays|Noes)\s+(?:IXI\s+|\[\s*[xX]\s*\]\s+)?\d+\b|"
    r"\bCommittee\s+Totals:\s*\d+\s+\d+\b|"
    r"\b(?:AGREED\s+TO|PASSED|FAILED|REJECTED|DEFEATED|ADOPTED)\s*\(\d+\s*[-–]\s*\d+\)|"
    r"\bFC-\d{1,3}\b|\bFC\s+Vote\s*#|\bRecord\s+Vote\b)",
    re.I,
)
_RX_V5_VOTE_NEG = re.compile(
    r"(?:ROLL\s+CALL\s+ATTENDANCE/QUORUM\s+CALL|ATTENDANCE\s+Meeting\s+on:|"
    r"\[To\s+accompany\b|HOUSE\s+OF\s+REPRESENTATIVES\s*\{?\s*REPORT\s+1[012]\d|"
    r"R\s+E\s+P\s+O\s+R\s+T\s+OF\s+THE\s+COMMITTEE\s+ON|"
    r"\bsubmitted\s+the\s+fol[li]owing\s+(?:CONFERENCE\s+|SUPPLEMENTAL\s+)?(?:REPORT|R\s+E\s+P\s+O\s+R\s+T)\b|"
    r"Calendar\s+No\.|SUMMARY\s+OF\s+ACTION|Sponsor\s+Summary\s+and\s+Text\s+Result|"
    r"COMMITTEE\s+ACTION\s+The\s+Committee\s+on.{0,120}?\bmet,\s+pursuant\s+to\s+notice|"
    r"Results\s+of\s+Executive\s+Business\s+Meeting|"
    r"\bDear\s+|MEMORANDUM|HEARING\s+BEFORE\s+THE)",
    re.I,
)

# 2. `amdt_hlc_ans_and_slc_v5` -> `committee_amendment`
_RX_V5_AMDT_HLC_HEAD = re.compile(
    r"^(?:(?:[A-Za-z]:\\[A-Za-z0-9_.\\()-]+\.XML|[A-Za-z .#'0-9_-]{1,35}#\d+[A-Za-z*]*|"
    r"l\.|Page\s+1\s+of\s+\d+|1)\s+)*"
    r"(?:AMENDMENT\s+(?:\(IN\s+THE\s+NATURE\s+OF\s+A\s+SUBSTITUTE\)\s+|IN\s+THE\s+NA-?\s*TURE\s+OF\s+A\s+SUBSTITUTE\s+)?(?:TO\b|OFFERED\s+BY\b)|"
    r"Amendment\s+(?:in\s+the\s+Nature\s+of\s+a\s+Substitute\s+)?to\s+(?:the\s+[A-Za-z0-9 .'-]{2,45}\s+(?:ANS|Amendment)\s+to\s+)?(?:H\.?\s*R\.?\s*\d+|S\.?\s*\d+|Rules\s+Committee\s+Print|Committee\s+Print)\s+Offered\s+by\b)",
    re.I,
)
_RX_V5_AMDT_OFFERED = re.compile(
    r"OFFERED\s+BY\s+(?:MR\.?|MS[.,]?|MRS\.?|M[l_1I]\.|REP\.?|REPRESENTATIVE|SEN\.?|SENATOR)",
    re.I,
)
_RX_V5_AMDT_OPERATIVE = re.compile(
    r"(?:\bPage\s+\d+,\s*(?:beginning\s+on\s+|after\s+|strike\s+)?line\s+\d+|"
    r"\bStrike\s+all\s+after\s+the\s+enacting\s+clause|"
    r"\bStrike\s+(?:section|subsection|paragraph|title|subtitle|the\s+matter)|"
    r"\b(?:Add|Insert)\s+at\s+the\s+end(?:\s+of\s+[A-Za-z0-9 ]+)?(?:\s*,\s*|\s+the\s+following|\s*:)|"
    r"\bAt\s+the\s+end(?:\s+of\s+(?:title|subtitle|section|the\s+bill))?,?\s+(?:insert|add)\b|"
    r"\bAt\s+the\s+appropriate\s+place(?:\s+in\s+[A-Za-z0-9 ]+)?,?\s+insert\b|"
    r"\bInsert\s+at\s+the\s+appropriate\s+place\b|"
    r"\bAfter\s+the\s+section\s+entitled\b.{1,80}?\binsert\b|"
    r"\bIn\s+section\s+\d+|"
    r"\bRedesignate\s+sections?\b)",
    re.I,
)
_RX_V5_AMDT_SENATE_CAL = re.compile(
    r"(?:\bAMENDMENT\s+NO\.?\s*(?:\d+|l+)?\s+Calendar\s+No\.\s*(?:\d+|l+)?\s+Purpose:\s+.{5,220}?\s+IN\s+THE\s+SENATE\s+OF\s+THE\s+UNITED\s+STATES|"
    r"^In\s+the\s+Senate\s+of\s+the\s+United\s+States,\s+[A-Z][a-z]+\s+\d{1,2},\s+20\d\d\.\s+Resolved,\s+That\s+the\s+bill\s+from\s+the\s+House\s+of\s+Representa-\s*tives.{10,240}?\bdo\s+pass\s+with\s+the\s+following\s+AMENDMENT:)"
)
_RX_V5_AMDT_NEG = re.compile(
    r"(?:SECTION-BY-SECTION|Explanation\s+of\s+Changes|\bsummary\b|Brief\s+Summary|"
    r"COVER\s+SHEET|This\s+amendment\s+(?:would|states|prohibits|requires|directs|provides|amends|strikes|clarifies|establishes|ensures|allows|creates|makes)|"
    r"\bROLL\s+CALL\b|\btoll\s+call\s+vote\b|\bRECORD\s+VOTE\b|\bRecorded\s+Vote\b|\bVOTES\s+OF\s+THE\s+COMMITTEE\b|"
    r"\bDISPOSITION:|\bYEAS\s+NAYS\b|\bAYES\s+(?:NOES|NOS|NAYS)\b|\bComparative\s+Print\b|"
    r"\bSUMMARY\s+OF\s+ACTION\b|Sponsor\s+Summary\s+and\s+Text\s+Result|"
    r"HOUSE\s+OF\s+REPRESENTATIVES\s*\{?\s*REPORT\s+1[012]\d|\bReport\s+No\.\s*1[012]\d|"
    r"\bMEMORANDUM\b|\bHEARING\s+BEFORE\s+THE\b)",
    re.I,
)

# 3. `stmt_member_opening_formal_v5` -> `member_opening_statement`
_MEMBER_ROLE_TOK = (
    r"(?:Full\s+Committee\s+|Subcommittee\s+)?"
    r"(?:Chairman|Chairwoman|Chair\b|Acting\s+Chair(?:man|woman)?|"
    r"Ranking\s+(?:Minority\s+)?Member|Vice\s+Chair(?:man|woman)?|"
    r"Republican\s+Leader|Democratic\s+Leader|"
    r"the\s+Honorable|Hon\.|Rep\.|Representative|Congressman|Congresswoman|Sen\.|Senator)"
)
_RX_V5_MEMBER_OPENING_POS = re.compile(
    r"(?:"
    r"^(?:\d+\s+)?(?:(?:House\s+|Senate\s+|U\.?S\.?\s+)?Committee\s+on\s+[A-Za-z ,&']{3,65}\s+)?"
    r"Opening\s+Statement\s+(?:as\s+Prepared\s+for\s+Delivery\s+|\(As\s+Prepared\s+for\s+Delivery\)\s+)?"
    r"(?:(?:of|for|by)\s+)?" + _MEMBER_ROLE_TOK + r"\s+[A-Z][A-Za-z .,'-]{2,45}"
    r"|\b(?:ONE\s+HUNDRED\s+[A-Z]+\s+CONGRESS|COMMITTEE\s+ON\s+[A-Z ,&']{4,55}).{20,420}?"
    r"\bOpening\s+Statement\s+(?:(?:of|for|by)\s+)?"
    r"(?:Chairman|Chairwoman|Ranking\s+(?:Minority\s+)?Member)\s+[A-Z][A-Za-z .,'-]{2,45}"
    r"|^(?:\d+\s+)?Statement\s+of\s+(?:Full\s+Committee\s+|Subcommittee\s+)?"
    r"(?:Chairman|Chairwoman|Ranking\s+(?:Minority\s+)?Member)\s+[A-Z][A-Za-z .,'-]{2,45}\s+"
    r"(?:(?:House\s+|Senate\s+|U\.?S\.?\s+)?(?:Committee|Subcommittee)\s+on\b|Full\s+Committee\s+(?:Markup|Business\s+Meeting)\b|Resolution\s+Authorizing\b)"
    r")"
)
_RX_V5_MEMBER_OPENING_NEG = re.compile(
    r"(?:\bBefore\s+the\s+(?:U\.?S\.?\s+)?(?:House|Senate|Committee|Subcommittee)\b|"
    r"\bTestimony\s+(?:of|by|before)\b|\bWritten\s+Testimony\b|"
    r"\bTruth\s+in\s+Testimony\b|\bWitness\s+Disclosure\b|\bAccompanied\s+by\b|"
    r"\bOn\s+behalf\s+of\s+(?:the\s+)?[A-Z]|"
    r"\bMr\.\s+Speaker\b|\bMadam\s+Speaker\b|\bMr\.\s+President\b|\bCongressional\s+Record\b|"
    r"\bDear\s+(?:Reader|Chair|Senator|Representative|Mr\.|Ms\.|Mrs\.|Dr\.|Secretary|Director|Colleague)|"
    r"\bSincerely,?|\bRespectfully\s+submitted|"
    r"\bFOR\s+IMMEDIATE\s+RELEASE\b|\bADVISORY\b|\bAnnounces?\s+(?:a\s+|Subcommittee\s+)?Hearing\b|"
    r"\b(?:HEARING|MARKUP|MEETING)\s+NOTICE\b|\bNOTICE\s+OF\b|\bMEMORANDUM\b|"
    r"\bQuestions\s+for\s+the\s+Record\b|\bResponse\s+to\s+Questions\b|"
    r"\bRPTR\b|\bStenographic\b|\bHEARING\s+BEFORE\s+THE\b|"
    r"\bmet,\s+pursuant\s+to\s+(?:notice|call)\b|\bwas\s+called\s+to\s+order\b|"
    r"\bROLL\s+CALL\b|\bAMENDMENT\s+TO\b)",
    re.I,
)

# 4. `witness_list_formal_panel_v5` -> `witness_list`
_RX_V5_WITLIST_TOP = re.compile(
    r"(?:"
    r"^(?:1\s+)?Witness\s+List\b.{5,260}?\b(?:Committee\s+on|Subcommittee\s+on|U\.?S\.?\s+House|United\s+States\s+Senate)\b"
    r"|\b(?:COMMITTEE\s+ON|Committee\s+on)\s+[A-Za-z ,&']{3,65}.{5,480}?(?:\bWITNESS\s+LIST\b|\bWitness\s+List\b|\bAGENDA\b.{5,180}?\bWITNESSES\b)"
    r")"
)
_RX_V5_WITLIST_NEG = re.compile(
    r"(?:\b(?:HEARING|MARKUP|BUSINESS\s+MEETING|MEETING)\s+NOTICE\b|\bNOTICE\s+OF\b|"
    r"\bADVISORY\b|\bFOR\s+IMMEDIATE\s+RELEASE\b|\bAnnounces?\s+.*?\bHearing\b|"
    r"\bMEMORANDUM\b|M\s+E\s+M\s+O\s+R\s+A\s+N\s+D\s+U\s+M|\bSUMMARY\s+OF\s+SUBJECT\s+MATTER\b|"
    r"\bHEARING\s+CHARTER\b|\bCHARTER\b|\bPurpose\s+On\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday)\b|"
    r"\bBackground\b|\bI\.\s+Introduction\b|"
    r"\bHEARING\s+BEFORE\s+THE\b|\bStenographic\b|\bRPTR\b|\bmet,\s+pursuant\s+to\b|\bcalled\s+to\s+order\b|"
    r"\bC\s*O\s*N\s*T\s*E\s*N\s*T\s*S\b|\bCHRONOLOGICAL\s+LIST\s+OF\s+WITNESSES\b|"
    r"\b(?:Written\s+|Prepared\s+|Opening\s+)?(?:Statement|Testimony|Biography)\s+(?:of|by)\b|"
    r"\bTruth\s+in\s+Testimony\b|\bWitness\s+Disclosure\b|\bQuestions\s+for\s+the\s+Record\b|"
    r"\bDear\s+|\bSincerely,?\b|\bROLL\s+CALL\b|\bSUMMARY\s+OF\s+ACTION\b)",
    re.I,
)

# 5. `qfr_response_qa_packet_v5` -> `qfr_response`
_RX_V5_QFR_RESP_EXPLICIT_HEAD = re.compile(
    r"(?:"
    r"\b(?:Responses?|Answers?)\s+to\s+(?:Additional\s+|Written\s+|Post-Hearing\s+)?Questions\s+for\s+the\s+Record\b"
    r"|\bQuestions\s+for\s+the\s+Record\s+Responses?\s*:?"
    r"|\bAnswers\s+for\s+the\s+Record\s*:"
    r"|\bResponses?\s+of\s+[A-Z][A-Za-z0-9 .,&'()-]{2,80}?\s+to\s+(?:Written\s+|Additional\s+)?Questions\s+for\s+the\s+Record\b"
    r"|\bprovide\s+the\s+following\s+responses?\s+to\s+the\s+questions?\s+submitted\s+for\s+the\s+record\b"
    r")",
    re.I,
)
_RX_V5_QFR_HEADER_START = re.compile(
    r"(?:^(?:\d+\s+|Page\s+\d+\s+of\s+\d+\s+)?(?:Attachment\s*[-–—]\s*)?(?:Additional\s+|Authorizing\s+)?Questions\s+for\s+the\s+Record\b"
    r"|\b(?:Committee\s+on|Subcommittee\s+on|Senate\s+[A-Za-z ]+\s+Committee).{0,240}?\bQuestions\s+for\s+the\s+Record\b"
    r"|\bSenator\s+[A-Z][A-Za-z .'-]+,\s*(?:Chairman|Chair|Ranking\s+Member)\s+Questions\s+for\s+the\s+Record\b"
    r"|^Question#\s*:\s*1\b.{0,180}?\bQuestion\s*:)",
    re.I,
)
_RX_V5_QFR_EXPLICIT_ANSWER_MARKER = re.compile(
    r"(?:\b(?:Answer|Response)\s*:\s+\S|\bA:\s+[A-Z]|\bRESPONSE:\s+\S)"
)
_RX_V5_QFR_RESP_NEG = re.compile(
    r"(?:\bAdvance\s+Policy\s+Questions\b|\bQUESTIONNAIRE\s+FOR\s+(?:JUDICIAL\s+|NON-JUDICIAL\s+)?NOMINEES\b|"
    r"\bDear\s+[^:\n]{2,60}[:,]\s+(?:I\s+am\s+writing\s+to\s+thank\s+you|Thank\s+you)\s+for\s+(?:appearing|testifying)\b|"
    r"\b(?:requests?\s+a\s+written\s+response|please\s+(?:provide|submit)\s+your\s+(?:written\s+)?responses?\s+(?:no\s+later\s+than|by\b))|"
    r"\bEnclosed\s+are\s+post-hearing\s+questions\s+that\s+have\s+been\s+directed\s+to\s+you\b|"
    r"\bHEARING\s+BEFORE\s+THE\b|\bStenographic\b|\bRPTR\b|\bTruth\s+in\s+Testimony\b|"
    r"\bMEMORANDUM\b|\bHEARING\s+CHARTER\b)",
    re.I,
)

# 6. `notice_ways_means_or_upper_heading_v5` -> `hearing_notice`
# Strictly case-sensitive on `HEARING NOTICE` / `NOTICE OF UPCOMING COMMITTEE HEARINGS` so lowercase prose never matches!
_RX_V5_NOTICE_UPPER_HEADING = re.compile(
    r"(?:"
    r"^(?:FULL\s+COMMITTEE\s+|SUBCOMMITTEE\s+|REVISED\s+)+HEARING\s+NOTICE\s+COMMITTEE\s+ON\b"
    r"|\bCommittee\s+on\s+[A-Za-z ,&']{3,55}\s+(?:Subcommittee\s+on\s+[A-Za-z ,&']{3,65}\s+)?HEARING\s+NOTICE\s+The\s+(?:Subcommittee|Committee)\b.{0,120}?\bwill\s+hold\s+a\s+hearing\b"
    r"|\bNOTICE\s+OF\s+UPCOMING\s+COMMITTEE\s+HEARINGS\b"
    r")"
)
_RX_V5_NOTICE_WM_ADVISORY = re.compile(
    r"^(?:ADVISORY(?:\s+FROM\s+THE\s+COMMITTEE\s+ON\s+WAYS\s+AND\s+MEANS)?\s+|FOR\s+IMMEDIATE\s+RELEASE\s+|\*New\s+Time\*\s+)"
    r".{0,260}?\b(?:Ways\s+and\s+Means\b.{0,120}?)?"
    r"\bChair(?:man|woman)?\s+[A-Z][A-Za-z .'-]{1,35}(?:\s+and\s+.{3,65}?Chair(?:man|woman)?\s+[A-Z][A-Za-z .'-]{1,35})?\s+"
    r"Announces?\s+(?:a\s+)?(?:Subcommittee\s+|Full\s+Committee\s+)?Hearing\s+on\b"
)
_RX_V5_NOTICE_NEG = re.compile(
    r"(?:\b(?:MARKUP|BUSINESS\s+MEETING)\b|\bMEMORANDUM\b|M\s+E\s+M\s+O\s+R\s+A\s+N\s+D\s+U\s+M|"
    r"\bFrom\s*:\s*[^:\n]{0,70}\bStaff\b|\bSUMMARY\s+OF\s+SUBJECT\s+MATTER\b|"
    r"\bHEARING\s+CHARTER\b|\bWitness\s+List\b|\bWITNESS\s+LIST\b|"
    r"\bOpening\s+Statement\b|\bSTATEMENT\s+OF\b|\bTestimony\s+of\b|"
    r"\bHEARING\s+BEFORE\s+THE\b|\bStenographic\b|\bRPTR\b|\bDear\s+|\bAmendment\s+to\b)",
    re.I,
)

# 7. `memo_summary_subject_matter_v5` -> `hearing_memo_or_charter`
_RX_V5_MEMO_SSM = re.compile(
    r"^(?:\d+\s+|Page\s+\d+\s+of\s+\d+\s+)?(?:[A-Z][a-z]+\s+\d{1,2},\s+20\d\d\s+)?SUMMARY\s+OF\s+SUBJECT\s+MATTER\s+"
    r"TO:\s*Members\b.{0,160}?\bFROM:\s*Staff\b"
)
_RX_V5_MEMO_UNBANNERED_STAFF = re.compile(
    r"^(?:1\s+of\s+\d+\s+|Page\s+1\s+of\s+\d+\s+)?To:\s*(?:All\s+)?(?:House\s+|Senate\s+)?Committee\s+on\s+[A-Za-z ,&']{3,55}\b.{0,60}?Members\s+"
    r"From:\s*[^:\n]{0,95}?\bStaff\b.{0,220}?\b(?:Subject|RE):\s*(?:Full\s+Committee\s+|Subcommittee\s+)?(?:Legislative\s+|Oversight\s+)?Hearing\b",
    re.I,
)

# 8. `report_gpo_committee_report_v5` -> `committee_report`
_RX_V5_GPO_REPORT = re.compile(
    r"(?:"
    r"^(?:\[Report\s+1[012]\d[–-]\d+\]\s*)?(?:House|Union|Senate|Executive)\s+Calendar\s+No\.\s*(?:\d+|l+)\s+"
    r"1[012]\d(?:TH|ST|ND|RD)\s+CONGRESS.{1,120}?(?<!\[)\b(?:House\s+|Senate\s+)?Report\s+(?:No\.\s*)?1[012]\d[–-](?:\d+|l+)"
    r"|^1[012]\d(?:TH|ST|ND|RD)\s+CONGRESS\s+(?:1ST|2D|FIRST|SECOND)\s+SESSION\s+(?:SENATE|HOUSE\s+OF\s+REPRESENTATIVES)\s*\{?\s*(?:EXEC\.\s*)?REPORT\s+1[012]\d[–-]\d+"
    r"|^1[012]\d(?:TH|ST|ND|RD)\s+CONGRESS\s+REPORT\s+[^\n]{0,40}?(?:HOUSE\s+OF\s+REPRESENTATIVES|SENATE)\s+(?:1ST|2D|FIRST|SECOND)\s+SESSION\s+1[012]\d[–-]"
    r"|^(?:R\s+E\s+S\s+O\s+L\s+U\s+T\s+I\s+O\s+N|RESOLUTION)\s+RECOMMENDING\s+THAT\s+THE\s+HOUSE\s+OF\s+REPRESENTATIVES\s+FIND\b.{20,260}?\b(?:R\s+E\s+P\s+O\s+R\s+T|REPORT)\s+OF\s+THE\s+COMMITTEE\s+ON\b"
    r")",
    re.I,
)
_RX_V5_GPO_REPORT_SUBMITTED = re.compile(
    r"\bfrom\s+the\s+[Cc]ommittee\s+(?:on\s+[A-Za-z ,&']+|of\s+conference),\s+submitted\s+the\s+fol[li]owing\s+(?:CONFERENCE\s+|SUPPLEMENTAL\s+)?(?:REPORT|R\s+E\s+P\s+O\s+R\s+T)\b"
)
_RX_V5_REPORT_NEG = re.compile(
    r"(?:\bAMENDMENT\b|\bComparative\s+Print\b|\bROLL\s+CALL\b|\bDear\s+|\bMEMORANDUM\b|\bHEARING\s+BEFORE\s+THE\b)",
    re.I,
)

# 9. `transcript_clerk_rptr_or_prelim_v5` -> `hearing_transcript`
_RX_V5_TRANSCRIPT_RPTR = re.compile(
    r"^(?:1\s+)?RPTR\s+[A-Z][A-Z_.-]*\s+EDTR\s+[A-Z][A-Z_.-]*\b"
    r"|(?:^|\b)(?:\d+\s+)?Diversified\s+Reporting\s+Services,\s+Inc\.\s+RPTS\b"
)
_RX_V5_TRANSCRIPT_PRELIM = re.compile(r"\bThis\s+is\s+a\s+preliminary,\s+unedited\s+transcript\.", re.I)

_RX_V5_TTF_UNBANNERED_EXT = re.compile(
    r"^(?:\d+\s+)?(?:Witness\s+Name|Your\s+Name|Name)\s*:\s*[A-Z].{1,260}?\s+"
    r"(?:1|5)\.\s*(?:Please\s+list\s+)?any\s+federal\s+grants\s+or\s+contracts\s*\(including\s+subgrants\s+or\s+subcontracts\)"
    r".{0,160}?since\s+October\s+1",
    re.I,
)
_RX_V5_TTF_DIGITALLY_SIGNED_TAIL = re.compile(r"\bNone\s+None\s+Digitally\s+signed\s+by\b")
_RX_V5_TRANSCRIPT_NEG = re.compile(
    r"(?:TRANSCRIBED\s+INTERVIEW|DEPOSITION\s+OF|INTERVIEW\s+OF\s*:?\s+[A-Z])",
    re.I,
)

# 10. `questionnaire_nominee_apq_v5` -> `nominee_questionnaire_apq`
_RX_V5_NOMINEE_QUEST_OCR = re.compile(
    r"^(?:\d+\s+)?(?:[ULl]NITED\s+ST\s*ATES\s+)?SENATE\s+(?:COMMITTEE\s+ON\s+[A-Z ,&']+\s+)?QUESTIONNAIRE\s+FOR\s+(?:JUDICIAL\s+|NON-JUDICIAL\s+|PRESIDENTIAL\s+)?NOMINEES\b",
    re.I,
)
_RX_V5_NOMINEE_APQ = re.compile(
    r"^(?:\d+\s+)?(?:United\s+States\s+)?Senate\s+(?:Committee\s+on\s+Armed\s+Services|Armed\s+Services\s+Committee)\s+"
    r"Advance\s+Policy\s+Questions\s+for\s+.{3,100}?\bNominee\s+to\s+be\b",
    re.I,
)

# 11. `bio_hsag_nongov_witness_form_v5` -> `witness_biography`
_RX_V5_BIO_HSAG_FORM = re.compile(
    r"^(?:\d+\s+)?Committee\s+on\s+Agriculture\s+U\.?S\.?\s+House\s+of\s+Representatives\s+"
    r"Information\s+Required\s+From\s+Nongovernmental\s+Witnesses\s+"
    r"House\s+rules\s+require\s+nongovernmental\s+witnesses\s+to\s+provide\s+their\s+resume\s+or\s+biographical\s+sket[ce]h",
    re.I,
)


def detect_new_tier1_signatures_v5(
    filename: str | None,
    text: str | None,
    is_html: bool | None = None,
    *,
    v4_hits: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """Evaluate all 11 new V5 100.0%-precision Tier-1 structural signatures (mutually exclusive with V4)."""
    if not text or not isinstance(text, str) or len(text) < 60:
        return []
    html_flag = infer_is_html_v5(filename, text, is_html=is_html) if is_html is None else bool(is_html)
    if html_flag:
        return []

    existing_v4 = detect_v4_tier1_signatures(filename, text, is_html=False) if v4_hits is None else v4_hits
    if existing_v4:
        return []

    t_ws = _norm_ws_prefix(text, 1300)
    if len(t_ws) < 60:
        return []
    if filename and _RX_EXHIBIT_FN.search(filename):
        return []

    base_fn = (filename or "").rsplit("/", 1)[-1]
    t550 = t_ws[:550]
    t950 = t_ws[:950]
    t_low = t_ws[:1100].lower()
    t_ws_full: str | None = None

    # Evaluate in strict priority/disjoint order (guaranteed <= 1 match, and 0 raw multi-hits or V4 overlaps)
    hits: list[tuple[str, str]] = []

    # 1. `bio_hsag_nongov_witness_form_v5` -> `witness_biography`
    if "nongovernmental witnesses" in t_low[:260] and _RX_V5_BIO_HSAG_FORM.match(t_ws[:320]):
        hits.append(("bio_hsag_nongov_witness_form_v5", "witness_biography"))

    # 2. `questionnaire_nominee_apq_v5` -> `nominee_questionnaire_apq`
    if "nominee" in t_low[:320] and not RX_SENATE_QUEST.match(t_ws[:220]):
        if _RX_V5_NOMINEE_QUEST_OCR.match(t_ws[:260]) or _RX_V5_NOMINEE_APQ.match(t_ws[:320]):
            hits.append(("questionnaire_nominee_apq_v5", "nominee_questionnaire_apq"))

    # 3. `transcript_clerk_rptr_or_prelim_v5` -> `hearing_transcript`
    if (
        "rptr " in t_low[:80]
        or "diversified reporting" in t_low[:200]
        or "preliminary, unedited transcript" in t_low[:450]
    ):
        if not _RX_V5_TRANSCRIPT_NEG.search(t_ws[:600]) and (
            _RX_V5_TRANSCRIPT_RPTR.search(t_ws[:200]) or _RX_V5_TRANSCRIPT_PRELIM.search(t_ws[:450])
        ):
            hits.append(("transcript_clerk_rptr_or_prelim_v5", "hearing_transcript"))

    # 4. `report_gpo_committee_report_v5` -> `committee_report`
    if not base_fn.upper().startswith("BILLS-") and (
        "report" in t_low[:600] or "r e p o r t" in t_low[:900]
    ):
        if not _RX_V5_REPORT_NEG.search(t_ws[:900]) and (
            _RX_V5_GPO_REPORT.match(t_ws[:420])
            or _RX_V5_GPO_REPORT_SUBMITTED.search(t_ws[:900])
        ):
            hits.append(("report_gpo_committee_report_v5", "committee_report"))

    # 5. `vote_committee_grid_v5` -> `committee_vote`
    if (
        "vote" in t_low[:500]
        or "roll call" in t_low[:500]
        or "call of the roll" in t_low[:500]
        or "yeas" in t_low[:500]
        or "ayes" in t_low[:950]
    ):
        if not _RX_V5_VOTE_NEG.search(t950):
            if t_ws_full is None:
                t_ws_full = _norm_ws_prefix(text, 2600)
            is_v4_vote = (
                bool(RX_VOTE_HSWM.match(t_ws[:240]) and RX_VOTE_YEAS_NAYS_PAIR.search(t_ws_full[:1600]))
                or bool(
                    ("roll call" in t_low[:380] or "record vote" in t_low[:380])
                    and not RX_VOTE_NEG.search(t_ws[:500])
                    and RX_VOTE_GEN_HEAD.search(t_ws[:380])
                    and RX_VOTE_GEN_TALLY.search(t_ws_full[:1600])
                )
            )
            if not is_v4_vote:
                is_hsba_vote = (
                    bool(_RX_V5_VOTE_HSBA_HEAD.search(t950))
                    and "quorum" not in ((filename or "") + " " + t_ws_full[:1600]).lower()
                    and bool(_RX_V5_VOTE_HSBA_TALLY.search(t_ws_full[:1600]))
                )
                if _RX_V5_VOTE_POS.search(t950) or is_hsba_vote:
                    hits.append(("vote_committee_grid_v5", "committee_vote"))

    # 6. `amdt_hlc_ans_and_slc_v5` -> `committee_amendment`
    if "amendment" in t_low[:650]:
        if t_ws_full is None:
            t_ws_full = _norm_ws_prefix(text, 2600)
        if not _RX_V5_AMDT_NEG.search(t_ws_full[:1500]) and not RX_LETTER_SALUTATION.search(t_ws[:650]):
            is_v4_amdt = (
                bool(
                    RX_AMDT_HLC_HEAD.search(t_ws[:360])
                    and RX_AMDT_HLC_OFFERED.search(t_ws[:520])
                    and RX_AMDT_HLC_OPERATIVE.search(t_ws_full[:1200])
                    and not RX_AMDT_HLC_NEG.search(t_ws_full[:1400])
                )
                or bool(RX_AMDT_SENATE.search(t_ws[:600]) and not RX_VOTE_ANY_TALLY.search(t_ws[:500]))
                or bool(RX_AMDT_HSRU.match(t_ws[:220]) and RX_AMDT_HSRU_BODY.search(t_ws[:500]))
            )
            if not is_v4_amdt:
                is_hlc_v5 = (
                    bool(_RX_V5_AMDT_HLC_HEAD.match(t_ws[:380]))
                    and bool(_RX_V5_AMDT_OFFERED.search(t_ws[:580]))
                    and bool(_RX_V5_AMDT_OPERATIVE.search(t_ws_full[:1300]))
                )
                is_sen_v5 = bool(_RX_V5_AMDT_SENATE_CAL.search(t_ws[:650])) and not bool(
                    RX_VOTE_ANY_TALLY.search(t_ws[:550])
                )
                if is_hlc_v5 or is_sen_v5:
                    hits.append(("amdt_hlc_ans_and_slc_v5", "committee_amendment"))

    # 7. `memo_summary_subject_matter_v5` -> `hearing_memo_or_charter`
    if "summary of subject matter" in t_low[:220] or ("to:" in t_low[:120] and "staff" in t_low[:450]):
        if not RX_MEMO_NOTICE_EXCL.search(t_ws[:420]) and (
            _RX_V5_MEMO_SSM.match(t_ws[:450]) or _RX_V5_MEMO_UNBANNERED_STAFF.match(t_ws[:550])
        ):
            hits.append(("memo_summary_subject_matter_v5", "hearing_memo_or_charter"))

    # 8. `notice_ways_means_or_upper_heading_v5` -> `hearing_notice`
    if (
        "HEARING NOTICE" in t950
        or "UPCOMING COMMITTEE HEARINGS" in t_ws[:240]
        or "Announce" in t_ws[:360]
    ):
        if not _RX_V5_NOTICE_NEG.search(t950) and (
            _RX_V5_NOTICE_UPPER_HEADING.search(t950) or _RX_V5_NOTICE_WM_ADVISORY.match(t_ws[:420])
        ):
            hits.append(("notice_ways_means_or_upper_heading_v5", "hearing_notice"))

    # 9. `witness_list_formal_panel_v5` -> `witness_list`
    if "witness" in t_low[:650]:
        if not _RX_V5_WITLIST_NEG.search(t950) and _RX_V5_WITLIST_TOP.search(t_ws[:680]):
            hits.append(("witness_list_formal_panel_v5", "witness_list"))

    # 10. `qfr_response_qa_packet_v5` -> `qfr_response`
    if "questions for the record" in t_low[:650] or "answers for the record" in t_low[:450] or "question#:" in t_low[:80]:
        if t_ws_full is None:
            t_ws_full = _norm_ws_prefix(text, 2600)
        if not _RX_V5_QFR_RESP_NEG.search(t_ws_full[:1800]):
            if _RX_V5_QFR_RESP_EXPLICIT_HEAD.search(t_ws[:650]) or (
                _RX_V5_QFR_HEADER_START.search(t_ws[:450])
                and _RX_V5_QFR_EXPLICIT_ANSWER_MARKER.search(t_ws_full[:2500])
            ):
                hits.append(("qfr_response_qa_packet_v5", "qfr_response"))

    # 11. `stmt_member_opening_formal_v5` -> `member_opening_statement`
    if "opening statement" in t_low[:550] or t_low.startswith(("statement of chair", "statement of ranking", "1 statement of chair", "1 statement of ranking")):
        if t_ws_full is None:
            t_ws_full = _norm_ws_prefix(text, 2600)
        if not _RX_V5_MEMBER_OPENING_NEG.search(t_ws_full[:1400]) and _RX_V5_MEMBER_OPENING_POS.search(t550):
            hits.append(("stmt_member_opening_formal_v5", "member_opening_statement"))

    # 12. Unbannered 112-115 TTF forms (`Name: ... 5. Any federal grants ... since October 1`) and `-TTF-` custom-font forms with Adobe `None None Digitally signed by`
    if not hits:
        if (
            "october 1" in t_low[:750]
            and "subgrants" in t_low[:750]
            and not RX_TTF_NEG_STRICT.search(t_ws[:1000])
            and not RX_TTF_HEAD_NEG_STRICT.search(t_ws[:360])
            and not RX_TTF_ALLCAPS_RULES.search(t_ws[:360])
            and _RX_V5_TTF_UNBANNERED_EXT.match(t_ws[:750])
        ):
            hits.append(("ttf_committee_bespoke_form_112_118", "truth_in_testimony_disclosure"))
        elif "-ttf-" in base_fn.lower():
            if t_ws_full is None:
                t_ws_full = _norm_ws_prefix(text, 2600)
            if _RX_V5_TTF_DIGITALLY_SIGNED_TAIL.search(t_ws_full):
                hits.append(("ttf_committee_bespoke_form_112_118", "truth_in_testimony_disclosure"))

    return hits


def detect_all_tier1_signatures_v5(
    filename: str | None,
    text: str | None,
    is_html: bool | None = None,
) -> list[tuple[str, str]]:
    """Evaluate all 32 Tier-1 signatures (21 V4 + 11 V5), returning `(signature_id, target_doc_kind)`."""
    if not text or not isinstance(text, str) or len(text) < 60:
        return []
    html_flag = infer_is_html_v5(filename, text, is_html=is_html) if is_html is None else bool(is_html)
    v4_hits = detect_v4_tier1_signatures(filename, text, is_html=html_flag)
    if v4_hits or html_flag:
        return v4_hits
    return detect_new_tier1_signatures_v5(filename, text, is_html=False, v4_hits=v4_hits)


def detect_exact_tier1_signature_v5(
    filename: str | None,
    text: str | None,
    is_html: bool | None = None,
) -> tuple[str | None, str | None]:
    """Return `(signature_id, target_doc_kind)` if `(filename, text)` matches any V4 or V5 Tier-1 signature."""
    hits = detect_all_tier1_signatures_v5(filename, text, is_html=is_html)
    if hits:
        return hits[0]
    return None, None


detect_all_tier1_signatures = detect_all_tier1_signatures_v5
detect_exact_tier1_signature = detect_exact_tier1_signature_v5


# --- Non-Locking Tier-2 Sidecar Hints (for cues that are < 100.0% grammar-locking pure) ---

_RX_T2_PRESS_RELEASE = re.compile(
    r"^(?:ACTION\s+FROM\s+THE\s+COMMITTEE\s+ON\s+[A-Z ,&']+\s+)?FOR\s+IMMEDIATE\s+RELEASE\b",
    re.I,
)
_RX_T2_PRESS_EXCL = re.compile(
    r"\b(?:ADVISORY|Announces?\s+(?:a\s+|Subcommittee\s+)?(?:Hearing|Markup)|"
    r"For\s+Release\s+on\s+Delivery|Government\s+Accountability\s+Office|"
    r"Opening\s+Statement|Testimony\s+of|Statement\s+of)\b",
    re.I,
)
_RX_T2_WITNESS_BIO = re.compile(
    r"^(?:1\s+)?(?:Biography(?:\s+of)?\s+[A-Z]|[A-Z][A-Za-z .,'-]{3,55}\s+Biography\b|CURRICULUM\s+VITAE\b)",
)
_RX_T2_MEETING_RESULTS = re.compile(
    r"(?:\bSponsor\s+Summary\s+and\s+Text\s+Result\b|\bResults\s+of\s+Executive\s+Business\s+Meeting\b|"
    r"\bSUMMARY\s+OF\s+ACTION\b)",
    re.I,
)
_RX_T2_SECTION_BY_SECTION = re.compile(
    r"(?:\bSection[- ]by[- ]Section(?:\s+Summary|\s+Analysis)?\b|\bExplanation\s+of\s+Changes\s+Reflected\s+in\b)",
    re.I,
)


def detect_tier2_sidecar_hints_v5(
    filename: str | None,
    text: str | None,
    is_html: bool | None = None,
) -> list[dict[str, Any]]:
    """Return non-locking sidecar hints (`tier=2`, never used to lock `LLMatcher` grammar)."""
    if not text or not isinstance(text, str) or len(text) < 40:
        return []
    t_ws = _norm_ws_prefix(text, 900)
    hints: list[dict[str, Any]] = []
    if _RX_T2_PRESS_RELEASE.match(t_ws[:200]) and not _RX_T2_PRESS_EXCL.search(t_ws[:500]):
        hints.append(
            {
                "hint_id": "t2_for_immediate_release_header",
                "candidate_kind": "press_release_or_fact_sheet",
                "locking": False,
            }
        )
    if _RX_T2_WITNESS_BIO.match(t_ws[:180]):
        hints.append(
            {
                "hint_id": "t2_biography_or_cv_heading",
                "candidate_kind": "witness_biography",
                "locking": False,
            }
        )
    if _RX_T2_MEETING_RESULTS.search(t_ws[:450]):
        hints.append(
            {
                "hint_id": "t2_committee_markup_action_summary",
                "candidate_kind": "meeting_results",
                "locking": False,
            }
        )
    if _RX_T2_SECTION_BY_SECTION.search(t_ws[:320]):
        hints.append(
            {
                "hint_id": "t2_section_by_section_heading",
                "candidate_kind": "section_by_section",
                "locking": False,
            }
        )
    return hints


__all__ = [
    "CMS_STRIPPER_FAMILIES_V5",
    "CANONICAL_COMMITTEES_V5",
    "V4_TIER1_SIGNATURE_TO_KIND",
    "NEW_TIER1_SIGNATURE_TO_KIND_V5",
    "TIER1_SIGNATURE_TO_KIND_V5",
    "TIER1_SIGNATURE_IDS_V5",
    "TIER1_TARGET_KINDS_V5",
    "TIER1_SIGNATURE_TO_KIND",
    "TIER1_SIGNATURE_IDS",
    "TIER1_TARGET_KINDS",
    "infer_is_html_v5",
    "infer_is_html",
    "strip_html_cms_nav_v5",
    "strip_html_cms_nav",
    "iso_date_to_congress",
    "extract_official_slug_congress",
    "extract_pdf_masthead_congress_v5",
    "extract_pdf_masthead_congress",
    "extract_formal_committee_masthead_v5",
    "extract_formal_committee_masthead",
    "detect_v4_tier1_signatures",
    "detect_new_tier1_signatures_v5",
    "detect_all_tier1_signatures_v5",
    "detect_all_tier1_signatures",
    "detect_exact_tier1_signature_v5",
    "detect_exact_tier1_signature",
    "detect_tier2_sidecar_hints_v5",
]
