#!/usr/bin/env python3
"""DocMetaV4Causal prompt, canonicalizer, and validator."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DOCMETA_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = DOCMETA_DIR / "docmeta_v4_causal.schema.json"
DOCMETA_V4_SCHEMA_PATH = SCHEMA_PATH
SCHEMA_OBJ = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

TOP_KEYS_ORDER = list(SCHEMA_OBJ["properties"].keys())
PERSONA_KEYS_ORDER = list(SCHEMA_OBJ["properties"]["personas"]["items"]["properties"].keys())
DISCLOSURE_KEYS_ORDER = list(SCHEMA_OBJ["properties"]["disclosure"]["properties"].keys())

DOC_KINDS_SET = set(SCHEMA_OBJ["$defs"]["doc_kind"]["enum"])
STATUS_SET = set(SCHEMA_OBJ["properties"]["status"]["enum"])
TEXT_QUALITY_SET = set(SCHEMA_OBJ["properties"]["text_quality"]["enum"])
ROLES_SET = set(SCHEMA_OBJ["properties"]["personas"]["items"]["properties"]["role"]["enum"])
ETYPES_SET = set(SCHEMA_OBJ["properties"]["personas"]["items"]["properties"]["entity_type"]["enum"])

NON_USABLE_TRIAGE_STATUSES = frozenset({"error_or_block", "stub_or_blank", "ocr_unreadable"})
assert NON_USABLE_TRIAGE_STATUSES <= STATUS_SET

# Frozen pipe order used in V4 LoRA training prompts (train_v4_all360.jsonl; ct-1lpr).
V4_TRAINED_STATUS_ORDER = (
    "error_or_block",
    "index_or_listing",
    "govinfo_wrapper",
    "ocr_unreadable",
    "usable",
    "cover_or_toc",
    "stub_or_blank",
    "catalog_xml",
)
assert len(V4_TRAINED_STATUS_ORDER) == len(STATUS_SET) and set(V4_TRAINED_STATUS_ORDER) == STATUS_SET

DOC_KINDS_CSV = "|".join(SCHEMA_OBJ["$defs"]["doc_kind"]["enum"])
STATUS_CSV = "|".join(V4_TRAINED_STATUS_ORDER)
ROLES_CSV = "|".join(SCHEMA_OBJ["properties"]["personas"]["items"]["properties"]["role"]["enum"])
ETYPES_CSV = "|".join(SCHEMA_OBJ["properties"]["personas"]["items"]["properties"]["entity_type"]["enum"])

SYS_DOCMETA_V4 = (
    "Extract Congressional p1-2 metadata as ONE compact minified JSON matching DocMetaV4Causal in exact key order "
    "(omit empty/absent keys; NEVER emit null or empty arrays []; NEVER list roll-call voter grids or standing backbench rosters).\n"
    "Critical Rules:\n"
    "- TEXT OVER FILENAME SLUG: Judge primary_kind from document text, NOT filename slugs (e.g. `Wstate-` containing QFRs is `qfr_response`; `QFR001`/`TTF-` cover letters are `qfr_request`/`witness_invitation`/`external_submission_letter`).\n"
    "- CHARTER/MEMO vs NOTICE vs WEB vs TRANSCRIPT: Committee staff memos, hearing charters, and markup memos -> `hearing_memo_or_charter`. Formal event announcements -> `hearing_notice`/`markup_notice`. Scraped HTML single-hearing pages -> `event_web_page` (or `index_or_listing` status if pure nav/list). Verbatim Q&A/GPO hearing books -> `hearing_transcript`.\n"
    "- MEMBER vs WITNESS: Chair/member opening remarks -> `member_opening_statement`. A Member testifying before another committee -> `witness_statement` (role=`witness`, entity_type=`member`).\n"
    "- AMENDMENTS vs VOTES vs REPORTS: ALL amendments (floor, Senate, ANS, committee, report amendments) -> `committee_amendment`. Roll-call tallies -> `committee_vote`. Formal committee reports -> `committee_report`.\n"
    "- EXHIBITS vs ERRORS: Redacted/internal emails, chat logs, org charts, and news clips entered as exhibits are `status:\"usable\"` (`investigative_exhibit` or `news_clip_or_article`), NEVER `error_or_block`. Use `error_or_block`/`stub_or_blank` ONLY for unreadable/blank/JS-only stubs.\n"
    "- PERSONAS <= 10: Active actors in reading order ONLY (witnesses, speakers, chairs, ranking members, sponsors, offerors, nominees, senders, recipients, named staff).\n"
    "Keys in order:\n"
    f"1. status ({STATUS_CSV}), text_quality (native|clean_ocr|noisy_ocr|garbled), error_reason (ONLY if error_or_block|stub_or_blank|ocr_unreadable; omit remaining keys).\n"
    "2. verbatim_title, short_titles ([]<=8), chamber (house|senate|joint|commission|executive_or_external), congress (1..130), committees ([]), subcommittees ([]), issuer_org, event_type (hearing|field_hearing|nomination_hearing|markup|business_meeting|roundtable_or_briefing|floor_or_other), event_title, venue_kind (capitol_room|field_site|virtual|hybrid), venue, event_time, date_spans ([]<=8), doc_date, event_date, due_date (YYYY-MM-DD or YYYY-MM).\n"
    f"3. primary_kind ({DOC_KINDS_CSV}), secondary_kinds ([]), subkind.\n"
    f"4. personas ([]<=10: name FIRST, creds, title, org, sub_org, secondary_orgs, on_behalf_of, party_state, panel, role [{ROLES_CSV}], entity_type [{ETYPES_CSV}], work_addr, official_contact, prior_roles, education, redacted_personal_pii).\n"
    "5. refs ([]<=25 prefixed bill:|amdt:|law:|usc:|cfr:|fr:|docket:|eo:|rule:|treaty:|nom:|rept:|hrg:|jct:|gao:|crs:|cbo:|olc:|gsa:|sudoc:|gpo:|grant:|advisory:|exhibit:|id:), programs ([]<=10), orgs_mentioned ([]<=12), places ([]<=10), fiscal_years ([]<=12 int), correspondence_flow (committee_to_witness|witness_to_committee|congress_to_agency|agency_to_congress|member_to_committee|committee_to_member|external_to_committee|foreign_gov_to_congress|internal_exhibit_chain), signatory_count, action_summary, disclosure.\n"
    "6. LAST: composed_title (<110 chars), gist (<=22 words), topics ([]<=6).\n"
    "Output raw JSON only."
)


def build_prompt_v4(known: str, filename: str, text: str) -> str:
    return f"{SYS_DOCMETA_V4}\n\nAdvisory known metadata: {known}\nFilename: {filename}\nText:\n{text}"


def _is_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and v.strip() in ("", "N/A", "n/a", "None", "null", "unknown", "Unknown"):
        return True
    if isinstance(v, (list, dict)) and len(v) == 0:
        return True
    return False


def canonicalize_v4(raw_obj: dict) -> dict:
    """Clean nulls/N/A/empty values, enforce minItems>=1 & maxItems, order causally, and validate against DocMetaV4Causal."""
    out: dict = {}
    st = raw_obj.get("status", "usable")
    tq = raw_obj.get("text_quality", "native")
    out["status"] = st if isinstance(st, str) and st in STATUS_SET else "usable"
    out["text_quality"] = tq if isinstance(tq, str) and tq in TEXT_QUALITY_SET else "native"

    if out["status"] in NON_USABLE_TRIAGE_STATUSES:
        er = raw_obj.get("error_reason")
        out["error_reason"] = er.strip()[:200] if isinstance(er, str) and er.strip() else out["status"]
        ok, err = validate_v4(out)
        if not ok:
            from .pythonic_v5 import DocMetaValidationError

            raise DocMetaValidationError(f"Invalid error-status DocMetaV4: {err}")
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
        if k in ("status", "text_quality", "error_reason"):
            continue
        if k not in raw_obj:
            continue
        val = raw_obj[k]
        if _is_empty(val):
            continue

        if k == "personas" and isinstance(val, list):
            clean_p = []
            for item in val:
                if not isinstance(item, dict) or _is_empty(item.get("name")):
                    continue
                role = item.get("role", "witness")
                if role == "member":
                    role = "author_or_speaker"
                if not isinstance(role, str) or role not in ROLES_SET:
                    continue
                etype = item.get("entity_type", "non_gov_person")
                if not isinstance(etype, str) or etype not in ETYPES_SET:
                    etype = "non_gov_person"
                p_item = {}
                for pk in PERSONA_KEYS_ORDER:
                    if pk == "role":
                        p_item["role"] = role
                    elif pk == "entity_type":
                        p_item["entity_type"] = etype
                    elif pk in item and not _is_empty(item[pk]):
                        pv = item[pk]
                        if pk == "prior_roles" and isinstance(pv, list):
                            pv = [str(x).strip() for x in pv if not _is_empty(x)][:8]
                            if not pv:
                                continue
                        elif pk == "education" and isinstance(pv, list):
                            pv = [str(x).strip() for x in pv if not _is_empty(x)][:5]
                            if not pv:
                                continue
                        elif pk == "secondary_orgs" and isinstance(pv, list):
                            pv = [str(x).strip() for x in pv if not _is_empty(x)]
                            if not pv:
                                continue
                        elif pk == "redacted_personal_pii":
                            if pv is not True:
                                continue
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
            d_obj = {}
            for dk in DISCLOSURE_KEYS_ORDER:
                if dk not in val or val[dk] is None:
                    continue
                dv = val[dk]
                if dk in ("represented_orgs", "fiduciary_orgs", "federal_grants", "foreign_payments"):
                    if isinstance(dv, list):
                        dv = [str(x).strip() for x in dv if not _is_empty(x)]
                        if dv:
                            d_obj[dk] = dv
                elif dk == "capacity":
                    if dv in ("self", "organization", "government"):
                        d_obj[dk] = dv
                elif isinstance(dv, bool):
                    d_obj[dk] = dv
            if d_obj:
                out["disclosure"] = d_obj

        elif k == "primary_kind":
            out[k] = val if isinstance(val, str) and val in DOC_KINDS_SET else "other"

        elif k == "secondary_kinds" and isinstance(val, list):
            sk = [x for x in val if isinstance(x, str) and x in DOC_KINDS_SET and x != out.get("primary_kind")]
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
            arr = [str(x).strip() for x in val if not _is_empty(x)]
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

    ok, err = validate_v4(out)
    if not ok:
        from .pythonic_v5 import DocMetaValidationError

        raise DocMetaValidationError(f"Canonicalized DocMetaV4 failed validation: {err}")
    return out


def validate_v4(obj: str | Mapping[str, Any] | None) -> tuple[bool, str | None]:
    """Validate an object against DocMetaV4Causal using the single strict validator."""
    from .pythonic_v5 import validate_docmeta_v4

    return validate_docmeta_v4(obj)
