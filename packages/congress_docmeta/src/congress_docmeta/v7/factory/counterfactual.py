"""Deterministic adversarial counterfactual perturbations & flip assertions for DocMeta V7.2.

Implements Law 1 ("treat codebooks & rubrics as counterfactually tested code"):
- Misleading `-TTF-` and `-Wstate-` filename slug tests (verifies blind text-only invariance)
- Stripping `Present:` / `Members Present:` / `Staff Present:` headers (grounding rejection + abstention)
- Prepending multi-doc packet covers / TOCs (`is_packet` flips `False -> True`)
- Deleting dates & `issuer_org` mentions (grounding rejection + abstention)
- Corrupting to HTTP/blank stub (`status != usable => primary_genre is None`)
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import re
from typing import Any, Callable, Mapping, Sequence

from .grounding import verify_span_grounding


@dataclass
class CounterfactualCase:
    """One synthesized counterfactual test case paired with its baseline payload."""

    case_id: str
    kind: str
    source_doc_key: str
    original_text: str
    perturbed_text: str
    original_filename: str
    perturbed_filename: str
    original_payload: dict[str, Any]
    expected_abstained_payload: dict[str, Any]
    expectation: str


@dataclass
class CounterfactualCheckResult:
    """Assertion outcome for a single `CounterfactualCase`."""

    case_id: str
    kind: str
    passed: bool
    old_grounding_failed_as_expected: bool
    new_grounding_passed: bool
    verdict_assertion_passed: bool
    details: str


@dataclass
class CounterfactualSuiteReport:
    """Aggregate summary of `run_counterfactual_suite`."""

    total: int
    passed_count: int
    failed_count: int
    pass_rate: float
    evaluation_mode: str = "harness_mechanics_self_check"
    results: list[CounterfactualCheckResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "pass_rate": round(self.pass_rate, 4),
            "evaluation_mode": self.evaluation_mode,
            "results": [
                {
                    "case_id": r.case_id,
                    "kind": r.kind,
                    "passed": r.passed,
                    "old_grounding_failed_as_expected": r.old_grounding_failed_as_expected,
                    "new_grounding_passed": r.new_grounding_passed,
                    "verdict_assertion_passed": r.verdict_assertion_passed,
                    "details": r.details,
                }
                for r in self.results
            ],
        }


_PRESENT_BLOCK_RE = re.compile(
    r"(?im)^(?:members?\s+present|staff\s+present|present)\s*:.*(?:\n(?:[ \t]+.*|\s*(?:reps?\.|sens?\.|mr\.|ms\.|mrs\.|dr\.|hon\.).*))*",
)


def perturb_misleading_filename(
    doc: Mapping[str, Any],
    *,
    target_slug: str = "-TTF-",
) -> CounterfactualCase:
    """Attach a misleading `-TTF-` or `-Wstate-` House filename slug without altering text."""
    doc_key = str(doc.get("doc_key") or "sample")
    text = str(doc.get("text") or "")
    orig_fn = str(doc.get("filename") or "document.pdf")
    orig_payload = copy.deepcopy(dict(doc.get("payload") or {}))
    if target_slug == "-TTF-":
        bad_fn = "HHRG-118-GO00-TTF-CounterfactualA-20250401.pdf"
        kind = "misleading_ttf_filename"
        exp = "Blind extraction must ignore -TTF- filename slug and retain non-TTF genre."
    else:
        bad_fn = "HHRG-118-IF18-Wstate-CounterfactualB-20250401.pdf"
        kind = "misleading_wstate_filename"
        exp = "Blind extraction must ignore -Wstate- filename slug and retain non-witness_statement genre."

    return CounterfactualCase(
        case_id=f"{doc_key}:{kind}",
        kind=kind,
        source_doc_key=doc_key,
        original_text=text,
        perturbed_text=text,
        original_filename=orig_fn,
        perturbed_filename=bad_fn,
        original_payload=orig_payload,
        expected_abstained_payload=copy.deepcopy(orig_payload),
        expectation=exp,
    )


def perturb_strip_present_header(doc: Mapping[str, Any]) -> CounterfactualCase:
    """Strip `Present:` / `Members Present:` / `Staff Present:` header lines from text."""
    doc_key = str(doc.get("doc_key") or "sample")
    text = str(doc.get("text") or "")
    orig_fn = str(doc.get("filename") or "transcript.pdf")
    orig_payload = copy.deepcopy(dict(doc.get("payload") or {}))

    perturbed = _PRESENT_BLOCK_RE.sub("", text)
    # Also strip explicitly listed member/staff/persona names if they still remain in header.
    for key in ("members_present", "staff_present"):
        for item in orig_payload.get(key) or []:
            nm = item.get("name") if isinstance(item, Mapping) else item
            if isinstance(nm, str) and nm.strip():
                perturbed = re.sub(re.escape(nm), "[REDACTED]", perturbed, flags=re.IGNORECASE)
    perturbed = re.sub(r"\n{3,}", "\n\n", perturbed).strip()

    abstained = copy.deepcopy(orig_payload)
    for key in ("members_present", "staff_present"):
        if key in abstained:
            abstained[key] = []
    # Filter personas whose names no longer appear in perturbed text.
    if isinstance(abstained.get("personas"), list):
        kept = []
        for p in abstained["personas"]:
            nm = p.get("name") if isinstance(p, Mapping) else p
            if isinstance(nm, str) and nm.lower() in perturbed.lower():
                kept.append(p)
        abstained["personas"] = kept
    # Re-check remaining spans in abstained against perturbed text.
    if not verify_span_grounding(perturbed, abstained).passed:
        abstained.pop("spans", None)
        abstained.pop("title_span", None)

    return CounterfactualCase(
        case_id=f"{doc_key}:strip_present_header",
        kind="strip_present_header",
        source_doc_key=doc_key,
        original_text=text,
        perturbed_text=perturbed,
        original_filename=orig_fn,
        perturbed_filename=orig_fn,
        original_payload=orig_payload,
        expected_abstained_payload=abstained,
        expectation="Stripped Present: personas must fail grounding on old payload and abstain in new payload.",
    )


def perturb_prepend_packet_cover(doc: Mapping[str, Any]) -> CounterfactualCase:
    """Prepend a multi-doc packet Table of Contents cover so `is_packet` flips False -> True."""
    doc_key = str(doc.get("doc_key") or "sample")
    text = str(doc.get("text") or "")
    orig_fn = str(doc.get("filename") or "single_doc.pdf")
    orig_payload = copy.deepcopy(dict(doc.get("payload") or {}))

    cover = (
        "COMMITTEE HEARING PACKET — TABLE OF CONTENTS\n"
        "Document 1: Witness Written Statement\n"
        "Document 2: Truth in Testimony Disclosure Form\n"
        "Document 3: Witness Biography\n"
        "--- BEGIN DOCUMENT 1 ---\n\n"
    )
    perturbed = cover + text
    flipped = copy.deepcopy(orig_payload)
    flipped["is_packet"] = True
    existing_kinds = list(flipped.get("contains_kinds") or [])
    for k in ("witness_statement", "truth_in_testimony_disclosure", "witness_biography"):
        if k not in existing_kinds:
            existing_kinds.append(k)
    flipped["contains_kinds"] = existing_kinds

    # Shift any explicit SpanRefs by len(cover) so expected payload stays strictly offset-grounded!
    shift = len(cover)
    def _shift_spans(obj: Any) -> None:
        if isinstance(obj, dict):
            if "quote" in obj and isinstance(obj.get("start"), int) and isinstance(obj.get("end"), int):
                obj["start"] += shift
                obj["end"] += shift
            for v in obj.values():
                _shift_spans(v)
        elif isinstance(obj, list):
            for it in obj:
                _shift_spans(it)

    _shift_spans(flipped)

    return CounterfactualCase(
        case_id=f"{doc_key}:prepend_packet_cover",
        kind="prepend_packet_cover",
        source_doc_key=doc_key,
        original_text=text,
        perturbed_text=perturbed,
        original_filename=orig_fn,
        perturbed_filename=orig_fn,
        original_payload=orig_payload,
        expected_abstained_payload=flipped,
        expectation="Packet cover prepend must flip is_packet from False to True while preserving status=usable.",
    )


def perturb_delete_dates_and_orgs(doc: Mapping[str, Any]) -> CounterfactualCase:
    """Delete date spans and `issuer_org` strings from text to test abstention & grounding."""
    doc_key = str(doc.get("doc_key") or "sample")
    text = str(doc.get("text") or "")
    orig_fn = str(doc.get("filename") or "dated_doc.pdf")
    orig_payload = copy.deepcopy(dict(doc.get("payload") or {}))

    perturbed = text
    for ds in orig_payload.get("date_spans") or []:
        val = ds.get("quote") if isinstance(ds, Mapping) else ds
        if isinstance(val, str) and val.strip():
            perturbed = re.sub(re.escape(val), "[DATE_REMOVED]", perturbed, flags=re.IGNORECASE)
    issuer_org = orig_payload.get("issuer_org")
    if isinstance(issuer_org, str) and issuer_org.strip():
        perturbed = re.sub(re.escape(issuer_org), "[ORG_REMOVED]", perturbed, flags=re.IGNORECASE)
    # Also redact common month/year dates if `date_spans` used formatted variants.
    perturbed = re.sub(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b",
        "[DATE_REMOVED]",
        perturbed,
        flags=re.IGNORECASE,
    )

    abstained = copy.deepcopy(orig_payload)
    abstained["date_spans"] = []
    abstained["doc_date"] = None
    if "event_date" in abstained:
        abstained["event_date"] = None
    if "issuer_org" in abstained:
        abstained["issuer_org"] = None
    if not verify_span_grounding(perturbed, abstained).passed:
        abstained.pop("spans", None)
        abstained.pop("title_span", None)

    return CounterfactualCase(
        case_id=f"{doc_key}:delete_dates_and_orgs",
        kind="delete_dates_and_orgs",
        source_doc_key=doc_key,
        original_text=text,
        perturbed_text=perturbed,
        original_filename=orig_fn,
        perturbed_filename=orig_fn,
        original_payload=orig_payload,
        expected_abstained_payload=abstained,
        expectation="Deleted dates/issuer_org must fail grounding on old payload and abstain in new payload.",
    )


def perturb_corrupt_to_error_stub(doc: Mapping[str, Any]) -> CounterfactualCase:
    """Replace text with an error stub verifying `status != usable => primary_genre is None`."""
    doc_key = str(doc.get("doc_key") or "sample")
    text = str(doc.get("text") or "")
    orig_fn = str(doc.get("filename") or "stub.pdf")
    orig_payload = copy.deepcopy(dict(doc.get("payload") or {}))

    perturbed = "403 Forbidden - Cloudflare Access Denied\nPage could not be retrieved."
    flipped = {
        "status": "error_or_block",
        "media_format": None,
        "is_packet": False,
        "contains_kinds": [],
        "primary_genre": None,
        "subkind": None,
        "date_spans": [],
        "issuer_org": None,
        "verbatim_title": None,
    }
    return CounterfactualCase(
        case_id=f"{doc_key}:corrupt_to_error_stub",
        kind="corrupt_to_error_stub",
        source_doc_key=doc_key,
        original_text=text,
        perturbed_text=perturbed,
        original_filename=orig_fn,
        perturbed_filename=orig_fn,
        original_payload=orig_payload,
        expected_abstained_payload=flipped,
        expectation="Corrupted error stub must flip status!=usable and primary_genre=None.",
    )


def _default_sample_docs() -> list[dict[str, Any]]:
    """Built-in canonical sample docs covering all counterfactual perturbation kinds."""
    transcript_text = (
        "HEARING TRANSCRIPT\n"
        "Committee on Oversight and Reform\n"
        "Present: Reps. Jordan, Connolly, and Porter.\n"
        "Staff Present: Mark Marin, Sarah Vance.\n"
        "May 14, 2025\n"
        "The Committee met, pursuant to notice, at 10:00 a.m. in Room 2154, Rayburn House Office Building."
    )
    qfr_text = (
        "Questions for the Record\n"
        "Submitted by Chairman James Comer\n"
        "Response of Dr. Elena Patel, U.S. Energy Information Administration\n"
        "July 9, 2024\n"
        "Question 1: Please clarify the baseline forecast assumptions."
    )
    invitation_text = (
        "Committee on Education and the Workforce\n"
        "April 2, 2025\n"
        "Dear Dr. Jordan Wine-Banks:\n"
        "You are invited to testify before the Subcommittee on Higher Education regarding accreditation reform."
    )
    return [
        {
            "doc_key": "cf_sample_transcript",
            "filename": "HHRG-119-GO00-Transcript-20250514.pdf",
            "text": transcript_text,
            "payload": {
                "status": "usable",
                "media_format": "prose",
                "is_packet": False,
                "primary_genre": "hearing_transcript",
                "verbatim_title": "HEARING TRANSCRIPT",
                "date_spans": ["May 14, 2025"],
                "doc_date": "2025-05-14",
                "members_present": [{"name": "Jordan"}, {"name": "Connolly"}, {"name": "Porter"}],
                "staff_present": [{"name": "Mark Marin"}, {"name": "Sarah Vance"}],
            },
        },
        {
            "doc_key": "cf_sample_qfr",
            "filename": "HHRG-118-IF18-Wstate-PatelE-20240709.pdf",
            "text": qfr_text,
            "payload": {
                "status": "usable",
                "media_format": "prose",
                "is_packet": False,
                "primary_genre": "qfr_document",
                "verbatim_title": "Questions for the Record",
                "date_spans": ["July 9, 2024"],
                "doc_date": "2024-07-09",
                "issuer_org": "U.S. Energy Information Administration",
                "personas": [{"name": "Dr. Elena Patel", "role": "witness"}],
            },
        },
        {
            "doc_key": "cf_sample_invitation",
            "filename": "HHRG-119-ED14-TTF-WineBanksJ-20250402.pdf",
            "text": invitation_text,
            "payload": {
                "status": "usable",
                "media_format": "prose",
                "is_packet": False,
                "primary_genre": "oversight_or_correspondence",
                "date_spans": ["April 2, 2025"],
                "doc_date": "2025-04-02",
                "personas": [{"name": "Dr. Jordan Wine-Banks", "role": "recipient"}],
            },
        },
    ]


def synthesize_counterfactual_cases(
    docs: Sequence[Mapping[str, Any]] | None = None,
) -> list[CounterfactualCase]:
    """Build deterministic counterfactual perturbations from sample docs."""
    source_docs = list(docs) if docs else _default_sample_docs()
    cases: list[CounterfactualCase] = []

    for doc in source_docs:
        payload = doc.get("payload") or {}
        genre = str(payload.get("primary_genre") or payload.get("primary_kind") or "")
        text = str(doc.get("text") or "")

        if genre not in {"truth_in_testimony_disclosure", "truth_in_testimony"}:
            cases.append(perturb_misleading_filename(doc, target_slug="-TTF-"))
        if genre not in {"witness_statement", "witness_testimony"}:
            cases.append(perturb_misleading_filename(doc, target_slug="-Wstate-"))
        if "present:" in text.casefold() or payload.get("members_present") or payload.get("staff_present"):
            cases.append(perturb_strip_present_header(doc))
        if not payload.get("is_packet"):
            cases.append(perturb_prepend_packet_cover(doc))
        if payload.get("date_spans") or payload.get("issuer_org"):
            cases.append(perturb_delete_dates_and_orgs(doc))
        cases.append(perturb_corrupt_to_error_stub(doc))
    return cases


def _default_offline_counterfactual_eval(
    text: str,
    *,
    filename: str,
    case: CounterfactualCase,
) -> dict[str, Any]:
    """Blind text-only baseline evaluator verifying grounding + packet/status rules."""
    del filename  # Blind evaluator MUST ignore misleading filenames!
    lower = text.casefold()
    if "403 forbidden" in lower or "access denied" in lower:
        return {
            "status": "error_or_block",
            "media_format": None,
            "is_packet": False,
            "contains_kinds": [],
            "primary_genre": None,
            "date_spans": [],
            "issuer_org": None,
        }

    out = copy.deepcopy(case.expected_abstained_payload)
    if "table of contents" in lower and "document 1:" in lower and "document 2:" in lower:
        out["is_packet"] = True
    return out


def run_counterfactual_suite(
    cases_or_docs: Sequence[CounterfactualCase | Mapping[str, Any]] | None = None,
    *,
    eval_fn: Callable[..., Mapping[str, Any]] | None = None,
) -> CounterfactualSuiteReport:
    """Execute counterfactual perturbation checks and return structured pass/fail report."""
    if not cases_or_docs:
        cases = synthesize_counterfactual_cases()
    elif isinstance(cases_or_docs[0], CounterfactualCase):
        cases = list(cases_or_docs)  # type: ignore[arg-type]
    else:
        cases = synthesize_counterfactual_cases(cases_or_docs)  # type: ignore[arg-type]

    results: list[CounterfactualCheckResult] = []
    for case in cases:
        old_gr = verify_span_grounding(case.perturbed_text, case.original_payload)
        if case.kind in {"strip_present_header", "delete_dates_and_orgs"}:
            old_failed_expected = not old_gr.passed
        else:
            old_failed_expected = True

        if eval_fn is not None:
            try:
                new_payload = dict(eval_fn(case.perturbed_text, filename=case.perturbed_filename, case=case))
            except TypeError:
                try:
                    new_payload = dict(eval_fn(case.perturbed_text, case.perturbed_filename))
                except TypeError:
                    new_payload = dict(eval_fn(case.perturbed_text))
        else:
            new_payload = _default_offline_counterfactual_eval(
                case.perturbed_text,
                filename=case.perturbed_filename,
                case=case,
            )

        new_gr = verify_span_grounding(case.perturbed_text, new_payload)
        new_passed = new_gr.passed

        orig_genre = case.original_payload.get("primary_genre") or case.original_payload.get("primary_kind")
        new_genre = new_payload.get("primary_genre") or new_payload.get("primary_kind")
        verdict_ok = True
        reason = "ok"

        if case.kind == "misleading_ttf_filename":
            verdict_ok = new_genre not in {"truth_in_testimony_disclosure", "truth_in_testimony"} and new_genre == orig_genre
            if not verdict_ok:
                reason = f"fooled_by_ttf_slug: orig={orig_genre!r}, new={new_genre!r}"
        elif case.kind == "misleading_wstate_filename":
            verdict_ok = new_genre not in {"witness_statement", "witness_testimony"} and new_genre == orig_genre
            if not verdict_ok:
                reason = f"fooled_by_wstate_slug: orig={orig_genre!r}, new={new_genre!r}"
        elif case.kind == "strip_present_header":
            verdict_ok = not new_payload.get("members_present") and not new_payload.get("staff_present")
            if not verdict_ok:
                reason = "failed_to_abstain_on_stripped_present_headers"
        elif case.kind == "prepend_packet_cover":
            verdict_ok = new_payload.get("is_packet") is True and new_payload.get("status") == "usable"
            if not verdict_ok:
                reason = f"packet_flag_did_not_flip: {new_payload.get('is_packet')!r}"
        elif case.kind == "delete_dates_and_orgs":
            verdict_ok = (not new_payload.get("date_spans")) and (new_payload.get("issuer_org") is None)
            if not verdict_ok:
                reason = "failed_to_abstain_on_deleted_dates_or_issuer_org"
        elif case.kind == "corrupt_to_error_stub":
            verdict_ok = new_payload.get("status") != "usable" and new_genre is None
            if not verdict_ok:
                reason = f"error_stub_invariant_failed: status={new_payload.get('status')!r}, genre={new_genre!r}"

        all_ok = old_failed_expected and new_passed and verdict_ok
        if not old_failed_expected:
            reason = "expected_old_payload_to_fail_grounding_on_perturbed_text"
        elif not new_passed:
            reason = f"new_payload_failed_grounding: {[e.reason for e in new_gr.errors]}"

        results.append(
            CounterfactualCheckResult(
                case_id=case.case_id,
                kind=case.kind,
                passed=all_ok,
                old_grounding_failed_as_expected=old_failed_expected,
                new_grounding_passed=new_passed,
                verdict_assertion_passed=verdict_ok,
                details=reason,
            )
        )

    passed_cnt = sum(1 for r in results if r.passed)
    total = len(results)
    return CounterfactualSuiteReport(
        total=total,
        passed_count=passed_cnt,
        failed_count=total - passed_cnt,
        pass_rate=(passed_cnt / total) if total else 1.0,
        evaluation_mode="live_evaluator" if eval_fn is not None else "harness_mechanics_self_check",
        results=results,
    )


__all__ = [
    "CounterfactualCase",
    "CounterfactualCheckResult",
    "CounterfactualSuiteReport",
    "perturb_corrupt_to_error_stub",
    "perturb_delete_dates_and_orgs",
    "perturb_misleading_filename",
    "perturb_prepend_packet_cover",
    "perturb_strip_present_header",
    "run_counterfactual_suite",
    "synthesize_counterfactual_cases",
]
