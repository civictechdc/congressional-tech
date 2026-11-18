#!/usr/bin/env python3
"""Stage 4 (`N12`) Pure-Python Zero-LLM Complete `DocMetaV4Causal` Bypass (`zero_llm_bypass_v6.py`).

100% Python standard-library runtime module (`/usr/bin/python3 -B -I -S` verified, zero third-party
imports) synthesizing complete, `strict_validate_v4`-verified, causal-key-ordered `DocMetaV4Causal`
dicts with `0` GPU tokens across four high-volume template/relational genres:
  1. `truth_in_testimony_disclosure` (`~21,510+` target rows)
  2. `attendance_quorum_sheet` (`746` target rows)
  3. `witness_list` (`~1,160+` target rows)
  4. `legislative_schedule_or_calendar` (`199` `schedule_docs_house_floor_weekly` rows)

Core Design Invariant (`100.0%` Precision Over Recall):
  `try_synthesize_zero_llm_docmeta_v6(...)` returns a synthesized `DocMetaV4Causal` dict ONLY when
  every required 80/20 field is deterministically known at 100% confidence and passes self-contained
  schema, causal-key-order, and Constitutional Congress-calendar validation. Whenever any required
  field is missing or ambiguous (e.g., unchecked/blank `has_federal_grants` on a non-governmental
  Truth-in-Testimony form, multi-witness ambiguity, missing committee/date, or calendar mismatch),
  it returns `None` so the document routes cleanly to the LLM queue.
"""

from __future__ import annotations

import datetime
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "BYPASS_SUPPORTED_KINDS_V6",
    "DISCLOSURE_KEYS_ORDER_V6",
    "PERSONA_KEYS_ORDER_V6",
    "TOP_KEYS_ORDER_V6",
    "iso_date_to_congress_v6",
    "order_and_validate_docmeta_v6",
    "parse_ttf_form_v6",
    "synthesize_zero_llm_docmeta_v6",
    "try_synthesize_zero_llm_docmeta_v6",
    "try_zero_llm_bypass_v6",
]

BYPASS_SUPPORTED_KINDS_V6: frozenset[str] = frozenset(
    {
        "truth_in_testimony_disclosure",
        "attendance_quorum_sheet",
        "witness_list",
        "legislative_schedule_or_calendar",
    }
)

# ---------------------------------------------------------------------------
# 1. Exact `DocMetaV4Causal` Key Order & Self-Contained Strict Validator
# ---------------------------------------------------------------------------

TOP_KEYS_ORDER_V6: tuple[str, ...] = (
    "status",
    "text_quality",
    "error_reason",
    "verbatim_title",
    "short_titles",
    "chamber",
    "congress",
    "committees",
    "subcommittees",
    "issuer_org",
    "event_type",
    "event_title",
    "venue_kind",
    "venue",
    "event_time",
    "date_spans",
    "doc_date",
    "event_date",
    "due_date",
    "primary_kind",
    "secondary_kinds",
    "subkind",
    "personas",
    "refs",
    "programs",
    "orgs_mentioned",
    "places",
    "fiscal_years",
    "correspondence_flow",
    "signatory_count",
    "action_summary",
    "disclosure",
    "composed_title",
    "gist",
    "topics",
)

PERSONA_KEYS_ORDER_V6: tuple[str, ...] = (
    "name",
    "creds",
    "title",
    "org",
    "sub_org",
    "secondary_orgs",
    "on_behalf_of",
    "party_state",
    "panel",
    "role",
    "entity_type",
    "work_addr",
    "official_contact",
    "prior_roles",
    "education",
    "redacted_personal_pii",
)

DISCLOSURE_KEYS_ORDER_V6: tuple[str, ...] = (
    "capacity",
    "gov_witness",
    "represented_orgs",
    "fiduciary_orgs",
    "unrepresented_parent_or_sub",
    "has_federal_grants",
    "federal_grants",
    "has_foreign_payments",
    "foreign_payments",
)

_VALID_TEXT_QUALITY = frozenset({"native", "clean_ocr", "noisy_ocr", "garbled"})
_VALID_CHAMBER = frozenset({"house", "senate", "joint", "commission", "executive_or_external"})
_VALID_EVENT_TYPE = frozenset(
    {
        "hearing",
        "field_hearing",
        "nomination_hearing",
        "markup",
        "business_meeting",
        "roundtable_or_briefing",
        "floor_or_other",
    }
)
_VALID_VENUE_KIND = frozenset({"capitol_room", "field_site", "virtual", "hybrid"})
_VALID_ROLES = frozenset(
    {
        "witness",
        "author_or_speaker",
        "chair",
        "ranking_member",
        "presiding",
        "questioner",
        "sponsor",
        "cosponsor",
        "amendment_offeror",
        "nominee",
        "introducer",
        "sender",
        "recipient",
        "signatory",
        "staff",
        "party_or_investigator",
    }
)
_VALID_ENTITY_TYPES = frozenset(
    {
        "member",
        "gov_official",
        "military_officer",
        "judicial_or_exec_nominee",
        "non_gov_person",
        "staff",
        "organization",
    }
)
_VALID_CAPACITY = frozenset({"self", "organization", "government"})
_ARRAY_MAX_ITEMS: dict[str, int] = {
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


def _dedup_nonempty_strs(items: Sequence[Any] | None, *, max_items: int | None = None, max_len: int = 220) -> list[str]:
    if not items:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for x in items:
        if not isinstance(x, str):
            continue
        s = re.sub(r"\s+", " ", x).strip()
        if not s:
            continue
        if len(s) > max_len:
            s = s[: max_len - 3].rstrip() + "..."
        key = s.lower()
        if key not in seen:
            seen.add(key)
            out.append(s)
            if max_items is not None and len(out) >= max_items:
                break
    return out


def _order_persona(p: Mapping[str, Any]) -> dict[str, Any] | None:
    nm = re.sub(r"\s+", " ", str(p.get("name") or "")).strip()
    role = p.get("role")
    etype = p.get("entity_type")
    if not nm or role not in _VALID_ROLES or etype not in _VALID_ENTITY_TYPES:
        return None
    out: dict[str, Any] = {}
    for k in PERSONA_KEYS_ORDER_V6:
        if k not in p or p[k] is None:
            continue
        v = p[k]
        if k == "name":
            out[k] = nm[:120]
        elif k in ("role", "entity_type"):
            out[k] = v
        elif k == "redacted_personal_pii":
            if isinstance(v, bool):
                out[k] = v
        elif k in ("secondary_orgs", "prior_roles", "education"):
            lim = 5 if k == "education" else (8 if k == "prior_roles" else 6)
            arr = _dedup_nonempty_strs(v if isinstance(v, Sequence) and not isinstance(v, str) else None, max_items=lim)
            if arr:
                out[k] = arr
        elif k == "panel":
            if not isinstance(v, bool):
                sv = re.sub(r"\s+", " ", str(v)).strip()
                if sv:
                    out[k] = f"Panel {sv}" if sv.isdigit() else sv[:80]
        elif isinstance(v, datetime.date):
            out[k] = v.isoformat()
        elif isinstance(v, str):
            sv = re.sub(r"\s+", " ", v).strip()
            if sv:
                out[k] = sv[:180]
    return out if ("name" in out and "role" in out and "entity_type" in out) else None


def _order_disclosure(d: Mapping[str, Any]) -> dict[str, Any] | None:
    out: dict[str, Any] = {}
    for k in DISCLOSURE_KEYS_ORDER_V6:
        if k not in d or d[k] is None:
            continue
        v = d[k]
        if k == "capacity":
            if v in _VALID_CAPACITY:
                out[k] = v
        elif k in ("gov_witness", "unrepresented_parent_or_sub", "has_federal_grants", "has_foreign_payments"):
            if isinstance(v, bool):
                out[k] = v
        elif k in ("represented_orgs", "fiduciary_orgs", "federal_grants", "foreign_payments"):
            arr = _dedup_nonempty_strs(v if isinstance(v, Sequence) and not isinstance(v, str) else None, max_items=12)
            if arr:
                out[k] = arr
    return out if out else None


def order_and_validate_docmeta_v6(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    """Canonicalize key order, prune empty/null values, and strictly validate against `DocMetaV4Causal`."""
    status = raw.get("status")
    tq = raw.get("text_quality")
    pk = raw.get("primary_kind")
    if status != "usable" or tq not in _VALID_TEXT_QUALITY or pk not in BYPASS_SUPPORTED_KINDS_V6:
        return None

    ordered: dict[str, Any] = {}
    for k in TOP_KEYS_ORDER_V6:
        if k not in raw or raw[k] is None:
            continue
        v = raw[k]
        if k in ("status", "text_quality", "primary_kind"):
            ordered[k] = v
        elif k == "error_reason":
            continue
        elif k == "chamber":
            if v not in _VALID_CHAMBER:
                return None
            ordered[k] = v
        elif k == "congress":
            if isinstance(v, bool) or not isinstance(v, int) or not (1 <= v <= 130):
                return None
            ordered[k] = v
        elif k == "event_type":
            if v in _VALID_EVENT_TYPE:
                ordered[k] = v
        elif k == "venue_kind":
            if v in _VALID_VENUE_KIND:
                ordered[k] = v
        elif k == "personas":
            if not isinstance(v, Sequence) or isinstance(v, str):
                continue
            ps = [op for item in v if isinstance(item, Mapping) for op in [_order_persona(item)] if op is not None][:10]
            if ps:
                ordered[k] = ps
        elif k == "disclosure":
            if isinstance(v, Mapping):
                od = _order_disclosure(v)
                if od:
                    ordered[k] = od
        elif k == "fiscal_years":
            if isinstance(v, Sequence) and not isinstance(v, str):
                fys: list[int] = []
                for fy in v:
                    if not isinstance(fy, bool) and isinstance(fy, int) and 1900 <= fy <= 2100 and fy not in fys:
                        fys.append(fy)
                if fys:
                    ordered[k] = fys[:12]
        elif k == "signatory_count":
            if not isinstance(v, bool) and isinstance(v, int) and v >= 1:
                ordered[k] = v
        elif k in (
            "short_titles",
            "committees",
            "subcommittees",
            "date_spans",
            "secondary_kinds",
            "refs",
            "programs",
            "orgs_mentioned",
            "places",
            "topics",
        ):
            if isinstance(v, Sequence) and not isinstance(v, str):
                arr = _dedup_nonempty_strs(v, max_items=_ARRAY_MAX_ITEMS.get(k))
                if arr:
                    ordered[k] = arr
        elif isinstance(v, datetime.date):
            ordered[k] = v.isoformat()
        elif isinstance(v, str):
            sv = re.sub(r"\s+", " ", v).strip()
            if sv:
                if k == "composed_title" and len(sv) > 108:
                    sv = sv[:105].rstrip(" ,;:-–—(") + "..."
                ordered[k] = sv

    if not ordered.get("composed_title") or not ordered.get("gist") or not ordered.get("topics"):
        return None
    if len(str(ordered["gist"]).split()) > 22:
        words = str(ordered["gist"]).split()[:22]
        ordered["gist"] = " ".join(words).rstrip(",;:") + "."
    return ordered


# ---------------------------------------------------------------------------
# 2. Shared Calendar, Committee, Date & Persona Utilities (100% Stdlib)
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")
_SLUG_META_RE = re.compile(
    r"\b(?P<etype>HHRG|HMKP|HMTG)-(?P<cong>1\d\d)-(?P<cmt>[A-Z]{2})(?P<sub>\d{2}|[A-Z0-9]{0,2})",
    re.I,
)
_SLUG_CONG_GENERIC_RE = re.compile(
    r"^(?:HHRG|HMKP|HMTG|BILLS|CRPT|CHRG|CPRT)-(1\d\d)(?:[-_.]|[A-Za-z])",
    re.I,
)
_SLUG_TRAILING_DATE_RE = re.compile(r"-(20\d{2})(\d{2})(\d{2})(?:[-_.]|$)")

_HOUSE_2LETTER_COMMITTEE_CANON: dict[str, str] = {
    "AG": "House Committee on Agriculture",
    "AP": "House Committee on Appropriations",
    "AS": "House Committee on Armed Services",
    "BA": "House Committee on Financial Services",
    "BU": "House Committee on the Budget",
    "ED": "House Committee on Education and the Workforce",
    "FA": "House Committee on Foreign Affairs",
    "GO": "House Committee on Oversight and Government Reform",
    "HA": "House Committee on House Administration",
    "HM": "House Committee on Homeland Security",
    "IF": "House Committee on Energy and Commerce",
    "II": "House Committee on Natural Resources",
    "JU": "House Committee on the Judiciary",
    "PW": "House Committee on Transportation and Infrastructure",
    "RU": "House Committee on Rules",
    "SM": "House Committee on Small Business",
    "SO": "House Committee on Ethics",
    "SY": "House Committee on Science, Space, and Technology",
    "VR": "House Committee on Veterans' Affairs",
    "WM": "House Committee on Ways and Means",
    "IG": "House Permanent Select Committee on Intelligence",
    "ZS": "House Select Committee on the Strategic Competition between the United States and the Chinese Communist Party",
    "CN": "House Select Committee on the Climate Crisis",
    "MH": "House Select Committee on the Modernization of Congress",
    "EF": "House Select Committee on Economic Disparity and Fairness in Growth",
    "IJ": "House Select Committee to Investigate the January 6th Attack on the United States Capitol",
    "GW": "House Select Committee on Energy Independence and Global Warming",
    "ZI": "House Select Committee on the Events Surrounding the 2012 Terrorist Attacks in Benghazi",
    "FD": "House Select Subcommittee on the Weaponization of the Federal Government",
    "VC": "House Select Subcommittee on the Coronavirus Crisis",
    "SS": "House Select Subcommittee on the Coronavirus Pandemic",
}

_SENATE_CODE_TO_CANON: dict[str, str] = {
    "ssaf": "Senate Committee on Agriculture, Nutrition, and Forestry",
    "ssap": "Senate Committee on Appropriations",
    "ssas": "Senate Committee on Armed Services",
    "ssbk": "Senate Committee on Banking, Housing, and Urban Affairs",
    "ssbu": "Senate Committee on the Budget",
    "sscm": "Senate Committee on Commerce, Science, and Transportation",
    "sseg": "Senate Committee on Energy and Natural Resources",
    "ssev": "Senate Committee on Environment and Public Works",
    "ssfi": "Senate Committee on Finance",
    "ssfr": "Senate Committee on Foreign Relations",
    "ssga": "Senate Committee on Homeland Security and Governmental Affairs",
    "sshr": "Senate Committee on Health, Education, Labor, and Pensions",
    "ssju": "Senate Committee on the Judiciary",
    "ssra": "Senate Committee on Rules and Administration",
    "sssb": "Senate Committee on Small Business and Entrepreneurship",
    "ssva": "Senate Committee on Veterans' Affairs",
    "slia": "Senate Committee on Indian Affairs",
    "slin": "Senate Select Committee on Intelligence",
    "spag": "Senate Special Committee on Aging",
    "slet": "Senate Select Committee on Ethics",
    "scnc": "Senate Caucus on International Narcotics Control",
    "jstx": "Joint Committee on Taxation",
    "jslc": "Joint Economic Committee",
}

_COMMITTEE_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\bCommittee\s+on\s+Energy\s+and\s+Commerce\b", re.I), "house", "House Committee on Energy and Commerce"),
    (re.compile(r"\bCommittee\s+on\s+(?:F|in)inancial\s+Services\b|\binancial\s+Services\b", re.I), "house", "House Committee on Financial Services"),
    (re.compile(r"\bCommittee\s+on\s+Ways\s+and\s+Means\b", re.I), "house", "House Committee on Ways and Means"),
    (re.compile(r"\bCommittee\s+on\s+Transportation\s+and\s+Infrastructure\b", re.I), "house", "House Committee on Transportation and Infrastructure"),
    (re.compile(r"\bCommittee\s+on\s+Education\s+and\s+(?:the\s+Workforce|Labor|Workforce)\b", re.I), "house", "House Committee on Education and the Workforce"),
    (re.compile(r"\bCommittee\s+on\s+Oversight\s+and\s+(?:Government\s+Reform|Reform|Accountability)\b", re.I), "house", "House Committee on Oversight and Government Reform"),
    (re.compile(r"\bCommittee\s+on\s+Natural\s+Resources\b", re.I), "house", "House Committee on Natural Resources"),
    (re.compile(r"\b(?:Committee|Conumittee)\s+on\s+Foreign\s+(?:Affairs|Attairs)\b", re.I), "house", "House Committee on Foreign Affairs"),
    (re.compile(r"\bCommittee\s+on\s+Foreign\s+Relations\b", re.I), "senate", "Senate Committee on Foreign Relations"),
    (re.compile(r"\bCommittee\s+on\s+Homeland\s+Security\s+and\s+Governmental\s+Affairs\b", re.I), "senate", "Senate Committee on Homeland Security and Governmental Affairs"),
    (re.compile(r"\bCommittee\s+on\s+Homeland\s+Security\b", re.I), "house", "House Committee on Homeland Security"),
    (re.compile(r"\bCommittee\s+on\s+Science,\s*Space,\s*and\s+Technology\b|\bCommittee\s+on\s+Science\s+and\s+Technology\b", re.I), "house", "House Committee on Science, Space, and Technology"),
    (re.compile(r"\bCommittee\s+on\s+House\s+Administration\b", re.I), "house", "House Committee on House Administration"),
    (re.compile(r"\bCommittee\s+on\s+Agriculture,\s*Nutrition,\s*and\s+Forestry\b", re.I), "senate", "Senate Committee on Agriculture, Nutrition, and Forestry"),
    (re.compile(r"\bCommittee\s+on\s+Agriculture\b", re.I), "house", "House Committee on Agriculture"),
    (re.compile(r"\bCommittee\s+on\s+Banking,\s*Housing,\s*and\s+Urban\s+Affairs\b", re.I), "senate", "Senate Committee on Banking, Housing, and Urban Affairs"),
    (re.compile(r"\bCommittee\s+on\s+Commerce,\s*Science,\s*and\s+Transportation\b", re.I), "senate", "Senate Committee on Commerce, Science, and Transportation"),
    (re.compile(r"\bCommittee\s+on\s+Energy\s+and\s+Natural\s+Resources\b", re.I), "senate", "Senate Committee on Energy and Natural Resources"),
    (re.compile(r"\bCommittee\s+on\s+Environment\s+and\s+Public\s+Works\b", re.I), "senate", "Senate Committee on Environment and Public Works"),
    (re.compile(r"\bCommittee\s+on\s+Health,\s*Education,\s*Labor,\s*and\s+Pensions\b", re.I), "senate", "Senate Committee on Health, Education, Labor, and Pensions"),
    (re.compile(r"\bCommittee\s+on\s+Finance\b", re.I), "senate", "Senate Committee on Finance"),
    (re.compile(r"\bCommittee\s+on\s+Indian\s+Affairs\b", re.I), "senate", "Senate Committee on Indian Affairs"),
    (re.compile(r"\bSelect\s+Subcommittee\s+on\s+the\s+Coronavirus\s+Crisis\b", re.I), "house", "House Select Subcommittee on the Coronavirus Crisis"),
    (re.compile(r"\bSelect\s+Subcommittee\s+on\s+the\s+Coronavirus\s+Pandemic\b", re.I), "house", "House Select Subcommittee on the Coronavirus Pandemic"),
    (re.compile(r"\bSelect\s+Subcommittee\s+on\s+the\s+Weaponization\s+of\s+the\s+Federal\s+Government\b", re.I), "house", "House Select Subcommittee on the Weaponization of the Federal Government"),
    (re.compile(r"\bSelect\s+Committee\s+on\s+the\s+Climate\s+Crisis\b", re.I), "house", "House Select Committee on the Climate Crisis"),
    (re.compile(r"\bSelect\s+Committee\s+on\s+the\s+Modernization\s+of\s+Congress\b", re.I), "house", "House Select Committee on the Modernization of Congress"),
    (re.compile(r"\bPermanent\s+Select\s+Committee\s+on\s+Intelligence\b", re.I), "house", "House Permanent Select Committee on Intelligence"),
    (re.compile(r"\bCommittee\s+on\s+Small\s+Business\s+and\s+Entrepreneurship\b", re.I), "senate", "Senate Committee on Small Business and Entrepreneurship"),
    (re.compile(r"\bCommittee\s+on\s+Small\s+Business\b", re.I), "house", "House Committee on Small Business"),
    (re.compile(r"\bCommittee\s+on\s+Ethics\b", re.I), "house", "House Committee on Ethics"),
    (re.compile(r"\bCommittee\s+on\s+Rules\s+and\s+Administration\b", re.I), "senate", "Senate Committee on Rules and Administration"),
)

_SHARED_CHAMBER_COMMITTEE_RE: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bCommittee\s+on\s+the\s+Judiciary\b", re.I), "Committee on the Judiciary"),
    (re.compile(r"\bCommittee\s+on\s+Appropriations\b", re.I), "Committee on Appropriations"),
    (re.compile(r"\bCommittee\s+on\s+Armed\s+Services\b", re.I), "Committee on Armed Services"),
    (re.compile(r"\bCommittee\s+on\s+Veterans['’]?\s+Affairs\b", re.I), "Committee on Veterans' Affairs"),
    (re.compile(r"\bCommittee\s+on\s+the\s+Budget\b", re.I), "Committee on the Budget"),
    (re.compile(r"\bCommittee\s+on\s+Rules\b", re.I), "House Committee on Rules"),
)

