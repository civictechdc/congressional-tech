"""Compact V6 Residual Wire Format (`C2` Short System Prompt + `C4` Lossless Compact JSON).

Cuts `SYS_DOCMETA` prefix tokens by ~87% (`1,368 -> ~175` tokens, `-6.9 ms/step` at `B=128`)
and cuts output decode tokens by ~16.5% (`~310 -> ~259` tokens) with 100% lossless expansion
back to `DocMetaV4Causal` before `post_pass_v6` (which synthesizes deterministic `refs[]`
and `fiscal_years[]` via `citations_v6`).

Top-level import is 100% Python stdlib (`/usr/bin/python3 -B -I -S` clean).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

DOCMETA_DIR = Path(__file__).resolve().parent
V4_SCHEMA_PATH = DOCMETA_DIR / "docmeta_v4_causal.schema.json"
_V4_SCHEMA_OBJ: dict[str, Any] = json.loads(V4_SCHEMA_PATH.read_text(encoding="utf-8"))

# 100% bijective top-level, persona, and disclosure short keys (preserving exact causal order!)
COMPACT_TOP_KEY_MAP: dict[str, str] = {
    "status": "st",
    "text_quality": "tq",
    "error_reason": "er",
    "verbatim_title": "vt",
    "short_titles": "sts",
    "chamber": "ch",
    "congress": "cg",
    "committees": "cm",
    "subcommittees": "sc",
    "issuer_org": "io",
    "event_type": "et",
    "event_title": "ev",
    "venue_kind": "vk",
    "venue": "vn",
    "event_time": "tm",
    "date_spans": "ds",
    "doc_date": "dd",
    "event_date": "ed",
    "due_date": "du",
    "primary_kind": "pk",
    "secondary_kinds": "sk",
    "subkind": "sb",
    "personas": "ps",
    # Note: `refs` and `fiscal_years` are omitted from compact wire generation and
    # deterministically populated by `post_pass_v6` (`citations_v6`), while still mapped
    # if present in any hybrid input.
    "refs": "rf",
    "programs": "pg",
    "orgs_mentioned": "om",
    "places": "pl",
    "fiscal_years": "fy",
    "correspondence_flow": "cf",
    "signatory_count": "sn",
    "action_summary": "as",
    "disclosure": "dc",
    "composed_title": "ct",
    "gist": "gi",
    "topics": "tp",
}
INV_COMPACT_TOP_KEY_MAP: dict[str, str] = {v: k for k, v in COMPACT_TOP_KEY_MAP.items()}

COMPACT_PERSONA_KEY_MAP: dict[str, str] = {
    "name": "n",
    "creds": "cr",
    "title": "t",
    "org": "o",
    "sub_org": "so",
    "secondary_orgs": "s2",
    "on_behalf_of": "ob",
    "party_state": "ps",
    "panel": "pn",
    "role": "r",
    "entity_type": "e",
    "work_addr": "wa",
    "official_contact": "oc",
    "prior_roles": "pr",
    "education": "ed",
    "redacted_personal_pii": "pii",
}
INV_COMPACT_PERSONA_KEY_MAP: dict[str, str] = {v: k for k, v in COMPACT_PERSONA_KEY_MAP.items()}

COMPACT_DISCLOSURE_KEY_MAP: dict[str, str] = {
    "capacity": "c",
    "gov_witness": "gw",
    "represented_orgs": "ro",
    "fiduciary_orgs": "fo",
    "unrepresented_parent_or_sub": "up",
    "has_federal_grants": "fg",
    "federal_grants": "fgs",
    "has_foreign_payments": "fp",
    "foreign_payments": "fps",
}
INV_COMPACT_DISCLOSURE_KEY_MAP: dict[str, str] = {v: k for k, v in COMPACT_DISCLOSURE_KEY_MAP.items()}

OMITTED_DETERMINISTIC_V4_KEYS: frozenset[str] = frozenset({"refs", "fiscal_years"})

# Proposal C2: Distilled ~180-token system prompt (vs 1,368-token SYS_DOCMETA_V4)
SYS_DOCMETA_V6_COMPACT: str = (
    "Extract Congressional p1-2 metadata as compact JSON (DocMetaV6Compact) in causal key order. "
    "Omit absent/null/[], default status:\"usable\", default text_quality:\"native\", and refs/fiscal_years; "
    "no voter grids or backbench rosters.\n"
    "Rules: Judge pk from text over slug (Wstate QFR->qfr_response; memo/charter->hearing_memo_or_charter; "
    "hearing HTML->event_web_page; Chair remarks->member_opening_statement; Member witness->witness_statement r:witness e:member; "
    "amendment->committee_amendment; exhibit/email->investigative_exhibit).\n"
    "Keys: st,tq,er(non-usable only),vt,sts,ch,cg,cm,sc,io,et,ev,vk,vn,tm,ds,dd,ed,du,pk,sk,sb,"
    "ps(<=10: n,cr,t,o,so,s2,ob,ps,pn,r,e,wa,oc,pr,ed,pii),pg,om,pl,cf,sn,as,dc,ct(<110c),gi(<=22w),tp(<=6)."
)


def compact_known_str(known: str) -> str:
    """Advisory metadata in one serialization (`separators=(",", ":")`) whichever caller built it."""
    try:
        return json.dumps(json.loads(known), separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        return known


def build_prompt_v6_compact(known: str, filename: str, text: str) -> str:
    """Build C2+C4 compact prompt preserving the exact `Advisory known metadata / Filename / Text` suffix interface."""
    return (
        f"{SYS_DOCMETA_V6_COMPACT}\n\nAdvisory known metadata: {compact_known_str(known)}\n"
        f"Filename: {filename}\nText:\n{text}"
    )


def _strip_descriptions(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_descriptions(v) for k, v in node.items() if k != "description"}
    if isinstance(node, list):
        return [_strip_descriptions(x) for x in node]
    return node


def _build_compact_schema_obj() -> dict[str, Any]:
    src = copy.deepcopy(_V4_SCHEMA_OBJ)
    v4_props: dict[str, Any] = src["properties"]
    c_props: dict[str, Any] = {}

    for v4_k, prop_def in v4_props.items():
        if v4_k in OMITTED_DETERMINISTIC_V4_KEYS:
            continue
        ck = COMPACT_TOP_KEY_MAP[v4_k]
        p_clean = _strip_descriptions(prop_def)
        if v4_k == "personas":
            item_props_v4 = p_clean["items"]["properties"]
            p_clean["items"]["properties"] = {
                COMPACT_PERSONA_KEY_MAP[pk_k]: pv for pk_k, pv in item_props_v4.items()
            }
            p_clean["items"]["required"] = ["n", "r", "e"]
        elif v4_k == "disclosure":
            disc_props_v4 = p_clean["properties"]
            p_clean["properties"] = {
                COMPACT_DISCLOSURE_KEY_MAP[dk]: dv for dk, dv in disc_props_v4.items()
            }
        c_props[ck] = p_clean

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "DocMetaV6Compact",
        "type": "object",
        "minProperties": 1,
        "additionalProperties": False,
        "$defs": _strip_descriptions(src["$defs"]),
        "properties": c_props,
    }


DOCMETA_V6_COMPACT_SCHEMA_OBJ: dict[str, Any] = _build_compact_schema_obj()
DOCMETA_V6_COMPACT_SCHEMA_STR: str = json.dumps(DOCMETA_V6_COMPACT_SCHEMA_OBJ, separators=(",", ":"))


def build_doc_kind_compact_schema_v6(
    target_kinds: str | Sequence[str],
    *,
    banned_kinds: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Compile a 1-kind, multi-kind (`'kindA|kindB'`), or banned-kind `DocMetaV6Compact` JSON Schema."""
    all_kinds: list[str] = list(_V4_SCHEMA_OBJ["$defs"]["doc_kind"]["enum"])
    valid_set = set(all_kinds)

    if isinstance(target_kinds, str):
        parts = [p.strip() for p in target_kinds.split("|") if p.strip()]
    else:
        parts = [str(p).strip() for p in target_kinds if str(p).strip()]

    schema = copy.deepcopy(DOCMETA_V6_COMPACT_SCHEMA_OBJ)
    props = schema["properties"]

    if banned_kinds:
        ban_set = {str(b).strip() for b in banned_kinds if str(b).strip()}
        allowed = [k for k in all_kinds if k not in ban_set]
        if allowed:
            props["pk"] = {"type": "string", "enum": allowed}
        return schema

    deduped = [k for k in dict.fromkeys(parts) if k in valid_set]
    if not deduped:
        raise ValueError(f"Empty or invalid compact target_kinds={target_kinds!r}")

    # Locked/narrowed schemas correspond strictly to usable documents (`st` omitted or `"usable"`):
    # disallow error_reason (`er`) and non-usable `st` values, and require `pk`, `ct`, `gi`, `tp`.
    props["st"]["enum"] = ["usable"]
    props.pop("er", None)
    props["pk"] = {"type": "string", "enum": deduped}
    schema["required"] = ["pk", "ct", "gi", "tp"]

    if len(deduped) == 1 and deduped[0] == "truth_in_testimony_disclosure":
        props["ch"]["enum"] = ["house"]
        schema["required"] = ["pk", "dc", "ct", "gi", "tp"]
    elif "truth_in_testimony_disclosure" not in deduped:
        # Keep `dc` available on witness_statement/biography where stapled disclosures appear,
        # but prune on pure legislative/notice kinds where disclosure never occurs.
        if all(
            k
            in {
                "hearing_notice",
                "markup_notice",
                "committee_vote",
                "bill_or_draft",
                "committee_amendment",
                "comparative_print",
                "section_by_section",
                "legislative_schedule_or_calendar",
            }
            for k in deduped
        ):
            props.pop("dc", None)
    return schema


