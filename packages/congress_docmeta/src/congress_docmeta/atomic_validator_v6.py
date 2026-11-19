#!/usr/bin/env python3
"""Post-LLM Atomic `Noul` Output Validator & Teacher Escalation Gate (`atomic_validator_v6.py`).

100% Python stdlib at module import time (`/usr/bin/python3 -B -I -S` clean).
Heavy runtime dependencies (`numpy`, `mlx`, `tokenizers`) are lazy-loaded only when
`AtomicOutputValidatorV6` initializes a neural backend (`"laya-ane"`, `"kev-0.8b"`, or `"both"`).

Validates candidate `DocMetaV4Causal` JSON outputs via focused atomic `Noul` checks:
  1. `q1_kind_valid`:      Does `primary_kind` match the document excerpt (skipped if grammar-locked)?
  2. `q2_committee_valid`: Are predicted `committees` grounded in excerpt/slug/metadata?
  3. `q3_summary_valid`:   Do `composed_title` + `gist` name the right lead actor/committee & topic?
  4. `q4_genre_valid`:     Genre-conditional check (`correspondence_flow` direction on letters/QFRs,
                           `action_summary` tally/polarity on votes/estimates, `disclosure` on TTFs).
  5. `q_actors_complete` & `q_persona_valid`: Full-roster actor omission + per-persona `(name, role, entity_type)` check.

Apple Silicon M4 Pro Roofline Optimizations:
  - `"laya-ane"`: `Laya-Typed-421M` (`W8A16` `S=256` & `S=512`, `[1585, 0, 0]` ANE/GPU/CPU ops, `0` GPU contention)
                  with lock-aware & `V0`-gated redundant-question skipping (`~75 ms/doc` on ANE) and
                  split `run_stage1_ane` / `finish_stage2` hooks for async overlap behind `Gemma-4` GPU decode.
  - `"kev-0.8b"`: Lossless `8-bit` (`g64`, `~764 MB`) + `@mx.compile` + left-padded `B=8` cross-document
                  batched prefill & branch scoring (`~35–48 ms/doc` on Metal MLX, `cos >= 0.999` vs `B=1` `BF16`).
  - `"both"`:     Two-sided gray-zone cascade (`< 0.22` accept on ANE, `> 0.62` escalate on ANE, `0.22..0.62`
                  batched `W8` `Kev-0.8B` on Metal MLX -> `~7–15 ms/doc` average GPU time).
"""

from __future__ import annotations

import ctypes
from functools import partial
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
from typing import Any, Literal, Mapping, Sequence

from .anomaly_router_v6 import (
    ACTOR_REQUIRED_KINDS_V6,
    check_gist_title_grounding_v6,
    score_atomic_stdlib_v6,
    surname_token_v6,
)

ValidatorMode = Literal["laya-ane", "kev-0.8b", "both"]

_WS_RE = re.compile(r"\s+")

_CORRESPONDENCE_CHECK_KINDS_V6 = frozenset(
    {
        "oversight_letter",
        "witness_invitation",
        "nomination_or_support_letter",
        "external_submission_letter",
        "public_comment_or_submission",
        "qfr_request",
        "qfr_response",
        "investigative_exhibit",
    }
)
_ACTION_SUMMARY_CHECK_KINDS_V6 = frozenset(
    {"committee_vote", "meeting_results", "revenue_or_cost_estimate"}
)

CFLOW_DESC_V6: dict[str, str] = {
    "committee_to_witness": "sent from a congressional committee to a hearing witness (invitation or QFR request)",
    "witness_to_committee": "sent from a witness to a congressional committee (QFR answers or follow-up)",
    "congress_to_agency": "sent from Members/committee of Congress to a federal agency or executive official",
    "agency_to_congress": "sent from a federal agency or executive official responding/reporting to Congress",
    "member_to_committee": "sent from a Member of Congress to a committee chair/ranking member",
    "committee_to_member": "sent from a committee chair/staff to committee members",
    "external_to_committee": "sent from an outside organization, company, coalition, or citizen to a committee",
    "foreign_gov_to_congress": "sent from a foreign government or embassy to Congress",
    "internal_exhibit_chain": "internal corporate or agency email/message chain produced as an exhibit",
}

ALL_KIND_DESC_V6: dict[str, str] = {
    "hearing_transcript": "full verbatim Q&A hearing or meeting transcript",
    "witness_statement": "prepared written testimony or statement of a witness",
    "member_opening_statement": "committee chair, ranking member, or member opening statement at a hearing/markup",
    "member_or_floor_statement": "floor speech, Congressional Record statement, or standalone member remarks",
    "truth_in_testimony_disclosure": "witness Truth-in-Testimony financial/grant/foreign-payment disclosure form",
    "witness_biography": "witness curriculum vitae (CV), resume, or biographical sketch",
    "witness_list": "list of scheduled witnesses/panels for a hearing",
    "member_roster": "standing committee or subcommittee membership list",
    "attendance_quorum_sheet": "committee attendance or quorum tally sheet",
    "qfr_request": "Questions for the Record (QFRs) sent from members to a witness without answers",
    "qfr_response": "witness or agency written responses/answers to Questions for the Record (QFRs)",
    "nominee_questionnaire_apq": "executive/judicial nominee biographical questionnaire or APQs",
    "hearing_notice": "public announcement or notice scheduling a hearing (date, time, room)",
    "markup_notice": "notice scheduling a committee markup or business meeting on bills/resolutions",
    "hearing_memo_or_charter": "staff background memorandum or hearing charter explaining hearing issues",
    "meeting_results": "summary list of actions/outcomes taken at a markup or business meeting",
    "committee_vote": "committee roll-call vote tally sheet recording Yeas and Nays",
    "legislative_schedule_or_calendar": "committee calendar or legislative floor/committee schedule",
    "event_web_page": "committee website event landing page listing hearing details/links",
    "bill_or_draft": "full bill text, discussion draft, chair's mark, or joint/concurrent resolution",
    "committee_amendment": "amendment text offered in committee (e.g., strike line X and insert, ANS)",
    "comparative_print": "Ramseyer / Cordon comparative print showing statutory changes",
    "section_by_section": "section-by-section summary or analysis of a bill or division",
    "committee_report": "formal numbered House/Senate committee report accompanying legislation or activity",
    "explanatory_statement": "joint explanatory statement or managers' statement on appropriations/bills",
    "committee_resolution": "internal committee resolution (funding, subpoena authorization, rules)",
    "committee_rules": "adopted rules of procedure of a congressional committee",
    "oversight_plan": "committee biennial oversight and authorization plan",
    "budget_views_and_estimates": "committee Views and Estimates letter/report to the Budget Committee",
    "revenue_or_cost_estimate": "CBO cost estimate or JCT revenue score/table for legislation",
    "treaty_document": "presidential treaty transmittal or Senate Treaty Document",
    "agency_or_gao_crs_report": "federal agency, GAO, CRS, CBO, or Inspector General report/study",
    "external_report_or_whitepaper": "non-government research report, academic study, or whitepaper",
    "gsa_prospectus_or_property": "GSA capital investment, lease, or courthouse building prospectus",
    "oversight_letter": "congressional letter requesting information/action from an agency or company, or agency reply",
    "witness_invitation": "committee letter inviting a witness to testify at a hearing",
    "nomination_or_support_letter": "letter endorsing or opposing a nominee or legislation",
    "external_submission_letter": "letter for the record submitted by an outside group, coalition, or official",
    "public_comment_or_submission": "public comment filing or stakeholder statement for the record",
    "investigative_exhibit": "internal email chain, chat log, memo, or document produced as an investigative exhibit",
    "legal_or_investigative_filing": "court filing, subpoena, deposition, affidavit, or regulatory petition",
    "news_clip_or_article": "newspaper, magazine, or online journalism article entered into the record",
    "press_release_or_fact_sheet": "press release, media advisory, or one-page fact sheet",
    "slides_or_visual": "presentation slide deck, chart, infographic, or map",
    "multi_doc_packet": "compiled multi-document bundle or appendix packet",
    "error_or_non_document": "404/403 error page, blank stub, or non-document wrapper",
    "other": "document not fitting any other category",
}