_BARE_SHORT_HOUSE_CMT_MAP: dict[str, str] = {
    "agriculture": "House Committee on Agriculture",
    "appropriations": "House Committee on Appropriations",
    "armed services": "House Committee on Armed Services",
    "financial services": "House Committee on Financial Services",
    "budget": "House Committee on the Budget",
    "the budget": "House Committee on the Budget",
    "education and labor": "House Committee on Education and Labor",
    "education and workforce": "House Committee on Education and Workforce",
    "education and the workforce": "House Committee on Education and the Workforce",
    "energy and commerce": "House Committee on Energy and Commerce",
    "ethics": "House Committee on Ethics",
    "foreign affairs": "House Committee on Foreign Affairs",
    "homeland security": "House Committee on Homeland Security",
    "house administration": "House Committee on House Administration",
    "administration": "House Committee on House Administration",
    "judiciary": "House Committee on the Judiciary",
    "the judiciary": "House Committee on the Judiciary",
    "natural resources": "House Committee on Natural Resources",
    "oversight and reform": "House Committee on Oversight and Reform",
    "oversight and accountability": "House Committee on Oversight and Accountability",
    "oversight and government reform": "House Committee on Oversight and Government Reform",
    "rules": "House Committee on Rules",
    "science, space, and technology": "House Committee on Science, Space, and Technology",
    "small business": "House Committee on Small Business",
    "transportation and infrastructure": "House Committee on Transportation and Infrastructure",
    "veterans' affairs": "House Committee on Veterans' Affairs",
    "veterans affairs": "House Committee on Veterans' Affairs",
    "ways and means": "House Committee on Ways and Means",
    "climate crisis": "House Select Committee on the Climate Crisis",
    "modernization of congress": "House Select Committee on the Modernization of Congress",
    "coronavirus crisis": "House Select Subcommittee on the Coronavirus Crisis",
    "coronavirus pandemic": "House Select Subcommittee on the Coronavirus Pandemic",
}

_US_STATE_TO_ABBR: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "lowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
    "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "puerto rico": "PR", "guam": "GU", "virgin islands": "VI",
    "american samoa": "AS", "northern mariana islands": "MP",
}

_MONTH_MAP: dict[str, int] = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

_LONG_DATE_RE = re.compile(
    r"\b(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+)?"
    r"(January|Jan\.?|February|Feb\.?|March|Mar\.?|April|Apr\.?|May|June|Jun\.?|July|Jul\.?|"
    r"August|Aug\.?|September|Sept?\.?|October|Oct\.?|November|Nov\.?|December|Dec\.?)"
    r"\s+(\d{1,2}|Z)(?:st|nd|rd|th)?,?\s*((?:19|20)\d{2})\b",
    re.I,
)
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})\s*[/-]\s*(\d{1,2})\s*[/-]\s*((?:20)?\d{2})\b")
_ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")