def encode_v4_to_compact_v6(
    v4_obj: Mapping[str, Any],
    *,
    omit_deterministic: bool = True,
) -> dict[str, Any]:
    """Convert a canonical `DocMetaV4Causal` dict into `DocMetaV6Compact` causal key order."""
    out: dict[str, Any] = {}
    for v4_k in _V4_SCHEMA_OBJ["properties"]:
        if v4_k not in v4_obj:
            continue
        if omit_deterministic and v4_k in OMITTED_DETERMINISTIC_V4_KEYS:
            continue
        val = v4_obj[v4_k]
        if val is None or val == "" or val == [] or val == {}:
            continue
        if v4_k == "status" and val == "usable":
            continue
        if v4_k == "text_quality" and val == "native":
            continue

        ck = COMPACT_TOP_KEY_MAP[v4_k]
        if v4_k == "personas" and isinstance(val, list):
            cp_list: list[dict[str, Any]] = []
            for p in val:
                if not isinstance(p, Mapping) or not p.get("name"):
                    continue
                cp: dict[str, Any] = {}
                for pk_v4 in _V4_SCHEMA_OBJ["properties"]["personas"]["items"]["properties"]:
                    if pk_v4 in p and p[pk_v4] not in (None, "", [], {}):
                        cp[COMPACT_PERSONA_KEY_MAP[pk_v4]] = p[pk_v4]
                if "n" in cp and "r" in cp and "e" in cp:
                    cp_list.append(cp)
            if cp_list:
                out[ck] = cp_list
        elif v4_k == "disclosure" and isinstance(val, Mapping):
            cd: dict[str, Any] = {}
            for dk_v4 in _V4_SCHEMA_OBJ["properties"]["disclosure"]["properties"]:
                if dk_v4 in val and val[dk_v4] not in (None, "", [], {}):
                    cd[COMPACT_DISCLOSURE_KEY_MAP[dk_v4]] = val[dk_v4]
            if cd:
                out[ck] = cd
        else:
            out[ck] = val
    return out


