"""100-doc stratified 3-family pilot runner & CLI for DocMeta V7.2.

Usage:
    python -m congress_docmeta.v7.factory.pilot --limit 100
    python -m congress_docmeta.v7.factory.pilot --limit 5 --dry-run --out-dir /tmp/pilot_smoke
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Sequence

from .cache import SixTupleCache, default_cache_path, discover_main_checkout_root
from .counterfactual import run_counterfactual_suite
from .grounding import (
    ConsensusDecision,
    adjudicate_three_family,
    format_deadlock_digest,
    merge_consensus_payload,
    repair_span_refs_in_payload,
    verify_span_grounding,
)
from .runners import (
    FamilyRunResult,
    RunnerConfig,
    extract_json_payload,
    run_three_family_parallel,
)
from .splits import (
    audit_decontamination,
    build_event_temporal_splits,
    compute_agreement_metrics,
)


DEFAULT_CODEBOOK_VERSION = "v7.0"

# Built-in V6.5 -> (V7 primary_genre, V7 specialist_family) crosswalk matching
# DocMeta V7.1's 14 orthogonal genres when `congress_docmeta.v7.crosswalk` is not loaded.
V65_TO_V7_GENRE_MAP: dict[str, tuple[str | None, str | None]] = {
    # 1. event_logistics
    "hearing_notice": ("hearing_or_markup_notice", "event_logistics"),
    "markup_notice": ("hearing_or_markup_notice", "event_logistics"),
    "legislative_schedule_or_calendar": ("hearing_or_markup_notice", "event_logistics"),
    "event_web_page": ("hearing_or_markup_notice", "event_logistics"),
    "hearing_memo_or_charter": ("hearing_memo_or_witness_list", "event_logistics"),
    "witness_list": ("hearing_memo_or_witness_list", "event_logistics"),
    # 2. testimony_bio_disclosure
    "witness_statement": ("witness_testimony", "testimony_bio_disclosure"),
    "member_opening_statement": ("member_statement", "testimony_bio_disclosure"),
    "member_or_floor_statement": ("member_statement", "testimony_bio_disclosure"),
    "witness_biography": ("witness_biography", "testimony_bio_disclosure"),
    "nominee_questionnaire_apq": ("witness_biography", "testimony_bio_disclosure"),
    "truth_in_testimony_disclosure": ("truth_in_testimony", "testimony_bio_disclosure"),
    # 3. transcript_vote_attendance
    "hearing_transcript": ("hearing_transcript", "transcript_vote_attendance"),
    "committee_vote": ("committee_vote_or_action", "transcript_vote_attendance"),
    "meeting_results": ("committee_vote_or_action", "transcript_vote_attendance"),
    "attendance_quorum_sheet": ("committee_vote_or_action", "transcript_vote_attendance"),
    "member_roster": ("committee_vote_or_action", "transcript_vote_attendance"),
    "committee_resolution": ("committee_vote_or_action", "transcript_vote_attendance"),
    "committee_rules": ("committee_vote_or_action", "transcript_vote_attendance"),
    # 4. correspondence_qfr_oversight
    "qfr_request": ("qfr_correspondence", "correspondence_qfr_oversight"),
    "qfr_response": ("qfr_correspondence", "correspondence_qfr_oversight"),
    "oversight_letter": ("oversight_or_committee_letter", "correspondence_qfr_oversight"),
    "witness_invitation": ("oversight_or_committee_letter", "correspondence_qfr_oversight"),
    "nomination_or_support_letter": ("oversight_or_committee_letter", "correspondence_qfr_oversight"),
    "external_submission_letter": ("external_submission_or_comment", "correspondence_qfr_oversight"),
    "public_comment_or_submission": ("external_submission_or_comment", "correspondence_qfr_oversight"),
    "legal_or_investigative_filing": ("external_submission_or_comment", "correspondence_qfr_oversight"),
    "investigative_exhibit": ("external_submission_or_comment", "correspondence_qfr_oversight"),
    # 5. legislation_report_fiscal
    "bill_or_draft": ("bill_or_amendment", "legislation_report_fiscal"),
    "committee_amendment": ("bill_or_amendment", "legislation_report_fiscal"),
    "comparative_print": ("bill_or_amendment", "legislation_report_fiscal"),
    "section_by_section": ("bill_or_amendment", "legislation_report_fiscal"),
    "treaty_document": ("bill_or_amendment", "legislation_report_fiscal"),
    "committee_report": ("committee_or_agency_report", "legislation_report_fiscal"),
    "agency_or_gao_crs_report": ("committee_or_agency_report", "legislation_report_fiscal"),
    "external_report_or_whitepaper": ("committee_or_agency_report", "legislation_report_fiscal"),
    "oversight_plan": ("committee_or_agency_report", "legislation_report_fiscal"),
    "press_release_or_fact_sheet": ("committee_or_agency_report", "legislation_report_fiscal"),
    "news_clip_or_article": ("committee_or_agency_report", "legislation_report_fiscal"),
    "explanatory_statement": ("committee_or_agency_report", "legislation_report_fiscal"),
    "budget_views_and_estimates": ("budget_or_cost_estimate", "legislation_report_fiscal"),
    "revenue_or_cost_estimate": ("budget_or_cost_estimate", "legislation_report_fiscal"),
    "gsa_prospectus_or_property": ("budget_or_cost_estimate", "legislation_report_fiscal"),
    # Orthogonal V6.5 classes dismantled in V7
    "multi_doc_packet": ("witness_testimony", "testimony_bio_disclosure"),
    "slides_or_visual": ("witness_testimony", "testimony_bio_disclosure"),
    "error_or_non_document": (None, None),
    "other": ("committee_or_agency_report", "legislation_report_fiscal"),
}

GENRE_TO_SPECIALIST_FAMILY: dict[str, str] = {
    "hearing_or_markup_notice": "event_logistics",
    "hearing_memo_or_witness_list": "event_logistics",
    "witness_testimony": "testimony_bio_disclosure",
    "member_statement": "testimony_bio_disclosure",
    "witness_biography": "testimony_bio_disclosure",
    "truth_in_testimony": "testimony_bio_disclosure",
    "hearing_transcript": "transcript_vote_attendance",
    "committee_vote_or_action": "transcript_vote_attendance",
    "qfr_correspondence": "correspondence_qfr_oversight",
    "oversight_or_committee_letter": "correspondence_qfr_oversight",
    "external_submission_or_comment": "correspondence_qfr_oversight",
    "bill_or_amendment": "legislation_report_fiscal",
    "committee_or_agency_report": "legislation_report_fiscal",
    "budget_or_cost_estimate": "legislation_report_fiscal",
}

_SPAN_REF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "quote": {"type": "string"},
        "start": {"type": "integer"},
        "end": {"type": "integer"},
    },
    "required": ["quote", "start", "end"],
}

CORE_TRIAGE_SCHEMA: dict[str, Any] = {
    "title": "CoreEnvelopeExtraction",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "rationale": {"type": "string"},
        "status": {
            "type": "string",
            "enum": [
                "usable",
                "cover_or_toc",
                "govinfo_wrapper",
                "index_or_listing",
                "catalog_xml",
                "stub_or_blank",
                "error_or_block",
                "ocr_unreadable",
            ],
        },
        "media_format": {
            "type": ["string", "null"],
            "enum": ["prose", "slides", "web_page", "table_or_form", None],
        },
        "is_packet": {"type": "boolean"},
        "contains_genres": {"type": "array", "items": {"type": "string"}},
        "primary_genre": {
            "type": ["string", "null"],
            "enum": [*sorted(GENRE_TO_SPECIALIST_FAMILY.keys()), None],
        },
        "specialist_family": {
            "type": ["string", "null"],
            "enum": [*sorted(set(GENRE_TO_SPECIALIST_FAMILY.values())), None],
        },
        "subkind": {"type": ["string", "null"]},
        "verbatim_title": {"type": ["string", "null"]},
        "title_span": {"anyOf": [_SPAN_REF_SCHEMA, {"type": "null"}]},
        "doc_date": {"type": ["string", "null"]},
        "date_spans": {"type": "array", "items": _SPAN_REF_SCHEMA},
        "chamber": {
            "type": ["string", "null"],
            "enum": ["house", "senate", "joint", "commission", "executive_or_external", None],
        },
        "congress": {"type": ["integer", "null"]},
        "committees": {"type": "array", "items": {"type": "string"}},
        "subcommittees": {"type": "array", "items": {"type": "string"}},
        "gist": {"type": ["string", "null"]},
        "topics": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "rationale",
        "status",
        "media_format",
        "is_packet",
        "contains_genres",
        "primary_genre",
        "specialist_family",
        "subkind",
        "verbatim_title",
        "title_span",
        "doc_date",
        "date_spans",
        "chamber",
        "congress",
        "committees",
        "subcommittees",
        "gist",
        "topics",
    ],
}

SPECIALIST_SCHEMAS: dict[str, dict[str, Any]] = {
    "event_logistics": {
        "title": "EventLogisticsExtraction",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "rationale": {"type": "string"},
            "event_type": {"type": ["string", "null"]},
            "event_title": {"type": ["string", "null"]},
            "event_title_span": {"anyOf": [_SPAN_REF_SCHEMA, {"type": "null"}]},
            "event_date": {"type": ["string", "null"]},
            "event_date_span": {"anyOf": [_SPAN_REF_SCHEMA, {"type": "null"}]},
            "event_time": {"type": ["string", "null"]},
            "venue_kind": {"type": ["string", "null"]},
            "venue": {"type": ["string", "null"]},
            "venue_span": {"anyOf": [_SPAN_REF_SCHEMA, {"type": "null"}]},
            "witnesses": {"type": "array", "items": {"type": "object"}},
            "due_date": {"type": ["string", "null"]},
            "bill_refs": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "rationale",
            "event_type",
            "event_title",
            "event_title_span",
            "event_date",
            "event_date_span",
            "event_time",
            "venue_kind",
            "venue",
            "venue_span",
            "witnesses",
            "due_date",
            "bill_refs",
        ],
    },
    "testimony_bio_disclosure": {
        "title": "TestimonyBioDisclosureExtraction",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "rationale": {"type": "string"},
            "personas": {"type": "array", "items": {"type": "object"}},
            "issuer_org": {"type": ["string", "null"]},
            "issuer_org_span": {"anyOf": [_SPAN_REF_SCHEMA, {"type": "null"}]},
            "disclosure_has_grants_or_contracts": {"type": ["boolean", "null"]},
            "disclosure_amounts": {"type": "array", "items": {"type": "string"}},
            "disclosure_spans": {"type": "array", "items": _SPAN_REF_SCHEMA},
            "prior_roles": {"type": "array", "items": {"type": "string"}},
            "education": {"type": "array", "items": {"type": "string"}},
            "event_title": {"type": ["string", "null"]},
            "event_date": {"type": ["string", "null"]},
            "bill_refs": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "rationale",
            "personas",
            "issuer_org",
            "issuer_org_span",
            "disclosure_has_grants_or_contracts",
            "disclosure_amounts",
            "disclosure_spans",
            "prior_roles",
            "education",
            "event_title",
            "event_date",
            "bill_refs",
        ],
    },
    "transcript_vote_attendance": {
        "title": "TranscriptVoteAttendanceExtraction",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "rationale": {"type": "string"},
            "event_type": {"type": ["string", "null"]},
            "event_title": {"type": ["string", "null"]},
            "event_title_span": {"anyOf": [_SPAN_REF_SCHEMA, {"type": "null"}]},
            "event_date": {"type": ["string", "null"]},
            "venue": {"type": ["string", "null"]},
            "presiding_or_witnesses": {"type": "array", "items": {"type": "object"}},
            "members_present": {"type": "array", "items": {"type": "string"}},
            "members_present_spans": {"type": "array", "items": _SPAN_REF_SCHEMA},
            "staff_present": {"type": "array", "items": {"type": "string"}},
            "staff_present_spans": {"type": "array", "items": _SPAN_REF_SCHEMA},
            "action_summary": {"type": ["string", "null"]},
            "vote_tallies": {"type": "array", "items": {"type": "string"}},
            "bill_refs": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "rationale",
            "event_type",
            "event_title",
            "event_title_span",
            "event_date",
            "venue",
            "presiding_or_witnesses",
            "members_present",
            "members_present_spans",
            "staff_present",
            "staff_present_spans",
            "action_summary",
            "vote_tallies",
            "bill_refs",
        ],
    },
    "correspondence_qfr_oversight": {
        "title": "CorrespondenceQfrOversightExtraction",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "rationale": {"type": "string"},
            "correspondence_direction": {"type": ["string", "null"]},
            "senders": {"type": "array", "items": {"type": "object"}},
            "recipients": {"type": "array", "items": {"type": "object"}},
            "issuer_org": {"type": ["string", "null"]},
            "issuer_org_span": {"anyOf": [_SPAN_REF_SCHEMA, {"type": "null"}]},
            "signatory_count": {"type": ["integer", "null"]},
            "due_date": {"type": ["string", "null"]},
            "due_date_span": {"anyOf": [_SPAN_REF_SCHEMA, {"type": "null"}]},
            "subpoena_or_compelled": {"type": "boolean"},
            "bill_refs": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "rationale",
            "correspondence_direction",
            "senders",
            "recipients",
            "issuer_org",
            "issuer_org_span",
            "signatory_count",
            "due_date",
            "due_date_span",
            "subpoena_or_compelled",
            "bill_refs",
        ],
    },
    "legislation_report_fiscal": {
        "title": "LegislationReportFiscalExtraction",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "rationale": {"type": "string"},
            "short_titles": {"type": "array", "items": {"type": "string"}},
            "short_title_spans": {"type": "array", "items": _SPAN_REF_SCHEMA},
            "issuer_org": {"type": ["string", "null"]},
            "issuer_org_span": {"anyOf": [_SPAN_REF_SCHEMA, {"type": "null"}]},
            "sponsors_or_offerors": {"type": "array", "items": {"type": "object"}},
            "fiscal_years": {"type": "array", "items": {"type": "string"}},
            "bill_refs": {"type": "array", "items": {"type": "string"}},
            "statute_or_rule_refs": {"type": "array", "items": {"type": "string"}},
            "action_summary": {"type": ["string", "null"]},
        },
        "required": [
            "rationale",
            "short_titles",
            "short_title_spans",
            "issuer_org",
            "issuer_org_span",
            "sponsors_or_offerors",
            "fiscal_years",
            "bill_refs",
            "statute_or_rule_refs",
            "action_summary",
        ],
    },
}


def default_ssot_path() -> Path:
    return (
        discover_main_checkout_root()
        / ".cache"
        / "archive-release"
        / "docmeta-v65-raretypes-20261118"
        / "ssot"
        / "docmeta_gold_v6_5.jsonl"
    )


def default_out_dir() -> Path:
    return discover_main_checkout_root() / ".cache" / "archive-release" / "docmeta-v7-factory" / "pilot"


def _resolve_v7_runtime_specs(
    codebook_version_override: str | None = None,
) -> tuple[str, dict[str, Any], dict[str, dict[str, Any]], Any, dict[str, Any]]:
    """Lazily load `congress_docmeta.v7.models` / `codebook` if present, else use built-in V7.2 specs."""
    codebook_version = codebook_version_override or DEFAULT_CODEBOOK_VERSION
    core_schema = CORE_TRIAGE_SCHEMA
    specialist_schemas = SPECIALIST_SCHEMAS
    core_model_cls: Any = None
    specialist_model_classes: dict[str, Any] = {}

    try:
        cb = importlib.import_module("congress_docmeta.v7.codebook")
        if codebook_version_override is None:
            cv_attr = getattr(cb, "codebook_version", None)
            if callable(cv_attr):
                ver = str(cv_attr())
                codebook_version = f"v7.0:{ver[:12]}"
            else:
                for attr in ("CODEBOOK_VERSION", "VERSION"):
                    val = getattr(cb, attr, None)
                    if isinstance(val, str) and val.strip():
                        codebook_version = val.strip()
                        break
    except ImportError:
        pass

    try:
        models = importlib.import_module("congress_docmeta.v7.models")
        strict_schema_fn = getattr(models, "strict_json_schema", None)
        for attr in ("CoreEnvelopeExtraction", "CoreTriage", "CoreTriageV7", "CoreTriageSchema"):
            cls = getattr(models, attr, None)
            if cls is not None and hasattr(cls, "model_json_schema"):
                core_model_cls = cls
                if callable(strict_schema_fn):
                    core_schema = strict_schema_fn(cls, openai_strict=True)
                else:
                    core_schema = cls.model_json_schema()
                break
        if hasattr(models, "SPECIALIST_MODELS") and isinstance(models.SPECIALIST_MODELS, Mapping):
            loaded_spec: dict[str, dict[str, Any]] = {}
            for fam_key, cls in models.SPECIALIST_MODELS.items():
                key_str = fam_key.value if hasattr(fam_key, "value") else str(fam_key)
                specialist_model_classes[key_str] = cls
                if callable(strict_schema_fn):
                    loaded_spec[key_str] = strict_schema_fn(cls, openai_strict=True)
                elif hasattr(cls, "model_json_schema"):
                    loaded_spec[key_str] = cls.model_json_schema()
            if loaded_spec:
                specialist_schemas = loaded_spec
    except ImportError:
        pass

    return codebook_version, core_schema, specialist_schemas, core_model_cls, specialist_model_classes


def extract_blind_text_from_ssot_row(row: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Extract ONLY pure document text after `\\nText:\\n`, stripping prompt/filename/metadata.

    Returns `(blind_text, sidecar_metadata)`.
    """
    sidecar: dict[str, Any] = {
        "doc_key": str(row.get("doc_key") or ""),
        "ssot_split": row.get("split"),
        "stratum": row.get("stratum"),
        "source_batch": row.get("source_batch"),
        "filename": "",
        "v65_gold": {},
    }

    if "messages" in row and isinstance(row["messages"], Sequence) and row["messages"]:
        prompt_content = str(row["messages"][0].get("content") or "")
        marker = "\nText:\n"
        idx = prompt_content.find(marker)
        if idx >= 0:
            header = prompt_content[:idx]
            blind_text = prompt_content[idx + len(marker) :]
        elif prompt_content.startswith("Text:\n"):
            header = ""
            blind_text = prompt_content[len("Text:\n") :]
        else:
            header = ""
            blind_text = prompt_content

        for ln in header.splitlines():
            if ln.startswith("Filename:"):
                sidecar["filename"] = ln[len("Filename:") :].strip()
                break

        if len(row["messages"]) > 1:
            raw_gold = row["messages"][1].get("content")
            if isinstance(raw_gold, str) and raw_gold.strip():
                try:
                    sidecar["v65_gold"] = json.loads(raw_gold)
                except json.JSONDecodeError:
                    sidecar["v65_gold"] = {}
            elif isinstance(raw_gold, Mapping):
                sidecar["v65_gold"] = dict(raw_gold)
    else:
        blind_text = str(row.get("text") or "")
        sidecar["filename"] = str(row.get("filename") or "")
        if isinstance(row.get("v65_gold"), Mapping):
            sidecar["v65_gold"] = dict(row["v65_gold"])

    if not sidecar["doc_key"]:
        sidecar["doc_key"] = hashlib.sha256(blind_text.encode("utf-8")).hexdigest()[:16]

    v65_gold = sidecar["v65_gold"]
    sidecar["doc_date"] = v65_gold.get("doc_date")
    sidecar["event_date"] = v65_gold.get("event_date")
    sidecar["chamber"] = v65_gold.get("chamber")
    sidecar["committees"] = v65_gold.get("committees")
    return blind_text, sidecar