CONFUSABLE_ALTS_V6: dict[str, str] = {
    "witness_statement": "qfr_response (written Q&A answers), truth_in_testimony_disclosure, or member_opening_statement",
    "news_clip_or_article": "event_web_page (committee hearing webpage), press_release_or_fact_sheet, or witness_biography",
    "external_report_or_whitepaper": "press_release_or_fact_sheet, agency_or_gao_crs_report, or hearing_memo_or_charter",
    "investigative_exhibit": "legal_or_investigative_filing (deposition/court filing) or oversight_letter",
}

ROLE_DESC_V6: dict[str, str] = {
    "witness": "person testifying or listed as a panel witness at a hearing",
    "author_or_speaker": "primary author of a report/article/bill summary or standalone speaker",
    "chair": "Chair or Acting Chair of the committee or subcommittee",
    "ranking_member": "Ranking Minority Member of the committee or subcommittee",
    "presiding": "Member presiding over the hearing or session (when not Chair)",
    "questioner": "Member asking Questions for the Record (QFRs) or questioning in a transcript",
    "sponsor": "primary congressional sponsor introducing a bill or resolution",
    "cosponsor": "congressional cosponsor of a bill or resolution",
    "amendment_offeror": "Member offering or proposing a committee amendment",
    "nominee": "presidential nominee for judicial or executive office under consideration",
    "introducer": "official or Member introducing a witness or nominee to the committee",
    "sender": "author/sender of a letter, email, or memorandum",
    "recipient": "addressed recipient ('Dear ...' / 'To:') of a letter, email, or memo",
    "signatory": "additional co-signer on a multi-signer letter",
    "staff": "named congressional or agency staff contact",
    "party_or_investigator": "litigant, counsel, deponent, or investigator in a legal/investigative record",
}

ALL_ROLES_V6: tuple[str, ...] = (
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
)


def _extract_row_fields(row: Mapping[str, Any]) -> tuple[str, str, str]:
    fn = str(row.get("filename") or "")
    txt = ""
    for k in ("p12_clean_text", "clean_text", "text", "p12_text", "p12_raw_text"):
        v = row.get(k)
        if isinstance(v, str) and v:
            txt = v
            break
    known_raw = row.get("known") if row.get("known") is not None else row.get("known_json")
    if isinstance(known_raw, Mapping):
        known_str = json.dumps(dict(known_raw), sort_keys=True, ensure_ascii=False)
    else:
        known_str = str(known_raw or "<NONE>")
    return fn, known_str, txt


def _format_doc_head_tail(
    clean_text: str,
    known_str: str,
    filename: str,
    *,
    head_chars: int = 1450,
    tail_chars: int = 500,
) -> str:
    fn_str = filename or "<NONE>"
    t = clean_text or ""
    if len(t) <= head_chars + tail_chars + 80:
        body = t
    else:
        body = t[:head_chars] + "\n[...]\n" + t[-tail_chars:]
    return f"FILE: {fn_str} | KNOWN: {known_str}\n{body}"


def _extract_entity_context(clean_text: str, entity_name: str, window_chars: int = 220) -> str:
    t = clean_text or ""
    if not t or not entity_name:
        return _WS_RE.sub(" ", t[: window_chars * 2]).strip()
    sur = surname_token_v6(entity_name)
    patterns = [re.escape(entity_name.strip())]
    if len(sur) > 2:
        patterns.append(r"\b" + re.escape(sur) + r"\b")
    snippets: list[str] = []
    used_spans: list[tuple[int, int]] = []
    for pat in patterns:
        for m in re.finditer(pat, t, flags=re.I):
            s = max(0, m.start() - window_chars)
            e = min(len(t), m.end() + window_chars)
            if any(not (e < us or s > ue) for us, ue in used_spans):
                continue
            used_spans.append((s, e))
            marked = t[s : m.start()] + f"<<{t[m.start():m.end()]}>>" + t[m.end() : e]
            snippets.append(_WS_RE.sub(" ", marked).strip())
            if len(snippets) >= 2:
                break
        if snippets:
            break
    if not snippets:
        return _WS_RE.sub(" ", t[:360]).strip()
    return " ... ".join(snippets)


def _compact_personas_summary(docmeta: Mapping[str, Any]) -> str:
    raw = docmeta.get("personas")
    if not isinstance(raw, list) or not raw:
        return "<NONE>"
    parts: list[str] = []
    for px in raw[:10]:
        if isinstance(px, Mapping) and px.get("name"):
            nm = str(px["name"]).strip()
            rl = str(px.get("role") or "witness")
            et = str(px.get("entity_type") or "")
            parts.append(f"{nm} ({rl}{', ' + et if et else ''})")
    return "; ".join(parts) if parts else "<NONE>"


