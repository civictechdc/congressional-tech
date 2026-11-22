#!/usr/bin/env python3
"""Phase 4 Multi-Page (`p3..N`) Deterministic Rules & Non-Usable Triage Helpers (100% Python stdlib).

Reusable by `pythonic_v5.py` (`@v5-integrator`) and `build_corpus_manifest_v5.py` with ZERO external
dependencies beyond Python standard library:
  1. `split_pdf_pages(text, page_offsets)`
  2. `is_gpo_cover_roster_only_p12(text_p12)` & `is_steno_cover_roster_only_p12(text_p12)`
  3. `extract_gpo_p3_p8_rescue(pages, p12_text=None)` -> rescues `p3..p8` `CONTENTS` / `WITNESSES` /
     `STATEMENTS OF` / opening gavel slice (`<= 2,500` chars) + `has_gpo_p3_witness_panel` when `p1-2`
     is cover + standing roster only.
  4. `extract_ttf_disclosure_booleans(ttf_text, sig_id=None)` -> 100%-precision deterministic booleans
     (`gov_witness`, `capacity`, `has_federal_grants`, `has_foreign_payments`) on Clerk AcroForm v1/v2
     and unambiguous committee-bespoke Truth-in-Testimony forms (`0` mismatches on `Gold360`).
  5. `detect_stapled_backpage_packets(pages, filename=None, p12_text=None)` -> 100%-precision detection
     of stapled `p3..N` Truth-in-Testimony forms (`stapled_ttf_page`), Committee Roll-Call Vote tallies
     (`stapled_vote_page`), and Questions for the Record appendices (`stapled_qfr_page`).
  6. `extract_multipage_signals_v5(text, page_offsets, filename=None)` -> unified Phase 4 entrypoint.
  7. `triage_unwrapped_http_or_empty(http_status, text, ...)` -> deterministic HTTP 404/403/5xx/WAF &
     certified-empty triage helper reusable by `triage_non_usable_v5`.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

__all__ = [
    "split_pdf_pages",
    "is_gpo_cover_roster_only_p12",
    "is_steno_cover_roster_only_p12",
    "extract_gpo_p3_p8_rescue",
    "detect_ttf_page_signature",
    "extract_ttf_disclosure_booleans",
    "detect_vote_page_signature",
    "match_qfr_appendix_page",
    "is_qfr_appendix_page",
    "detect_stapled_backpage_packets",
    "extract_multipage_signals_v5",
    "triage_unwrapped_http_or_empty",
]

WS_RE = re.compile(r"[ \t\r\n]+")


def _norm_ws(text: str, limit: int | None = None) -> str:
    sub = text[:limit] if limit is not None else text
    if "\n" in sub or "\r" in sub or "\t" in sub or "  " in sub:
        return WS_RE.sub(" ", sub).strip()
    return sub.strip()


def split_pdf_pages(
    text: str | None,
    page_offsets: Sequence[int] | None,
) -> list[str]:
    """Split concatenated PDF `text` into per-page strings using `page_offsets`."""
    if not text:
        return []
    if not page_offsets:
        return [text]
    n_txt = len(text)
    n_off = len(page_offsets)
    pages: list[str] = []
    for i in range(n_off):
        start = max(0, min(int(page_offsets[i]), n_txt))
        end = max(start, min(int(page_offsets[i + 1]), n_txt)) if i + 1 < n_off else n_txt
        pages.append(text[start:end])
    return pages


# ---------------------------------------------------------------------------
# 1. GPO & Stenographic Cover+Roster P1-2 Detectors & P3-P8 Rescue
# ---------------------------------------------------------------------------

_RX_GPO_IMPRINT_OR_USE = re.compile(
    r"U\.?\s*S\.?\s+GOVERNMENT\s+(?:PUBLISHING|PRINTING)\s+OFFICE"
    r"|Printed\s+for\s+the\s+use\s+of\s+the\s+(?:Select\s+|Permanent\s+|Special\s+|Joint\s+)?Committee",
    re.I,
)
_RX_GPO_COVER_BANNER = re.compile(
    r"\b(?:HEARINGS?|JOINT\s+HEARING|FIELD\s+HEARING|OVERSIGHT\s+HEARING|VIRTUAL\s+HEARING|MARKUP)\s+BEFORE\s+(?:A\s+SUBCOMMITTEE\s+OF\s+)?THE\b"
    r"|Printed\s+for\s+the\s+use\s+of\s+the\s+(?:Select\s+|Permanent\s+|Special\s+|Joint\s+)?Committee",
    re.I,
)
_RX_STATE_ROSTER_ENTRY = re.compile(
    r"\b[A-Z][A-Z.\s'\u2019-]{2,30},\s+(?:Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|"
    r"Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|"
    r"Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New\s+Hampshire|"
    r"New\s+Jersey|New\s+Mexico|New\s+York|North\s+Carolina|North\s+Dakota|Ohio|Oklahoma|Oregon|"
    r"Pennsylvania|Rhode\s+Island|South\s+Carolina|South\s+Dakota|Tennessee|Texas|Utah|Vermont|"
    r"Virginia|Washington|West\s+Virginia|Wisconsin|Wyoming|District\s+of\s+Columbia|Puerto\s+Rico|"
    r"Guam|American\s+Samoa|Virgin\s+Islands|Northern\s+Mariana\s+Islands)\b"
)
_RX_P12_SUBSTANTIVE_BODY = re.compile(
    r"\bThe\s+(?:sub)?committee(?:s|\s+on\s+[^\n.]{1,100})?\s+(?:met|convened|assembled)\b"
    r"|\bmet,?\s+pursuant\s+to\s+(?:notice|call|adjournment|recess|other\s+business)\b"
    r"|\b(?:hearing|meeting|subcommittee|committee)\s+(?:was\s+called\s+to\s+order|will\s+come\s+to\s+order|came\s+to\s+order)\b"
    r"|\b(?:OPENING\s+)?STATEMENT\s+OF\s+(?:HON\.|THE\s+HONORABLE|SENATOR|REP\.|REPRESENTATIVE|MR\.|MS\.|MRS\.|DR\.|[A-Z][A-Z\s.,'-]{3,})"
    r"|\bTESTIMONY\s+OF\s+[A-Z]"
    r"|\bC\s*O\s*N\s*T\s*E\s*N\s*T\s*S\b"
    r"|\bSUBMISSIONS?\s+FOR\s+THE\s+RECORD\b"
    r"|\bCHRONOLOGICAL\s+LIST\s+OF\s+WITNESSES\b"
    r"|\ba\s+(?:Representative|Senator|Delegate|Resident\s+Commissioner)\s+in\s+Congress\s+from\s+the\s+State\s+of\b"
    r"|\[\s*(?:Whereupon|The\s+(?:advisory|charter|notice|prepared\s+statement))\b",
    re.I,
)
_RX_SPEAKER_TURN = re.compile(
    r"\b(?:(?:The\s+)?(?:Acting\s+)?Chair(?:man|woman|person)?|Senator|Representative|Rep\.|Mr\.|Ms\.|Mrs\.|Dr\.)"
    r"(?:\s+[A-Z][A-Za-z'\-]+){0,3}"
    r"(?:\s+of\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)?"
    r"(?:\s*\[[^\]]{1,40}\])?\s*\.\s+[A-Z\"\u201c]"
)
_RX_STENO_COVER = re.compile(
    r"Stenographic\s+Transcript\s+Before\s+the\s+(?:Subcommittee|Committee|Select\s+Committee|Permanent\s+Select\s+Committee)",
    re.I,
)
_RX_STENO_NEG = re.compile(r"TRANSCRIBED\s+INTERVIEW|DEPOSITION\s+OF", re.I)


def is_gpo_cover_roster_only_p12(text_p12: str | None) -> bool:
    """True ONLY when p1-2 is an unmistakable GPO printed cover + standing roster BEFORE gavel/TOC."""
    if not text_p12 or len(text_p12) > 5200:
        return False
    norm = _norm_ws(text_p12, 2000)
    if not _RX_GPO_IMPRINT_OR_USE.search(norm):
        return False
    if not _RX_GPO_COVER_BANNER.search(norm):
        return False
    if len(_RX_STATE_ROSTER_ENTRY.findall(text_p12)) < 4:
        return False
    if _RX_P12_SUBSTANTIVE_BODY.search(text_p12):
        return False
    if _RX_SPEAKER_TURN.search(text_p12):
        return False
    return True


def is_steno_cover_roster_only_p12(text_p12: str | None) -> bool:
    """True when p1-2 is a raw Stenographic Transcript cover (+ optional APPEARANCES roster) before gavel."""
    if not text_p12 or len(text_p12) > 4800:
        return False
    norm = _norm_ws(text_p12, 600)
    if not _RX_STENO_COVER.search(norm) or _RX_STENO_NEG.search(norm):
        return False
    if _RX_P12_SUBSTANTIVE_BODY.search(text_p12) or _RX_SPEAKER_TURN.search(text_p12):
        return False
    return True


_RX_GPO_TOC_HEAD = re.compile(
    r"(?:\bC\s*O\s*N\s*T\s*E\s*N\s*T\s*S\b"
    r"|(?:^|\n|\))\s*(?:O\s*N\s*T\s*E\s*N\s*T\s*S|N\s*T\s*E\s*N\s*T\s*S|T\s*E\s*N\s*T\s*S|E\s*N\s*T\s*S)\s+"
    r"(?:[A-Z]+\s+\d{1,2},\s+\d{4}\s+)?Page\b"
    r"|\bCHRONOLOGICAL\s+LIST\s+OF\s+WITNESSES\b"
    r"|\bLIST\s+OF\s+WITNESSES\b)",
    re.I,
)
_RX_BUDGET_JUSTIFICATION_NEG = re.compile(
    r"\b(?:BUDGET\s+JUSTIFICATIONS?|JUSTIFICATIONS?\s+and\s+Annual\s+Performance\s+Plan|Appropriation\s+Language\s+Sheet)\b",
    re.I,
)
_RX_TOC_WITNESS_PANEL_CUE = re.compile(
    r"(?:\bWITNESS(?:ES)?\b"
    r"|\bCHRONOLOGICAL\s+LIST\s+OF\s+WITNESSES\b"
    r"|\bPANEL\s+(?:I|II|III|1|2|3|ONE|TWO)\b"
    r"|\bSTATEMENTS?\s+OF\b.*?(?:\.{4,}\s*\d+))",
    re.I | re.S,
)
_RX_GAVEL_CUE = re.compile(
    r"\bThe\s+(?:sub)?committee(?:s|\s+on\s+[^\n.]{1,100})?\s+(?:met|convened|assembled)\b"
    r"|\bmet,?\s+pursuant\s+to\s+(?:notice|call|adjournment|recess|other\s+business)\b"
    r"|\b(?:hearing|meeting|subcommittee|committee)\s+(?:was\s+called\s+to\s+order|will\s+come\s+to\s+order|came\s+to\s+order)\b",
    re.I,
)


def extract_gpo_p3_p8_rescue(
    pages: Sequence[str],
    p12_text: str | None = None,
    max_chars: int = 2500,
) -> dict[str, Any]:
    """When `p1-2` is GPO or Stenographic cover+roster only, locate TOC / witness panel / gavel in `p3..p8`."""
    if len(pages) <= 2:
        return {
            "is_cover_roster_p12": False,
            "cover_roster_kind": None,
            "p3_toc_or_gavel_page": None,
            "p3_toc_or_gavel_slice": None,
            "has_gpo_p3_witness_panel": False,
        }

    p12 = p12_text if p12_text is not None else (pages[0] + pages[1])
    is_gpo = is_gpo_cover_roster_only_p12(p12)
    is_steno = (not is_gpo) and is_steno_cover_roster_only_p12(p12)
    if not (is_gpo or is_steno):
        return {
            "is_cover_roster_p12": False,
            "cover_roster_kind": None,
            "p3_toc_or_gavel_page": None,
            "p3_toc_or_gavel_slice": None,
            "has_gpo_p3_witness_panel": False,
        }

    cover_kind = "gpo_cover_roster" if is_gpo else "steno_cover_roster"
    scan_end = min(len(pages), 8)

    # Check if p3..p8 turns out to be an executive agency Budget Justification volume rather than a hearing
    p3_p8_concat_head = " ".join(pg[:600] for pg in pages[2:scan_end])
    if _RX_BUDGET_JUSTIFICATION_NEG.search(p3_p8_concat_head):
        return {
            "is_cover_roster_p12": True,
            "cover_roster_kind": cover_kind,
            "p3_toc_or_gavel_page": None,
            "p3_toc_or_gavel_slice": None,
            "has_gpo_p3_witness_panel": False,
        }

    toc_pno: int | None = None
    gavel_pno: int | None = None
    for idx in range(2, scan_end):
        pg = pages[idx]
        if not pg or len(pg.strip()) < 30:
            continue
        if toc_pno is None and _RX_GPO_TOC_HEAD.search(pg[:900]):
            toc_pno = idx + 1  # 1-indexed page number
        if gavel_pno is None and (_RX_GAVEL_CUE.search(pg) or _RX_SPEAKER_TURN.search(pg[:1600])):
            gavel_pno = idx + 1

    chosen_pno = toc_pno if toc_pno is not None else gavel_pno
    if chosen_pno is None:
        return {
            "is_cover_roster_p12": True,
            "cover_roster_kind": cover_kind,
            "p3_toc_or_gavel_page": None,
            "p3_toc_or_gavel_slice": None,
            "has_gpo_p3_witness_panel": False,
        }

    chunks: list[str] = []
    has_witness_panel = False

    if toc_pno is not None:
        toc_pg = pages[toc_pno - 1].strip()
        chunks.append(toc_pg)
        if _RX_TOC_WITNESS_PANEL_CUE.search(toc_pg):
            has_witness_panel = True
        # Check if next page continues the dotted-leader TOC (e.g. WITNESSES on p4 after OPENING STATEMENTS on p3)
        if toc_pno < scan_end:
            next_pg = pages[toc_pno].strip()
            if next_pg and re.search(r"\.{4,}\s*\d+", next_pg[:1200]):
                if _RX_TOC_WITNESS_PANEL_CUE.search(next_pg):
                    has_witness_panel = True
                if sum(len(c) for c in chunks) < max_chars - 200:
                    chunks.append(next_pg)
        # Also append compact gavel header if room remains
        if gavel_pno is not None and gavel_pno != toc_pno and sum(len(c) for c in chunks) < max_chars - 240:
            chunks.append(pages[gavel_pno - 1].strip()[:900])
    else:
        assert gavel_pno is not None
        gavel_pg = pages[gavel_pno - 1].strip()
        chunks.append(gavel_pg)

    combined = "\n".join(c for c in chunks if c).strip()
    if len(combined) > max_chars:
        combined = combined[:max_chars].rstrip()

    return {
        "is_cover_roster_p12": True,
        "cover_roster_kind": cover_kind,
        "p3_toc_or_gavel_page": chosen_pno,
        "p3_toc_or_gavel_slice": combined or None,
        "has_gpo_p3_witness_panel": has_witness_panel,
    }


# ---------------------------------------------------------------------------
# 2. Exact Tier-1 Page Matchers & Unambiguous TTF Disclosure Booleans
# ---------------------------------------------------------------------------

_RX_LETTER_SALUTATION = re.compile(
    r"\b(?:Dear\s+(?:Chair|Chairman|Chairwoman|Ranking|Senator|Representative|Congressman|"
    r"Congresswoman|Member|Members|Mr\.|Ms\.|Mrs\.|Dr\.|Prof\.|Professor|Secretary|Director|"
    r"Administrator|Commissioner|General|Admiral|Judge|Honorable|Colleague)|"
    r"Sincerely,?|Respectfully\s+submitted)\b",
    re.I,
)
_RX_TTF_V1 = re.compile(
    r"^(?:\d+\s+|Page\s+\d+(?:\s+of\s+\d+)?\s+)?Truth in Testimony Disclosure Form\s+(?:In\s+|1\s+)?(?:ac)?cordance with Rule XI,\s*[ce]lause 2\(g\)\(5\)",
    re.I,
)
_RX_TTF_V2 = re.compile(
    r"^(?:\d+\s+|Page\s+\d+(?:\s+of\s+\d+)?\s+)?Truth in Testimony Disclosure Form\s+Witness Name:\s*.*?Position/Title:\s*.*?Witness Type:\s*Governmental\s+Non-governmental",
    re.I,
)
_RX_TTF_BESPOKE_EXACT_TITLE = re.compile(
    r"(?:[WV]?itness Disclosure Requirement\s*[-\u2013\u2014]\s*[\"\u201c\u00ab]?Truth in Testimony|"
    r"[\"\u201c\u00ab]?Truth in Testimony[\"\u201d\u00bb]?\s+Disclosure Form|"
    r"Required Witness Disclosure Form\s+House Rules|"
    r"Disclosure Form\s+As required by and provided for in House Rule XI|"
    r"Witness Disclosure Statement\s+Re[qg]uired by House Rule XI|"
    r"DISCLOSURE FORM FOR WITNESSES CONCERNING FEDERAL CONTRACT AND GRANT INFORMATION)",
    re.I,
)
_RX_TTF_BESPOKE_SLOTS = re.compile(
    r"(?:1\.\s*(?:Your\s+)?Name:|(?:Your|Xour|ur)\s+Nam[e:]|Witness Name:|Name:\s+[A-Z]|"
    r"Organization(?:s|\(s\))?\s+you\s+(?:are\s+)?represent|"
    r"INSTRUCTION\s+TO\s+WITNESSES:\s*Rule\s+(?:XI|11),\s*clause\s*2\(g\))",
    re.I,
)
_RX_TTF_GENERIC_HEAD = re.compile(
    r"truth\s+in\s+testimony|(?:required\s+)?[wv]itness\s+disclosure\s+(?:form|requirement|statement)",
    re.I,
)
_RX_TTF_GENERIC_FIELD = re.compile(
    r"(?:Witness\s+Name|(?:Your|Xour)\s+Name|\bName)\s*:"
    r"|Position\s*/?\s*Title\s*:"
    r"|Witness\s+Type\s*:"
    r"|Entity\(ies\)\s+you\s+are\s+representing"
    r"|Organization(?:\s+or\s+organizations)?\s+you(?:\s+are)?\s+represent"
    r"|Are\s+you\s+representing\s+yourself"
    r"|testifying\s+on\s+behalf\s+of",
    re.I,
)
_RX_TTF_GRANTS_CUE = re.compile(
    r"[fr]ederal\s+grants?"
    r"|subgrants?\s+(?:or|and)\s+subcontracts?"
    r"|grants?,\s+cooperative\s+agreements?,\s+or\s+contracts?"
    r"|Are\s+you\s+a\s+fiduciary"
    r"|originating\s+with\s+a\s+for(?:ei|ie)gn\s+government"
    r"|foreign\s+government\s+payments?",
    re.I,
)
_RX_TTF_UNBANNERED_112_115 = re.compile(
    r"^(?:\d+\s+)?(?:Witness\s+Name|Your\s+Name|Name)\s*:\s*[A-Z].{1,260}?\s+"
    r"(?:1|5)\.\s*(?:Please\s+list\s+)?any\s+federal\s+grants\s+or\s+contracts\s*\(including\s+subgrants\s+or\s+subcontracts\)"
    r".{0,160}?since\s+October\s+1",
    re.I,
)
_RX_TTF_NEG_STRICT = re.compile(
    r"\bDear\s+[A-Za-z]|\bSincerely\b|\bRespectfully\s+submitted\b"
    r"|pleased\s+to\s+invite|invit(?:e|ing)\s+you\s+to\s+testify|invitation\s+to\s+testify"
    r"|enclosed\s+please\s+find|please\s+find\s+enclosed|attached\s+please\s+find|please\s+find\s+attached"
    r"|\bThank\s+you,?\s+(?:Mr\.?|Madam|Chair(?:man|woman)?)"
    r"|\bThank\s+you\s+for\s+(?:agreeing|appearing)\b",
    re.I,
)
_RX_TTF_HEAD_NEG_STRICT = re.compile(
    r"^(?:\d+\s+)?(?:written\s+|prepared\s+|oral\s+|opening\s+)?(?:statement|testimony|remarks|biography|curriculum\s+vitae)\s+(?:of|by|from|:)\b"
    r"|^(?:\d+\s+)?(?:instructions|guidelines|information)\s+for\s+witnesses\b"
    r"|^(?:\d+\s+)?(?:RULES\s+(?:OF|FOR)\s+THE\s+COMMITTEE|AMENDMENT\s+TO\s+(?:THE\s+)?RULES)"
    r"|\bHEARING\s+BEFORE\s+THE\b"
    r"|\bNOTICE\s+OF\b|\b(?:HEARING|MARKUP|BUSINESS\s+MEETING)\s+NOTICE\b"
    r"|\bMEMORANDUM\b|M\s+E\s+M\s+O\s+R\s+A\s+N\s+D\s+U\s+M|\b(?:HEARING|MARKUP)\s+CHARTER\b",
    re.I,
)
_RX_TTF_ALLCAPS_RULES = re.compile(r"(?<!and the )\bRULES OF THE COMMITTEE\b")


def detect_ttf_page_signature(page_text: str) -> str | None:
    """Return exact Tier-1 TTF signature ID if `page_text` is a House Rule XI Truth-in-Testimony form."""
    if not page_text or len(page_text) < 80:
        return None
    t_ws = _norm_ws(page_text, 2600)
    if len(t_ws) < 80:
        return None
    t360 = t_ws[:360]
    t600 = t_ws[:600]
    t_low = t_ws[:1100].lower()
    t360_low = t_low[:360]

    has_tit_360 = "truth in testimony" in t360_low
    if has_tit_360:
        if (
            _RX_TTF_V1.match(t_ws[:260])
            and "filling in the provided blanks" in t_ws[:400]
            and not _RX_LETTER_SALUTATION.search(t600)
        ):
            return "ttf_clerk_acroform_v1_116_118"
        if _RX_TTF_V2.match(t_ws[:300]) and not _RX_LETTER_SALUTATION.search(t600):
            return "ttf_clerk_acroform_v2_118_119"

    if (
        has_tit_360
        or "disclosure" in t360_low
        or ("october 1" in t_low[:750] and "subgrants" in t_low[:750])
    ):
        t1000 = t_ws[:1000]
        if (
            not _RX_TTF_NEG_STRICT.search(t1000)
            and not _RX_TTF_HEAD_NEG_STRICT.search(t360)
            and not _RX_TTF_ALLCAPS_RULES.search(t360)
        ):
            t2400 = t_ws[:2400]
            if (
                (_RX_TTF_BESPOKE_EXACT_TITLE.search(t360) and _RX_TTF_BESPOKE_SLOTS.search(t1000))
                or (
                    _RX_TTF_GENERIC_HEAD.search(t_ws[:350])
                    and _RX_TTF_GENERIC_FIELD.search(t2400)
                    and _RX_TTF_GRANTS_CUE.search(t2400)
                )
                or _RX_TTF_UNBANNERED_112_115.match(t_ws[:750])
            ):
                return "ttf_committee_bespoke_form_112_118"
    return None


_EXPLICIT_NEG_VAL_RE = re.compile(
    r"^(?:none|none\.|n/?a|n\.a\.|no|no\.|not\s+applicable|not\s+applicable\.|zero|\$0(?:\.00)?|nothing|nil|-+|—+)$",
    re.I,
)
_SUBSTANTIVE_GRANT_POS_RE = re.compile(
    r"(?:\$\s*\d[\d,]*|₩\s*\d[\d,]*|\b\d{1,3}(?:,\d{3})+\b"
    r"|\bsee\s+(?:attached|attachment|attachments|addendum|appendix|below)\b"
    r"|\b(?:grant|subgrant|contract|subcontract|subrecipient|cooperative\s+agreement)s?\s+(?:from|with|under|award|no\.|#)"
    r"|\b(?:USDA|HHS|NIH|NSF|DOD|DOE|DOT|DOJ|DHS|EPA|USAID|SAMHSA|CMS|HRSA|CDC|FEMA|HUD|VA|NASA|NOAA|FAA|FRA|FTA)\b)"
)
_CHECKED_GLYPH_CHARS = "•●®◉☑☒✓✔■◆"
_UNCHECKED_GLYPH_CHARS = "Oo○◯☐□"


def _classify_grant_or_foreign_answer(ans: str) -> bool | None:
    """Return True/False ONLY when `ans` is 100% unambiguous; return None when blank or ambiguous."""
    s = _norm_ws(ans)
    s = re.sub(
        r"^(?:If\s+necessary,\s+attach\s+additional\s+sheet\(s\)\s+to\s+provide\s+more\s+information\.?\s*)",
        "",
        s,
        flags=re.I,
    ).strip()
    if not s:
        return None
    if _EXPLICIT_NEG_VAL_RE.match(s):
        return False
    if re.match(r"^(?:none|no)\b", s, re.I) and "$" not in s and not re.search(r"\b\d{4,}\b", s):
        return False
    if _SUBSTANTIVE_GRANT_POS_RE.search(s):
        return True
    return None


def extract_ttf_disclosure_booleans(
    ttf_text: str | None,
    sig_id: str | None = None,
) -> dict[str, Any]:
    """Extract 100%-precision unambiguous disclosure fields from a House Truth-in-Testimony form.

    Emits keys in strict `DISCLOSURE_KEYS_ORDER` (`capacity`, `gov_witness`, `has_federal_grants`,
    `has_foreign_payments`) ONLY when text evidence is 100% unambiguous (blank fields are omitted).
    """
    if not ttf_text:
        return {}
    t_ws = _norm_ws(ttf_text, 5000)
    if not t_ws:
        return {}
    if sig_id is None:
        sig_id = detect_ttf_page_signature(ttf_text)

    gov_witness: bool | None = None
    capacity: str | None = None
    has_fed_grants: bool | None = None
    has_for_payments: bool | None = None

    # 1. Witness Type: Governmental vs Non-governmental (Clerk AcroForm v1 text or unambiguous radio glyph)
    m_wt_plain = re.search(
        r"Witness\s+Type\s*:\s*(Non-governmental|Governmental)\s+(?:Are\s+you\s+representing|If\s+you)",
        t_ws,
        re.I,
    )
    if m_wt_plain:
        wt_val = m_wt_plain.group(1).lower()
        gov_witness = wt_val == "governmental"
        if gov_witness:
            capacity = "government"
    else:
        m_wt_radio = re.search(
            rf"Witness\s+Type\s*:\s*([{_CHECKED_GLYPH_CHARS}{_UNCHECKED_GLYPH_CHARS}])\s*Governmental\s*"
            rf"([{_CHECKED_GLYPH_CHARS}{_UNCHECKED_GLYPH_CHARS}])\s*Non-governmental",
            t_ws,
        )
        if m_wt_radio:
            g1, g2 = m_wt_radio.group(1), m_wt_radio.group(2)
            if g1 in _UNCHECKED_GLYPH_CHARS and g2 in _CHECKED_GLYPH_CHARS:
                gov_witness = False
            elif g1 in _CHECKED_GLYPH_CHARS and g2 in _UNCHECKED_GLYPH_CHARS:
                gov_witness = True
                capacity = "government"

    # 2. Capacity: Self vs Organization (Clerk AcroForm v1 plain value or unambiguous radio glyph)
    m_cap_plain = re.search(
        r"Are\s+you\s+representing\s+yourself\s+or\s+an\s+organization\?\s*(Organization|Self)\s+If\s+you\s+are\s+representing",
        t_ws,
        re.I,
    )
    if m_cap_plain and gov_witness is not True:
        capacity = m_cap_plain.group(1).lower()
    elif capacity is None and gov_witness is not True:
        m_cap_radio = re.search(
            rf"Are\s+you\s+representing\s+yourself\s+or\s+an\s+organization\?\s*"
            rf"([{_CHECKED_GLYPH_CHARS}{_UNCHECKED_GLYPH_CHARS}])\s*Self\s*"
            rf"([{_CHECKED_GLYPH_CHARS}{_UNCHECKED_GLYPH_CHARS}])\s*Organization",
            t_ws,
        )
        if m_cap_radio:
            c1, c2 = m_cap_radio.group(1), m_cap_radio.group(2)
            if c1 in _CHECKED_GLYPH_CHARS and c2 in _UNCHECKED_GLYPH_CHARS:
                capacity = "self"
            elif c1 in _UNCHECKED_GLYPH_CHARS and c2 in _CHECKED_GLYPH_CHARS:
                capacity = "organization"

    # 3. Clerk v1/v2 filled entity box -> confirms non-governmental organization vs self
    m_org_v1 = re.search(
        r"If\s+you\s+are\s+representing\s+an\s+organization,\s+please\s+list\s+what\s+entity\s+or\s+entities\s+you\s+are\s+representing:\s*(.+?)\s+"
        r"(?:If\s+you\s+are\s+a\s+non-governmental\s+witness|FOR\s+WITNESSES\s+APPEARING)",
        t_ws,
        re.I,
    )
    if m_org_v1 and gov_witness is not True:
        org_ans = m_org_v1.group(1).strip()
        if org_ans and not _EXPLICIT_NEG_VAL_RE.match(org_ans) and org_ans.lower() not in ("self", "myself", "individual"):
            if capacity is None:
                capacity = "organization"

    # 4. Clerk v1 & v2 Federal Grants & Foreign Payments blocks
    m_fed_block = re.search(
        r"Include\s+the\s+source\s+and\s+amount\s+of\s+each\s+grant\s+or\s+contract\."
        r"(?:\s*If\s+necessary,\s+attach\s+additional\s+sheet\(s\)\s+to\s+provide\s+more\s+information\.)?\s*(.*?)\s*"
        r"(?:If\s+you\s+are\s+a\s+non-governmental\s+witness,\s+please\s+list\s+any\s+contracts\s+or\s+payments\s+originating\s+with\s+a\s+foreign\s+government"
        r"|Please\s+list\s+any\s+contracts,\s+grants,\s+or\s+payments\s+originating\s+with\s+a\s+foreign\s+government)",
        t_ws,
        re.I,
    )
    if m_fed_block:
        has_fed_grants = _classify_grant_or_foreign_answer(m_fed_block.group(1))

    m_for_block = re.search(
        r"Include\s+the\s+amount\s+and\s+country\s+of\s+origin\s+of\s+each\s+contract\s+or\s+payment\."
        r"(?:\s*If\s+necessary,\s+attach\s+additional\s+sheet\(s\)\s+to\s+provide\s+more\s+information\.)?\s*(.*?)\s*"
        r"(?:False\s+Statements\s+Certification|Please\s+complete\s+the\s+following\s+fields\.|Are\s+you\s+a\s+fiduciary)",
        t_ws,
        re.I,
    )
    if m_for_block:
        has_for_payments = _classify_grant_or_foreign_answer(m_for_block.group(1))

    # In Clerk AcroForm v2, if the NON-GOVERNMENTAL CAPACITY section has filled answers, witness is non-gov
    if (
        gov_witness is None
        and "FOR WITNESSES APPEARING IN A NON-GOVERNMENTAL CAPACITY" in t_ws
        and (has_fed_grants is not None or has_for_payments is not None)
    ):
        gov_witness = False

    out: dict[str, Any] = {}
    if capacity in ("self", "organization", "government"):
        out["capacity"] = capacity
    if isinstance(gov_witness, bool):
        out["gov_witness"] = gov_witness
    if isinstance(has_fed_grants, bool):
        out["has_federal_grants"] = has_fed_grants
    if isinstance(has_for_payments, bool):
        out["has_foreign_payments"] = has_for_payments
    return out


# ---------------------------------------------------------------------------
# 3. Stapled Committee Roll-Call Vote & QFR Appendix Page Matchers (`p3..N`)
# ---------------------------------------------------------------------------

_RX_VOTE_HSWM = re.compile(
    r"^(?:\d+\s+|Page\s+\d+\s+)?VOTES OF THE COMMITTEE\s+In compliance with the Rules of the House of Representatives,\s+the following statement is made concerning the vote"
)
_RX_VOTE_YEAS_NAYS_PAIR = re.compile(r"\b(?:Yeas|Ayes)\b.*?\b(?:Nays|Noes)\b", re.I)
_RX_VOTE_NEG = re.compile(
    r"ROLL CALL ATTENDANCE/QUORUM CALL|\[To accompany\b|HOUSE OF REPRESENTATIVES\s*\{\s*REPORT\s+11\d|"
    r"Calendar No\.|SUMMARY OF ACTION|Sponsor\s+Summary and Text\s+Result",
    re.I,
)
_RX_VOTE_GEN_HEAD = re.compile(
    r"(?:FULL COMMITTEE (?:ROSTER )?ROLL CALL|SUBCOMMITTEE ROLL CALL|COMMITTEE ROLL CALL VOTE|"
    r"Roll Call Vote(?:\s+No\.|\s*#|\s+on\b)|RECORD VOTE NO\.\s*\d+|\bROLL CALL:\s*\d+|"
    r"\bROLL CALL NO\.\s*_*\d+|\bRoll Call\s+#\s*\d+)",
    re.I,
)
_RX_VOTE_GEN_TALLY = re.compile(
    r"(?:\b(?:YEAS?|AYES?)\s+(?:X*\s*)?(?:NAYS?|NOES?)(?:\s+PRESENT)?\b|"
    r"\(AYE\)\s*\d+\s*\(NO\)\s*\d+|"
    r"\b(?:Yeas?|Ayes?)\s*[:=-]?\s*\d+\s*[,;/]?\s*(?:Nays?|Noes?)\s*[:=-]?\s*\d+|"
    r"\bYEA/AYE\s+NAY/NO\b)",
    re.I,
)
_RX_P12_COMMITTEE_REPORT = re.compile(
    r"(?:\b1\d{2}(?:ST|ND|RD|TH)\s+CONGRESS\b.{0,120}\bREPORT\b.{0,120}\b(?:HOUSE OF REPRESENTATIVES|SENATE)\b"
    r"|\bCalendar\s+No\.\s*\d+|\[\s*To\s+accompany\s+(?:H\.\s*R\.|S\.))",
    re.I | re.S,
)
_RX_P12_TRANSCRIPT_BOOK = re.compile(
    r"(?:U\.?\s*S\.?\s+GOVERNMENT\s+(?:PUBLISHING|PRINTING)\s+OFFICE.{0,600}?\b(?:HEARINGS?|MARKUP)\s+BEFORE\s+(?:A\s+SUBCOMMITTEE\s+OF\s+)?THE\b"
    r"|Stenographic\s+Transcript\s+Before\s+the\s+(?:Subcommittee|Committee|Select\s+Committee|Permanent\s+Select\s+Committee))",
    re.I | re.S,
)


def detect_vote_page_signature(page_text: str) -> str | None:
    """Return exact Tier-1 `committee_vote` signature ID if `page_text` is a roll-call tally sheet."""
    if not page_text or len(page_text) < 80:
        return None
    t_ws = _norm_ws(page_text, 2000)
    if len(t_ws) < 80:
        return None
    t_low = t_ws[:420].lower()
    if "votes of the committee" in t_low[:260]:
        if _RX_VOTE_HSWM.match(t_ws[:260]) and _RX_VOTE_YEAS_NAYS_PAIR.search(t_ws[:1600]):
            return "vote_hswm_votes_of_committee"
    if "roll call" in t_low or "record vote" in t_low:
        if not _RX_VOTE_NEG.search(t_ws[:500]) and _RX_VOTE_GEN_HEAD.search(t_ws[:400]):
            if _RX_VOTE_GEN_TALLY.search(t_ws[:1600]):
                return "vote_committee_roll_call_tally_sheet"
    return None


# Line-anchored Title/UPPERCASE QFR appendix heading (excludes lowercase mid-sentence wraps)
_RX_QFR_PAGE_HEADING = re.compile(
    r"(?:^|\n)\s*(?:Page\s+\d+(?:\s+of\s+\d+)?\s+|\d{1,4}\s+)?"
    r"(?:(?:Attachment|ATTACHMENT|Appendix|APPENDIX)\s*[A-Z0-9]*\s*[-\u2013\u2014:]\s*)?"
    r"(?:(?:Post[- ]Hearing|POST[- ]HEARING|Additional|ADDITIONAL|Written|WRITTEN|"
    r"Supplemental|SUPPLEMENTAL|Follow[- ]Up|FOLLOW[- ]UP|"
    r"Responses?\s+to|RESPONSES?\s+TO|Answers?\s+to|ANSWERS?\s+TO)\s+)?"
    r"(?:Questions|QUESTIONS)\s+(?:(?:Submitted|SUBMITTED)\s+)?(?:for\s+the\s+(?:Hearing\s+)?Record|FOR\s+THE\s+(?:HEARING\s+)?RECORD)\b"
)
_RX_QFR_ATTRIBUTION = re.compile(
    r"(?:Questions\s+(?:Submitted\s+)?for\s+the\s+(?:Hearing\s+)?Record\s+(?:Submitted\s+(?:to|by)|from|for|to)\s+[A-Z]"
    r"|\bQuestions?\s+(?:from|by|submitted\s+by)\s+(?:Chairman|Chairwoman|Chair|Ranking\s+Member|"
    r"Senator|Rep\.|Representative|Congressman|Congresswoman|The\s+Honorable|Hon\.)"
    r"|\b(?:Responses?|Answers?)\s+to\s+Questions\s+for\s+the\s+(?:Hearing\s+)?Record\s+(?:from|by|to|submitted\s+by)\s+[A-Z])",
    re.I,
)
_RX_QFR_PROMPT_STRUCT = re.compile(
    r"(?:(?:^|\n)\s*(?:Question\s*\d*\s*[:.]|Q\.?\s*\d*\s*[:.)]|\d{1,2}\.\s+[A-Z][^\n]{15,}\?)"
    r"|\b(?:Response|Answer)\s*:\s+[A-Z]"
    r"|\[(?:No\s+response\s+was\s+received|RESPONSE\s+NOT\s+RECEIVED)[^\]]*\])",
    re.I,
)
_RX_QFR_NEG_COLLOQUY_OR_TOC = re.compile(
    r"(?:\.{5,}\s*\d+"
    r"|\b(?:Mr\.|Ms\.|Mrs\.|Senator|Chairman|Chairwoman|Representative)\s+[A-Z]{2,}\.\s+"
    r"|\byield\s+back\b|\bhappy\s+to\s+answer\s+any\s+questions\b)",
)
# Exclude documents where p1-2 is ALREADY a standalone QFR question/response packet
_RX_P12_ALREADY_QFR = re.compile(
    r"(?:(?:Questions?|QUESTIONS?)\s+(?:Submitted\s+|SUBMITTED\s+)?(?:for\s+the\s+(?:Hearing\s+)?Record|FOR\s+THE\s+(?:HEARING\s+)?RECORD)"
    r"|(?:(?:Written|Post[- ]Hearing|Follow[- ]Up|Additional|Hearing)\s+)?Questions\s+(?:for|to|from|submitted)\b.{0,320}?(?:\b1\.\s+[A-Z]|\bQuestion\s*1\b|\bQ\.?\s*1\b)"
    r"|\bHearing\s+Questions\s+1\.\s+[A-Z]"
    r"|\bResponses?\s+to\s+(?:Senator|Representative|Rep\.|Chairman|Chairwoman|Ranking\s+Member)\s+[A-Z].{0,200}?\b1\.\s+[A-Z]"
    r"|\bQuestion\s*1\s*[:.].{10,900}?\b(?:Answer|Response)\s*:)",
    re.I | re.S,
)


def match_qfr_appendix_page(page_text: str) -> int | None:
    """Return heading char offset if `page_text` (`p3..N`) is a formal QFR appendix page, else None."""
    if not page_text or len(page_text) < 100:
        return None
    if "questions" not in page_text[:1200].lower():
        return None
    m_head = _RX_QFR_PAGE_HEADING.search(page_text[:1200])
    if m_head is None:
        return None
    tail = page_text[m_head.start() :]
    if _RX_QFR_NEG_COLLOQUY_OR_TOC.search(tail[:1000]):
        return None
    norm1400 = _norm_ws(tail, 1400)
    if not _RX_QFR_ATTRIBUTION.search(norm1400):
        return None
    if not _RX_QFR_PROMPT_STRUCT.search(tail[:2000]):
        return None
    return m_head.start()


def is_qfr_appendix_page(page_text: str) -> bool:
    """True ONLY when `page_text` (`p3..N`) is a formal Questions for the Record appendix page."""
    return match_qfr_appendix_page(page_text) is not None


def detect_stapled_backpage_packets(
    pages: Sequence[str],
    filename: str | None = None,
    p12_text: str | None = None,
) -> dict[str, Any]:
    """Scan `p3..N` (`pages[2:]`) for stapled TTF disclosure forms, Roll-Call Votes, and QFR appendices."""
    empty = {
        "stapled_ttf_page": None,
        "stapled_ttf_sig_id": None,
        "stapled_ttf_slice": None,
        "stapled_ttf_disclosure": None,
        "stapled_vote_page": None,
        "stapled_vote_sig_id": None,
        "stapled_vote_slice": None,
        "p12_is_committee_report": False,
        "stapled_qfr_page": None,
        "stapled_qfr_slice": None,
    }
    if len(pages) <= 2:
        return empty

    p12 = p12_text if p12_text is not None else (pages[0] + pages[1])
    p12_is_ttf = (
        detect_ttf_page_signature(p12) is not None
        or detect_ttf_page_signature(pages[0]) is not None
        or detect_ttf_page_signature(pages[1]) is not None
    )
    p12_is_vote = (
        detect_vote_page_signature(p12) is not None
        or detect_vote_page_signature(pages[0]) is not None
        or detect_vote_page_signature(pages[1]) is not None
    )
    p12_is_qfr = bool(_RX_P12_ALREADY_QFR.search(p12[:1800]))
    p12_is_transcript_book = bool(
        _RX_P12_TRANSCRIPT_BOOK.search(p12[:2200])
        or is_gpo_cover_roster_only_p12(p12)
        or is_steno_cover_roster_only_p12(p12)
    )
    p12_is_report = bool(_RX_P12_COMMITTEE_REPORT.search(p12[:1200]))

    stapled_ttf_page: int | None = None
    stapled_ttf_sig_id: str | None = None
    stapled_ttf_slice: str | None = None
    stapled_ttf_disclosure: dict[str, Any] | None = None

    stapled_vote_page: int | None = None
    stapled_vote_sig_id: str | None = None
    stapled_vote_slice: str | None = None

    stapled_qfr_page: int | None = None
    stapled_qfr_slice: str | None = None

    n_pages = len(pages)
    for idx in range(2, n_pages):
        pg = pages[idx]
        if not pg or len(pg) < 80:
            continue
        pno = idx + 1  # 1-indexed

        # (a) Stapled Truth-in-Testimony disclosure form (on non-transcript-book packets where p1-2 != TTF)
        if stapled_ttf_page is None and not p12_is_ttf and not p12_is_transcript_book:
            low_head = pg[:450].lower()
            if "truth in testimony" in low_head or "disclosure" in low_head or "subgrants" in pg[:700].lower():
                t_sig = detect_ttf_page_signature(pg)
                if t_sig is not None:
                    stapled_ttf_page = pno
                    stapled_ttf_sig_id = t_sig
                    # Include next page when a 2-page Clerk AcroForm continues onto `idx + 1`
                    ttf_span = pg.strip()
                    if idx + 1 < n_pages and t_sig in ("ttf_clerk_acroform_v1_116_118", "ttf_clerk_acroform_v2_118_119"):
                        ttf_span = (ttf_span + "\n" + pages[idx + 1].strip())
                    stapled_ttf_slice = ttf_span[:1800].rstrip()
                    disc = extract_ttf_disclosure_booleans(ttf_span, sig_id=t_sig)
                    stapled_ttf_disclosure = disc if disc else None

        # (b) Stapled Committee Roll-Call Vote tally sheet (where p1-2 != vote, report, or transcript book)
        if (
            stapled_vote_page is None
            and not p12_is_vote
            and not p12_is_transcript_book
            and not p12_is_report
        ):
            low_head_v = pg[:450].lower()
            if "roll call" in low_head_v or "record vote" in low_head_v or "votes of the committee" in low_head_v:
                v_sig = detect_vote_page_signature(pg)
                if v_sig is not None:
                    stapled_vote_page = pno
                    stapled_vote_sig_id = v_sig
                    stapled_vote_slice = pg.strip()[:1200].rstrip()

        # (c) Stapled Questions for the Record appendix (`p3..N`)
        if stapled_qfr_page is None and not p12_is_qfr:
            if "questions" in pg[:1200].lower():
                qfr_off = match_qfr_appendix_page(pg)
                if qfr_off is not None:
                    stapled_qfr_page = pno
                    stapled_qfr_slice = pg[qfr_off:].strip()[:1200].rstrip()

        if (
            (stapled_ttf_page is not None or p12_is_ttf or p12_is_transcript_book)
            and (stapled_vote_page is not None or p12_is_vote or p12_is_transcript_book or p12_is_report)
            and (stapled_qfr_page is not None or p12_is_qfr)
        ):
            break

    return {
        "stapled_ttf_page": stapled_ttf_page,
        "stapled_ttf_sig_id": stapled_ttf_sig_id,
        "stapled_ttf_slice": stapled_ttf_slice,
        "stapled_ttf_disclosure": stapled_ttf_disclosure,
        "stapled_vote_page": stapled_vote_page,
        "stapled_vote_sig_id": stapled_vote_sig_id,
        "stapled_vote_slice": stapled_vote_slice,
        "p12_is_committee_report": p12_is_report,
        "stapled_qfr_page": stapled_qfr_page,
        "stapled_qfr_slice": stapled_qfr_slice,
    }


def extract_multipage_signals_v5(
    text: str | None,
    page_offsets: Sequence[int] | None,
    filename: str | None = None,
) -> dict[str, Any]:
    """Unified Phase 4 multi-page deterministic extractor (`100%` Python stdlib)."""
    pages = split_pdf_pages(text, page_offsets)
    num_pages = len(pages)
    if num_pages <= 2:
        return {
            "num_pages": num_pages,
            "is_multipage_gt2": False,
            "is_cover_roster_p12": False,
            "cover_roster_kind": None,
            "p3_toc_or_gavel_page": None,
            "p3_toc_or_gavel_slice": None,
            "has_gpo_p3_witness_panel": False,
            "stapled_ttf_page": None,
            "stapled_ttf_sig_id": None,
            "stapled_ttf_slice": None,
            "stapled_ttf_disclosure": None,
            "stapled_vote_page": None,
            "stapled_vote_sig_id": None,
            "stapled_vote_slice": None,
            "p12_is_committee_report": False,
            "stapled_qfr_page": None,
            "stapled_qfr_slice": None,
        }

    p12 = pages[0] + pages[1]
    gpo_res = extract_gpo_p3_p8_rescue(pages, p12_text=p12)
    pkt_res = detect_stapled_backpage_packets(pages, filename=filename, p12_text=p12)
    return {
        "num_pages": num_pages,
        "is_multipage_gt2": True,
        **gpo_res,
        **pkt_res,
    }


# ---------------------------------------------------------------------------
# 4. Deterministic HTTP / Empty / Unreadable Triage Helper
# ---------------------------------------------------------------------------

_RX_HTML_HTTP_ERROR_SHELL = re.compile(
    r"^(?:\s*(?:404\s+Not\s+Found|403\s+Forbidden|500\s+Internal\s+Server\s+Error|"
    r"502\s+Bad\s+Gateway|503\s+Service\s+Unavailable|Page\s+Not\s+Found\s*[-|]|"
    r"Access\s+Denied\s+You\s+don't\s+have\s+permission\s+to\s+access|"
    r"Attention\s+Required!\s*\|\s*Cloudflare|Just\s+a\s+moment\.\.\.\s*Enable\s+JavaScript\s+and\s+cookies))",
    re.I,
)


def triage_unwrapped_http_or_empty(
    text: str | None,
    *,
    http_status: int | None = None,
    known_valid_empty: bool = False,
    body_state: str | None = None,
) -> tuple[str | None, str | None]:
    """Return `(triage_status, error_reason)` ONLY when non-usable status is 100% deterministic.

    Returns `(None, None)` for all usable documents (including short notices, exhibits, and
    redacted investigative artifacts).
    """
    if http_status is not None and (http_status in (401, 403, 404, 410, 429) or 500 <= http_status <= 599):
        return "error_or_block", f"HTTP {http_status} response envelope"

    t_norm = _norm_ws(text or "", 400)
    if t_norm and len(t_norm) < 260 and _RX_HTML_HTTP_ERROR_SHELL.match(t_norm):
        return "error_or_block", t_norm[:120]

    if not t_norm:
        if known_valid_empty:
            return "stub_or_blank", "Certified empty/photographic page without extractable text"
        if body_state == "unreadable":
            return "ocr_unreadable", "Corrupt or unreadable binary container"
        if body_state == "error":
            return "error_or_block", "Upstream capture error without document body"

    return None, None
