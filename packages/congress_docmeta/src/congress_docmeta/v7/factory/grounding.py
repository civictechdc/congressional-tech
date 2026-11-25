"""Deterministic span grounding, CheckEval 2-vs-1 adjudication & deadlock digests.

Implements:
- `verify_span_grounding` (`google/langextract` exact offset + normalized text rules)
  preventing Horizon 0's ungrounded transcript personas (31%), synthesized titles,
  ISO `date_spans` leakage, and unmentioned `issuer_org` acronym expansion.
- `repair_span_refs_in_payload`: pure helper usable inside `parse()` (never in cache key).
- `adjudicate_three_family` & `run_checkeval_arbiter` (EMNLP 2024 CheckEval binary
  Yes/No checklists for 2-vs-1 splits).
- `format_deadlock_digest`: concise Markdown summary for ~1-2% owner deadlock review.
"""

from __future__ import annotations

from collections import Counter
import copy
from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re
from typing import Any, Callable, Mapping, Sequence


TriageTuple = tuple[str | None, str | None, bool | None, str | None]

_HONORIFICS = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "miss",
        "dr",
        "hon",
        "honorable",
        "rep",
        "representative",
        "sen",
        "senator",
        "chair",
        "chairman",
        "chairwoman",
        "chairperson",
        "ranking",
        "member",
        "prof",
        "professor",
        "gen",
        "adm",
        "col",
        "maj",
        "capt",
        "lt",
        "cmdr",
        "rev",
        "amb",
        "ambassador",
        "gov",
        "governor",
        "sec",
        "secretary",
        "jr",
        "sr",
        "ii",
        "iii",
        "iv",
        "v",
        "phd",
        "md",
        "esq",
        "jd",
        "mpa",
    }
)

_PERSON_LIST_KEYS = (
    "personas",
    "witnesses",
    "senders",
    "recipients",
    "sponsors_or_offerors",
    "members_present",
    "staff_present",
    "witness_list_entries",
    "presiding_or_witnesses",
)

# Concise built-in V7 genre boundary indicators used for CheckEval question generation
# and deterministic offline fallback when `congress_docmeta.v7.codebook` is not loaded.
_BUILTIN_GENRE_CUES: dict[str, dict[str, Any]] = {
    "hearing_or_markup_notice": {
        "definition": "Official notice announcing or rescheduling a scheduled congressional hearing or markup.",
        "cues": ("notice of hearing", "committee will hold a hearing", "notice of markup", "markup notice", "full committee hearing"),
    },
    "hearing_notice": {
        "definition": "Official notice announcing or rescheduling a scheduled congressional hearing or markup.",
        "cues": ("notice of hearing", "committee will hold a hearing", "notice of markup", "markup notice", "hearings"),
    },
    "hearing_memo_or_witness_list": {
        "definition": "Staff hearing memorandum, briefing charter, or panel witness list.",
        "cues": ("hearing memorandum", "briefing memo", "witness list", "panel i", "panel ii"),
    },
    "hearing_memo_or_charter": {
        "definition": "Staff hearing memorandum, briefing charter, or background memo prepared for committee members.",
        "cues": ("hearing memorandum", "briefing memo", "to:", "from:", "subject:", "background"),
    },
    "witness_list": {
        "definition": "Roster or panel list of scheduled witnesses for a congressional hearing.",
        "cues": ("witness list", "panel i", "panel ii", "witnesses:"),
    },
    "witness_testimony": {
        "definition": "Prepared written testimony or statement submitted by a witness for a hearing.",
        "cues": ("testimony of", "written statement", "prepared statement", "thank you for the opportunity to testify"),
    },
    "witness_statement": {
        "definition": "Prepared written testimony or statement submitted by a witness for a hearing.",
        "cues": ("testimony of", "written statement", "prepared statement", "chairman", "thank you for the opportunity to testify"),
    },
    "witness_biography": {
        "definition": "Biographical sketch or CV of a witness appearing before a committee.",
        "cues": ("biography", "biographical", "education", "b.a.", "j.d.", "ph.d.", "currently serves as"),
    },
    "truth_in_testimony": {
        "definition": "House Rule XI Truth-in-Testimony disclosure form reporting federal grants or contracts.",
        "cues": ("truth in testimony", "rule xi", "clause 2(g)", "federal grant", "disclosure form"),
    },
    "truth_in_testimony_disclosure": {
        "definition": "House Rule XI Truth-in-Testimony disclosure form reporting federal grants or contracts.",
        "cues": ("truth in testimony", "rule xi", "clause 2(g)", "federal grant", "disclosure form"),
    },
    "member_statement": {
        "definition": "Opening statement, floor statement, or remarks by a Member of Congress.",
        "cues": ("opening statement", "statement of rep.", "statement of senator", "statement of chairman", "mr. chairman"),
    },
    "hearing_transcript": {
        "definition": "Verbatim transcript of a convened hearing or markup with speaker turns.",
        "cues": ("the committee met", "came to order", "mr. chairman.", "the chair.", "rptr", "edtr"),
    },
    "committee_vote_or_action": {
        "definition": "Recorded committee roll-call vote, attendance/quorum sheet, committee resolution, or action summary.",
        "cues": ("roll call", "yeas", "nays", "present:", "quorum", "ordered reported", "recorded vote", "resolved,"),
    },
    "vote_or_meeting_summary": {
        "definition": "Recorded committee roll-call vote, attendance/quorum sheet, or meeting action summary.",
        "cues": ("roll call", "yeas", "nays", "present:", "quorum", "ordered reported", "recorded vote"),
    },
    "qfr_correspondence": {
        "definition": "Questions for the Record (QFR) request or written QFR response thread.",
        "cues": ("questions for the record", "qfr", "question 1", "question:", "response:"),
    },
    "qfr_document": {
        "definition": "Questions for the Record (QFR) request or written QFR response thread.",
        "cues": ("questions for the record", "qfr", "question 1", "question:", "response:"),
    },
    "oversight_or_committee_letter": {
        "definition": "Oversight letter, subpoena demand, witness invitation, or committee correspondence.",
        "cues": ("dear ", "sincerely,", "thank you for", "you are invited to testify", "please respond by"),
    },
    "external_submission_or_comment": {
        "definition": "External stakeholder submission, public comment, or third-party letter for the record.",
        "cues": ("submitted for the record", "public comment", "on behalf of", "dear chairman"),
    },
    "oversight_or_correspondence": {
        "definition": "Oversight letter, subpoena demand, witness invitation, or external correspondence.",
        "cues": ("dear ", "sincerely,", "thank you for", "you are invited to testify", "please respond by"),
    },
    "bill_or_amendment": {
        "definition": "Bill text, draft legislation, committee amendment, comparative print, or section-by-section.",
        "cues": ("a bill", "be it enacted", "amendment to", "section 1.", "section-by-section", "strike "),
    },
    "committee_or_agency_report": {
        "definition": "Committee report, CRS/GAO/agency report, oversight plan, or external whitepaper.",
        "cues": ("committee on", "report", "executive summary", "gao-", "crs report"),
    },
    "budget_or_cost_estimate": {
        "definition": "CBO cost estimate, budget views and estimates, or fiscal revenue score.",
        "cues": ("cost estimate", "fiscal year", "appropriations", "budget", "cbo", "revenue"),
    },
}


@dataclass(frozen=True)
class GroundingViolation:
    """Single grounding or structural invariant violation."""

    field_path: str
    reason: str
    value: Any = None


@dataclass
class GroundingResult:
    """Result of deterministic grounding verification on one payload."""

    passed: bool
    errors: list[GroundingViolation] = field(default_factory=list)
    checked_spans: int = 0
    checked_entities: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checked_spans": self.checked_spans,
            "checked_entities": self.checked_entities,
            "errors": [
                {"field_path": e.field_path, "reason": e.reason, "value": e.value}
                for e in self.errors
            ],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class CheckEvalQuestion:
    """Atomic verifiable binary Yes/No checklist question for 2-vs-1 adjudication."""

    qid: str
    dimension: str
    question: str
    target_value: Any
    favors_side: str  # "majority" | "minority" | "diagnostic"


@dataclass
class CheckEvalAnswer:
    """Single binary answer with optional grounded evidence quote."""

    qid: str
    answer: bool
    evidence_quote: str | None = None
    verified_in_text: bool = False