def build_genre_conditional_question_v6(docmeta: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return an optional 4th genre-tailored `Noul` check (`correspondence_flow`, `action_summary`, or `disclosure`)."""
    pk = str(docmeta.get("primary_kind") or "")
    cflow = docmeta.get("correspondence_flow")
    act_sum = docmeta.get("action_summary")
    disc = docmeta.get("disclosure")

    if pk in _ACTION_SUMMARY_CHECK_KINDS_V6:
        act_str = str(act_sum).strip() if isinstance(act_sum, str) and act_sum.strip() else "<MISSING>"
        return {
            "id": "q4_action_summary_valid",
            "field": "action_summary",
            "type": "noul",
            "instructions": (
                f"In `document_excerpt`, does `action_summary` (`{act_str}`) accurately record the "
                "stated vote outcome (e.g. adopted, rejected, voice/nonrecord vote, or tally) or cost figure?"
            ),
            "criteria": {
                "true": "yes, the action or vote outcome matches the document",
                "false": "no, the outcome/tally is missing, inverted, or unsupported",
            },
        }

    if pk == "truth_in_testimony_disclosure" or isinstance(disc, Mapping):
        disc_str = json.dumps(dict(disc), ensure_ascii=False) if isinstance(disc, Mapping) else "<MISSING>"
        return {
            "id": "q4_disclosure_valid",
            "field": "disclosure",
            "type": "noul",
            "instructions": (
                f"Does `disclosure` (`{disc_str}`) accurately match the witness capacity, government status, "
                "federal grants, and foreign payments stated in `document_excerpt`?"
            ),
            "criteria": {
                "true": "yes, the disclosure fields match the form responses",
                "false": "no, disclosure is missing or contradicts the form",
            },
        }

    if pk in _CORRESPONDENCE_CHECK_KINDS_V6 or isinstance(cflow, str):
        cf_str = str(cflow) if isinstance(cflow, str) and cflow else "<MISSING>"
        cf_desc = CFLOW_DESC_V6.get(cf_str, "missing correspondence flow")
        return {
            "id": "q4_correspondence_flow_valid",
            "field": "correspondence_flow",
            "type": "noul",
            "instructions": (
                f"In `document_excerpt`, does `correspondence_flow` = `{cf_str}` ({cf_desc}) accurately "
                "reflect who sent this communication and to whom?"
            ),
            "criteria": {
                "true": f"yes, `{cf_str}` matches the sender-to-recipient direction",
                "false": f"no, `{cf_str}` is wrong, missing, or inappropriate for this genre",
            },
        }

    return None


def build_atomic_doc_questions_v6(
    docmeta: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    head_chars: int = 1450,
    tail_chars: int = 500,
    include_genre_check: bool = False,
    include_omission_check: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Construct shared `state` and atomic `Noul` validation questions for `docmeta`."""
    fn, known_str, clean_text = _extract_row_fields(row)
    pk = str(docmeta.get("primary_kind") or "non_usable_stub")
    pk_desc = ALL_KIND_DESC_V6.get(
        pk, "blank stub, error page, or index wrapper without substantive document text"
    )
    alts = CONFUSABLE_ALTS_V6.get(pk, "a different congressional document type")
    comms_list = [str(c) for c in (docmeta.get("committees") or ()) if isinstance(c, str) and c.strip()]
    comms = ", ".join(comms_list) if comms_list else "NO CONGRESSIONAL COMMITTEE (external/executive only)"
    title = str(docmeta.get("composed_title") or "<NONE>")
    gist = str(docmeta.get("gist") or "<NONE>")

    cand_ext: dict[str, Any] = {
        "status": docmeta.get("status"),
        "primary_kind": pk,
        "committees": comms,
        "composed_title": title,
        "gist": gist,
    }
    if include_genre_check or include_omission_check:
        cand_ext["actors"] = _compact_personas_summary(docmeta)
        if docmeta.get("correspondence_flow") is not None:
            cand_ext["correspondence_flow"] = docmeta.get("correspondence_flow")
        if docmeta.get("action_summary") is not None:
            cand_ext["action_summary"] = docmeta.get("action_summary")
        if docmeta.get("disclosure") is not None:
            cand_ext["disclosure"] = docmeta.get("disclosure")

    state: dict[str, Any] = {
        "filename": fn or "<NONE>",
        "known_metadata": known_str,
        "document_excerpt": _format_doc_head_tail(clean_text, known_str, fn, head_chars=head_chars, tail_chars=tail_chars),
        "candidate_extraction": cand_ext,
    }
    questions: list[dict[str, Any]] = [
        {
            "id": "q1_kind_valid",
            "field": "primary_kind",
            "type": "noul",
            "instructions": (
                f"In `document_excerpt`, is `{pk}` ({pk_desc}) the correct document classification, "
                f"rather than {alts} or a substantive usable document?"
            ),
            "criteria": {
                "true": f"yes, the document is genuinely `{pk}`",
                "false": f"no, `{pk}` is wrong for this document",
            },
        },
        {
            "id": "q2_committee_valid",
            "field": "committees",
            "type": "noul",
            "instructions": (
                f"Does `document_excerpt` or `filename` support `{comms}` as the authoring or host "
                "congressional committee for this document?"
            ),
            "criteria": {
                "true": "yes, the committee assignment matches the document",
                "false": "no, the committee is hallucinated, wrong, or missing from the document",
            },
        },
        {
            "id": "q3_summary_valid",
            "field": "gist",
            "type": "noul",
            "instructions": (
                "Do `composed_title` and `gist` in `candidate_extraction` name the right lead "
                "person/committee and main topic of `document_excerpt` (allowing normal brevity)?"
            ),
            "criteria": {
                "true": "yes, the main actor, committee, and subject match",
                "false": "no, names a wrong committee, wrong person/sender, or wrong topic",
            },
        },
    ]
    if include_genre_check:
        q4 = build_genre_conditional_question_v6(docmeta)
        if q4 is not None:
            questions.append(q4)
    if include_omission_check:
        actors_s = _compact_personas_summary(docmeta)
        questions.append(
            {
                "id": "q5_actors_complete",
                "field": "personas_omission",
                "type": "noul",
                "instructions": (
                    f"Does `actors` (`{actors_s}`) include every primary witness, speaker, author, sender, "
                    "or addressed recipient explicitly featured in `document_excerpt` (ignoring standing rosters)?"
                ),
                "criteria": {
                    "true": "yes, the main active participants are covered",
                    "false": "no, one or more primary witnesses, senders, or recipients were omitted",
                },
            }
        )
    return state, questions


def build_atomic_persona_question_v6(
    docmeta: Mapping[str, Any],
    row: Mapping[str, Any],
    persona: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Construct full-roster-aware `state` + atomic `Noul` check for one extracted persona."""
    _, _, clean_text = _extract_row_fields(row)
    nm = str(persona.get("name") or "<EMPTY>")
    rl = str(persona.get("role") or "witness")
    et = str(persona.get("entity_type") or "non_gov_person")
    rl_desc = ROLE_DESC_V6.get(rl, rl)
    pk = str(docmeta.get("primary_kind") or "unknown")
    ctx = _extract_entity_context(clean_text, nm, window_chars=200)
    state: dict[str, Any] = {
        "candidate_actor": {
            "name": nm,
            "role": rl,
            "entity_type": et,
            "title": str(persona.get("title") or ""),
            "org": str(persona.get("org") or ""),
        },
        "mentions_of_actor": ctx,
        "all_extracted_actors": _compact_personas_summary(docmeta),
        "document_type": pk,
        "document_opening": _WS_RE.sub(" ", clean_text[:200]).strip(),
    }
    question = {
        "id": "q_persona_valid",
        "type": "noul",
        "instructions": (
            f"Given `all_extracted_actors` and `mentions_of_actor`, is `{nm}` a real active participant "
            f"(not a building/office word or webpage chrome) whose role in this `{pk}` is `{rl}` ({rl_desc})?"
        ),
        "criteria": {
            "true": f"yes, `{nm}` is a real participant acting as `{rl}`",
            "false": f"no, `{nm}` is not a real actor here or has a different role than `{rl}` (e.g. recipient vs chair/sender)",
        },
    }
    return state, question


# ---------------------------------------------------------------------------
# 3. Unified Production Verifier (`ExternalVerifierFn` + Async Stage-1 Overlap)
# ---------------------------------------------------------------------------


def _is_grammar_locked_kind(docmeta: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    locked = row.get("locked_primary_kind") or row.get("v6_locked_primary_kind") or row.get("v5_locked_primary_kind")
    return isinstance(locked, str) and bool(locked) and docmeta.get("primary_kind") == locked


def _can_skip_empty_committees(docmeta: Mapping[str, Any], row: Mapping[str, Any], clean_text: str) -> bool:
    if docmeta.get("committees") or row.get("rel_committees") or row.get("meeting_committees"):
        return False
    return "committee" not in clean_text[:1200].lower()


_OMISSION_PRONE_KINDS_V6: frozenset[str] = frozenset(
    {
        "witness_list",
        "hearing_notice",
        "markup_notice",
        "investigative_exhibit",
        "hearing_transcript",
        "oversight_letter",
        "witness_invitation",
        "nomination_or_support_letter",
    }
)


def _should_check_omission(obj: Mapping[str, Any], v0: Mapping[str, Any]) -> bool:
    if v0.get("persona_omission_flags"):
        return True
    pk = str(obj.get("primary_kind") or "")
    personas = obj.get("personas")
    n_p = len(personas) if isinstance(personas, list) else 0
    if n_p == 0 and pk in ACTOR_REQUIRED_KINDS_V6:
        return True
    return pk in _OMISSION_PRONE_KINDS_V6


def _is_trivially_verified_single_persona(
    docmeta: Mapping[str, Any],
    row: Mapping[str, Any],
    v0_pers_scores: list[float],
) -> bool:
    personas = docmeta.get("personas")
    if not isinstance(personas, list) or len(personas) != 1 or not v0_pers_scores or v0_pers_scores[0] > 0.0:
        return False
    p0 = personas[0]
    if not isinstance(p0, Mapping) or p0.get("role") not in ("witness", "author_or_speaker"):
        return False
    sur = surname_token_v6(str(p0.get("name") or ""))
    if len(sur) < 3:
        return False
    fn = str(row.get("filename") or "").lower()
    rel_w = str(row.get("rel_witness_name") or "").lower()
    return (sur in fn) or (bool(rel_w) and sur in rel_w)


def resolve_docmeta_pkg_root(home: str | Path | None = None) -> Path:
    """Resolve `packages/congress_docmeta` root cleanly with stdlib-only path traversal."""
    if home is not None:
        return Path(home).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def resolve_docmeta_validators_dir(
    artifacts_dir: str | Path | None = None,
    *,
    home: str | Path | None = None,
) -> Path:
    """Resolve Congressional V6.3 validator artifacts directory (`explicit > env > checkout cache`)."""
    if artifacts_dir is not None:
        return Path(artifacts_dir).expanduser().resolve()
    env_dir = os.environ.get("DOCMETA_VALIDATORS_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    if home is not None:
        home_art = Path(home).expanduser().resolve() / "artifacts" / "atomic_validators"
        if home_art.exists():
            return home_art
    env_data = os.environ.get("DOCMETA_V6_DATA_DIR")
    if env_data:
        return Path(env_data).expanduser().resolve() / "atomic_validators"
    pkg_root = Path(__file__).resolve().parents[2]
    ct_root = pkg_root.parents[1]
    candidates = [
        ct_root / ".cache" / "archive-release" / "docmeta-v6-20261116" / "atomic_validators",
        pkg_root / "artifacts" / "atomic_validators",
    ]
    for cand in candidates:
        if cand.exists():
            return cand
    return candidates[0]


class AtomicOutputValidatorV6:
    """Post-`Gemma-4` Atomic `Noul` Output Validator (`laya-ane` | `kev-0.8b` | `both`).

    Conforms directly to `parquet_runner_v6.ExternalVerifierFn`:
        `verdicts = validator(clean_objs, chunk)`
    And exposes `run_stage1_ane(...)` + `finish_stage2(...)` so `parquet_runner_v6` can
    overlap Stage-1 Pure-ANE execution in a background thread behind `Gemma-4` GPU decode!
    """

    def __init__(
        self,
        mode: ValidatorMode = "both",
        *,
        home: str | Path | None = None,
        artifacts_dir: str | Path | None = None,
        escalate_threshold: float | None = None,
        cascade: bool = True,
        cascade_low: float | None = None,
        cascade_high: float | None = None,
        cascade_min_defect: float | None = None,
        skip_redundant: bool = True,
        include_genre_check: bool = True,
        include_omission_check: bool = True,
        score_personas: bool = True,
        kev_quant: Literal["auto", "w8", "bf16"] = "auto",
        kev_batch_docs: int = 1,
        pipe_depth: int = 4,
    ) -> None:
        if mode not in ("laya-ane", "kev-0.8b", "both"):
            raise ValueError(f"Unsupported mode={mode!r}; expected 'laya-ane', 'kev-0.8b', or 'both'.")
        from fast_decision_models import Kev08bMlxBackend, LayaAneBackend
        from fast_decision_models.paths import ensure_laya_dylib

        self.mode: ValidatorMode = mode
        self.home_dir = resolve_docmeta_pkg_root(home)
        self.artifacts_dir = resolve_docmeta_validators_dir(artifacts_dir, home=home)
        cal_p = self.artifacts_dir / "validator_v63_calibration.json"
        cal: dict[str, Any] = json.loads(cal_p.read_text(encoding="utf-8")) if cal_p.is_file() else {}
        self.calibration_version: str = str(cal.get("version") or "v6_2")
        self.laya_raw_offset = float(cal.get("laya_raw_offset", 0.24))
        self.laya_raw_scale = float(cal.get("laya_raw_scale", 0.36))
        vl_w = cal.get("v0_laya_weights") or [0.55, 0.45]
        vlk_w = cal.get("v0_laya_kev_weights") or [0.44, 0.18, 0.38]
        self.v0_laya_weights = (float(vl_w[0]), float(vl_w[1]))
        self.v0_laya_kev_weights = (float(vlk_w[0]), float(vlk_w[1]), float(vlk_w[2]))
        self.persona_role_choice_temp = float(cal.get("persona_role_choice16_temperature", 0.625))
        self.role_repair_min_defect = float(cal.get("role_repair_min_defect", 0.48))
        self.role_repair_min_prob = float(cal.get("role_repair_min_prob", 0.45))

        self.escalate_threshold = float(
            escalate_threshold if escalate_threshold is not None else cal.get("escalate_threshold", 0.45)
        )
        self.cascade = bool(cascade)
        eff_low = (
            cascade_min_defect
            if cascade_min_defect is not None
            else (cascade_low if cascade_low is not None else cal.get("cascade_low", 0.22))
        )
        self.cascade_low = float(eff_low)
        self.cascade_high = float(cascade_high if cascade_high is not None else cal.get("cascade_high", 0.62))
        self.skip_redundant = bool(skip_redundant)
        self.include_genre_check = bool(include_genre_check)
        self.include_omission_check = bool(include_omission_check)
        self.score_personas = bool(score_personas)

        self.laya_backend: Any = None
        self.kev_backend: Any = None

        if mode in ("laya-ane", "both"):
            dylib_p = ensure_laya_dylib()
            self.laya_backend = LayaAneBackend(
                self.artifacts_dir / "laya_typed",
                dylib_p,
                pipe_depth=pipe_depth,
            )
        if mode in ("kev-0.8b", "both"):
            self.kev_backend = Kev08bMlxBackend(
                self.artifacts_dir / "kev_08b",
                quant_mode=kev_quant,
                batch_docs=kev_batch_docs,
            )

    @property
    def supports_async_ane_stage1(self) -> bool:
        return self.laya_backend is not None

    @staticmethod
    def _agg_defect(p_kind: float, p_comm: float, p_gist: float) -> float:
        p_min = min(p_kind, p_comm, p_gist)
        p_mean = (p_kind + p_comm + p_gist) / 3.0
        return 1.0 - (0.65 * p_min + 0.35 * p_mean)

    def run_stage1_ane(
        self,
        clean_objs: Sequence[Mapping[str, Any]],
        chunk: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Run CPU `V0_Stdlib_Atomic` + Pure-ANE `Laya-Typed-421M` (`0` GPU ops — thread-safe with Metal GPU!)."""
        n = len(clean_objs)
        v0_list: list[dict[str, Any]] = []
        eval_doc_indices: list[int] = []
        clean_texts: list[str] = []

        for i in range(n):
            obj = clean_objs[i] if i < len(clean_objs) and isinstance(clean_objs[i], Mapping) else {}
            row = chunk[i] if i < len(chunk) and isinstance(chunk[i], Mapping) else {}
            v0 = dict(score_atomic_stdlib_v6(obj, row))
            fn_i, known_i, txt = _extract_row_fields(row)
            if txt.strip() and str(obj.get("status") or "usable") == "usable":
                g_rep = check_gist_title_grounding_v6(obj, text=txt, filename=fn_i, known=known_i)
                if g_rep.get("ungrounded_citations") or g_rep.get("ungrounded_modality"):
                    v0["gist_grounding_ungrounded"] = True
                    v0["atomic_risk_score"] = round(float(v0["atomic_risk_score"]) + 0.65, 4)
                if obj.get("primary_kind") == "truth_in_testimony_disclosure" and isinstance(obj.get("disclosure"), Mapping):
                    from .zero_llm_bypass_v6 import parse_ttf_form_v6

                    ttf_det = parse_ttf_form_v6(txt)
                    disc_pred = obj["disclosure"]
                    for dk in ("gov_witness", "capacity", "has_federal_grants", "has_foreign_payments"):
                        if dk in ttf_det and dk in disc_pred and ttf_det[dk] != disc_pred[dk]:
                            v0["disclosure_flags"] = [f"ttf_contradiction:{dk}"]
                            v0["atomic_risk_score"] = round(float(v0["atomic_risk_score"]) + 0.75, 4)
                            break
            v0_list.append(v0)
            clean_texts.append(txt)
            if txt.strip() and not row.get("triage_status"):
                eval_doc_indices.append(i)

        laya_field_probs: dict[int, dict[str, float]] = {}
        laya_pers_defects: dict[int, list[float]] = {}

        if self.laya_backend is not None and eval_doc_indices:
            doc_encs: list[dict[str, Any]] = []
            doc_slots: list[tuple[int, str]] = []

            for di in eval_doc_indices:
                obj = clean_objs[di]
                row = chunk[di]
                do_omit = self.include_omission_check and _should_check_omission(obj, v0_list[di])
                st_core, _ = build_atomic_doc_questions_v6(
                    obj,
                    row,
                    head_chars=950,
                    tail_chars=350,
                    include_genre_check=False,
                    include_omission_check=False,
                )
                st_ext, qs = build_atomic_doc_questions_v6(
                    obj,
                    row,
                    head_chars=740,
                    tail_chars=240,
                    include_genre_check=self.include_genre_check,
                    include_omission_check=do_omit,
                )
                laya_field_probs[di] = {"primary_kind": 0.98, "committees": 0.92, "gist": 0.5}
                for q in qs:
                    fld = str(q.get("field") or q["id"])
                    if self.skip_redundant:
                        if fld == "primary_kind" and _is_grammar_locked_kind(obj, row):
                            continue
                        if fld == "committees" and _can_skip_empty_committees(obj, row, clean_texts[di]):
                            continue
                    st_use = st_core if fld in ("primary_kind", "committees", "gist") else st_ext
                    doc_encs.append(self.laya_backend.encode_item(st_use, q))
                    doc_slots.append((di, fld))

            if doc_encs:
                p_doc_flat = self.laya_backend.score_noul_batch(doc_encs)
                for (di, fld), p_val in zip(doc_slots, p_doc_flat):
                    laya_field_probs[di][fld] = float(p_val)

            if self.score_personas:
                p_encs: list[dict[str, Any]] = []
                p_slots: list[tuple[int, int]] = []
                for di in eval_doc_indices:
                    obj = clean_objs[di]
                    row = chunk[di]
                    v0_p = list(v0_list[di]["persona_defect_scores"])
                    personas = obj.get("personas")
                    if not isinstance(personas, list) or not personas:
                        laya_pers_defects[di] = []
                        continue
                    if self.skip_redundant and _is_trivially_verified_single_persona(obj, row, v0_p):
                        laya_pers_defects[di] = [0.06]
                        continue
                    laya_pers_defects[di] = [0.5] * len(personas)
                    for pi, px in enumerate(personas):
                        if isinstance(px, Mapping):
                            pst, pq = build_atomic_persona_question_v6(obj, row, px)
                            p_encs.append(self.laya_backend.encode_item(pst, pq))
                            p_slots.append((di, pi))
                if p_encs:
                    p_pers_true = self.laya_backend.score_noul_batch(p_encs)
                    for (di, pi), pt in zip(p_slots, p_pers_true):
                        laya_pers_defects[di][pi] = round(1.0 - float(pt), 4)

        return {
            "clean_objs": clean_objs,
            "chunk": chunk,
            "v0_list": v0_list,
            "eval_doc_indices": eval_doc_indices,
            "clean_texts": clean_texts,
            "laya_field_probs": laya_field_probs,
            "laya_pers_defects": laya_pers_defects,
        }

    def finish_stage2(self, stage1: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Run Stage-2 batched `W8` `Kev-0.8B` (on all or gray-zone docs) and assemble final verdicts."""
        clean_objs: Sequence[Mapping[str, Any]] = stage1["clean_objs"]
        chunk: Sequence[Mapping[str, Any]] = stage1["chunk"]
        v0_list: list[dict[str, Any]] = stage1["v0_list"]
        eval_doc_indices: list[int] = stage1["eval_doc_indices"]
        clean_texts: list[str] = stage1["clean_texts"]
        laya_field_probs: dict[int, dict[str, float]] = stage1["laya_field_probs"]
        laya_pers_defects: dict[int, list[float]] = stage1["laya_pers_defects"]
        n = len(clean_objs)
        if n == 0:
            return []

        kev_field_probs: dict[int, dict[str, float]] = {}
        kev_pers_defects: dict[int, list[float]] = {}

        if self.kev_backend is not None and eval_doc_indices:
            kev_doc_targets: list[int] = []
            kev_batch_inputs: list[tuple[Any, list[dict[str, Any]]]] = []
            kev_q_meta: list[list[tuple[str, int]]] = []

            for di in eval_doc_indices:
                if self.mode == "both" and self.cascade and di in laya_field_probs:
                    v0_u = min(1.0, float(v0_list[di]["atomic_risk_score"]) / 1.50)
                    lfp = laya_field_probs[di]
                    l_raw = self._agg_defect(lfp["primary_kind"], lfp["committees"], lfp["gist"])
                    l_cal = max(0.0, min(1.0, (l_raw - self.laya_raw_offset) / max(self.laya_raw_scale, 1e-4)))
                    w_v0, w_l = self.v0_laya_weights
                    stage1_def = w_v0 * v0_u + w_l * l_cal
                    # Two-sided gray-zone cascade: skip GPU when Stage-1 is clearly clean OR clearly defective!
                    if stage1_def < self.cascade_low or stage1_def > self.cascade_high:
                        continue

                obj = clean_objs[di]
                row = chunk[di]
                do_omit_k = self.include_omission_check and _should_check_omission(obj, v0_list[di])
                st, qs = build_atomic_doc_questions_v6(
                    obj,
                    row,
                    head_chars=1450,
                    tail_chars=500,
                    include_genre_check=self.include_genre_check,
                    include_omission_check=do_omit_k,
                )
                filtered_qs: list[dict[str, Any]] = []
                q_meta_di: list[tuple[str, int]] = []
                kev_field_probs[di] = {"primary_kind": 0.98, "committees": 0.92, "gist": 0.5}
                for q in qs:
                    fld = str(q.get("field") or q["id"])
                    if self.skip_redundant:
                        if fld == "primary_kind" and _is_grammar_locked_kind(obj, row):
                            continue
                        if fld == "committees" and _can_skip_empty_committees(obj, row, clean_texts[di]):
                            continue
                    filtered_qs.append(q)
                    q_meta_di.append((fld, -1))

                # Attach persona checks onto the SAME cached state pass (`kev-0.8b` or top-2 gray-zone in `both`)!
                personas = obj.get("personas")
                v0_p = list(v0_list[di]["persona_defect_scores"])
                if self.score_personas and isinstance(personas, list) and personas:
                    if self.skip_redundant and _is_trivially_verified_single_persona(obj, row, v0_p):
                        kev_pers_defects[di] = [0.06]
                    elif self.mode == "kev-0.8b":
                        kev_pers_defects[di] = [0.5] * len(personas)
                        for pi, px in enumerate(personas):
                            if isinstance(px, Mapping):
                                pst, pq = build_atomic_persona_question_v6(obj, row, px)
                                pq_inline = dict(pq)
                                pq_inline["instructions"] = (
                                    f"Actor context: {pst['mentions_of_actor']} | " + str(pq["instructions"])
                                )
                                filtered_qs.append(pq_inline)
                                q_meta_di.append(("persona", pi))
                    elif self.mode == "both" and di in laya_pers_defects and len(laya_pers_defects[di]) == len(personas):
                        lp_di = list(laya_pers_defects[di])
                        gray_pis = [
                            pi
                            for pi in range(len(personas))
                            if 0.28 <= (0.55 * v0_p[pi] + 0.45 * lp_di[pi]) <= 0.68
                        ][:2]
                        if gray_pis:
                            kev_pers_defects[di] = list(lp_di)
                            for pi in gray_pis:
                                px = personas[pi]
                                if isinstance(px, Mapping):
                                    pst, pq = build_atomic_persona_question_v6(obj, row, px)
                                    pq_inline = dict(pq)
                                    pq_inline["instructions"] = (
                                        f"Actor context: {pst['mentions_of_actor']} | " + str(pq["instructions"])
                                    )
                                    filtered_qs.append(pq_inline)
                                    q_meta_di.append(("persona", pi))

                if filtered_qs:
                    kev_doc_targets.append(di)
                    kev_batch_inputs.append((st, filtered_qs))
                    kev_q_meta.append(q_meta_di)

            if kev_batch_inputs:
                batch_outs = self.kev_backend.score_multi_states_noul(kev_batch_inputs)
                for di, q_meta_di, outs_di in zip(kev_doc_targets, kev_q_meta, batch_outs):
                    for (fld, pi), (p1, _rz) in zip(q_meta_di, outs_di):
                        if fld == "persona" and pi >= 0 and di in kev_pers_defects:
                            kev_pers_defects[di][pi] = round(1.0 - float(p1), 4)
                        else:
                            kev_field_probs[di][fld] = float(p1)

        eval_set = set(eval_doc_indices)
        verdicts: list[dict[str, Any]] = []
        for i in range(n):
            v0 = v0_list[i]
            v0_risk = float(v0["atomic_risk_score"])
            v0_unit = min(1.0, v0_risk / 1.50)

            if i not in eval_set:
                has_false_nu = any(str(x).startswith("false_non_usable:") for x in v0["kind_conflicts"])
                codes_nu = ["false_non_usable_on_substantive_text"] if has_false_nu else []
                def_nu = 0.85 if has_false_nu else 0.0
                verdicts.append(
                    {
                        "mode": self.mode,
                        "score": round(1.0 - def_nu, 4),
                        "defect_score": round(def_nu, 4),
                        "is_faithful": not has_false_nu,
                        "escalate": has_false_nu,
                        "v0_score": round(1.0 - v0_unit, 4),
                        "laya_score": None,
                        "kev_score": None,
                        "field_probs": None,
                        "persona_defect_scores": list(v0["persona_defect_scores"]),
                        "flagged_fields": ["status"] if has_false_nu else [],
                        "codes": codes_nu,
                    }
                )
                continue

            lfp = laya_field_probs.get(i)
            kfp = kev_field_probs.get(i)
            laya_raw = self._agg_defect(lfp["primary_kind"], lfp["committees"], lfp["gist"]) if lfp is not None else None
            laya_def = (
                max(0.0, min(1.0, (laya_raw - self.laya_raw_offset) / max(self.laya_raw_scale, 1e-4)))
                if laya_raw is not None
                else None
            )
            kev_raw = self._agg_defect(kfp["primary_kind"], kfp["committees"], kfp["gist"]) if kfp is not None else None
            kev_def = max(0.0, min(1.0, (kev_raw - 0.14) / 0.62)) if kev_raw is not None else None

            if laya_def is not None and kev_def is not None and lfp is not None and kfp is not None:
                wv0, wl, wk = self.v0_laya_kev_weights
                defect = wv0 * v0_unit + wl * laya_def + wk * kev_def
                merged_fp: dict[str, float] = {}
                for fk in set(lfp) | set(kfp):
                    if fk in lfp and fk in kfp:
                        merged_fp[fk] = 0.40 * lfp[fk] + 0.60 * kfp[fk]
                    elif fk in kfp:
                        merged_fp[fk] = kfp[fk]
                    else:
                        merged_fp[fk] = lfp[fk]
            elif kev_def is not None and kfp is not None:
                defect = 0.48 * v0_unit + 0.52 * kev_def
                merged_fp = dict(kfp)
            elif laya_def is not None and lfp is not None:
                wv0_s, wl_s = self.v0_laya_weights
                defect = wv0_s * v0_unit + wl_s * laya_def
                merged_fp = dict(lfp)
            else:
                defect = v0_unit
                merged_fp = {"primary_kind": 1.0 - v0_unit, "committees": 1.0 - v0_unit, "gist": 1.0 - v0_unit}

            # Incorporate high-confidence `action_summary` / `disclosure` defect into escalation score
            disc_thresh = 0.35 if kfp is not None else 0.28
            if merged_fp.get("action_summary", 1.0) < 0.28 or v0.get("action_summary_flags"):
                defect = max(defect, 0.58)
            if merged_fp.get("disclosure", 1.0) < disc_thresh or v0.get("disclosure_flags"):
                defect = max(defect, 0.56)

            # Combine per-persona defect scores (`V0` + `Laya-ANE` + `Kev-0.8B`)
            v0_p = list(v0["persona_defect_scores"])
            lp_p = laya_pers_defects.get(i)
            kp_p = kev_pers_defects.get(i)
            if lp_p is not None and kp_p is not None and len(lp_p) == len(v0_p) == len(kp_p):
                pers_def = [
                    round(max(0.80 * a + 0.10 * b + 0.10 * c, 0.20 * a + 0.35 * b + 0.45 * c), 4)
                    for a, b, c in zip(v0_p, lp_p, kp_p)
                ]
            elif kp_p is not None and len(kp_p) == len(v0_p):
                pers_def = [round(max(0.82 * a + 0.18 * c, 0.20 * a + 0.80 * c), 4) for a, c in zip(v0_p, kp_p)]
            elif lp_p is not None and len(lp_p) == len(v0_p):
                pers_def = [round(max(0.85 * a + 0.15 * b, 0.20 * a + 0.80 * b), 4) for a, b in zip(v0_p, lp_p)]
            else:
                pers_def = v0_p

            flagged_fields: list[str] = []
            codes: list[str] = []
            if merged_fp.get("primary_kind", 1.0) < 0.50 or v0["kind_conflicts"]:
                flagged_fields.append("primary_kind")
                codes.append("atomic_kind_suspect")
            if merged_fp.get("committees", 1.0) < 0.50 or v0["ungrounded_committees"]:
                flagged_fields.append("committees")
                codes.append("atomic_committee_suspect")
            if merged_fp.get("gist", 1.0) < 0.50 or float(v0["gist_miss_frac"]) >= 0.45:
                flagged_fields.append("gist")
                codes.append("atomic_gist_suspect")
            if merged_fp.get("action_summary", 1.0) < 0.45 or v0.get("action_summary_flags"):
                flagged_fields.append("action_summary")
                codes.append("atomic_action_summary_suspect")
            if merged_fp.get("correspondence_flow", 1.0) < 0.45 or v0.get("correspondence_flow_flags"):
                flagged_fields.append("correspondence_flow")
                codes.append("atomic_correspondence_flow_suspect")
            if merged_fp.get("disclosure", 1.0) < 0.45 or v0.get("disclosure_flags"):
                flagged_fields.append("disclosure")
                codes.append("atomic_disclosure_suspect")
            if v0.get("ungrounded_dates"):
                flagged_fields.append("dates")
                codes.append("atomic_date_suspect")
            if (
                any(ps >= 0.65 for ps in pers_def)
                or merged_fp.get("personas_omission", 1.0) < 0.42
                or v0.get("persona_omission_flags")
            ):
                flagged_fields.append("personas")
                codes.append("atomic_persona_suspect")

            escalate = bool(defect >= self.escalate_threshold)
            if escalate and not codes:
                codes.append("atomic_validator_escalated")

            raw_faith = max(0.0, min(1.0, 1.0 - defect))
            if escalate and raw_faith >= 0.5:
                raw_faith = 0.49
            elif not escalate and raw_faith < 0.5:
                raw_faith = 0.51

            verdicts.append(
                {
                    "mode": self.mode,
                    "score": round(raw_faith, 4),
                    "defect_score": round(defect, 4),
                    "is_faithful": not escalate,
                    "escalate": escalate,
                    "v0_score": round(1.0 - v0_unit, 4),
                    "laya_score": round(1.0 - laya_def, 4) if laya_def is not None else None,
                    "kev_score": round(1.0 - kev_def, 4) if kev_def is not None else None,
                    "field_probs": {k: round(v, 4) for k, v in sorted(merged_fp.items())},
                    "persona_defect_scores": pers_def,
                    "flagged_fields": flagged_fields,
                    "codes": codes,
                }
            )
        return verdicts

    def score_batch(
        self,
        clean_objs: Sequence[Mapping[str, Any]],
        chunk: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Score a batch of `(clean_objs, chunk)` rows and return structured `ExternalVerifierFn` dicts."""
        if not clean_objs:
            return []
        s1 = self.run_stage1_ane(clean_objs, chunk)
        return self.finish_stage2(s1)

    def predict_persona_roles_ane(
        self,
        clean_objs: Sequence[Mapping[str, Any]],
        chunk: Sequence[Mapping[str, Any]],
        target_slots: Sequence[tuple[int, int]] | None = None,
    ) -> dict[tuple[int, int], tuple[str, float]]:
        """Run `Laya-Typed-v63` `Choice(16)` on Pure ANE (`0` GPU ops) to classify `(doc_idx, persona_idx)` roles."""
        if self.laya_backend is None or not clean_objs:
            return {}
        slots: list[tuple[int, int]] = []
        if target_slots is not None:
            slots = list(target_slots)
        else:
            for di, obj in enumerate(clean_objs):
                ps = obj.get("personas")
                if isinstance(ps, list):
                    for pi in range(len(ps)):
                        slots.append((di, pi))
        if not slots:
            return {}

        encs: list[dict[str, Any]] = []
        valid_slots: list[tuple[int, int]] = []
        roles_list = list(ALL_ROLES_V6)
        for di, pi in slots:
            if di >= len(clean_objs) or di >= len(chunk):
                continue
            obj = clean_objs[di]
            ps = obj.get("personas")
            if not isinstance(ps, list) or pi >= len(ps) or not isinstance(ps[pi], Mapping):
                continue
            px = ps[pi]
            pst, _ = build_atomic_persona_question_v6(obj, chunk[di], px)
            nm = str(px.get("name") or "<EMPTY>")
            pk = str(obj.get("primary_kind") or "unknown")
            q_role = {
                "id": "q_persona_role_choice",
                "type": "choice",
                "instructions": (
                    f"In this `{pk}`, what is `{nm}`'s exact participant `role` given `mentions_of_actor` "
                    "and `all_extracted_actors`?"
                ),
                "criteria": roles_list,
            }
            encs.append(self.laya_backend.encode_item(pst, q_role))
            valid_slots.append((di, pi))

        if not encs:
            return {}
        probs_batch = self.laya_backend.score_choice_batch(
            encs, temperature_override=self.persona_role_choice_temp
        )
        out: dict[tuple[int, int], tuple[str, float]] = {}
        for slot_key, p_vec in zip(valid_slots, probs_batch):
            if len(p_vec) == len(roles_list):
                best_j = max(range(len(p_vec)), key=lambda j: p_vec[j])
                out[slot_key] = (roles_list[best_j], round(float(p_vec[best_j]), 4))
        return out

    def repair_suspect_personas(
        self,
        clean_objs: Sequence[dict[str, Any]],
        chunk: Sequence[Mapping[str, Any]],
        verdicts: Sequence[Mapping[str, Any] | None] | None = None,
        *,
        min_defect: float | None = None,
        min_prob: float | None = None,
    ) -> list[dict[str, Any]]:
        """Auto-repair grounded human personas flagged with role defects via `Laya-Typed-v63` ANE `Choice(16)`.

        Never modifies non-person decoys or ungrounded surnames (which belong to deletion/escalation),
        and only updates `persona["role"]` when `P(new_role) >= min_prob` (`0` GPU ops).
        """
        if self.laya_backend is None or not clean_objs:
            return []
        eff_min_def = float(min_defect if min_defect is not None else self.role_repair_min_defect)
        eff_min_prob = float(min_prob if min_prob is not None else self.role_repair_min_prob)
        eff_verdicts = list(verdicts) if verdicts is not None else self.score_batch(clean_objs, chunk)

        cand_slots: list[tuple[int, int]] = []
        for di, (obj, row) in enumerate(zip(clean_objs, chunk)):
            vd = eff_verdicts[di] if di < len(eff_verdicts) else None
            if not isinstance(vd, Mapping):
                continue
            ps = obj.get("personas")
            p_defs = vd.get("persona_defect_scores")
            if not isinstance(ps, list) or not isinstance(p_defs, list) or len(ps) != len(p_defs):
                continue
            v0 = score_atomic_stdlib_v6(obj, row)
            bad_names = {
                str(f).split(":", 1)[1].strip("'\"")
                for f in (v0.get("persona_flags") or ())
                if str(f).startswith(("non_person_persona:", "ungrounded_persona_surname:"))
            }
            for pi, (px, p_sc) in enumerate(zip(ps, p_defs)):
                if not isinstance(px, dict):
                    continue
                nm = str(px.get("name") or "").strip()
                if nm and nm not in bad_names and float(p_sc) >= eff_min_def:
                    cand_slots.append((di, pi))

        if not cand_slots:
            return []

        preds = self.predict_persona_roles_ane(clean_objs, chunk, cand_slots)
        repairs: list[dict[str, Any]] = []
        for (di, pi), (new_role, prob) in preds.items():
            px = clean_objs[di]["personas"][pi]
            old_role = str(px.get("role") or "")
            if new_role != old_role and prob >= eff_min_prob:
                px["role"] = new_role
                repairs.append(
                    {
                        "doc_idx": di,
                        "persona_idx": pi,
                        "name": px.get("name"),
                        "old_role": old_role,
                        "new_role": new_role,
                        "prob": prob,
                    }
                )
        return repairs

    def __call__(
        self,
        clean_objs: Sequence[Mapping[str, Any]],
        chunk: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        return self.score_batch(clean_objs, chunk)

    def close(self) -> None:
        if self.laya_backend is not None:
            self.laya_backend.close()
            self.laya_backend = None
        if self.kev_backend is not None:
            self.kev_backend.close()
            self.kev_backend = None

    def __enter__(self) -> "AtomicOutputValidatorV6":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


__all__ = [
    "ALL_KIND_DESC_V6",
    "ALL_ROLES_V6",
    "AtomicOutputValidatorV6",
    "CFLOW_DESC_V6",
    "CONFUSABLE_ALTS_V6",
    "ROLE_DESC_V6",
    "ValidatorMode",
    "build_atomic_doc_questions_v6",
    "build_atomic_persona_question_v6",
    "build_genre_conditional_question_v6",
    "resolve_docmeta_pkg_root",
    "resolve_docmeta_validators_dir",
]
