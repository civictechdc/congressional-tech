"""Lightweight DocMeta V7 deterministic pre-extractors and shared window bridge (`ct-f2ai`).

Pure stdlib + Pydantic enum types (`DocStatus`), with zero legacy V4-V6.5 or
external orchestrator dependencies. Shares `viewer_publication.body_text_slices.docmeta_v7_window`
as the single canonical 9,000-char window producer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import re
from typing import Any, Sequence

from viewer_publication.body_text_slices import (
    DOCMETA_V7_WINDOW_MAX_CHARS,
    DOCMETA_V7_WINDOW_SPEC,
    docmeta_v7_window,
    strip_invisible_format_chars,
)

from .models import DocStatus

_TAIL_MARKER_RE = re.compile(r"\[\.\.\.\s*page\s+\d+\s+tail\s*\.\.\.\]", re.IGNORECASE)
_GPO_ERRATA_RE = re.compile(r"\[\s*ERRATA\s*\]|\bGPO\s+ERRATA\b", re.IGNORECASE)

_XML_HEAD_RE = re.compile(
    r"^\s*(?:<\?xml\b|<(?:modsCollection|mods|billStatus|bill|amendment|resolution|documentMetadata)\b)",
    re.IGNORECASE,
)
_WAF_BLOCK_RE = re.compile(
    r"\b(?:403\s+Forbidden|404\s+(?:File\s+or\s+Directory\s+)?Not\s+Found|Access\s+Denied|"
    r"Attention\s+Required!\s*\|\s*Cloudflare|Enable\s+JavaScript\s+and\s+cookies\s+to\s+continue|"
    r"Just\s+a\s+moment\.\.\.|Request\s+blocked\s+by\s+security\s+rules|ERR_TOO_MANY_REDIRECTS)\b",
    re.IGNORECASE,
)
_GOVINFO_WRAPPER_RE = re.compile(
    r"\b(?:GovInfo\s*\|?\s*U\.S\.\s+Government\s+Publishing\s+Office|THOMAS\s+Home\s*\|\s*Library\s+of\s+Congress|"
    r"Authenticate\s+this\s+official\s+document\s+with\s+the\s+seal|PDF\s+details\s+and\s+metadata)\b",
    re.IGNORECASE,
)

_BILL_RE = re.compile(
    r"\b(H\.?\s*R\.?|S\.|H\.?\s*J\.?\s*Res\.?|S\.?\s*J\.?\s*Res\.?|"
    r"H\.?\s*Con\.?\s*Res\.?|S\.?\s*Con\.?\s*Res\.?|H\.?\s*Res\.?|S\.?\s*Res\.?)\s*(\d{1,5})\b",
    re.IGNORECASE,
)
_PL_RE = re.compile(r"\b(?:Public\s+Law|Pub\.?\s*L\.?)\s*(?:No\.?\s*)?(\d{2,3})\s*[-–—]\s*(\d{1,4})\b", re.IGNORECASE)
_USC_RE = re.compile(r"\b(\d{1,2})\s+U\.?\s*S\.?\s*C\.?(?:\s*(?:§§?|Sec(?:tion)?\.?))?\s*(\d+[a-zA-Z0-9-]*)\b")
_CFR_RE = re.compile(r"\b(\d{1,2})\s+C\.?\s*F\.?\s*R\.?\s*(?:Part\s+|§§?\s*)?(\d+(?:\.[A-Za-z0-9-]+)*)\b", re.IGNORECASE)
_EO_RE = re.compile(r"\b(?:Executive\s+Order|E\.?\s*O\.?)\s*(?:No\.?\s*)?(1\d{4})\b", re.IGNORECASE)
_GPO_SERIAL_RE = re.compile(r"\b([HS]\.\s*(?:Hrg\.|Rept\.|Doc\.|Prt\.)\s*\d{2,3}\s*[-–—]\s*\d{1,5}[A-Za-z]?)\b")
_HHRG_RE = re.compile(r"\b((?:HHRG|CHRG|HMKP|HMTG|S?\d{3}[A-Z]{2}\d{2}|CRPT|HRPT|SRPT)-\d{2,3}-[A-Za-z0-9-]+)\b")
_NUMERIC_CONGRESS_RE = re.compile(r"\b(9\d|1\d{2})(?:st|nd|rd|th)\s+Congress\b", re.IGNORECASE)
_WRITTEN_CONGRESS_RE = re.compile(
    r"\bONE\s+HUNDRED\s+(?:AND\s+)?(TENTH|ELEVENTH|TWELFTH|THIRTEENTH|FOURTEENTH|FIFTEENTH|"
    r"SIXTEENTH|SEVENTEENTH|EIGHTEENTH|NINETEENTH|TWENTIETH)\s+CONGRESS\b",
    re.IGNORECASE,
)
_WRITTEN_CONGRESS_MAP: dict[str, int] = {
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

_MONTHS = {
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
_MONTH_DATE_RE = re.compile(
    r"\b(January|Jan\.?|February|Feb\.?|March|Mar\.?|April|Apr\.?|May|June|Jun\.?|July|Jul\.?|"
    r"August|Aug\.?|September|Sept?\.?|October|Oct\.?|November|Nov\.?|December|Dec\.?)\s+"
    r"(\d{1,2}),\s*((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b((?:19|20)\d{2})-(\d{2})-(\d{2})\b")

_BILL_PREFIX_CANON = {
    "hr": "H.R.",
    "s": "S.",
    "hjres": "H.J.Res.",
    "sjres": "S.J.Res.",
    "hconres": "H.Con.Res.",
    "sconres": "S.Con.Res.",
    "hres": "H.Res.",
    "sres": "S.Res.",
}


@dataclass(frozen=True, slots=True)
class PreExtractResult:
    """Deterministic structural & citation hints extracted prior to student inference."""

    deterministic_status: DocStatus | None
    deterministic_reason: str | None
    is_blank_or_stub_head_tail: bool
    is_gpo_errata_slip: bool
    bill_refs: tuple[str, ...]
    public_laws: tuple[str, ...]
    usc_refs: tuple[str, ...]
    cfr_refs: tuple[str, ...]
    executive_orders: tuple[str, ...]
    gpo_serials: tuple[str, ...]
    hhrg_tokens: tuple[str, ...]
    congress_hint: int | None
    date_hints: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        if self.deterministic_status is not None:
            out["deterministic_status"] = self.deterministic_status.value
        for k in (
            "bill_refs",
            "public_laws",
            "usc_refs",
            "cfr_refs",
            "executive_orders",
            "gpo_serials",
            "hhrg_tokens",
            "date_hints",
        ):
            out[k] = list(out[k])
        return out


def _dedupe_preserve(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(out)


def detect_non_usable_status(
    text: str,
    *,
    effective_format: str | None = None,
) -> tuple[DocStatus | None, str | None]:
    """Conservatively detect unambiguous non-usable stubs (zero false positives on real docs)."""
    cleaned = strip_invisible_format_chars(text or "").strip()
    non_ws = len(" ".join(cleaned.split()))
    if non_ws < 20:
        return DocStatus.stub_or_blank, "empty_or_sub_20_non_ws"

    fmt = (effective_format or "").strip().lower()
    if _XML_HEAD_RE.match(cleaned) and (fmt in {"", "xml", "mods"} or "</mods>" in cleaned or "</billStatus>" in cleaned):
        return DocStatus.catalog_xml, "xml_catalog_envelope"

    if len(cleaned) < 2500 and _WAF_BLOCK_RE.search(cleaned):
        return DocStatus.error_or_block, "waf_or_http_error_stub"

    if len(cleaned) < 2500 and _GOVINFO_WRAPPER_RE.search(cleaned) and "testimony" not in cleaned.lower():
        return DocStatus.govinfo_wrapper, "govinfo_or_thomas_wrapper"

    return None, None


def extract_deterministic_signals(
    text: str,
    *,
    effective_format: str | None = None,
) -> PreExtractResult:
    """Extract conservative deterministic triage flags and normalized citation/date hints."""
    cleaned = strip_invisible_format_chars(text or "")
    det_status, det_reason = detect_non_usable_status(cleaned, effective_format=effective_format)

    tail_m = _TAIL_MARKER_RE.search(cleaned)
    is_stub_tail = bool(tail_m is not None and len(" ".join(cleaned[: tail_m.start()].split())) < 80)
    is_errata = bool(_GPO_ERRATA_RE.search(cleaned[:1200]))

    bills: list[str] = []
    for raw_pfx, num in _BILL_RE.findall(cleaned):
        key = re.sub(r"[\s.]+", "", raw_pfx).lower()
        canon = _BILL_PREFIX_CANON.get(key)
        if canon:
            bills.append(f"{canon} {int(num)}")

    plaws = [f"Pub. L. {int(c)}-{int(n)}" for c, n in _PL_RE.findall(cleaned)]
    uscs = [f"{int(t)} U.S.C. {sec}" for t, sec in _USC_RE.findall(cleaned)]
    cfrs = [f"{int(t)} C.F.R. {sec}" for t, sec in _CFR_RE.findall(cleaned)]
    eos = [f"E.O. {num}" for num in _EO_RE.findall(cleaned)]
    serials = [re.sub(r"\s*[–—-]\s*", "-", " ".join(s.split())) for s in _GPO_SERIAL_RE.findall(cleaned)]
    hhrgs = _HHRG_RE.findall(cleaned)

    congress_hint: int | None = None
    m_cong = _NUMERIC_CONGRESS_RE.search(cleaned)
    if m_cong:
        congress_hint = int(m_cong.group(1))
    else:
        m_wcong = _WRITTEN_CONGRESS_RE.search(cleaned)
        if m_wcong:
            congress_hint = _WRITTEN_CONGRESS_MAP.get(m_wcong.group(1).upper())

    dates: list[str] = []
    for y_s, m_s, d_s in _ISO_DATE_RE.findall(cleaned):
        try:
            dates.append(date(int(y_s), int(m_s), int(d_s)).isoformat())
        except ValueError:
            pass
    for mon_s, day_s, yr_s in _MONTH_DATE_RE.findall(cleaned):
        mon_num = _MONTHS.get(mon_s.rstrip(".").lower())
        if mon_num is not None:
            try:
                dates.append(date(int(yr_s), mon_num, int(day_s)).isoformat())
            except ValueError:
                pass

    return PreExtractResult(
        deterministic_status=det_status,
        deterministic_reason=det_reason,
        is_blank_or_stub_head_tail=is_stub_tail,
        is_gpo_errata_slip=is_errata,
        bill_refs=_dedupe_preserve(bills),
        public_laws=_dedupe_preserve(plaws),
        usc_refs=_dedupe_preserve(uscs),
        cfr_refs=_dedupe_preserve(cfrs),
        executive_orders=_dedupe_preserve(eos),
        gpo_serials=_dedupe_preserve(serials),
        hhrg_tokens=_dedupe_preserve(hhrgs),
        congress_hint=congress_hint,
        date_hints=_dedupe_preserve(dates),
    )


def build_v7_text_window(
    text: str | None,
    page_offsets: Sequence[int] = (),
    *,
    rescued_text: str | None = None,
    rescued_status: str | None = None,
    max_chars: int = DOCMETA_V7_WINDOW_MAX_CHARS,
    head_pages: int = 2,
    tail_chars: int = 2400,
) -> dict[str, Any]:
    """Delegate directly to `viewer_publication.body_text_slices.docmeta_v7_window` (single owner)."""
    return docmeta_v7_window(
        text,
        page_offsets,
        rescued_text=rescued_text,
        rescued_status=rescued_status,
        max_chars=max_chars,
        head_pages=head_pages,
        tail_chars=tail_chars,
    )


__all__ = [
    "DOCMETA_V7_WINDOW_MAX_CHARS",
    "DOCMETA_V7_WINDOW_SPEC",
    "PreExtractResult",
    "build_v7_text_window",
    "detect_non_usable_status",
    "extract_deterministic_signals",
]