def _try_lazy_v65_migration(v65_status: str | None, v65_kind: str | None) -> tuple[str | None, str | None]:
    try:
        cw = importlib.import_module("congress_docmeta.v7.crosswalk")
        fn = getattr(cw, "migrate_v65_to_v7", None)
        if callable(fn):
            res = fn(v65_status or "usable", v65_kind)
            pg = res.primary_genre.value if res.primary_genre is not None else None
            sf = res.specialist_family.value if res.specialist_family is not None else None
            return pg, sf
    except Exception:
        pass
    if v65_status and v65_status != "usable":
        return None, None
    return V65_TO_V7_GENRE_MAP.get(str(v65_kind or ""), (None, None))


def load_ssot_rows(ssot_path: Path) -> list[dict[str, Any]]:
    """Load SSOT JSONL rows cleanly and extract blind text + sidecar metadata."""
    rows: list[dict[str, Any]] = []
    with ssot_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            blind_text, sidecar = extract_blind_text_from_ssot_row(raw)
            v65_gold = sidecar["v65_gold"]
            v65_kind = v65_gold.get("primary_kind")
            v65_status = v65_gold.get("status")
            mapped_genre, mapped_family = _try_lazy_v65_migration(v65_status, v65_kind)
            rows.append(
                {
                    "doc_key": sidecar["doc_key"],
                    "text": blind_text,
                    "filename": sidecar["filename"],
                    "ssot_split": sidecar["ssot_split"],
                    "source_batch": sidecar["source_batch"],
                    "stratum": sidecar["stratum"],
                    "v65_status": v65_status,
                    "v65_primary_kind": v65_kind,
                    "v7_target_genre": mapped_genre,
                    "v7_target_family": mapped_family,
                    "doc_date": sidecar["doc_date"],
                    "event_date": sidecar["event_date"],
                    "chamber": sidecar["chamber"],
                    "committees": sidecar["committees"],
                    "v65_gold": v65_gold,
                }
            )
    return rows


