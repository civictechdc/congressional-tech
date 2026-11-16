"""Published bill type/version vocabularies; retain unlisted source tokens.

Source: https://www.govinfo.gov/help/bills (checked 2026-09-29).
The page calls its version table common versions, not an exhaustive validity list.
A version describes a text edition; its chamber need not be the bill origin.
"""

from __future__ import annotations

import functools
import re
from typing import Any

BILLS_HELP_URL = "https://www.govinfo.gov/help/bills"
BILLS_HELP_CHECKED_ON = "2026-09-29"

MIN_CONGRESS = 1
MAX_CONGRESS = 130
MAX_BILL_NUMBER_DIGITS = 5

_SHA_PREFIX_RE = re.compile(r"^[0-9a-fA-F]{64}\.", re.ASCII)
_BILLS_EXT_RE = re.compile(
    r"\.(?:pdf|xml|html?|docx?|xlsx?|pptx?|txt|rtf|zip|csv|tsv|xsd|aspx|cfm)(?:[?&].*)?$",
    re.I | re.ASCII,
)
_BILLS_REV_RE = re.compile(r"-[Uu][1-9][0-9]{0,9}(?:_[0-9]+)?$", re.ASCII)
_BILLS_HEAD_RE = re.compile(r"^BILLS(?P<sep>\s*-\s*|\s*_\s*|-?)(?P<rest>.+)$", re.I | re.ASCII)
_MEASURE_CODE_PAT = r"(?:hconres|sconres|hjres|sjres|hres|sres|hr|s)"
_EXPLICIT_CONG_AND_TYPED_RE = re.compile(
    rf"^(?P<congress>[1-9][0-9]{{0,2}})[-_ ]*(?P<measure>{_MEASURE_CODE_PAT})(?P<number>[1-9][0-9]{{0,4}}|0{{1,5}})(?P<tail>(?:[^0-9].*)?)$",
    re.I | re.ASCII,
)
_DELIMITED_CONG_AND_UNTYPED_RE = re.compile(
    r"^(?P<congress>[1-9][0-9]{0,2})[-_]+(?P<number>[1-9][0-9]{0,4}|0{1,5})(?P<tail>(?:[^0-9].*)?)$",
    re.I | re.ASCII,
)
_CONCAT_3DIGIT_CONG_RE = re.compile(
    r"^(?P<congress>1(?:[0-2][0-9]|30))(?P<number>[1-9][0-9]{0,4}|0{1,5})(?P<tail>(?:[^0-9].*)?)$",
    re.I | re.ASCII,
)
_CONCAT_JAMMED_MEASURE_RE = re.compile(
    rf"^[0-9]{{4,}}-?{_MEASURE_CODE_PAT}(?:[0-9]+|[-_])",
    re.I | re.ASCII,
)


def is_valid_congress(congress: int | str | None) -> bool:
    """Return True when ``congress`` is an integer (or canonical digit string) in ``1..130``."""
    if isinstance(congress, bool) or congress is None:
        return False
    if isinstance(congress, int):
        return MIN_CONGRESS <= congress <= MAX_CONGRESS
    if isinstance(congress, str):
        s = congress.strip()
        if not s or not s.isascii() or not s.isdigit() or (len(s) > 1 and s.startswith("0")):
            return False
        return MIN_CONGRESS <= int(s) <= MAX_CONGRESS
    return False


@functools.cache
def _known_stage_codes() -> frozenset[str]:
    from .catalog import load_guide
    guide = load_guide()
    return frozenset({
        'pis',
        *guide["codes"].get("version", {}).keys(),
        *guide["codes"].get("consideration", {}).keys(),
        *guide["extraction_vocabularies"].get("govinfo-bill-versions", {}).keys(),
        *guide["extraction_vocabularies"].get("house-version-overrides", {}).keys(),
    })


def _extract_stage_prefix(tail: str) -> str | None:
    if not tail:
        return None
    cleaned = tail.lstrip("-_")
    m = re.match(r"^(?:r[0-9]+)?([A-Za-z]{2,8})(?=$|[^A-Za-z])", cleaned, re.ASCII)
    if not m:
        return None
    cand = m.group(1).lower()
    return cand if cand in _known_stage_codes() else None