@dataclass
class CheckEvalResult:
    """Structured outcome of `run_checkeval_arbiter`."""

    resolved: bool
    winner_side: str | None  # "majority" | "minority" | None
    winner_tuple: TriageTuple | None
    majority_score: float
    minority_score: float
    questions: list[CheckEvalQuestion] = field(default_factory=list)
    answers: list[CheckEvalAnswer] = field(default_factory=list)
    reason: str = ""


@dataclass
class ConsensusDecision:
    """3-family adjudication verdict for a document."""

    doc_key: str
    verdict: str  # "auto_accept_gold" | "checkeval_resolved" | "deadlock_needs_owner"
    accepted_tuple: TriageTuple | None
    accepted_payload: dict[str, Any] | None
    family_tuples: dict[str, TriageTuple]
    grounding_by_family: dict[str, GroundingResult]
    consensus_families: list[str] = field(default_factory=list)
    disagreeing_families: list[str] = field(default_factory=list)
    checkeval: CheckEvalResult | None = None
    deadlock_reason: str | None = None
    text_preview: str = ""


_INVISIBLE_FORMAT_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069\u200e\u200f\ufeff\u00ad]")


def strip_invisible_format_chars(text: str) -> str:
    """Strip invisible Unicode bidi overrides, zero-width marks, BOM, and soft hyphens."""
    if not text:
        return ""
    return _INVISIBLE_FORMAT_RE.sub("", text)


def _strip_invisible_with_index_map(text: str) -> tuple[str, list[int]]:
    """Return `(stripped_text, raw_index_map)` mapping stripped char index -> raw `text` index."""
    if not text or not _INVISIBLE_FORMAT_RE.search(text):
        return text, list(range(len(text)))
    chars: list[str] = []
    idx_map: list[int] = []
    for i, ch in enumerate(text):
        if _INVISIBLE_FORMAT_RE.match(ch):
            continue
        chars.append(ch)
        idx_map.append(i)
    return "".join(chars), idx_map


def _map_stripped_span_to_raw(idx_map: list[int], s_lo: int, s_hi: int) -> tuple[int, int] | None:
    """Translate `[s_lo, s_hi)` in stripped text back to raw `[raw_lo, raw_hi)` bounds."""
    if not (0 <= s_lo < s_hi <= len(idx_map)):
        return None
    return idx_map[s_lo], idx_map[s_hi - 1] + 1


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", strip_invisible_format_chars(text)).strip()


def _norm_typography(text: str) -> str:
    cleaned = strip_invisible_format_chars(text)
    return (
        cleaned.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u00a0", " ")
    )


def _norm_for_title(text: str) -> str:
    # Undo soft line-break hyphenation ("appro-\npriations" -> "appropriations")
    unwrapped = re.sub(r"-\s*\n\s*", "", _norm_typography(text))
    return re.sub(r"\s+", " ", unwrapped).strip().casefold()


