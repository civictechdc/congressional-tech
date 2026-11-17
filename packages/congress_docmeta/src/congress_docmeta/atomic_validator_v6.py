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

if __package__:
    from .anomaly_router_v6 import (
        ACTOR_REQUIRED_KINDS_V6,
        check_gist_title_grounding_v6,
        score_atomic_stdlib_v6,
        surname_token_v6,
    )
else:
    import sys

    _DOCMETA_DIR = Path(__file__).resolve().parent
    if str(_DOCMETA_DIR) not in sys.path:
        sys.path.insert(0, str(_DOCMETA_DIR))
    from anomaly_router_v6 import (  # type: ignore
        ACTOR_REQUIRED_KINDS_V6,
        check_gist_title_grounding_v6,
        score_atomic_stdlib_v6,
        surname_token_v6,
    )

ValidatorMode = Literal["laya-ane", "kev-0.8b", "both"]

_QTYPES = {"choice": 0, "score": 1, "noul": 2}
_KEV_SPECIAL_RE = re.compile(r"<\|([A-Za-z0-9_]+)\|>")
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

# Metal kernel source for Qwen3.5 `GatedDeltaNet` (`Dk=128`, `Dv % 8 == 0` packed butterfly).
# Uses `acc_f32` output name for the FP32 recurrent state accumulator per `fast-ir-guard` contract.
_GDN_PACKED_BTREE_SRC = r"""
    constexpr int lanes_per_row = 4;
    constexpr int rows_per_simdgroup = 32 / lanes_per_row;
    constexpr int values_per_lane = Dk / lanes_per_row;
    constexpr int partials_per_lane = values_per_lane / 4;

    auto n = thread_position_in_grid.z;
    auto b_idx = n / Hv;
    auto hv_idx = n % Hv;
    auto hk_idx = hv_idx / (Hv / Hk);

    auto lane = thread_index_in_simdgroup;
    auto row_in_simdgroup = lane / lanes_per_row;
    auto lane_in_row = lane & (lanes_per_row - 1);
    auto row_group = thread_position_in_grid.y;
    auto dv_idx = row_group * rows_per_simdgroup + row_in_simdgroup;

    auto q_ = q + (b_idx * T * Hk + hk_idx) * Dk + lane_in_row * values_per_lane;
    auto k_ = k + (b_idx * T * Hk + hk_idx) * Dk + lane_in_row * values_per_lane;
    auto v_ = v + (b_idx * T * Hv + hv_idx) * Dv;
    y += (b_idx * T * Hv + hv_idx) * Dv;

    auto i_state = state_in + (n * Dv + dv_idx) * Dk + lane_in_row * values_per_lane;
    auto o_state = acc_f32 + (n * Dv + dv_idx) * Dk + lane_in_row * values_per_lane;

    float state[values_per_lane];
    for (int i = 0; i < values_per_lane; ++i) {
        state[i] = static_cast<float>(i_state[i]);
    }

    auto g_ = g + b_idx * T * Hv;
    auto beta_ = beta + b_idx * T * Hv;

    for (int t = 0; t < T; ++t) {
        float gt = static_cast<float>(g_[hv_idx]);
        float part[partials_per_lane];
        for (int pb = 0; pb < partials_per_lane; ++pb) {
            float acc = 0.0f;
            for (int i = 0; i < 4; ++i) {
                int e = pb * 4 + i;
                state[e] = state[e] * gt;
                acc += state[e] * static_cast<float>(k_[e]);
            }
            part[pb] = acc;
        }
        float kv_mem =
            ((part[0] + part[1]) + (part[2] + part[3])) +
            ((part[4] + part[5]) + (part[6] + part[7]));
        kv_mem += simd_shuffle_xor(kv_mem, 1);
        kv_mem += simd_shuffle_xor(kv_mem, 2);

        auto delta =
            (static_cast<float>(v_[dv_idx]) - kv_mem) *
            static_cast<float>(beta_[hv_idx]);

        for (int pb = 0; pb < partials_per_lane; ++pb) {
            float acc = 0.0f;
            for (int i = 0; i < 4; ++i) {
                int e = pb * 4 + i;
                state[e] = state[e] + static_cast<float>(k_[e]) * delta;
                acc += state[e] * static_cast<float>(q_[e]);
            }
            part[pb] = acc;
        }
        float out =
            ((part[0] + part[1]) + (part[2] + part[3])) +
            ((part[4] + part[5]) + (part[6] + part[7]));
        out += simd_shuffle_xor(out, 1);
        out += simd_shuffle_xor(out, 2);
        if (lane_in_row == 0) {
            y[dv_idx] = static_cast<InT>(out);
        }

        q_ += Hk * Dk;
        k_ += Hk * Dk;
        v_ += Hv * Dv;
        y += Hv * Dv;
        g_ += Hv;
        beta_ += Hv;
    }

    for (int i = 0; i < values_per_lane; ++i) {
        o_state[i] = static_cast<StT>(state[i]);
    }
"""

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


def _resolve_default_home(home: str | Path | None = None) -> Path:
    if home is not None:
        return Path(home).expanduser().resolve()
    env_home = os.environ.get("FAST_GEMMA4_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()
    import fast_gemma4  # the engine checkout holds build/, native/ and artifacts/atomic_validators

    return Path(fast_gemma4.__file__).resolve().parents[2]


def _ensure_laya_dylib(home_dir: Path) -> Path:
    dylib = home_dir / "build" / "liblaya_ane_runner.dylib"
    if dylib.is_file():
        return dylib
    src_mm = home_dir / "native" / "laya_ane_runner.mm"
    if not src_mm.is_file():
        raise FileNotFoundError(f"Missing {dylib} and native source {src_mm}")
    dylib.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        [
            "clang++",
            "-std=c++17",
            "-O3",
            "-fobjc-arc",
            "-dynamiclib",
            "-framework",
            "Foundation",
            "-framework",
            "CoreML",
            f"-I{home_dir / 'native'}",
            str(src_mm),
            "-o",
            str(dylib),
        ]
    )
    return dylib


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