def split_bills_congress_and_number(slug_or_filename: str | None) -> dict[str, Any] | None:
    """Validate and split a ``BILLS`` slug into bounded Congress (`1..130`) and bill number.

    Guards against malformed GPO/committee ``BILLS-`` slugs where:
      - a 3-digit Congress (`100..130`) and bill number (`1..5` digits) were concatenated
        without a delimiter or measure code (e.g. ``BILLS-1152823ih.pdf`` -> Congress ``115``
        + bill ``2823``, NEVER Congress ``1152823``),
      - multiple Congresses or extra digits were jammed before a measure code
        (e.g. ``BILLS-114119hr1ih.pdf``, ``BILLS-1152823hr2823ih.pdf``, ``BILLS-1117s2126-SUS.pdf`` -> ``None``),
      - an implausible Congress ``> 130`` or ``< 1`` appears (e.g. ``BILLS-9992823ih.pdf``,
        ``BILLS-150hr1ih.pdf``, or mis-grouped ``BILLS-932823ih.pdf`` -> ``None``).
    """
    if not isinstance(slug_or_filename, str):
        return None
    base = slug_or_filename.strip().rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    base = _SHA_PREFIX_RE.sub("", base)
    while True:
        stripped = _BILLS_EXT_RE.sub("", base)
        if stripped == base:
            break
        base = stripped
    base = _BILLS_REV_RE.sub("", base)
    m_head = _BILLS_HEAD_RE.match(base)
    if not m_head:
        return None
    has_prefix_sep = bool(m_head.group("sep").strip())
    rest = m_head.group("rest")

    # Hard guard: 4+ leading digits jammed before a measure code (e.g. 114119hr1ih, 1117-s2126-SUS, 114119hr-PIH-Draft)
    if _CONCAT_JAMMED_MEASURE_RE.match(rest):
        return None

    # 1. Explicit measure code (e.g. BILLS-115hr2823ih, BILLS-115-HR2823ih, BILLS-93hr2823ih, BILLS112hr2576ih)
    m_typed = _EXPLICIT_CONG_AND_TYPED_RE.match(rest)
    if m_typed:
        c_raw = m_typed.group("congress")
        if not is_valid_congress(c_raw):
            return None
        cong = int(c_raw)
        if not has_prefix_sep and cong < 100:
            return None
        tail = m_typed.group("tail")
        # Reject ordinal tails adjoining digits (e.g. HR2534116thCongress)
        if re.match(r"^(?:st|nd|rd|th)(?:[ _-]|[A-Z]|Congress|Century|$)", tail, re.I | re.ASCII):
            return None
        num_raw = m_typed.group("number")
        num_val = int(num_raw) if int(num_raw) > 0 else None
        return {
            "congress": cong,
            "measure_type": m_typed.group("measure").lower(),
            "measure_number": num_val,
            "number_token": num_raw,
            "stage": _extract_stage_prefix(tail),
            "was_concatenated": not has_prefix_sep,
        }

    # 2. Explicitly delimited Congress and untyped number (e.g. BILLS-115-2823ih)
    m_delim = _DELIMITED_CONG_AND_UNTYPED_RE.match(rest)
    if m_delim:
        c_raw = m_delim.group("congress")
        if not is_valid_congress(c_raw):
            return None
        cong = int(c_raw)
        if not has_prefix_sep and cong < 100:
            return None
        tail = m_delim.group("tail")
        if re.match(r"^(?:st|nd|rd|th)(?:[ _-]|[A-Z]|Congress|Century|$)", tail, re.I | re.ASCII):
            return None
        # Guard against local compound identifiers, Bioguide sponsor Amdt slots, prints, and appropriations
        if re.match(r"^[-_]+[0-9X_]+", tail, re.I | re.ASCII):
            return None
        if re.match(r"^[-_]+[A-Za-z][A-Za-z0-9]{6}-Amdt-", tail, re.I | re.ASCII):
            return None
        if re.search(r"(?:^|[-_])(?:AP-|CommitteePrint|CmtePrint|HAmdt)", tail, re.I | re.ASCII):
            return None
        stage = _extract_stage_prefix(tail)
        if tail and not tail.startswith(("-", "_")) and stage is None:
            return None
        num_raw = m_delim.group("number")
        num_val = int(num_raw) if int(num_raw) > 0 else None
        return {
            "congress": cong,
            "measure_type": None,
            "measure_number": num_val,
            "number_token": num_raw,
            "stage": stage,
            "was_concatenated": not has_prefix_sep,
        }

    # 3. Unambiguous concatenated 1\d{2} (100..130) Congress + 1..5-digit bill number + stage (e.g. BILLS-1152823ih)
    m_concat = _CONCAT_3DIGIT_CONG_RE.match(rest)
    if m_concat:
        cong = int(m_concat.group("congress"))
        num_raw = m_concat.group("number")
        tail = m_concat.group("tail")
        if re.match(r"^(?:st|nd|rd|th)(?:[ _-]|[A-Z]|Congress|Century|$)", tail, re.I | re.ASCII):
            return None
        # Concatenated untyped digits require a direct stage code without a hyphenated non-bill tail
        if tail.startswith(("-", "_")):
            return None
        stage = _extract_stage_prefix(tail)
        if stage is None:
            return None
        num_val = int(num_raw) if int(num_raw) > 0 else None
        return {
            "congress": cong,
            "measure_type": None,
            "measure_number": num_val,
            "number_token": num_raw,
            "stage": stage,
            "was_concatenated": True,
        }

    return None


parse_bills_slug = split_bills_congress_and_number


@functools.cache
def _get_vocabularies() -> dict[str, Any]:
    from .catalog import load_guide
    return load_guide()['extraction_vocabularies']


@functools.cache
def get_bill_types() -> dict[str, str]:
    return {key: value['label'] for key, value in _get_vocabularies()['govinfo-bill-types'].items()}


@functools.cache
def get_bill_versions() -> dict[str, str]:
    return {key: value['label'] for key, value in _get_vocabularies()['govinfo-bill-versions'].items()}


def __getattr__(name: str) -> Any:
    if name == 'BILL_TYPES':
        val = get_bill_types()
        globals()['BILL_TYPES'] = val
        return val
    if name == 'BILL_VERSIONS':
        val = get_bill_versions()
        globals()['BILL_VERSIONS'] = val
        return val
    if name == 'BILL_CODES':
        val = {'types': get_bill_types(), 'versions': get_bill_versions()}
        globals()['BILL_CODES'] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'BILLS_HELP_URL',
    'BILLS_HELP_CHECKED_ON',
    'BILL_TYPES',
    'BILL_VERSIONS',
    'BILL_CODES',
    'MIN_CONGRESS',
    'MAX_CONGRESS',
    'MAX_BILL_NUMBER_DIGITS',
    'get_bill_types',
    'get_bill_versions',
    'is_valid_congress',
    'split_bills_congress_and_number',
    'parse_bills_slug',
]