def _norm_alnum_ws(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", _norm_typography(text).casefold())
    return re.sub(r"\s+", " ", cleaned).strip()


def _is_int_not_bool(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _iter_span_refs(obj: Any, path: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Recursively discover every dict matching a `SpanRef` shape."""
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(obj, dict):
        if "quote" in obj and ("start" in obj or "end" in obj):
            found.append((path or "span", obj))
        for key, val in obj.items():
            sub_path = f"{path}.{key}" if path else str(key)
            found.extend(_iter_span_refs(val, sub_path))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            sub_path = f"{path}[{idx}]"
            found.extend(_iter_span_refs(item, sub_path))
    return found


def repair_span_refs_in_payload(
    text: str,
    payload: dict[str, Any],
    *,
    search_window: int = 250,
) -> dict[str, Any]:
    """Pure `parse()`-stage helper: auto-repair `SpanRef` start/end offsets if quote exists in `text`.

    Does NOT fabricate missing quotes; if a quote does not occur in `text`, leaves
    offsets untouched so `verify_span_grounding` strictly rejects it.
    """
    repaired = copy.deepcopy(payload)
    stripped_text, idx_map = _strip_invisible_with_index_map(text)
    has_invisible = len(stripped_text) != len(text)
    for _, span in _iter_span_refs(repaired):
        quote = span.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            continue
        start = span.get("start")
        end = span.get("end")
        if (
            _is_int_not_bool(start)
            and _is_int_not_bool(end)
            and 0 <= start < end <= len(text)
            and text[start:end] == quote
        ):
            continue

        # 1) Search near provided offset first, then anywhere in `text` for exact match.
        hint = start if _is_int_not_bool(start) else 0
        lo = max(0, hint - search_window)
        hi = min(len(text), hint + len(quote) + search_window)
        idx = text.find(quote, lo, hi)
        if idx >= 0:
            span["start"] = idx
            span["end"] = idx + len(quote)
            continue

        idx_global = text.find(quote)
        if idx_global >= 0:
            span["start"] = idx_global
            span["end"] = idx_global + len(quote)
            continue

        # 2) Collapsed-whitespace regex match (keeps exact substring bounds from `text`).
        clean_quote = strip_invisible_format_chars(quote)
        tokens = _collapse_ws(clean_quote).split(" ")
        if tokens and all(tokens):
            ws_pattern = r"\s+".join(re.escape(tok) for tok in tokens)
            m = re.search(ws_pattern, text[lo:hi])
            if m is not None:
                span["start"] = lo + m.start()
                span["end"] = lo + m.end()
                continue
            m_global = re.search(ws_pattern, text)
            if m_global is not None:
                span["start"] = m_global.start()
                span["end"] = m_global.end()
                continue

            # 3) Invisible bidi/format fallback: search stripped text and map back to raw `text` bounds.
            if has_invisible:
                idx_s = stripped_text.find(clean_quote)
                if idx_s >= 0:
                    mapped = _map_stripped_span_to_raw(idx_map, idx_s, idx_s + len(clean_quote))
                    if mapped is not None:
                        span["start"], span["end"] = mapped
                        span["quote"] = clean_quote
                        continue
                m_s = re.search(ws_pattern, stripped_text)
                if m_s is not None:
                    mapped = _map_stripped_span_to_raw(idx_map, m_s.start(), m_s.end())
                    if mapped is not None:
                        span["start"], span["end"] = mapped
                        span["quote"] = _collapse_ws(stripped_text[m_s.start() : m_s.end()])
                        continue
    return repaired


def _verify_single_span_ref(text: str, span: dict[str, Any], *, allow_whitespace_norm: bool = True) -> tuple[bool, str | None]:
    quote = span.get("quote")
    start = span.get("start")
    end = span.get("end")
    if not isinstance(quote, str) or not quote.strip():
        return False, "span_empty_quote"
    if not (_is_int_not_bool(start) and _is_int_not_bool(end)):
        return False, "span_non_integer_offsets"
    if not (0 <= start < end <= len(text)):
        return False, f"span_out_of_bounds({start},{end},len={len(text)})"

    sliced = text[start:end]
    if sliced == quote:
        return True, None

    if allow_whitespace_norm:
        norm_quote = _collapse_ws(_norm_typography(quote))
        norm_slice = _collapse_ws(_norm_typography(sliced))
        if norm_quote and norm_slice == norm_quote and norm_quote in _collapse_ws(_norm_typography(text)):
            return True, None
    return False, f"span_slice_mismatch(slice={sliced!r},quote={quote!r})"


_CONJUNCTIONS = frozenset({"and", "or", "vs", "with", "for", "to", "from", "of", "at", "by", "in", "on"})


def _tokens_match_tight_span(seq: Sequence[str], norm_text_alnum: str) -> bool:
    """Verify `seq` tokens appear contiguously or with at most 1 non-conjunction middle token."""
    if not seq:
        return False
    if len(seq) == 1:
        return len(seq[0]) >= 3 and re.search(rf"\b{re.escape(seq[0])}\b", norm_text_alnum) is not None

    # Exact adjacent match
    exact_seq = " ".join(seq)
    if re.search(rf"\b{re.escape(exact_seq)}\b", norm_text_alnum):
        return True

    # Allow at most 1 optional middle initial/name between first and last token (excluding conjunctions).
    first = seq[0]
    rest = seq[1:]
    if len(seq) == 2:
        pattern = rf"\b{re.escape(first)}\s+(?:([a-z0-9]+)\s+)?{re.escape(rest[0])}\b"
        for m in re.finditer(pattern, norm_text_alnum):
            mid = m.group(1)
            if mid is None or (mid not in _CONJUNCTIONS):
                return True
        return False

    # 3+ tokens (e.g. "Jane A. Doe"): require all tokens within a short contiguous slice (<= 24 chars),
    # with zero intervening conjunction words.
    pat = r"\b" + r"\s+(?:[a-z0-9]+\s+)?".join(re.escape(t) for t in seq) + r"\b"
    for m in re.finditer(pat, norm_text_alnum):
        span_tokens = m.group(0).split()
        if len(span_tokens) <= len(seq) + 1 and not any(t in _CONJUNCTIONS for t in span_tokens if t not in seq):
            return True
    return False


def _person_name_grounded(name: str, text: str, norm_text_alnum: str) -> bool:
    if not name or not name.strip():
        return False
    norm_name = _norm_alnum_ws(name)
    if not norm_name:
        return False
    if re.search(rf"\b{re.escape(norm_name)}\b", norm_text_alnum):
        return True

    tokens = [tok for tok in norm_name.split(" ") if tok and tok not in _HONORIFICS]
    if not tokens:
        tokens = norm_name.split(" ")
    core_tokens = [t for t in tokens if len(t) >= 2] or tokens

    if _tokens_match_tight_span(core_tokens, norm_text_alnum):
        return True

    # Also support "Last, First [Middle]" <-> "First [Middle] Last" ordering.
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        last_toks = [t for t in _norm_alnum_ws(parts[0]).split(" ") if t and t not in _HONORIFICS]
        first_toks = [t for t in _norm_alnum_ws(parts[1]).split(" ") if t and t not in _HONORIFICS]
        reordered = [t for t in (first_toks + last_toks) if len(t) >= 2] or (first_toks + last_toks)
        if _tokens_match_tight_span(reordered, norm_text_alnum):
            return True
    elif len(core_tokens) >= 2:
        reversed_comma_form = [core_tokens[-1], *core_tokens[:-1]]
        if _tokens_match_tight_span(reversed_comma_form, norm_text_alnum):
            return True

    return False


def _date_span_grounded(span_val: str, norm_text_ws_cf: str) -> bool:
    norm_span = _collapse_ws(_norm_typography(span_val)).casefold()
    if not norm_span:
        return False
    return norm_span in norm_text_ws_cf


def _verbatim_title_grounded(title: str, norm_text_title: str, norm_text_alnum: str) -> bool:
    norm_t = _norm_for_title(title)
    if not norm_t:
        return False
    if norm_t in norm_text_title:
        return True
    # Also permit minor punctuation normalization (e.g., colon/comma differences) while preserving exact token sequence.
    alnum_t = _norm_alnum_ws(title)
    return bool(alnum_t and alnum_t in norm_text_alnum)


def _issuer_org_grounded(org: str, norm_text_alnum: str) -> bool:
    norm_o = _norm_alnum_ws(org)
    if not norm_o:
        return False
    if norm_o in norm_text_alnum:
        return True
    # Strip optional leading "the" and check exact sequential token match (does NOT expand acronyms).
    words = [w for w in norm_o.split(" ") if w]
    if words and words[0] == "the" and len(words) > 1:
        seq = " ".join(words[1:])
        if seq in norm_text_alnum:
            return True
    return False


def _ocr_span_grounded(
    value: str,
    span: Any,
    text: str,
    *,
    allow_whitespace_norm: bool = True,
) -> bool:
    """Return True when an explicit SpanRef is valid in `text` and OCR-matches `value`."""
    if not isinstance(span, Mapping):
        return False
    ok, _ = _verify_single_span_ref(text, dict(span), allow_whitespace_norm=allow_whitespace_norm)
    if not ok:
        return False
    quote = str(span.get("quote") or "")
    norm_val = _norm_alnum_ws(value)
    norm_q = _norm_alnum_ws(quote)
    if not norm_val or not norm_q or min(len(norm_val), len(norm_q)) < 5:
        return False
    if norm_val == norm_q or norm_val in norm_q:
        return True
    v_toks = norm_val.split()
    q_toks = norm_q.split()
    if len(v_toks) != len(q_toks):
        return False
    if SequenceMatcher(None, norm_val, norm_q).ratio() < 0.78:
        return False
    return all(SequenceMatcher(None, vt, qt).ratio() >= 0.70 for vt, qt in zip(v_toks, q_toks))


def verify_span_grounding(
    text: str,
    payload: Mapping[str, Any],
    *,
    allow_whitespace_norm: bool = True,
) -> GroundingResult:
    """Verify SpanRefs, entity/title/date/org grounding, and `status != usable => primary_genre is None`."""
    errors: list[GroundingViolation] = []
    checked_spans = 0
    checked_entities = 0

    if not isinstance(payload, Mapping):
        return GroundingResult(
            passed=False,
            errors=[GroundingViolation("payload", "payload_not_mapping", type(payload).__name__)],
        )

    # 1) Non-usable status invariant.
    status = payload.get("status")
    primary_genre = payload.get("primary_genre") if "primary_genre" in payload else payload.get("primary_kind")
    if status is not None and status != "usable" and primary_genre is not None:
        errors.append(
            GroundingViolation(
                "primary_genre",
                "non_usable_status_must_have_null_primary_genre",
                {"status": status, "primary_genre": primary_genre},
            )
        )

    # 2) Recursive SpanRef offset + quote validation.
    for path, span in _iter_span_refs(dict(payload)):
        checked_spans += 1
        ok, err_reason = _verify_single_span_ref(text, span, allow_whitespace_norm=allow_whitespace_norm)
        if not ok:
            errors.append(GroundingViolation(path, err_reason or "span_invalid", span))

    norm_text_ws_cf = _collapse_ws(_norm_typography(text)).casefold()
    norm_text_title = _norm_for_title(text)
    norm_text_alnum = _norm_alnum_ws(text)

    # 3) Named entities (`personas`, `witnesses`, `senders`, `recipients`, `sponsors_or_offerors`, etc.).
    for key in _PERSON_LIST_KEYS:
        items = payload.get(key)
        if not items:
            continue
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
            continue
        for idx, item in enumerate(items):
            if isinstance(item, Mapping):
                name = item.get("name")
                name_span = item.get("name_span")
            elif isinstance(item, str):
                name = item
                name_span = None
            else:
                continue
            if name is None:
                continue
            checked_entities += 1
            if not isinstance(name, str) or (
                not _person_name_grounded(name, text, norm_text_alnum)
                and not _ocr_span_grounded(name, name_span, text, allow_whitespace_norm=allow_whitespace_norm)
            ):
                errors.append(
                    GroundingViolation(
                        f"{key}[{idx}].name",
                        "ungrounded_person_name",
                        name,
                    )
                )

    # 4) `verbatim_title`.
    verbatim_title = payload.get("verbatim_title")
    if isinstance(verbatim_title, str) and verbatim_title.strip():
        checked_entities += 1
        if not _verbatim_title_grounded(verbatim_title, norm_text_title, norm_text_alnum):
            errors.append(
                GroundingViolation(
                    "verbatim_title",
                    "ungrounded_verbatim_title",
                    verbatim_title,
                )
            )

    # 5) `date_spans[]` (strict literal substring check — blocks ISO leakage like `2022-01-13`).
    date_spans = payload.get("date_spans")
    if isinstance(date_spans, Sequence) and not isinstance(date_spans, (str, bytes)):
        for idx, ds in enumerate(date_spans):
            if isinstance(ds, Mapping):
                val = ds.get("quote")
            elif isinstance(ds, str):
                val = ds
            else:
                continue
            checked_entities += 1
            if not isinstance(val, str) or not _date_span_grounded(val, norm_text_ws_cf):
                errors.append(
                    GroundingViolation(
                        f"date_spans[{idx}]",
                        "ungrounded_date_span",
                        val,
                    )
                )

    # 6) `issuer_org` (blocks unmentioned acronym expansion).
    issuer_org = payload.get("issuer_org")
    if isinstance(issuer_org, str) and issuer_org.strip():
        checked_entities += 1
        if not _issuer_org_grounded(issuer_org, norm_text_alnum) and not _ocr_span_grounded(
            issuer_org, payload.get("issuer_org_span"), text, allow_whitespace_norm=allow_whitespace_norm
        ):
            errors.append(
                GroundingViolation(
                    "issuer_org",
                    "ungrounded_issuer_org",
                    issuer_org,
                )
            )

    return GroundingResult(
        passed=len(errors) == 0,
        errors=errors,
        checked_spans=checked_spans,
        checked_entities=checked_entities,
    )


def extract_triage_tuple(payload: Mapping[str, Any] | None) -> TriageTuple | None:
    """Extract canonical `(status, media_format, is_packet, primary_genre)` tuple."""
    if not isinstance(payload, Mapping):
        return None
    status = payload.get("status")
    status_str = str(status) if status is not None else None
    media_format = None if (status_str is not None and status_str != "usable") else payload.get("media_format")
    is_packet = payload.get("is_packet")
    primary_genre = payload.get("primary_genre") if "primary_genre" in payload else payload.get("primary_kind")
    return (
        status_str,
        str(media_format) if media_format is not None else None,
        bool(is_packet) if is_packet is not None else None,
        str(primary_genre) if primary_genre is not None else None,
    )


def _load_codebook_definitions() -> dict[str, dict[str, Any]]:
    """Lazily read genre definitions from `congress_docmeta.v7.codebook` if available."""
    try:
        import importlib

        cb = importlib.import_module("congress_docmeta.v7.codebook")
        if hasattr(cb, "get_codebook") and callable(cb.get_codebook):
            spec = cb.get_codebook()
            genres = spec.get("genres") if isinstance(spec, Mapping) else None
            if isinstance(genres, Mapping) and genres:
                out: dict[str, dict[str, Any]] = {}
                for k, v in genres.items():
                    if isinstance(v, Mapping):
                        entry = dict(v)
                        if "cues" not in entry:
                            entry["cues"] = tuple(entry.get("positive_indicators") or ())
                        out[str(k)] = entry
                for k, v in _BUILTIN_GENRE_CUES.items():
                    if k not in out:
                        out[k] = v
                    elif not out[k].get("cues"):
                        out[k]["cues"] = v.get("cues", ())
                return out
        for attr in ("GENRE_DEFINITIONS", "CODEBOOK_GENRES", "GENRES"):
            val = getattr(cb, attr, None)
            if isinstance(val, Mapping) and val:
                out = {}
                for k, v in val.items():
                    if isinstance(v, Mapping):
                        out[str(k)] = dict(v)
                    else:
                        out[str(k)] = {"definition": str(v), "cues": ()}
                return out
    except Exception:
        pass
    return _BUILTIN_GENRE_CUES


def build_checkeval_questions(
    majority_tuple: TriageTuple,
    minority_tuple: TriageTuple,
) -> list[CheckEvalQuestion]:
    """Generate atomic verifiable binary Yes/No checklist questions for a 2-vs-1 split."""
    questions: list[CheckEvalQuestion] = []
    m_status, m_media, m_pkt, m_genre = majority_tuple
    n_status, n_media, n_pkt, n_genre = minority_tuple

    if m_status != n_status:
        questions.append(
            CheckEvalQuestion(
                qid="q_status_usable",
                dimension="status",
                question=(
                    "Does the text contain substantive legislative, hearing, correspondence, "
                    "or committee document content rather than a blank stub, HTTP/Cloudflare error, or wrapper?"
                ),
                target_value="usable",
                favors_side="majority" if m_status == "usable" else ("minority" if n_status == "usable" else "diagnostic"),
            )
        )

    if m_pkt != n_pkt:
        packet_side = "majority" if m_pkt is True else "minority"
        single_side = "minority" if m_pkt is True else "majority"
        questions.append(
            CheckEvalQuestion(
                qid="q_is_packet",
                dimension="is_packet",
                question=(
                    "Does the text bundle two or more distinct concatenated documents/exhibits "
                    "(e.g., Table of Exhibits + Exhibit bodies, or Testimony + Bio + Disclosure form) — "
                    "NOT merely a single S. Rept./H. Rept. committee report with embedded bill text or minority views?"
                ),
                target_value=True,
                favors_side=packet_side,
            )
        )
        questions.append(
            CheckEvalQuestion(
                qid="q_is_single_doc",
                dimension="is_packet_single",
                question=(
                    "Is the text one cohesive single document (such as a single numbered committee report, "
                    "single hearing transcript, single bill, or single letter) rather than a bundle of separate documents?"
                ),
                target_value=False,
                favors_side=single_side,
            )
        )

    if m_media != n_media:
        media_cues_help = {
            "prose": "clean plain narrative paragraphs, bill sections, Q&A transcript, or letter prose WITHOUT HTML navigation/breadcrumbs or labeled form grid",
            "web_page": "scraped HTML webpage with site navigation chrome, search/breadcrumb bar (e.g. 'Home > ...', 'THIS SEARCH'), or webpage post metadata",
            "table_or_form": "structured labeled form template (e.g. NIH Biographical Sketch fields NAME/POSITION TITLE/EDUCATION, Rule XI disclosure boxes) or roll-call/attendance/score grid",
            "slides": "presentation slide deck or captioned photograph/visual exhibit",
        }
        if m_media is not None:
            questions.append(
                CheckEvalQuestion(
                    qid="q_media_majority",
                    dimension="media_format",
                    question=(
                        f"Does the document layout match media_format={m_media!r} "
                        f"({media_cues_help.get(str(m_media), str(m_media))})?"
                    ),
                    target_value=m_media,
                    favors_side="majority",
                )
            )
        if n_media is not None:
            questions.append(
                CheckEvalQuestion(
                    qid="q_media_minority",
                    dimension="media_format",
                    question=(
                        f"Does the document layout match media_format={n_media!r} "
                        f"({media_cues_help.get(str(n_media), str(n_media))})?"
                    ),
                    target_value=n_media,
                    favors_side="minority",
                )
            )

    if m_genre != n_genre:
        defs = _load_codebook_definitions()
        if m_genre:
            m_def = defs.get(m_genre, {}).get("definition") or f"Matches congressional genre {m_genre}."
            questions.append(
                CheckEvalQuestion(
                    qid="q_genre_majority",
                    dimension="primary_genre",
                    question=f"Is the document's primary genre '{m_genre}' ({m_def})?",
                    target_value=m_genre,
                    favors_side="majority",
                )
            )
        if n_genre:
            n_def = defs.get(n_genre, {}).get("definition") or f"Matches congressional genre {n_genre}."
            questions.append(
                CheckEvalQuestion(
                    qid="q_genre_minority",
                    dimension="primary_genre",
                    question=f"Is the document's primary genre '{n_genre}' ({n_def})?",
                    target_value=n_genre,
                    favors_side="minority",
                )
            )
        # Explicit negative boundary check for QFR vs witness statement / invitation vs disclosure.
        if {m_genre, n_genre} & {"qfr_correspondence", "qfr_document", "qfr_response", "qfr_request"}:
            questions.append(
                CheckEvalQuestion(
                    qid="q_neg_qfr_boundary",
                    dimension="negative_boundary",
                    question=(
                        "Does the text contain numbered Questions for the Record (QFR) or explicit "
                        "post-hearing written questions/answers rather than standalone prepared testimony?"
                    ),
                    target_value="qfr",
                    favors_side="majority" if "qfr" in str(m_genre) else "minority",
                )
            )
        if {m_genre, n_genre} & {"truth_in_testimony", "truth_in_testimony_disclosure"}:
            ttf_genres = {"truth_in_testimony", "truth_in_testimony_disclosure"}
            questions.append(
                CheckEvalQuestion(
                    qid="q_neg_ttf_boundary",
                    dimension="negative_boundary",
                    question=(
                        "Does the text contain House Rule XI Truth-in-Testimony grant/contract disclosure "
                        "fields and signature certification (not merely a witness invitation letter)?"
                    ),
                    target_value="truth_in_testimony",
                    favors_side="majority" if m_genre in ttf_genres else "minority",
                )
            )

    if not questions:
        questions.append(
            CheckEvalQuestion(
                qid="q_fallback_match",
                dimension="triage",
                question=f"Does the grounded text support {majority_tuple} over {minority_tuple}?",
                target_value=majority_tuple,
                favors_side="majority",
            )
        )
    return questions


def _find_evidence_quote(text: str, cues: Sequence[str]) -> str | None:
    lower = text.casefold()
    for cue in cues:
        idx = lower.find(cue.casefold())
        if idx >= 0:
            end = min(len(text), idx + max(len(cue), 40))
            return text[idx:end].strip()
    return None


def _default_deterministic_checkeval(
    text: str,
    questions: Sequence[CheckEvalQuestion],
) -> list[dict[str, Any]]:
    """Offline evidence-locked binary evaluator for `CheckEval` when no LLM callback is provided."""
    defs = _load_codebook_definitions()
    lower = text.casefold()
    out: list[dict[str, Any]] = []

    pkt_cues = (
        "table of contents",
        "table of exhibits",
        "packet",
        "document 1:",
        "document 2:",
        "exhibit 1:",
        "exhibit 2:",
        "exhibit a",
        "exhibit b",
        "attachment 1",
    )
    slide_cues = ("slide ", "agenda", "•", "photo courtesy")
    web_cues = ("skip to main content", "navigation", "breadcrumbs", "home >", "search results", "this search", "thomas home", "bill status:")
    form_cues = ("checkbox", "yes [", "no [", "signature:", "roll call", "yeas", "biographical sketch", "position title", "education/training")

    for q in questions:
        ans = False
        quote: str | None = None

        if q.dimension == "status":
            error_cues = ("403 forbidden", "access denied", "page not found", "intentionally left blank", "cloudflare")
            has_err = any(c in lower for c in error_cues)
            is_photo = _find_evidence_quote(text, ("photo courtesy",)) is not None and len(_collapse_ws(text)) >= 25
            is_substantive = (len(_collapse_ws(text)) >= 60 or is_photo) and not has_err
            ans = is_substantive
            if is_substantive:
                quote = text.strip()[:60]
            else:
                quote = _find_evidence_quote(text, error_cues)
        elif q.dimension == "is_packet":
            quote = _find_evidence_quote(text, pkt_cues)
            ans = quote is not None
        elif q.dimension == "is_packet_single":
            has_pkt = _find_evidence_quote(text, pkt_cues) is not None
            if not has_pkt and len(_collapse_ws(text)) >= 40:
                ans = True
                quote = text.strip()[:60]
        elif q.dimension == "media_format":
            target = str(q.target_value or "")
            if target == "slides":
                quote = _find_evidence_quote(text, slide_cues)
                ans = quote is not None
            elif target == "web_page":
                quote = _find_evidence_quote(text, web_cues)
                ans = quote is not None
            elif target == "table_or_form":
                quote = _find_evidence_quote(text, form_cues)
                ans = quote is not None
            else:
                has_special = any(
                    _find_evidence_quote(text, cues) is not None
                    for cues in (web_cues, form_cues, slide_cues)
                )
                ans = len(_collapse_ws(text)) >= 60 and not has_special
                quote = text.strip()[:60] if ans else None
        elif q.dimension == "negative_boundary":
            if q.target_value == "qfr":
                quote = _find_evidence_quote(text, ("questions for the record", "qfr", "question 1", "question:"))
                ans = quote is not None
            elif q.target_value in {"truth_in_testimony", "truth_in_testimony_disclosure"}:
                quote = _find_evidence_quote(text, ("truth in testimony", "rule xi", "federal grant", "clause 2(g)"))
                ans = quote is not None
        elif q.dimension == "primary_genre":
            target_genre = str(q.target_value or "")
            builtin_cues = _BUILTIN_GENRE_CUES.get(target_genre, {}).get("cues", ())
            cb_cues = defs.get(target_genre, {}).get("cues", ())
            cues = builtin_cues or cb_cues
            if not cues and target_genre:
                cues = (target_genre.replace("_", " "),)
            quote = _find_evidence_quote(text, cues)
            ans = quote is not None

        out.append({"qid": q.qid, "answer": ans, "evidence_quote": quote})
    return out


def _quote_is_in_text(quote: str | None, text: str) -> bool:
    if not isinstance(quote, str) or not quote.strip():
        return False
    return _collapse_ws(_norm_typography(quote)).casefold() in _collapse_ws(_norm_typography(text)).casefold()


def run_checkeval_arbiter(
    text: str,
    majority_tuple: TriageTuple,
    minority_tuple: TriageTuple,
    *,
    check_eval_fn: Callable[..., Any] | None = None,
    candidates: Mapping[str, list[dict[str, Any]]] | None = None,
) -> CheckEvalResult:
    """Resolve a 2-vs-1 split via atomic binary Yes/No checklist questions grounded in `text`."""
    questions = build_checkeval_questions(majority_tuple, minority_tuple)
    raw_resp: Any
    if check_eval_fn is not None:
        try:
            raw_resp = check_eval_fn(
                text,
                questions,
                {"majority": majority_tuple, "minority": minority_tuple},
                candidates,
            )
        except TypeError:
            try:
                raw_resp = check_eval_fn(text, questions, {"majority": majority_tuple, "minority": minority_tuple})
            except TypeError:
                raw_resp = check_eval_fn(text, questions)
    else:
        raw_resp = _default_deterministic_checkeval(text, questions)

    explicit_winner: str | None = None
    if isinstance(raw_resp, Mapping):
        explicit_winner = raw_resp.get("winner")
        raw_answers = raw_resp.get("answers", [])
    elif isinstance(raw_resp, Sequence):
        raw_answers = list(raw_resp)
    else:
        return CheckEvalResult(
            resolved=False,
            winner_side=None,
            winner_tuple=None,
            majority_score=0.0,
            minority_score=0.0,
            questions=questions,
            reason="invalid_checkeval_response",
        )

    ans_by_qid: dict[str, dict[str, Any]] = {}
    for item in raw_answers:
        if isinstance(item, Mapping) and item.get("qid"):
            ans_by_qid[str(item["qid"])] = dict(item)
        elif hasattr(item, "qid"):
            ans_by_qid[str(item.qid)] = {
                "qid": item.qid,
                "answer": bool(getattr(item, "answer", False)),
                "evidence_quote": getattr(item, "evidence_quote", None),
            }

    answers: list[CheckEvalAnswer] = []
    maj_score = 0.0
    min_score = 0.0

    for q in questions:
        rec = ans_by_qid.get(q.qid, {})
        ans_bool = bool(rec.get("answer", False))
        ev_quote = rec.get("evidence_quote")
        # Require evidence quote to actually appear in `text` if supplied; if `check_eval_fn`
        # provided an affirmative answer with an ungrounded quote, reject the affirmative vote!
        has_quote = isinstance(ev_quote, str) and bool(ev_quote.strip())
        verified = _quote_is_in_text(ev_quote, text) if has_quote else False
        if ans_bool and has_quote and not verified:
            ans_bool = False

        answers.append(
            CheckEvalAnswer(
                qid=q.qid,
                answer=ans_bool,
                evidence_quote=ev_quote if isinstance(ev_quote, str) else None,
                verified_in_text=verified,
            )
        )

        if q.favors_side == "majority":
            if ans_bool:
                maj_score += 1.0
            elif q.dimension in {"is_packet", "negative_boundary", "status"} and not ans_bool:
                # Negative answer on a discriminating binary criterion supports the opposite side.
                min_score += 0.5
        elif q.favors_side == "minority":
            if ans_bool:
                min_score += 1.0
            elif q.dimension in {"is_packet", "negative_boundary", "status"} and not ans_bool:
                maj_score += 0.5

    if explicit_winner in {"ambiguous", "deadlock", "none", None}:
        if explicit_winner in {"ambiguous", "deadlock"}:
            return CheckEvalResult(
                resolved=False,
                winner_side=None,
                winner_tuple=None,
                majority_score=maj_score,
                minority_score=min_score,
                questions=questions,
                answers=answers,
                reason="checkeval_explicit_ambiguous",
            )
    elif (
        (explicit_winner == "majority" and maj_score >= 1.0 and maj_score >= min_score)
        or (explicit_winner == "minority" and min_score >= 1.0 and min_score >= maj_score)
    ):
        w_tuple = majority_tuple if explicit_winner == "majority" else minority_tuple
        return CheckEvalResult(
            resolved=True,
            winner_side=explicit_winner,
            winner_tuple=w_tuple,
            majority_score=maj_score,
            minority_score=min_score,
            questions=questions,
            answers=answers,
            reason="checkeval_explicit_winner",
        )

    if maj_score > min_score and maj_score >= 1.0:
        return CheckEvalResult(
            resolved=True,
            winner_side="majority",
            winner_tuple=majority_tuple,
            majority_score=maj_score,
            minority_score=min_score,
            questions=questions,
            answers=answers,
            reason="checkeval_checklist_majority",
        )
    if min_score > maj_score and min_score >= 1.0:
        return CheckEvalResult(
            resolved=True,
            winner_side="minority",
            winner_tuple=minority_tuple,
            majority_score=maj_score,
            minority_score=min_score,
            questions=questions,
            answers=answers,
            reason="checkeval_checklist_minority",
        )
    return CheckEvalResult(
        resolved=False,
        winner_side=None,
        winner_tuple=None,
        majority_score=maj_score,
        minority_score=min_score,
        questions=questions,
        answers=answers,
        reason="checkeval_tie_or_insufficient_evidence",
    )


def merge_consensus_payload(
    text: str,
    payloads: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Deterministically merge grounded field outputs from agreeing families."""
    if not payloads:
        return {}
    merged: dict[str, Any] = {}
    all_keys: list[str] = []
    seen_keys: set[str] = set()
    for p in payloads:
        for k in p.keys():
            if k not in seen_keys:
                seen_keys.add(k)
                all_keys.append(k)

    for key in all_keys:
        vals = [p[key] for p in payloads if key in p]
        if not vals:
            continue

        # Merge lists deterministically by preserving consensus/grounded order.
        if all(isinstance(v, list) for v in vals):
            merged_list: list[Any] = []
            seen_repr: set[str] = set()
            for lst in vals:
                for item in lst:
                    if isinstance(item, Mapping) and "quote" in item and ("start" in item or "end" in item):
                        ok, _ = _verify_single_span_ref(text, dict(item))
                        if not ok:
                            continue
                    rep = repr(item)
                    if rep not in seen_repr:
                        seen_repr.add(rep)
                        merged_list.append(copy.deepcopy(item))
            merged[key] = merged_list
            continue

        # Merge scalar / dict values by majority frequency (non-None preferred on tie).
        non_none = [v for v in vals if v is not None]
        if not non_none:
            merged[key] = None
            continue
        counts = Counter(repr(v) for v in non_none)
        best_repr, _ = max(counts.items(), key=lambda kv: (kv[1], -non_none.index(next(x for x in non_none if repr(x) == kv[0]))))
        best_val = next(x for x in non_none if repr(x) == best_repr)
        merged[key] = copy.deepcopy(best_val)

    # Keep merged (verbatim_title, title_span) paired from one consistent payload when possible.
    ts = merged.get("title_span")
    vt = merged.get("verbatim_title")
    if isinstance(ts, Mapping):
        vt_norm = _collapse_ws(str(vt or ""))
        ts_norm = _collapse_ws(str(ts.get("quote") or ""))
        if vt_norm != ts_norm:
            matched_pair: tuple[str, dict[str, Any]] | None = None
            # Prefer a payload matching the majority verbatim_title first.
            for p in payloads:
                p_vt = p.get("verbatim_title")
                p_ts = p.get("title_span")
                if (
                    isinstance(p_vt, str)
                    and p_vt.strip()
                    and isinstance(p_ts, Mapping)
                    and _collapse_ws(p_vt) == _collapse_ws(str(p_ts.get("quote") or ""))
                    and _verify_single_span_ref(text, dict(p_ts))[0]
                ):
                    if _collapse_ws(p_vt) == vt_norm:
                        matched_pair = (p_vt, copy.deepcopy(dict(p_ts)))
                        break
                    if matched_pair is None:
                        matched_pair = (p_vt, copy.deepcopy(dict(p_ts)))
            if matched_pair is not None:
                merged["verbatim_title"], merged["title_span"] = matched_pair
            elif isinstance(vt, str) and vt.strip():
                merged["title_span"] = None

    return merged


_MONTH_PATTERNS: dict[int, tuple[str, ...]] = {
    1: ("January", "Jan"),
    2: ("February", "Feb"),
    3: ("March", "Mar"),
    4: ("April", "Apr"),
    5: ("May",),
    6: ("June", "Jun"),
    7: ("July", "Jul"),
    8: ("August", "Aug"),
    9: ("September", "Sept", "Sep"),
    10: ("October", "Oct"),
    11: ("November", "Nov"),
    12: ("December", "Dec"),
}


def _synthesize_grounded_date_span(text: str, doc_date: str) -> dict[str, Any] | None:
    """Find a literal grounded SpanRef in `text` corresponding to ISO `doc_date`."""
    if not text or not doc_date:
        return None
    parts = doc_date.split("-")
    patterns: list[str] = []
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        y, m_num, d_num = int(parts[0]), int(parts[1]), int(parts[2])
        months = _MONTH_PATTERNS.get(m_num, ())
        patterns.append(rf"\b{y:04d}-{m_num:02d}-{d_num:02d}\b")
        if months:
            mon_alt = "|".join(re.escape(nm) for nm in months)
            patterns.append(rf"\b(?:{mon_alt})\.?\s+0?{d_num}(?:st|nd|rd|th)?,?\s+{y:04d}\b")
            patterns.append(rf"\b0?{d_num}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{mon_alt})\.?,?\s+{y:04d}\b")
        patterns.append(rf"(?<!\d)0?{m_num}[/-]0?{d_num}[/-](?:{y:04d}|{y % 100:02d})(?!\d)")
    elif len(parts) == 2 and all(p.isdigit() for p in parts):
        y, m_num = int(parts[0]), int(parts[1])
        months = _MONTH_PATTERNS.get(m_num, ())
        patterns.append(rf"\b{y:04d}-{m_num:02d}\b")
        if months:
            mon_alt = "|".join(re.escape(nm) for nm in months)
            patterns.append(rf"\b(?:{mon_alt})\.?,?\s+{y:04d}\b")
        patterns.append(rf"(?<!\d)0?{m_num}/{y:04d}(?!\d)")
    elif len(parts) == 1 and parts[0].isdigit():
        y = int(parts[0])
        patterns.append(rf"\b{y:04d}\b")

    stripped_text, idx_map = _strip_invisible_with_index_map(text)
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m is not None and m.group(0).strip():
            return {"quote": m.group(0), "start": m.start(), "end": m.end()}
        if len(stripped_text) != len(text):
            m_s = re.search(pat, stripped_text, flags=re.IGNORECASE)
            if m_s is not None and m_s.group(0).strip():
                mapped = _map_stripped_span_to_raw(idx_map, m_s.start(), m_s.end())
                if mapped is not None:
                    return {"quote": m_s.group(0), "start": mapped[0], "end": mapped[1]}
    return None


def _search_ws_tokens_in_text(text: str, norm_text: str) -> tuple[str, int, int] | None:
    tokens = [tok for tok in _collapse_ws(norm_text).split(" ") if tok]
    if not tokens:
        return None
    ws_pat = r"\s+".join(re.escape(tok) for tok in tokens)
    m = re.search(ws_pat, text)
    if m is not None:
        return text[m.start() : m.end()], m.start(), m.end()
    stripped_text, idx_map = _strip_invisible_with_index_map(text)
    if len(stripped_text) != len(text):
        m_s = re.search(ws_pat, stripped_text)
        if m_s is not None:
            mapped = _map_stripped_span_to_raw(idx_map, m_s.start(), m_s.end())
            if mapped is not None:
                return stripped_text[m_s.start() : m_s.end()], mapped[0], mapped[1]
    return None


def _reconcile_title_and_span(
    text: str,
    payload: dict[str, Any],
    *,
    title_key: str,
    span_key: str,
    repairs: list[str],
    repair_tag: str,
) -> None:
    title = payload.get(title_key)
    span = payload.get(span_key)
    if isinstance(title, str) and _INVISIBLE_FORMAT_RE.search(title):
        payload[title_key] = _collapse_ws(title)
        title = payload[title_key]
        repairs.append(repair_tag)
    if not isinstance(span, Mapping):
        return
    ok, _ = _verify_single_span_ref(text, dict(span), allow_whitespace_norm=True)
    if not ok:
        if isinstance(title, str) and title.strip():
            hit = _search_ws_tokens_in_text(text, title)
            if hit is not None:
                q_str, raw_lo, raw_hi = hit
                payload[span_key] = {"quote": q_str, "start": raw_lo, "end": raw_hi}
                repairs.append(repair_tag)
                return
        payload[span_key] = None
        repairs.append(repair_tag)
        return

    quote = str(span.get("quote") or "")
    norm_quote = _collapse_ws(quote)
    norm_title = _collapse_ws(str(title or ""))
    if norm_title == norm_quote and norm_quote:
        if _INVISIBLE_FORMAT_RE.search(quote):
            start = span.get("start")
            end = span.get("end")
            if _is_int_not_bool(start) and _is_int_not_bool(end):
                payload[span_key] = {"quote": strip_invisible_format_chars(quote), "start": start, "end": end}
                repairs.append(repair_tag)
        return

    # Line-wrap truncation or full-heading mismatch against a grounded title_span:
    # prefer expanding/aligning title to the verified grounded span if it contains title,
    # else try locating exact title in text, else clear unaligned title_span.
    if not norm_title or norm_title.casefold() in norm_quote.casefold() or norm_quote.casefold() in norm_title.casefold():
        start = span.get("start")
        end = span.get("end")
        if _is_int_not_bool(start) and _is_int_not_bool(end) and 0 <= start < end <= len(text):
            exact_slice = text[start:end]
            clean_slice = strip_invisible_format_chars(exact_slice)
            payload[title_key] = _collapse_ws(clean_slice)
            payload[span_key] = {
                "quote": clean_slice if _INVISIBLE_FORMAT_RE.search(exact_slice) else exact_slice,
                "start": start,
                "end": end,
            }
            repairs.append(repair_tag)
            return

    if isinstance(title, str) and title.strip():
        hit = _search_ws_tokens_in_text(text, norm_title)
        if hit is not None:
            q_str, raw_lo, raw_hi = hit
            payload[title_key] = _collapse_ws(q_str)
            payload[span_key] = {"quote": q_str, "start": raw_lo, "end": raw_hi}
            repairs.append(repair_tag)
            return

    payload[span_key] = None
    repairs.append(repair_tag)


def reconcile_and_validate_v7_payload(
    text: str,
    core_payload: Mapping[str, Any],
    specialist_payload: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, list[str], list[str]]:
    """Deterministically reconcile grounded spans and enforce canonical Pydantic + grounding validation."""
    from ..models import (
        CoreEnvelopeExtraction,
        DocStatus,
        SPECIALIST_MODELS,
        verify_grounded_extraction,
    )

    repairs: list[str] = []
    core = repair_span_refs_in_payload(text, copy.deepcopy(dict(core_payload)))
    spec = (
        repair_span_refs_in_payload(text, copy.deepcopy(dict(specialist_payload)))
        if specialist_payload is not None
        else None
    )

    # Repair 1: align title_span.quote and verbatim_title (and specialist event_title_span).
    _reconcile_title_and_span(
        text,
        core,
        title_key="verbatim_title",
        span_key="title_span",
        repairs=repairs,
        repair_tag="reconciled_title_span",
    )
    if spec is not None and "event_title_span" in spec:
        _reconcile_title_and_span(
            text,
            spec,
            title_key="event_title",
            span_key="event_title_span",
            repairs=repairs,
            repair_tag="reconciled_event_title_span",
        )

    # Repair 2: usable doc_date with empty date_spans -> synthesize literal date span or abstain.
    if core.get("status") == DocStatus.usable.value and core.get("doc_date") and not core.get("date_spans"):
        syn = _synthesize_grounded_date_span(text, str(core["doc_date"]))
        if syn is not None:
            core["date_spans"] = [syn]
            repairs.append("synthesized_grounded_date_span")
        else:
            core["doc_date"] = None
            repairs.append("abstained_ungrounded_doc_date")

    # Repair 3: specialist issuer_org grounded by issuer_org_span (e.g., abbreviated acronym vs full grounded span).
    if spec is not None and isinstance(spec.get("issuer_org_span"), Mapping):
        span_obj = spec["issuer_org_span"]
        if _verify_single_span_ref(text, dict(span_obj), allow_whitespace_norm=True)[0]:
            fam_val = core.get("specialist_family")
            if fam_val and fam_val in {f.value for f in SPECIALIST_MODELS}:
                from ..models import SpecialistFamily

                s_cls = SPECIALIST_MODELS[SpecialistFamily(fam_val)]
                try:
                    s_cls.model_validate(spec)
                except Exception:
                    spec["issuer_org"] = _collapse_ws(str(span_obj.get("quote") or ""))
                    repairs.append("reconciled_issuer_org_span")

    errors: list[str] = []
    core_model: CoreEnvelopeExtraction | None = None
    spec_model = None
    try:
        core_model = CoreEnvelopeExtraction.model_validate(core)
    except Exception as exc:
        errors.append(f"core_pydantic_invalid:{exc}")

    if spec is not None:
        if core_model is None or core_model.status != DocStatus.usable or core_model.specialist_family is None:
            spec = None
        else:
            s_cls = SPECIALIST_MODELS[core_model.specialist_family]
            try:
                spec_model = s_cls.model_validate(spec)
            except Exception as exc:
                errors.append(f"specialist_pydantic_invalid:{exc}")

    if core_model is not None and not errors:
        errors.extend(verify_grounded_extraction(core_model, spec_model, text, normalize_ws=True))

    return core, spec, repairs, errors


def _unwrap_payload_mapping(val: Any) -> Mapping[str, Any] | None:
    if isinstance(val, Mapping):
        return val
    if hasattr(val, "parsed") and isinstance(getattr(val, "parsed"), Mapping):
        return getattr(val, "parsed")
    return None


def adjudicate_three_family(
    text: str,
    results: Mapping[str, Any],
    *,
    doc_key: str = "doc",
    check_eval_fn: Callable[..., Any] | None = None,
) -> ConsensusDecision:
    """Adjudicate 3-family outputs into `auto_accept_gold`, `checkeval_resolved`, or `deadlock_needs_owner`."""
    family_tuples: dict[str, TriageTuple] = {}
    grounding_by_family: dict[str, GroundingResult] = {}
    payloads_by_family: dict[str, Mapping[str, Any]] = {}

    for fam, raw_res in results.items():
        payload = _unwrap_payload_mapping(raw_res)
        if payload is None:
            grounding_by_family[fam] = GroundingResult(
                passed=False,
                errors=[GroundingViolation("payload", "missing_or_unparsed_payload", None)],
            )
            continue
        tup = extract_triage_tuple(payload)
        assert tup is not None
        family_tuples[fam] = tup
        payloads_by_family[fam] = payload
        grounding_by_family[fam] = verify_span_grounding(text, payload)

    preview = _collapse_ws(text)[:320]
    total_families = len(results)
    if len(family_tuples) < 2 or total_families == 0:
        return ConsensusDecision(
            doc_key=doc_key,
            verdict="deadlock_needs_owner",
            accepted_tuple=None,
            accepted_payload=None,
            family_tuples=family_tuples,
            grounding_by_family=grounding_by_family,
            disagreeing_families=list(results.keys()),
            deadlock_reason="insufficient_valid_families",
            text_preview=preview,
        )

    tuple_counts = Counter(family_tuples.values())
    ranked = tuple_counts.most_common()

    # Case 1: Unanimous agreement across all configured families (3/3).
    if len(ranked) == 1 and len(family_tuples) == total_families:
        winning_tuple = ranked[0][0]
        failed_grounding = [f for f, gr in grounding_by_family.items() if not gr.passed]
        if failed_grounding:
            return ConsensusDecision(
                doc_key=doc_key,
                verdict="deadlock_needs_owner",
                accepted_tuple=None,
                accepted_payload=None,
                family_tuples=family_tuples,
                grounding_by_family=grounding_by_family,
                consensus_families=list(family_tuples.keys()),
                disagreeing_families=failed_grounding,
                deadlock_reason=f"grounding_failure:{','.join(failed_grounding)}",
                text_preview=preview,
            )

        merged = merge_consensus_payload(text, [payloads_by_family[f] for f in family_tuples])
        merged_grounding = verify_span_grounding(text, merged)
        if not merged_grounding.passed:
            return ConsensusDecision(
                doc_key=doc_key,
                verdict="deadlock_needs_owner",
                accepted_tuple=None,
                accepted_payload=None,
                family_tuples=family_tuples,
                grounding_by_family=grounding_by_family,
                consensus_families=list(family_tuples.keys()),
                deadlock_reason="merged_payload_grounding_failure",
                text_preview=preview,
            )
        return ConsensusDecision(
            doc_key=doc_key,
            verdict="auto_accept_gold",
            accepted_tuple=winning_tuple,
            accepted_payload=merged,
            family_tuples=family_tuples,
            grounding_by_family=grounding_by_family,
            consensus_families=list(family_tuples.keys()),
            disagreeing_families=[],
            text_preview=preview,
        )

    # Case 2: 2 vs 1 split (including 2 agreeing + 1 dissenting or 1 missing)
    # OR 2-family 1-vs-1 tie when CheckEval arbiter is supplied.
    if len(ranked) <= 2 and (
        ranked[0][1] >= 2
        or (total_families == 2 and len(ranked) == 2 and check_eval_fn is not None)
    ):
        maj_tuple = ranked[0][0]
        min_tuple = ranked[1][0] if len(ranked) == 2 else (None, None, None, None)
        grouped: dict[str, list[dict[str, Any]]] = {
            "majority": [dict(payloads_by_family[f]) for f, t in family_tuples.items() if t == maj_tuple],
            "minority": [dict(payloads_by_family[f]) for f, t in family_tuples.items() if t == min_tuple],
        }
        ce = run_checkeval_arbiter(
            text,
            maj_tuple,
            min_tuple,
            check_eval_fn=check_eval_fn,
            candidates=grouped,
        )
        if not ce.resolved or ce.winner_tuple is None:
            return ConsensusDecision(
                doc_key=doc_key,
                verdict="deadlock_needs_owner",
                accepted_tuple=None,
                accepted_payload=None,
                family_tuples=family_tuples,
                grounding_by_family=grounding_by_family,
                consensus_families=[f for f, t in family_tuples.items() if t == maj_tuple],
                disagreeing_families=[f for f in results if family_tuples.get(f) != maj_tuple],
                checkeval=ce,
                deadlock_reason=ce.reason or "checkeval_ambiguous",
                text_preview=preview,
            )

        winner_fams = [f for f, t in family_tuples.items() if t == ce.winner_tuple]
        grounded_winner_fams = [f for f in winner_fams if grounding_by_family[f].passed]
        if not grounded_winner_fams:
            return ConsensusDecision(
                doc_key=doc_key,
                verdict="deadlock_needs_owner",
                accepted_tuple=None,
                accepted_payload=None,
                family_tuples=family_tuples,
                grounding_by_family=grounding_by_family,
                consensus_families=winner_fams,
                disagreeing_families=[f for f in results if f not in winner_fams],
                checkeval=ce,
                deadlock_reason="checkeval_winner_failed_grounding",
                text_preview=preview,
            )

        merged = merge_consensus_payload(text, [payloads_by_family[f] for f in grounded_winner_fams])
        if not verify_span_grounding(text, merged).passed:
            return ConsensusDecision(
                doc_key=doc_key,
                verdict="deadlock_needs_owner",
                accepted_tuple=None,
                accepted_payload=None,
                family_tuples=family_tuples,
                grounding_by_family=grounding_by_family,
                consensus_families=grounded_winner_fams,
                disagreeing_families=[f for f in results if f not in grounded_winner_fams],
                checkeval=ce,
                deadlock_reason="checkeval_merged_failed_grounding",
                text_preview=preview,
            )
        return ConsensusDecision(
            doc_key=doc_key,
            verdict="checkeval_resolved",
            accepted_tuple=ce.winner_tuple,
            accepted_payload=merged,
            family_tuples=family_tuples,
            grounding_by_family=grounding_by_family,
            consensus_families=grounded_winner_fams,
            disagreeing_families=[f for f in results if f not in grounded_winner_fams],
            checkeval=ce,
            text_preview=preview,
        )

    # Case 3: 3-way deadlock.
    return ConsensusDecision(
        doc_key=doc_key,
        verdict="deadlock_needs_owner",
        accepted_tuple=None,
        accepted_payload=None,
        family_tuples=family_tuples,
        grounding_by_family=grounding_by_family,
        consensus_families=[],
        disagreeing_families=list(results.keys()),
        deadlock_reason="three_way_deadlock",
        text_preview=preview,
    )


def format_deadlock_digest(deadlocks: Sequence[ConsensusDecision | Mapping[str, Any]]) -> str:
    """Render a concise Markdown digest for ~10-minute owner review of unresolved deadlocks."""
    items = list(deadlocks)
    lines: list[str] = [
        "# DocMeta V7 Deadlock Digest for Owner Review",
        "",
        f"**Total deadlocks:** {len(items)}",
        "",
    ]
    if not items:
        lines.append("No deadlocks requiring owner intervention.")
        return "\n".join(lines) + "\n"

    reason_counts: Counter[str] = Counter()
    for item in items:
        reason = item.deadlock_reason if isinstance(item, ConsensusDecision) else item.get("deadlock_reason")
        reason_counts[str(reason or "unknown")] += 1

    lines.append("## Breakdown by Deadlock Reason")
    lines.append("")
    for reason, cnt in reason_counts.most_common():
        lines.append(f"- `{reason}`: {cnt}")
    lines.append("")

    for idx, item in enumerate(items, start=1):
        if isinstance(item, ConsensusDecision):
            doc_key = item.doc_key
            reason = item.deadlock_reason or "unknown"
            preview = item.text_preview
            fam_tuples = item.family_tuples
            grounding = item.grounding_by_family
            ce = item.checkeval
        else:
            doc_key = str(item.get("doc_key", f"doc_{idx}"))
            reason = str(item.get("deadlock_reason", "unknown"))
            preview = str(item.get("text_preview", ""))
            fam_tuples = dict(item.get("family_tuples", {}))
            grounding = dict(item.get("grounding_by_family", {}))
            ce = item.get("checkeval")

        lines.extend(
            [
                f"## {idx}. `{doc_key}` (`{reason}`)",
                "",
                f"> {preview}" if preview else "> *(no text preview)*",
                "",
                "| Family | status | media_format | is_packet | primary_genre | grounding |",
                "| :--- | :--- | :--- | :--- | :--- | :--- |",
            ]
        )
        all_fams = list(dict.fromkeys([*fam_tuples.keys(), *grounding.keys()]))
        for fam in all_fams:
            tup = fam_tuples.get(fam) or (None, None, None, None)
            gr = grounding.get(fam)
            if isinstance(gr, GroundingResult):
                gr_label = "PASS" if gr.passed else f"FAIL ({len(gr.errors)})"
            elif isinstance(gr, Mapping):
                gr_label = "PASS" if gr.get("passed") else "FAIL"
            else:
                gr_label = "N/A"
            lines.append(
                f"| `{fam}` | `{tup[0]}` | `{tup[1]}` | `{tup[2]}` | `{tup[3]}` | `{gr_label}` |"
            )
        lines.append("")

        # List grounding errors succinctly if present.
        for fam in all_fams:
            gr = grounding.get(fam)
            errs = gr.errors if isinstance(gr, GroundingResult) else (gr.get("errors", []) if isinstance(gr, Mapping) else [])
            if errs:
                err_strs = [
                    f"`{e.field_path}`:{e.reason}" if isinstance(e, GroundingViolation) else f"`{e.get('field_path')}`:{e.get('reason')}"
                    for e in errs[:4]
                ]
                lines.append(f"- **{fam} grounding issues:** {', '.join(err_strs)}")

        if isinstance(ce, CheckEvalResult) and ce.questions:
            lines.append(
                f"- **CheckEval arbiter:** `{ce.reason}` (majority={ce.majority_score:.1f}, minority={ce.minority_score:.1f})"
            )
            ans_map = {a.qid: a for a in ce.answers}
            for q in ce.questions:
                a = ans_map.get(q.qid)
                ans_txt = "YES" if (a and a.answer) else "NO"
                lines.append(f"  - `{q.qid}` ({ans_txt}): {q.question}")

        lines.extend(
            [
                "- **Owner decision:** `[ ] accept majority` / `[ ] accept minority` / `[ ] patch codebook`",
                "",
            ]
        )

    return "\n".join(lines) + "\n"


__all__ = [
    "CheckEvalAnswer",
    "CheckEvalQuestion",
    "CheckEvalResult",
    "ConsensusDecision",
    "GroundingResult",
    "GroundingViolation",
    "TriageTuple",
    "adjudicate_three_family",
    "build_checkeval_questions",
    "extract_triage_tuple",
    "format_deadlock_digest",
    "merge_consensus_payload",
    "reconcile_and_validate_v7_payload",
    "repair_span_refs_in_payload",
    "run_checkeval_arbiter",
    "strip_invisible_format_chars",
    "verify_span_grounding",
]