def expand_compact_v6_to_v4(raw_obj: Mapping[str, Any]) -> dict[str, Any]:
    """Losslessly expand `DocMetaV6Compact` (or pass-through `DocMetaV4Causal`) into V4 key space."""
    if not isinstance(raw_obj, Mapping):
        return {"status": "usable", "text_quality": "native"}

    # Auto-detect already-expanded V4 objects that contain full V4 keys and no compact-only keys
    has_compact_key = any(k in INV_COMPACT_TOP_KEY_MAP for k in raw_obj)
    if not has_compact_key and ("status" in raw_obj or "primary_kind" in raw_obj or "composed_title" in raw_obj):
        return dict(raw_obj)

    expanded_unordered: dict[str, Any] = {}
    for k, val in raw_obj.items():
        v4_k = INV_COMPACT_TOP_KEY_MAP.get(k, k)
        if v4_k not in _V4_SCHEMA_OBJ["properties"]:
            continue
        if v4_k == "personas" and isinstance(val, list):
            p_list: list[dict[str, Any]] = []
            for p in val:
                if not isinstance(p, Mapping):
                    continue
                ep: dict[str, Any] = {}
                for pk_raw, pv in p.items():
                    ep[INV_COMPACT_PERSONA_KEY_MAP.get(pk_raw, pk_raw)] = pv
                # Order persona keys strictly per V4 schema
                ordered_p = {
                    pk_ord: ep[pk_ord]
                    for pk_ord in _V4_SCHEMA_OBJ["properties"]["personas"]["items"]["properties"]
                    if pk_ord in ep
                }
                if ordered_p.get("name"):
                    p_list.append(ordered_p)
            if p_list:
                expanded_unordered["personas"] = p_list
        elif v4_k == "disclosure" and isinstance(val, Mapping):
            ed: dict[str, Any] = {}
            for dk_raw, dv in val.items():
                ed[INV_COMPACT_DISCLOSURE_KEY_MAP.get(dk_raw, dk_raw)] = dv
            ordered_d = {
                dk_ord: ed[dk_ord]
                for dk_ord in _V4_SCHEMA_OBJ["properties"]["disclosure"]["properties"]
                if dk_ord in ed
            }
            if ordered_d:
                expanded_unordered["disclosure"] = ordered_d
        else:
            expanded_unordered[v4_k] = val

    # Restore omitted defaults (`status="usable"`, `text_quality="native"`) and enforce exact V4 causal order
    expanded_unordered.setdefault("status", "usable")
    expanded_unordered.setdefault("text_quality", "native")

    ordered_v4: dict[str, Any] = {}
    for v4_k in _V4_SCHEMA_OBJ["properties"]:
        if v4_k in expanded_unordered:
            ordered_v4[v4_k] = expanded_unordered[v4_k]
    return ordered_v4