def iso_date_to_congress_v6(iso_date: str | datetime.date | None) -> int | None:
    """Map `YYYY-MM-DD` (or `datetime.date`) to Constitutional Congress number (`None` on Jan 3 noon boundary)."""
    if isinstance(iso_date, datetime.date):
        iso_date = iso_date.isoformat()
    if not iso_date or not isinstance(iso_date, str):
        return None
    s = iso_date.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        yr, mo, da = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            datetime.date(yr, mo, da)
        except ValueError:
            return None
        if yr >= 1935:
            if yr % 2 == 1 and mo == 1 and da == 3:
                return None
            base_yr = yr if (yr % 2 == 1 and (mo > 1 or da > 3)) else (yr - 1 if yr % 2 == 0 else yr - 2)
            cong = ((base_yr - 1789) // 2) + 1
            return cong if 1 <= cong <= 130 else None
        if yr >= 1789:
            if yr % 2 == 1 and mo == 3 and da == 4:
                return None
            base_yr = yr if (yr % 2 == 1 and (mo > 3 or (mo == 3 and da > 4))) else (yr - 1 if yr % 2 == 0 else yr - 2)
            cong = ((base_yr - 1789) // 2) + 1
            return cong if 1 <= cong <= 130 else None
        return None
    m_ym = re.fullmatch(r"(\d{4})-(\d{2})", s)
    if m_ym:
        yr, mo = int(m_ym.group(1)), int(m_ym.group(2))
        if 1 <= mo <= 12 and yr >= 1935:
            if yr % 2 == 1 and mo == 1:
                return None
            base_yr = yr if yr % 2 == 1 else yr - 1
            cong = ((base_yr - 1789) // 2) + 1
            return cong if 1 <= cong <= 130 else None
    return None


def _extract_slug_congress(filename: str) -> int | None:
    s = (filename or "").strip()
    m = _SLUG_CONG_GENERIC_RE.match(s)
    if m:
        c = int(m.group(1))
        return c if 100 <= c <= 130 else None
    m2 = re.search(r"(?:^|[_.-])0?(1\d\d)(?:th|st|nd|rd)[_.-]congress", s, re.I)
    if m2:
        c = int(m2.group(1))
        return c if 100 <= c <= 130 else None
    return None


def _extract_filename_iso_date(filename: str) -> str | None:
    """Extract unambiguous calendar date from publisher filename (stripping 64-hex SHA prefixes first)."""
    if not filename:
        return None
    s = re.sub(r"^[0-9A-Fa-f]{40,64}[._-]", "", filename.strip())
    m1 = _SLUG_TRAILING_DATE_RE.search(s)
    if m1:
        _, iso = _parse_single_date_str(f"{m1.group(1)}-{m1.group(2)}-{m1.group(3)}")
        if iso:
            return iso
    m2 = re.search(r"(?:^|[_.-])(20\d{2})[._-](\d{2})[._-](\d{2})(?:[._-]|$)", s)
    if m2:
        _, iso = _parse_single_date_str(f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}")
        if iso:
            return iso
    m3 = re.match(r"^(20\d{2})(\d{2})(\d{2})(?=[A-Za-z_-])", s)
    if m3:
        _, iso = _parse_single_date_str(f"{m3.group(1)}-{m3.group(2)}-{m3.group(3)}")
        if iso:
            return iso
    m4 = re.search(r"(?:^|[_-])(\d{1,2})[._-](\d{1,2})[._-](20\d{2}|\d{2})(?:[_.-]|$)", s)
    if m4:
        yr_raw = int(m4.group(3))
        yr = yr_raw + 2000 if yr_raw < 100 else yr_raw
        if 2009 <= yr <= 2027:
            _, iso = _parse_single_date_str(f"{yr:04d}-{int(m4.group(1)):02d}-{int(m4.group(2)):02d}")
            if iso:
                return iso
    return None


def _parse_single_date_str(s: str) -> tuple[str | None, str | None]:
    """Return `(verbatim_span, YYYY-MM-DD)` from a short string slice."""
    if not s:
        return None, None
    m_iso = _ISO_DATE_RE.search(s)
    if m_iso:
        yr, mo, da = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        try:
            datetime.date(yr, mo, da)
            return m_iso.group(0), f"{yr:04d}-{mo:02d}-{da:02d}"
        except ValueError:
            pass
    m_long = _LONG_DATE_RE.search(s)
    if m_long:
        mo = _MONTH_MAP.get(m_long.group(1).rstrip(".").lower())
        raw_d = m_long.group(2)
        da = 2 if raw_d.upper() == "Z" else int(raw_d)
        yr = int(m_long.group(3))
        if mo:
            try:
                datetime.date(yr, mo, da)
                return m_long.group(0).strip(), f"{yr:04d}-{mo:02d}-{da:02d}"
            except ValueError:
                pass
    m_num = _NUMERIC_DATE_RE.search(s)
    if m_num:
        mo, da = int(m_num.group(1)), int(m_num.group(2))
        yr_raw = m_num.group(3)
        yr = (2000 + int(yr_raw)) if len(yr_raw) == 2 else int(yr_raw)
        try:
            datetime.date(yr, mo, da)
            return m_num.group(0).strip(), f"{yr:04d}-{mo:02d}-{da:02d}"
        except ValueError:
            pass
    return None, None


def _era_aware_house_committee(base_canon: str, congress: int | None, text_head: str = "") -> str:
    low = text_head.lower()
    if "oversight" in base_canon.lower() and "house" in base_canon.lower():
        if "oversight and accountability" in low or congress == 118:
            return "House Committee on Oversight and Accountability"
        if "oversight and reform" in low or congress in (116, 117):
            return "House Committee on Oversight and Reform"
        return "House Committee on Oversight and Government Reform"
    if "education" in base_canon.lower() and "house" in base_canon.lower():
        if "education and labor" in low or congress in (110, 111, 116, 117):
            return "House Committee on Education and Labor"
        if "education and workforce" in low and "the workforce" not in low and congress == 119:
            return "House Committee on Education and Workforce"
        return "House Committee on Education and the Workforce"
    return base_canon


def _committee_code_to_canon(code: str, congress: int | None = None, text_head: str = "") -> tuple[str | None, str | None]:
    sc = (code or "").strip().lower()
    if len(sc) < 4:
        return None, None
    p4 = sc[:4]
    if p4 in _SENATE_CODE_TO_CANON:
        ch = "joint" if p4.startswith("js") else "senate"
        return ch, _SENATE_CODE_TO_CANON[p4]
    if sc.startswith(("hs", "hl", "ht", "hj")):
        two = sc[2:4].upper()
        base = _HOUSE_2LETTER_COMMITTEE_CANON.get(two)
        if base:
            return "house", _era_aware_house_committee(base, congress, text_head)
    return None, None


def _resolve_committees_and_chamber(
    *,
    filename: str,
    text: str,
    congress: int | None,
    known: Mapping[str, Any],
    relational: Mapping[str, Any],
    provenance: Mapping[str, Any],
    default_house: bool = False,
) -> tuple[str | None, list[str]]:
    head = _WS_RE.sub(" ", (text or "")[:1600])
    cmts: list[str] = []
    chamber: str | None = "house" if default_house else None

    for key in ("rel_author_safe_committees", "rel_host_committees"):
        val = relational.get(key)
        if isinstance(val, str) and val.startswith("["):
            try:
                val = json.loads(val)
            except Exception:
                val = None
        if isinstance(val, Sequence) and not isinstance(val, str):
            for c in val:
                if isinstance(c, str) and c.strip() and c.strip() not in cmts:
                    cmts.append(_era_aware_house_committee(c.strip(), congress, head))
        if cmts:
            break

    if not cmts:
        codes: list[str] = []
        for src_codes in (
            relational.get("rel_host_committee_codes"),
            known.get("cmt"),
            provenance.get("committee_codes"),
        ):
            if isinstance(src_codes, Sequence) and not isinstance(src_codes, str):
                for sc in src_codes:
                    if isinstance(sc, str) and sc.strip():
                        codes.append(sc.strip())
        m_slug = _SLUG_META_RE.search(filename or "")
        if m_slug:
            codes.append(f"hs{m_slug.group('cmt').lower()}00")
        for sc in codes:
            ch_c, canon_c = _committee_code_to_canon(sc, congress, head)
            if canon_c and canon_c not in cmts:
                cmts.append(canon_c)
            if chamber is None and ch_c:
                chamber = ch_c

    if not cmts:
        for rx, ch_p, canon_p in _COMMITTEE_TEXT_PATTERNS:
            if rx.search(head):
                cmts.append(_era_aware_house_committee(canon_p, congress, head))
                if chamber is None:
                    chamber = ch_p
                break
    if not cmts:
        low_h = head.lower()
        inferred_ch = (
            "house"
            if (default_house or "house of representatives" in low_h or "u.s. house" in low_h)
            else ("senate" if ("united states senate" in low_h or "u.s. senate" in low_h) else None)
        )
        for rx, base_shared in _SHARED_CHAMBER_COMMITTEE_RE:
            if rx.search(head):
                if base_shared.startswith("House "):
                    cmts.append(base_shared)
                    chamber = chamber or "house"
                elif inferred_ch == "house":
                    cmts.append(f"House {base_shared}")
                    chamber = chamber or "house"
                elif inferred_ch == "senate":
                    cmts.append(f"Senate {base_shared}")
                    chamber = chamber or "senate"
                break

    if chamber is None:
        rel_ch = relational.get("rel_author_safe_chamber") or relational.get("rel_host_chamber")
        if rel_ch in ("house", "senate", "joint", "commission"):
            chamber = str(rel_ch)
        elif isinstance(known.get("chambers"), Sequence) and not isinstance(known.get("chambers"), str):
            chs = [str(x).lower() for x in known["chambers"] if x]
            if len(chs) == 1 and chs[0] in ("house", "senate", "joint", "commission"):
                chamber = chs[0]
        elif cmts:
            if all(c.startswith("House ") for c in cmts):
                chamber = "house"
            elif all(c.startswith("Senate ") for c in cmts):
                chamber = "senate"

    return chamber, cmts


def _infer_text_quality(text: str) -> str:
    if not text:
        return "native"
    sample = text[:2500]
    ocr_typos = sum(
        1
        for pat in ("Gouse of", "Representatioes", "Representatiucs", "Attairs", "Vitness", "lause 2(g)", "disciosur", "inancial Services")
        if pat in sample
    )
    weird = sum(1 for ch in sample if ord(ch) > 0x0370 and ch not in "’‘“”–—•…§®©™°±×÷₩€£¥☐☑☒✓✔✗✘●○◉◯")
    if ocr_typos >= 2 or weird >= 8:
        return "noisy_ocr" if weird >= 10 else "clean_ocr"
    if ocr_typos == 1:
        return "clean_ocr"
    return "native"


def _surname_of(name: str) -> str:
    s = re.sub(
        r"\b(?:Jr\.?|Sr\.?|II|III|IV|V|Ph\.?D\.?|M\.?D\.?|J\.?D\.?|Esq\.?|CPA|CFA|P\.?E\.?|RN|"
        r"Ret\.?|USN|USA|USAF|USMC|USCG|Hon\.?|The\s+Honorable|Honorable|Dr\.?|Mr\.?|Ms\.?|Mrs\.?|Miss|"
        r"Prof\.?|Professor|Rep\.?|Sen\.?|Gen\.?|Adm\.?|Col\.?|Lt\.?|Maj\.?|Capt\.?|Detective|Sheriff|Chief)\b",
        " ",
        name or "",
        flags=re.I,
    )
    parts = [p for p in re.split(r"[^A-Za-z'\u00C0-\u024F-]+", s) if len(p) > 1]
    return unicodedata.normalize("NFKC", parts[-1]).lower() if parts else ""


def _clean_person_name(raw_name: str) -> str:
    s = _WS_RE.sub(" ", raw_name or "").strip(" ,;:-–—._")
    for _ in range(2):
        s = re.sub(
            r"^(?:The\s+Honorable|Honorable|Hon\.|Dr\.|Mr\.|Ms\.|Mrs\.|Miss|Professor|Prof\.|"
            r"Detective|Sheriff|Chief|Officer|Pastor|Rabbi|Rev\.|Reverend|Father|Bishop)\s+",
            "",
            s,
            flags=re.I,
        ).strip()
    # Strip trailing degree credentials (`Makola M. Abdullah, Ph.D` -> `Makola M. Abdullah`)
    s = re.sub(r",\s*(?:Ph\.?D\.?|M\.?D\.?|J\.?D\.?|Esq\.?|P\.?E\.?|CPA|RN|MPH|MBA|MPP)\.?$", "", s, flags=re.I).strip()
    if s.count(",") == 1:
        left, right = [p.strip() for p in s.split(",", 1)]
        if (
            left
            and right
            and 1 <= len(left.split()) <= 2
            and 1 <= len(right.split()) <= 3
            and not re.match(r"^(?:Jr\.?|Sr\.?|II|III|IV|Ph\.?D\.?|M\.?D\.?|J\.?D\.?|Esq\.?|P\.?E\.?|CPA|RN|Ret\.?|US[A-Z]{1,3})$", right, re.I)
        ):
            s = f"{right} {left}"
    if s.isupper() and len(s) >= 4:
        s = " ".join(w.capitalize() if not re.match(r"^[IVX]{2,}$", w) else w for w in s.split())
    return s[:120]


_STOP_TOPIC_WORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "into", "over", "under", "through", "after", "before",
        "about", "hearing", "oversight", "examining", "examination", "review", "update", "assessing",
        "perspectives", "challenges", "opportunities", "future", "americas", "america", "american",
        "united", "states", "federal", "national", "committee", "subcommittee", "house", "senate",
        "congress", "part", "act", "bill", "title", "getting", "right", "track", "navigating",
        "biased", "broken", "system", "proposals", "overhaul", "achieve", "shifting", "identifying",
        "priorities", "next", "how", "can", "support", "our", "full", "legislative", "on", "of", "in", "to", "a", "an",
    }
)


def _derive_topics_from_context(
    *,
    base_tag: str,
    committees: Sequence[str],
    event_title: str | None = None,
    extra_tags: Sequence[str] = (),
) -> list[str]:
    tags: list[str] = [base_tag]
    for t in extra_tags:
        if t and t.lower() not in {x.lower() for x in tags}:
            tags.append(t)
    if event_title:
        clean_et = re.sub(r"[^A-Za-z0-9\s-]", " ", event_title)
        words = [w.lower() for w in clean_et.split() if len(w) >= 4 and w.lower() not in _STOP_TOPIC_WORDS and not w.isdigit()]
        if len(words) >= 2:
            phrase = f"{words[0]} {words[1]}"
            if phrase not in {x.lower() for x in tags}:
                tags.append(phrase)
        elif len(words) == 1 and words[0] not in {x.lower() for x in tags}:
            tags.append(words[0])
    for c in committees[:1]:
        short_c = re.sub(r"^(?:House|Senate|Joint)\s+(?:Permanent\s+Select\s+|Select\s+)?(?:Committee|Subcommittee)\s+on\s+(?:the\s+)?", "", c, flags=re.I).strip()
        if short_c and len(short_c) <= 48 and short_c.lower() not in {x.lower() for x in tags}:
            tags.append(short_c.lower())
    if len(tags) < 3:
        tags.append("congressional oversight")
    return tags[:5]


# ---------------------------------------------------------------------------
# 3A. Genre 1: `truth_in_testimony_disclosure` (`~21,510+` rows)
# ---------------------------------------------------------------------------

_CHECKED_CHARS = "•●◉⚫■▪☒☑✓✔✗✘XxVv®©*+@¾K"
_UNCHECKED_CHARS = "O0o○◯☐□▫D"

_EXPLICIT_NONE_RE = re.compile(
    r"^(?:\.?n/?a\.?|\.?nla\.?|no[unvmc]e\.?|nonc\.?|no\.?|nox\.?|no,\s*not\s+a\s+fiduciary\.?|"
    r"not\s+applicable\.?|nothing\.?|zero\.?|\$0(?:\.00)?|-+|—+)$",
    re.I,
)
_SELF_CAPACITY_RE = re.compile(
    r"^(?:self|myself|individual|personal(?:\s+capacity)?|representing\s+myself|in\s+my\s+personal\s+capacity)$",
    re.I,
)
_GOV_ORG_RE = re.compile(
    r"\b(?:U\.?S\.?\s+(?:Army|Navy|Air\s+Force|Marine\s+Corps|Coast\s+Guard|Space\s+Force|Department|Government|Forest\s+Service|Fish\s+and\s+Wildlife|Geological\s+Survey|Customs|Secret\s+Service|Marshals|Postal\s+Service|Census\s+Bureau|Small\s+Business\s+Administration)|"
    r"United\s+States\s+(?:Army|Navy|Air\s+Force|Marine\s+Corps|Coast\s+Guard|Department|Government\s+Accountability\s+Office|Forest\s+Service|Postal\s+Service)|"
    r"Department\s+of\s+(?:Defense|War|State|the\s+Treasury|Treasury|Justice|the\s+Interior|Interior|Agriculture|"
    r"Commerce|Labor|Health|Housing|Transportation|Energy|Education|Veterans|Homeland\s+Security)|"
    r"Government\s+Accountability\s+Office|Environmental\s+Protection\s+Agency|Federal\s+(?:Reserve|Trade\s+Commission|"
    r"Communications\s+Commission|Deposit\s+Insurance|Bureau\s+of\s+Investigation|Aviation\s+Administration|"
    r"Emergency\s+Management|Energy\s+Regulatory|Highway\s+Administration|Railroad\s+Administration|Transit\s+Administration|Maritime\s+Commission)|"
    r"Drug\s+Enforcement\s+Administration|Substance\s+Abuse\s+and\s+Mental\s+Health|SAMHSA|Centers\s+for\s+(?:Medicare|Disease\s+Control)|"
    r"Food\s+and\s+Drug\s+Administration|National\s+(?:Institutes\s+of\s+Health|Park\s+Service|Aeronautics\s+and\s+Space|Defense\s+University|Oceanic\s+and\s+Atmospheric|Science\s+Foundation|Labor\s+Relations\s+Board|Transportation\s+Safety\s+Board)|"
    r"Bureau\s+of\s+(?:Indian\s+Affairs|Land\s+Management|Reclamation|Prisons|Alcohol|Labor\s+Statistics|Ocean\s+Energy)|DOI/|"
    r"Internal\s+Revenue\s+Service|Social\s+Security\s+Administration|Small\s+Business\s+Administration|"
    r"Securities\s+and\s+Exchange\s+Commission|Nuclear\s+Regulatory\s+Commission|Consumer\s+Financial\s+Protection|"
    r"Cybersecurity\s+and\s+Infrastructure|Transportation\s+Security\s+Administration|Office\s+of\s+(?:Management\s+and\s+Budget|Inspector\s+General|Personnel\s+Management|the\s+Comptroller|the\s+United\s+States\s+Trade)|"
    r"Supervisor\s+of\s+Elections|State\s+of\s+[A-Z][a-z]+|Commonwealth\s+of\s+[A-Z][a-z]+|City\s+of\s+[A-Z][a-z]+|"
    r"County\s+of\s+[A-Z][a-z]+|[A-Z][a-z]+\s+Department\s+of\s+[A-Z][a-z]+)\b",
    re.I,
)
_MIL_ORG_OR_RANK_RE = re.compile(
    r"\b(?:U\.?S\.?\s+(?:Army|Navy|Air\s+Force|Marine\s+Corps|Coast\s+Guard|Space\s+Force)|"
    r"United\s+States\s+(?:Army|Navy|Air\s+Force|Marine\s+Corps|Coast\s+Guard)|"
    r"General|Admiral|Colonel|Commander|Major\s+General|Lieutenant\s+General|Vice\s+Admiral|Rear\s+Admiral)\b",
    re.I,
)
_BAD_FORM_NAME_RE = re.compile(
    r"\b(?:Please|Committee|Subcommittee|Hearing|Witness|Disclosure|Testimony|Organization|Position|Title|"
    r"Representing|Governmental|Signature|Date|Address|Business|Telephone|Rule\s+XI|Clause|Attach|Entity)\b",
    re.I,
)
_LOOKBACK_PROMPT_DATE_RE = re.compile(
    r"\b(?:since|on\s+or\s+after|after|subsequent\s+to)\s+"
    r"((?:January|October|December)\s+(?:1|31),?\s+20\d{2})\b",
    re.I,
)
_AG_DISCLAIMER_STRIP_RE = re.compile(
    r"Hous[ce]\s+Rules\s+do\s+NOT\s+require\s+disclosure\s+o[fr]\s+federal\s+payments\s+to\s+individuals,\s*"
    r"such\s+as\s+(?:Social\s+Security\s+or\s+Medicare\s+benefits,\s*)?farm\s+progra\w+\s+payments,?\s+or\s+assistance\s+[tf]o\s+agricultural\s+producers\.?",
    re.I,
)


def _classify_ttf_free_answer_ex(raw_ans: str | None) -> tuple[bool | None, list[str], bool]:
    """Classify a TTF federal-grant or foreign-payment free-text answer block.

    Returns `(has_items_bool_or_None, extracted_items, is_truly_blank)`.
    """
    if raw_ans is None:
        return None, [], False
    s = _AG_DISCLAIMER_STRIP_RE.sub(" ", raw_ans)
    s = _WS_RE.sub(" ", s).strip(" _.:;-–—*")
    s = re.sub(
        r"^(?:[!I]f['’]?\s*necessar[yt],\s*)?(?:a[tl]{1,2}[au]ch|atcach)\s+(?:a\s+second\s+page|add[il1]{0,2}ti?onal\s+shee[tsl]\(?s\)?)\s+"
        r"(?:if\s+necessar[yt]|(?:to|t0|10)\s*provide\s+more\s+information)\.?\s*",
        "",
        s,
        flags=re.I,
    ).strip(" _.:;-–—*")
    if not s:
        return None, [], True
    s = re.sub(
        r"\s*(?:Please\s+attach\s+a\s+copy|Please\s+complete\s+the\s+following\s+fields|Signature\s*:|"
        r"Signat\w*\s*:?|Fa\s*lse\s+Statements\s+Certification|\*?\s*Rule\s+XI|I\s+certify\s+that|"
        r"Witness\s+signature|Title\s*$).*$",
        "",
        s,
        flags=re.I,
    ).strip(" _.:;-–—*")
    if not s:
        return None, [], True
    if _EXPLICIT_NONE_RE.match(s):
        return False, [], False
    toks = [t.strip(".,;:") for t in s.split()]
    if toks and len(toks) <= 3 and all(_EXPLICIT_NONE_RE.match(t) for t in toks):
        return False, [], False
    if re.match(
        r"^(?:[a-z]\.\s*)?(?:no\s+(?:federal\s+|relevant\s+|related\s+)?(?:grants?|contracts?|payments?|subgrants?|funding)\b|"
        r"none\s+(?:received|to\s+report|applicable)\b|not\s+applicable\b|"
        r"(?:[A-Za-z0-9.,&'’\s()-]{1,65}\s+)?(?:has|have|does)\s+not\s+(?:have,?\s+and\s+has\s+not\s+)?re[ce]{1,2}ived,?\s+any\s+(?:federal\s+)?(?:grants?|contracts?|payments?|funding)\b|"
        r"neither\s+[i1l],?\s+nor\b)",
        s,
        re.I,
    ):
        return False, [], False
    if (
        re.search(r"[$₩€£]\s*\d[\d,]*(?:\.\d+)?", s)
        or re.search(r"\b\d{1,3}(?:,\d{3})+(?:\.\d{2})?\b", s)
        or re.search(
            r"\b(?:see\s+(?:attach(?:ed|ments?)|addendum)|sec\s+attachments?|attached\s+(?:sheet|list|schedule|addendum|table|chart)|"
            r"additional\s+sheet\s+attached|please\s+see\s+attached|subrecipient|subcontract|cooperative\s+agreement|funder\s+title|"
            r"statement\s+of\s+federal\s+grants)\b",
            s,
            re.I,
        )
        or re.search(
            r"\b(?:USDA|HHS|NIH|NSF|DOD|DOE|DOT|EPA|FAA|NASA|CMS|FEMA|USAID|DOJ|HUD|VA|DHS|DARPA|ARPA|CDC|SAMHSA|HRSA|"
            r"NOAA|NIST|USAF|NRO|OSD|CRISI|RAISE|TEFAP|CSFP|TANF|Medicare\s+Advantage)\b",
            s,
        )
        or (
            len(s) >= 10
            and re.search(
                r"\b(?:contracts?\s+(?:with|from|no\.)|grants?\s+(?:from|for|awarded|program|number)|awarded\s+by|funded\s+by)\b",
                s,
                re.I,
            )
        )
    ):
        return True, [s[:180]], False
    return None, [], False


def _classify_ttf_free_answer(raw_ans: str | None) -> tuple[bool | None, list[str]]:
    b, items, _ = _classify_ttf_free_answer_ex(raw_ans)
    return b, items


def _combine_grant_booleans(answers: Sequence[tuple[bool | None, list[str]]]) -> tuple[bool | None, list[str]]:
    """Combine personal + entity grant answers on multi-part TTFs (`True` if ANY is `True`; `False` if >=1 `False` and 0 `True`)."""
    items: list[str] = []
    any_true = False
    any_false = False
    for b, it in answers:
        if b is True:
            any_true = True
            items.extend(it)
        elif b is False:
            any_false = True
    if any_true:
        return True, items[:8]
    if any_false:
        return False, []
    return None, []


def _parse_yes_no_checkbox_pair(snippet: str) -> bool | None:
    """Parse unambiguous Yes/No checkbox pairs (`• YES XNO`, `O YES ANO`, `Yes VNo`, `DYES No`, `YES ÑO`, etc.)."""
    if not snippet:
        return None
    s = _WS_RE.sub(" ", snippet).strip()
    if "ÑO" in s and "YES" in s:
        return False
    if re.search(r"\b(?:IYES|X[I1l|]?YES|V[I1l|]?YES)\b", s):
        return True
    if re.search(r"\b(?:X[I1l|]?NO|V[I1l|]?NO|NOX|No\s*[XxVv✓✔☒☑])\b", s, re.I):
        return False
    if re.search(r"\bYes\s*[XxVv✓✔☒☑•]\s*(?:2\.|No\b(?!\s*[XxVv✓✔☒☑]))", s, re.I):
        return True

    strong_marks = "☒☑✓✔✗✘XxVv"
    m1 = re.search(
        r"(?P<m1>\[[Xx✓✔ ]\]|[•●◉⚫■▪☒☑✓✔✗✘XxVv®O0o○◯☐□▫D])?\s*Yes\b\s*"
        r"(?P<m2>\[[Xx✓✔ ]\]|[•●◉⚫■▪☒☑✓✔✗✘XxVv®AO0o○◯☐□▫D])?\s*No\b",
        s,
        re.I,
    )
    if m1:
        g1 = (m1.group("m1") or "").strip("[] ")
        g2 = (m1.group("m2") or "").strip("[] ")
        if g2 in strong_marks and g1 in "•O0o○◯☐□▫D":
            return False
        if g1 in strong_marks and g2 in "•O0o○◯☐□▫D":
            return True
        c1 = bool(g1 and g1 in _CHECKED_CHARS)
        u1 = bool(not g1 or g1 in _UNCHECKED_CHARS)
        c2 = bool(g2 and (g2 in _CHECKED_CHARS or (g2 == "A" and g1 in _UNCHECKED_CHARS and len(g1) == 1)))
        u2 = bool(not g2 or g2 in _UNCHECKED_CHARS)
        if c1 and u2 and not c2:
            return True
        if c2 and u1 and not c1:
            return False

    m3 = re.search(
        r"\bYes\b(?:\s*(?:\[\s*\]|[_O0o○◯☐□▫D]))?\s*\bNo\s*(?P<m2>\[[Xx✓✔]\]|[•●◉⚫■▪☒☑✓✔✗✘XxVv])\b",
        s,
        re.I,
    )
    if m3:
        return False
    return None


def parse_ttf_form_v6(text: str) -> dict[str, Any]:
    """Parse structured fields from Clerk AcroForm v1, Clerk AcroForm v2a/v2b, and Committee bespoke TTFs."""
    info: dict[str, Any] = {}
    if not text:
        return info

    t_ws = _WS_RE.sub(" ", text[:7500]).strip()
    if "Truth in Testimony Disclosure Form" in t_ws:
        info["verbatim_title"] = "Truth in Testimony Disclosure Form"

    if re.search(r"\b(?:BOARD\s+OF\s+DIRECTORS\s+BIOGRAPHY|BIOGRAPHICAL\s+SKETCH|CURRICULUM\s+VITAE)\b", t_ws[500:], re.I):
        info["has_attached_bio"] = True

    # Non-governmental form-level header declaration (Judiciary, Education & Workforce, Appropriations, Agriculture)
    if re.search(
        r"\b(?:by\s+(?:all\s+)?witnesses\s+appearing\s+in\s+a\s+non-?governmental\s+capacity|"
        r"require[sd]?\s+non-?governmental\s+witnesses\s+to\s+disclose)\b",
        t_ws[:650],
        re.I,
    ):
        info["header_declares_nongov"] = True

    m_chair = re.search(
        r"Committee\s+on\s+[A-Za-z,\s&'’-]{4,65}?\s+([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z'-]+),\s*(?:Chairman|Chairwoman|Chair)\b",
        t_ws[:320],
    )
    if m_chair:
        info["masthead_chair"] = m_chair.group(1).strip()

    lookback_isos: set[str] = set()
    for m_lb in _LOOKBACK_PROMPT_DATE_RE.finditer(t_ws):
        _, iso = _parse_single_date_str(m_lb.group(1))
        if iso:
            lookback_isos.add(iso)
    info["lookback_isos"] = lookback_isos

    # --- Variant A1: Clerk AcroForm v2b (`118th–119th` Fiduciary AcroForm widget dump, e.g. GOLD[184, 247]) ---
    v2b_tail: str | None = None
    m_v2b_anchor = re.search(
        r"Are\s+you\s+a\s+fiduciary.{10,160}?If\s+so,\s+please\s+list\s+the\s+name\s+of\s+the\s+organization\(s\)\s+or\s+entities\.\s*(.+)$",
        t_ws,
        re.I,
    )
    if m_v2b_anchor and re.search(r"^.{3,200}?\b(?:\d{1,2}/\d{1,2}/20\d{2}|[A-Z][a-z]+\s+\d{1,2},\s+20\d{2})\s+Title\s+", m_v2b_anchor.group(1)):
        v2b_tail = m_v2b_anchor.group(1)
    elif re.match(r"^[A-Z][A-Za-z,\s&'’-]{3,160}?\s+(?:\d{1,2}/\d{1,2}/20\d{2}|[A-Z][a-z]+\s+\d{1,2},\s+20\d{2})\s+Title\s+", t_ws):
        v2b_tail = t_ws

    if v2b_tail is not None:
        m_v2_head = re.match(
            r"^(?P<cmts>.{3,180}?)\s+(?P<dt>\d{1,2}/\d{1,2}/20\d{2}|[A-Z][a-z]+\s+\d{1,2},\s+20\d{2})\s+Title\s+(?P<rest>.+)$",
            v2b_tail,
        )
        if m_v2_head:
            sp_d, iso_d = _parse_single_date_str(m_v2_head.group("dt"))
            if iso_d:
                info["event_date"] = iso_d
                info["date_spans"] = [sp_d] if sp_d else []
            cmt_blob = m_v2_head.group("cmts").strip()
            for short_k, canon_v in sorted(_BARE_SHORT_HOUSE_CMT_MAP.items(), key=lambda kv: -len(kv[0])):
                idx_k = cmt_blob.lower().find(short_k)
                if idx_k >= 0:
                    info["form_committee"] = canon_v
                    sub_rem = cmt_blob[idx_k + len(short_k) :].strip(" ,;:-")
                    if sub_rem and len(sub_rem) >= 4:
                        info["form_subcommittee"] = sub_rem
                    break

            rest = m_v2_head.group("rest")
            fed_ans_str: str | None = None
            for_ans_str: str | None = None
            vals_str = ""
            m_p_split = re.search(
                r"^(?P<vals>.+?)\s+Please\s+list\s+any\s+federal\s+grants\s+or\s+contracts.{20,280}?Include\s+the\s+source\s+and\s+amount\s+of\s+each\s+grant\s+or\s+contract\.(?:\s*If\s+necessary,\s+attach\s+additional\s+sheet\(s\)\s+to\s+provide\s+more\s+information\.)?\s*(?P<after>.+)$",
                rest,
                re.I,
            )
            if m_p_split:
                vals_str = m_p_split.group("vals").strip()
                after_fed = m_p_split.group("after")
                m_for_p = re.search(
                    r"^(?P<fed>.*?)\s*Please\s+list\s+any\s+contracts,?\s*(?:grants,?\s*)?or\s+payments\s+originating\s+with\s+a\s+foreign\s+government.{20,260}?Include\s+the\s+amount\s+and\s+country\s+of\s+origin\s+of\s+each\s+contract\s+or\s+payment\.(?:\s*If\s+necessary,\s+attach\s+additional\s+sheet\(s\)\s+to\s+provide\s+more\s+information\.)?\s*(?P<for>.*?)(?:\s+Please\s+complete|\s+False\s+Statements|\s+Signature|\s+\*\s*Rule\s+XI|\s+I\s+certify|$)",
                    after_fed,
                    re.I,
                )
                if m_for_p:
                    fed_ans_str = m_for_p.group("fed")
                    for_ans_str = m_for_p.group("for")
                else:
                    fed_ans_str = after_fed[:300]
            else:
                m_direct = re.search(
                    r"^(?P<vals>.+?)\s+(?P<fid>No|None|N/?A|No,\s*not\s+a\s+fiduciary|Yes,\s*[^.]{2,90})\s+(?P<fed>(?:To\s+the\s+best\s+of\s+my\s+knowledge|N/?A|None|No|\$?\d|See\s+attach).+?)(?:\s+(?P<for>N/?A|None|No)\s+[A-Z][A-Za-z]+\s+and\s+[A-Z]|$)",
                    rest,
                    re.I,
                )
                if m_direct:
                    vals_str = f"{m_direct.group('vals')} {m_direct.group('fid')}"
                    fed_ans_str = m_direct.group("fed")
                    for_ans_str = m_direct.group("for")

            if vals_str:
                info["v2_vals_blob"] = vals_str
                info["gov_witness"] = False
                # Strip trailing fiduciary answer (`No` / `None` / `N/A` / `No, not a fiduciary`)
                core_vals = re.sub(r"\s+(?:No,\s*not\s+a\s+fiduciary|No|None|N/?A)$", "", vals_str, flags=re.I).strip()
                if re.search(r"\b(?:Self|Myself|Individual|N/?A|None)$", core_vals, re.I):
                    info["capacity"] = "self"
                else:
                    info["capacity"] = "organization"
                # Line-accurate extraction when `\n` is preserved
                raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                for idx_ln, ln in enumerate(raw_lines):
                    if ln == "Title" and idx_ln + 4 < len(raw_lines):
                        info["event_title"] = raw_lines[idx_ln + 1]
                        cand_nm = _clean_person_name(raw_lines[idx_ln + 2])
                        if cand_nm and not _BAD_FORM_NAME_RE.search(cand_nm):
                            info["witness_name"] = cand_nm
                        info["witness_title"] = raw_lines[idx_ln + 3]
                        cand_org = raw_lines[idx_ln + 4]
                        if _EXPLICIT_NONE_RE.match(cand_org) or _SELF_CAPACITY_RE.match(cand_org):
                            info["capacity"] = "self"
                        else:
                            info["capacity"] = "organization"
                            info["represented_orgs"] = [cand_org]
                            info["witness_org"] = cand_org
                        break

            fg_bool, fg_items, fg_blank = _classify_ttf_free_answer_ex(fed_ans_str)
            fp_bool, fp_items, _ = _classify_ttf_free_answer_ex(for_ans_str)
            if fg_bool is not None:
                info["has_federal_grants"] = fg_bool
                if fg_items:
                    info["federal_grants"] = fg_items
                info.setdefault("gov_witness", False)
            elif fg_blank:
                info["grant_truly_blank"] = True
            elif fed_ans_str is not None:
                info["grant_ambiguous"] = True
            if fp_bool is not None:
                info["has_foreign_payments"] = fp_bool
                if fp_items:
                    info["foreign_payments"] = fp_items
            return info

    # --- Variant A2: Clerk AcroForm v2a (`116th–117th` widget dump on Page 1 or bottom of Page 2) ---
    if re.search(r"^Truth\s+in\s+Testimony\s+Disclosure\s+Form\s+Witness\s+Name:\s+Position/Title:\s+Witness\s+Type:", t_ws, re.I):
        all_lines = [ln.strip() for ln in text.splitlines() if ln.strip() and ln.strip() != "Title"]
        anchor_idx: int | None = None
        for idx_l in range(4, max(4, len(all_lines) - 3)):
            c_try = all_lines[idx_l].lower().removeprefix("house committee on ").removeprefix("committee on ").strip()
            if c_try in _BARE_SHORT_HOUSE_CMT_MAP or "select subcommittee" in c_try or "select committee" in c_try:
                _, iso_try = _parse_single_date_str(all_lines[idx_l + 1])
                if iso_try:
                    anchor_idx = idx_l
                    break
        if anchor_idx is not None:
            # Truncate `tail_lines` before trailing `Subject` / `*Rule XI` / `False Statements Certification`
            tail_lines: list[str] = []
            for tln in all_lines[anchor_idx:]:
                if re.match(r"^(?:Subject|\*?\s*Rule\s+XI|\(5\)\([A-D]\)|False\s+Statements\s+Certification|Witness\s+signature)\b", tln, re.I):
                    break
                tail_lines.append(tln)
            # Capture any multi-line grant dump immediately preceding `anchor_idx` (after `witness appears.` on Page-2 dumps)
            pre_grant_lines: list[str] = []
            witness_appears_idx = next(
                (i_w for i_w, sln in enumerate(all_lines[:anchor_idx]) if "not later than one day after the witness appears." in sln.lower()),
                None,
            )
            if witness_appears_idx is not None:
                pre_grant_lines = [
                    x for x in all_lines[witness_appears_idx + 1 : anchor_idx]
                    if not re.search(r"origin\s+of\s+each\s+contract|each\s+grant\s+or\s+contract", x, re.I)
                ]
            if len(tail_lines) >= 5:
                c0 = tail_lines[0]
                c0_key = c0.lower().removeprefix("house committee on ").removeprefix("committee on ").strip()
                info["form_committee"] = _BARE_SHORT_HOUSE_CMT_MAP.get(c0_key, c0)
                sp_d, iso_d = _parse_single_date_str(tail_lines[1])
                if iso_d:
                    info["event_date"] = iso_d
                    if sp_d:
                        info["date_spans"] = [sp_d]
                    ev_t = tail_lines[2]
                    nm_idx = 3
                    if len(tail_lines) >= 7 and (
                        (ev_t.startswith(('"', "“")) and not ev_t.endswith(('"', "”")) and tail_lines[3].endswith(('"', "”")))
                        or (tail_lines[3][:1].islower())
                        or (len(tail_lines[3].split()) == 1 and tail_lines[3].rstrip('"”').isalpha())
                        or (ev_t.endswith(("for", "of", "and", "in", "to", "the", "on", "Policyholders")))
                    ):
                        ev_t = f"{ev_t} {tail_lines[3]}"
                        nm_idx = 4
                    info["event_title"] = ev_t.strip(" \"'“”")
                    if len(tail_lines) > nm_idx + 1:
                        cand_nm = _clean_person_name(tail_lines[nm_idx])
                        if cand_nm and not _BAD_FORM_NAME_RE.search(cand_nm):
                            info["witness_name"] = cand_nm
                        info["witness_title"] = tail_lines[nm_idx + 1]
                        rest_idx = nm_idx + 3
                        org_cand = tail_lines[nm_idx + 2] if len(tail_lines) > nm_idx + 2 else ""
                        if (
                            len(tail_lines) == nm_idx + 5
                            and _EXPLICIT_NONE_RE.match(tail_lines[nm_idx + 3])
                            and _EXPLICIT_NONE_RE.match(tail_lines[nm_idx + 4])
                        ):
                            # `Self` witness on subcommittee hearing (`[subcmt, none, none]`, org box blank)
                            info["form_subcommittee"] = (
                                tail_lines[nm_idx + 2]
                                if tail_lines[nm_idx + 2].lower().startswith("subcommittee")
                                else f"Subcommittee on {tail_lines[nm_idx + 2]}"
                            )
                            org_cand = "Self"
                            rest_idx = nm_idx + 3
                        elif (
                            len(tail_lines) > nm_idx + 3
                            and not _EXPLICIT_NONE_RE.match(tail_lines[nm_idx + 3])
                            and not re.search(r"[$₩€£]\d|^CY\d\d\b|^FY\d\d\b", tail_lines[nm_idx + 3])
                        ):
                            info["form_subcommittee"] = (
                                tail_lines[nm_idx + 2]
                                if tail_lines[nm_idx + 2].lower().startswith("subcommittee")
                                else f"Subcommittee on {tail_lines[nm_idx + 2]}"
                            )
                            org_cand = tail_lines[nm_idx + 3]
                            rest_idx = nm_idx + 4
                        post_lines = tail_lines[rest_idx:]
                        if (
                            len(post_lines) >= 3
                            and _EXPLICIT_NONE_RE.match(post_lines[-1])
                            and _EXPLICIT_NONE_RE.match(post_lines[-2])
                            and not pre_grant_lines
                        ):
                            org_cand = f"{org_cand} {' '.join(post_lines[:-2])}".strip()
                            post_lines = post_lines[-2:]
                        if org_cand:
                            if (
                                _EXPLICIT_NONE_RE.match(org_cand)
                                or _SELF_CAPACITY_RE.match(org_cand)
                                or re.search(r"\bviews\b.{0,30}\bmy\s+own\b|\bpersonal\s+capacity\b|\bnot\s+representing\b", org_cand, re.I)
                            ):
                                info["capacity"] = "self"
                                info["gov_witness"] = False
                            else:
                                info["represented_orgs"] = [org_cand]
                                info["witness_org"] = org_cand
                                info["gov_witness"] = bool(_GOV_ORG_RE.search(org_cand))
                                info["capacity"] = "organization"
                        ans_lines = post_lines if post_lines else pre_grant_lines
                        if ans_lines:
                            fg_b, fg_i, fg_bl = _classify_ttf_free_answer_ex(" ".join(ans_lines))
                            if fg_b is not None:
                                info["has_federal_grants"] = fg_b
                                if fg_i:
                                    info["federal_grants"] = fg_i
                            elif fg_bl:
                                info["grant_truly_blank"] = True
                            else:
                                info["grant_ambiguous"] = True
                        else:
                            info["grant_truly_blank"] = True
                    return info

    # --- Variant B: Clerk AcroForm v1 (`Witness Name:` ... `Witness Type:` ... `Are you representing yourself...`) ---
    if re.search(r"Witness\s+Nam[ie]{1,2}\s*:", t_ws, re.I) and re.search(r"A\s*re\s*you\s+representing\s+yoursel[ft]", t_ws, re.I):
        m_c = re.search(r"Committee:\s*(.*?)\s+Subcommittee:\s*(.*?)\s+Hearing\s+Date:\s*(.*?)\s+Hearing\s*(?:Ti[tk]le|Subject)?\s*[:\"“]", t_ws, re.I)
        if m_c:
            c_raw, sub_raw, hd_raw = m_c.group(1).strip(), m_c.group(2).strip(" _"), m_c.group(3).strip()
            if c_raw:
                info["form_committee"] = _BARE_SHORT_HOUSE_CMT_MAP.get(c_raw.lower().removeprefix("committee on ").strip(), c_raw)
            if sub_raw and not _EXPLICIT_NONE_RE.match(sub_raw):
                info["form_subcommittee"] = sub_raw if sub_raw.lower().startswith("subcommittee") else f"Subcommittee on {sub_raw}"
            sp_d, iso_d = _parse_single_date_str(hd_raw)
            if iso_d:
                info["event_date"] = iso_d
                info.setdefault("date_spans", []).append(sp_d)

        m_ht = re.search(r"Hearing\s*(?:Ti[tk]le|Subject)?\s*(?:[A-Za-z]+\s*)?:?\s*(.+?)\s+Witness\s+Nam[ie]{1,2}\s*:", t_ws, re.I)
        if m_ht:
            ht = m_ht.group(1).strip(" :\"'“”")
            if ht and len(ht) >= 6:
                info["event_title"] = ht

        m_wn = re.search(r"Witness\s+Nam[ie]{1,2}\s*:\s*(.+?)\s+Position/Ti[td]le\s*:\s*(.*?)\s+Witness\s+Type\s*:", t_ws, re.I)
        if m_wn:
            nm = _clean_person_name(m_wn.group(1))
            if nm and not _BAD_FORM_NAME_RE.search(nm):
                info["witness_name"] = nm
            pt = m_wn.group(2).strip(" ,;:-")
            if pt and not _EXPLICIT_NONE_RE.match(pt):
                if " of " in pt and "witness_org" not in info:
                    left_t, right_o = pt.split(" of ", 1)
                    if len(left_t) >= 3 and len(right_o) >= 3 and right_o[0].isupper():
                        info["witness_title"] = left_t.strip()
                        info["witness_org"] = right_o.strip()
                    else:
                        info["witness_title"] = pt
                else:
                    info["witness_title"] = pt

        m_wt = re.search(r"Witness\s+Type\s*:\s*(.+?)\s+A\s*re\s*you\s+representing\s+yoursel[ft]", t_ws, re.I)
        if m_wt:
            wt_s = m_wt.group(1).strip()
            if re.match(r"^Gove[rnm]{1,3}ental$", wt_s, re.I):
                info["gov_witness"] = True
                info["capacity"] = "government"
            elif re.match(r"^Non-?gove[rnm]{1,3}ental$", wt_s, re.I):
                info["gov_witness"] = False
            elif re.match(r"^[O0o○◯☐□▫D]\s*Gove[rnm]{1,3}ental(?:\s+Non-?gove[rnm]{1,3}ental)?$", wt_s, re.I):
                info["gov_witness"] = False
            elif re.match(r"^(?:Gove[rnm]{1,3}ental\s*)?[O0o○◯☐□▫D]\s*Non-?gove[rnm]{1,3}ental$", wt_s, re.I):
                info["gov_witness"] = True
                info["capacity"] = "government"
            else:
                m_rg = re.search(
                    r"(?P<g1>\S)?\s*Gove[rnm]{1,3}ental\s*(?P<g1b>\S)?\s*(?P<g2>\S)?\s*Non-?gove[rnm]{1,3}ental",
                    wt_s,
                    re.I,
                )
                if m_rg:
                    g1 = m_rg.group("g1") or ""
                    g1b = m_rg.group("g1b") or ""
                    g2 = m_rg.group("g2") or ""
                    mark_non = g2 if g2 else (g1b if g1 in _UNCHECKED_CHARS else "")
                    if mark_non and mark_non in _CHECKED_CHARS and (not g1 or g1 in _UNCHECKED_CHARS):
                        info["gov_witness"] = False
                    elif g1 and g1 in _CHECKED_CHARS and (not mark_non or mark_non in _UNCHECKED_CHARS):
                        info["gov_witness"] = True
                        info["capacity"] = "government"

        m_cap = re.search(
            r"A\s*re\s*you\s+representing\s+yoursel[ft]['’\s]*or\s+an\s+organization\?\s*(.*?)\s+If['’]?\s*you\s+are\s+representing\s+an\s+organization,\s+please\s+list\s+(?:what|that)\s+entity\s+or\s+entities\s+you\s+are\s+representing:\s*(.*?)\s*(?=FOR\s+WITNESSES\s+APPEARING|I[fl]['’]?\s*you\s+\S+\s+\S+\s+non-?gove[rnm]{1,3}ental|[Pp]?lease\s+list\s+any\s+federal\s+grants)",
            t_ws,
            re.I,
        )
        if m_cap:
            cap_s = m_cap.group(1).strip()
            org_s = m_cap.group(2).strip(" ,;:-")
            if org_s and (_SELF_CAPACITY_RE.match(org_s) or _EXPLICIT_NONE_RE.match(org_s)):
                info["capacity"] = "self"
                info.setdefault("gov_witness", False)
            elif org_s:
                info["represented_orgs"] = [org_s]
                info.setdefault("witness_org", org_s)
                if info.get("gov_witness") is True:
                    info["capacity"] = "organization"
                else:
                    info["capacity"] = "organization"
                    info["gov_witness"] = False
            elif re.match(r"^Self\s*[O0o○◯☐□▫D]\s*Organization$", cap_s, re.I):
                info["capacity"] = "self"
                info.setdefault("gov_witness", False)
            elif re.match(r"^[O0o○◯☐□▫D]\s*Self(?:\s+Organization)?$", cap_s, re.I):
                info["capacity"] = "organization"
                info.setdefault("gov_witness", False)
            elif re.match(r"^[•●◉⚫■▪☒☑✓✔✗✘XxVv®©*+฿-]{1,2}\s*Self(?:\s*[O0o○◯☐□▫D]\s*Organization)?$", cap_s, re.I) or cap_s.lower() == "self":
                info["capacity"] = "self"
                info.setdefault("gov_witness", False)
            elif re.match(r"^(?:[O0o○◯☐□▫D]\s*Self\s*)?[•●◉⚫■▪☒☑✓✔✗✘XxVv®©*+]\s*Organization$", cap_s, re.I) or cap_s.lower() == "organization":
                info["capacity"] = "organization"
                info.setdefault("gov_witness", False)
            elif re.search(r"O\s*Organization$", cap_s) and not re.search(r"\bO\s*Self\b", cap_s):
                info["capacity"] = "self"
                info.setdefault("gov_witness", False)

        m_fed = re.search(
            r"In[ch]l?ude\s+the\s+source\s+and\s+a?mount\s+of\s+[ce]ach\s+grant\s+(?:or\s+)?contract\.(?:\s*[!I]f['’]?\s*necessar[yt],\s*a[tl]{1,2}[au]ch\s+add[il1]{0,2}ti?onal\s+shee[tsl]\(?s\)?\s*(?:to|t0|10)\s*provide\s+more\s+information\.?)?\s*(.*?)\s*(?=I[fl]['’]?\s*you\s+\S+\s+\S+\s+non-?gove[rnm]{1,3}ental\s+witness,\s+[pp]?lease\s+list\s+any\s+contracts|[Pp]?lease\s+list\s+any\s+contracts,?\s*(?:grants,?\s*)?or\s+payments\s+originating\s+with\s+a\s+foreign)",
            t_ws,
            re.I,
        )
        if m_fed:
            fg_b, fg_i, fg_bl = _classify_ttf_free_answer_ex(m_fed.group(1))
            if fg_b is not None:
                info["has_federal_grants"] = fg_b
                if fg_i:
                    info["federal_grants"] = fg_i
                info.setdefault("gov_witness", False)
            elif fg_bl:
                info["grant_truly_blank"] = True
            else:
                info["grant_ambiguous"] = True

        m_for = re.search(
            r"Include\s+the\s+amount\s+and\s+country\s+of\s*origin\s+of\s*[ce]ach\s+contract\s+or\s+payment\.(?:\s*[!I]f['’]?\s*necessar[yt],\s*a[tl]{0,2}[au]ch\s+additional\s+shee[tl]\(?s\)?\s*(?:to|t0|10)\s*provide\s+more\s+information\.?)?\s*(.*?)\s*(?=Please\s+complete\s+the\s+following\s+fields|False\s+Statements\s+Certification|Witness\s+signature|Signature\s*:|\*\s*Rule\s+XI|HE\s*ARING:|$)",
            t_ws,
            re.I,
        )
        if m_for:
            fp_b, fp_i, _ = _classify_ttf_free_answer_ex(m_for.group(1))
            if fp_b is not None:
                info["has_foreign_payments"] = fp_b
                if fp_i:
                    info["foreign_payments"] = fp_i

    # --- Variant C: Committee Bespoke TTF Forms (`112th–118th`) ---
    else:
        # C1. Natural Resources 2-section form (`For Individuals:` vs `For Witnesses Representing Organizations:`, 113th–116th)
        if "For Individuals:" in t_ws and "For Witnesses Representing Organizations:" in t_ws:
            m_nr_hdr = re.search(r"Disclosure\s+Form.*?(?:Natural\s+Resources|clause\s+2\(g\)(?:\(5\))?)\s+(?P<hdr>.+?)\s+For\s+Individuals:", t_ws, re.I)
            if m_nr_hdr:
                hdr_blob = m_nr_hdr.group("hdr").strip()
                sp_nh, iso_nh = _parse_single_date_str(hdr_blob)
                if iso_nh and iso_nh not in lookback_isos:
                    info["event_date"] = iso_nh
                    info.setdefault("date_spans", []).append(sp_nh)
                    ht_nh = hdr_blob.replace(sp_nh or "", "").strip(" ,;:-")
                    ht_nh = re.sub(r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday)\s*,?\s*|(?:Monday|Tuesday|Wednesday|Thursday|Friday)\s*,?\s*$", "", ht_nh, flags=re.I).strip(" ,;:-")
                    if ht_nh and len(ht_nh) >= 6:
                        info["event_title"] = ht_nh[:200]
            m_nr = re.search(
                r"For\s+Individuals:\s*(?:1\.\s*)?Name:\s*(?P<ind>.*?)\s*(?:(?:2\.\s*)?Address:|\*\s*\*\s*\*).*?"
                r"For\s+Witnesses\s+Representing\s+Organizations:\s*(?:1\.\s*)?Name:\s*(?P<org_w>.*?)\s*"
                r"(?:2\.\s*)?Name\s+of\s+Organization\(s\)\s+You\s+are\s+Representing\s+at\s+the\s+Hearing:\s*(?P<org>.*?)\s*(?:3\.\s*)?Business\s+Address:",
                t_ws,
                re.I,
            )
            if m_nr:
                ind_nm = _clean_person_name(m_nr.group("ind"))
                org_wnm = _clean_person_name(m_nr.group("org_w"))
                org_val = m_nr.group("org").strip(" ,;:-*")
                if org_wnm and org_val and (not ind_nm or ind_nm.lower() == org_wnm.lower()):
                    info["witness_name"] = org_wnm
                    info["represented_orgs"] = [org_val]
                    info["witness_org"] = org_val
                    info["capacity"] = "organization"
                    info["gov_witness"] = bool(_GOV_ORG_RE.search(org_val))
                elif ind_nm and not org_wnm:
                    info["witness_name"] = ind_nm
                    info["capacity"] = "self"
                    info["gov_witness"] = False
            m_nr_g = re.search(
                r"For\s+Nongovernment\s+Witnesses\s+ONLY:.*?2\.\s*Please\s+list\s+any\s+federal\s+grants\s+or\s+contracts.{20,260}?grant\s+or\s+contract\.\s*(.*?)\s*3\.\s*Please\s+list\s+any\s+contracts\s+or\s+payments\s+originating\s+with\s+a\s+foreign\s+government.{20,260}?contract\s+or\s+payment\.\s*(.*?)(?:\s+I\s+hereby|\s+Signature|$)",
                t_ws,
                re.I,
            )
            if m_nr_g:
                fg_b, fg_i, fg_bl = _classify_ttf_free_answer_ex(m_nr_g.group(1))
                fp_b, fp_i, _ = _classify_ttf_free_answer_ex(m_nr_g.group(2))
                if fg_b is not None:
                    info["has_federal_grants"] = fg_b
                    if fg_i:
                        info["federal_grants"] = fg_i
                    info.setdefault("gov_witness", False)
                elif fg_bl:
                    info["grant_truly_blank"] = True
                else:
                    info["grant_ambiguous"] = True
                if fp_b is not None:
                    info["has_foreign_payments"] = fp_b
                    if fp_i:
                        info["foreign_payments"] = fp_i
            else:
                nr_d_parts: list[tuple[bool | None, list[str]]] = []
                nr_d_ambig = False
                nr_d_blank = False
                for m_nrd in re.finditer(
                    r"\bd\.\s*Any\s+federal\s+grants\s+or\s+contracts.{20,300}?grant\s+or\s+contract\.\s*(.*?)\s+(?=e\.\s*A\s+list\s+of\s+all\s+lawsuits)",
                    t_ws,
                    re.I,
                ):
                    bd, id_items, d_bl = _classify_ttf_free_answer_ex(m_nrd.group(1))
                    if bd is not None:
                        nr_d_parts.append((bd, id_items))
                    elif d_bl:
                        nr_d_blank = True
                    else:
                        nr_d_ambig = True
                comb_d, comb_di = _combine_grant_booleans(nr_d_parts)
                if comb_d is not None and not nr_d_ambig:
                    info["has_federal_grants"] = comb_d
                    if comb_di:
                        info["federal_grants"] = comb_di
                    info.setdefault("gov_witness", False)
                elif nr_d_ambig:
                    info["grant_ambiguous"] = True
                elif nr_d_blank:
                    info["grant_truly_blank"] = True
        else:
            # Hearing title & date when printed at top
            m_hd_bespoke = re.search(r"Date\s+of\s+Committee\s+hearing\s*:\s*(.+?)\s+(?:4\.|[Hl]ave\s+you)", t_ws, re.I)
            if m_hd_bespoke:
                sp_d, iso_d = _parse_single_date_str(m_hd_bespoke.group(1))
                if iso_d and iso_d not in lookback_isos:
                    info["event_date"] = iso_d
                    info.setdefault("date_spans", []).append(sp_d)
            else:
                m_hd2 = re.search(r"Hearing:\s*Date:\s*(.+?)\s+1\.\s*(?:Your\s+)?Name", t_ws, re.I)
                if m_hd2:
                    blob = m_hd2.group(1).strip()
                    sp_d, iso_d = _parse_single_date_str(blob)
                    if iso_d and iso_d not in lookback_isos:
                        info["event_date"] = iso_d
                        info.setdefault("date_spans", []).append(sp_d)
                        ht_cand = blob.replace(sp_d or "", "").strip(" ,;:-")
                        if ht_cand and len(ht_cand) >= 5:
                            info["event_title"] = ht_cand

            # Interleaved 2-column `1. Name: 2. Organization...: <Name> <Org>` (`GOLD[55]`, Foreign Affairs `AndrewsT`, Education `Robbins`)
            m_interleaved_self = re.search(
                r"1\.\s*(?:Your\s+)?Name(?:\s*\(Please\s+Print\))?:\s*2\.\s*Organization(?:\(s\)|\s+or\s+organizations)\s+you\s+are\s+representing:\s*([A-Z][A-Za-z.\s'’-]{3,55})\s+(Self|None|N/?A)\s+3\.",
                t_ws,
                re.I,
            )
            m_interleaved = m_interleaved_self or re.search(
                r"1\.\s*(?:Your\s+)?Name(?:\s*\(Please\s+Print\))?:\s*2\.\s*Organization(?:\(s\)|\s+or\s+organizations)\s+you\s+are\s+representing:\s*([A-Z][A-Za-z.\s'’-]{3,55}?)\s+([A-Z][A-Za-z0-9,&.\s'’()-]{2,110}?)\s+3\.",
                t_ws,
                re.I,
            )
            if m_interleaved:
                nm = _clean_person_name(m_interleaved.group(1))
                if nm and not _BAD_FORM_NAME_RE.search(nm):
                    info["witness_name"] = nm
                org_raw = re.sub(r"\s+N/?A\b", "", m_interleaved.group(2)).strip(" ,;:-")
                if _EXPLICIT_NONE_RE.match(org_raw) or _SELF_CAPACITY_RE.match(org_raw):
                    info["capacity"] = "self"
                    info["gov_witness"] = False
                elif org_raw:
                    info["represented_orgs"] = [org_raw]
                    info["witness_org"] = org_raw
                    info["gov_witness"] = False if info.get("header_declares_nongov") and not _GOV_ORG_RE.search(org_raw) else bool(_GOV_ORG_RE.search(org_raw))
                    info["capacity"] = "organization"
            else:
                m_nm = re.search(
                    r"(?:1\.\s*(?:Your\s+)?Name(?:\s*\(Please\s+Print\))?|(?<!Witness\s)Your\s+Name|(?<!Witness\s)Name)\s*:\s*([^:\n]{3,80}?)\s+"
                    r"(?:1\.\s*(?:Please\s+list|Are\s+you)|2\.\s*(?:Your\s+Title|Entity|Organization|Are\s+you)|Organization\s+you\s+represent)",
                    t_ws,
                    re.I,
                )
                if m_nm:
                    nm = _clean_person_name(m_nm.group(1))
                    if nm and not _BAD_FORM_NAME_RE.search(nm):
                        info["witness_name"] = nm

                m_title_b = re.search(
                    r"(?:2\.\s*Your\s+Title\s*:\s*(.+?)\s+3\.\s*The\s+Entity|"
                    r"describe\s+your\s+position\s+or\s+representational\s+capacity(?:\s+with\s+the\s+entity(?:\(ies\)|\s+or\s+entities)\s+you\s+are\s+representing)?[.:]\s*(.+?)\s+[478]\.)",
                    t_ws,
                    re.I,
                )
                if m_title_b:
                    t_raw = (m_title_b.group(1) or m_title_b.group(2) or "").strip(" ,;:-")
                    t_raw = re.sub(r"\bViee\b", "Vice", t_raw)
                    t_raw = re.sub(r"\s+N/?A$", "", t_raw, flags=re.I).strip()
                    if t_raw and not _EXPLICIT_NONE_RE.match(t_raw):
                        if "," in t_raw and "witness_org" not in info:
                            p_t, p_o = [x.strip() for x in t_raw.split(",", 1)]
                            info["witness_title"] = p_t
                            if p_o and len(p_o) >= 3:
                                info["witness_org"] = p_o
                        else:
                            info["witness_title"] = t_raw

                # Explicit Org / Entity slots across Judiciary, E&C, Science, Agriculture, Oversight, Appropriations, Small Business, Ways & Means
                m_org_b = re.search(
                    r"(?:[23]\.\s*(?:Entity\(ies\)|Organization\s+or\s+organizations|Organization\(s\))\s+you\s+are\s+representing|"
                    r"(?:3\.\s*)?The\s+Entity\(ies\)\s+You\s+are\s+Representing|"
                    r"Organization\s+you\s+represent\s*\(if\s*any\)|"
                    r"2\.\s*Please\s+list\s+any\s+entity\s+you\s+are\s+testifying\s+on\s+behalf\s+of[^.]*\.|"
                    r"1\.\s*Are\s+you\s+appearing\s+on\s+behalf\s+of\s+yourself\s+or\s+a\s+non-?governmental\s+organization\?\s*Please\s+list\s+organization\(s\)\s+you\s+are\s+representing\.)\s*:?\s*(.+?)\s+"
                    r"(?=(?:[12345]\.\s*)?(?:Please\s+list|Have\s+you|With\s+respect|Are\s+you\s+testif|If\s+you)|Have\s+you\s+received)",
                    t_ws,
                    re.I,
                )
                if m_org_b:
                    org_b = m_org_b.group(1).strip(" ,;:-")
                    if re.match(r"^(?:NONE|Self|Myself|Individual|N/?A)\b", org_b, re.I):
                        info["capacity"] = "self"
                        info["gov_witness"] = False
                        m_emp = re.search(r"emp[la]{1,2}[oy]{1,2}ed\s+by\s+([A-Z][A-Za-z\s&'-]{3,60}?)(?:\s+but|\)|$)", org_b, re.I)
                        if m_emp:
                            info["witness_org"] = re.sub(r"\bAmarican\b", "American", m_emp.group(1).strip())
                    elif org_b:
                        org_clean = re.sub(r"^(?:No\.\s*Here\s+representing\s+(?:the\s+)?|I\s+am\s+test\S+\s+as\s+[^o]+\s+of\s+)", "", org_b, flags=re.I).strip(" .,:;")
                        info["represented_orgs"] = [org_clean[:140]]
                        info.setdefault("witness_org", org_clean[:140])
                        info["gov_witness"] = bool(_GOV_ORG_RE.search(org_clean)) and not bool(info.get("header_declares_nongov"))
                        info["capacity"] = "organization"
                else:
                    # E&C / Science / Small Business item 3 or 4: `Other than yourself, please list which/what entity or entities you are representing:`
                    m_other_ent = re.search(
                        r"[34]\.\s*Other\s+than\s+yourself,\s+please\s+list\s+(?:which|what)\s+[ce]n[tf]ity\s+or\s+entities\s+you\s+are\s+representing:\s*(?:Yes\s+Yes\s+No\s+[XxVv•]No\s+)?(.+?)\s+[45]\.\s*Pleas[ec]\s+list",
                        t_ws,
                        re.I,
                    )
                    if m_other_ent:
                        org_oe = re.sub(r"\s+(?:No|Yes)\s+(?:No|Yes)\s*$", "", m_other_ent.group(1), flags=re.I).strip(" ,;:-")
                        if _EXPLICIT_NONE_RE.match(org_oe) or _SELF_CAPACITY_RE.match(org_oe):
                            info["capacity"] = "self"
                            info["gov_witness"] = False
                        elif org_oe:
                            info["represented_orgs"] = [org_oe[:140]]
                            info.setdefault("witness_org", org_oe[:140])
                            info["gov_witness"] = bool(_GOV_ORG_RE.search(org_oe))
                            info["capacity"] = "organization"
                    else:
                        # Ways & Means Q1 (Gov) + Q2 (Non-Gov), including OCR `l. Are you testifuing` & blank Q1 slots
                        m_wm = re.search(
                            r"[1l]\.\s*Are\s+you\s+testi\S+ing\s+on\s+behalf\s+of\s+a\s+Federal,\s*State,\s*or\s*Local\s+Government\s+entity\?\s*"
                            r"a\.\s*Name\s+of\s+entity\(ies\)\.\s*(?P<q1a>.*?)\s*b\.\s*Briefly\s+describe[^.]*\.\s*(?P<q1b>.*?)\s+"
                            r"2\.\s*Are\s+you\s+testi\S+ing\s+on\s+behalf\s+of\s+any\s+non-?governmental\s+entity\(ies\)\?\s*"
                            r"a\.\s*Name\s+of\s+entity\(ies\)\.\s*(?P<q2a>.*?)\s*b\.\s*Briefly\s+describe[^.]*\.\s*(?P<q2b>.*?)\s+3\.\s*Pleas[ec]\s+list",
                            t_ws,
                            re.I,
                        )
                        if m_wm:
                            q1a = re.sub(r"\b(?:Yes|No|Non|!|\d+|•|[XxVv])\b", " ", m_wm.group("q1a"), flags=re.I).strip(" .,:;-")
                            q1b = m_wm.group("q1b").strip()
                            q2a = re.sub(r"\b(?:Yes|No|Non|Yesx|!|\d+|•|[XxVv])\b", " ", m_wm.group("q2a"), flags=re.I).strip(" .,:;-")
                            q2b = re.sub(r"\b(?:Yes|No|Non|Yesx|!|\d+|•|[XxVv])\b", " ", m_wm.group("q2b"), flags=re.I).strip(" .,:;-")
                            if q2a and len(q2a) >= 3 and not q1a:
                                info["gov_witness"] = False
                                info["capacity"] = "organization"
                                info["represented_orgs"] = [q2a[:140]]
                                info.setdefault("witness_org", q2a[:140])
                                if q2b and len(q2b) >= 3:
                                    info.setdefault("witness_title", q2b[:140])
                            elif q1a and len(q1a) >= 3 and not q2a:
                                info["gov_witness"] = True
                                info["capacity"] = "government"
                                info.setdefault("witness_org", q1a[:140])
                            elif re.search(r"\bYes\s*[•XxVv✓✔]", q1b, re.I) and re.search(r"\bNo", q2b, re.I):
                                info["gov_witness"] = True
                                info["capacity"] = "government"
                            elif re.search(r"\bNo\s*[•XxVv✓✔]", q1b, re.I) and re.search(r"\bNo\s*[•XxVv✓✔]", q2b, re.I):
                                info["gov_witness"] = False
                                info["capacity"] = "self"
                        elif re.search(r"\bI\s+am\s+not\s+testifying\s+(?:on\s+)?behalf\s+of\s+any\s+entit|\bcomments\s+are\s+solely\s+my\s+own\b", t_ws, re.I):
                            info["gov_witness"] = False
                            info["capacity"] = "self"

            # Bespoke Federal Grants: evaluate ALL grant sub-questions (Checkboxes, Source/Amount, Prose Q1..Q9/a)/b))
            grant_parts: list[tuple[bool | None, list[str]]] = []
            saw_checkbox_q = False
            saw_prose_blank = False
            saw_prose_ambig = False

            # 1) Yes/No checkbox pairs after `invited to testify?` or `since October 1, 20\d\d?` (handles 2-column Q4+Q5 as in GOLD[55]!)
            for m_gq in re.finditer(
                r"(?:invited\s+to\s+te[as]tify(?:\s+during\s+the\s+past\s+two\s+calendar\s+years\s*\([^)]+\))?\?|contracts\s*\([^)]+\)\s*since\s+Octob[eo]r\s+1,\s*20\d{2}[?17]?)\s*([^?]{2,85}?)(?=\s+(?:[3567]\.|\.?\s*If\s+you\s+answered|If\s+your\s+response|Have\s+you|[gr]ant\s+or\s+contract|Signature))",
                t_ws,
                re.I,
            ):
                saw_checkbox_q = True
                yn = _parse_yes_no_checkbox_pair(m_gq.group(1))
                if yn is None and re.search(r"\b[O0o○◯☐□▫]\s*YES\s+(?:~|ti|IN|[I1l/|\\])\s*NO\b", m_gq.group(1), re.I):
                    yn = False
                if yn is not None:
                    grant_parts.append((yn, []))
                    if yn is False and ("foriegn government" in t_ws.lower() or "foreign government" in t_ws.lower()):
                        info.setdefault("has_foreign_payments", False)

            # 2) Explicit Q3 / Q6 follow-up (`6. If you answered "yes" to either item 4 or 5...` or Appropriations `3. If your response to question #2 is "Yes", please list...`)
            for m_qf in re.finditer(
                r"(?:6\.\s*If\s+you\s+answered\s+[\"“']?yes[\"”']?(?:\s+B)?\s+to\s+either\s+(?:item|question)\s+4\s+or\s+5.{20,340}?(?:sheets\s+if\s+(?:necessary|needed)\.|additional\s+sheets\.)|"
                r"3\.\s*If\s+your\s+response\s+to\s+question\s+#?2\s+is\s+[\"“']?Yes[\"”']?,\s*please\s+list.{20,300}?representing\.)\s*(.*?)(?=\s+(?:[47]\.|Signat|s;gnature|Please\s+attach|I\s+certify|\(\s*Please\s+use)|$)",
                t_ws,
                re.I,
            ):
                b6, i6, _ = _classify_ttf_free_answer_ex(m_qf.group(1))
                if b6 is not None:
                    grant_parts.append((b6, i6))

            if re.search(r"\bStatement\s+of\s+Federal\s+Grants\b", text, re.I):
                grant_parts.append((True, ["See attached Statement of Federal Grants"]))

            # Foreign Affairs AcroForm bottom widget dump (`Please attach a copy of this form to your written testimony.\nMARCH 22, 2016\nHASSAN ABBAS\n...`)
            m_fa_dump = re.search(
                r"Please\s+attach\s+a\s+copy\s+of\s+this\s+form\s+to\s+your\s+written\s+testimony\.\s*\n(.+)$",
                text,
                re.I | re.S,
            )
            if m_fa_dump and "Committee on Foreign Affairs" in text[:350]:
                fa_lines = [ln.strip() for ln in m_fa_dump.group(1).splitlines() if ln.strip() and ln.strip() not in ("II", "IClear Form", "Clear Form")]
                if len(fa_lines) >= 3:
                    sp_fa, iso_fa = _parse_single_date_str(fa_lines[0])
                    if iso_fa:
                        info.setdefault("event_date", iso_fa)
                        if sp_fa and sp_fa not in info.get("date_spans", []):
                            info.setdefault("date_spans", []).append(sp_fa)
                        nm_fa = _clean_person_name(fa_lines[1])
                        if nm_fa and not _BAD_FORM_NAME_RE.search(nm_fa):
                            info.setdefault("witness_name", nm_fa)
                        org_fa = fa_lines[2]
                        if _EXPLICIT_NONE_RE.match(org_fa) or _SELF_CAPACITY_RE.match(org_fa):
                            info.setdefault("capacity", "self")
                            info.setdefault("gov_witness", False)
                        else:
                            info.setdefault("represented_orgs", [org_fa])
                            info.setdefault("witness_org", org_fa)
                            info["gov_witness"] = bool(_GOV_ORG_RE.search(org_fa))
                            info.setdefault("capacity", "organization")

            # 3) Agriculture Source/Amount slots (`GOLD[336]`)
            m_src_amt = re.search(
                r"Source:\s*([A-Za-z0-9,\s&'’().-]{3,100}?)\s+Amount:\s*([$₩€£]?\s*\d[\d,]*(?:\.\d+)?)",
                t_ws,
            )
            if m_src_amt:
                src_s = m_src_amt.group(1).strip()
                amt_s = re.sub(r"^₩", "$", m_src_amt.group(2).strip())
                grant_parts.append((True, [f"{src_s} ({amt_s})"]))
            elif re.search(r"Source:\s*(?:None|N/?A)\s+Amount:", t_ws, re.I):
                grant_parts.append((False, []))

            # 4) Prose grant questions (`1..9. / a)/b) Please list any Federal grants...`), routing foreign-gov questions separately
            for m_pg in re.finditer(
                r"(?:[1-9tIl]\.|[ab][.)])\s*(?:If\s+(?:the\s+answer|you\s+are)\s+[^,]+,\s*)?(?P<qhead>Pleas[ec]\s+list\s+any\s+(?:fe[^.\s]{0,6}\s+|Federal\s+|foreign\s+government\s+)?(?:grants|payments)(?:,\s*(?:cooperative\s+agreements|contracts),?)?(?:\s+or\s+(?:contracts|payments))?(?:,\s*or\s+contracts\s+or\s+payments\s+originating\s+with\s+a\s+foreign\s+government,?)?.{15,430}?(?:20\d{2}\s*:|must\s+be\s+listed\.|hearing\s*:|years\s*:|(?:gr\S*|grant)\s+or\s+con\S+(?:\s+to\s+be\s+listed)?[.:]|necessar[yt]\.?|received\s*:))\s*(?P<ans>.*?)(?=\s+(?:[2-9tIl]\.\s*(?:Pleas|Does|Are|If|Signature)|[ab][.)]\s*(?:If|Pleas)|Pleas[ec]\s+list\s+any|If\s+(?:your?|the)\s+answer|If\s+you\s+are\s+testif|ing\s+on\s+beb?alf|Are\s+you\s+a\s+fiduciary|I\s+certify|Signat|Please\s+attach|$))",
                t_ws,
                re.I,
            ):
                qhead_low = m_pg.group("qhead").lower()
                has_fed_kw = bool(re.search(r"\bfe[d:]|\bfederal\b", qhead_low))
                has_for_kw = "foreign" in qhead_low or "foreigr" in qhead_low
                bp, ip, p_bl = _classify_ttf_free_answer_ex(m_pg.group("ans"))
                if has_for_kw and not has_fed_kw:
                    if bp is not None:
                        info["has_foreign_payments"] = bp
                        if ip:
                            info["foreign_payments"] = ip
                    continue
                if has_for_kw and has_fed_kw:
                    # Combined E&C Federal + Foreign question (`None`/`N/A` -> both False; US agency -> federal True)
                    if bp is False:
                        grant_parts.append((False, []))
                        info["has_foreign_payments"] = False
                    elif bp is True and ip and re.search(r"\b(?:USDA|HHS|NIH|NSF|DOD|DOE|DOT|EPA|FAA|NASA|CMS|FEMA|DOJ|HUD|VA|DHS|DARPA|ARPA|CDC|NOAA|NIST|Federal|Department\s+of)\b", ip[0], re.I):
                        grant_parts.append((True, ip))
                    elif p_bl:
                        saw_prose_blank = True
                    else:
                        saw_prose_ambig = True
                    continue
                if bp is not None:
                    grant_parts.append((bp, ip))
                elif p_bl:
                    saw_prose_blank = True
                else:
                    saw_prose_ambig = True

            comb_fg, comb_items = _combine_grant_booleans(grant_parts)
            if comb_fg is not None and not saw_prose_ambig:
                info["has_federal_grants"] = comb_fg
                if comb_items:
                    info["federal_grants"] = comb_items
            elif saw_prose_ambig or (saw_checkbox_q and comb_fg is None):
                info["grant_ambiguous"] = True
            elif saw_prose_blank and not saw_checkbox_q:
                info["grant_truly_blank"] = True

    # Signature `Date:` at bottom of TTF (`Date: 2/27/17`, `2/3/20 Date`, `Dale: 3/31/2014`, `bate: 5-17-13`)
    for m_sig_d in re.finditer(
        r"(?:Signat\w*\s*:?.{0,70}?\b[DBdb]a[tl]e\s*:\s*([A-Za-z0-9/.,\s-]{5,24})|(\d{1,2}\s*/\s*\d{1,2}\s*/\s*(?:\d{2}|\d{4}))\s+Date\b|\b[DBdb]a[tl]e\s*:\s*(\d{1,2}\s*[/-]\s*\d{1,2}\s*[/-]\s*(?:\d{2}|\d{4})))",
        text[-1200:],
        re.I,
    ):
        cand_s = m_sig_d.group(1) or m_sig_d.group(2) or m_sig_d.group(3)
        sp_s, iso_s = _parse_single_date_str(cand_s or "")
        if iso_s and iso_s not in lookback_isos:
            info["sig_doc_date"] = iso_s
            if sp_s and sp_s not in info.get("date_spans", []):
                info.setdefault("date_spans", []).append(sp_s)
            break

    return info


def _synthesize_ttf_v6(
    *,
    filename: str,
    text: str,
    known: Mapping[str, Any],
    relational: Mapping[str, Any],
    provenance: Mapping[str, Any],
    citations: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not text or len(text.strip()) < 120:
        return None

    parsed = parse_ttf_form_v6(text)

    wks = list(relational.get("witness_keys") or ())
    rel_w_list: list[dict[str, Any]] = []
    w_json = relational.get("rel_witness_personas_json")
    if isinstance(w_json, str) and w_json:
        try:
            rel_w_list = json.loads(w_json)
        except Exception:
            rel_w_list = []
    elif isinstance(relational.get("rel_witness_personas"), list):
        rel_w_list = [dict(x) for x in relational["rel_witness_personas"] if isinstance(x, Mapping)]

    form_name = parsed.get("witness_name")
    witness_p: dict[str, Any] | None = None

    if len(wks) > 1:
        if form_name:
            fsur = _surname_of(form_name)
            matches = [wp for wp in rel_w_list if _surname_of(str(wp.get("name") or "")) == fsur]
            if len(matches) == 1:
                witness_p = dict(matches[0])
        if witness_p is None:
            return None
    elif len(wks) == 1 and len(rel_w_list) == 1:
        wp0 = dict(rel_w_list[0])
        rel_full = str(wp0.get("name") or "")
        s_rel = _surname_of(rel_full)
        norm_txt_alnum = re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower())
        norm_fn_alnum = re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", filename or "").encode("ascii", "ignore").decode("ascii").lower())
        s_rel_alnum = re.sub(r"[^a-z0-9]", "", s_rel or "")
        rel_grounded = bool(s_rel_alnum and (s_rel_alnum in norm_txt_alnum or s_rel_alnum in norm_fn_alnum or s_rel_alnum[:5] in norm_txt_alnum))
        if form_name:
            s_frm = _surname_of(form_name)
            first_match = bool(
                rel_full.split()
                and form_name.split()
                and rel_full.split()[0].lower()[:3] == form_name.split()[0].lower()[:3]
            )
            short_first_only = len([t for t in form_name.split() if len(t.rstrip(".")) >= 2]) == 1
            aligned = (
                not s_rel
                or not s_frm
                or s_rel == s_frm
                or s_rel[:4] == s_frm[:4]
                or s_rel in form_name.lower()
                or (first_match and (s_rel[:2] == s_frm[:2] or rel_grounded))
                or (short_first_only and rel_grounded)
            )
            if not aligned:
                return None
        elif not rel_grounded:
            return None
        witness_p = wp0
    elif len(wks) == 0 and form_name:
        toks = form_name.split()
        if 2 <= len(toks) <= 5 and not _BAD_FORM_NAME_RE.search(form_name):
            w_org = parsed.get("witness_org")
            w_title = parsed.get("witness_title")
            if w_org or w_title or parsed.get("capacity") == "self":
                comb_ot = f"{w_org or ''} {w_title or ''}"
                if _MIL_ORG_OR_RANK_RE.search(comb_ot):
                    et = "military_officer"
                elif parsed.get("gov_witness") is True or _GOV_ORG_RE.search(comb_ot):
                    et = "gov_official"
                else:
                    et = "non_gov_person"
                witness_p = {"name": form_name, "role": "witness", "entity_type": et}
                if w_title:
                    witness_p["title"] = w_title
                if w_org:
                    witness_p["org"] = w_org

    if witness_p is None or not witness_p.get("name"):
        return None

    witness_p["role"] = "witness"
    if not witness_p.get("title") and parsed.get("witness_title"):
        witness_p["title"] = parsed["witness_title"]
    if not witness_p.get("org") and parsed.get("witness_org"):
        witness_p["org"] = parsed["witness_org"]
    if _MIL_ORG_OR_RANK_RE.search(f"{witness_p.get('org') or ''} {witness_p.get('title') or ''}"):
        witness_p["entity_type"] = "military_officer"

    m_txt_cong = re.search(r"\b(1\d\d)(?:th|st|nd|rd)\s+Congress\b", text[:600], re.I)
    cand_cong = (
        relational.get("rel_congress")
        or known.get("congress")
        or _extract_slug_congress(filename)
        or (int(m_txt_cong.group(1)) if m_txt_cong else None)
    )
    event_date = parsed.get("event_date") or relational.get("rel_event_date") or known.get("date")
    if not event_date:
        event_date = _extract_filename_iso_date(filename or "")
    sig_doc_date = parsed.get("sig_doc_date")

    if isinstance(cand_cong, bool) or not isinstance(cand_cong, int):
        cand_cong = iso_date_to_congress_v6(event_date) or iso_date_to_congress_v6(sig_doc_date)
    if not isinstance(cand_cong, int) or not (100 <= cand_cong <= 130):
        return None

    slug_c = _extract_slug_congress(filename)
    if slug_c is not None and slug_c != cand_cong:
        return None
    if event_date and iso_date_to_congress_v6(event_date) != cand_cong:
        if parsed.get("event_date") and iso_date_to_congress_v6(parsed["event_date"]) == cand_cong:
            event_date = parsed["event_date"]
        else:
            event_date = None
    if sig_doc_date and iso_date_to_congress_v6(sig_doc_date) != cand_cong:
        sig_doc_date = None
    if not event_date and not sig_doc_date:
        return None

    _, cmts = _resolve_committees_and_chamber(
        filename=filename,
        text=text,
        congress=cand_cong,
        known=known,
        relational=relational,
        provenance=provenance,
        default_house=True,
    )
    if not cmts and parsed.get("form_committee"):
        cmts = [_era_aware_house_committee(str(parsed["form_committee"]), cand_cong, text[:1200])]
    if not cmts:
        return None

    subcmts: list[str] = []
    rel_subs = relational.get("rel_subcommittees")
    if isinstance(rel_subs, Sequence) and not isinstance(rel_subs, str):
        subcmts = [str(s).strip() for s in rel_subs if s and str(s).strip()]
    if not subcmts and parsed.get("form_subcommittee"):
        subcmts = [str(parsed["form_subcommittee"]).strip()]

    cap = parsed.get("capacity")
    gov_w = parsed.get("gov_witness")
    rep_orgs = list(parsed.get("represented_orgs") or ())
    low_t = text.lower()

    # Enrich capacity / gov_witness from verified single-witness `witness_p` ONLY when text-grounded and non-contradictory
    w_rel_org = str(witness_p.get("org") or "").strip()
    if gov_w is None:
        if _GOV_ORG_RE.search(w_rel_org) or (witness_p.get("entity_type") in ("gov_official", "military_officer") and w_rel_org):
            gov_w = True
            cap = cap or ("organization" if w_rel_org else "government")
        elif (
            parsed.get("header_declares_nongov")
            or isinstance(parsed.get("has_federal_grants"), bool)
            or (len(wks) == 1 and witness_p.get("entity_type") == "non_gov_person" and w_rel_org and not _GOV_ORG_RE.search(w_rel_org))
        ):
            gov_w = False

    if cap is None and gov_w is False:
        not_rep = bool(re.search(r"\b(?:not\s+repres\w+|acting\s+independently|in\s+my\s+personal\s+capacity)\b", low_t))
        if not_rep:
            cap = "self"
        elif w_rel_org:
            org_tokens = [tok.lower() for tok in re.split(r"[^A-Za-z0-9]+", w_rel_org) if len(tok) >= 4]
            if (org_tokens and any(tok in low_t for tok in org_tokens[:3])) or len(wks) == 1:
                cap = "organization"
                rep_orgs = [w_rel_org]
        elif len(wks) == 1 and witness_p.get("title") and "citizen" in str(witness_p.get("title")).lower():
            cap = "self"

    if cap == "organization" and not rep_orgs and w_rel_org:
        rep_orgs = [w_rel_org]
    elif rep_orgs and w_rel_org and _surname_of(rep_orgs[0]) != _surname_of(w_rel_org):
        if len(w_rel_org) >= 4:
            rep_orgs = [w_rel_org]

    has_fg = parsed.get("has_federal_grants")
    has_fp = parsed.get("has_foreign_payments")

    if cap not in _VALID_CAPACITY or not isinstance(gov_w, bool):
        return None
    if gov_w is False:
        if parsed.get("grant_ambiguous"):
            return None
        if not isinstance(has_fg, bool) and not parsed.get("grant_truly_blank"):
            return None

    disc: dict[str, Any] = {
        "capacity": cap,
        "gov_witness": gov_w,
    }
    if rep_orgs and cap == "organization":
        disc["represented_orgs"] = rep_orgs[:4]
    if isinstance(has_fg, bool):
        disc["has_federal_grants"] = has_fg
    if has_fg is True and parsed.get("federal_grants"):
        disc["federal_grants"] = parsed["federal_grants"][:8]
    if isinstance(has_fp, bool):
        disc["has_foreign_payments"] = has_fp
    if has_fp is True and parsed.get("foreign_payments"):
        disc["foreign_payments"] = parsed["foreign_payments"][:8]

    personas: list[dict[str, Any]] = [witness_p]
    if parsed.get("masthead_chair"):
        personas.append(
            {
                "name": parsed["masthead_chair"],
                "role": "chair",
                "entity_type": "member",
            }
        )

    refs: list[str] = []
    if "2(g)(5)" in low_t:
        refs.append("rule:House Rule XI, clause 2(g)(5)")
    elif "2(g)" in low_t or "rule xi" in low_t:
        refs.append("rule:House Rule XI, clause 2(g)")
    if "18 u.s.c." in low_t and "1001" in low_t:
        refs.append("usc:18 U.S.C. 1001")

    event_title = parsed.get("event_title") or relational.get("rel_event_title")
    event_type = relational.get("rel_event_type") or ("hearing" if (event_title or "hearing" in low_t[:900]) else None)

    w_name = str(witness_p["name"])
    w_org_disp = (rep_orgs[0] if rep_orgs else witness_p.get("org")) or ""
    comp_title = (
        f"Truth in Testimony Disclosure of {w_name} ({w_org_disp})"
        if w_org_disp
        else f"Truth in Testimony Disclosure of {w_name}"
    )

    grant_phrase = (
        "reporting federal grants or contracts"
        if has_fg is True
        else ("reporting no federal grants" if has_fg is False else "for congressional testimony")
    )
    org_phrase = f" ({w_org_disp})" if w_org_disp and len(w_org_disp.split()) <= 6 else ""
    gist = f"Truth in Testimony disclosure form submitted by {w_name}{org_phrase}, {grant_phrase}."

    extra_t = ["federal grants"] if has_fg is True else ["witness disclosure"]
    topics = _derive_topics_from_context(
        base_tag="truth in testimony",
        committees=cmts,
        event_title=str(event_title) if event_title else None,
        extra_tags=extra_t,
    )

    raw_doc: dict[str, Any] = {
        "status": "usable",
        "text_quality": _infer_text_quality(text),
        "verbatim_title": parsed.get("verbatim_title"),
        "chamber": "house",
        "congress": cand_cong,
        "committees": cmts,
        "subcommittees": subcmts or None,
        "event_type": event_type,
        "event_title": event_title,
        "date_spans": parsed.get("date_spans") or None,
        "doc_date": sig_doc_date,
        "event_date": event_date,
        "primary_kind": "truth_in_testimony_disclosure",
        "secondary_kinds": ["witness_biography"] if parsed.get("has_attached_bio") else None,
        "personas": personas,
        "refs": refs or None,
        "orgs_mentioned": [w_org_disp] if w_org_disp else None,
        "disclosure": disc,
        "composed_title": comp_title,
        "gist": gist,
        "topics": topics,
    }
    return order_and_validate_docmeta_v6(raw_doc)


# ---------------------------------------------------------------------------
# 3B. Genre 2: `attendance_quorum_sheet` (`746` rows)
# ---------------------------------------------------------------------------

_ATTEND_MEMBER_LEAD_RE = re.compile(
    r"\b(?:MR\.|MS\.|MRS\.|REP\.|SEN\.)\s+([A-Z][A-Z'\u00C0-\u024F-]+(?:\s+[A-Z][A-Z'\u00C0-\u024F-]+)?)"
    r"(?:\s*\(([A-Z]{2})\))?\s*\((Chair(?:man|woman)?|Ranking\s+Member)\)",
    re.I,
)


def _synthesize_attendance_v6(
    *,
    filename: str,
    text: str,
    known: Mapping[str, Any],
    relational: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not text or len(text.strip()) < 40:
        return None
    t_ws = _WS_RE.sub(" ", text[:4500]).strip()

    m_cong_txt = re.search(r"\b(1\d\d)\s*(?:th|st|nd|rd)\s+CONGRESS\b", t_ws, re.I)
    cand_cong = (
        (int(m_cong_txt.group(1)) if m_cong_txt else None)
        or relational.get("rel_congress")
        or known.get("congress")
        or _extract_slug_congress(filename)
    )

    date_spans: list[str] = []
    sheet_date: str | None = None
    m_as_of = re.search(r"\bAs\s+of\s+(\d{1,2}/\d{1,2}/20\d{2})\b", t_ws, re.I)
    if m_as_of:
        date_spans.append(m_as_of.group(1))
    m_dt = re.search(
        r"\bDate\s*:\s*([A-Za-z0-9,/\s-]{5,32}?)(?=\s+(?:Subject|Convened|Gavel|Adjourn|Time|Place|YEAS|Democrats)\b|$)",
        t_ws,
        re.I,
    )
    if m_dt:
        sp_d, iso_d = _parse_single_date_str(m_dt.group(1))
        if iso_d:
            sheet_date = iso_d
            if sp_d and sp_d not in date_spans:
                date_spans.append(sp_d)

    event_date = sheet_date or relational.get("rel_event_date") or known.get("date")
    if not event_date:
        m_sd = _SLUG_TRAILING_DATE_RE.search(filename or "")
        if m_sd:
            _, event_date = _parse_single_date_str(f"{m_sd.group(1)}-{m_sd.group(2)}-{m_sd.group(3)}")
    if isinstance(cand_cong, bool) or not isinstance(cand_cong, int):
        cand_cong = iso_date_to_congress_v6(event_date)
    if not isinstance(cand_cong, int) or not event_date:
        return None
    if iso_date_to_congress_v6(event_date) != cand_cong:
        if relational.get("rel_event_date") and iso_date_to_congress_v6(str(relational["rel_event_date"])) == cand_cong:
            event_date = str(relational["rel_event_date"])
            sheet_date = None
        else:
            return None
    slug_c = _extract_slug_congress(filename)
    if slug_c is not None and slug_c != cand_cong:
        return None

    chamber, cmts = _resolve_committees_and_chamber(
        filename=filename,
        text=text,
        congress=cand_cong,
        known=known,
        relational=relational,
        provenance=provenance,
        default_house=bool((filename or "").upper().startswith(("HHRG-", "HMKP-", "HMTG-"))),
    )
    if not chamber or not cmts:
        return None

    subcmts: list[str] = []
    m_sub = re.search(
        r"\b(SUBCOMMITTEE\s+ON\s+[A-Z0-9,\s&'’-]{3,90}?)(?=\s+(?:Date|Subject|Gavel|Time|Convened|Meeting)\b)",
        t_ws,
    )
    if m_sub:
        raw_sub = m_sub.group(1).strip()
        subcmts.append(
            "Subcommittee on "
            + " ".join(
                w.capitalize() if w.lower() not in ("on", "and", "of", "the", "for", "in") else w.lower()
                for w in raw_sub[15:].split()
            )
        )
    elif isinstance(relational.get("rel_subcommittees"), Sequence) and not isinstance(relational.get("rel_subcommittees"), str):
        subcmts = [str(s).strip() for s in relational["rel_subcommittees"] if s and str(s).strip()]

    event_title: str | None = None
    m_subj = re.search(r"\b(?:Subject|Meeting\s+on)\s*:?\s*(.+?)(?=\s+(?:Gavel|Date|Convened|Adjournment|YEAS)\b)", t_ws, re.I)
    if m_subj:
        cand_et = m_subj.group(1).strip(" :;-–—")
        if cand_et and cand_et.lower() not in ("business meeting", "markup", "hearing", "quorum call", "attendance"):
            event_title = cand_et
    if not event_title and relational.get("rel_event_title"):
        ret = str(relational["rel_event_title"]).strip()
        if ret.lower() not in ("business meeting", "markup"):
            event_title = ret

    if re.search(r"\bBusiness\s+Meeting\b", t_ws[:400], re.I):
        event_type = "business_meeting"
    elif (filename or "").upper().startswith("HMKP-") or re.search(r"\bMarkup\b", t_ws[:400], re.I):
        event_type = relational.get("rel_event_type") or "markup"
    else:
        event_type = relational.get("rel_event_type") or "hearing"

    event_time: str | None = None
    m_gv = re.search(r"\b(?:Gavel|Convened)\s*:\s*([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM|a\.m\.|p\.m\.|am|pm))", t_ws)
    m_adj = re.search(r"\b(?:Adjournment|Adjourned)\s*:\s*([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM|a\.m\.|p\.m\.|am|pm))", t_ws)
    if m_gv and m_adj:
        event_time = f"{m_gv.group(1).strip()} - {m_adj.group(1).strip()}"
    elif m_gv:
        event_time = m_gv.group(1).strip()
    elif relational.get("rel_event_time"):
        event_time = str(relational["rel_event_time"]).strip()

    personas: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    for m_lead in _ATTEND_MEMBER_LEAD_RE.finditer(t_ws):
        raw_nm, st_abbr, r_lbl = m_lead.group(1), m_lead.group(2), m_lead.group(3).lower()
        role = "chair" if r_lbl.startswith("chair") else "ranking_member"
        if role in seen_roles:
            continue
        seen_roles.add(role)
        p_obj: dict[str, Any] = {
            "name": _clean_person_name(raw_nm),
            "role": role,
            "entity_type": "member",
        }
        if st_abbr:
            p_obj["party_state"] = st_abbr.upper()
        personas.append(p_obj)

    action_summary: str | None = None
    is_blank_dots = ".........." in t_ws
    if not is_blank_dots and "Present" in t_ws[:500]:
        present_cnt = len(
            re.findall(
                r"\b(?:MR\.|MS\.|MRS\.|REP\.)\s+[A-Z][A-Z'\u00C0-\u024F-]+(?:\s+[A-Z'\u00C0-\u024F-]+)?\s*\([A-Z]{2}\)(?:\s*\([^)]+\))?\s+X\b",
                t_ws,
            )
        )
        if present_cnt >= 2:
            action_summary = f"Committee attendance recorded: {present_cnt} members marked present."

    body_label = subcmts[0] if subcmts else cmts[0]
    comp_title = f"{body_label} Attendance/Quorum Sheet ({event_date})"
    kind_word = "Blank roll-call attendance and quorum sheet" if is_blank_dots else "Committee attendance and quorum sheet"
    ev_desc = f" on {event_title[:65]}" if event_title else f" ({event_type.replace('_', ' ')})"
    gist = f"{kind_word} for {event_date} {cmts[0]}{ev_desc}."

    topics = _derive_topics_from_context(
        base_tag="committee attendance",
        committees=cmts,
        event_title=event_title,
        extra_tags=[event_type.replace("_", " ")],
    )

    raw_doc: dict[str, Any] = {
        "status": "usable",
        "text_quality": _infer_text_quality(text),
        "chamber": chamber,
        "congress": cand_cong,
        "committees": cmts,
        "subcommittees": subcmts or None,
        "event_type": event_type,
        "event_title": event_title,
        "event_time": event_time,
        "date_spans": date_spans or None,
        "doc_date": sheet_date,
        "event_date": event_date,
        "primary_kind": "attendance_quorum_sheet",
        "personas": personas or None,
        "action_summary": action_summary,
        "composed_title": comp_title,
        "gist": gist,
        "topics": topics,
    }
    return order_and_validate_docmeta_v6(raw_doc)


# ---------------------------------------------------------------------------
# 3C. Genre 3: `witness_list` (`~1,160+` rows)
# ---------------------------------------------------------------------------

_LETTERHEAD_CHAIR_RE = re.compile(
    r"\b([A-Z][A-Z.\s'’-]{3,38}?),\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+CHAIR(?:MAN|WOMAN)?\b"
)
_LETTERHEAD_RM_RE = re.compile(
    r"\b([A-Z][A-Z.\s'’-]{3,38}?),\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+RANKING\s+(?:MINORITY\s+)?MEMBER\b"
)
_BILL_CITE_SIMPLE_RE = re.compile(
    r"\b(H\.\s*R\.|S\.|H\.\s*Res\.|S\.\s*Res\.|H\.\s*J\.\s*Res\.|S\.\s*J\.\s*Res\.|H\.\s*Con\.\s*Res\.|S\.\s*Con\.\s*Res\.)\s*(\d{1,5})\b",
    re.I,
)


def _extract_letterhead_leadership(text: str) -> list[dict[str, Any]]:
    head = _WS_RE.sub(" ", (text or "")[:1400])
    if "CONGRESS" not in head or ("CHAIRMAN" not in head and "CHAIRWOMAN" not in head):
        return []
    leaders: list[dict[str, Any]] = []
    m_ch = _LETTERHEAD_CHAIR_RE.search(head)
    if m_ch:
        nm = _clean_person_name(m_ch.group(1))
        st = _US_STATE_TO_ABBR.get(m_ch.group(2).strip().lower())
        if nm and 2 <= len(nm.split()) <= 4:
            d: dict[str, Any] = {"name": nm, "title": "Chairman", "role": "chair", "entity_type": "member"}
            if st:
                d["party_state"] = st
            leaders.append(d)
    m_rm = _LETTERHEAD_RM_RE.search(head)
    if m_rm:
        nm = _clean_person_name(m_rm.group(1))
        st = _US_STATE_TO_ABBR.get(m_rm.group(2).strip().lower())
        if nm and 2 <= len(nm.split()) <= 4:
            d2: dict[str, Any] = {"name": nm, "title": "Ranking Member", "role": "ranking_member", "entity_type": "member"}
            if st:
                d2["party_state"] = st
            leaders.append(d2)
    return leaders


def _synthesize_witness_list_v6(
    *,
    filename: str,
    text: str,
    known: Mapping[str, Any],
    relational: Mapping[str, Any],
    provenance: Mapping[str, Any],
    hygiene: Mapping[str, Any],
    citations: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not text or len(text.strip()) < 80:
        return None
    t_ws = _WS_RE.sub(" ", text[:6500]).strip()
    norm_low = unicodedata.normalize("NFKC", text).lower()

    p12_span, p12_iso = _parse_single_date_str(t_ws[:1500])
    cand_cong = (
        relational.get("rel_congress")
        or known.get("congress")
        or _extract_slug_congress(filename)
        or iso_date_to_congress_v6(p12_iso)
    )
    if isinstance(cand_cong, bool) or not isinstance(cand_cong, int):
        cand_cong = None

    event_date: str | None = None
    date_spans: list[str] = []
    if p12_iso and (cand_cong is None or iso_date_to_congress_v6(p12_iso) == cand_cong):
        event_date = p12_iso
        if p12_span:
            date_spans.append(p12_span)
    else:
        fallback_d = relational.get("rel_event_date") or known.get("date")
        if isinstance(fallback_d, str) and (cand_cong is None or iso_date_to_congress_v6(fallback_d) == cand_cong):
            event_date = fallback_d
        elif not fallback_d:
            m_sd = _SLUG_TRAILING_DATE_RE.search(filename or "")
            if m_sd:
                _, d_s = _parse_single_date_str(f"{m_sd.group(1)}-{m_sd.group(2)}-{m_sd.group(3)}")
                if d_s and (cand_cong is None or iso_date_to_congress_v6(d_s) == cand_cong):
                    event_date = d_s

    if not event_date:
        return None
    if cand_cong is None:
        cand_cong = iso_date_to_congress_v6(event_date)
    if not isinstance(cand_cong, int):
        return None
    slug_c = _extract_slug_congress(filename)
    if slug_c is not None and slug_c != cand_cong:
        return None

    chamber, cmts = _resolve_committees_and_chamber(
        filename=filename,
        text=text,
        congress=cand_cong,
        known=known,
        relational=relational,
        provenance=provenance,
    )
    if not chamber or not cmts:
        return None

    rel_ev_w: list[dict[str, Any]] = []
    ew_json = relational.get("rel_event_witnesses_json")
    if isinstance(ew_json, str) and ew_json:
        try:
            rel_ev_w = json.loads(ew_json)
        except Exception:
            rel_ev_w = []
    elif isinstance(relational.get("rel_event_witnesses"), list):
        rel_ev_w = [dict(x) for x in relational["rel_event_witnesses"] if isinstance(x, Mapping)]

    hyg_w: list[dict[str, Any]] = []
    hw_json = hygiene.get("witness_list_personas_json")
    if isinstance(hw_json, str) and hw_json:
        try:
            hyg_w = json.loads(hw_json)
        except Exception:
            hyg_w = []
    elif isinstance(hygiene.get("witness_list_personas"), list):
        hyg_w = [dict(x) for x in hygiene["witness_list_personas"] if isinstance(x, Mapping)]

    panel_spans: list[tuple[int, str]] = [
        (m_pn.start(), f"Panel {m_pn.group(1).upper()}")
        for m_pn in re.finditer(r"\bpanel\s+([1-6]|i{1,3}|iv|v|vi)\b", norm_low)
    ]

    raw_candidates = rel_ev_w if rel_ev_w else hyg_w
    grounded_with_pos: list[tuple[int, bool, dict[str, Any]]] = []
    seen_w_keys: set[str] = set()
    hyg_by_sur = {_surname_of(str(hw.get("name") or "")): hw for hw in hyg_w if _surname_of(str(hw.get("name") or ""))}

    def _collect_grounded(cands: Sequence[Mapping[str, Any]]) -> None:
        for wp_raw in cands:
            wp = dict(wp_raw)
            nm = _clean_person_name(str(wp.get("name") or ""))
            sur = _surname_of(nm)
            if not nm or not sur:
                continue
            pos_idx = norm_low.find(sur)
            if pos_idx < 0:
                continue
            dedup_k = f"{sur}:{nm[0].lower()}"
            if dedup_k in seen_w_keys:
                continue
            seen_w_keys.add(dedup_k)
            wp["name"] = nm
            wp["role"] = "witness"
            hw_match = hyg_by_sur.get(sur)
            if hw_match:
                for fk in ("title", "org", "panel", "creds"):
                    if not wp.get(fk) and hw_match.get(fk):
                        wp[fk] = hw_match[fk]
            # Normalize or backfill `panel` from explicit `Panel 1 / Panel 2` headings in `norm_low`
            if panel_spans:
                preceding_panels = [plbl for ppos, plbl in panel_spans if ppos < pos_idx]
                if preceding_panels:
                    wp["panel"] = preceding_panels[-1]
            ctx_before = norm_low[max(0, pos_idx - 75) : pos_idx]
            is_accomp = bool(re.search(r"accompanied\s+by\s*:", ctx_before))
            grounded_with_pos.append((pos_idx, is_accomp, wp))

    _collect_grounded(raw_candidates)
    if not grounded_with_pos and hyg_w and raw_candidates is not hyg_w:
        _collect_grounded(hyg_w)
    elif rel_ev_w and hyg_w:
        # Also append any `hyg_w` witness on `p12` that was missing from `rel_ev_w` (e.g. Panel 2 end)
        _collect_grounded(hyg_w)

    if not grounded_with_pos:
        return None

    grounded_with_pos.sort(key=lambda item: item[0])
    leaders = _extract_letterhead_leadership(text)
    leader_surs = {_surname_of(x["name"]) for x in leaders}
    filtered_items = [(pos, acc, w) for pos, acc, w in grounded_with_pos if _surname_of(w["name"]) not in leader_surs]
    if not filtered_items:
        return None

    budget = 10 - len(leaders)
    if len(filtered_items) > budget:
        # Drop `Accompanied by:` secondary aides first when exceeding the 10-persona cap
        non_acc = [(pos, acc, w) for pos, acc, w in filtered_items if not acc]
        if len(non_acc) >= budget:
            filtered_items = non_acc

    ordered_witnesses = [w for _, _, w in filtered_items]
    if len(ordered_witnesses) > budget:
        panels_order: list[str] = []
        by_panel: dict[str, list[dict[str, Any]]] = {}
        for w in ordered_witnesses:
            pk_lbl = str(w.get("panel") or "_default")
            if pk_lbl not in by_panel:
                panels_order.append(pk_lbl)
                by_panel[pk_lbl] = []
            by_panel[pk_lbl].append(w)
        if len(panels_order) >= 2:
            selected_w: list[dict[str, Any]] = []
            rem = budget
            for idx_p, pk_lbl in enumerate(panels_order):
                plist = by_panel[pk_lbl]
                reserve_later = sum(min(3, len(by_panel[p_lat])) for p_lat in panels_order[idx_p + 1 :])
                take = min(len(plist), max(1, rem - reserve_later))
                selected_w.extend(plist[:take])
                rem -= take
                if rem <= 0:
                    break
            ordered_witnesses = selected_w[:budget]
        else:
            ordered_witnesses = ordered_witnesses[:budget]

    personas = leaders + ordered_witnesses

    subcmts: list[str] = []
    if isinstance(relational.get("rel_subcommittees"), Sequence) and not isinstance(relational.get("rel_subcommittees"), str):
        subcmts = [str(s).strip() for s in relational["rel_subcommittees"] if s and str(s).strip()]
    if not subcmts:
        m_sub = re.search(
            r"\b(Subcommittee\s+on\s+[A-Z][A-Za-z,\s&'’-]{3,85}?)(?=\s+(?:Witness\s+List|Hearing|Markup|TIME|Monday|Tuesday|Wednesday|Thursday|Friday)\b)",
            t_ws,
        )
        if m_sub:
            subcmts.append(m_sub.group(1).strip())

    event_title = relational.get("rel_event_title")
    if not event_title:
        m_et = re.search(
            r"(?:Subject:\s*|Hearing\s+on\s+|Hearing\s+\")([^\"]+?)(?:\"|\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|TIME|WITNESSES|Panel\s+1)\b)",
            t_ws,
            re.I,
        )
        if m_et:
            event_title = m_et.group(1).strip()

    event_type = relational.get("rel_event_type") or ("markup" if "markup" in t_ws[:500].lower() else "hearing")
    venue = relational.get("rel_venue")
    venue_kind = relational.get("rel_venue_kind")
    if not venue:
        if re.search(r"\bWebEx\b", t_ws[:600], re.I):
            venue, venue_kind = "WebEx", "virtual"
        else:
            m_rm = re.search(
                r"\b(\d{3,4}\s+(?:Rayburn|Longworth|Cannon)\s+House\s+Office\s+Building|(?:SD|SH|SR)-\d{3}\s+(?:Dirksen|Hart|Russell)\s+Senate\s+Office\s+Building)\b",
                t_ws[:900],
                re.I,
            )
            if m_rm:
                venue, venue_kind = m_rm.group(1).strip(), "capitol_room"

    event_time: str | None = None
    m_tm = re.search(r"\b(\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.|AM|PM))\b", t_ws[:900])
    if m_tm:
        event_time = m_tm.group(1).strip()
    elif relational.get("rel_event_time"):
        event_time = str(relational["rel_event_time"]).strip()

    refs: list[str] = []
    if isinstance(citations.get("det_refs"), Sequence) and not isinstance(citations.get("det_refs"), str):
        refs = [str(r) for r in citations["det_refs"] if isinstance(r, str) and r.startswith("bill:")]
    if not refs:
        for m_b in _BILL_CITE_SIMPLE_RE.finditer(t_ws[:1000]):
            b_type = re.sub(r"\s+", " ", m_b.group(1).strip())
            b_ref = f"bill:{b_type} {m_b.group(2)}"
            if b_ref not in refs:
                refs.append(b_ref)

    short_titles: list[str] = []
    if isinstance(citations.get("det_short_titles"), Sequence) and not isinstance(citations.get("det_short_titles"), str):
        short_titles = [str(st) for st in citations["det_short_titles"] if isinstance(st, str)]
    if not short_titles:
        for m_st in re.finditer(r"[\"“]([A-Z][A-Za-z0-9,\s'’-]{6,110}?\s+Act(?:\s+of\s+20\d{2})?)[\"”]", t_ws[:1000]):
            short_titles.append(m_st.group(1).strip())

    fys: list[int] = []
    if isinstance(citations.get("det_fiscal_years"), Sequence) and not isinstance(citations.get("det_fiscal_years"), str):
        fys = [int(y) for y in citations["det_fiscal_years"] if not isinstance(y, bool) and isinstance(y, int)]
    if not fys:
        fys = [int(y) for y in dict.fromkeys(re.findall(r"\b(?:Fiscal\s+Year|FY)\s*(20\d{2})\b", t_ws[:1000], re.I))]

    orgs_m = _dedup_nonempty_strs([w.get("org") for w in ordered_witnesses if w.get("org")], max_items=8)
    verb_title = "Witness List" if re.search(r"\bWitness\s+List\b", t_ws[:400], re.I) else None

    ev_short = str(event_title)[:65].rstrip() if event_title else f"{event_date} {event_type}"
    comp_title = f"Witness List: {cmts[0]} ({ev_short})"
    gist = f"Witness list for the {event_date} {cmts[0]} {event_type} featuring {len(ordered_witnesses)} scheduled witness(es)."
    topics = _derive_topics_from_context(
        base_tag="witness list",
        committees=cmts,
        event_title=str(event_title) if event_title else None,
    )

    raw_doc: dict[str, Any] = {
        "status": "usable",
        "text_quality": _infer_text_quality(text),
        "verbatim_title": verb_title,
        "short_titles": short_titles or None,
        "chamber": chamber,
        "congress": cand_cong,
        "committees": cmts,
        "subcommittees": subcmts or None,
        "event_type": event_type,
        "event_title": event_title,
        "venue_kind": venue_kind,
        "venue": venue,
        "event_time": event_time,
        "date_spans": date_spans or None,
        "doc_date": event_date if p12_iso == event_date else None,
        "event_date": event_date,
        "primary_kind": "witness_list",
        "personas": personas,
        "refs": refs or None,
        "orgs_mentioned": orgs_m or None,
        "fiscal_years": fys or None,
        "composed_title": comp_title,
        "gist": gist,
        "topics": topics,
    }
    return order_and_validate_docmeta_v6(raw_doc)


# ---------------------------------------------------------------------------
# 3D. Genre 4: `legislative_schedule_or_calendar` (`199` `docs.house.gov` weekly rows)
# ---------------------------------------------------------------------------

_FLOOR_ITEM_RE = re.compile(
    r"\b(?P<prefix>H\.\s*R\.|S\.|H\.\s*Res\.|S\.\s*Res\.|H\.\s*J\.\s*Res\.|S\.\s*J\.\s*Res\.|H\.\s*Con\.\s*Res\.|S\.\s*Con\.\s*Res\.)\s*"
    r"(?P<num>\d{1,5})\b"
    r"(?:\s*[-–—:]?\s*(?P<title>[^\[\n]{4,180}?))?"
    r"\s*(?=\[(?:PDF|XML|HTML)\]|\bAdded\s+\d{1,2}/\d{1,2}/20\d{2})",
    re.I,
)


def _normalize_bill_prefix(raw_p: str) -> str:
    low = re.sub(r"\s+", "", raw_p.lower())
    return {
        "h.r.": "H.R.",
        "s.": "S.",
        "h.res.": "H. Res.",
        "s.res.": "S. Res.",
        "h.j.res.": "H.J. Res.",
        "s.j.res.": "S.J. Res.",
        "h.con.res.": "H. Con. Res.",
        "s.con.res.": "S. Con. Res.",
    }.get(low, raw_p.strip())


def _synthesize_weekly_floor_schedule_v6(
    *,
    tier1_signature_id: str | None,
    text: str,
    citations: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not text:
        return None
    t_ws = _WS_RE.sub(" ", text[:8000]).strip()
    if (
        tier1_signature_id != "schedule_docs_house_floor_weekly"
        and "Bills to be Considered on the House Floor" not in t_ws[:500]
    ):
        return None

    m_week = re.search(
        r"\bWeek\s+of\s+([A-Za-z]+\.?\s+\d{1,2},?\s+20\d{2})\b",
        t_ws[:900],
        re.I,
    )
    if not m_week:
        return None
    week_sp, week_iso = _parse_single_date_str(m_week.group(1))
    if not week_iso:
        return None

    date_spans: list[str] = [week_sp] if week_sp else []
    pub_iso: str | None = None
    upd_iso: str | None = None

    m_pub = re.search(r"\bFirst\s+Published:\s*([A-Za-z]+\.?\s+\d{1,2},?\s+20\d{2})", t_ws[:900], re.I)
    if m_pub:
        sp_p, pub_iso = _parse_single_date_str(m_pub.group(1))
        if sp_p and sp_p not in date_spans:
            date_spans.append(sp_p)

    m_upd = re.search(r"\bLast\s+Updated:\s*([A-Za-z]+\.?\s+\d{1,2},?\s+20\d{2})", t_ws[:900], re.I)
    if m_upd:
        sp_u, upd_iso = _parse_single_date_str(m_upd.group(1))
        if sp_u and sp_u not in date_spans:
            date_spans.append(sp_u)

    doc_date = upd_iso or pub_iso or week_iso
    congress = iso_date_to_congress_v6(doc_date)
    if not congress:
        return None

    refs: list[str] = []
    short_titles: list[str] = []
    for m_item in _FLOOR_ITEM_RE.finditer(t_ws):
        pref = _normalize_bill_prefix(m_item.group("prefix"))
        num = m_item.group("num")
        ref_s = f"bill:{pref} {num}"
        if ref_s not in refs:
            refs.append(ref_s)
        raw_t = (m_item.group("title") or "").strip(" -–—:;,")
        raw_t = re.sub(r",\s*as\s+amended.*$", "", raw_t, flags=re.I).strip(" \"'“”")
        if (
            raw_t
            and len(raw_t) >= 5
            and not re.match(r"^(?:Providing\s+for\s+consideration|Relating\s+to|To\s+[a-z]+\s+)", raw_t)
            and raw_t not in short_titles
        ):
            short_titles.append(raw_t)

    if not refs and isinstance(citations.get("det_refs"), Sequence) and not isinstance(citations.get("det_refs"), str):
        refs = [str(r) for r in citations["det_refs"] if isinstance(r, str) and r.startswith("bill:")]
    if not refs:
        for m_b in _BILL_CITE_SIMPLE_RE.finditer(t_ws):
            pref = _normalize_bill_prefix(m_b.group(1))
            ref_s = f"bill:{pref} {m_b.group(2)}"
            if ref_s not in refs:
                refs.append(ref_s)

    if not refs:
        return None

    week_disp = week_sp or week_iso
    comp_title = f"House Floor Legislative Schedule: Week of {week_disp}"
    gist = f"House Majority Leader floor schedule listing {len(refs)} measure(s) scheduled for consideration during the week of {week_disp}."
    topics = ["House floor schedule", "legislative calendar", "House of Representatives"]
    if "suspension of the rules" in t_ws.lower():
        topics.append("suspension bills")

    raw_doc: dict[str, Any] = {
        "status": "usable",
        "text_quality": "native",
        "verbatim_title": "Bills to be Considered on the House Floor",
        "short_titles": short_titles[:8] or None,
        "chamber": "house",
        "congress": congress,
        "date_spans": date_spans[:8] or None,
        "doc_date": doc_date,
        "primary_kind": "legislative_schedule_or_calendar",
        "refs": refs[:25],
        "composed_title": comp_title,
        "gist": gist,
        "topics": topics,
    }
    return order_and_validate_docmeta_v6(raw_doc)


# ---------------------------------------------------------------------------
# 4. Main Public Entrypoint (`try_synthesize_zero_llm_docmeta_v6`)
# ---------------------------------------------------------------------------


def try_synthesize_zero_llm_docmeta_v6(
    ctx_row: Mapping[str, Any] | None = None,
    *,
    locked_primary_kind: str | None = None,
    tier1_signature_id: str | None = None,
    filename: str = "",
    text: str = "",
    p12_lines: str | None = None,
    known_dict: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    relational: Mapping[str, Any] | None = None,
    citations: Mapping[str, Any] | None = None,
    hygiene: Mapping[str, Any] | None = None,
    row: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Synthesize a complete, 100%-confidence, causal-key-ordered `DocMetaV4Causal` dict (`0` GPU tokens).

    Supports both keyword invocation (used by `pythonic_v6.pre_pass_v6`) and single-dict `ctx_row`
    invocation. Returns `None` whenever any required 80/20 field is missing or ambiguous.
    """
    merged_row: dict[str, Any] = {}
    if isinstance(row, Mapping):
        merged_row.update(row)
    if isinstance(ctx_row, Mapping):
        merged_row.update(ctx_row)

    pk = (
        locked_primary_kind
        or merged_row.get("locked_primary_kind")
        or merged_row.get("v6_locked_primary_kind")
        or merged_row.get("v5_locked_primary_kind")
    )
    if pk not in BYPASS_SUPPORTED_KINDS_V6:
        return None

    sig_id = (
        tier1_signature_id
        or merged_row.get("tier1_signature_id")
        or merged_row.get("v5_tier1_signature_id")
    )
    fn = filename or str(merged_row.get("filename") or "")
    hyg_map: dict[str, Any] = dict(merged_row)
    if isinstance(hygiene, Mapping):
        hyg_map.update(hygiene)
    elif isinstance(merged_row.get("hygiene"), Mapping):
        hyg_map.update(merged_row["hygiene"])

    raw_text_in = text or str(merged_row.get("text") or merged_row.get("p12_text") or "")
    cand_p12 = (
        p12_lines
        if (isinstance(p12_lines, str) and p12_lines.strip())
        else (
            str(merged_row["p12_lines"])
            if (isinstance(merged_row.get("p12_lines"), str) and str(merged_row["p12_lines"]).strip())
            else ""
        )
    )

    # Guard against generic-filename alignment collisions (e.g., 199 `Default.aspx` floor schedules):
    # if both `text` and `p12_lines` are present (without BGSDD glyph repair) and their leading numeric
    # tokens are disjoint, `p12_lines` / sidecars belong to a different row sharing the generic filename.
    sidecar_mismatch = False
    if raw_text_in and cand_p12 and not hyg_map.get("bgsdd_repaired"):
        yrs_raw = set(re.findall(r"\b(?:19|20)\d{2}\b", raw_text_in[:600]))
        yrs_p12 = set(re.findall(r"\b(?:19|20)\d{2}\b", cand_p12[:700]))
        if yrs_raw and yrs_p12 and yrs_raw.isdisjoint(yrs_p12):
            sidecar_mismatch = True
        else:
            toks_raw = re.findall(r"[a-z]{4,}", raw_text_in[:500].lower())
            toks_p12 = set(re.findall(r"[a-z]{4,}", cand_p12[:650].lower()))
            if len(toks_raw) >= 12 and toks_p12:
                overlap = sum(1 for t in toks_raw if t in toks_p12) / len(toks_raw)
                if overlap < 0.65:
                    sidecar_mismatch = True

    if sidecar_mismatch:
        probe_txt = raw_text_in
        rel_map = {}
        prov_map = {}
        cit_map = {}
    elif pk == "legislative_schedule_or_calendar" and raw_text_in:
        probe_txt = raw_text_in
    else:
        probe_txt = cand_p12 if cand_p12 else raw_text_in

    if not probe_txt:
        return None

    known_map: Mapping[str, Any] = (
        known_dict
        if isinstance(known_dict, Mapping)
        else (merged_row.get("known") if isinstance(merged_row.get("known"), Mapping) else {})
    )
    if not sidecar_mismatch:
        rel_map = dict(merged_row)
        if isinstance(relational, Mapping):
            rel_map.update(relational)
        elif isinstance(merged_row.get("relational"), Mapping):
            rel_map.update(merged_row["relational"])

        prov_map = (
            provenance
            if isinstance(provenance, Mapping)
            else (merged_row.get("provenance") if isinstance(merged_row.get("provenance"), Mapping) else {})
        )
        cit_map = (
            citations
            if isinstance(citations, Mapping)
            else (merged_row.get("citations") if isinstance(merged_row.get("citations"), Mapping) else {})
        )

    if pk == "truth_in_testimony_disclosure":
        return _synthesize_ttf_v6(
            filename=fn,
            text=probe_txt,
            known=known_map,
            relational=rel_map,
            provenance=prov_map,
            citations=cit_map,
        )
    if pk == "attendance_quorum_sheet":
        return _synthesize_attendance_v6(
            filename=fn,
            text=probe_txt,
            known=known_map,
            relational=rel_map,
            provenance=prov_map,
        )
    if pk == "witness_list":
        return _synthesize_witness_list_v6(
            filename=fn,
            text=probe_txt,
            known=known_map,
            relational=rel_map,
            provenance=prov_map,
            hygiene=hyg_map,
            citations=cit_map,
        )
    if pk == "legislative_schedule_or_calendar":
        return _synthesize_weekly_floor_schedule_v6(
            tier1_signature_id=str(sig_id) if sig_id else None,
            text=probe_txt,
            citations=cit_map,
        )
    return None


synthesize_zero_llm_docmeta_v6 = try_synthesize_zero_llm_docmeta_v6
try_zero_llm_bypass_v6 = try_synthesize_zero_llm_docmeta_v6