def _softmax_2(z0: float, z1: float, temp: float) -> tuple[float, float]:
    inv_t = 1.0 / max(temp, 1e-5)
    a = z0 * inv_t
    b = z1 * inv_t
    m = a if a > b else b
    ea = math.exp(a - m)
    eb = math.exp(b - m)
    s = ea + eb
    return ea / s, eb / s


# ---------------------------------------------------------------------------
# 1. Pure-ANE Backend: `Laya-Typed-421M` (`W8A16` `S=256` & `S=512`, `0` GPU Ops)
# ---------------------------------------------------------------------------


class _LayaAneBackend:
    """Zero-GPU CoreML ANE `W8A16` runner for `convaiinnovations/laya-typed-decisions`."""

    def __init__(self, laya_dir: Path, dylib_path: Path, *, pipe_depth: int = 4, compute_mode: int = 1) -> None:
        import numpy as np
        from tokenizers import Tokenizer

        self._np = np
        self._exec_lock = threading.Lock()
        self.laya_dir = laya_dir
        self.dylib_path = dylib_path
        self.pipe_depth = max(1, int(pipe_depth))
        self.compute_mode = int(compute_mode)

        cfg = json.loads((laya_dir / "rl_agent_config.json").read_text(encoding="utf-8"))
        self.temperature = [float(x) for x in cfg.get("temperature", [1.0, 1.0, 1.0])]
        self.temperature_by_options = {str(k): float(v) for k, v in cfg.get("temperature_by_options", {}).items()}
        self.max_len = 512
        self.head_max_len = 192

        tok_path = laya_dir / "tokenizer" / "tokenizer.json"
        self.tok = Tokenizer.from_file(str(tok_path))
        self.tok.no_truncation()
        self.tok.no_padding()
        self.cls_id = int(self.tok.token_to_id("[CLS]") or 50281)
        self.sep_id = int(self.tok.token_to_id("[SEP]") or 50282)
        self.pad_id = int(self.tok.token_to_id("[PAD]") or 50283)
        self.mask_id = int(self.tok.token_to_id("[MASK]") or 50284)
        self.mask_tok = "[MASK]"

        emb = np.load(laya_dir / "laya_typed_emb_f16.npz")
        self._word_f16 = np.ascontiguousarray(emb["word_f16"])
        self._type_f16 = np.ascontiguousarray(emb["type_f16"])
        H = int(self._word_f16.shape[1])
        vocab_sz = int(self._word_f16.shape[0])

        self._lib = ctypes.CDLL(str(dylib_path))
        self._lib.laya_ane_inspect_plan.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        self._lib.laya_ane_load.argtypes = [
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        self._lib.laya_ane_load.restype = ctypes.c_void_p
        self._lib.laya_ane_exec_batch.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self._lib.laya_ane_exec_batch.restype = ctypes.c_double
        self._lib.laya_ane_free.argtypes = [ctypes.c_void_p]

        self._mc_s256 = laya_dir / "laya_typed_s256_w8.mlmodelc"
        self._mc_s512 = laya_dir / "laya_typed_s512_w8.mlmodelc"
        if not self._mc_s512.exists():
            raise FileNotFoundError(f"Missing ANE bundle {self._mc_s512}. Run scripts/build_atomic_validators.py.")

        self._h512 = self._lib.laya_ane_load(
            str(self._mc_s512).encode("utf-8"),
            H,
            512,
            self.pipe_depth,
            self.compute_mode,
            self._word_f16.ctypes.data,
            vocab_sz,
            self._type_f16.ctypes.data,
        )
        if not self._h512:
            raise RuntimeError(f"Failed to load ANE bundle {self._mc_s512}")

        self._h256 = None
        if self._mc_s256.exists():
            self._h256 = self._lib.laya_ane_load(
                str(self._mc_s256).encode("utf-8"),
                H,
                256,
                self.pipe_depth,
                self.compute_mode,
                self._word_f16.ctypes.data,
                vocab_sz,
                self._type_f16.ctypes.data,
            )

    def inspect_compute_plans(self) -> dict[str, tuple[int, int, int]]:
        plans: dict[str, tuple[int, int, int]] = {}
        for tag, mc in (("s256", self._mc_s256), ("s512", self._mc_s512)):
            if mc.exists():
                counts = (ctypes.c_int * 3)()
                self._lib.laya_ane_inspect_plan(str(mc).encode("utf-8"), self.compute_mode, counts)
                plans[tag] = (int(counts[0]), int(counts[1]), int(counts[2]))
        return plans

    def _encode_ids(self, text: str) -> list[int]:
        return list(self.tok.encode(text, add_special_tokens=False).ids)

    def encode_item(self, state: Any, qdef: Mapping[str, Any], *, max_len: int | None = None) -> dict[str, Any]:
        eff_max = min(self.max_len, int(max_len)) if max_len is not None else self.max_len
        eff_head = min(self.head_max_len, 128) if eff_max <= 256 else self.head_max_len
        t = str(qdef["type"])
        crit = qdef.get("criteria")
        if t == "choice":
            items = [(c, None) for c in crit] if isinstance(crit, list) else list((crit or {}).items())
            opts = [k if not v else f"{k}: {v}" for k, v in items]
        elif t == "score":
            opts = [f"level {i}: {c}" for i, c in enumerate(crit or ())]
        else:
            c_map = crit if isinstance(crit, Mapping) else {}
            opts = [
                "false: " + str(c_map.get("false") or "no, the statement does not hold"),
                "true: " + str(c_map.get("true") or "yes, the statement holds"),
            ]
        ins_raw = qdef["instructions"] if isinstance(qdef["instructions"], str) else json.dumps(qdef["instructions"])
        ins = str(ins_raw).replace(self.mask_tok, " ")
        head_ids = self._encode_ids(f"{t} question: {ins}")
        opt_cap = 32 if eff_max <= 256 else 48
        opt_ids: list[list[int]] = []
        for opt_s in opts:
            opt_ids.append([self.mask_id] + self._encode_ids(" " + opt_s.replace(self.mask_tok, " "))[:opt_cap])
        opt_budget = eff_head - sum(len(o) for o in opt_ids)
        if opt_budget < 16:
            per = max(4, (eff_head - 16) // max(1, len(opt_ids)))
            opt_ids = [o[:per] for o in opt_ids]
            opt_budget = eff_head - sum(len(o) for o in opt_ids)
        head_ids = head_ids[: max(8, opt_budget)]
        ids = [self.cls_id] + head_ids + [self.sep_id]
        markers: list[int] = []
        for o in opt_ids:
            markers.append(len(ids))
            ids.extend(o)
        ids.append(self.sep_id)
        room = max(0, eff_max - len(ids) - 1)
        state_str = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)
        st_ids = self._encode_ids(state_str.replace(self.mask_tok, " "))[:room]
        ids = (ids + st_ids + [self.sep_id])[:eff_max]
        return {"ids": ids, "markers": markers, "qtype": _QTYPES[t], "k": len(opts)}

    def _exec_bucket(self, bucket_items: list[dict[str, Any]], S: int, handle: Any) -> Any:
        np = self._np
        N = len(bucket_items)
        ids_np = np.full((N, S), self.pad_id, dtype=np.int32)
        vl_np = np.zeros((N,), dtype=np.int32)
        qt_np = np.zeros((N,), dtype=np.int32)
        for i, it in enumerate(bucket_items):
            ln = min(S, len(it["ids"]))
            ids_np[i, :ln] = it["ids"][:ln]
            vl_np[i] = ln
            qt_np[i] = it["qtype"]
        out_pos = np.empty((N, S), dtype=np.float32)
        with self._exec_lock:
            self._lib.laya_ane_exec_batch(
                handle,
                N,
                ids_np.ctypes.data,
                vl_np.ctypes.data,
                qt_np.ctypes.data,
                out_pos.ctypes.data,
                1 if N > 1 else 0,
            )
        return out_pos

    def score_noul_batch(self, encoded_items: list[dict[str, Any]]) -> list[float]:
        """Execute ANE inference across `S=256` / `S=512` buckets and return `P(true)` per item."""
        if not encoded_items:
            return []
        p_true = [0.5] * len(encoded_items)
        idx_256: list[int] = []
        idx_512: list[int] = []
        for idx, it in enumerate(encoded_items):
            if self._h256 is not None and len(it["ids"]) <= 256:
                idx_256.append(idx)
            else:
                idx_512.append(idx)

        temp = float(self.temperature_by_options.get("noul:2", self.temperature[2]))
        if idx_256:
            out256 = self._exec_bucket([encoded_items[i] for i in idx_256], 256, self._h256)
            for b_i, orig_i in enumerate(idx_256):
                mk = encoded_items[orig_i]["markers"]
                _, p1 = _softmax_2(float(out256[b_i, mk[0]]), float(out256[b_i, mk[1]]), temp)
                p_true[orig_i] = p1
        if idx_512:
            out512 = self._exec_bucket([encoded_items[i] for i in idx_512], 512, self._h512)
            for b_i, orig_i in enumerate(idx_512):
                mk = encoded_items[orig_i]["markers"]
                _, p1 = _softmax_2(float(out512[b_i, mk[0]]), float(out512[b_i, mk[1]]), temp)
                p_true[orig_i] = p1
        return p_true

    def score_choice_batch(
        self,
        encoded_items: list[dict[str, Any]],
        *,
        temperature_override: float | None = None,
    ) -> list[list[float]]:
        """Execute ANE `Choice(K)` inference across `S=256` / `S=512` buckets and return calibrated option probs."""
        if not encoded_items:
            return []
        probs_out: list[list[float]] = [[] for _ in encoded_items]
        idx_256: list[int] = []
        idx_512: list[int] = []
        for idx, it in enumerate(encoded_items):
            if self._h256 is not None and len(it["ids"]) <= 256:
                idx_256.append(idx)
            else:
                idx_512.append(idx)

        def _row_probs(row_arr: Any, markers: list[int], S_lim: int) -> list[float]:
            valid_mk = [m for m in markers if m < S_lim]
            k = len(valid_mk)
            if k == 0:
                return []
            if temperature_override is not None:
                t_val = float(temperature_override)
            elif k == 2:
                t_val = float(self.temperature_by_options.get("choice:2", self.temperature[0]))
            elif k <= 5:
                t_val = float(self.temperature_by_options.get("choice:3-5", self.temperature[0]))
            elif k <= 10:
                t_val = float(self.temperature_by_options.get("choice:6-10", self.temperature[0]))
            else:
                t_val = float(self.temperature_by_options.get("choice:11+", 1.0))
            inv_t = 1.0 / max(t_val, 0.05)
            zs = [float(row_arr[m]) * inv_t for m in valid_mk]
            m_z = max(zs)
            ezs = [math.exp(z - m_z) for z in zs]
            s_z = sum(ezs)
            return [e / s_z for e in ezs]

        if idx_256:
            out256 = self._exec_bucket([encoded_items[i] for i in idx_256], 256, self._h256)
            for b_i, orig_i in enumerate(idx_256):
                probs_out[orig_i] = _row_probs(out256[b_i], encoded_items[orig_i]["markers"], 256)
        if idx_512:
            out512 = self._exec_bucket([encoded_items[i] for i in idx_512], 512, self._h512)
            for b_i, orig_i in enumerate(idx_512):
                probs_out[orig_i] = _row_probs(out512[b_i], encoded_items[orig_i]["markers"], 512)
        return probs_out

    def close(self) -> None:
        if getattr(self, "_h256", None):
            self._lib.laya_ane_free(self._h256)
            self._h256 = None
        if getattr(self, "_h512", None):
            self._lib.laya_ane_free(self._h512)
            self._h512 = None


# ---------------------------------------------------------------------------
# 2. Pure-MLX Backend: `Kev-0.8B r15` (`W8`/`BF16`, `B=8` Batched + `@mx.compile`)
# ---------------------------------------------------------------------------


def _kev_render(v: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return str(v)
    if isinstance(v, list):
        return "\n".join(f"{pad}- {_kev_render(x, indent + 1).lstrip()}" for x in v)
    if isinstance(v, Mapping):
        return "\n".join(
            f"{pad}{k}:\n{_kev_render(x, indent + 1)}"
            if isinstance(x, (Mapping, list))
            else f"{pad}{k}: {_kev_render(x)}"
            for k, x in v.items()
        )
    return str(v)


def _build_qwen35_backbone(
    text_cfg: Mapping[str, Any],
    weights: dict[str, Any],
    *,
    quant_cfg: Mapping[str, Any] | None = None,
) -> Any:
    """Build self-contained MLX `Qwen3_5TextModel` (`W8` quantized or `BF16`, batched left-pad ready)."""
    import mlx.core as mx
    import mlx.nn as nn

    gdn_packed_kernel = mx.fast.metal_kernel(
        name="kev_gated_delta_step_packed_btree",
        input_names=["q", "k", "v", "g", "beta", "state_in", "T"],
        output_names=["y", "acc_f32"],
        source=_GDN_PACKED_BTREE_SRC,
    )

    @partial(mx.compile, shapeless=True)
    def _fused_swiglu(gate: Any, up: Any) -> Any:
        return nn.silu(gate) * up

    @partial(mx.compile, shapeless=True)
    def _fused_precise_gate(xn: Any, gate: Any) -> Any:
        gf = nn.silu(gate.astype(mx.float32))
        xf = xn.astype(mx.float32)
        return (gf * xf).astype(xn.dtype)

    @partial(mx.compile, shapeless=True)
    def _fused_compute_g(A_log: Any, a: Any, dt_bias: Any) -> Any:
        return mx.exp(
            -mx.exp(A_log.astype(mx.float32))
            * nn.softplus(a.astype(mx.float32) + dt_bias.astype(mx.float32))
        )

    hidden_size = int(text_cfg["hidden_size"])
    intermediate_size = int(text_cfg["intermediate_size"])
    num_layers = int(text_cfg["num_hidden_layers"])
    num_q_heads = int(text_cfg["num_attention_heads"])
    num_kv_heads = int(text_cfg["num_key_value_heads"])
    head_dim = int(text_cfg.get("head_dim") or (hidden_size // num_q_heads))
    rms_eps = float(text_cfg.get("rms_norm_eps", 1e-6))
    vocab_size = int(text_cfg["vocab_size"])
    fa_interval = int(text_cfg.get("full_attention_interval", 4))
    num_v_heads = int(text_cfg["linear_num_value_heads"])
    num_k_heads = int(text_cfg["linear_num_key_heads"])
    head_k_dim = int(text_cfg["linear_key_head_dim"])
    head_v_dim = int(text_cfg["linear_value_head_dim"])
    conv_k = int(text_cfg.get("linear_conv_kernel_dim", 4))
    rope_p = text_cfg.get("rope_parameters") or {}
    rope_theta = float(rope_p.get("rope_theta", 10000000.0))
    partial_rotary = float(rope_p.get("partial_rotary_factor", 0.25))
    rot_dims = int(head_dim * partial_rotary)
    half_rot = rot_dims // 2
    inv_freq = mx.array(
        [1.0 / (rope_theta ** (float(i) / float(rot_dims))) for i in range(0, rot_dims, 2)],
        dtype=mx.float32,
    )

    def _apply_partial_rope(x: Any, pos_2d: Any) -> Any:
        # x: [B, H, L, head_dim], pos_2d: [B, L] int32/float32 true token positions
        angles = (pos_2d.astype(mx.float32)[:, None, :, None]) * inv_freq[None, None, None, :]
        cos_a = mx.cos(angles).astype(x.dtype)
        sin_a = mx.sin(angles).astype(x.dtype)
        x_rot, x_pass = mx.split(x, [rot_dims], axis=-1)
        x0, x1 = mx.split(x_rot, [half_rot], axis=-1)
        y0 = x0 * cos_a - x1 * sin_a
        y1 = x1 * cos_a + x0 * sin_a
        return mx.concatenate([y0, y1, x_pass], axis=-1)

    class _DeltaCache:
        def __init__(self, conv_state: Any = None, rec_state: Any = None) -> None:
            self.conv_state = conv_state
            self.rec_state = rec_state

        def select_rows(self, row_indices: Any) -> "_DeltaCache":
            cs = mx.take(self.conv_state, row_indices, axis=0) if self.conv_state is not None else None
            rs = mx.take(self.rec_state, row_indices, axis=0) if self.rec_state is not None else None
            return _DeltaCache(cs, rs)

    class _FullAttnCache:
        def __init__(self, keys: Any = None, values: Any = None, offset: int = 0) -> None:
            self.keys = keys
            self.values = values
            self.offset = offset

        def update_and_fetch(self, k_new: Any, v_new: Any) -> tuple[Any, Any]:
            if self.keys is None:
                self.keys = k_new
                self.values = v_new
            else:
                self.keys = mx.concatenate([self.keys, k_new], axis=2)
                self.values = mx.concatenate([self.values, v_new], axis=2)
            self.offset += int(k_new.shape[2])
            return self.keys, self.values

        def select_rows(self, row_indices: Any) -> "_FullAttnCache":
            ks = mx.take(self.keys, row_indices, axis=0) if self.keys is not None else None
            vs = mx.take(self.values, row_indices, axis=0) if self.values is not None else None
            return _FullAttnCache(ks, vs, self.offset)

    class _RMSNormGated(nn.Module):
        def __init__(self, d: int, eps: float) -> None:
            super().__init__()
            self.eps = eps
            self.weight = mx.ones((d,), dtype=mx.bfloat16)

        def __call__(self, x: Any, gate: Any) -> Any:
            xn = mx.fast.rms_norm(x, self.weight, self.eps)
            return _fused_precise_gate(xn, gate)

    class _GatedDeltaLayer(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.key_dim = head_k_dim * num_k_heads
            self.value_dim = head_v_dim * num_v_heads
            self.conv_dim = self.key_dim * 2 + self.value_dim
            self.conv1d = nn.Conv1d(
                in_channels=self.conv_dim,
                out_channels=self.conv_dim,
                bias=False,
                kernel_size=conv_k,
                groups=self.conv_dim,
                padding=0,
            )
            self.in_proj_qkv = nn.Linear(hidden_size, self.conv_dim, bias=False)
            self.in_proj_z = nn.Linear(hidden_size, self.value_dim, bias=False)
            self.in_proj_b = nn.Linear(hidden_size, num_v_heads, bias=False)
            self.in_proj_a = nn.Linear(hidden_size, num_v_heads, bias=False)
            self.dt_bias = mx.ones((num_v_heads,), dtype=mx.bfloat16)
            self.A_log = mx.zeros((num_v_heads,), dtype=mx.bfloat16)
            self.norm = _RMSNormGated(head_v_dim, rms_eps)
            self.out_proj = nn.Linear(self.value_dim, hidden_size, bias=False)
            self._inv_scale = head_k_dim**-0.5
            self._rms_eps = 1e-6 * (self._inv_scale**2)

        def __call__(self, x: Any, cache: _DeltaCache, valid_token_scale: Any | None = None) -> Any:
            B, S, _ = x.shape
            qkv = self.in_proj_qkv(x)
            if valid_token_scale is not None:
                qkv = qkv * valid_token_scale
            z = self.in_proj_z(x).reshape(B, S, num_v_heads, head_v_dim)
            b = self.in_proj_b(x)
            a = self.in_proj_a(x)

            conv_state = (
                cache.conv_state
                if cache.conv_state is not None
                else mx.zeros((B, conv_k - 1, self.conv_dim), dtype=x.dtype)
            )
            conv_in = mx.concatenate([conv_state, qkv], axis=1)
            cache.conv_state = mx.contiguous(conv_in[:, -(conv_k - 1) :, :])
            conv_out = nn.silu(self.conv1d(conv_in))

            q_raw, k_raw, v = mx.split(conv_out, [self.key_dim, 2 * self.key_dim], axis=-1)
            q = q_raw.reshape(B, S, num_k_heads, head_k_dim)
            k = k_raw.reshape(B, S, num_k_heads, head_k_dim)
            v = v.reshape(B, S, num_v_heads, head_v_dim)

            s_q = mx.array(self._inv_scale**2, dtype=q.dtype)
            s_k = mx.array(self._inv_scale, dtype=k.dtype)
            q = mx.fast.rms_norm(q, None, self._rms_eps) * s_q
            k = mx.fast.rms_norm(k, None, self._rms_eps) * s_k

            beta = mx.sigmoid(b)
            if valid_token_scale is not None:
                # Zeroing beta on left-pad slots keeps initial rec_state == 0.0 bit-identical to unpadded B=1!
                beta = beta * valid_token_scale
            g = _fused_compute_g(self.A_log, a, self.dt_bias)
            rec_state = (
                cache.rec_state
                if cache.rec_state is not None
                else mx.zeros((B, num_v_heads, head_v_dim, head_k_dim), dtype=mx.float32)
            )
            T = int(k.shape[1])
            y, new_state = gdn_packed_kernel(
                inputs=[q, k, v, g, beta, rec_state, T],
                template=[
                    ("InT", q.dtype),
                    ("StT", mx.float32),
                    ("Dk", head_k_dim),
                    ("Dv", head_v_dim),
                    ("Hk", num_k_heads),
                    ("Hv", num_v_heads),
                ],
                grid=(32, head_v_dim // 8, B * num_v_heads),
                threadgroup=(32, 2, 1),
                output_shapes=[(B, T, num_v_heads, head_v_dim), rec_state.shape],
                output_dtypes=[q.dtype, mx.float32],
            )
            cache.rec_state = new_state
            out = self.norm(y, z)
            return self.out_proj(out.reshape(B, S, -1))

    class _GatedFullAttention(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.scale = head_dim**-0.5
            self.q_proj = nn.Linear(hidden_size, num_q_heads * head_dim * 2, bias=False)
            self.k_proj = nn.Linear(hidden_size, num_kv_heads * head_dim, bias=False)
            self.v_proj = nn.Linear(hidden_size, num_kv_heads * head_dim, bias=False)
            self.o_proj = nn.Linear(num_q_heads * head_dim, hidden_size, bias=False)
            self.q_norm = nn.RMSNorm(head_dim, eps=rms_eps)
            self.k_norm = nn.RMSNorm(head_dim, eps=rms_eps)
            self.rope = nn.RoPE(rot_dims, traditional=False, base=rope_theta)

        def __call__(
            self,
            x: Any,
            cache: _FullAttnCache,
            attn_mask: Any = "causal",
            pos_2d: Any | None = None,
        ) -> Any:
            B, L, _ = x.shape
            qp = self.q_proj(x)
            queries, gate = mx.split(qp.reshape(B, L, num_q_heads, -1), 2, axis=-1)
            gate = gate.reshape(B, L, -1)
            keys = self.k_proj(x).reshape(B, L, num_kv_heads, head_dim)
            values = self.v_proj(x).reshape(B, L, num_kv_heads, head_dim).transpose(0, 2, 1, 3)
            queries = self.q_norm(queries).transpose(0, 2, 1, 3)
            keys = self.k_norm(keys).transpose(0, 2, 1, 3)

            if pos_2d is not None:
                queries = _apply_partial_rope(queries, pos_2d)
                keys = _apply_partial_rope(keys, pos_2d)
            else:
                off = cache.offset
                queries = self.rope(queries, offset=off)
                keys = self.rope(keys, offset=off)
            keys, values = cache.update_and_fetch(keys, values)

            eff_mask = (None if L == 1 else "causal") if attn_mask == "causal" else attn_mask
            out = mx.fast.scaled_dot_product_attention(
                queries,
                keys,
                values,
                scale=self.scale,
                mask=eff_mask,
            )
            out = out.transpose(0, 2, 1, 3).reshape(B, L, -1)
            return self.o_proj(out * mx.sigmoid(gate))

    class _SwiGLU(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.gate_proj = nn.Linear(hidden_size, intermediate_size, bias=False)
            self.down_proj = nn.Linear(intermediate_size, hidden_size, bias=False)
            self.up_proj = nn.Linear(hidden_size, intermediate_size, bias=False)

        def __call__(self, x: Any) -> Any:
            return self.down_proj(_fused_swiglu(self.gate_proj(x), self.up_proj(x)))

    class _DecoderBlock(nn.Module):
        def __init__(self, idx: int) -> None:
            super().__init__()
            self.is_linear = (idx + 1) % fa_interval != 0
            if self.is_linear:
                self.linear_attn = _GatedDeltaLayer()
            else:
                self.self_attn = _GatedFullAttention()
            self.input_layernorm = nn.RMSNorm(hidden_size, eps=rms_eps)
            self.post_attention_layernorm = nn.RMSNorm(hidden_size, eps=rms_eps)
            self.mlp = _SwiGLU()

        def __call__(
            self,
            x: Any,
            cache: Any,
            *,
            valid_token_scale: Any | None = None,
            attn_mask: Any = "causal",
            pos_2d: Any | None = None,
        ) -> Any:
            if self.is_linear:
                h = x + self.linear_attn(self.input_layernorm(x), cache, valid_token_scale=valid_token_scale)
            else:
                h = x + self.self_attn(self.input_layernorm(x), cache, attn_mask=attn_mask, pos_2d=pos_2d)
            return h + self.mlp(self.post_attention_layernorm(h))

    class _Qwen35Backbone(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.embed_tokens = nn.Embedding(vocab_size, hidden_size)
            self.layers = [_DecoderBlock(i) for i in range(num_layers)]
            self.norm = nn.RMSNorm(hidden_size, eps=rms_eps)

        def make_cache(self) -> list[Any]:
            return [_DeltaCache() if blk.is_linear else _FullAttnCache() for blk in self.layers]

        @staticmethod
        def select_cache_rows(cache: list[Any], row_indices: Any) -> list[Any]:
            return [c.select_rows(row_indices) for c in cache]

        def __call__(
            self,
            input_ids: Any,
            cache: list[Any],
            *,
            valid_token_scale: Any | None = None,
            attn_mask: Any = "causal",
            pos_2d: Any | None = None,
        ) -> Any:
            h = self.embed_tokens(input_ids)
            for idx in range(len(self.layers)):
                h = self.layers[idx](
                    h,
                    cache[idx],
                    valid_token_scale=valid_token_scale,
                    attn_mask=attn_mask,
                    pos_2d=pos_2d,
                )
            return self.norm(h)

    backbone = _Qwen35Backbone()
    if quant_cfg is not None:
        nn.quantize(
            backbone,
            group_size=int(quant_cfg.get("group_size", 64)),
            bits=int(quant_cfg.get("bits", 8)),
        )
    model_items = [(k[len("model.") :], v) for k, v in weights.items() if k.startswith("model.")]
    backbone.load_weights(model_items, strict=True)
    backbone.eval()
    mx.eval(backbone.parameters())
    return backbone


class _Kev08bMlxBackend:
    """Metal MLX `Kev-0.8B r15` runner with `W8` quantization + left-padded `B=8` cross-doc batching."""

    def __init__(
        self,
        kev_dir: Path,
        *,
        quant_mode: Literal["auto", "w8", "bf16"] = "auto",
        batch_docs: int = 8,
        max_state: int = 1024,
        max_branch: int = 2048,
    ) -> None:
        import mlx.core as mx
        import numpy as np
        from tokenizers import Tokenizer

        self._mx = mx
        self._np = np
        self.kev_dir = kev_dir
        self.batch_docs = max(1, int(batch_docs))
        self.max_state = int(max_state)
        self.max_branch = int(max_branch)

        w8_sf = kev_dir / "model_w8.safetensors"
        w8_meta = kev_dir / "kev_meta_w8.json"
        bf16_sf = kev_dir / "model.safetensors"
        bf16_meta = kev_dir / "kev_meta.json"
        tok_p = kev_dir / "tokenizer.json"

        use_w8 = (quant_mode == "w8") or (quant_mode == "auto" and w8_sf.exists() and w8_meta.exists())
        self.quant_mode: Literal["w8", "bf16"] = "w8" if use_w8 else "bf16"
        sf_p = w8_sf if use_w8 else bf16_sf
        meta_p = w8_meta if use_w8 else bf16_meta
        if not (meta_p.exists() and sf_p.exists() and tok_p.exists()):
            raise FileNotFoundError(f"Missing Kev-0.8B artifacts in {kev_dir}. Run scripts/build_atomic_validators.py.")

        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        self.quantization = meta.get("quantization")
        self.native_temperature = float(meta["native_temperature"])
        self.special_ids = [int(x) for x in meta["special_ids"]]
        self.pad_id = int(meta["pad_id"])

        self.tok = Tokenizer.from_file(str(tok_p))
        self.tok.no_truncation()
        self.tok.no_padding()

        mx.set_cache_limit(1 << 30)
        weights = mx.load(str(sf_p))
        self.q_w = np.asarray(weights["pointer_head.q_weight"].astype(mx.float32))
        self.q_b = np.asarray(weights["pointer_head.q_bias"].astype(mx.float32))
        self.k_w = np.asarray(weights["pointer_head.k_weight"].astype(mx.float32))
        self.k_b = np.asarray(weights["pointer_head.k_bias"].astype(mx.float32))
        self.ptr_scale = 1.0 / math.sqrt(float(self.q_w.shape[0]))

        self.backbone = _build_qwen35_backbone(meta["text_config"], weights, quant_cfg=self.quantization)
        del weights
        mx.clear_cache()

    def _user_tokens(self, text: str) -> list[int]:
        return list(self.tok.encode(_KEV_SPECIAL_RE.sub(r"<¦\1¦>", text), add_special_tokens=False).ids)

    def encode_questions(self, state: Any, questions: Sequence[Mapping[str, Any]]) -> tuple[list[int], list[dict[str, Any]]]:
        s_toks = self._user_tokens(_kev_render(state))
        state_ids = [self.special_ids[0]] + s_toks[: self.max_state - 1]
        q_id, o_id, c_id, d_id = self.special_ids[1:]

        rows: list[dict[str, Any]] = []
        for qdef in questions:
            t = str(qdef["type"])
            crit = qdef.get("criteria")
            if t == "noul":
                cm = crit if isinstance(crit, Mapping) else {}
                f_desc = cm.get("false")
                t_desc = cm.get("true")
                opts = [
                    "no" if not f_desc else f"no: {_kev_render(f_desc)}",
                    "yes" if not t_desc else f"yes: {_kev_render(t_desc)}",
                ]
            elif t == "choice":
                if isinstance(crit, list):
                    opts = [str(x) for x in crit]
                else:
                    opts = [k if not v else f"{k}: {_kev_render(v)}" for k, v in (crit or {}).items()]
            else:
                opts = [_kev_render(x) for x in (crit or ())]

            instr = [q_id] + self._user_tokens(_kev_render(qdef.get("instructions")))
            spans = [[o_id] + self._user_tokens(o) + [c_id] for o in opts]
            br = instr + [tid for sp in spans for tid in sp] + [d_id]
            if len(state_ids) + len(br) > self.max_branch:
                br = br[: self.max_branch - len(state_ids) - 1] + [d_id]
            ends: list[int] = []
            cursor = len(instr)
            for sp in spans:
                cursor += len(sp)
                ends.append(min(cursor - 1, len(br) - 2))
            rows.append({"ids": br, "decide": len(br) - 1, "opts": ends, "k": len(opts)})
        return state_ids, rows

    def _pointer_probs_from_hidden(self, h_row_f32: Any, decide_idx: int, opt_indices: list[int]) -> tuple[float, list[float]]:
        h_dec = h_row_f32[decide_idx]
        h_opt = h_row_f32[opt_indices]
        q_vec = h_dec @ self.q_w.T + self.q_b
        k_mat = h_opt @ self.k_w.T + self.k_b
        raw_z = ((k_mat @ q_vec) * self.ptr_scale).tolist()
        _, p1 = _softmax_2(float(raw_z[0]), float(raw_z[1]), self.native_temperature)
        return p1, [float(x) for x in raw_z]

    def score_state_noul(self, state: Any, questions: Sequence[Mapping[str, Any]]) -> list[tuple[float, list[float]]]:
        """Single-document fast path."""
        return self.score_multi_states_noul([(state, questions)])[0]

    def score_multi_states_noul(
        self,
        items: Sequence[tuple[Any, Sequence[Mapping[str, Any]]]],
        *,
        batch_docs: int | None = None,
    ) -> list[list[tuple[float, list[float]]]]:
        """Batch `B` document states via left-padded hybrid prefill + `[sum(Q_b), L_br]` parallel branch pass."""
        if not items:
            return []
        mx = self._mx
        np = self._np
        eff_b = max(1, int(batch_docs or self.batch_docs))

        # Sort by state token length to minimize left-padding waste across waves
        encoded_all = [self.encode_questions(st, qs) for st, qs in items]
        order = sorted(range(len(items)), key=lambda idx: len(encoded_all[idx][0]))
        out_by_orig: list[list[tuple[float, list[float]]]] = [[] for _ in items]

        for wave_start in range(0, len(order), eff_b):
            wave_orig = order[wave_start : wave_start + eff_b]
            B = len(wave_orig)

            if B == 1:
                orig_0 = wave_orig[0]
                state_ids, rows = encoded_all[orig_0]
                if not rows:
                    out_by_orig[orig_0] = []
                    continue
                cache = self.backbone.make_cache()
                h_st = self.backbone(mx.array([state_ids], dtype=mx.int32), cache)
                mx.eval(h_st)

                br_cache = (
                    cache
                    if len(rows) == 1
                    else self.backbone.select_cache_rows(cache, mx.zeros((len(rows),), dtype=mx.int32))
                )
                max_l = max(len(r["ids"]) for r in rows)
                ids_mx = mx.array([r["ids"] + [self.pad_id] * (max_l - len(r["ids"])) for r in rows], dtype=mx.int32)
                h_mx = self.backbone(ids_mx, br_cache)
                mx.eval(h_mx)
                h_np = np.asarray(h_mx.astype(mx.float32))
                out_by_orig[orig_0] = [
                    self._pointer_probs_from_hidden(h_np[ri], r["decide"], r["opts"])
                    for ri, r in enumerate(rows)
                ]
                continue

            # Left-padded multi-document prefill (`B >= 2`)
            state_lists = [encoded_all[idx][0] for idx in wave_orig]
            s_lens = [len(s) for s in state_lists]
            s_max = max(s_lens)
            pad_lens = [s_max - ln for ln in s_lens]

            st_np = np.full((B, s_max), self.pad_id, dtype=np.int32)
            valid_np = np.zeros((B, s_max, 1), dtype=np.float32)
            pos_st_np = np.zeros((B, s_max), dtype=np.int32)
            mask_st_np = np.full((B, 1, s_max, s_max), -1e9, dtype=np.float32)

            for b_i in range(B):
                pl = pad_lens[b_i]
                ln = s_lens[b_i]
                st_np[b_i, pl:] = state_lists[b_i]
                valid_np[b_i, pl:, 0] = 1.0
                pos_st_np[b_i, pl:] = np.arange(ln, dtype=np.int32)
                for q_t in range(pl, s_max):
                    mask_st_np[b_i, 0, q_t, pl : q_t + 1] = 0.0

            cache = self.backbone.make_cache()
            h_st = self.backbone(
                mx.array(st_np, dtype=mx.int32),
                cache,
                valid_token_scale=mx.array(valid_np).astype(mx.bfloat16),
                attn_mask=mx.array(mask_st_np).astype(mx.bfloat16),
                pos_2d=mx.array(pos_st_np, dtype=mx.int32),
            )
            mx.eval(h_st)

            # Gather all branches across the `B` cached states into 1 batched GPU forward pass
            flat_rows: list[dict[str, Any]] = []
            owner_b: list[int] = []
            doc_slices: list[tuple[int, int]] = []
            for b_i, orig_i in enumerate(wave_orig):
                _, rows = encoded_all[orig_i]
                st_idx = len(flat_rows)
                flat_rows.extend(rows)
                owner_b.extend([b_i] * len(rows))
                doc_slices.append((st_idx, len(flat_rows)))

            if not flat_rows:
                continue

            N_br = len(flat_rows)
            max_br = max(len(r["ids"]) for r in flat_rows)
            br_np = np.full((N_br, max_br), self.pad_id, dtype=np.int32)
            pos_br_np = np.zeros((N_br, max_br), dtype=np.int32)
            mask_br_np = np.full((N_br, 1, max_br, s_max + max_br), -1e9, dtype=np.float32)

            for r_i, r in enumerate(flat_rows):
                b_i = owner_b[r_i]
                pl = pad_lens[b_i]
                sl = s_lens[b_i]
                bl = len(r["ids"])
                br_np[r_i, :bl] = r["ids"]
                pos_br_np[r_i] = sl + np.arange(max_br, dtype=np.int32)
                for q_t in range(max_br):
                    mask_br_np[r_i, 0, q_t, pl : s_max + q_t + 1] = 0.0

            br_cache = self.backbone.select_cache_rows(cache, mx.array(owner_b, dtype=mx.int32))
            h_br = self.backbone(
                mx.array(br_np, dtype=mx.int32),
                br_cache,
                valid_token_scale=None,
                attn_mask=mx.array(mask_br_np).astype(mx.bfloat16),
                pos_2d=mx.array(pos_br_np, dtype=mx.int32),
            )
            mx.eval(h_br)
            h_br_np = np.asarray(h_br.astype(mx.float32))

            flat_outs = [
                self._pointer_probs_from_hidden(h_br_np[ri], r["decide"], r["opts"])
                for ri, r in enumerate(flat_rows)
            ]
            for b_i, orig_i in enumerate(wave_orig):
                lo, hi = doc_slices[b_i]
                out_by_orig[orig_i] = flat_outs[lo:hi]

        return out_by_orig

    def close(self) -> None:
        self.backbone = None
        self._mx.clear_cache()


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
        self.mode: ValidatorMode = mode
        self.home_dir = _resolve_default_home(home)
        self.artifacts_dir = (
            Path(artifacts_dir).expanduser().resolve()
            if artifacts_dir is not None
            else self.home_dir / "artifacts" / "atomic_validators"
        )
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

        self.laya_backend: _LayaAneBackend | None = None
        self.kev_backend: _Kev08bMlxBackend | None = None

        if mode in ("laya-ane", "both"):
            dylib_p = _ensure_laya_dylib(self.home_dir)
            self.laya_backend = _LayaAneBackend(
                self.artifacts_dir / "laya_typed",
                dylib_p,
                pipe_depth=pipe_depth,
            )
        if mode in ("kev-0.8b", "both"):
            self.kev_backend = _Kev08bMlxBackend(
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
                    if __package__:
                        from .zero_llm_bypass_v6 import parse_ttf_form_v6
                    else:
                        from zero_llm_bypass_v6 import parse_ttf_form_v6  # type: ignore

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
]