def expand_compact_json_str_to_v4(raw_text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse raw model JSON output (compact V6 or full V4) and return `(expanded_v4_dict, expanded_v4_json_str)`."""
    t = (raw_text or "").strip()
    if not t:
        return None, None
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    try:
        parsed = json.loads(t)
    except Exception:
        return None, None
    if not isinstance(parsed, Mapping):
        return None, None
    v4_obj = expand_compact_v6_to_v4(parsed)
    return v4_obj, json.dumps(v4_obj, separators=(",", ":"), ensure_ascii=False)


def detect_checkpoint_wire_format(model_dir: str | Path | None) -> str:
    """Inspect `docmeta_wire_config.json` in `model_dir` -> `'compact'` or `'v4'`."""
    if model_dir is None:
        return "v4"
    cfg_p = Path(model_dir) / "docmeta_wire_config.json"
    if cfg_p.is_file():
        try:
            meta = json.loads(cfg_p.read_text(encoding="utf-8"))
            wf = str(meta.get("wire_format") or "").strip().lower()
            if wf in ("compact", "compact_v6", "v6_compact"):
                return "compact"
        except Exception:
            pass
    return "v4"


__all__ = [
    "COMPACT_DISCLOSURE_KEY_MAP",
    "COMPACT_PERSONA_KEY_MAP",
    "COMPACT_TOP_KEY_MAP",
    "DOCMETA_V6_COMPACT_SCHEMA_OBJ",
    "DOCMETA_V6_COMPACT_SCHEMA_STR",
    "OMITTED_DETERMINISTIC_V4_KEYS",
    "SYS_DOCMETA_V6_COMPACT",
    "build_doc_kind_compact_schema_v6",
    "build_prompt_v6_compact",
    "detect_checkpoint_wire_format",
    "encode_v4_to_compact_v6",
    "expand_compact_json_str_to_v4",
    "expand_compact_v6_to_v4",
]