def stratify_pilot_sample(
    rows: Sequence[Mapping[str, Any]],
    *,
    limit: int = 100,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Deterministically stratify rows across V7 families & Cleanlab/Horizon 0 edge cases."""
    if limit <= 0 or not rows:
        return []
    if len(rows) <= limit:
        return [dict(r) for r in rows]

    def _sort_hash(r: Mapping[str, Any]) -> str:
        return hashlib.sha256(f"{seed}:{r.get('doc_key')}".encode("utf-8")).hexdigest()

    ordered = sorted((dict(r) for r in rows), key=_sort_hash)

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in ordered:
        fn = str(r.get("filename") or "")
        pk = str(r.get("v65_primary_kind") or "")
        st = str(r.get("v65_status") or "")
        fam = str(r.get("v7_target_family") or "")

        if pk == "multi_doc_packet":
            buckets["edge:multi_doc_packet"].append(r)
        elif pk == "slides_or_visual":
            buckets["edge:slides_or_visual"].append(r)
        elif "-TTF-" in fn and pk != "truth_in_testimony_disclosure":
            buckets["edge:ttf_slug_mismatch"].append(r)
        elif "-Wstate-" in fn and pk != "witness_statement":
            buckets["edge:wstate_slug_mismatch"].append(r)
        elif pk == "event_web_page":
            buckets["edge:event_web_page"].append(r)
        elif st != "usable" or pk == "error_or_non_document":
            buckets["edge:non_usable"].append(r)
        elif pk == "hearing_transcript":
            buckets["edge:hearing_transcript"].append(r)
        elif pk == "truth_in_testimony_disclosure":
            buckets["edge:truth_in_testimony"].append(r)
        elif fam:
            buckets[f"family:{fam}"].append(r)
        else:
            buckets["other"].append(r)

    bucket_order = [
        "edge:multi_doc_packet",
        "edge:slides_or_visual",
        "edge:ttf_slug_mismatch",
        "edge:wstate_slug_mismatch",
        "edge:event_web_page",
        "edge:hearing_transcript",
        "edge:truth_in_testimony",
        "edge:non_usable",
        "family:event_logistics",
        "family:testimony_bio_disclosure",
        "family:transcript_vote_attendance",
        "family:correspondence_qfr_oversight",
        "family:legislation_report_fiscal",
        "other",
    ]

    selected: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    cursors: dict[str, int] = defaultdict(int)

    while len(selected) < limit:
        progressed = False
        for bname in bucket_order:
            items = buckets.get(bname, [])
            cur = cursors[bname]
            while cur < len(items):
                cand = items[cur]
                cur += 1
                dk = str(cand["doc_key"])
                if dk not in seen_keys:
                    seen_keys.add(dk)
                    cand_copy = dict(cand)
                    cand_copy["pilot_stratum"] = bname
                    selected.append(cand_copy)
                    progressed = True
                    break
            cursors[bname] = cur
            if len(selected) >= limit:
                break
        if not progressed:
            break

    return selected


def render_core_triage_prompt(
    blind_text: str,
    codebook_version: str,
    *,
    doc_id: str = "doc",
) -> str:
    """Render blind text-only Core Triage prompt (delegates lazily to `v7.codebook` if available)."""
    try:
        cb = importlib.import_module("congress_docmeta.v7.codebook")
        fn = getattr(cb, "render_core_prompt", None)
        if callable(fn):
            return str(fn(blind_text, doc_id))
    except Exception:
        pass
    return (
        f"You are labeling Congressional archive documents under DocMeta {codebook_version}.\n"
        "Judge strictly from the verbatim Document Text below. Do NOT guess unseen dates, "
        "people, acronyms, or metadata.\n"
        "Rules:\n"
        "- If status != 'usable', set primary_genre = null and specialist_family = null.\n"
        "- media_format is orthogonal ('prose'|'slides'|'web_page'|'table_or_form').\n"
        "- is_packet is orthogonal (true when document bundles multiple distinct sub-documents).\n"
        "- date_spans must be SpanRef objects copied verbatim from Document Text.\n"
        "- verbatim_title must appear verbatim in Document Text or be null.\n\n"
        "<<<DOC_TEXT>>>\n"
        f"{blind_text}\n"
        "<<<END_DOC_TEXT>>>"
    )


def render_specialist_prompt(
    blind_text: str,
    specialist_family: str,
    primary_genre: str,
    codebook_version: str,
    *,
    core_result: Mapping[str, Any] | None = None,
) -> str:
    """Render blind text-only Specialist extractor prompt (delegates lazily to `v7.codebook` if available)."""
    try:
        cb = importlib.import_module("congress_docmeta.v7.codebook")
        fn = getattr(cb, "render_specialist_prompt", None)
        if callable(fn) and core_result is not None:
            return str(fn(specialist_family, blind_text, dict(core_result)))
    except Exception:
        pass
    return (
        f"Extract DocMeta {codebook_version} specialist fields for family='{specialist_family}' "
        f"(primary_genre='{primary_genre}').\n"
        "Strict Grounding Rules:\n"
        "- Every person name (personas, members_present, staff_present, witnesses, senders, recipients, "
        "sponsors_or_offerors) and issuer_org MUST appear verbatim in Document Text.\n"
        "- Every SpanRef {'quote', 'start', 'end'} must satisfy 0 <= start < end <= len(text) "
        "and match text[start:end] verbatim.\n"
        "- Omit/abstain (null or []) when absent from Document Text.\n\n"
        "<<<DOC_TEXT>>>\n"
        f"{blind_text}\n"
        "<<<END_DOC_TEXT>>>"
    )


def _extract_text_from_prompt(prompt: str) -> str:
    start_marker = "<<<DOC_TEXT>>>\n"
    end_marker = "\n<<<END_DOC_TEXT>>>"
    s_idx = prompt.find(start_marker)
    if s_idx >= 0:
        rest = prompt[s_idx + len(start_marker) :]
        e_idx = rest.rfind(end_marker)
        return rest[:e_idx] if e_idx >= 0 else rest
    marker = "Document Text:\n"
    idx = prompt.find(marker)
    return prompt[idx + len(marker) :] if idx >= 0 else prompt


def _deterministic_dry_run_triage(blind_text: str) -> dict[str, Any]:
    """Text-only deterministic Core Triage classifier compliant with `CoreEnvelopeExtraction`."""
    lower = blind_text.casefold()
    stripped = blind_text.strip()
    if not stripped or len(stripped) < 25:
        status = "stub_or_blank"
    elif any(k in lower for k in ("403 forbidden", "access denied", "cloudflare", "404 not found")):
        status = "error_or_block"
    elif stripped.startswith("<?xml") or "<mods" in lower[:200]:
        status = "catalog_xml"
    else:
        status = "usable"

    if status != "usable":
        return {
            "rationale": f"Non-usable document classified as {status}.",
            "status": status,
            "media_format": None,
            "is_packet": False,
            "contains_genres": [],
            "primary_genre": None,
            "specialist_family": None,
            "subkind": None,
            "verbatim_title": None,
            "title_span": None,
            "doc_date": None,
            "date_spans": [],
            "chamber": None,
            "congress": None,
            "committees": [],
            "subcommittees": [],
            "gist": None,
            "topics": [],
        }

    if any(k in lower for k in ("skip to main content", "breadcrumbs", "home >", "navigation", "open in new window")):
        media_format = "web_page"
    elif "slide 1" in lower or "this presentation is for" in lower or (blind_text.count("•") >= 5 and len(blind_text) < 2500):
        media_format = "slides"
    elif any(k in lower for k in ("checkbox", "yes [", "no [", "rule xi", "truth in testimony")):
        media_format = "table_or_form"
    else:
        media_format = "prose"

    is_packet = any(
        k in lower
        for k in (
            "table of contents",
            "table of exhibits",
            "document 1:",
            "document 2:",
            "exhibit 1:",
            "exhibit 2:",
            "exhibit a",
            "exhibit b",
        )
    )

    if "notice of appearance" in lower or any(k in lower for k in ("you are invited to testify", "dear ", "sincerely,")):
        genre = "oversight_or_committee_letter"
    elif "truth in testimony" in lower[:400] or "clause 2(g)" in lower[:400]:
        genre = "truth_in_testimony"
    elif "questions for the record" in lower or ("question 1" in lower and "response" in lower):
        genre = "qfr_correspondence"
    elif any(k in lower for k in ("the committee met", "came to order", "rptr ", "edtr ")):
        genre = "hearing_transcript"
    elif any(k in lower for k in ("roll call", "yeas", "nays", "ordered reported", "recorded vote", "resolved,")):
        genre = "committee_vote_or_action"
    elif "hearing memorandum" in lower or "briefing memo" in lower or "witness list" in lower:
        genre = "hearing_memo_or_witness_list"
    elif "notice of hearing" in lower or "notice of markup" in lower or ("full committee hearing" in lower and "location:" in lower):
        genre = "hearing_or_markup_notice"
    elif "biography" in lower or "biographical" in lower:
        genre = "witness_biography"
    elif "opening statement" in lower or "statement of chairman" in lower or "statement of rep." in lower:
        genre = "member_statement"
    elif "be it enacted" in lower or "amendment to" in lower or "section-by-section" in lower:
        genre = "bill_or_amendment"
    elif any(k in lower for k in ("written statement", "testimony of", "thank you for the opportunity", "thank you for inviting me")):
        genre = "witness_testimony"
    elif any(k in lower for k in ("cost estimate", "fiscal year", "budget views")):
        genre = "budget_or_cost_estimate"
    else:
        genre = "committee_or_agency_report"

    spec_family = GENRE_TO_SPECIALIST_FAMILY.get(genre, "legislation_report_fiscal")

    lines = [ln.strip() for ln in blind_text.splitlines() if ln.strip()]
    verbatim_title = None
    title_span = None
    if lines:
        cand = lines[0][:120]
        pos = blind_text.find(cand)
        if pos >= 0 and len(cand) >= 4:
            verbatim_title = cand
            title_span = {"quote": cand, "start": pos, "end": pos + len(cand)}

    date_spans: list[dict[str, Any]] = []
    for m in re.finditer(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b",
        blind_text,
    ):
        date_spans.append({"quote": m.group(0), "start": m.start(), "end": m.end()})
        if len(date_spans) >= 3:
            break

    chamber = None
    if "house of representatives" in lower:
        chamber = "house"
    elif "senate" in lower:
        chamber = "senate"

    return {
        "rationale": f"Blind text signals match {genre} ({media_format})."[:280],
        "status": "usable",
        "media_format": media_format,
        "is_packet": is_packet,
        "contains_genres": [genre] if is_packet else [],
        "primary_genre": genre,
        "specialist_family": spec_family,
        "subkind": None,
        "verbatim_title": verbatim_title,
        "title_span": title_span,
        "doc_date": None,
        "date_spans": date_spans,
        "chamber": chamber,
        "congress": None,
        "committees": [],
        "subcommittees": [],
        "gist": None,
        "topics": [],
    }


def _deterministic_dry_run_specialist(blind_text: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    title = str(schema.get("title") or "")
    lines = [ln.strip() for ln in blind_text.splitlines() if ln.strip()]
    first_span = None
    if lines:
        snippet = lines[0][:80]
        idx = blind_text.find(snippet)
        if idx >= 0 and snippet:
            first_span = {"quote": snippet, "start": idx, "end": idx + len(snippet)}

    if "EventLogistics" in title:
        ev_title = first_span["quote"] if first_span else None
        return {
            "rationale": "Extracted grounded event logistics from blind text.",
            "event_type": "hearing",
            "event_title": ev_title,
            "event_title_span": first_span,
            "event_date": None,
            "event_date_span": None,
            "event_time": None,
            "venue_kind": None,
            "venue": None,
            "venue_span": None,
            "witnesses": [],
            "due_date": None,
            "bill_refs": [],
        }
    if "TestimonyBioDisclosure" in title:
        return {
            "rationale": "Extracted testimony/bio/disclosure fields from blind text.",
            "personas": [],
            "issuer_org": None,
            "issuer_org_span": None,
            "disclosure_has_grants_or_contracts": True if "federal grant" in blind_text.casefold() else None,
            "disclosure_amounts": [],
            "disclosure_spans": [],
            "prior_roles": [],
            "education": [],
            "event_title": None,
            "event_date": None,
            "bill_refs": [],
        }
    if "TranscriptVoteAttendance" in title:
        return {
            "rationale": "Extracted transcript/vote attendance fields from blind text.",
            "event_type": None,
            "event_title": first_span["quote"] if first_span else None,
            "event_title_span": first_span,
            "event_date": None,
            "venue": None,
            "presiding_or_witnesses": [],
            "members_present": [],
            "members_present_spans": [],
            "staff_present": [],
            "staff_present_spans": [],
            "action_summary": None,
            "vote_tallies": [],
            "bill_refs": [],
        }
    if "CorrespondenceQfrOversight" in title:
        return {
            "rationale": "Extracted correspondence/QFR/oversight fields from blind text.",
            "correspondence_direction": None,
            "senders": [],
            "recipients": [],
            "issuer_org": None,
            "issuer_org_span": None,
            "signatory_count": None,
            "due_date": None,
            "due_date_span": None,
            "subpoena_or_compelled": "subpoena" in blind_text.casefold(),
            "bill_refs": [],
        }
    return {
        "rationale": "Extracted legislative/report/fiscal fields from blind text.",
        "short_titles": [],
        "short_title_spans": [],
        "issuer_org": None,
        "issuer_org_span": None,
        "sponsors_or_offerors": [],
        "fiscal_years": [],
        "bill_refs": [],
        "statute_or_rule_refs": [],
        "action_summary": None,
    }


def build_dry_run_adapters(families: Sequence[str]) -> dict[str, Callable[..., Any]]:
    """Build deterministic offline mock adapters for `--dry-run` pipeline verification."""
    adapters: dict[str, Callable[..., Any]] = {}
    for fam in families:
        def _make_adapter(family_name: str) -> Callable[..., Any]:
            def _adapter(
                prompt: str,
                schema: dict[str, Any],
                *,
                model_id: str = "",
                timeout_s: float = 30.0,
                rollout_id: int = 0,
            ) -> dict[str, Any]:
                del model_id, timeout_s, rollout_id
                blind_text = _extract_text_from_prompt(prompt)
                title = str(schema.get("title") or "")
                if "Core" in title or "primary_genre" in schema.get("properties", {}):
                    return _deterministic_dry_run_triage(blind_text)
                return _deterministic_dry_run_specialist(blind_text, schema)

            _adapter.__name__ = f"dry_run_{family_name}"
            return _adapter

        adapters[fam] = _make_adapter(fam)
    return adapters


def _parse_and_validate(
    raw_text: str,
    blind_text: str,
    *,
    model_cls: Any = None,
) -> dict[str, Any]:
    _, payload = extract_json_payload(raw_text)
    if payload is None:
        raise ValueError("Could not extract JSON object from model output")
    repaired = repair_span_refs_in_payload(blind_text, payload)
    if isinstance(repaired.get("rationale"), str) and len(repaired["rationale"]) > 480:
        repaired["rationale"] = repaired["rationale"][:477].rstrip() + "..."
    if model_cls is not None and hasattr(model_cls, "model_validate"):
        validated = model_cls.model_validate(repaired)
        return validated.model_dump(mode="json")
    return repaired


_LIVE_CHECKEVAL_SCHEMA: dict[str, Any] = {
    "title": "CheckEvalVerdict",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "qid": {"type": "string"},
                    "answer": {"type": "boolean"},
                    "evidence_quote": {"type": ["string", "null"]},
                },
                "required": ["qid", "answer", "evidence_quote"],
            },
        },
        "winner": {
            "type": ["string", "null"],
            "enum": ["majority", "minority", "ambiguous", None],
        },
    },
    "required": ["answers", "winner"],
}


def build_live_sota_checkeval_fn(
    cache: SixTupleCache,
    codebook_version: str,
    runner_config: RunnerConfig,
    *,
    arbiter_family: str = "claude",
) -> Callable[..., Any]:
    """Return a cached live SOTA binary-checklist arbiter for 2-vs-1 splits."""
    from .runners import run_family_with_cache

    def _arbiter(
        text: str,
        questions: Sequence[Any],
        sides: Mapping[str, Any],
        candidates: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        del candidates
        q_lines = "\n".join(
            f"- {q.qid} (favors={q.favors_side}, dimension={q.dimension}): {q.question}"
            for q in questions
        )
        prompt = (
            f"You are an evidence-locked binary checklist arbiter (DocMeta {codebook_version}).\n"
            f"Sides in dispute: majority={sides.get('majority')} vs minority={sides.get('minority')}.\n"
            "Answer each atomic Yes/No question strictly from Document Text below.\n"
            "For every True answer (and any decisive negative), provide a verbatim exact `evidence_quote` "
            "substring copied directly from Document Text. Never guess or rely on filenames.\n\n"
            f"Checklist Questions:\n{q_lines}\n\n"
            f"<<<DOC_TEXT>>>\n{text}\n<<<END_DOC_TEXT>>>"
        )
        res = run_family_with_cache(
            family=arbiter_family,
            input_text=text,
            prompt_text=prompt,
            schema=_LIVE_CHECKEVAL_SCHEMA,
            codebook_version=codebook_version,
            cache=cache,
            config=runner_config,
            slice_spec=f"blind_text_only:checkeval:{sides.get('majority')}:{sides.get('minority')}",
            stage="checkeval_arbiter",
        )
        if not res.ok or res.parsed is None:
            return {"answers": [], "winner": "ambiguous"}
        return res.parsed

    return _arbiter


def _process_single_doc(
    row: Mapping[str, Any],
    *,
    families: Sequence[str],
    codebook_version: str,
    core_schema: dict[str, Any],
    specialist_schemas: Mapping[str, dict[str, Any]],
    core_model_cls: Any,
    specialist_model_classes: Mapping[str, Any],
    cache: SixTupleCache,
    runner_config: RunnerConfig,
    adapters: Mapping[str, Callable[..., Any]] | None,
    skip_specialist: bool,
    check_eval_fn: Callable[..., Any] | None,
    specialist_families: Sequence[str] | None = None,
) -> dict[str, Any]:
    doc_key = str(row["doc_key"])
    blind_text = str(row["text"])

    core_prompt = render_core_triage_prompt(blind_text, codebook_version, doc_id=doc_key)

    core_runs: dict[str, FamilyRunResult] = run_three_family_parallel(
        input_text=blind_text,
        prompt_text=core_prompt,
        schema=core_schema,
        codebook_version=codebook_version,
        cache=cache,
        families=families,
        config=runner_config,
        slice_spec="blind_text_only:core_triage",
        stage="core_triage",
        parse_fn=lambda raw: _parse_and_validate(raw, blind_text, model_cls=core_model_cls),
        adapters=adapters,
    )

    decision: ConsensusDecision = adjudicate_three_family(
        blind_text,
        core_runs,
        doc_key=doc_key,
        check_eval_fn=check_eval_fn,
    )

    specialist_runs: dict[str, FamilyRunResult] = {}
    final_gold: dict[str, Any] | None = None
    specialist_fields: dict[str, Any] | None = None

    if decision.verdict in {"auto_accept_gold", "checkeval_resolved"} and decision.accepted_payload is not None:
        final_gold = dict(decision.accepted_payload)
        accepted_status = final_gold.get("status")
        accepted_genre = final_gold.get("primary_genre")
        spec_family = final_gold.get("specialist_family") or GENRE_TO_SPECIALIST_FAMILY.get(
            str(accepted_genre or "")
        )

        if (
            not skip_specialist
            and accepted_status == "usable"
            and spec_family
            and spec_family in specialist_schemas
        ):
            spec_schema = specialist_schemas[spec_family]
            spec_cls = specialist_model_classes.get(spec_family)
            spec_prompt = render_specialist_prompt(
                blind_text,
                spec_family,
                str(accepted_genre or ""),
                codebook_version,
                core_result=final_gold,
            )

            active_spec_families = tuple(specialist_families) if specialist_families else tuple(families)
            specialist_runs = run_three_family_parallel(
                input_text=blind_text,
                prompt_text=spec_prompt,
                schema=spec_schema,
                codebook_version=codebook_version,
                cache=cache,
                families=active_spec_families,
                config=runner_config,
                slice_spec=f"blind_text_only:specialist:{spec_family}",
                stage=f"specialist:{spec_family}",
                parse_fn=lambda raw: _parse_and_validate(raw, blind_text, model_cls=spec_cls),
                adapters=adapters,
            )
            grounded_spec_payloads = [
                r.parsed
                for r in specialist_runs.values()
                if r.ok and r.parsed is not None and verify_span_grounding(blind_text, r.parsed).passed
            ]
            if grounded_spec_payloads:
                specialist_fields = merge_consensus_payload(blind_text, grounded_spec_payloads)

    return {
        "row": dict(row),
        "core_runs": core_runs,
        "decision": decision,
        "specialist_runs": specialist_runs,
        "final_gold": final_gold,
        "specialist_fields": specialist_fields,
    }


def run_pilot(
    *,
    ssot_path: Path | None = None,
    out_dir: Path | None = None,
    cache_path: Path | None = None,
    limit: int = 100,
    workers: int = 3,
    families: Sequence[str] = ("claude", "codex", "gemini"),
    timeout_s: float = 120.0,
    dry_run: bool = False,
    skip_specialist: bool = False,
    codebook_version: str | None = None,
    claude_model: str | None = None,
    codex_model: str | None = None,
    codex_reasoning_effort: str | None = None,
    gemini_model: str | None = None,
    live_checkeval: bool | None = None,
    adapters: Mapping[str, Callable[..., Any]] | None = None,
    check_eval_fn: Callable[..., Any] | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """Execute the stratified V7.2 3-family pilot and write summary, gold, and deadlock artifacts."""
    resolved_ssot = Path(ssot_path) if ssot_path is not None else default_ssot_path()
    resolved_out = Path(out_dir) if out_dir is not None else default_out_dir()
    resolved_out.mkdir(parents=True, exist_ok=True)

    resolved_cache = (
        Path(cache_path)
        if cache_path is not None
        else (resolved_out / "dry_run_cache.sqlite" if dry_run else default_cache_path())
    )

    cb_ver, core_schema, specialist_schemas, core_cls, spec_clses = _resolve_v7_runtime_specs(codebook_version)
    all_rows = load_ssot_rows(resolved_ssot)
    sampled_rows = stratify_pilot_sample(all_rows, limit=limit, seed=seed)

    active_adapters = adapters if adapters is not None else (build_dry_run_adapters(families) if dry_run else None)
    runner_cfg_kwargs: dict[str, Any] = {
        "timeout_s": timeout_s,
        "max_workers": max(1, len(families)),
    }
    if claude_model:
        runner_cfg_kwargs["claude_model"] = claude_model
    if codex_model:
        runner_cfg_kwargs["codex_model"] = codex_model
    if codex_reasoning_effort:
        runner_cfg_kwargs["codex_reasoning_effort"] = codex_reasoning_effort
    if gemini_model:
        runner_cfg_kwargs["gemini_model"] = gemini_model
    runner_cfg = RunnerConfig(**runner_cfg_kwargs)

    use_live_ce = (not dry_run and adapters is None) if live_checkeval is None else bool(live_checkeval)

    processed: list[dict[str, Any]] = []
    with SixTupleCache(resolved_cache) as cache:
        effective_check_eval = check_eval_fn
        if effective_check_eval is None and use_live_ce:
            arb_fam = "claude" if "claude" in families else families[0]
            effective_check_eval = build_live_sota_checkeval_fn(
                cache, cb_ver, runner_cfg, arbiter_family=arb_fam
            )
        doc_workers = max(1, workers)
        total_sampled = len(sampled_rows)
        if doc_workers == 1 or total_sampled <= 1:
            for idx, row in enumerate(sampled_rows, start=1):
                item = _process_single_doc(
                    row,
                    families=families,
                    codebook_version=cb_ver,
                    core_schema=core_schema,
                    specialist_schemas=specialist_schemas,
                    core_model_cls=core_cls,
                    specialist_model_classes=spec_clses,
                    cache=cache,
                    runner_config=runner_cfg,
                    adapters=active_adapters,
                    skip_specialist=skip_specialist,
                    check_eval_fn=effective_check_eval,
                )
                processed.append(item)
                print(
                    f"[pilot] {idx}/{total_sampled} doc={item['row']['doc_key'][:12]} verdict={item['decision'].verdict}",
                    file=sys.stderr,
                    flush=True,
                )
        else:
            ordered_results: dict[int, dict[str, Any]] = {}
            with ThreadPoolExecutor(max_workers=doc_workers) as pool:
                fut_map = {
                    pool.submit(
                        _process_single_doc,
                        row,
                        families=families,
                        codebook_version=cb_ver,
                        core_schema=core_schema,
                        specialist_schemas=specialist_schemas,
                        core_model_cls=core_cls,
                        specialist_model_classes=spec_clses,
                        cache=cache,
                        runner_config=runner_cfg,
                        adapters=active_adapters,
                        skip_specialist=skip_specialist,
                        check_eval_fn=effective_check_eval,
                    ): idx
                    for idx, row in enumerate(sampled_rows)
                }
                done_count = 0
                for fut in as_completed(fut_map):
                    item = fut.result()
                    ordered_results[fut_map[fut]] = item
                    done_count += 1
                    print(
                        f"[pilot] {done_count}/{total_sampled} doc={item['row']['doc_key'][:12]} verdict={item['decision'].verdict}",
                        file=sys.stderr,
                        flush=True,
                    )
            processed = [ordered_results[i] for i in range(total_sampled)]

        cache_stats = cache.stats()

    verdict_counts: Counter[str] = Counter()
    grounding_fail_counts: Counter[str] = Counter()
    gold_candidates: list[dict[str, Any]] = []
    deadlocks: list[ConsensusDecision] = []

    family_genre_preds: dict[str, list[str]] = {f: [] for f in families}
    consensus_genre_labels: list[str] = []
    split_input_docs: list[dict[str, Any]] = []

    for item in processed:
        row = item["row"]
        decision: ConsensusDecision = item["decision"]
        verdict_counts[decision.verdict] += 1

        for fam, gr in decision.grounding_by_family.items():
            if not gr.passed:
                grounding_fail_counts[fam] += 1

        if decision.verdict == "deadlock_needs_owner":
            deadlocks.append(decision)
        elif item["final_gold"] is not None:
            gold_rec = {
                "doc_key": row["doc_key"],
                "pilot_stratum": row.get("pilot_stratum"),
                "verdict": decision.verdict,
                "consensus_families": decision.consensus_families,
                "gold": item["final_gold"],
                "specialist_fields": item.get("specialist_fields"),
                "v65_primary_kind": row.get("v65_primary_kind"),
                "v7_target_genre": row.get("v7_target_genre"),
            }
            gold_candidates.append(gold_rec)

        for fam in families:
            tup = decision.family_tuples.get(fam)
            lbl = (tup[3] if tup and tup[0] == "usable" else f"STATUS:{tup[0]}") if tup else "MISSING"
            family_genre_preds[fam].append(str(lbl))
        if decision.accepted_tuple is not None:
            acc = decision.accepted_tuple
            cons_lbl = acc[3] if acc[0] == "usable" else f"STATUS:{acc[0]}"
        else:
            cons_lbl = "DEADLOCK"
        consensus_genre_labels.append(str(cons_lbl))

        split_input_docs.append(
            {
                "doc_key": row["doc_key"],
                "text": row["text"],
                "filename": row["filename"],
                "doc_date": row.get("doc_date"),
                "event_date": row.get("event_date"),
                "chamber": row.get("chamber"),
                "committees": row.get("committees"),
            }
        )

    pairwise_metrics: dict[str, Any] = {}
    for i, fa in enumerate(families):
        for fb in families[i + 1 :]:
            pairwise_metrics[f"{fa}_vs_{fb}"] = compute_agreement_metrics(
                family_genre_preds[fa], family_genre_preds[fb]
            )
    family_vs_consensus_metrics: dict[str, Any] = {
        fam: compute_agreement_metrics(consensus_genre_labels, family_genre_preds[fam])
        for fam in families
    }

    split_result = build_event_temporal_splits(split_input_docs)
    eval_docs = split_result.splits["dev_iter"] + split_result.splits["sealed_temporal_2026"]
    decontam_report = audit_decontamination(split_result.splits["train"], eval_docs)
    cf_report = run_counterfactual_suite()

    total_docs = len(processed)
    resolved_cnt = verdict_counts["auto_accept_gold"] + verdict_counts["checkeval_resolved"]
    consensus_rate = (resolved_cnt / total_docs) if total_docs else 0.0

    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "codebook_version": cb_ver,
        "dry_run": dry_run,
        "ssot_path": str(resolved_ssot),
        "families": list(families),
        "total_docs": total_docs,
        "verdict_counts": dict(verdict_counts),
        "consensus_resolved_rate": round(consensus_rate, 4),
        "auto_accept_rate": round((verdict_counts["auto_accept_gold"] / total_docs) if total_docs else 0.0, 4),
        "checkeval_resolved_rate": round((verdict_counts["checkeval_resolved"] / total_docs) if total_docs else 0.0, 4),
        "deadlock_rate": round((verdict_counts["deadlock_needs_owner"] / total_docs) if total_docs else 0.0, 4),
        "grounding_fail_counts": dict(grounding_fail_counts),
        "strata_counts": dict(Counter(str(r.get("pilot_stratum") or "") for r in sampled_rows)),
        "pairwise_agreement": pairwise_metrics,
        "family_vs_consensus_agreement": family_vs_consensus_metrics,
        "splits": {
            "counts": split_result.counts,
            "temporal_cutoff": split_result.temporal_cutoff,
        },
        "decontamination": decontam_report.to_dict(),
        "counterfactual_suite": cf_report.to_dict(),
        "cache_stats": cache_stats,
    }

    summary_path = resolved_out / "pilot_summary.json"
    gold_path = resolved_out / "gold_candidates.jsonl"
    deadlock_path = resolved_out / "deadlocks_for_owner.md"

    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    with gold_path.open("w", encoding="utf-8") as fh:
        for rec in gold_candidates:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    deadlock_path.write_text(format_deadlock_digest(deadlocks), encoding="utf-8")

    return {
        "summary": summary,
        "summary_path": str(summary_path),
        "gold_candidates_path": str(gold_path),
        "deadlocks_path": str(deadlock_path),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run DocMeta V7.2 3-family stratified labeling pilot.")
    p.add_argument("--limit", type=int, default=100, help="Number of stratified SSOT docs to run (default: 100)")
    p.add_argument("--workers", type=int, default=3, help="Concurrent document workers (default: 3)")
    p.add_argument(
        "--families",
        type=str,
        default="claude,codex,gemini",
        help="Comma-separated model families (default: claude,codex,gemini)",
    )
    p.add_argument("--out-dir", type=Path, default=None, help="Output artifact directory")
    p.add_argument("--ssot-path", type=Path, default=None, help="Path to docmeta_gold_v6_5.jsonl")
    p.add_argument("--cache-path", type=Path, default=None, help="Optional override path for SixTupleCache SQLite")
    p.add_argument("--codebook-version", type=str, default=None, help="Override codebook version string")
    p.add_argument("--claude-model", type=str, default=None, help="Override Claude CLI model")
    p.add_argument("--codex-model", type=str, default=None, help="Override Codex CLI model")
    p.add_argument("--codex-reasoning", type=str, default=None, help="Override Codex reasoning effort (low|medium|high)")
    p.add_argument("--gemini-model", type=str, default=None, help="Override Antigravity Gemini model")
    p.add_argument("--no-live-checkeval", action="store_true", help="Disable live SOTA CheckEval arbiter on 2-vs-1 splits")
    p.add_argument("--timeout", type=float, default=120.0, help="Per-CLI invocation timeout in seconds")
    p.add_argument("--skip-specialist", action="store_true", help="Skip Stage 2 specialist extraction")
    p.add_argument("--dry-run", action="store_true", help="Run full pipeline with deterministic offline mock adapters")
    p.add_argument("--seed", type=int, default=42, help="Deterministic stratification seed")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    families = [f.strip() for f in args.families.split(",") if f.strip()]
    result = run_pilot(
        ssot_path=args.ssot_path,
        out_dir=args.out_dir,
        cache_path=args.cache_path,
        limit=args.limit,
        workers=args.workers,
        families=families,
        timeout_s=args.timeout,
        dry_run=args.dry_run,
        skip_specialist=args.skip_specialist,
        codebook_version=args.codebook_version,
        claude_model=args.claude_model,
        codex_model=args.codex_model,
        codex_reasoning_effort=args.codex_reasoning,
        gemini_model=args.gemini_model,
        live_checkeval=False if args.no_live_checkeval else None,
        seed=args.seed,
    )
    print(json.dumps({"summary": result["summary"], "paths": {k: v for k, v in result.items() if k.endswith("_path")}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CORE_TRIAGE_SCHEMA",
    "DEFAULT_CODEBOOK_VERSION",
    "GENRE_TO_SPECIALIST_FAMILY",
    "SPECIALIST_SCHEMAS",
    "V65_TO_V7_GENRE_MAP",
    "build_dry_run_adapters",
    "build_live_sota_checkeval_fn",
    "default_out_dir",
    "default_ssot_path",
    "extract_blind_text_from_ssot_row",
    "load_ssot_rows",
    "main",
    "render_core_triage_prompt",
    "render_specialist_prompt",
    "run_pilot",
    "stratify_pilot_sample",
]
