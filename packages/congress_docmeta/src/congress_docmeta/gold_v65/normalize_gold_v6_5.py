#!/usr/bin/env python3
"""One deterministic normalisation pass over the DocMeta gold (owner decisions 2026-11-18).

Conventions: `packages/congress_docmeta/docs/ANNOTATION_RUBRIC.md` ("V6.5 House Conventions") and
`packages/congress_docmeta/docs/GOLD_CONTRACT.md`. Reads the gold as labeled, never edits a source file, and writes new files to
`lookups_and_gold/` (OUT_NAMES). Labels are the reviewers' raw JSON (`messages[-1].content`) plus this pass; the
trainer's rules R4-R6 are NOT baked in (`parse_gold_rows` is used only for each row's training `text`, `known`,
`filename`). Rules run in order X1-X4, K1-K13, F1-F10 (F5 after G1), then the data-driven A1 (transcript witness
additions), C1 (coordinator adjudications) and C2 (second-opinion rulings), which read reviewed files keyed by link key;
each is a pure function of (label, row context, those files), so a second run over the outputs changes nothing
(`--inputs-from-outputs`).

CPU only: MLX is blocked at import, and the production queue is read one row group at a time (~1.6 GB peak).

    python -m congress_docmeta.gold_v65.normalize_gold_v6_5
    python -m congress_docmeta.gold_v65.normalize_gold_v6_5 --inputs-from-outputs --out-dir DIR
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from .paths import resolve_docmeta_v6_data_dir, resolve_docmeta_v65_dir, resolve_package_fallback

sys.modules.setdefault("mlx", None)  # type: ignore[arg-type]  # CPU only: nothing here may load MLX

A_DIR = resolve_docmeta_v6_data_dir()
N_DIR = resolve_docmeta_v65_dir()
QUEUE_PARQUET = A_DIR / "parquets_v6_2" / "llm_queue_v6_2.parquet"
HELDOUT_KEYS = resolve_package_fallback(N_DIR / "lookups_and_gold" / "heldout_v6_4_183_link_keys.json", "heldout_v6_4_183_link_keys.json")
SCRATCH = N_DIR / "_scratch_normalize"
VERIFY_NOTES = SCRATCH / "verification_notes.json"  # optional notes folded into the review markdown

SETS = ("old", "gapfill_train", "gapfill_test")
IN_PATHS = {
    "old": A_DIR / "lookups_and_gold" / "train_v6_4_complete_ssot_gold.jsonl",
    "gapfill_train": N_DIR / "lookups_and_gold" / "train_v6_5_gapfill_train.jsonl",
    "gapfill_test": N_DIR / "lookups_and_gold" / "eval_v6_5_gapfill_test.jsonl",
}
OUT_NAMES = {
    "old": "gold_v6_5n_old.jsonl",
    "gapfill_train": "gold_v6_5n_gapfill_train.jsonl",
    "gapfill_test": "gold_v6_5n_gapfill_test.jsonl",
    "excluded": "gold_v6_5n_excluded.jsonl",
    "changelog": "normalize_changelog.jsonl",
    "summary": "normalize_summary.json",
    "review": "NORMALIZE_REVIEW.md",
    "signal": "gold_v6_5n_signal.jsonl",
    "dependencies": "rule_dependencies.json",
    "pending": "pending_owner_decisions.json",
    "second_opinion": "second_opinion_applied.jsonl",
}

# The seven letter kinds that may carry correspondence_flow (rubric, V6.5 House Conventions, Fields).
LETTER_KINDS = frozenset({
    "oversight_letter", "external_submission_letter", "nomination_or_support_letter", "witness_invitation",
    "qfr_request", "qfr_response", "public_comment_or_submission",
})
# F3 applies to the five kinds that are letters by form; qfr_response / public_comment are often not letters and
# their chair / ranking-member personas are usually questioners or addressed hosts, so they are left out.
F3_LETTER_KINDS = frozenset({
    "oversight_letter", "external_submission_letter", "nomination_or_support_letter", "witness_invitation",
    "qfr_request",
})
# F5: kinds whose document is the record of the event (doc_date == event_date in 93-100% of gold that has both).
EVENT_RECORD_KINDS = frozenset({
    "hearing_transcript", "event_web_page", "committee_vote", "attendance_quorum_sheet", "witness_list",
    "member_opening_statement", "witness_statement", "meeting_results",
})
HARD_ERROR_STATUSES = frozenset({"error_or_block", "stub_or_blank", "ocr_unreadable"})

W_AND_M = "House Committee on Ways and Means"
FINANCE = "Senate Committee on Finance"
JCT = "Joint Committee on Taxation"


# --------------------------------------------------------------------------------------------------------------
# Training context: the text, known string and filename the trainer shows for each row
# --------------------------------------------------------------------------------------------------------------
def _queue_subset(keys: set[str], cache: Path) -> Path:
    """Write the production-queue rows for `keys` to `cache`, reading one row group (~0.4 GB) at a time."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    keys_file = cache.with_suffix(".keys.json")
    if cache.is_file() and keys_file.is_file() and keys <= set(json.loads(keys_file.read_text())):
        return cache
    pf = pq.ParquetFile(QUEUE_PARQUET)
    want = pa.array(sorted(keys))
    parts = []
    for g in range(pf.metadata.num_row_groups):
        lk = pf.read_row_group(g, columns=["link_key_hex"]).column(0)
        mask = pc.is_in(lk, value_set=want)
        if pc.any(mask).as_py():
            parts.append(pf.read_row_group(g).filter(mask))
    tbl = pa.concat_tables(parts).sort_by("link_key_hex") if parts else pf.schema_arrow.empty_table()
    cache.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(tbl, cache)
    keys_file.write_text(json.dumps(sorted(keys)))
    return cache


def load_contexts(in_paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    """link_key -> {text, known, filename, in_queue} exactly as `parse_gold_rows` builds them (no blind skip)."""
    from congress_docmeta.gold import parse_gold_rows

    keys: set[str] = set()
    for p in in_paths.values():
        for line in p.open(encoding="utf-8"):
            if line.strip():
                keys.add(str(json.loads(line).get("link_key_hex") or ""))
    sub = _queue_subset(keys - {""}, SCRATCH / "cache" / "queue_subset_gold.parquet")
    ctx: dict[str, dict[str, Any]] = {}
    for p in in_paths.values():
        parsed, _ = parse_gold_rows(p, (), queue_parquet=sub)
        for r in parsed:
            ctx[r["link_key_hex"]] = {
                "text": r["text"], "known": r["known"], "filename": r["filename"],
                "in_queue": r["queue_row"] is not None, "alt_text": r["alt_text"],
            }
    return ctx


def norm_ground(s: str) -> str:
    """Case-folded, accent-stripped, quote-folded, whitespace-collapsed text for grounding checks."""
    s = unicodedata.normalize("NFKD", s or "")
    s = re.sub("[\u200b\u200c\u200d\u2060\ufeff]", "", s)  # zero-width spaces between words ('October\u200b 3,\u200b 2017')
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    s = re.sub("[\u2010\u2011\u2012\u2013\u2014\u2212\ufe63\uff0d]", "-", s).replace("\u00ad", "")
    s = s.translate(_TRANSLIT)
    return re.sub(r"\s+", " ", s).strip().lower()


# Letters NFKD does not decompose (Erik M\u00f8se, \u0141ukasz, \u0110or\u0111e, Stra\u00dfe, \u00c6sir).
_TRANSLIT = str.maketrans({"\u019f": "ti", "\u00f8": "o", "\u00d8": "O", "\u0142": "l", "\u0141": "L", "\u0111": "d", "\u0110": "D", "\u00df": "ss", "\u00e6": "ae", "\u00c6": "AE", "\u0153": "oe", "\u0152": "OE"})
_TRANSLIT_ALT = str.maketrans({"\u00f8": "oe", "\u00d8": "Oe", "\u00f6": "oe", "\u00fc": "ue", "\u00e4": "ae"})


def _cached(obj: Any, name: str, make: Callable[[], Any]) -> Any:
    """Per-row cache on a Ctx / TextFacts object (built once, on first use)."""
    if name not in obj.__dict__:
        obj.__dict__[name] = make()
    return obj.__dict__[name]


def camel_split(fn: str) -> str:
    """'HHRG-118-Wstate-SmithJ-2023.pdf' -> 'HHRG 118 Wstate Smith J 2023 pdf' (filenames carry names)."""
    s = re.sub(r"[_\-.()/]+", " ", fn or "")
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)


class Ctx:
    """Everything a rule may read about a row: the training text, known string, filename and row metadata."""

    def __init__(self, set_name: str, raw: dict[str, Any], c: dict[str, Any]):
        self.set_name = set_name
        self.lk = str(raw.get("link_key_hex") or "")
        self.raw = raw
        self.text: str = c["text"] or ""
        self.known: str = c["known"] or ""
        self.fn: str = c["filename"] or ""
        self.in_queue: bool = bool(c["in_queue"])
        self.alt_text: str = c.get("alt_text") or ""
        self.reviewer = str(raw.get("reviewer_id") or "")
        # Grounding is the training text only (owner, 2026-11-18): never `known`, the filename or the reviewer window.
        self.ground = norm_ground(self.text)

    def snippet(self, m: re.Match[str] | None, width: int = 260) -> str:
        if m is None:
            return re.sub(r"\s+", " ", self.text[:width])
        s0 = max(0, m.start() - width // 3)
        return re.sub(r"\s+", " ", self.text[s0 : s0 + width]).strip()


# --------------------------------------------------------------------------------------------------------------
# Label helpers
# --------------------------------------------------------------------------------------------------------------
def _schema_personas_max() -> int:
    """The format's people limit (`schema_v4.MAX_PERSONAS`, 26 since 2026-11-18), checked against the schema."""
    from congress_docmeta.pythonic_v5 import SCHEMA_OBJ
    from congress_docmeta.schema_v4 import MAX_PERSONAS

    if SCHEMA_OBJ["properties"]["personas"].get("maxItems") != MAX_PERSONAS:
        raise AssertionError("schema personas.maxItems disagrees with schema_v4.MAX_PERSONAS")
    return MAX_PERSONAS


def _schema() -> tuple[list[str], list[str], list[str]]:
    from congress_docmeta.pythonic_v5 import SCHEMA_OBJ

    return (
        list(SCHEMA_OBJ["properties"]),
        list(SCHEMA_OBJ["properties"]["personas"]["items"]["properties"]),
        list(SCHEMA_OBJ["properties"]["disclosure"]["properties"]),
    )


TOP_ORDER, PERSONA_ORDER, DISCLOSURE_ORDER = _schema()
PERSONAS_MAX = _schema_personas_max()


def canon(lab: dict[str, Any]) -> dict[str, Any]:
    """Schema key order at all three levels; empty lists / None dropped (the schema has minItems 1)."""
    out: dict[str, Any] = {}
    for k in TOP_ORDER:
        if k not in lab or lab[k] is None or lab[k] == [] or lab[k] == "":
            continue
        v = lab[k]
        if k == "personas":
            v = [{pk: p[pk] for pk in PERSONA_ORDER if pk in p and p[pk] is not None and p[pk] != [] and p[pk] != ""} for p in v]
        elif k == "disclosure" and isinstance(v, dict):
            v = {dk: v[dk] for dk in DISCLOSURE_ORDER if dk in v and v[dk] is not None and v[dk] != []}
        out[k] = v
    extra = [k for k in lab if k not in TOP_ORDER]
    if extra:
        raise ValueError(f"unknown label keys {extra}")
    return out


def kind(lab: dict[str, Any]) -> str | None:
    return lab.get("primary_kind") if lab.get("status", "usable") == "usable" else None


def set_kind(lab: dict[str, Any], new: str, add_secondary: list[str] = (), drop_secondary: set[str] = frozenset()) -> None:
    """primary_kind = new; secondary_kinds = rule secondaries + kept old secondaries (minus `drop_secondary`)."""
    old_sec = list(lab.get("secondary_kinds") or [])
    sec = list(add_secondary) + [s for s in old_sec if s not in drop_secondary and s not in add_secondary]
    lab["primary_kind"] = new
    lab["secondary_kinds"] = [s for s in dict.fromkeys(sec) if s != new]


def head(cx: Ctx, n: int) -> str:
    return cx.text[:n]


# --------------------------------------------------------------------------------------------------------------
# Row-level rules (X): decide exclusion; X4 rewrites the user prompt
# --------------------------------------------------------------------------------------------------------------
# X2: L3 `data/drop_from_gap_train_to_protect_heldout.txt` (siblings / re-posts of held-out docs; the gap-fill
# sampler was shown the held-out labels). Spec: remove these 13 keys from gapfill_train.
X2_DROP_GAPFILL_TRAIN = (
    "1166ee8b97d67fb8", "11e9106e5fe529d3", "2d508aa5978042fb", "46639ad2b24ec6ff", "4a5fdb85424507ea",
    "4b282a6de84f75a3", "8873698541d10be2", "8b46b2a6c328f152", "a62c115532ff106b", "a90524347bfee409",
    "b02bf0a1b43edd5a", "bb84cfb36cd72469", "df9a547e6201f8d2",
)
# X3: L3 `data/neardup_ge08_classified.csv`, class same_doc_repost with a gap-fill test copy, each pair re-read
# (see NORMALIZE_REVIEW.md). (test copy, training copy kept). The script re-measures the pair before excluding.
X3_REPOSTS = (
    ("86ae1e4b0d80a514", "4c61326120c0df3b"),  # Third Way report filed at two hearings (both in the 600 new docs)
    ("3fdc6cb033021e21", "fec9a7db0967b9d4"),  # DHS press release filed at two hearings (old training copy)
    ("9cb11a3d99d78042", "00fb3534a91fc292"),  # IOM slide deck under two filenames (gap-fill train copy)
)


def word_shingles(text: str, n: int = 5) -> set[str]:
    w = re.findall(r"[a-z0-9]+", norm_ground(text))
    return {" ".join(w[i : i + n]) for i in range(max(0, len(w) - n + 1))}


def jaccard(a: str, b: str) -> float:
    sa, sb = word_shingles(a), word_shingles(b)
    return len(sa & sb) / max(1, len(sa | sb))


PROD_KNOWN_ORDER = ("congress", "cmt", "chambers", "date")
_KNOWN_LINE_RE = re.compile(r"(Advisory known metadata:[ \t]*)(\{[^\n]*\})(\n)")


def x4_rewrite_known(user: str) -> tuple[str, str | None, str | None]:
    """Production form of the known JSON: keys congress,cmt,chambers,date; compact separators (json.dumps as
    `_build_precomputed_context_from_queue_row` writes it). Values are untouched."""
    m = _KNOWN_LINE_RE.search(user)
    if not m:
        return user, None, None
    before = m.group(2)
    d = json.loads(before)
    if set(d) - set(PROD_KNOWN_ORDER):
        raise ValueError(f"unexpected known keys {sorted(d)}")
    after = json.dumps({k: d[k] for k in PROD_KNOWN_ORDER if k in d}, separators=(",", ":"), ensure_ascii=False)
    if after == before:
        return user, None, None
    return user[: m.start(2)] + after + user[m.end(2) :], before, after


# --------------------------------------------------------------------------------------------------------------
# Kind rules (K): each returns an evidence snippet when it applies (and mutates `lab`), else None
# --------------------------------------------------------------------------------------------------------------
JCT_SCORE_RE = re.compile(
    r"Fiscal\s+Years?\s*\[?\s*(?:Millions|Billions)\s+of\s+Dollars"
    r"|Estimated\s+Revenue\s+Effects?"
    r"|Revenue\s+Effects?\s+of\s+the\s+(?:Provision|Proposal|Bill|Amendment)"
    r"|estimated\s+Federal\s+fiscal\s+year\s+budget\s+effects?"
    r"|effects?\s+on\s+Federal\s+fiscal\s+year\s+budget\s+receipts"
    r"|negligible\s+revenue\s+(?:loss|gain|effect)",
    re.I,
)
JCT_FAMILY_KINDS = {"section_by_section", "revenue_or_cost_estimate", "explanatory_statement",
                    "committee_amendment", "hearing_memo_or_charter"}


def k1_jct_description(lab: dict[str, Any], cx: Ctx) -> str | None:
    """JCT 'Description of ...' pamphlets and one-page substitute descriptions (JCX-NN-YY). Text only: the
    marking-up committee and its chamber come from the text's 'Scheduled for Markup by the ... Committee on Ways
    and Means / Finance' line (rubric: House for Ways and Means, Senate for Finance); a description whose text
    names no marking-up committee gets no committees and no chamber (rubric and spec: 'list none'), never an
    inferred one. issuer_org is JCT, whose name the detector requires in the text."""
    t = cx.text
    m = re.search(r"\bDESCRIPTION OF\b", t[:200])
    if not (m and re.search(r"JOINT\s+COMMITTEE\s+ON\s+TAXATION", t, re.I) and re.search(r"\bJCX-\d+-\d\d\b", norm_ground(t), re.I)):
        return None
    if kind(lab) is None:
        return None
    cx.__dict__["_k1_protect"] = True
    mk = re.search(r"Scheduled\s+for\s+Markup\s+by\s+the\s+(HOUSE\s+|SENATE\s+)?COMMITTEE\s+ON\s+(WAYS\s+AND\s+MEANS|FINANCE)", t, re.I)
    score = JCT_SCORE_RE.search(t)
    set_kind(lab, "section_by_section", ["revenue_or_cost_estimate"] if score else [], JCT_FAMILY_KINDS)
    if mk:
        cmt = W_AND_M if "WAYS" in mk.group(2).upper() else FINANCE
        lab["chamber"] = "house" if cmt == W_AND_M else "senate"
        lab["committees"] = [cmt, JCT]
    else:  # no marking-up committee named: committees = what the text names, the JCT; no chamber
        for v in [c for c in (lab.get("committees") or []) if c != JCT] + ([lab["chamber"]] if "chamber" in lab else []):
            _signal(cx, lab, "K1", "chamber" if v == lab.get("chamber") else "committees", v)
        lab.pop("chamber", None)
        lab["committees"] = [JCT]
    lab["issuer_org"] = JCT
    return f"[marking-up committee: {'text' if mk else 'none named'}; score={'yes' if score else 'no'}] " + cx.snippet(mk or m)


# K2: statements for the record, decided from the TEXT (never the filing slot in the filename).
SFR_SUBMIT_RE = re.compile(
    r"\bsubmit(?:s|ted|ting)?\b[^.]{0,80}?\bfor\s+the\s+(?:hearing\s+)?record|\bhereby\s+submit|statement\s+submitted\s+for\s+the\s+record",
    re.I)
SFR_TESTIMONY_RE = re.compile(
    r"\btestimony\s+of\b|\bstatement\s+of\s+.{3,120}?\s+before\s+the\s+(?:\w+\s+){0,6}(?:sub)?committee|\btestimony\s+before\s+the\b",
    re.I)
SFR_APPEAR_RE = re.compile(
    r"(?:opportunity|privilege|honor|pleasure|invitation|inviting\s+me|invited)\s+(?:to\s+)?(?:\w+\s+){0,4}(?:testify|appear|be\s+here|speak\s+(?:to|with|before)\s+you)"
    r"|(?:testify|appear)(?:ing)?\s+(?:before\s+you\s+)?today|before\s+you\s+today|my\s+testimony\s+today"
    r"|I\s+look\s+forward\s+to\s+(?:answering|your\s+questions|taking\s+your)",
    re.I)


def _letter_form(t: str) -> bool:
    return bool(re.search(r"\bDear\b", t[:4000]) and re.search(r"\b(Sincerely|Respectfully|Very truly yours|Regards|Cordially)\b", t))


def _author_role(lab: dict[str, Any], src: str, dst: str) -> None:
    for p in lab.get("personas") or []:
        if p.get("role") == src and p.get("entity_type") != "organization":
            p["role"] = dst


def k2_statement_for_record(lab: dict[str, Any], cx: Ctx) -> str | None:
    """A statement whose text says it is submitted for the record and never presents itself as testimony given
    ('Testimony of', 'before the Committee', 'opportunity to testify', 'testify today', 'answering questions')
    -> public_comment_or_submission; one that presents itself as testimony before the committee and addresses
    the panel as a witness, with no submission wording -> witness_statement. Otherwise the label stays."""
    k = kind(lab)
    if k not in ("witness_statement", "public_comment_or_submission", "external_submission_letter"):
        return None
    h = re.sub(r"\s+", " ", cx.text[:1500])
    sub, tes, app = SFR_SUBMIT_RE.search(h), SFR_TESTIMONY_RE.search(h), SFR_APPEAR_RE.search(cx.text)
    if sub and any(p.get("entity_type") == "member" and p.get("role") in ("witness", "author_or_speaker") for p in lab.get("personas") or []):
        cx.__dict__.setdefault("_flags", set()).add("K2_member_statement")  # coordinator: leave as labeled, list
        return None
    if sub and not tes and not app and (k == "witness_statement" or (k == "external_submission_letter" and not _letter_form(cx.text))):
        set_kind(lab, "public_comment_or_submission")
        _author_role(lab, "witness", "author_or_speaker")
        m = sub
    elif k == "public_comment_or_submission" and tes and app and not sub:
        set_kind(lab, "witness_statement")
        _author_role(lab, "author_or_speaker", "witness")
        m = tes
    else:
        return None
    return h[max(0, m.start() - 120) : m.end() + 140]


def k3_rules_committee_print(lab: dict[str, Any], cx: Ctx) -> str | None:
    if kind(lab) != "comparative_print":
        return None
    m = re.search(r"RULES\s+COMMITTEE\s+PRINT\s+\d{2,3}\s*[-\u2013\u2014]\s*\d+", cx.text[:400], re.I)
    s = re.search(r"\[\s*Showing\s+the\s+texts?\b", cx.text[:1000], re.I)
    if not (m and s and m.end() <= s.start()) or re.search(r"AMENDMENT", cx.text[m.end() : s.start()], re.I):
        return None
    set_kind(lab, "bill_or_draft")
    return cx.snippet(m)


AC_RES_RE = re.compile(r"RESOLUTION\s+OF\s+ADVICE\s+AND\s+CONSENT\s+TO\s+RATIFICATION", re.I)


def k4_treaty(lab: dict[str, Any], cx: Ctx) -> str | None:
    k, t = kind(lab), cx.text
    if k is None:
        return None
    ac = AC_RES_RE.search(t[:600])
    ac = ac if ac and re.search(r"\bResolved\b", t[:1500]) else None
    ex = re.search(r"EXEC\.\s*REPT\.", t[:600])
    ex = ex if ex and re.search(r"To\s+accompany\s+Treaty\s+Doc", t[:3000], re.I) else None
    tr = re.search(r"TREATY\s+DOC\.\s*\d", t[:600], re.I)
    tr = tr if tr and re.search(r"MESSAGE\s+FROM\s+THE\s+PRESIDENT", t[:1500], re.I) else None
    if not (ac or ex or tr):
        return None
    before = (k, list(lab.get("secondary_kinds") or []))
    set_kind(lab, "treaty_document", ["committee_report"] if ex else [])
    if (lab["primary_kind"], lab["secondary_kinds"]) == before:
        return None
    return cx.snippet(ac or ex or tr)


def k5_special_rule_report(lab: dict[str, Any], cx: Ctx) -> str | None:
    """House Rules special-rule paperwork, from the text: the heading carries a House Report number (first 300
    characters: 'Report No. 117-', '{ REPORT 113-'), the head says it is 'Providing for consideration of' a
    measure, and the text shows the H. RES. Floor-schedule pages that list such rules do not open with one."""
    t = cx.text
    m = re.search(r"PROVIDING\s+FOR\s+(?:THE\s+)?CONSIDERATION\s+OF", t[:600], re.I)
    rpt = re.search(r"Report\s+No\.|\{\s*REPORT\s+\d{2,3}|\bH\.\s*Rept\.", t[:300], re.I)
    if not (kind(lab) and m and rpt and re.search(r"\bH\.\s*RES\.", t, re.I)):
        return None
    before = (lab.get("primary_kind"), list(lab.get("secondary_kinds") or []))
    set_kind(lab, "committee_report", ["committee_resolution"], {"bill_or_draft"})
    if (lab["primary_kind"], lab["secondary_kinds"]) == before:
        return None
    return cx.snippet(m)


def k6_agenda_sheet(lab: dict[str, Any], cx: Ctx) -> str | None:
    t = cx.text
    if kind(lab) != "other" or len(t) > 2000 or re.search(r"ERRATA|COMMITTEE\s+PRINT", t):
        return None
    a = re.search(r"\bAGENDA\b", t, re.I)
    m = re.search(r"\b(MARK-?UP|BUSINESS\s+MEETING|ORGANIZATION(?:AL)?\s+MEETING)\b", t, re.I)
    if not (a and m):
        return None
    set_kind(lab, "markup_notice")
    return cx.snippet(a)


ANNOUNCES_ACTION_RE = re.compile(r"\bAnnounces\s+(?:Full\s+)?(?:Sub)?[Cc]ommittee\s+(?:\w+\s+){0,2}Action\b")


def k7_committee_action_release(lab: dict[str, Any], cx: Ctx) -> str | None:
    if kind(lab) not in ("press_release_or_fact_sheet", "meeting_results"):
        return None
    m = ANNOUNCES_ACTION_RE.search(re.sub(r"\s+", " ", cx.text[:900]))
    if not m:
        return None
    before = (lab.get("primary_kind"), list(lab.get("secondary_kinds") or []))
    set_kind(lab, "meeting_results", ["press_release_or_fact_sheet"])
    if (lab["primary_kind"], lab["secondary_kinds"]) == before:
        return None
    return re.sub(r"\s+", " ", cx.text[:900])[max(0, m.start() - 80) : m.end() + 160]


K8_SECTION_RE = re.compile(
    r"Streamline Icon: https://streamlinehq\.com|Press Releases|Opening Statements|Committee Statements|News\s*/\s*\w+")
K8_TITLE_END_RE = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\bWASHINGTON\b|\bWashington,|Share on"
    r"|\bImage\b|delivered the following|gave the following|Remarks as [Pp]repared|\(Remarks|Thank you|For Immediate Release"
    r"|Contact:|CONTACT:", re.I)
K8_REMARKS_RE = re.compile(
    r"opening\s+(?:statement|remarks)|delivered\s+the\s+following|gave\s+the\s+following|remarks\s+as\s+prepared"
    r"|statement\s+(?:of|at|for)\s+.{0,80}?\b(?:hearing|markup|mark\s?up)\b", re.I)


K8_WEB_RE = re.compile(
    r"Share on (?:Facebook|X|Twitter)|Skip to (?:main )?content|Print this Page|Streamline Icon|Main menu|\bMenu\b"
    r"|News\s*/|\bImage\b|Press Releases", re.I)
K8_NAV_WORDS_RE = re.compile(r"^(?:Editorials|Subcommittees|About|Hearings|Home|Menu|Contact|Issues|Legislation|Members|Press Contact)\b")


def k8_title(text: str) -> tuple[str, str, bool]:
    """(page head, page title, sits in a press-release / news section). The title follows the last site-section
    marker (breadcrumb, 'Press Releases', 'Opening Statements') unless that marker is only a menu item (the next
    words are more menu), and ends at the dateline, date or first body words."""
    head = re.sub(r"\s+", " ", text[:1600])
    secs = [m for m in K8_SECTION_RE.finditer(head[:1300])]
    body, section = head, ""
    if secs:
        rest = head[secs[-1].end() :].lstrip()
        if not K8_NAV_WORDS_RE.match(rest):
            body, section = rest, secs[-1].group(0)
    body = re.sub(r"^\s*(?:\d{1,2}\.\d{1,2}\.\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\s*", "", body)
    m = K8_TITLE_END_RE.search(body, 10)
    title = (body[: m.start()] if m else body[:200]).strip()
    news = bool(re.search(r"\bPress Release\b(?!s)|News\s*/\s*\w+", head) or section == "Press Releases")
    return head, title, news


def k8_member_remarks_page(lab: dict[str, Any], cx: Ctx) -> str | None:
    """Committee web pages carrying a member's hearing remarks, as the page presents itself in its text (a web
    page by its site chrome: share buttons, menus, breadcrumbs, never by its filename): titled 'Opening Statement'
    / 'Opening Remarks' -> member_opening_statement (+ press_release_or_fact_sheet when the page sits in a
    press-release / news section); otherwise marked 'Press Release' (or listed under Press Releases) or headlined
    with a quote -> press_release_or_fact_sheet + member_opening_statement. Other pages are left as labeled."""
    k = kind(lab)
    sec = lab.get("secondary_kinds") or []
    if k not in ("member_opening_statement", "press_release_or_fact_sheet"):
        return None
    if not K8_WEB_RE.search(re.sub(r"\s+", " ", cx.text[:900])):
        return None
    if not (k == "member_opening_statement" or "member_opening_statement" in sec or K8_REMARKS_RE.search(cx.text[:3000])):
        return None
    head, title, news = k8_title(cx.text)
    before = (k, list(sec))
    if re.search(r"Opening\s+(?:Statement|Remarks)", title, re.I):
        if news:
            cx.__dict__.setdefault("_flags", set()).add("K8_both_marks")
        set_kind(lab, "member_opening_statement", ["press_release_or_fact_sheet"] if news else [],
                 set() if news else {"press_release_or_fact_sheet"})
        why = "titled Opening Statement/Remarks" + (", in a press-release / news section" if news else "")
    elif news or re.search(r"^\W*[\"\u201c]|^[^:\"\u201c]{3,90}:\s*[\"\u201c]", title):
        set_kind(lab, "press_release_or_fact_sheet", ["member_opening_statement"])
        why = "marked Press Release" if news else "headlined with a quote"
    else:
        return None
    if (lab["primary_kind"], lab.get("secondary_kinds") or []) == before:
        return None
    return f"[{why}] title: {title[:160]}"


INVITE_RE = re.compile(
    r"(?:invites?|invited|inviting|request(?:s|ing)?\s+that)\s+you(?:\s+or\s+your\s+designee)?\s+(?:to\s+)?(?:testify|appear)",
    re.I,
)


def k9_testify_invitation(lab: dict[str, Any], cx: Ctx) -> str | None:
    if kind(lab) not in ("oversight_letter", "hearing_notice", "external_submission_letter", "other"):
        return None
    if not re.search(r"\bDear\b", cx.text[:3000]):
        return None
    m = INVITE_RE.search(re.sub(r"\s+", " ", cx.text[:5000]))
    if not m:
        return None
    set_kind(lab, "witness_invitation")
    return re.sub(r"\s+", " ", cx.text[:5000])[max(0, m.start() - 120) : m.end() + 120]


LEGAL_RECORD_RE = re.compile(
    r"\bSUBPOENA\b[\s\S]{0,60}\bAUTHORITY\s+OF\s+THE\s+(?:HOUSE|SENATE)"
    r"|\bDEPOSITION\s+OF:?\s+[A-Z]"
    r"|APPLICATION\s+TO\s+THE\s+OFFICE\s+OF\s+THE\s+COMPTROLLER"
    r"|UNITED\s+STATES\s+DISTRICT\s+COURT|SUPREME\s+COURT\s+OF\s+THE\s+UNITED\s+STATES|COURT\s+OF\s+APPEALS"
    r"|\bCase\s+(?:No\.\s*)?\d:\d{2}-[a-z]{2}-\d+",
    re.I,
)


def k10_legal_exhibit(lab: dict[str, Any], cx: Ctx) -> str | None:
    k = kind(lab)
    if k == "investigative_exhibit":
        m = LEGAL_RECORD_RE.search(cx.text[:600])
        if not m:
            return None
        set_kind(lab, "legal_or_investigative_filing", ["investigative_exhibit"])
        return cx.snippet(m)
    if k == "legal_or_investigative_filing" and "investigative_exhibit" not in (lab.get("secondary_kinds") or []):
        m = re.search(r"\bEXHIBIT\b", cx.text[:300])  # text only: an 'Exhibit' filename is not evidence
        if not m:
            return None
        set_kind(lab, "legal_or_investigative_filing", ["investigative_exhibit"])
        return "[exhibit marker] " + cx.snippet(m, 200)
    return None


def k11_property_resolution(lab: dict[str, Any], cx: Ctx) -> str | None:
    if kind(lab) not in ("committee_resolution", "gsa_prospectus_or_property"):
        return None
    t = cx.text
    m = re.search(r"Resolved\s+by\s+the\s+(?:Senate\s+)?Committee\s+on", t, re.I)
    if not (m and re.search(r"prospectus|\blease", t, re.I)
            and re.search(r"General\s+Services\s+Administration|Veterans\s+Affairs|\b3307\b|Title\s+40|40\s+U\.?S\.?C", t, re.I)):
        return None
    before = (lab.get("primary_kind"), list(lab.get("secondary_kinds") or []))
    set_kind(lab, "gsa_prospectus_or_property", ["committee_resolution"])
    if (lab["primary_kind"], lab["secondary_kinds"]) == before:
        return None
    return cx.snippet(m)


def k12_placeholder(lab: dict[str, Any], cx: Ctx) -> str | None:
    if lab.get("status", "usable") != "usable":
        return None
    t = cx.text.strip()
    redirect = re.search(r"please\s+wait\W+your\s+(?:file\s+)?download\s+will\s+begin", t, re.I) if len(t) < 400 else None
    words = re.sub(r"https?://\S+|www\.\S+", " ", t).split()
    video = re.search(r"youtube\.com|youtu\.be|vimeo\.com|c-span\.org/video", t, re.I) if len(words) <= 25 else None
    if not (redirect or video):
        return None
    why = ("Download-redirect placeholder page with no document content" if redirect
           else "Sheet holding only a video link, with no document content")
    for k, v in lab.items():
        if k in ("status", "text_quality", "primary_kind", "secondary_kinds", "subkind", "gist", "topics",
                 "composed_title", "event_type", "correspondence_flow", "venue_kind", "error_reason"):
            continue
        if k == "personas":
            for pp in v:
                _signal(cx, lab, "K12", "personas.name", pp.get("name"))
        else:
            for x in (v if isinstance(v, list) else [v]):
                _signal(cx, lab, "K12", k, x, sources=g1_sources(k, x, cx, lab) if k in ("congress", "chamber", "committees", "subcommittees") or k in G1_DATE_FIELDS else None)
    lab.clear()
    lab.update({"status": "stub_or_blank", "text_quality": "native", "error_reason": why})
    return re.sub(r"\s+", " ", t[:240])


# K13: single-document corrections from L1 suspects.tsv (gold_wrong_sample / rule_template_minority) and L2
# label_fixes_kind.json that no K1-K12 detector covers, applied only where the text was re-read and agreed with.
# Each carries a text assertion so a changed text window cannot be relabeled blindly.
K13_FIXES: dict[str, tuple[str, str, str]] = {
    # link key: (from kind, to kind, text that must be present)
    "002ad74ebb6b5247": ("meeting_results", "hearing_transcript", "RPTS DEAN"),  # verbatim stenographic meeting
    "7d93aa19d39510fc": ("event_web_page", "member_opening_statement", "I yield back"),  # member's remarks page
    "7f52fce5730b818f": ("public_comment_or_submission", "witness_statement", "I look forward to answering any questions"),
    "757c1e7307b49eff": ("bill_or_draft", "committee_amendment", "TEXT OF HOUSE AMENDMENT TO S. 1071"),
    # independent row review (raw_review_20261118 wrong_kind findings), each re-read and agreed with:
    "008ec8441d3deab6": ("agency_or_gao_crs_report", "witness_statement", "pleased to be here today"),  # GAO testimony delivered
    "13af259aaf9db19a": ("witness_statement", "public_comment_or_submission", "Mary Jane Scott, Mayor"),  # From/To submission, no testimony
    "274c945dc37724c1": ("meeting_results", "event_web_page", "Executive Session"),  # scraped event page with results (rubric)
    "81931b09a82857e4": ("legal_or_investigative_filing", "oversight_letter", "Dear Mr. Butler"),  # committee letter transmitting a subpoena
    "8fd63d9c0c162cc7": ("slides_or_visual", "error_or_non_document", "Vicinity Map"),  # single map (rubric)
    "e1fb173cdfd1454a": ("slides_or_visual", "error_or_non_document", "Annual drug cost in"),  # single chart (rubric)
    "e606cf89d6cc8e1b": ("slides_or_visual", "error_or_non_document", "Annual drug cost in"),  # single chart (rubric)
    "da57e5030b508c51": ("external_submission_letter", "public_comment_or_submission", "Statement for the record"),  # submitted for the record
    "eb1183b83d7b10f6": ("external_submission_letter", "public_comment_or_submission", "statement for the record"),  # submitted for the record
    "f6ec6396a48b15f1": ("slides_or_visual", "external_report_or_whitepaper", "Executive Summary"),  # multi-page prose report
    "ff11e30862426769": ("witness_statement", "external_report_or_whitepaper", "Geopolitical Shift in the Levant"),  # policy paper, no testimony
}
K13_SECONDARY = {"274c945dc37724c1": ["meeting_results"]}


def k13_single_doc(lab: dict[str, Any], cx: Ctx) -> str | None:
    fix = K13_FIXES.get(cx.lk)
    if not fix or kind(lab) != fix[0]:
        return None
    i = cx.text.find(fix[2])
    if i < 0:
        raise AssertionError(f"K13 text assertion failed for {cx.lk}: {fix[2]!r}")
    set_kind(lab, fix[1], K13_SECONDARY.get(cx.lk, []))
    if fix[1] == "witness_statement":
        _author_role(lab, "author_or_speaker", "witness")
    elif fix[1] in ("public_comment_or_submission", "external_report_or_whitepaper"):
        _author_role(lab, "witness", "author_or_speaker")
    return re.sub(r"\s+", " ", cx.text[max(0, i - 150) : i + 150])


# --------------------------------------------------------------------------------------------------------------
# Field rules (F)
# --------------------------------------------------------------------------------------------------------------
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_NOT_PERSON_TOKENS = {
    "of", "on", "the", "and", "for", "to", "at", "&", "committee", "subcommittee", "staff", "office", "department",
    "agency", "bureau", "council", "association", "commission", "corporation", "company", "inc", "llc",
    "university", "institute", "foundation", "coalition", "union", "group", "members",
}
_OCR_FOLD = (("rn", "m"), ("vv", "w"), ("0", "o"), ("1", "l"), ("5", "s"), ("|", "l"))


def _tok_norm(tok: str) -> str:
    return norm_ground(tok).strip(".,;:'\"()[]")


def _ocr_fold(s: str) -> str:
    for a, b in _OCR_FOLD:
        s = s.replace(a, b)
    return s.replace("i", "l")


def _edit_distance(a: str, b: str, cap: int) -> int:
    """Levenshtein distance, early exit above `cap`."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


class NameIndex:
    """Word positions of a row's training text, plus an OCR fallback: the text with spaces / dots / hyphens removed
    (for split tokens like 'gutie rrez'). The filename and `known` are never read."""

    def __init__(self, cx: "Ctx"):
        g = cx.ground
        self.g = g
        self.pos: dict[str, list[int]] = defaultdict(list)
        for m in re.finditer(r"\w+(?:'\w+)*", g):
            w = m.group(0)
            self.pos[w].append(m.start())
            if "'" in w:
                for part in w.split("'"):
                    if part:
                        self.pos[part].append(m.start())
            fm = re.fullmatch(r"([^\W\d_]{2,})\d{1,2}", w)
            if fm:  # a footnote mark glued to a name: 'Emily Gee1'
                self.pos[fm.group(1)].append(m.start())
        keep = [(i, ch) for i, ch in enumerate(g) if not (ch.isspace() or ch in ".-_")]
        self.collapsed = "".join(ch for _, ch in keep)
        self.cmap = [i for i, _ in keep]
        # words the text writes capitalised somewhere: an OCR-variant match must be one ('Hayper', 'LUMIS'), so a
        # common word one edit from a short surname ('adding' for Ading, a 'hought' file path) never counts
        self.caps = {norm_ground(m.group(0)) for m in re.finditer(r"(?<![\w])[A-Z][\w'\u2019]*", cx.text)}
        self.tri: dict[str, set[str]] = defaultdict(set)
        for w in self.pos:
            for i in range(len(w) - 2):
                self.tri[w[i : i + 3]].add(w)

    def hits(self, tok: str, fuzzy: bool) -> list[int]:
        """Word-start positions where the surname `tok` occurs as a whole word (hyphen parts allowed); when
        `fuzzy`, also OCR variants of 5+ letters (edit distance 1-3 by length: 'eumings', 'thonspion'), OCR
        truncations ('rask' for raskin, 'sco,' for scott), and a word split by OCR or a line break ('gutie rrez',
        matched on word boundaries only). Never a substring of another word."""
        parts = [p for p in re.split(r"[-\s]+", tok) if p]
        if not parts:
            return []
        out = list(self.pos.get(parts[0], []))
        if len(parts) > 1 and not all(self.pos.get(p) for p in parts[1:]):
            out = []
        if not fuzzy:
            return out
        flat = tok.replace("-", "").replace(" ", "")
        g = self.g
        if len(flat) >= 5:
            for m in re.finditer(re.escape(flat), self.collapsed):
                s0, e0 = self.cmap[m.start()], self.cmap[m.end() - 1] + 1
                if (s0 == 0 or not g[s0 - 1].isalnum()) and (e0 >= len(g) or not g[e0].isalnum()):
                    out.append(s0)
            cap = 1 if len(flat) <= 6 else (2 if len(flat) == 7 else 3)
            f = _ocr_fold(flat)
            cands = set().union(*(self.tri.get(flat[i : i + 3], set()) for i in range(len(flat) - 2)))
            for w in cands:
                if w not in self.caps:
                    continue
                if len(w) >= max(3, len(flat) - 2) and len(w) < len(flat) and flat.startswith(w):
                    out.extend(self.pos[w])  # truncated by OCR or a line break
                    continue
                if abs(len(w) - len(flat)) > cap or (w[:1] != flat[:1] and len(flat) < 7):
                    continue
                if _ocr_fold(w) == f or _edit_distance(w, flat, cap) <= cap:
                    out.extend(self.pos[w])
        return sorted(set(out))

    def beside(self, a: int) -> tuple[list[str], list[str]]:
        """Words written right next to the name word starting at `a`: up to four words before it (back to the
        nearest , ; :), and, in inverted order ('Smith, John R., Jr.'), up to four words after a comma."""
        g = self.g
        m = re.match(r"\w+(?:['\-]\w+)*", g[a:])
        end = a + (m.end() if m else 0)
        left = re.split(r"[,;:]", g[max(0, a - 80) : a])[-1]
        lw = re.findall(r"\w+", left)[-4:]
        rw: list[str] = []
        after = g[end : end + 60]
        nxt = re.match(r"\s*,?\s*(jr|sr|ii|iii|iv)\b", after)
        if nxt:
            rw.append(nxt.group(1))
        if re.match(r"\s*,", after):
            rw += re.findall(r"\w+", re.split(r"[;:]", after)[0])[:4]
        return lw, rw

    def near_variants(self, tok: str) -> list[int]:
        """Positions of words sharing the first four letters of a surname ('cassidliz' for cassidy): extra
        anchors for deciding whether a given name sits next to an OCR-damaged surname."""
        flat = tok.replace("-", "").replace(" ", "")
        if len(flat) < 5:
            return []
        return [p for w, ps in self.pos.items() if len(w) >= 4 and w[:4] == flat[:4] for p in ps]


# People the OCR / non-Latin exemption would keep but whom a re-read found named nowhere: not in the training text,
# the reviewer's window, or a damaged form (contract T02, 2026-11-18). Pallone: only the bioguide id P000034 in the
# filename. Carper: an EPW letterhead garbled past recognition; no word of the text resembles the name.
F1_CONFIRMED_ABSENT: dict[str, set[str]] = {
    "33ade507baeb3343": {"Pallone"},
    "72ee00234ef6026f": {"Thomas R. Carper"},
}


_TITLE_WORDS = frozenset({"mr", "mrs", "ms", "dr", "rep", "sen", "hon", "honorable", "the", "senator", "representative",
                          "congressman", "congresswoman", "chairman", "chairwoman", "chair", "member", "ranking", "by",
                          "of", "judge", "general", "gen", "adm", "col", "secretary", "ambassador", "governor", "gov"})


_CRED_WORDS = frozenset({"phd", "ph", "md", "jd", "esq", "dvm", "dds", "mph", "mba", "cpa"})


def _initial_beside(letters: str, lw: list[str], rw: list[str], name_words: set[str]) -> bool:
    """An initial written inside the run of this person's name words that stands right before the surname
    ('Dr. C. Reynold Verret', 'Allyson K. Anderson Book', 'J. R. Smith'), or right after the comma of an
    inverted name ('Smith, John R.', a transcript index's 'Boswell, Hon. Leonard L.', 'Meckes, R.D.'); never a stray
    letter elsewhere near it."""
    run = []
    for w in reversed(lw):
        if w not in name_words:
            break
        run.append(w)
    if letters in run or (len(letters) > 1 and letters in "".join(reversed(run))):
        return True
    rest = [w for w in rw if w not in _SUFFIXES or w == letters]  # 'Almanza, Alfred V.': V is the initial here
    while rest and (rest[0] in _TITLE_WORDS or rest[0] in _CRED_WORDS or (rest[0] == "d" and len(rest) < len(rw) and "ph" in rw)):
        rest = rest[1:]  # 'Boswell, Hon. Leonard L.', 'Ribera, Ph.D., Luis A.'
    fwd = []
    for w in rest:
        if w not in name_words:
            break
        fwd.append(w)
    return letters in fwd or (len(letters) > 1 and letters in "".join(fwd))


def _garbled_trace(idx: "NameIndex", sur: str) -> bool:
    """A text word that could be the surname after heavy OCR damage: 6+ letter surnames within a third of their
    length in edits (same first letter), or sharing the first four letters."""
    flat = sur.replace("-", "").replace(" ", "")
    if len(flat) < 6:
        return False
    cap = len(flat) // 3
    return any(len(w) >= 4 and w[0] == flat[0] and (w[:4] == flat[:4] or _edit_distance(w, flat, cap) <= cap) for w in idx.pos)


UNREADABLE_SHARE = 0.6  # text layers below this readable share are left as labeled (coordinator ruling 6/10)


def readable_share(text: str) -> tuple[float, int]:
    """(share of words that read as words, number of words): a word fails when its letters flip case inside it
    the way a font cipher does ('RepXblican', 'DemocUaWV', 'aQd') or carry cipher marks (\\ [ ] ³ ¶ ´). Measured
    on words of three or more characters; the two Ways and Means advisories read 0.34 and 0.44, every other text
    0.84 or more."""
    W = [w.strip(".,;:()\"'!?") for w in re.findall(r"\S+", text or "")]
    W = [w for w in W if len(w) >= 3 and re.search(r"[A-Za-z]", w)]
    if not W:
        return 1.0, 0
    bad = 0
    for w in W:
        core = re.sub(r"^(?:Mc|Mac|O'|De|La|Le|Di|Van|Von)", "", w)
        if (re.search(r"[a-z][A-Z]", core) and not re.fullmatch(r"[a-z]+[A-Z][a-z]+", core)) or re.search(r"[\\\[\]³¶´{}]", w[1:-1]):
            bad += 1
    return 1 - bad / len(W), len(W)


def unreadable(cx: "Ctx") -> bool:
    share, n = _cached(cx, "_readable", lambda: readable_share(cx.text))
    return n >= 20 and share < UNREADABLE_SHARE


def _non_latin_share(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    return sum(1 for ch in letters if ord(ch) > 0x24F) / max(1, len(letters))


def f1_names(lab: dict[str, Any], cx: Ctx) -> str | None:
    """Keep only name tokens the text shows near another token of the same name; drop absent people."""
    if lab.get("status", "usable") != "usable" or not lab.get("personas") or _non_latin_share(cx.text) > 0.2:
        return None
    idx = _cached(cx, "_nameindex", lambda: NameIndex(cx))
    kept: list[dict[str, Any]] = []
    notes: list[str] = []
    ps0 = lab["personas"]
    for p_idx, p in enumerate(ps0):
        name = str(p.get("name") or "")
        if _c2_keeps_person_name(cx, ps0, p_idx):
            kept.append(p)
            continue
        toks = name.split()
        norms = [_tok_norm(t) for t in toks]
        if p.get("entity_type") == "organization" or not toks or any(n in _NOT_PERSON_TOKENS for n in norms):
            kept.append(p)  # not a personal name ("Committee on Small Business Staff")
            continue
        # anchor: the surname (last token that is not a suffix or degree), found as a word (OCR-lenient). A
        # person whose surname the text does not show is not named there, even if a common first name occurs.
        core = [i for i, n in enumerate(norms) if n and n not in _SUFFIXES and not re.fullmatch(r"(ph\.?d|m\.?d|esq|j\.?d)", n)]
        anchor: tuple[int, list[int]] | None = None
        if core:
            h = idx.hits(norms[core[-1]], fuzzy=True)
            alt = toks[core[-1]].translate(_TRANSLIT_ALT)
            if not h and alt != toks[core[-1]]:  # Møse written Moese
                h = idx.hits(_tok_norm(alt), fuzzy=True)
            if h:
                anchor = (core[-1], h)
        if anchor is None:
            # In OCR text the surname can be present but damaged past the matcher ('ppislmamanthi'): the person
            # stays only when a word of the text is a plausible damaged form of the surname (same first letters,
            # or a few edits); a person with no such trace is removed (contract T02: 9 kept people were named
            # nowhere). Non-Latin texts are left to the owner (open question) and never reach here.
            if lab.get("text_quality", "native") != "native" and core and _garbled_trace(idx, norms[core[-1]]) and name not in F1_CONFIRMED_ABSENT.get(cx.lk, ()):
                kept.append(p)
                continue
            notes.append(f"removed '{name}'")
            _signal(cx, lab, "F1", "personas.name", name)
            continue
        ai, apos = anchor
        apos = sorted(set(apos) | set(idx.near_variants(norms[ai])))
        keep_idx = {ai}
        alen = len(norms[ai])
        # A given name, initial or suffix is kept only when the text writes it right beside the surname (any
        # occurrence, OCR-damaged surnames included). Given names of 5+ letters allow one OCR edit with the same
        # first letter; shorter ones and initials must match exactly ('E.' only if 'e' stands next to the name).
        beside = [idx.beside(a) for a in apos]
        for i, n in enumerate(norms):
            if i == ai or not n:
                continue
            letters = n.replace(".", "")
            if re.fullmatch(r"(ph\.?d|m\.?d|esq|j\.?d)", n):
                found = True  # a degree is not a name token; F1 leaves it as labeled
            elif re.fullmatch(r"(?:[^\W\d_]\.?){1,3}", n) and len(letters) <= 3 and (len(letters) == 1 or "." in n):
                # an initial counts only right beside the surname ('E. Cummings', 'J. R. Smith') or right after the
                # comma of an inverted name ('Smith, John R.'): never a stray letter somewhere near it
                name_words = {q for n2 in norms for q in (n2.replace(".", ""), *n2.replace(".", " ").split()) if q}
                found = any(_initial_beside(letters, lw, rw, name_words) for lw, rw in beside)
                given_before = [j for j in range(i) if j != ai and norms[j] and not re.fullmatch(r"(?:[^\W\d_]\.?){1,3}", norms[j])]
                if found and given_before and not any(j in keep_idx for j in given_before):
                    # the first name is not in the text: a middle initial alone is a fragment ('E. Cummings' from
                    # 'Eligh E. Eumings') unless the text itself writes '<initial> <surname>' (after a title or alone)
                    found = any(lw[-1:] == [letters] and (len(lw) < 2 or lw[-2] in _TITLE_WORDS) for lw, _ in beside)
            elif n in _SUFFIXES and i > 0:  # 'JR Shelton': a first token is a given name, not a suffix
                found = any(n in rw for _, rw in beside)
            else:
                parts = [q for q in re.split(r"[-\s]+", letters) if q]
                found = False
                for lw, rw in beside:
                    ws = lw + rw + [a + b for a, b in zip(lw, lw[1:])]  # a name split by OCR: 'g ene' for gene
                    if all(any(w == q or (len(q) >= 5 and w[:1] == q[:1] and _edit_distance(w, q, 1) <= 1) for w in ws) for q in parts):
                        found = True
                        break
            if found:
                keep_idx.add(i)
        new = " ".join(toks[i] for i in sorted(keep_idx))
        new = new.strip(" ,")
        if new != name:
            dropped = " ".join(t for i, t in enumerate(toks) if i not in keep_idx)
            _signal(cx, lab, "F1", "personas.name", name, kept_as=new, sources=g1_sources("personas.name", dropped, cx, lab))
            a0 = apos[0]
            notes.append(f"'{name}' -> '{new}' [text: \"{cx.ground[max(0, a0 - 45) : a0 + alen + 25]}\"]")
            p = dict(p)
            p["name"] = new
        kept.append(p)
    if not notes:
        return None
    lab["personas"] = kept
    return "; ".join(notes)


def f2_grid_people(lab: dict[str, Any], cx: Ctx) -> str | None:
    if kind(lab) not in ("committee_vote", "attendance_quorum_sheet"):
        return None
    ps = lab.get("personas") or []
    keep = [p for i, p in enumerate(ps) if p.get("role") not in ("chair", "ranking_member") or _c2_keeps_person_field(cx, ps, i, "role", p.get("role"))]
    if len(keep) == len(ps):
        return None
    gone = [f"{p['name']} ({p['role']})" for p in ps if p not in keep]
    lab["personas"] = keep
    return "removed " + ", ".join(gone)


_CLOSING_RE = re.compile(
    r"\b(?:sincerely(?:\s+yours)?|respectfully(?:\s+(?:yours|submitted))?|very\s+truly\s+yours|yours\s+truly"
    r"|best\s+regards|kind\s+regards|warm\s+regards|with\s+(?:best|warm|kind)\s+regards|cordially|regards)\s*,"
    r"|\bsincerel\b",  # OCR-truncated 'sincerel cc:'
    re.I,
)


_DATE_RE = re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b")
_CC_END_RE = re.compile(r"\b(?:attachments?|enclosures?|additional\s+questions|questions\s+(?:for\s+the\s+record|from))\b")


def _letter_regions(tl: str) -> dict[str, tuple[int, int]] | None:
    """Regions of a letter in `tl` (the row's normalised text, the start of `Ctx.ground`): salutation (from 'Dear'
    to the colon; without 'Dear', an opening 'Honorable ...' line), inside address (after the date that precedes
    the salutation, never the letterhead above the date), signature block (500 chars from the first closing, cut
    at a cc marker) and cc block (to the next attachment / enclosure / questions header, at most 400 chars)."""
    s = re.search(r"\bdear\s+", tl)
    if s:
        colon = tl.find(":", s.end(), s.end() + 250)
        sal = (s.start(), colon if colon > 0 else s.end() + 120)
    else:
        s = re.search(r"\bhonorable\s+", tl[:2000])
        if not s:
            return None
        stop = re.search(r"[:,]", tl[s.end() + 15 : s.end() + 200])
        sal = (s.start(), s.end() + 15 + (stop.start() if stop else 120))
    dates = list(_DATE_RE.finditer(tl, max(0, sal[0] - 700), sal[0]))
    addr = (dates[-1].end(), sal[0]) if dates else (sal[0], sal[0])
    c = _CLOSING_RE.search(tl, sal[1])
    cc = re.search(r"(?:^|\s)(?:cc|c\.c\.)\s*[:.]", tl[(c.end() if c else sal[1]) :])
    cc_reg = (0, 0)
    if cc:
        cc0 = (c.end() if c else sal[1]) + cc.start()
        end = _CC_END_RE.search(tl, cc0 + 4, cc0 + 400)
        cc_reg = (cc0, end.start() if end else cc0 + 400)
    sig = (0, 0)
    if c:
        sig = (c.start(), c.start() + 500)
        if cc_reg[0] > c.start():
            sig = (sig[0], min(sig[1], cc_reg[0]))
    return {"sal": sal, "addr": addr, "sig": sig, "cc": cc_reg}


# F3 decisions read by hand where the text places an office holder in both the signature block and the
# salutation / cc (none needed on the 2026-11-18 data; kept as the place to record one).
F3_DECISIONS: dict[tuple[str, str], str] = {}


def f3_letter_roles(lab: dict[str, Any], cx: Ctx) -> str | None:
    """On the five letter kinds an office role (chair, ranking member) becomes the function: a person whose
    surname (OCR-lenient) sits only in the signature block signs; only in the salutation, inside address or cc
    block is a `recipient`; named only in the letterhead or the body (neither signs nor is addressed) is removed.
    A sole listed signer is the `sender` when the name opens the signature block; office holders who sign with
    no other sender: the chair leads. Multi-signer sender/signatory order is left as labeled (garbled first
    signatures hide the true lead)."""
    if kind(lab) not in F3_LETTER_KINDS or not lab.get("personas"):
        return None
    tl = norm_ground(cx.text)
    reg = _letter_regions(tl)
    if reg is None:
        return None
    idx = _cached(cx, "_nameindex", lambda: NameIndex(cx))

    def inside(o: int, r: tuple[int, int]) -> bool:
        return r[0] <= o < r[1]

    def surname(p: dict[str, Any]) -> str:
        toks = [t for t in str(p.get("name") or "").split() if _tok_norm(t) not in _SUFFIXES]
        return _tok_norm(toks[-1]) if toks else ""

    def occ(p: dict[str, Any]) -> list[int]:
        sur = surname(p)
        return [h for h in idx.hits(sur, fuzzy=True) if h < len(tl)] if len(sur) >= 2 else []

    notes: list[str] = []
    ps = [dict(p) for p in lab["personas"]]
    converted: list[dict[str, Any]] = []
    office: dict[int, str] = {}
    gone: list[dict[str, Any]] = []
    c2_role_locked = {id(p) for i, p in enumerate(ps) if _c2_keeps_person_field(cx, ps, i, "role", p.get("role"))}
    for p in ps:
        if id(p) in c2_role_locked or p.get("entity_type") == "organization" or p.get("role") not in ("chair", "ranking_member"):
            continue
        os_ = occ(p)
        sig = [o for o in os_ if inside(o, reg["sig"])]
        rcp = [o for o in os_ if inside(o, reg["sal"]) or inside(o, reg["cc"]) or inside(o, reg["addr"])]
        strong = [o for o in os_ if inside(o, reg["sal"]) or inside(o, reg["cc"])]
        decided = F3_DECISIONS.get((cx.lk, str(p.get("name"))))
        if decided is None:
            if sig and not strong:
                decided = "signer"
            elif rcp and not sig:
                decided = "recipient"
            elif os_ and not sig and not rcp:
                decided = "remove"
        if decided == "signer":
            o = sig[0] if sig else os_[0]
            notes.append(f"{p['name']}: {p['role']} -> signer [text: \"{tl[max(0, o - 50) : o + 30]}\"]")
            office[id(p)] = p["role"]
            converted.append(p)
            p["role"] = "signatory"  # sender / signatory settled below
        elif decided == "recipient":
            o = (strong or rcp)[0]
            notes.append(f"{p['name']}: {p['role']} -> recipient [text: \"{tl[max(0, o - 50) : o + 30]}\"]")
            p["role"] = "recipient"
        elif decided == "remove":
            where = "letterhead" if all(o < reg["sal"][0] for o in os_) else "body or a later page's letterhead"
            notes.append(f"{p['name']}: {p['role']} removed: named only in the {where}, neither signs nor is addressed [text: \"{tl[max(0, os_[0] - 40) : os_[0] + 40]}\"]")
            gone.append(p)
        else:
            notes.append(f"{p['name']}: {p['role']} unresolved (signature={bool(sig)}, salutation/address/cc={bool(rcp)}, found={bool(os_)})")
    ps = [p for p in ps if p not in gone]
    signers = [p for p in ps if p.get("entity_type") != "organization" and p.get("role") in ("sender", "signatory")]
    lead = None
    if len(signers) == 1:
        p = signers[0]
        if any(inside(o, (reg["sig"][0], reg["sig"][0] + 250)) for o in occ(p)) or p in converted:
            lead = p
    elif converted and not any(p["role"] == "sender" for p in signers if p not in converted):
        # office holders who sign and no other sender: the chair leads (then the ranking member)
        lead = next((p for p in converted if office[id(p)] == "chair"), converted[0])
        signers = converted
    if lead is None:
        signers = []  # no evidence for who leads: sender / signatory stay as labeled
    for p in signers:
        if id(p) in c2_role_locked:
            continue
        want = "sender" if p is lead else "signatory"
        if p["role"] != want:
            notes.append(f"{p['name']}: {p['role']} -> {want}")
            p["role"] = want
    if ps == lab["personas"]:
        return None
    lab["personas"] = ps
    return "; ".join(notes)


def f4_flow_scope(lab: dict[str, Any], cx: Ctx) -> str | None:
    if "correspondence_flow" not in lab or kind(lab) in LETTER_KINDS or _c2_keeps_scalar(cx, "correspondence_flow", lab.get("correspondence_flow")):
        return None
    v = lab.pop("correspondence_flow")
    return f"{kind(lab)}: removed correspondence_flow={v}"


_MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                         "september", "october", "november", "december"], 1)}


def _parse_full_dates(s: str) -> set[str]:
    out = set()
    for m in re.finditer(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", s):
        mon = next((v for k, v in _MONTHS.items() if k.startswith(m.group(1).lower()[:3])), None)
        if mon:
            try:
                out.add(dt.date(int(m.group(3)), mon, int(m.group(2))).isoformat())
            except ValueError:
                pass
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", s):
        out.add(m.group(0))
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", s):
        try:
            out.add(dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat())
        except ValueError:
            pass
    return out


# F5 mode. The rubric (owner conventions, which win over the spec) says: "doc_date on event documents: when the
# text states no separate document date, doc_date is the event date." The spec (2026-11-18) says the opposite
# (never copy, remove a doc_date that only repeats the event date). "rubric" follows the rubric; "spec" the spec.
# F5, dates (owner decision B, rubric "Dates" bullet): a date goes in exactly one place. A document tied to a
# hearing, markup or meeting that prints a single date: that date is `event_date`, and `doc_date` is left out.
# `doc_date` is only for a date the text marks as the document's own (a letter's date line, a press-release
# dateline, 'Adopted:', 'Dated:', 'Submitted:') or a second, distinct date. A stated date is never dropped from
# both fields: when neither field holds a date and the text prints one, it goes to `event_date`. Runs after G1, so
# both fields hold only stated dates.
EVENT_TIED_KINDS = EVENT_RECORD_KINDS | {"hearing_notice", "markup_notice", "hearing_memo_or_charter",
                                         "truth_in_testimony_disclosure", "witness_biography"}
_OWN_DATE_BEFORE_RE = re.compile(
    r"(?:\bdated|\badopted|\bapproved|\bagreed to|\bissued|\breleased|\bposted|\bpublished|\bupdated|\brevised|\bsubmitted"
    r"|\bsigned|\bas of|date of (?:this )?(?:letter|memo(?:randum)?))(?: on)?\W{0,6}(?:[a-z]+day,?\s*)?$")
# a place-and-date line ('Washington, D.C. October 18, 2023' under a hearing title, 'HEARING HELD IN WASHINGTON, DC,
# SEPTEMBER 28, 2021') is the event's date, not a dateline; only a release page's 'WASHINGTON -' dateline counts
_RELEASE_RE = re.compile(r"for immediate release|press release|news release|media advisory|\bcontact:")
_RELEASE_PAGE_RE = re.compile(r"press release|for immediate release|news release|media advisory|share on (?:facebook|x|twitter|linkedin)|\btags?:")


def event_tied(lab: dict[str, Any]) -> bool:
    """Tied to a hearing, markup or meeting: an event kind, or a label that records the event (event_type /
    event_title), the same test the contract's T04 uses."""
    return bool(lab.get("event_type") or lab.get("event_title")) or kind(lab) in EVENT_TIED_KINDS
_EVENT_PHRASE_RE = re.compile(r"(?:hearing|markup|mark-up|meeting|session|roundtable|briefing|held|convene[sd]?|take place|scheduled)\b[^.]{0,60}$")


def _own_date(f: TextFacts, iso: str, memo: bool) -> bool:
    """The text marks this date as the document's own: 'Dated:', 'Adopted:', 'Submitted:', a dateline, a letter's
    date line (the date followed by 'Dear ...'), or for a memo its 'Date:' line."""
    t = f.norm
    release_page = bool(_RELEASE_PAGE_RE.search(t[:1500]))
    for p in date_positions(f, iso):
        before = t[max(0, p - 160) : p]
        if _OWN_DATE_BEFORE_RE.search(before[-45:]) or (memo and re.search(r"\bdate\s*:?\s*$", before[-45:])):
            return True
        if _RELEASE_RE.search(before[-120:]) or re.search(r"\bjcx-\d", t[max(0, p - 200) : p + 200]):  # a JCX paper's date; a JCS-printed transcript's cover date is the hearing's
            return True
        if release_page and (p < 1500 or re.search(r"\bwashington\b\W{0,4}(?:d\.?\s?c\.?)?\W{0,4}$", before[-30:])):
            return True
        if re.search(r"\bdear\b", t[p : p + 450]) and not re.search(r"\bdear\b", t[max(0, p - 600) : p]):
            return True
    return False


def _first_printed_date(f: TextFacts) -> str | None:
    """The date a vote sheet, notice, cover or statement prints as its own date line: a 'Date:' field, or a line in
    the first 60 lines that holds only a date (a weekday allowed), read through scan damage. Never a date inside a
    sentence ('assumed his position on January 12, 2015'): those are what the document is about."""
    def parse(seg: str) -> str | None:
        fix = lambda x: x.replace("o", "0").replace("l", "1").replace("i", "1").replace("|", "1").replace("!", "1").replace("z", "2")
        m = re.fullmatch(r"([0-9o]?[0-9lio|!])\s?[./\\\-:|•·]\s?([0-9o]?[0-9lio|!z])\s?[./\\\-:|,•·]\s?((?:19|20)[0-9]{2}|[0-9li|!o]{2})", seg)
        if m:
            mo, d, y = int(fix(m.group(1))), int(fix(m.group(2))), fix(m.group(3))
            yy = int(y) if len(y) == 4 else 2000 + int(y) if int(y) < 50 else 1900 + int(y)
            return _iso(yy, mo, d)
        m = re.fullmatch(_MON_RE + r"\.?\s*,?\s*" + _DAY + r"\s*,?\s*" + _YEAR, seg)
        if m:
            return _iso(int(m.group(3)), _MON[m.group(1)[:3]], int(m.group(2)))
        return None
    head = f.norm[:1500]
    for m in re.finditer(r"date\s*[:.]?\s*((?:[a-z]+day,?\s*)?[^\n]{4,22}?)(?=\s{2}|\s[a-z]{4,}|$)", head):  # 'xdate:' (OCR)
        seg = re.sub(r"^[a-z]+day,?\s*", "", m.group(1)).strip(" .,;")
        for cut in range(len(seg), 3, -1):
            iso = parse(seg[:cut].strip(" .,;"))
            if iso:
                return iso
    for line in [norm_ground(x).strip() for x in f.text.splitlines()[:60]]:
        bare = re.sub(r"^(?:[a-z]+day,?\s*)", "", line).strip(" .,:;_-")
        if 6 <= len(bare) <= 24:
            iso = parse(bare)
            if iso:
                return iso
    return None

def f5_dates(lab: dict[str, Any], cx: Ctx) -> str | None:
    k = kind(lab) or lab.get("status")  # masthead statuses (cover_or_toc, govinfo_wrapper ...) carry dates too
    if lab.get("status", "usable") in HARD_ERROR_STATUSES or _non_latin_share(cx.text) > 0.2:
        return None
    f = facts(cx)
    d, e = lab.get("doc_date"), lab.get("event_date")
    full_d = bool(d and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d))
    tied = event_tied(lab)
    memo = k == "hearing_memo_or_charter"
    if d and e and d == e:
        # the text marks the date as the document's own (dateline, letter date line, 'Adopted:') -> doc_date, even
        # on a page tied to a hearing (coordinator: 87a608cfeb04ed7e, a78d422c50a9d932); otherwise -> event_date
        if not _own_date(f, d, memo):
            if _c2_keeps_scalar(cx, "doc_date", d):
                return None
            _signal(cx, lab, "F5", "doc_date", lab.pop("doc_date"), kept_as="event_date", sources=["moved_to_one_field"])
            return f"{k}: one printed date, not marked as the document's own -> event_date only"
        if len(date_positions(f, e)) >= 2 or any(_EVENT_PHRASE_RE.search(f.norm[max(0, p - 80) : p]) for p in date_positions(f, e)) or _c2_keeps_scalar(cx, "event_date", e):
            return None  # the document's own date, and the text separately presents that day as the event's
        _signal(cx, lab, "F5", "event_date", lab.pop("event_date"), kept_as="doc_date", sources=["moved_to_one_field"])
        return f"{k}: one printed date, the document's own -> doc_date only"
    if not tied:
        return None
    if d and not e and full_d and not _own_date(f, d, memo) and not _c2_keeps_scalar(cx, "doc_date", d) and not _c2_drops_scalar(cx, "event_date"):
        _signal(cx, lab, "F5", "doc_date", d, kept_as="event_date", sources=["moved_to_one_field"])
        lab["event_date"] = lab.pop("doc_date")
        return f"{k}: the single printed date is the event's -> event_date"
    if not d and not e:
        iso = _first_printed_date(f)
        if iso and not c1_removes(cx, "event_date", iso) and not _c2_drops_scalar(cx, "event_date") and not _c2_drops_scalar(cx, "doc_date"):  # never re-add a date C1 or C2 struck
            lab["event_date"] = iso
            return f"{k}: the text prints {iso} and neither field held it -> event_date"
    return None


def _ref_id_patterns(ref: str) -> list[str]:
    """The citation's identifying number: its most specific (last) digit group, joined to the group before it
    when the two form one id ("110-41", "99-177", "300a-7", "51-602"). Qualifiers the text often leaves implied
    (a U.S.C. title, a Federal Register volume, an act's year) are not required. Numberless refs: nothing."""
    body = ref.split(":", 1)[-1]
    nums = list(re.finditer(r"\d+", body))
    if not nums:
        return []
    last = nums[-1]
    b = last.group(0).lstrip("0") or "0"
    if len(nums) >= 2 and re.fullmatch(r"[A-Za-z]?\s*[-–]\s*", body[nums[-2].end() : last.start()]):
        a = nums[-2].group(0).lstrip("0") or "0"
        return [rf"(?<!\d)0*{a}[a-z]?\s*-\s*0*{b}(?!\d)"]  # zero padding: 'house report 110-041'
    if ref.startswith(("usc:", "cfr:")):
        # '§' read by OCR as '$8' or '8': '5 u.s.c. $8554', '5. u.s.c. 8555'
        return [rf"(?:(?<!\d)|[§$]\s*8?|u\.?\s?s\.?\s?c\.?\s*8)0*{b}(?!\d)"]
    return [rf"(?<!\d)0*{b}(?!\d)"]


def _ref_grounded(ref: str, ground: str) -> bool:
    """`ground`: the normalised training text (norm_ground). Besides the identifying number as written, accepts
    OCR letters for digits in a clause ('2(g)(s)'), a bill line number inside a compound citation ('300x- 8 2'),
    and the two parts of a compound number written apart ('report no. 670 ... 61st congress')."""
    pats = _ref_id_patterns(ref)
    if all(re.search(p, ground) for p in pats):
        return True
    ocr = re.sub(r"\((s)\)", "(5)", re.sub(r"\((o)\)", "(0)", ground))
    if ocr != ground and all(re.search(p, ocr) for p in pats):
        return True
    body = ref.split(":", 1)[-1]
    nums = re.findall(r"\d+", body)
    if len(nums) >= 2 and re.search(r"\d+\s*[A-Za-z]?\s*[-\u2013]\s*\d+\D*$", body):
        a, b = nums[-2].lstrip("0") or "0", nums[-1].lstrip("0") or "0"
        if re.search(rf"(?<!\d)0*{a}[a-z]?\s*-\s*(?:\d{{1,2}}\s+)?0*{b}(?!\d)", ground):
            return True
        if re.search(rf"(?<!\d)0*{a}(?:st|nd|rd|th|d)?(?!\d).{{0,90}}?(?<!\d)0*{b}(?!\d)|(?<!\d)0*{b}(?!\d).{{0,90}}?(?<!\d)0*{a}(?:st|nd|rd|th|d)?(?!\d)", ground):
            return True
    nospace = re.sub(r"\s+", "", ground)
    if all(re.search(p, nospace) for p in pats):
        return True  # OCR split a number: 'house report 11 9- 272'
    d = re.fullmatch(r".*?(\d{4})-(\d{2})-(\d{2})", ref)
    return bool(d and f"{d.group(1)}-{d.group(2)}-{d.group(3)}" in _parse_full_dates(ground))  # 'October 25, 2019'


def f6_ref_grounding(lab: dict[str, Any], cx: Ctx) -> str | None:
    refs = lab.get("refs") or []
    if not refs:
        return None
    keep, gone = [], []
    for ref in refs:
        if _ref_grounded(ref, cx.ground) or _c2_keeps_item(cx, "refs", ref):
            keep.append(ref)
        else:
            gone.append(ref)
            _signal(cx, lab, "F6", "refs", ref)
    if not gone:
        return None
    lab["refs"] = keep
    return "removed " + "; ".join(gone)


def _sub_norm(s: str) -> str:
    s = s.lower().replace("&", "and")
    s = re.sub(r"^(house|senate|joint)\s+", "", s)
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(r"\b(the|and|of|on|for)\b", " ", s)
    return " ".join(s.split())


class SubcommitteeCanon:
    """Canonical subcommittee spelling per normalised name: the roster `name`, else the gold majority."""

    def __init__(self, labels: list[dict[str, Any]]):
        R = json.loads((A_DIR / "lookups_and_gold" / "rosters_lookup_v6.json").read_text())
        roster: dict[str, set[str]] = defaultdict(set)
        for m in R["subcommittees_meta"].values():
            if m.get("name"):
                roster[_sub_norm(m["name"])].add(m["name"])
        counts: dict[str, Counter[str]] = defaultdict(Counter)
        for lab in labels:
            for s in lab.get("subcommittees") or []:
                counts[_sub_norm(s)][s] += 1
        self.canon: dict[str, str] = {}
        for key, c in counts.items():
            spellings = [s for s in c if s in roster.get(key, set())]
            if len(spellings) == 1:
                self.canon[key] = spellings[0]
                continue
            # Rubric: "and", not "&"; no leading "the". Among those, the gold majority (ties: keep as labeled).
            ok = [s for s in c if "&" not in s and not s.lower().startswith("the ")]
            ranked = sorted(ok or list(c), key=lambda s: (-c[s], s))
            if len(ranked) == 1 or c[ranked[0]] > c[ranked[1]]:
                self.canon[key] = ranked[0]


def _sub_clean(s: str) -> str:
    """Rubric spelling rules on any name, including ones spelled only one way: 'and', not '&'; no leading 'the'."""
    s = re.sub(r"\s*&\s*", " and ", s)
    s = re.sub(r"^the\s+", "", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


SUBCMTE: SubcommitteeCanon | None = None


def f7_subcommittee_spelling(lab: dict[str, Any], cx: Ctx) -> str | None:
    subs = lab.get("subcommittees") or []
    if not subs or SUBCMTE is None:
        return None
    new = [s if _c2_keeps_item(cx, "subcommittees", s) else _sub_clean(SUBCMTE.canon.get(_sub_norm(s), s)) for s in subs]
    new = list(dict.fromkeys(new))
    if new == subs:
        return None
    lab["subcommittees"] = new
    return "; ".join(f"{a} -> {b}" for a, b in zip(subs, new) if a != b) or "dedup"


REF_PREFIX_MAP = {"rpt": "rept", "res": "bill", "pl": "law", "reg": "cfr", "serial": "hrg", "case": "id"}


def f8_ref_prefix(lab: dict[str, Any], cx: Ctx) -> str | None:
    refs = lab.get("refs") or []
    new = []
    for r in refs:
        if _c2_keeps_item(cx, "refs", r):
            new.append(r)
            continue
        p, _, body = r.partition(":")
        new.append(f"{REF_PREFIX_MAP[p]}:{body}" if p in REF_PREFIX_MAP else r)
    new = list(dict.fromkeys(new))
    if new == refs:
        return None
    lab["refs"] = new
    return "; ".join(f"{a} -> {b}" for a, b in zip(refs, new) if a != b)


class CommitteeNames:
    """(code, congress) -> committee name from the gold itself: rows whose known names one committee code and
    whose label names one committee of that chamber vote for the name (era-aware; falls back to the code's
    single unambiguous name across congresses)."""

    def __init__(self, rows: list[tuple[dict[str, Any], "Ctx"]]):
        by_cc: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
        by_c: dict[str, Counter[str]] = defaultdict(Counter)
        for lab, cx in rows:
            try:
                kn = json.loads(cx.known)
            except Exception:
                continue
            codes = {c[:4] for c in kn.get("cmt") or [] if re.fullmatch(r"[a-z]{4}\d\d", c)}
            cmts = lab.get("committees") or []
            if len(codes) != 1 or len(cmts) != 1:
                continue
            code = next(iter(codes))
            prefix = {"h": "House ", "s": "Senate ", "j": "Joint "}.get(code[0], "")
            if not cmts[0].startswith(prefix):
                continue
            if kn.get("congress"):
                by_cc[(code, int(kn["congress"]))][cmts[0]] += 1
            by_c[code][cmts[0]] += 1
        self.by_cc, self.by_c = by_cc, by_c

    def name(self, code: str, congress: int | None) -> str | None:
        code = code[:4]
        c = self.by_cc.get((code, congress)) if congress else None
        if c:
            top = c.most_common(2)
            if len(top) == 1 or top[0][1] > top[1][1]:
                return top[0][0]
        c = self.by_c.get(code)
        if c and len(c) == 1:
            return next(iter(c))
        return None


CMTNAMES: CommitteeNames | None = None
def f10_nonusable_kind(lab: dict[str, Any], cx: Ctx) -> str | None:
    if lab.get("status", "usable") == "usable" or _c2_keeps_scalar(cx, "status", "usable"):
        return None
    gone = {k: lab.pop(k) for k in ("primary_kind", "secondary_kinds", "subkind") if k in lab}
    return f"status={lab['status']}: removed {gone}" if gone else None


# --------------------------------------------------------------------------------------------------------------
# G1: text only. A value of a factual field stays only if the TRAINING TEXT states it (owner, 2026-11-18).
# Matching is lenient about spelling (case, accents, punctuation, '&'/'and', 'U.S.'/'United States', state names
# and postal codes, common abbreviations, OCR splits and one-or-two-letter OCR errors in long words), never about
# content: a different number, a different word, or a value found only in `known` / the filename is not stated.
# --------------------------------------------------------------------------------------------------------------
_STATE_CODES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar", "california": "ca", "colorado": "co",
    "connecticut": "ct", "delaware": "de", "florida": "fl", "georgia": "ga", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks", "kentucky": "ky", "louisiana": "la",
    "maine": "me", "maryland": "md", "massachusetts": "ma", "michigan": "mi", "minnesota": "mn",
    "mississippi": "ms", "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new hampshire": "nh", "new jersey": "nj", "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa",
    "rhode island": "ri", "south carolina": "sc", "south dakota": "sd", "tennessee": "tn", "texas": "tx",
    "utah": "ut", "vermont": "vt", "virginia": "va", "washington": "wa", "west virginia": "wv",
    "wisconsin": "wi", "wyoming": "wy", "puerto rico": "pr", "guam": "gu",
}
_AP_STATES = {"ala": "al", "ariz": "az", "ark": "ar", "calif": "ca", "colo": "co", "conn": "ct", "del": "de", "fla": "fl",
              "ga": "ga", "ill": "il", "ind": "in", "kan": "ks", "ky": "ky", "la": "la", "md": "md", "mass": "ma",
              "mich": "mi", "minn": "mn", "miss": "ms", "mo": "mo", "mont": "mt", "neb": "ne", "nev": "nv",
              "okla": "ok", "ore": "or", "pa": "pa", "tenn": "tn", "tex": "tx", "va": "va", "vt": "vt", "wash": "wa",
              "wis": "wi", "wyo": "wy"}
_PHRASE_MAP = [
    (re.compile(r"&"), " and "),
    (re.compile(r"\bu\.\s?s\.\s?a\.?(?![a-z])"), " usa "),
    (re.compile(r"\bu\.\s?s\.(?![a-z])"), " us "),
    (re.compile(r"\bunited states of america\b"), " usa "),
    (re.compile(r"\bunited states\b"), " us "),
    (re.compile(r"\bd\.\s?c\.(?![a-z])"), " dc "),
    (re.compile(r"\bunited kingdom\b|\bu\.k\.(?![a-z])"), " uk "),
    (re.compile(r"\b(ala|ariz|ark|calif|colo|conn|del|fla|ga|ill|ind|kan|ky|la|md|mass|mich|minn|miss|mo|mont|neb|nev|okla|ore|pa|tenn|tex|va|vt|wash|wis|wyo)\.(?=\s|,|$)"),
     lambda m: " " + _AP_STATES[m.group(1)] + " "),
    (re.compile(r"\bdistrict of columbia\b"), " dc "),
    (re.compile(r"\b(" + "|".join(sorted(_STATE_CODES, key=len, reverse=True)) + r")\b"),
     lambda m: " " + _STATE_CODES[m.group(1)] + " "),
]
_TOKEN_MAP = {  # abbreviations expanded (so OCR-damaged full words still match), a few spelling variants folded
    "dept": "department", "depts": "departments", "natl": "national", "intl": "international",
    "assn": "association", "govt": "government", "univ": "university", "inst": "institute",
    "institution": "institute", "corp": "corporation", "incorporated": "inc", "ltd": "limited",
    "sen": "senator", "rep": "representative", "chairman": "chair", "chairwoman": "chair", "chairperson": "chair",
    "dir": "director", "asst": "assistant", "gen": "general", "lt": "lieutenant", "col": "colonel",
    "maj": "major", "capt": "captain", "adm": "admiral", "ave": "avenue", "street": "st", "blvd": "boulevard",
    "ste": "suite", "bldg": "building", "rd": "road", "dr": "drive", "northwest": "nw", "southwest": "sw",
    "northeast": "ne", "southeast": "se", "mt": "mount", "ft": "fort", "number": "no", "centre": "center",
    "programme": "program", "defence": "defense", "labour": "labor", "organisation": "organization",
    "sr": "senior", "jr": "junior", "chairmen": "chair", "chairs": "chair", "kiev": "kyiv", "prc": "china",
}
_WEAK = frozenset({"of", "and", "for", "on", "in", "to", "a", "an", "at", "by", "with", "us", "usa", "s"})
_ACR_STOP = frozenset({"of", "and", "for", "the", "on", "in", "to", "at", "a", "an", "by", "with"})
_IGNORABLE_SEG = frozenset({"inc", "llc", "ltd", "jr", "sr", "ii", "iii", "iv", "phd", "md", "esq", "co", "corp",
                            "pc", "lp", "llp", "pllc", "ret", "the"})


def _canon_tokens(s: str) -> list[str]:
    """Canonical word tokens used on both sides of every G1 comparison."""
    s = norm_ground(s)
    for rx, rep in _PHRASE_MAP:
        s = rx.sub(rep, s)
    return [_TOKEN_MAP.get(t, t) for t in re.findall(r"[a-z0-9]+", s) if t != "the"]


def _raw_tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", norm_ground(s).replace("&", " and "))


def _tok_eq(a: str, b: str) -> bool:
    """One word of a value against one word of the text: equal, or (5+ letters, no digits) one OCR-level edit
    (two for 9+ letters) with the same first letter, or equal after folding OCR look-alikes (rn/m, 1/l, 0/o)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if any(ch.isdigit() for ch in a) or any(ch.isdigit() for ch in b):
        # a number is exact; a word with a digit read for a letter ('g00dlatte', 'ist' for 1st) folds equal
        mixed = not (a.isdigit() or b.isdigit())
        return mixed and min(la, lb) >= 3 and _ocr_fold(a) == _ocr_fold(b)
    if min(la, lb) < 4:
        return False
    if _ocr_fold(a) == _ocr_fold(b):
        return True
    if min(la, lb) < 5 or (a[0] != b[0] and min(la, lb) < 8):
        return False
    cap = 1 if max(la, lb) <= 8 else 2
    return abs(la - lb) <= cap and _edit_distance(a, b, cap) <= cap


class TextFacts:
    """Per-row index of the training text for G1 (text only: never `known`, the filename or the reviewer window)."""

    def __init__(self, text: str):
        self.text = text or ""
        self.norm = norm_ground(self.text)
        self.toks = _canon_tokens(self.text)
        self.padded = " " + " ".join(self.toks) + " "
        self.collapsed = "".join(self.toks)
        self.pos: dict[str, list[int]] = defaultdict(list)
        for i, t in enumerate(self.toks):
            self.pos[t].append(i)
            if re.search(r"[a-z][1258][a-z]", t):  # font ligatures read as digits: 'appropria8ons', 'commi5ee'
                self.pos[re.sub(r"(?<=[a-z])[1258](?=[a-z])", lambda m: "tt" if m.group(0) == "5" else "ti", t)].append(i)
        raw = [t for t in _raw_tokens(self.text) if t not in _ACR_STOP]
        self.acr_words = raw
        self.raw_set = set(_raw_tokens(self.text))
        self.upper_words = set(re.findall(r"\b[A-Z]{2,6}\b", self.text))
        self.caps = {norm_ground(m.group(0)) for m in re.finditer(r"(?<![\w])[A-Z][\w'\u2019]*", self.text)}
        self._fuzzy: dict[str, list[int]] = {}
        self._dates: tuple[set[str], set[str], set[str], set[str]] | None = None

    # ---- generic phrase matching
    def positions(self, tok: str) -> list[int]:
        if tok in self.pos:
            return self.pos[tok]
        if tok not in self._fuzzy:
            self._fuzzy[tok] = sorted(p for w, ps in self.pos.items() if _tok_eq(tok, w) for p in ps)
        return self._fuzzy[tok]

    def phrase(self, V: list[str], allow_long_del: bool = True) -> bool:
        """V (canonical tokens) occurs as a phrase: exactly, with OCR-split words rejoined, or aligned word by
        word with OCR-level word errors, a dropped connective (of/and/us ...) or a stray inserted word."""
        V = [t for t in V if t]
        if not V:
            return True
        if " " + " ".join(V) + " " in self.padded:
            return True
        flat = "".join(V)
        if len(flat) >= 10 and flat in self.collapsed:
            return True
        k = len(V)
        budget = 0.5 if k <= 3 else (1.0 if k <= 7 else 1.0 + 0.1 * k)
        strong = [i for i, t in enumerate(V) if t not in _WEAK]
        if not strong:
            return False
        anchors = sorted(((len(self.positions(V[i])), i) for i in strong if self.positions(V[i])))
        if not anchors:
            return False
        if len(anchors) < len(strong) and (k < 8 or len(strong) - len(anchors) > max(1, k // 8)):
            return False  # a content word of a short value is missing outright
        _, ai = anchors[0]
        pad = int(budget * 2) + 2
        for p in self.positions(V[ai])[:200]:
            W = self.toks[max(0, p - ai - pad) : p + (k - ai) + pad]
            if _align_cost(V, W, allow_del=allow_long_del and k >= 8) <= budget:
                return True
        return False

    def acronym(self, value: str) -> bool:
        """`value` is written in the text as its initials ('GAO' for Government Accountability Office, 'DOD' for
        Department of Defense, 'USTR' for Office of the United States Trade Representative, 'VA' for Department of
        Veterans Affairs; a two-letter form only where the text writes it in capitals), or the value is an acronym
        whose expansion the text writes."""
        allw = _raw_tokens(value)
        cands: set[str] = set()
        for drop_of in (True, False):
            words = [t for t in allw if t not in _ACR_STOP or (not drop_of and t == "of")]
            variants = [words]
            if words[:2] == ["u", "s"] or words[:1] == ["us"]:
                variants.append(words[2:] if words[:2] == ["u", "s"] else words[1:])
            if words[:2] == ["united", "states"]:
                variants.append(words[2:])
            for v in list(variants):
                for lead in (["office", "of"], ["department", "of"], ["office"], ["department"]):
                    if v[: len(lead)] == lead:
                        variants.append(v[len(lead) :])
            for v in variants:
                if len(v) >= 2:
                    cands.add("".join(t[0] for t in v))
        for c in cands:
            if len(c) >= 3 and c in self.raw_set:
                return True
            if len(c) == 2 and c.upper() in self.upper_words:
                return True
        letters = re.sub(r"[^a-z]", "", value.lower())
        if len(allw) == 1 and 3 <= len(letters) <= 8 and re.fullmatch(r"[A-Za-z.&\-]+", value.strip()) and sum(ch.isupper() for ch in value) >= 2:
            L, W = len(letters), self.acr_words
            for i in range(len(W) - L + 1):
                if W[i][0] == letters[0] and "".join(w[0] for w in W[i : i + L]) == letters:
                    return True
        return False

    def any_order(self, V: list[str]) -> bool:
        """All content words of a 3+ word value within a few words of each other, in any order ('Eighth Circuit
        Court of Appeals' for U.S. Court of Appeals for the Eighth Circuit; 'Governor of Guam Office of the
        Governor')."""
        S = [t for t in V if t not in _WEAK]
        if len(S) < 3:
            return False
        span = len(V) + 6
        rare = min(S, key=lambda t: len(self.positions(t)))
        for p0 in self.positions(rare)[:200]:
            lo, hi = max(0, p0 - span), p0 + span
            if all(any(lo <= q <= hi for q in self.positions(t)) for t in S):
                return True
        return False

    def stated(self, value: str, *, segments: bool = True, acronyms: bool = False) -> bool:
        V = _canon_tokens(value)
        if not V:
            return True
        if self.phrase(V):
            return True
        if V[:1] == ["us"] and len(V) >= 2 and self.phrase(V[1:]):
            return True  # 'U.S. Department of X' written 'Department of X'
        W = V[1:] if V[:1] == ["us"] else V
        if len(W) >= 3 and W[:2] == ["department", "of"] and (
            self.phrase(W[2:] + ["department"]) or self.phrase(["secretary", "of"] + W[2:])
        ):
            return True  # 'Department of Justice' written 'the Justice Department'; 'Secretary of Defense' names it
        if len(V) >= 4 and V[-2:] in (["of", "usa"], ["of", "us"]) and self.phrase(V[:-2]):
            return True  # 'Transport Workers Union of America' written 'Transport Workers Union'
        if acronyms and self.any_order(V):
            return True
        if acronyms and self.acronym(value):
            return True
        core = re.sub(r"\s*\([^)]*\)\s*", " ", value).strip()
        if core != value.strip() and core:
            inner = re.findall(r"\(([^)]*)\)", value)
            if self.stated(core, segments=segments, acronyms=acronyms) or (
                acronyms and inner and all(self.stated(x, segments=False, acronyms=False) for x in inner)
            ):
                return True
        if segments:
            segs = [x for x in re.split(r"\s*[,;|/]\s*|\s+[-–—]+\s+|\s*:\s+", value) if x.strip()]
            segs = [x for x in segs if any(t not in _IGNORABLE_SEG for t in _canon_tokens(x))]
            if len(segs) >= 2:
                return all(
                    committee_stated(self, x)[0] if _COMMITTEE_LIKE.search(x.strip()) else self.stated(x, segments=False, acronyms=acronyms)
                    for x in segs
                )
        return False

    # ---- dates
    def dates(self) -> tuple[set[str], set[str], set[str], set[str]]:
        """(full ISO dates, YYYY-MM months, years, MM-DD month-days without a year) the text writes."""
        if self._dates is None:
            self._dates = _text_dates(self.norm)
        return self._dates


def _align_cost(V: list[str], W: list[str], allow_del: bool) -> float:
    """Cheapest alignment of all of V inside W (free start / end in W). Costs: word match 0 (OCR-tolerant, or two
    text words that join into the value word), connective dropped 0.5, inserted text word 0.5, a content word
    dropped 1 (long values only), a number dropped never."""
    INF = 99.0
    n = len(W)
    prev = [0.0] * (n + 1)
    for v in V:
        dcost = 0.5 if v in _WEAK else (1.0 if allow_del and not any(ch.isdigit() for ch in v) else INF)
        cur = [INF] * (n + 1)
        cur[0] = prev[0] + dcost
        for j in range(1, n + 1):
            best = prev[j] + dcost
            if _tok_eq(v, W[j - 1]):
                best = min(best, prev[j - 1])
            if j >= 2 and len(v) >= 5 and v == W[j - 2] + W[j - 1]:
                best = min(best, prev[j - 2])
            best = min(best, cur[j - 1] + 0.5)
            cur[j] = best
        prev = cur
    return min(prev[1:]) if n else prev[0]


_MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                "november", "december"]
_MON = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
        "nov": 11, "dec": 12}
_MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DAY = r"([0-3]?\d)(?:st|nd|rd|th|d)?"
_YEAR = r"((?:1[89]|20)\d\d)"


def _iso(y: int, m: int, d: int) -> str | None:
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return None


def _text_dates(t: str) -> tuple[set[str], set[str], set[str], set[str]]:
    full: set[str] = set()
    months: set[str] = set()
    md: set[str] = set()
    t = re.sub(r"(?<=\d)o(?=\d)|(?<=\d)o\b(?=,?\s*\d)", "0", t)  # OCR: '2o23'
    for m in re.finditer(_MON_RE + r"\.?\s*,?\s*" + _DAY + r"(?:\s*(?:-|and|through|to|&)\s*" + _DAY + r")?\s*,?\s*(?:" + _YEAR + r")?(?!\d)", t):
        mon = _MON[m.group(1)[:3]]
        days = [int(x) for x in (m.group(2), m.group(3)) if x]
        if m.group(3) and int(m.group(3)) > int(m.group(2)):
            days = list(range(int(m.group(2)), int(m.group(3)) + 1))
        if m.group(4):
            for d in days:
                iso = _iso(int(m.group(4)), mon, d)
                if iso:
                    full.add(iso)
        if not m.group(4):  # a month and day printed without a year ('Wednesday, May 15')
            for d in days:
                if 1 <= d <= 31:
                    md.add(f"{mon:02d}-{d:02d}")
    for m in re.finditer(r"(?<!\d)" + _DAY + r"(?:\s+day)?\s+(?:of\s+)?" + _MON_RE + r"\.?\s*,?\s*" + _YEAR, t):
        iso = _iso(int(m.group(3)), _MON[m.group(2)[:3]], int(m.group(1)))
        if iso:
            full.add(iso)
    # numeric dates with any separators and 2- or 4-digit years ('3.27.12', '06-27-17', '2/22|13', '4.26.23'),
    # and an OCR'd slash before a 4-digit year ('9/2212021')
    for m in re.finditer(r"(?<![\d.\-/|])(\d{1,2})\s?[./\-|]\s?(\d{1,2})\s?[./\-|]\s?((?:19|20)\d\d|\d\d)(?![\d])"
                         r"|(?<![\d.\-/|])(\d{1,2})/(\d{1,2})[1l|]((?:19|20)\d\d)(?!\d)", t):
        mo, d, y = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(4), m.group(5), m.group(6))
        yy = int(y)
        yy = yy + (2000 if yy < 50 else 1900) if yy < 100 else yy
        iso = _iso(yy, int(mo), int(d))
        if iso:
            full.add(iso)
    for m in re.finditer(r"(?<!\d)((?:19|20)\d\d)\s?[./]\s?(\d{1,2})\s?[./]\s?(\d{1,2})(?!\d)", t):
        iso = _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            full.add(iso)
    # OCR-damaged month names ('aprll 17, 2023', 'septernber'): one edit from a full month name of 5+ letters
    for m in re.finditer(r"\b([a-z1|]{5,10})\.?\s*,?\s*" + _DAY + r"\s*,?\s*" + _YEAR + r"(?!\d)", t):
        w = m.group(1).replace("1", "l").replace("|", "l")
        mon = next((i for i, nm in enumerate(_MONTH_NAMES, 1) if len(nm) >= 5 and nm[0] == w[0] and _edit_distance(w, nm, 1) <= 1), None)
        iso = _iso(int(m.group(3)), mon, int(m.group(2))) if mon else None
        if iso:
            full.add(iso)
    for m in re.finditer(r"(?<!\d)((?:19|20)\d\d)-(\d\d)-(\d\d)(?!\d)", t):
        iso = _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            full.add(iso)
    for m in re.finditer(_MON_RE + r"\.?\s*,?\s*" + _YEAR + r"(?!\d)", t):
        months.add(f"{m.group(2)}-{_MON[m.group(1)[:3]]:02d}")
    years = set(re.findall(r"(?<!\d)((?:1[89]|20)\d\d)(?!\d)", t))
    months |= {d[:7] for d in full}
    years |= {d[:4] for d in full}
    return full, months, years, md


def _congress_of_date(iso: str) -> int:
    y, m, d = int(iso[:4]), int(iso[5:7]), int(iso[8:10])
    if y % 2 == 1 and m == 1 and d < 3:
        y -= 1
    return (y - 1789) // 2 + 1


_ORD_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15,
    "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20,
}
_TENS = {"twenty": 20, "thirty": 30, "fortieth": 40, "forty": 40, "fiftieth": 50, "fifty": 50, "sixtieth": 60,
         "sixty": 60, "seventieth": 70, "seventy": 70, "eightieth": 80, "eighty": 80, "ninetieth": 90, "ninety": 90,
         "thirtieth": 30, "twentieth": 20}


def _ordinal_words(s: str) -> int | None:
    s = s.replace("-", " ")
    w = s.split()
    n = 0
    if w[:2] == ["one", "hundred"]:
        n, w = 100, w[2:]
        if w[:1] == ["and"]:
            w = w[1:]
    if not w:
        return n or None
    if len(w) == 1:
        v = _ORD_WORDS.get(w[0]) or _TENS.get(w[0])
        return n + v if v else None
    if len(w) == 2 and w[0] in _TENS and w[1] in _ORD_WORDS and _ORD_WORDS[w[1]] < 10:
        return n + _TENS[w[0]] + _ORD_WORDS[w[1]]
    return None


# Congress (decision A): an explicit statement of this document's Congress or a printed designator that carries
# it, read through scan damage. Never from a date, a cited law ('P.L. 105-33'), a file path or GPO package id, or a
# passing mention ('introduced in the 112th Congress'). Designators count where a document prints its own: the
# first 2,500 and last 1,500 characters (cover, title page, GPO back matter), not citations in the body.
_CONGRESS_ORD_RES = [
    re.compile(r"(?<![\d.$,])(\d{2,3})\s*[\"'`*]{0,3}\s*(?:st|nd|rd|th|d|h|tb|lh|t)?\s*[\"'`*]{0,3}\s*[-\s]{0,3}(?:united states\s+)?congress\b"),
    re.compile(r"(?<![\d.$,])(\d{1,2})\s*[\"'`*]{0,3}\s*(?:st|nd|rd|th|d)\s*[\"'`*]{0,3}\s*[-\s]{0,3}(?:united states\s+)?congress\b"),
    re.compile(r"congress\s*,?\s*(\d{1,3})(?:st|nd|rd|th|d)\b"),
]
_CONGRESS_DESIGNATOR_RES = [
    re.compile(r"\[\s*(?:house|senate|joint)\s+(?:hearing|report|document|prints?)\s*,?\s*(\d{1,3})\s+congress"),
    re.compile(r"\[\s*(?:house|senate|joint)\s+(?:hearing|report|document|prints?)\s+(\d{2,3})\s*-\s*\d+"),
    re.compile(r"(?:serial|ser\.)\s*(?:no\.?|number)?\s*(\d{2,3})\s*-"),
    re.compile(r"\b(?:house|senate)\s+(?:rpt|rept|hrg)\.?\s*(?:no\.?\s*)?(\d{2,3})\s*-\s*\d+"),
    re.compile(r"\bs\.\s?hr[g9]\.?\s*(\d{2,3})\s*-\s*\d+"),
    re.compile(r"\b(?:h|s)\.?\s*(?:rept|rpt|hrg|doc|prt|con\.?\s*rept)\.?\s*(?:no\.?\s*)?(\d{2,3})\s*-\s*\d+"),
    re.compile(r"\b(?:house|senate|exec(?:utive)?\.?|conference)\s+(?:report|rept\.?|hearing|document|doc\.)\s*(?:no\.?\s*)?(\d{2,3})\s*-\s*\d+"),
    re.compile(r"\{\s*(?:report|rept\.?)\s*(\d{2,3})\s*-\s*\d+"),
    re.compile(r"\breport\s+(?:no\.\s*)?(\d{2,3})\s*-\s*\d+"),
    re.compile(r"\btreaty\s+doc(?:ument)?\.?\s*(?:no\.?\s*)?(\d{2,3})\s*-\s*\d+"),
    re.compile(r"\b(?:rules\s+)?committee\s+print\s+(?:no\.?\s*)?(\d{2,3})\s*-\s*\d+"),
]
_CONGRESS_PASSING_RE = re.compile(
    r"(?:introduced|reintroduced|passed|enacted|considered|approved|adopted|signed|filed|defeated|failed|reported|"
    r"proposed|offered)\b[^.;]{0,40}?\b(?:in|during|by|of)\s+the\s*$")
_ORD_CONGRESS_RE = re.compile(
    r"((?:one[\s-]+hundred(?:[\s-]+and)?[\s-]+)?(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[\s-]+)?"
    r"(?:" + "|".join(sorted(set(_ORD_WORDS) | {w for w in _TENS if w.endswith("ieth")}, key=len, reverse=True)) + r"))\s+congress")


def stated_congresses(f: TextFacts) -> set[int]:
    t = f.norm
    t2 = re.sub(r"(?<=\d)[il|](?=\d|th|st|nd|rd)|(?<=\b)[il|](?=\d)", "1", t)  # OCR 'll8th' / '1l8th'
    t2 = re.sub(r"(?<=\d)o(?=\d)", "0", t2)
    out: set[int] = set()

    def add(n: int, s: str, start: int) -> None:
        if 1 <= n <= 130 and not _CONGRESS_PASSING_RE.search(s[max(0, start - 70) : start]):
            out.add(n)

    for s in (t, t2):
        for rx in _CONGRESS_ORD_RES:
            for m in rx.finditer(s):
                add(int(m.group(1)), s, m.start())
        page = s[:2500] + " \n " + s[-1500:]
        for rx in _CONGRESS_DESIGNATOR_RES:
            for m in rx.finditer(page):
                add(int(m.group(1)), page, m.start())
    for m in re.finditer(r"\b[a-z]{2,4}[\s-]+hundre\w?(?:[\s-]+and)?[\s-]+([a-z]+)(?:[\s-]+([a-z]+))?[\s-]+congress\b", t):
        words = [w for w in m.groups() if w and w != "congress"]
        fixed = [next((o for o in list(_ORD_WORDS) + list(_TENS) if _edit_distance(w, o, 2) <= 2 and w[0] == o[0]), w) for w in words]
        for i in range(len(fixed)):
            n = _ordinal_words("one hundred " + " ".join(fixed[i:]))
            if n:
                add(n, t, m.start())
                break
    for m in _ORD_CONGRESS_RE.finditer(t):
        words = m.group(1).split()
        for i in range(len(words)):
            n = _ordinal_words(" ".join(words[i:]))
            if n:
                add(n, t, m.start())
                break
    return out


def derived_congresses(f: TextFacts) -> set[int]:
    full, months, years, _ = f.dates()
    out = {_congress_of_date(d) for d in full}
    out |= {(int(y) - 1789) // 2 + 1 for y in years}
    return out


# Chamber (owner decision A, 2026-11-18): "stated" means evident from the document's own words to a careful reader.
# Evident: 'House of Representatives' / 'U.S. House' / 'United States Senate', a standalone SENATE or HOUSE OF
# REPRESENTATIVES header, a House or Senate office building in a location ('106 Dirksen Senate Office Building',
# '2167 Rayburn'), 'Rep.' / 'Representative' / 'Congressman' / 'Senator' of the presiding, speaking or signing
# member, a roll sheet with a 'Representative' or 'Senator' column, a committee that exists in one chamber only,
# the committee's own site (veterans.senate.gov), a House / Senate publication designator. Not evident: 'the
# White House', a state's House or Senate, a bill merely cited; in a biography only page-level cues count (a
# witness's past employer says nothing about this document).
_STATE_NAME_RE = "|".join(sorted(_STATE_CODES, key=len, reverse=True))
_LOOKALIKE_RE = re.compile(
    r"\bwhite\s+house\b|\b(?:" + _STATE_NAME_RE + r"|(?<!of )state|tribal)\s+(?:house|senate)\b(?:\s+of\s+representatives)?"
    r"|\bhouse\s+of\s+delegates\b|\b(?:" + _STATE_NAME_RE + r")\s+state\s+(?:house|senate)\b")
_HOUSE_CUE = re.compile(
    r"house of representatives|\bu\.?\s?s\.? house\b|united states house|\bhouse (?:select |permanent select )?(?:sub)?committee"
    r"|\bhouse hearing|\[\s*house\b|\bh\.\s?(?:rept|rpt|doc|prt)\b|\bhouse (?:report|document|calendar)"
    r"|\bhouse (?:\w+ ){1,5}(?:sub\s?)?comm?m?itt?ee?s?\b|\bcongressional record\W+house\b"
    r"|\bbefore\s+(?:the\s+)?(?:united states\s+|u\.?\s?s\.?\s+)?house\b|\bfavorably\s+to\s+the\s+house\b"
    r"|\bhouse\s+rules?\b|\brules?\s+[ivxl]+\s+of\s+the\s+house\b|\brules\s+of\s+the\s+house\b")
_SENATE_CUE = re.compile(
    r"united states senate|\bu\.?\s?s\.? senate\b|\bsenate (?:select |special )?(?:sub)?committee|\bsenate hearing|\[\s*senate\b"
    r"|\bs\.\s?(?:hrg|rept|rpt|doc|prt)\b|\bsenate (?:report|document|calendar)|\bsenate (?:\w+ ){1,5}(?:sub\s?)?comm?m?itt?ee?s?\b"
    r"|\bbefore\s+(?:the\s+)?(?:united states\s+|u\.?\s?s\.?\s+)?senate\b|\bfavorably\s+to\s+the\s+senate\b"
    r"|\bsenate\s+rules?\b|\brules?\s+[ivxl]+\s+of\s+the\s+(?:standing\s+rules\s+of\s+the\s+)?senate\b|\bstanding\s+rules\s+of\s+the\s+senate\b"
    r"|\bcommittee on (?:\w+ ){1,8}(?:\w+,? )?(?:u\.?\s?s\.? |united states )?senate\b|\bcongressional record\W+senate\b"
    r"|\bin the senate of the united states\b")
_HOUSE_PAGE_CUE = re.compile(  # page-level: buildings, the chamber's web domain
    r"\b(?:rayburn|longworth|cannon)\s+(?:house\s+office\s+)?(?:building|bldg|hob)\b|\b\d{3,4}-?[a-z]?\s+(?:rayburn|longworth|cannon)\b"
    r"|\b[rlc]\.?\s?h\.?\s?o\.?\s?b\.?(?![a-z])|\bhouse office building\b|\b[\w-]+\.house\.gov\b")
_SENATE_PAGE_CUE = re.compile(
    r"\b(?:dirksen|hart|russell)\s+(?:senate\s+)?(?:of+i?ce\s+)?(?:building|bldg|sob)\b|\b\d{2,4}[a-z]?\s+(?:dirksen|hart|russell)\b"
    r"|\bsenate office building\b|\b[\w-]+\.senate\.gov\b")
_ROLL_COLUMN_RE = re.compile(
    r"\b(representatives?|senators?)\s+(?:present|absent|ayes?|yeas?|nays?|noes|not voting)\b"
    r"|\b(?:present|absent|ayes?|yeas?|nays?|noes)\s+(representatives?|senators?)\b")
_MEMBER_TITLE = r"(senator|sen\.|representative|rep\.|congress(?:man|woman)|u\.?\s?s\.? (?:senator|representative))"
_PRESIDING_RE = re.compile(
    r"presiding:?\s*(?:chair(?:man|woman)?\s+)?(?:the\s+honorable\s+)?" + _MEMBER_TITLE
    + r"|" + _MEMBER_TITLE + r"\s+[a-z.'\-]+(?:\s+[a-z.'\-]+){0,2},?\s+presiding")
_HEADING_MEMBER_RE = re.compile(
    r"^\W*(?:\d+\s+)?(?:(?:opening\s+)?(?:statement|remarks|testimony)\s+(?:of|by|from)\s+)?(?:the\s+honorable\s+)?"
    + _MEMBER_TITLE + r"\s+[a-z]|(?:opening\s+)?(?:statement|remarks|testimony)\s+(?:of|by|from)\s+(?:the\s+honorable\s+)?"
    + _MEMBER_TITLE + r"\s+[a-z]")
_JOINT_CUE = re.compile(r"\bjoint (?:economic |select )?committee\b|\bjoint committee on\b")
_COMMISSION_CUE = re.compile(r"\bcommission\b")

# Committees whose name exists in one chamber only, built from the committee names the reviewers wrote in the
# gold itself (every core seen with a single chamber prefix across 3,517 names) plus the rubric's list; Ethics is
# both (Senate Select Committee on Ethics), so it is left out. Cores are canonical tokens ('the' dropped).
ONE_CHAMBER_CORES: dict[str, str] = {
    **{c: "house" for c in (
        "energy and commerce", "ways and means", "natural resources", "transportation and infrastructure",
        "science space and technology", "foreign affairs", "oversight and government reform", "financial services",
        "agriculture", "homeland security", "education and workforce", "small business", "oversight and reform",
        "rules", "house administration", "oversight and accountability", "education and labor",
        "science and technology", "climate crisis", "science", "modernization of congress", "resources",
        "government reform", "economic disparity and fairness in growth",
        "strategic competition between us and chinese communist party", "benghazi",
        "energy independence and global warming", "investigate january 6th attack on us capitol")},
    **{c: "senate" for c in (
        "commerce science and transportation", "finance", "foreign relations", "environment and public works",
        "energy and natural resources", "homeland security and governmental affairs", "indian affairs",
        "health education labor and pensions", "banking housing and urban affairs",
        "agriculture nutrition and forestry", "aging", "small business and entrepreneurship",
        "rules and administration", "governmental affairs", "year 2000 technology problem", "impeachment trial")},
}
_BOTH_CHAMBER_CORES = ("judiciary", "appropriations", "veterans affairs", "armed services", "intelligence", "budget", "ethics")
_ALL_CORES = [c.split() for c in list(ONE_CHAMBER_CORES) + list(_BOTH_CHAMBER_CORES)]


_PASSING_VERBS = ("passed", "voted", "approved", "adopted", "unanimously", "confirmed", "rejected")


def _text_chambers(f: "TextFacts") -> set[str]:
    """Chambers evident from the text alone (no label): see the block comment above."""
    t = _LOOKALIKE_RE.sub(lambda m: m.group(0).replace("house", "hxuse").replace("senate", "sxnate"), f.norm)
    # a chamber mentioned in passing, not this document's proceeding: 'the House of Representatives passed H.R. 3082'
    t = re.sub(r"\b(?:the\s+)?(?:house|senate)(?:\s+of\s+representatives?)?\s+(?:" + "|".join(_PASSING_VERBS) + r")\b"
               r"|\b(?:passed|approved|confirmed|adopted)\s+(?:by\s+)?(?:the\s+)?(?:full\s+)?(?:house|senate)\b",
               lambda m: m.group(0).replace("house", "hxuse").replace("senate", "sxnate"), t)
    out: set[str] = set()
    page = t[:2500] + "\n" + t[-1500:]
    if _HOUSE_PAGE_CUE.search(page):
        out.add("house")
    if _SENATE_PAGE_CUE.search(page):
        out.add("senate")
    for m in re.finditer(r"(?<![A-Za-z])SENATE(?![A-Za-z])", f.text):  # a standalone SENATE header
        before = re.sub(r"\s+", " ", f.text[max(0, m.start() - 25) : m.start()]).upper()
        if not re.search(r"(?:STATE|WHITE|" + _STATE_NAME_RE.upper() + r")\W*$", before):
            out.add("senate")
            break
    for m in _ROLL_COLUMN_RE.finditer(t):  # a roll sheet's 'Representative' / 'Senator' column
        out.add("house" if (m.group(1) or m.group(2)).startswith("rep") else "senate")
    for m in list(_PRESIDING_RE.finditer(t)) + list(_HEADING_MEMBER_RE.finditer(t[:300])):
        title = next(g for g in m.groups() if g)
        out.add("senate" if "sen" in title else "house")
    f.__dict__["_page_only"] = set(out)
    # 'Congressman Ben Cline', 'Questions from Senator Booker', 'Ilhan Omar (MN-05)' (a House district)
    hd = t[:600]  # the member heading this proceeding, asking or inviting; never one quoted in passing ('as Senator Tester said')
    if re.search(r"\bcongress(?:man|woman)\b", hd) or re.search(r"\(\s*[a-z]{2}\s*-\s*\d{1,2}\s*\)|\b[rd]-[a-z]{2}-\d{1,2}\b|\(\s*house\s*\)", t) \
            or re.search(r"questions?\s+(?:for\s+the\s+record\s+)?from\s+(?:congress(?:man|woman)|rep\.|representative)", t):
        out.add("house")
    if re.search(r"\bsenator\b", hd) or re.search(r"questions?\s+(?:for\s+the\s+record\s+)?from\s+senator|senators?\s+who\s+are\s+members\s+of\s+this\s+committee"
                                                  r"|\(\s*senate\s*\)|senator\s+[a-z.\s]{2,40}(?:for|thank)[^.]{0,40}(?:invitation|inviting|invite)", t):
        out.add("senate")
    codes = set(_STATE_CODES.values()) | {"state"}
    tp = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t))  # the same cues across punctuation ('house judiciary, immigration')
    if _HOUSE_CUE.search(tp):
        out.add("house")
    if _SENATE_CUE.search(tp):
        out.add("senate")
    if _HOUSE_CUE.search(t) or any(p > 1 and f.toks[p - 1] == "of" and f.toks[p - 3 if p >= 3 else 0] not in codes
                                   and (f.toks[p + 1] if p + 1 < len(f.toks) else "") not in _PASSING_VERBS
                                   for p in f.positions("representatives")):
        out.add("house")  # OCR-tolerant 'House of Representatives' ('Zouse of Representatiues'); not a state's, not in passing
    if _SENATE_CUE.search(t) or any(p > 0 and f.toks[p - 1] == "us" for p in f.pos.get("senate", [])):
        out.add("senate")
    for core, ch in ONE_CHAMBER_CORES.items():
        if committee_one_chamber_mention(f, core.split()):
            out.add(ch)
    return out


# Committee amendments (rubric, owner 2026-11-18): "AMENDMENT TO H.R. ... OFFERED BY MR. X OF STATE" is the House
# committee form (read through scan damage: 'OrFRRD Br Ms.', 'OFFERED вY', a blank 'Ml. llllll', a Rules Committee
# motion to make an amendment in order); the Senate form is "IN THE SENATE OF THE UNITED STATES", "AMENDMENT NO.",
# "Calendar No." (not a House report's 'Union Calendar No.'). Read only on amendment labels.
_AMDT_HOUSE_RE = re.compile(r"\bamendments?\b[\s\S]{0,200}?\bo[fr]{1,2}e?r?[er]?d\s+[bв][yr]\b|\bmake\s+in\s+order\s+(?:amendment|amdt)\b", re.I)
_AMDT_SENATE_RE = re.compile(r"in\s+the\s+senate\s+of\s+the\s+united\s+states|\bamendment\s+no\.\s*\d|(?<!union )(?<!house )\bcalendar\s+no\.\s*\d", re.I)


def is_amendment(lab: dict[str, Any]) -> bool:
    return "committee_amendment" in [lab.get("primary_kind")] + list(lab.get("secondary_kinds") or [])


def amendment_chambers(f: "TextFacts") -> set[str]:
    def make() -> set[str]:
        out = {"senate"} if _AMDT_SENATE_RE.search(f.text[:3000]) else set()
        if _AMDT_HOUSE_RE.search(f.text[:600]):
            out.add("house")
        return out
    return _cached(f, "_amendment_chambers", make)


def chamber_evidence(f: "TextFacts", lab: dict[str, Any]) -> set[str]:
    """Chambers evident for this document: the text cues, plus the title the text gives the presiding, speaking or
    signing member the label names ('Senator Booker', 'Rep. Allen'). In a biography only page-level cues count."""
    txt = _cached(f, "_text_chambers", lambda: _text_chambers(f))
    if lab.get("primary_kind") == "witness_biography":
        out = set(f.__dict__.get("_page_only", set()))
    else:
        out = set(txt)
        for p in lab.get("personas") or []:
            if p.get("entity_type") != "member" or p.get("role") not in ("author_or_speaker", "chair", "ranking_member", "presiding", "sender", "signatory"):
                continue
            sur = _tok_norm(str(p.get("name") or "").split()[-1]) if p.get("name") else ""
            if len(sur) >= 3:
                for m in re.finditer(_MEMBER_TITLE + r"\s+(?:[a-z.]+\s+){0,2}" + re.escape(sur) + r"\b", f.norm):
                    out.add("senate" if "sen" in m.group(1) else "house")
    if is_amendment(lab):
        out |= amendment_chambers(f)
    if {"house", "senate"} <= out or _JOINT_CUE.search(f.norm):
        out.add("joint")
    if _COMMISSION_CUE.search(f.norm):
        out.add("commission")
    return out


def committee_one_chamber_mention(f: "TextFacts", core: list[str]) -> bool:
    """The text names this one-chamber committee ('Committee on Ways and Means', 'Ways and Means Committee'),
    not as part of a longer name ('Committee on Homeland Security and Governmental Affairs')."""
    return bool(_core_mentions(f, core, "committee"))


def _core_mentions(f: "TextFacts", core: list[str], word: str) -> list[int]:
    hits = []
    for V, tail in (([word, "on"] + core, True), (core + [word], False)):
        for h in _phrase_positions(f, V, strict=True):
            if tail:
                nxt = f.toks[h + len(V) : h + len(V) + 6]
                if any(len(c2) > len(core) and c2[: len(core)] == core and nxt[: len(c2) - len(core)] == c2[len(core) :] for c2 in _ALL_CORES):
                    continue
            else:
                prv = f.toks[max(0, h - 6) : h]
                if any(len(c2) > len(core) and c2[-len(core) :] == core and prv[len(prv) - (len(c2) - len(core)) :] == c2[: len(c2) - len(core)] for c2 in _ALL_CORES) \
                        or (prv[-1:] == ["and"]):
                    continue
            hits.append(h)
    return hits


def stated_chambers(f: TextFacts, lab: dict[str, Any] | None = None) -> set[str]:
    return chamber_evidence(f, lab or {})


_CMTE_PREFIX_RE = re.compile(r"^(?:(?:the\s+)?(?:u\.?s\.?\s+|united states\s+)?(house|senate|joint)(?:\s+of representatives)?\s+)?")


def committee_core(name: str) -> tuple[str | None, list[str], str]:
    """(chamber word in the label name, core tokens, form) of a committee / subcommittee label:
    'House Committee on Ways and Means' -> ('house', [ways, and, means], 'committee')."""
    s = norm_ground(name)
    m = _CMTE_PREFIX_RE.match(s)
    ch = m.group(1) if m and m.group(1) else None
    rest = s[m.end() :] if m else s
    form = "subcommittee" if re.search(r"\bsubcommittee\b", rest) else "committee"
    m2 = re.match(r"(?:permanent\s+)?(?:select\s+|special\s+)?(?:investigative\s+)?(?:sub)?committee\s+(?:on|to|for)\s+(.*)$", rest) or (
        re.search(r"\bsubcommittee\s+(?:on|for)\s+(.*)$", rest) if form == "subcommittee" else None)
    if m2:
        return ch, _canon_tokens(m2.group(1)), form
    m3 = re.match(r"(.*?)\s+(?:select\s+)?(?:sub)?committee$", rest)
    if m3 and ch != "joint":
        return ch, _canon_tokens(m3.group(1)), form
    return ch, _canon_tokens(rest if ch != "joint" else s), "name"


def committee_mentions(f: TextFacts, name: str) -> list[int]:
    """Token positions where the text names this committee / subcommittee in a usual form: the full name,
    'Committee on <core>', '<core> Committee' (Subcommittee likewise), OCR-tolerant."""
    ch, core, form = committee_core(name)
    word = "subcommittee" if form == "subcommittee" else "committee"
    if not core:
        return []
    hits: list[int] = []
    forms = [[word, "on"] + core, core + [word], [word, "to"] + core, [word, "for"] + core]
    if form == "subcommittee":
        # usual short forms of an appropriations subcommittee ('Legislative Branch Appropriations Subcommittee',
        # 'Transportation, Housing and Urban Development Subcommittee', 'Financial Services Subcommittee')
        short = core[:-3] if core[-3:] == ["and", "related", "agencies"] else core
        heads = [short[:i] for i in range(2, len(short) + 1) if short[i - 1] not in _WEAK and sum(t not in _WEAK for t in short[:i]) >= 2]
        for h in [short] + heads:
            forms += [h + ["appropriations", word], h + [word], [word, "on"] + h]
    if form == "committee" and ch in ("house", "senate"):
        forms += [core + ["subcommittee", "on"], [ch] + core]
    if form == "committee":
        forms += [core + ["full", "committee"]] + ([["appropriations", "subcommittee"]] if core == ["appropriations"] else [])
        if core == ["security", "and", "cooperation", "in", "europe"]:
            forms += [["helsinki", "commission"]]
    if form == "subcommittee":
        forms += [core + ["subcommittees"], ["subcommittees", "on"] + core]
    if form == "name":
        forms = [core]
    for V in forms:
        hits += _phrase_positions(f, V)
    # a form field or heading that names it bare ('Committee: Energy and Commerce', 'Subcommittee: Oversight and
    # Investigations', 'Investigations & Oversight and Energy & Environment Subcommittees'): two or more content words
    if form in ("committee", "subcommittee") and sum(t not in _WEAK for t in core) >= 2:
        for h in _phrase_positions(f, core, strict=True):
            before, after = f.toks[max(0, h - 6) : h], f.toks[h + len(core) : h + len(core) + 8]
            if (word in before and "and" not in f.toks[h - 1 : h]) or (form == "subcommittee" and "subcommittees" in after):
                hits.append(h)
    if word == "committee" and form != "name":
        for V in (["subcommittee", "on"] + core, core + ["subcommittee"]):
            bad = set(_phrase_positions(f, V, strict=True))
            hits = [h for h in hits if h not in bad and h - 1 not in bad]
    return sorted(set(hits))


def _phrase_positions(f: TextFacts, V: list[str], strict: bool = False) -> list[int]:
    """Start positions of V in the text tokens (exact; else word-by-word OCR-tolerant, and for phrases of 4+ words
    also a dropped connective or a stray word). `strict`: exact words only."""
    k = len(V)
    out: list[int] = []
    strong = [i for i, t in enumerate(V) if t not in _WEAK and t not in ("committee", "subcommittee", "on")]
    if not strong:
        strong = list(range(k))
    if strict:
        if not all(V[i] in f.pos for i in strong):
            return []
        anchors = sorted((len(f.pos[V[i]]), i) for i in strong)
    else:
        anchors = sorted(((len(f.positions(V[i])), i) for i in strong if f.positions(V[i])))
    if not anchors or len(anchors) < len(strong) and k < 8:
        return []
    _, ai = anchors[0]
    budget = 0.0 if k <= 3 else (1.0 if k <= 7 else 1.0 + 0.1 * k)
    for p in (f.pos.get(V[ai], []) if strict else f.positions(V[ai]))[:300]:
        s0 = max(0, p - ai)
        if f.toks[s0 : s0 + k] == V:
            out.append(s0)
            continue
        if strict:
            continue
        if budget == 0.0:
            if p - ai >= 0 and len(f.toks[s0 : s0 + k]) == k and all(_tok_eq(a, b) for a, b in zip(V, f.toks[s0 : s0 + k])):
                out.append(s0)
            continue
        W = f.toks[max(0, p - ai - 2) : p + (k - ai) + 2]
        if _align_cost(V, W, allow_del=k >= 8) <= budget:
            out.append(s0)
    return out


def committee_stated(f: TextFacts, name: str, lab: dict[str, Any] | None = None) -> tuple[bool, bool]:
    """(named in the text, chamber evident for it). The chamber is evident when 'House' / 'Senate' stands in the
    text's own naming of it or within 25 words of a mention, when the committee exists in one chamber only (and no
    other chamber word stands right before the mention), or when the document's chamber evidence is that chamber
    alone (decision A)."""
    ch, core, form = committee_core(name)
    hits = committee_mentions(f, name)
    if not hits:
        if f.stated(name, segments=False):
            return True, True
        return False, False
    if ch in (None, "joint"):
        return True, True
    other = "senate" if ch == "house" else "house"

    def other_chamber_mention(h: int) -> bool:  # 'Senate Committee on the Judiciary' when the label says House
        near = f.toks[max(0, h - 4) : h] + f.toks[h + len(core) + 1 : h + len(core) + 7]
        return other in near and ch not in near and not (ch == "house" and "representatives" in near)

    if form == "committee" and all(other_chamber_mention(h) for h in hits):
        return False, False  # the text names the other chamber's committee, not this one
    if (lab or {}).get("primary_kind") == "witness_biography":
        employ = {"staff", "served", "serving", "serves", "worked", "working", "counsel", "aide", "director", "employed",
                  "fellow", "clerk", "advisor", "adviser", "detailee", "investigator", "economist", "member"}
        if all(employ & set(f.toks[max(0, h - 10) : h]) for h in hits):
            return False, False  # named only as the person's past employer, not this document's committee
    for h in hits:
        win = f.toks[max(0, h - 25) : h + len(core) + 30]
        if ch in win or (ch == "house" and "representatives" in win):
            return True, True
    if form == "committee" and ONE_CHAMBER_CORES.get(" ".join(core)) == ch and not any(other in f.toks[max(0, h - 3) : h] for h in hits):
        return True, True
    ev = chamber_evidence(f, lab or {}) & {"house", "senate"}
    return True, ev == {ch}


def committee_chamber(f: TextFacts, name: str, lab: dict[str, Any]) -> str | None:
    """The chamber evident for a named committee (decision A), whatever prefix the label wrote: the label's own
    chamber when 'House' / 'Senate' stands near a mention; else the one chamber the committee exists in; else the
    single chamber word near its mentions; else the document's single evident chamber; else none. Depends only on
    the committee's core, the text and the label's people, so writing the result back changes nothing."""
    ch, core, form = committee_core(name)
    if form != "committee" or not core or ch == "joint" or " ".join(core) == "house administration":
        return ch
    hits = committee_mentions(f, name)
    W = set()
    for h in hits:
        win = f.toks[max(0, h - 25) : h + len(core) + 30]
        W |= {c for c in ("house", "senate") if c in win} | ({"house"} if "representatives" in win else set())
    if ch in W:
        return ch
    one = ONE_CHAMBER_CORES.get(" ".join(core))
    if one:
        return one
    if len(W) == 1:
        return next(iter(W))
    ev = chamber_evidence(f, lab) & {"house", "senate"}
    return next(iter(ev)) if len(ev) == 1 else None


def _committee_value(f: TextFacts, v: str, lab: dict[str, Any]) -> str | None:
    """A committee-like org value written with the chamber the text makes evident (or none)."""
    if not _COMMITTEE_LIKE.search(v) or not committee_stated(f, v, lab)[0]:
        return None
    ch, core, form = committee_core(v)
    if ch not in (None, "house", "senate") or form != "committee" or v.startswith("Committee on House Administration"):
        return None
    return with_chamber(v, committee_chamber(f, v, lab))


def with_chamber(name: str, ch: str | None) -> str:
    base = strip_chamber(name)
    return f"{ch.title()} {base}" if ch in ("house", "senate") else base


def strip_chamber(name: str) -> str:
    """'House Committee on X' -> 'Committee on X'; 'House Permanent Select Committee on X' -> 'Permanent Select
    Committee on X'."""
    return re.sub(r"^(?:U\.?S\.?\s+|United States\s+)?(?:House|Senate)(?:\s+of Representatives)?\s+", "", name).strip()


_EVENT_PREFIX_RE = re.compile(
    r"^(?:(?:full\s+committee|subcommittee|joint|legislative|oversight|field|nomination|budget)\s+)*"
    r"(?:hearing|hearings|markup|mark-up|business\s+meeting|roundtable|briefing|forum|meeting|executive\s+session)"
    r"(?:\s+(?:on|of|to\s+examine|entitled|titled|regarding))?\s*[:\-–—]?\s*", re.I)


def title_stated(f: TextFacts, value: str) -> bool:
    v = value.strip().strip("\"'“”")
    if f.stated(v, segments=False):
        return True
    core = _EVENT_PREFIX_RE.sub("", v).strip().strip("\"'“”")
    if core and core != v and len(_canon_tokens(core)) >= 2 and f.stated(core, segments=False):
        return True
    # a title written on two lines with a subtitle: both halves stated
    parts = [x for x in re.split(r"\s*:\s+|\s+[-–—]+\s+", core or v) if x.strip()]
    if len(parts) >= 2 and all(len(_canon_tokens(x)) >= 1 and f.stated(x, segments=False) for x in parts):
        return True
    V = _canon_tokens(core or v)
    return _in_order_nearby(f, V) or _chunk_cover(f, V) or _chunk_share(f, V) >= 0.5


def _chunk_share(f: TextFacts, V: list[str]) -> float:
    """Share of a title's content words that the text writes inside phrases of two or more of the title's words, in
    any order and place: a title pieced together from the document's heading and bill list keeps a high share; a
    hearing title the document never prints (on a biography) shares at most a few loose words."""
    k = len(V)
    S = [i for i, t in enumerate(V) if t not in _WEAK]
    if len(S) < 2:
        return 0.0
    covered: set[int] = set()
    i = 0
    while i < k:
        best = 0
        for j in range(k, i + 1, -1):
            C = V[i:j]
            if sum(t not in _WEAK for t in C) < 2:
                break
            if f.phrase(C, allow_long_del=False):
                best = j
                break
        if best:
            covered |= set(range(i, best))
            i = best
        else:
            i += 1
    return len([x for x in S if x in covered]) / len(S)


def _in_order_nearby(f: TextFacts, V: list[str]) -> bool:
    """A long title whose words the text writes in order but interleaved with table or form text (a form field
    wrapped around a date column): every content word but at most one found, in order, within twice the title's
    length."""
    S = [t for t in V if t not in _WEAK]
    if len(S) < 5:
        return False
    span = 2 * len(V) + 10
    for first in (0, 1):
        for p0 in f.positions(S[first])[:100]:
            p, missing = p0, first
            for t in S[first + 1 :]:
                nxt = next((q for q in f.positions(t) if p < q <= p0 + span), None)
                if nxt is None:
                    missing += 1
                    if missing > 1:
                        break
                    continue
                p = nxt
            if missing <= 1:
                return True
    return False


def _chunk_cover(f: TextFacts, V: list[str], max_chunks: int = 5) -> bool:
    """A heading the reviewer joined from several heading lines ('Testimony of X' + 'before the Committee on Y' +
    the hearing title): every content word lies in a chunk of the value that the text writes as a phrase, each
    chunk carrying two or more content words, at most `max_chunks` chunks."""
    k = len(V)
    i, chunks, single_used = 0, 0, False
    while i < k:
        if V[i] in _WEAK:
            i += 1
            continue
        best = 0
        for j in range(k, i, -1):
            C = V[i:j]
            if sum(t not in _WEAK for t in C) < 2:
                break
            if f.phrase(C, allow_long_del=False):
                best = j
                break
        if not best and not single_used and i == k - 1 and len(V[i]) >= 5 and f.positions(V[i]):
            best, single_used = i + 1, True  # a closing heading word on its own line ('... MEETING / AGENDA')
        if not best:
            return False
        chunks += 1
        i = best
    return 0 < chunks <= max_chunks


_OCR_DIGIT = {"0": "[0o]", "1": "[1li|!]", "2": "[2z]", "5": "[5s]", "8": "[8b]"}


def _ocr_num(n: int, pad: bool = True) -> str:
    d = str(n)
    body = "".join(_OCR_DIGIT.get(ch, ch) for ch in d)
    return ("[0o]?" if pad and len(d) == 1 else "") + body


def date_positions(f: TextFacts, iso: str) -> list[int]:
    """Where the text prints this full date, in any written format and through scan damage ('4:14.ll' for
    4/14/11, 'MARCH Z, 2017', 'Ju1y 4'): month name or abbreviation + day + year, day + month + year, and numeric
    month / day / 2- or 4-digit year with any separator."""
    y, mo, d = int(iso[:4]), int(iso[5:7]), int(iso[8:10])
    t = f.norm
    name = _MONTH_NAMES[mo - 1]
    mon = rf"(?:{name}|[a-z]{name[1:]}|{name[:3]}{'t?' if mo == 9 else ''}\.?)" if len(name) > 3 else name  # 'Mune 4' / 'Uuly 27'

    yy, yyyy = _ocr_num(y % 100, pad=False) if y % 100 >= 10 else "[0o]" + _ocr_num(y % 100, False), _ocr_num(y, False)
    pats = [
        rf"\b{mon}\s*,?\s*{_ocr_num(d)}(?:st|nd|rd|th)?\s*(?:-\s*\d{{1,2}}\s*)?,?\s*{yyyy}(?![0-9])",
        rf"(?<![0-9a-z]){_ocr_num(d)}(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?{mon}\s*,?\s*{yyyy}(?![0-9])",
        rf"(?<![0-9a-z]){_ocr_num(mo)}\s?[./\\\-:|,•·]\s?{_ocr_num(d)}\s?[./\\\-:|,•·]\s?(?:{yyyy}|{yy})(?![0-9a-z])",
        rf"(?<![0-9]){yyyy}\s?[./\-]\s?{_ocr_num(mo)}\s?[./\-]\s?{_ocr_num(d)}(?![0-9])",
    ]
    return sorted({m.start() for pat in pats for m in re.finditer(pat, t)})


def date_stated(f: TextFacts, value: str) -> bool:
    full, months, years, md = f.dates()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        if value in full:
            return True
        if _iso(int(value[:4]), int(value[5:7]), int(value[8:10])) and date_positions(f, value):
            return True  # printed through scan damage
        return value[5:] in md and value[:4] in years  # 'Wednesday, May 15' with the year written elsewhere
    if re.fullmatch(r"\d{4}-\d{2}", value):
        if value in months:
            return True
        y, mo = int(value[:4]), int(value[5:7])
        return bool(re.search(rf"(?<![0-9/]){_ocr_num(mo)}\s?[/.\-]\s?(?:{y}|{y % 100:02d})(?![0-9/])|/{y}/0?{mo}/", f.norm))  # '4/2017', '01/18', '.gov/2026/6/'

    if re.fullmatch(r"\d{4}", value):
        return value in years
    return False


_COMMITTEE_LIKE = re.compile(r"^(?:(?:U\.?S\.?|United States)\s+)?(?:House|Senate|Joint)\b.*\b(?:Sub)?[Cc]ommittee\b|^(?:Permanent\s+|Select\s+|Special\s+)*(?:Sub)?[Cc]ommittee on ")
G1_STRING_FIELDS = ("verbatim_title", "event_title", "issuer_org")
G1_LIST_FIELDS = ("orgs_mentioned", "places", "programs")
G1_PERSONA_FIELDS = ("org", "title", "work_addr")
G1_DATE_FIELDS = ("doc_date", "event_date", "due_date")


# Descriptive fields where the blind read found the strict matcher under 95% correct on its removals (OCR and
# layout damage, informal or reordered names: 'Heritage' for The Heritage Foundation, 'Rural Util. Serv.', columns
# interleaved). There a value is removed only when, besides failing the strict match, most of its content words
# leave no trace anywhere in the text; a value with a trace stays (false keeps are preferred to deleting a stated
# fact). The hard fields (congress, chamber, committees, subcommittees, dates, event_title) stay strict.
G1_SOFT_FIELDS = {"p.title": 0.75, "p.work_addr": 0.75, "date_spans": 0.75,
                  # names of organisations, programs and places: removed only when no distinctive word is in the
                  # text at all (second read: half the residual removals were informal or damaged forms)
                  "orgs_mentioned": 1e-9, "programs": 1e-9, "places": 1e-9, "p.org": 1e-9, "issuer_org": 1e-9}
_GENERIC_WORDS = frozenset({"department", "office", "center", "foundation", "institute", "university", "association",
                            "council", "committee", "commission", "agency", "bureau", "service", "national", "american",
                            "international", "united", "states", "federal", "inc", "corporation", "company", "group"})


def g1_trace(f: TextFacts, value: str, ocr: bool = False) -> float:
    """Share of the value's content words that occur anywhere in the text, OCR-tolerant, or as an abbreviation the
    text writes ('util' for Utilities)."""
    C = [t for t in _canon_tokens(value) if t not in _WEAK and len(t) >= 3]
    if not C:
        return 1.0
    def found(t: str) -> bool:
        if f.positions(t):
            return True
        return len(t) >= 6 and any(len(w) >= 4 and t.startswith(w) and w in f.caps for w in f.pos)
    hit = [t for t in C if found(t)]
    if not any((ocr or t not in _GENERIC_WORDS) and len(t) >= 4 for t in hit):
        return 0.0  # in OCR text a generic word ('Natioval War Glhege') is trace enough
    return len(hit) / len(C)


def g1_value_stated(field: str, value: Any, f: TextFacts, lab: dict[str, Any]) -> bool:
    if g1_value_stated_strict(field, value, f, lab):
        return True
    return field in G1_SOFT_FIELDS and g1_trace(f, str(value), lab.get("text_quality", "native") != "native") >= G1_SOFT_FIELDS[field]


def g1_value_stated_strict(field: str, value: Any, f: TextFacts, lab: dict[str, Any]) -> bool:
    if field == "congress":
        return int(value) in stated_congresses(f)
    if field == "chamber":
        if value == "executive_or_external":
            return True  # a conclusion about authorship (no phrase states it); kept as a judgment
        if value in chamber_evidence(f, lab):
            return True
        # a committee the label lists, named in the text with this chamber evident for it ('Senate Judiciary');
        # not in a biography, where a named committee is the witness's past employer
        return lab.get("primary_kind") != "witness_biography" and any(committee_stated(f, c, lab)[0] and committee_chamber(f, c, lab) == value for c in lab.get("committees") or [])
    if field in ("committees", "subcommittees"):
        return committee_stated(f, value)[0]
    if field == "refs":
        return _ref_grounded(value, f.norm)
    if field in G1_DATE_FIELDS:
        return date_stated(f, value)
    if field == "date_spans":
        return f.stated(value, segments=False) or bool(_text_dates(norm_ground(value))[0] & f.dates()[0])
    if field in ("verbatim_title", "event_title"):
        return title_stated(f, value)
    if field in ("issuer_org", "orgs_mentioned", "p.org") and _COMMITTEE_LIKE.search(value):
        return committee_stated(f, value)[0]
    if field in ("issuer_org", "orgs_mentioned", "programs", "p.org"):
        return f.stated(value, acronyms=True)
    if field == "places":
        return place_stated(f, value)
    if field == "p.title":
        # rubric form 'Nominee to be <office>': the office must be stated, the prefix is the rubric's
        v2 = re.sub(r"^\s*nominee\s+(?:to\s+be|for)(?:\s+(?:a|an|the))?\s+", "", value, flags=re.I)
        if v2 != value and v2 and (f.stated(v2) or f.any_order(_canon_tokens(v2))):
            return True
        if f.any_order(_canon_tokens(value)) or f.stated(value, acronyms=True):
            return True
        if _COMMITTEE_LIKE.search(value.strip()):
            return committee_stated(f, value)[0]
    return f.stated(value)


def place_stated(f: TextFacts, value: str) -> bool:
    """A place, segment by segment: the name as written (state names and postal / AP abbreviations fold), the
    adjective the text uses ('Iranian' for Iran, 'Hawaiian' for Hawaii), 'Okanogan and Ferry counties' for
    Okanogan County, and 'Washington' or 'District of Columbia' for Washington, D.C."""
    def one(seg: str) -> bool:
        V = _canon_tokens(seg)
        if not V or f.stated(seg, segments=False):
            return True
        if V == ["wa", "dc"]:
            return "dc" in f.pos or "wa" in f.pos
        m = re.match(r"^(.+?)\s+count(?:y|ies)$", seg.strip(), re.I)
        if m:
            X = _canon_tokens(m.group(1))
            return any(any(f.toks[q] in ("county", "counties") for q in range(p + len(X), min(len(f.toks), p + len(X) + 5)))
                       for p in _phrase_positions(f, X))
        if len(V) == 1 and len(V[0]) >= 4:  # 'Cuban', 'Lebanese', 'Italian', 'Iranian'
            w0 = V[0]
            stems = {w0[:-1] if w0[-1] in "aeiouy" else w0, w0[:-2]}
            return any(w.startswith(st) and 0 < len(w) - len(st) <= 4 for st in stems if len(st) >= 3 for w in f.caps)
        return False
    segs = [x for x in re.split(r"\s*[,;/]\s*", value) if x.strip()]
    return all(one(x) for x in segs) if len(segs) >= 2 else one(value)


def facts(cx: "Ctx") -> TextFacts:
    return _cached(cx, "_facts", lambda: TextFacts(cx.text))


# ---- where an unstated value does occur (signal attribution only; never decides a label value)
_FN_CMTE_RE = re.compile(r"(?:HHRG|HMKP|HMTG|CHRG)-\d{2,3}-([A-Z]{2})(\d\d)")
ROSTER_SUBNAMES: dict[str, str] = {}


def _known_dict(cx: "Ctx") -> dict[str, Any]:
    try:
        d = json.loads(cx.known)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _code_names(code: str, congress: Any) -> list[str]:
    out = []
    if CMTNAMES is not None:
        n = CMTNAMES.name(code, int(congress) if congress else None)
        if n:
            out.append(n)
    if code[:6] in ROSTER_SUBNAMES:
        out.append(ROSTER_SUBNAMES[code[:6]])
    return out


def _same_committee(a: str, b: str) -> bool:
    return committee_core(a)[1] == committee_core(b)[1] and bool(committee_core(a)[1])


def _date_in(value: str, dates: set[str]) -> bool:
    return any(d == value or d.startswith(value) or value.startswith(d) for d in dates)


def _fn_dates(fn: str) -> set[str]:
    out = set(_text_dates(norm_ground(camel_split(fn)))[0])
    for m in re.finditer(r"(?<!\d)((?:19|20)\d\d)(\d\d)(\d\d)(?!\d)", fn):
        iso = _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            out.add(iso)
    for m in re.finditer(r"(?<!\d)(\d{1,2})[-._](\d{1,2})[-._](\d{2}|\d{4})(?!\d)", fn):
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        iso = _iso(y, int(m.group(1)), int(m.group(2)))
        if iso:
            out.add(iso)
    return out


def g1_sources(field: str, value: Any, cx: "Ctx", lab: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if cx.alt_text:
        fa = _cached(cx, "_facts_alt", lambda: TextFacts(cx.alt_text))
        if field == "personas.name":
            hit = any(_tok_norm(t) in fa.raw_set for t in str(value).split() if len(_tok_norm(t)) >= 3)
        else:
            hit = g1_value_stated(field, value, fa, lab)
        if hit:
            out.append("reviewer_window_only")
    kn = _known_dict(cx)
    known_hit = False
    if field == "congress":
        known_hit = kn.get("congress") is not None and int(kn["congress"]) == int(value)
    elif field == "chamber":
        known_hit = value in (kn.get("chambers") or [])
    elif field in G1_DATE_FIELDS or field == "date_spans":
        known_hit = bool(kn.get("date")) and _date_in(str(value), {str(kn["date"])}) if field != "date_spans" else False
    elif field in ("committees", "subcommittees"):
        for c in kn.get("cmt") or []:
            names = _code_names(c, kn.get("congress")) if re.fullmatch(r"[a-z]{4}\d\d", str(c)) else [str(c)]
            if any(_same_committee(n, value) for n in names):
                known_hit = True
    elif field == "refs":
        known_hit = _ref_grounded(str(value), norm_ground(cx.known))
    elif field == "personas.name":
        known_hit = False
    else:
        known_hit = TextFacts(cx.known).stated(str(value), segments=False)
    if known_hit:
        out.append("known")
    fn = cx.fn
    fn_hit = False
    if field == "congress":
        fn_hit = bool(re.search(rf"(?<!\d){int(value)}(?!\d)", fn))
    elif field in G1_DATE_FIELDS:
        fn_hit = _date_in(str(value), _fn_dates(fn))
    elif field in ("committees", "subcommittees"):
        for m in _FN_CMTE_RE.finditer(fn):
            code = ("hs" + m.group(1)).lower() + (m.group(2) if field == "subcommittees" else "00")
            if any(_same_committee(n, value) for n in _code_names(code, None)):
                fn_hit = True
    elif field == "chamber":
        fn_hit = bool(re.search(r"\b(?:HHRG|HMKP|HMTG|CRPT-\d+h|CHRG-\d+h)", fn)) if value == "house" else bool(re.search(r"CHRG-\d+s|CRPT-\d+s|senate", fn, re.I)) if value == "senate" else False
    elif field == "refs":
        fn_hit = _ref_grounded(str(value), norm_ground(camel_split(fn)))
    elif field == "personas.name":
        fn_hit = any(_tok_norm(t) in set(_raw_tokens(camel_split(fn))) for t in str(value).split() if len(_tok_norm(t)) >= 3)
    elif field != "date_spans":
        fn_hit = TextFacts(camel_split(fn)).stated(str(value), segments=False)
    if fn_hit:
        out.append("filename")
    if field == "congress" and int(value) in derived_congresses(facts(cx)):
        out.append("derived_from_stated_date")
    return out or ["none"]


SOURCE_ORDER = ("reviewer_window_only", "known", "filename", "derived_from_stated_date", "chamber_not_in_text",
                "chamber_evident_in_text", "moved_to_one_field", "none")


def _signal(cx: "Ctx", lab: dict[str, Any], rule: str, field: str, value: Any, *, persona: str | None = None,
            kept_as: Any = None, sources: list[str] | None = None) -> None:
    """Record a removed (or rewritten) label value in the signal layer, with where it does occur."""
    srcs = sources if sources is not None else g1_sources(field, value, cx, lab)
    rec = {"link_key_hex": cx.lk, "set": cx.set_name, "rule": rule, "field": field, "value": value,
           "occurs_in": srcs, "source": next(s for s in SOURCE_ORDER if s in srcs)}
    if persona is not None:
        rec["persona"] = persona
    if kept_as is not None:
        rec["kept_as"] = kept_as
    cx.__dict__.setdefault("_signal", []).append(rec)


def g1_text_only(lab: dict[str, Any], cx: "Ctx") -> str | None:
    """Every value of the factual fields must be stated in the training text; the rest moves to the signal layer.
    A committee the text names without its chamber is written without one. Rows whose text is mostly non-Latin
    (Cyrillic statements labeled in English) are left as labeled: the matcher cannot read them (owner question).
    The K1 JCT fields are the owner's explicit rule and are not re-judged here."""
    if lab.get("status", "usable") in HARD_ERROR_STATUSES or _non_latin_share(cx.text) > 0.2:
        return None
    f = facts(cx)
    notes: list[str] = []
    protect = cx.__dict__.get("_k1_protect", False)
    ch_ok = None
    if "chamber" in lab and not protect:
        ch_ok = True if _c2_keeps_scalar(cx, "chamber", lab["chamber"]) else g1_value_stated("chamber", lab["chamber"], f, lab)
    # committees: named in the text, and written without a chamber when the text gives none for it
    for field in ("committees", "subcommittees"):
        if not lab.get(field) or (protect and field == "committees"):
            continue
        new: list[str] = []
        for c in lab[field]:
            if _c2_keeps_item(cx, field, c):
                new.append(c)
                continue
            named = committee_stated(f, c, lab)[0]
            if not named:
                _signal(cx, lab, "G1", field, c)
                notes.append(f"{field} -{c}")
                continue
            if field == "committees" and committee_core(c)[0] in (None, "house", "senate") and committee_core(c)[2] == "committee":
                c2 = with_chamber(c, committee_chamber(f, c, lab))
                if c2 != c and c2 in new + list(lab[field]):
                    c2 = strip_chamber(c)  # the evident chamber's committee is listed already: keep this one unplaced
                if c2 != c:
                    _signal(cx, lab, "G1", field, c, kept_as=c2, sources=["chamber_not_in_text" if c2 == strip_chamber(c) else "chamber_evident_in_text"])
                    notes.append(f"{field} {c} -> {c2}")
                new.append(c2)
            else:
                new.append(c)
        lab[field] = list(dict.fromkeys(new))
    if ch_ok is False:
        _signal(cx, lab, "G1", "chamber", lab["chamber"])
        notes.append(f"chamber -{lab['chamber']}")
        del lab["chamber"]
    if not lab.get("chamber") and not protect and not _c2_drops_scalar(cx, "chamber") and is_amendment(lab) and len(amendment_chambers(f)) == 1:
        lab["chamber"] = next(iter(amendment_chambers(f)))  # the amendment's own form names its chamber
        notes.append(f"chamber +{lab['chamber']} (committee amendment form)")
    for field in ("congress",) + G1_DATE_FIELDS + G1_STRING_FIELDS:
        if field in lab and not _c2_keeps_scalar(cx, field, lab[field]) and not g1_value_stated(field, lab[field], f, lab):
            _signal(cx, lab, "G1", field, lab[field])
            notes.append(f"{field} -{lab[field]!r}")
            del lab[field]
    for field in ("issuer_org",):
        v = lab.get(field)
        c2 = _committee_value(f, v, lab) if v and not _c2_keeps_scalar(cx, field, v) else None
        if c2 and c2 != v:
            _signal(cx, lab, "G1", field, v, kept_as=c2, sources=["chamber_not_in_text" if c2 == strip_chamber(v) else "chamber_evident_in_text"])
            lab[field] = c2
            notes.append(f"{field} {v} -> {c2}")
    for field in ("date_spans",) + G1_LIST_FIELDS:
        if not lab.get(field):
            continue
        keep = []
        for v in lab[field]:
            if _c2_keeps_item(cx, field, v) or g1_value_stated(field, v, f, lab):
                keep.append(v)
            else:
                _signal(cx, lab, "G1", field, v)
                notes.append(f"{field} -{v!r}")
        lab[field] = keep
    ps_g1 = lab.get("personas") or []
    for p_idx, p in enumerate(ps_g1):
        for pf in G1_PERSONA_FIELDS:
            v = p.get(pf)
            if not v or _c2_keeps_person_field(cx, ps_g1, p_idx, pf, v):
                continue
            if not g1_value_stated("p." + pf, v, f, lab):
                _signal(cx, lab, "G1", "personas." + pf, v, persona=p.get("name"), sources=g1_sources("p." + pf, v, cx, lab))
                notes.append(f"{p.get('name')}.{pf} -{v!r}")
                del p[pf]
            elif pf == "org" and (c2 := _committee_value(f, v, lab)) and c2 != v:
                _signal(cx, lab, "G1", "personas.org", v, persona=p.get("name"), kept_as=c2,
                        sources=["chamber_not_in_text" if c2 == strip_chamber(v) else "chamber_evident_in_text"])
                p[pf] = c2
                notes.append(f"{p.get('name')}.org {v} -> {c2}")
    g1_person_and_venue(lab, cx, f, notes)
    return "; ".join(notes) if notes else None


# ---- G1, person and venue fields (owner: "interpret, do not invent"; coordinator 2026-11-18). Keep what the text
# gives, remove what has no basis in it (a party code, a room number, an event type the text never shows).
_PARTY_WORD = {"r": "R", "d": "D", "i": "I", "republican": "R", "democrat": "D", "democratic": "D", "independent": "I"}
_CODE_TO_STATE = {v: k for k, v in _STATE_CODES.items()}
_EVENT_CUE_RE = re.compile(
    r"hearing|meeting|mark-?\s?up|roundtable|briefing|forum|testimony|testify|before the|statement of|session"
    r"|will (?:be held|convene|meet)|\b\d{1,2}:\d{2}\s*[ap]\.?\s?m|\broom\b|office building|roll call|recorded vote|attendance|quorum"
    r"|for the record|nominee|nomination|advance policy questions|questions for the")
_VENUE_KIND_CUE = {  # read on the lower-cased raw text
    "capitol_room": re.compile(
        r"\broom\s*[a-z]?-?\s?\d|\brm\.?\s*\d|office building|\b[rlc]\.?\s?h\.?\s?o\.?\s?b\b|\brayburn\b|\blongworth\b"
        r"|\bcannon\s+(?:house|office|building|bldg|hob|caucus)|\b(?:dirksen|hart|russell)\s+(?:senate|office|building|bldg|sob)"
        r"|\b\d{2,4}\s+(?:rayburn|longworth|cannon|dirksen|hart|russell)\b|\bcapitol\b(?!\s+hill)|visitor center"
        r"|\b(?:s|h|sd|sh|sr|hc|hvc|svc)-\s?[g\d]\d{1,3}\b|\blocation:|\b(?:rayburn|longworth|cannon|dirksen|hart|russell)\s+\d{2,4}\b"),
    "virtual": re.compile(r"virtual|remote|webex|zoom|online|vide?o?\s?conferenc|teleconference|webinar"),
    "hybrid": re.compile(r"hybrid|in person and (?:virtual|remote)|in-person and (?:virtual|remote)|both in person"),
    "field_site": re.compile(r"field hearing|field site|\bheld (?:at|in)\b"),
}


def _party_state_evident(f: TextFacts, name: str, value: str) -> str | None:
    """The parts of a party / state code the text gives beside this person ('(R-GA)', 'R-Utah', 'Mr. Bishop of
    Utah', 'Republican of Utah'), written in the schema's form ('R-UT', 'UT'); None when it gives neither."""
    m = re.fullmatch(r"\s*([RDI])?\s*-?\s*([A-Z]{2})?(?:\s*-\s*(\d{1,2}|AL))?\s*", value or "")
    if not m or not (m.group(1) or m.group(2)):
        return value if f.stated(value, segments=False) else None
    party, state, dist = m.group(1), m.group(2), m.group(3)
    sur = _tok_norm(str(name or "").split()[-1]) if name else ""
    if len(sur) < 2:
        return None
    t, raw = f.norm, f.text
    got_p = got_s = got_d = False
    for mm in re.finditer(r"\b" + re.escape(sur) + r"\b", t):
        party_re = r"\(\s*([rdi])\s*[-–.,]\s*([a-z]{2,14}\.?)(?:\s*[-–]\s*(\d{1,2}|al))?\s*\)|\b([rdi])-([a-z]{2,14})\b(?:-(\d{1,2}))?"
        # the code written right after the name ('Frank Pallone (D-NJ)'), else right before it
        pm = re.search(party_re, t[mm.end() : mm.end() + 30]) or re.search(party_re + r"\W{0,4}$", t[max(0, mm.start() - 30) : mm.start()])
        if pm:
            pty, st, ds = (pm.group(1), pm.group(2), pm.group(3)) if pm.group(1) else (pm.group(4), pm.group(5), pm.group(6))
            st = st.rstrip(".")
            code = st if len(st) == 2 else _STATE_CODES.get(st) or _AP_STATES.get(st)
            if party and pty.upper() == party:
                got_p = True
            if state and code and code.upper() == state:
                got_s = True
            if dist and ds and ds.lstrip("0") == dist.lstrip("0"):
                got_d = True
        if party and re.match(r"\s*\(\s*" + party.lower() + r"\s*\)", t[mm.end() : mm.end() + 8]):
            got_p = True  # 'Smith (R)'; a party column header is never read
        if state and not got_s:
            full = _CODE_TO_STATE.get(state.lower(), "")
            after = t[mm.end() : mm.end() + 40]
            # the state attached to the name: 'Marlin A. Stutzman, Indiana', 'Mr. Bishop of Utah', 'Jackson Lee 18th
            # district. Texas', '... represents Texas' 16th'; never 'Washington, D.C.'
            if full and (re.match(r"\W{0,3}(?:of\s+|\d{1,2}(?:st|nd|rd|th)\s+district\W{0,3})?" + full + r"\b(?!\W{0,3}d\.?\s?c\b)", after)
                         or re.search(r"\brepresents\s+(?:the\s+(?:state|people)\s+of\s+)?" + full + r"\b", t[mm.end() : mm.end() + 250])):
                got_s = True
    if not got_s and not got_p:
        return None
    out = ""
    if got_p and got_s:
        out = f"{party}-{state}" + (f"-{int(dist):02d}" if got_d and dist.isdigit() else ("-AL" if got_d else ""))
    elif got_s:
        out = state
    else:
        return None  # a party alone has no schema form
    return out


_SERVICE = {"usaf": "air force", "usmc": "marine corps", "usn": "navy", "usa": "army", "uscg": "coast guard",
            "ussf": "space force", "ret": "retired", "lt": "lieutenant", "gen": "general", "adm": "admiral",
            "radm": "rear admiral", "vadm": "vice admiral", "col": "colonel", "maj": "major", "capt": "captain"}


def _creds_evident(f: TextFacts, creds: str) -> bool:
    """Any part of the credentials evident in the text: a degree written with or without dots ('M.D.', 'MD'), a
    rank written out or abbreviated ('Lt. Gen.' / 'Lieutenant General'), a service named ('USAF' / 'Air Force')."""
    t = f.norm
    for part in [x for x in re.split(r"[,;()/]", creds) if x.strip()]:
        letters = re.sub(r"[^a-z]", "", norm_ground(part))
        if not letters:
            continue
        if len(letters) <= 5 and re.search(r"(?<![a-z])" + r"\W{0,2}\s?".join(re.escape(ch) for ch in letters) + r"(?![a-z])", t):
            return True
        words = [_SERVICE.get(w, w) for w in _raw_tokens(part)]
        if words and f.stated(" ".join(words), segments=False, acronyms=True):
            return True
    return False


_VENUE_GENERIC = {"house", "senate", "office", "building", "bldg", "room", "rm", "the", "of", "us", "united", "states",
                  "hob", "sob", "hall", "floor", "suite"}
_VENUE_ABBR = [  # a building the text names by its usual abbreviation ('1300 LHOB', 'RHOB 2318', 'SD-608', 'S-216')
    (re.compile(r"\bR\.?\s?H\.?\s?O\.?\s?B\b"), "rayburn"), (re.compile(r"\bL\.?\s?H\.?\s?O\.?\s?B\b"), "longworth"),
    (re.compile(r"\bC\.?\s?H\.?\s?O\.?\s?B\b"), "cannon"), (re.compile(r"\bSD-?\s?[G\d]\d{1,3}"), "dirksen"),
    (re.compile(r"\bSH-?\s?[G\d]\d{1,3}"), "hart"), (re.compile(r"\bSR-?\s?[G\d]\d{1,3}"), "russell"),
    (re.compile(r"\b(?:S|H|HC|HVC|SVC)-\s?\d{1,3}\b"), "capitol")]
_LOCATION_RE = re.compile(r"\b(?:location|place|room)\s*:\s*([^\n]{2,80})", re.I)
_ROOM_BUILDING_RE = re.compile(
    r"\b((?:room\s+)?(?:(?:SD|SH|SR|HC|HVC|SVC|S|H)-?\s?[G\d]\d{0,3}[A-Z]?|\d{3,4}(?:-?[A-Z])?)(?:,?\s+(?:the\s+)?(?:Rayburn|Longworth|Cannon|Dirksen|Hart|Russell)"
    r"(?:\s+(?:House|Senate))?(?:\s+Off?ice\s+Building|\s+[HS]OB)?))", re.I)


_BUILDINGS = ("rayburn", "longworth", "cannon", "dirksen", "hart", "russell")
_BUILDING_NEXT = {"house", "senate", "office", "building", "bldg", "hob", "sob", "room"}


def _place_word_in(f: TextFacts, w: str, text: str) -> bool:
    """A place name in the text as written or through scan damage ('Raybum'), never a near-miss word ('cannot',
    'capital'); an office building only as a building ('Cannon 360', '2167 Rayburn', 'Dirksen Senate Office
    Building'), not 'a cannon crewmember'."""
    if w in _BUILDINGS:
        T = f.toks
        hits = [i for x, ps in f.pos.items() if x == w or _ocr_fold(x) == _ocr_fold(w) for i in ps]
        return any((i + 1 < len(T) and (T[i + 1] in _BUILDING_NEXT or T[i + 1][:1].isdigit()))
                   or (i >= 1 and T[i - 1][:1].isdigit())
                   or (i >= 2 and (T[i - 1] == "the" or len(T[i - 1]) == 1) and T[i - 2][:1].isdigit()) for i in hits)  # '2362-B Rayburn'
    return w in f.pos or (len(w) >= 5 and any(_ocr_fold(w) == _ocr_fold(x) for x in f.pos))


def venue_kind_evident(vk: str, text: str, venue: str | None) -> bool:
    """The text gives a place or mode of this kind: a Capitol room or office building; 'virtual', 'Webex', 'Zoom';
    hybrid = 'hybrid' or a room and a remote mode together ('2318 Rayburn ... and Online via Zoom', 'in person or by
    video conference'); a field hearing's named venue is its place."""
    tl = text.lower()
    cue = _VENUE_KIND_CUE[vk].search(tl)
    if vk == "hybrid":
        return bool(cue or (_VENUE_KIND_CUE["virtual"].search(tl) and (_VENUE_KIND_CUE["capitol_room"].search(tl) or venue)))
    if vk == "field_site":
        return bool(cue or venue)
    return bool(cue)


def venue_from_text(text: str) -> str | None:
    """The event's place as the text writes it: a 'Location:' / 'Room:' field, or a room and building near an
    event word ('will be held in 2167 Rayburn'). A letterhead address (building followed by 'Washington, DC 205..')
    is the sender's office, not the event's venue."""
    m = _LOCATION_RE.search(text)
    if m:
        v = re.split(r"\s{2,}|\s+(?:Time|Date|Presiding|Witnesses?)\b", m.group(1).strip())[0].strip(" .,;")
        if 2 <= len(v) <= 80 and re.search(r"\d|building|capitol|hall|center|room|virtual|online", v, re.I):
            return v
    for m in _ROOM_BUILDING_RE.finditer(text):
        after = re.sub(r"\s+", " ", text[m.end() : m.end() + 60])
        before = re.sub(r"\s+", " ", text[max(0, m.start() - 160) : m.start()]).lower()
        if re.match(r"\W{0,4}washington,?\s*d\.?\s?c\.?\s*205\d\d", after, re.I):
            continue  # letterhead
        if re.search(r"hearing|meeting|markup|mark-up|convene|held|session|location|room|in person", before + " " + after.lower()):
            return re.sub(r"\s+", " ", m.group(1)).strip(" ,")
    return None


def g1_person_and_venue(lab: dict[str, Any], cx: "Ctx", f: TextFacts, notes: list[str]) -> None:
    t = f.norm
    ps_pv = lab.get("personas") or []
    for p_idx, p in enumerate(ps_pv):
        if p.get("party_state") and not _c2_keeps_person_field(cx, ps_pv, p_idx, "party_state", p["party_state"]):
            v = p["party_state"]
            new = _party_state_evident(f, p.get("name"), v)
            if new != v:
                _signal(cx, lab, "G1", "personas.party_state", v, persona=p.get("name"), kept_as=new, sources=g1_sources("p.party_state", v, cx, lab))
                notes.append(f"{p.get('name')}.party_state {v} -> {new}")
                if new:
                    p["party_state"] = new
                else:
                    del p["party_state"]
        if p.get("panel") and not _c2_keeps_person_field(cx, ps_pv, p_idx, "panel", p["panel"]) and not (f.stated(p["panel"], segments=False) or (
                re.search(r"\bpanel\b", t) and any(w in f.raw_set for w in _raw_tokens(p["panel"]) if w not in ("panel",)))):
            _signal(cx, lab, "G1", "personas.panel", p["panel"], persona=p.get("name"))
            notes.append(f"{p.get('name')}.panel -{p['panel']!r}")
            del p["panel"]
        if p.get("creds") and not _c2_keeps_person_field(cx, ps_pv, p_idx, "creds", p["creds"]) and not _creds_evident(f, p["creds"]):
            if True:
                _signal(cx, lab, "G1", "personas.creds", p["creds"], persona=p.get("name"))
                notes.append(f"{p.get('name')}.creds -{p['creds']!r}")
                del p["creds"]
        if p.get("education"):
            keep = [e for e in p["education"] if _c2_keeps_person_field(cx, ps_pv, p_idx, "education", e)
                    or g1_trace(f, e.replace("|", " "), lab.get("text_quality", "native") != "native") >= 0.5]
            for e in p["education"]:
                if e not in keep:
                    _signal(cx, lab, "G1", "personas.education", e, persona=p.get("name"))
                    notes.append(f"{p.get('name')}.education -{e!r}")
            if keep:
                p["education"] = keep
            else:
                del p["education"]
    if lab.get("venue") and not _c2_keeps_scalar(cx, "venue", lab["venue"]):
        v = lab["venue"]
        nums = re.findall(r"\d{2,5}", norm_ground(v))
        v2 = v
        for n in nums:
            if not re.search(r"(?<![0-9])" + n + r"(?![0-9])", t):  # a room number the text never gives
                v2 = re.sub(r"\b[A-Za-z]{0,3}-?" + n + r"[A-Za-z]?\b,?", " ", v2).strip(" ,")
                v2 = re.sub(r"\s+", " ", v2)
        # the place's own name must be in the text: 'Rayburn House Office Building' is not stated by 'House' and 'Office'
        named = [w for w in _canon_tokens(v2) if w not in _VENUE_GENERIC and not w.isdigit()]
        abbr = _cached(f, "_venue_abbr", lambda: {b for rx, b in _VENUE_ABBR if rx.search(f.text)})
        written = bool(v2) and f" {norm_ground(v2)} " in f" {f.norm} "  # as the text writes it ('SD-608')
        if not v2 or not _canon_tokens(v2) or not (written or g1_trace(f, v2, lab.get("text_quality", "native") != "native") >= 0.5) \
                or not all(w in abbr or _place_word_in(f, w, cx.text) for w in named):
            _signal(cx, lab, "G1", "venue", v)
            notes.append(f"venue -{v!r}")
            del lab["venue"]
        elif v2 != v:
            _signal(cx, lab, "G1", "venue", v, kept_as=v2)
            notes.append(f"venue {v!r} -> {v2!r}")
            lab["venue"] = v2
    vk = lab.get("venue_kind")
    if vk and not lab.get("venue"):
        # where the event is held, as the text writes it ('Location: SD-366', '406 Dirksen Senate Office Building');
        # a virtual hearing keeps its kind with no venue string; with no place of the event at all the kind goes
        v_txt = venue_from_text(cx.text)
        if v_txt and vk != "virtual" and not _c2_drops_scalar(cx, "venue"):
            lab["venue"] = v_txt
            notes.append(f"venue +{v_txt!r} (the text's location line)")
        elif not _c2_keeps_scalar(cx, "venue_kind", vk) and not (vk in ("virtual", "hybrid") and venue_kind_evident(vk, cx.text, None)):
            _signal(cx, lab, "G1", "venue_kind", vk)
            notes.append(f"venue_kind -{vk}")
            del lab["venue_kind"]
    vk = lab.get("venue_kind")
    if vk and lab.get("venue") and not _c2_keeps_scalar(cx, "venue_kind", vk) and not venue_kind_evident(vk, cx.text, lab["venue"]):
        # the text gives no place or mode of this kind ('room for improvement' is not a room; a letterhead city is
        # not a Capitol room); a field hearing's venue named in the text is its place
        _signal(cx, lab, "G1", "venue_kind", vk)
        notes.append(f"venue_kind -{vk}")
        del lab["venue_kind"]
    et = lab.get("event_type")
    if et and not _c2_keeps_scalar(cx, "event_type", et) and not _EVENT_CUE_RE.search(t):
        _signal(cx, lab, "G1", "event_type", et)  # the text shows no event at all (a standalone biography, a filing)
        notes.append(f"event_type -{et}")
        del lab["event_type"]


# ---- Data-driven rules: reviewed files in N/lookups_and_gold, read by link key (never the filename or the hint).
# They run on every row after the text rules, unreadable text layers included (those rows were read by a person).
WITNESS_ADDITIONS = N_DIR / "lookups_and_gold" / "transcript_witness_additions.jsonl"
ADJUDICATIONS = resolve_package_fallback(N_DIR / "lookups_and_gold" / "coordinator_adjudications.jsonl", "coordinator_adjudications.jsonl")
SECOND_OPINION = N_DIR / "lookups_and_gold" / "second_opinion_rulings.jsonl"
SECOND_OPINION_HELD = N_DIR / "lookups_and_gold" / "second_opinion_held.jsonl"
_DATA: dict[Path, dict[str, list[dict[str, Any]]]] = {}
_HELD_C2_CACHE: dict[Path, dict[tuple[str, int], str]] = {}

C2_LIST_FIELDS = frozenset({
    "committees", "subcommittees", "refs", "secondary_kinds", "orgs_mentioned",
    "places", "programs", "date_spans", "short_titles", "fiscal_years", "topics",
})
_C2_DEG_OR_SUF_RE = re.compile(r"^(?:ph\.?d|m\.?d|esq|j\.?d|d\.?o|facp|dvm|dds|mph|mba|cpa|rn|jr|sr|ii|iii|iv|v)$")


def _by_key(path: Path) -> dict[str, list[dict[str, Any]]]:
    if path not in _DATA:
        out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if path.is_file():
            for line in path.open(encoding="utf-8"):
                if line.strip():
                    rec = json.loads(line)
                    out[rec.get("link_key_hex") or rec["key"]].append(rec)
        _DATA[path] = out
    return _DATA[path]


def c1_removes(cx: "Ctx", field: str, value: Any) -> bool:
    """The coordinator's adjudications remove this value from this row (the adding rules A1 and F5 never re-add it)."""
    return any(a["field"] == field and a["value"] == value for a in _by_key(ADJUDICATIONS).get(cx.lk, []))


def _c2_surname(name: Any) -> str:
    toks = [tok for t in str(name or "").split() if (tok := _tok_norm(t)) and not _C2_DEG_OR_SUF_RE.fullmatch(tok)]
    return toks[-1] if toks else ""


def _held_c2_rulings(path: Path | None = None) -> dict[tuple[str, int], str]:
    target = path or SECOND_OPINION_HELD
    if target not in _HELD_C2_CACHE:
        held: dict[tuple[str, int], str] = {}
        if target.is_file():
            for line in target.open(encoding="utf-8"):
                if line.strip():
                    rec = json.loads(line)
                    lk = str(rec.get("link_key_hex") or "").strip()
                    n_val = rec.get("n")
                    if lk and n_val is not None:
                        held[(lk, int(n_val))] = str(rec.get("held_reason") or "held_for_owner")
        _HELD_C2_CACHE[target] = held
    return _HELD_C2_CACHE[target]


def _c2_active(cx: "Ctx") -> list[dict[str, Any]]:
    if "C2" not in ENABLED:
        return []
    held = _held_c2_rulings()
    return [
        r
        for r in _by_key(SECOND_OPINION).get(cx.lk, [])
        if r.get("ruling") in ("apply", "modify") and (cx.lk, int(r["n"])) not in held
    ]


def _c2_match_person_idx(ps: list[dict[str, Any]], r: dict[str, Any], sub_field: str) -> tuple[int | None, str | None]:
    fr = r.get("first_reviewer") or {}
    lv = fr.get("label_value")
    if isinstance(lv, dict) and lv.get("name"):
        sur = _c2_surname(lv["name"])
        if not sur:
            return None, "empty surname in first_reviewer.label_value"
        hits = [i for i, p in enumerate(ps) if _c2_surname(p.get("name")) == sur]
        if len(hits) == 1:
            return hits[0], None
        return None, f"no person in label matched surname {sur!r}" if not hits else f"multiple people in label matched surname {sur!r}: {[ps[i].get('name') for i in hits]}"
    if sub_field == "name" and isinstance(lv, str) and lv.strip():
        sur = _c2_surname(lv)
        if not sur:
            return None, "empty surname in first_reviewer.label_value"
        hits = [i for i, p in enumerate(ps) if _c2_surname(p.get("name")) == sur]
        if len(hits) == 1:
            return hits[0], None
        return None, f"no person in label matched surname {sur!r}" if not hits else f"multiple people in label matched surname {sur!r}: {[ps[i].get('name') for i in hits]}"

    w_norm = norm_ground(r.get("why") or "")
    q_norm = norm_ground(r.get("quote") or "")
    hits_why = [i for i, p in enumerate(ps) if (s := _c2_surname(p.get("name"))) and re.search(rf"\b{re.escape(s)}\b", w_norm)]
    hits_quote = [i for i, p in enumerate(ps) if (s := _c2_surname(p.get("name"))) and re.search(rf"\b{re.escape(s)}\b", q_norm)]
    if len(hits_why) == 1:
        return hits_why[0], None
    if len(hits_why) == 0 and len(hits_quote) == 1:
        return hits_quote[0], None
    if len(hits_why) > 1:
        if len(hits_quote) == 1 and hits_quote[0] in hits_why:
            return hits_quote[0], None
        clauses = [c.strip() for c in re.split(r",\s*so\b|;\s*|\bwhile\b|\bwhereas\b|\band\b", w_norm) if c.strip()]
        fv = r.get("final_value")
        if isinstance(fv, str) and fv.strip():
            fv_tok = norm_ground(fv)
            fv_alt = fv_tok.replace("_", " ")
            c_hits = [c for c in clauses if re.search(rf"\b{re.escape(fv_tok)}\b", c) or (fv_alt != fv_tok and re.search(rf"\b{re.escape(fv_alt)}\b", c))]
            if len(c_hits) == 1:
                p_in_c = [i for i in hits_why if re.search(rf"\b{re.escape(_c2_surname(ps[i].get('name')))}\b", c_hits[0])]
                if len(p_in_c) == 1:
                    return p_in_c[0], None
        if isinstance(lv, str) and lv.strip():
            lv_tok = norm_ground(lv).replace("_", " ")
            c_hits = [c for c in clauses if re.search(rf"\b(?:not|rather than|never|without)\b.*\b{re.escape(lv_tok)}\b", c)]
            if len(c_hits) == 1:
                p_in_c = [i for i in hits_why if re.search(rf"\b{re.escape(_c2_surname(ps[i].get('name')))}\b", c_hits[0])]
                if len(p_in_c) == 1:
                    return p_in_c[0], None
        return None, f"multiple people in label matched quote/why: {[ps[i].get('name') for i in hits_why]}"
    if len(hits_quote) > 1:
        return None, f"multiple people in label matched quote: {[ps[i].get('name') for i in hits_quote]}"
    return None, "no person in label matched surname in quote/why"


def _c2_keeps_scalar(cx: "Ctx", field: str, val: Any) -> bool:
    return any(r["field"] == field and r["final_value"] is not None and r["final_value"] == val for r in _c2_active(cx))


def _c2_drops_scalar(cx: "Ctx", field: str) -> bool:
    return any(r["field"] == field and r["final_value"] is None for r in _c2_active(cx))


def _c2_keeps_item(cx: "Ctx", field: str, item: Any) -> bool:
    for r in _c2_active(cx):
        fv = r["final_value"]
        if fv is None:
            continue
        if r["field"] == field:
            if isinstance(fv, list) and item in fv:
                return True
            if not isinstance(fv, list) and fv == item:
                return True
        elif re.fullmatch(rf"{re.escape(field)}\[\d+\]", r["field"]) and fv == item:
            return True
    return False


def _c2_keeps_person_name(cx: "Ctx", ps: list[dict[str, Any]], p_idx: int) -> bool:
    name = ps[p_idx].get("name")
    if not name:
        return False
    for r in _c2_active(cx):
        f, fv = r["field"], r["final_value"]
        if f == "personas" and isinstance(fv, list) and any(isinstance(wp, dict) and wp.get("name") == name for wp in fv):
            return True
        if re.fullmatch(r"personas\[\d+\]", f) and isinstance(fv, dict) and fv.get("name") == name:
            return True
        if re.fullmatch(r"personas\[\d+\]\.name", f) and fv == name and _c2_match_person_idx(ps, r, "name")[0] == p_idx:
            return True
    return False


def _c2_keeps_person_field(cx: "Ctx", ps: list[dict[str, Any]], p_idx: int, pf: str, val: Any) -> bool:
    if val is None:
        return False
    sur = _c2_surname(ps[p_idx].get("name"))
    for r in _c2_active(cx):
        f, fv = r["field"], r["final_value"]
        if fv is None:
            continue
        if f == "personas" and isinstance(fv, list):
            for wp in fv:
                if isinstance(wp, dict) and sur and _c2_surname(wp.get("name")) == sur:
                    if (pf == "education" and val in (wp.get("education") or [])) or wp.get(pf) == val:
                        return True
        elif re.fullmatch(r"personas\[\d+\]", f) and isinstance(fv, dict):
            if sur and _c2_surname(fv.get("name")) == sur:
                if (pf == "education" and val in (fv.get("education") or [])) or fv.get(pf) == val:
                    return True
        elif (m := re.fullmatch(r"personas\[\d+\]\.([a-z_]+)(?:\[\d+\])?", f)) and m.group(1) == pf:
            if fv == val and _c2_match_person_idx(ps, r, pf)[0] == p_idx:
                return True
    return False


def _c2_drops_person(cx: "Ctx", name: str) -> bool:
    for r in _c2_active(cx):
        f, fv = r["field"], r["final_value"]
        if fv is None and (f == "personas" or re.fullmatch(r"personas\[\d+\]", f)):
            lv = (r.get("first_reviewer") or {}).get("label_value")
            targets = lv if isinstance(lv, list) else ([lv] if lv is not None else [])
            if not targets or any((t.get("name") if isinstance(t, dict) else str(t)) == name for t in targets):
                return True
    return False


def _surname(name: Any) -> str:
    toks = [t for t in str(name or "").split() if _tok_norm(t) not in _SUFFIXES]
    return _tok_norm(toks[-1]) if toks else ""


def a1_transcript_witnesses(lab: dict[str, Any], cx: Ctx) -> str | None:
    """Owner 2026-11-18 (rubric: hearing transcripts list their witnesses): add every witness the machine-verified
    transcript pass lists for this row (name as the text shows it, title and organisation as given, role `witness`),
    unless the label already has a person with that surname. entity_type comes from the trainer's witness builder."""
    adds = _by_key(WITNESS_ADDITIONS).get(cx.lk)
    if not adds or lab.get("status", "usable") != "usable":
        return None
    from congress_docmeta.relational_rules_v6 import build_witness_persona_v6

    have = {_surname(p.get("name")) for p in lab.get("personas") or []}  # the label's people before A1
    names = {p.get("name") for p in lab.get("personas") or []}
    quotes = cx.__dict__.setdefault("_a1_quotes", {})
    added, full = [], []
    for a in adds:  # two witnesses who share a surname ('Christopher H. Smith', 'Linda Smith') are both added
        built = build_witness_persona_v6({"name": a["name"], "position": a.get("title"), "organization": a.get("org")})
        if not built or _surname(built["name"]) in have or built["name"] in names or c1_removes(cx, "personas", built["name"]) or _c2_drops_person(cx, built["name"]):
            continue
        if len(lab.get("personas") or []) >= PERSONAS_MAX:  # the schema's cap: the rest are counted, not added
            full.append(built["name"])
            continue
        p = {"name": built["name"], "title": a.get("title"), "org": a.get("org"), "role": "witness", "entity_type": built["entity_type"]}
        lab.setdefault("personas", []).append({k: v for k, v in p.items() if v})
        names.add(built["name"])
        quotes[built["name"]] = a.get("quote")
        added.append(built["name"])
    if full:
        cx.__dict__.setdefault("_flags", set()).add("A1_personas_cap")
        cx.__dict__["_a1_over_cap"] = full
    return f"witnesses from the transcript's own list: {', '.join(added)}" if added else None


def _fn_has(cx: Ctx, field: str, value: Any) -> bool:
    """The value is spelled in the filename (signal attribution only): a name ('Møse' as 'Moese'), a date
    ('19032025', '231020-'), a Congress number."""
    fn = cx.fn
    if field == "personas":
        fold = {"ø": "oe", "æ": "ae", "å": "aa", "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
        toks = set(_raw_tokens(camel_split(fn)))
        return any(_tok_norm(t) in toks or "".join(fold.get(ch, ch) for ch in t.lower()) in toks
                   for t in str(value).split() if len(t) >= 3)
    if field in G1_DATE_FIELDS:
        y, m, d = str(value)[:4], str(value)[5:7], str(value)[8:10]
        return _date_in(str(value), _fn_dates(fn)) or bool(re.search(rf"(?<!\d)(?:{d}{m}{y}|{m}{d}{y}|{y[2:]}{m}{d})(?!\d)", fn))
    return bool(re.search(rf"(?<!\d){re.escape(str(value))}(?!\d)", fn))


def c1_coordinator_adjudications(lab: dict[str, Any], cx: Ctx) -> str | None:
    """The coordinator's reading of rows no text rule can judge or that stayed disputed (2026-11-18): each line
    removes one value the text does not give: `remove_person` (a person by name), `remove` (a scalar field),
    `remove_item` (one value out of a list field such as `subcommittees` or `refs`). A line whose value is no longer
    in the label (a text rule already removed it) changes nothing. Signal source: `filename` when the filename spells
    the value, else `none`."""
    notes = []
    seen = cx.__dict__.setdefault("_c1", [])
    for a in _by_key(ADJUDICATIONS).get(cx.lk, []):
        field, value, act = a["field"], a["value"], a["action"]
        src = ["filename" if _fn_has(cx, field, value) else "none"]
        hit = False
        if act == "remove_person":
            ps_c1 = lab.get("personas") or []
            if any(p.get("name") == value and not _c2_keeps_person_name(cx, ps_c1, i) for i, p in enumerate(ps_c1)):
                lab["personas"] = [p for i, p in enumerate(ps_c1) if p.get("name") != value or _c2_keeps_person_name(cx, ps_c1, i)]
                _signal(cx, lab, "C1", "personas.name", value, persona=value, sources=src)
                hit = True
        elif act == "remove":
            if lab.get(field) == value and not _c2_keeps_scalar(cx, field, value):
                del lab[field]
                _signal(cx, lab, "C1", field, value, sources=src)
                hit = True
        elif act == "remove_item":
            if value in (lab.get(field) or []) and not _c2_keeps_item(cx, field, value):
                lab[field] = [v for v in lab[field] if v != value]
                _signal(cx, lab, "C1", field, value, sources=src)
                hit = True
        else:
            raise ValueError(f"C1: unknown action {act!r} for {cx.lk}")
        seen.append({"link_key_hex": cx.lk, "action": act, "field": field, "value": value, "applied": hit})
        if hit:
            notes.append(f"{field} -{value!r}")
    return "; ".join(notes) if notes else None


def _c2_emit_signal(cx: Ctx, lab: dict[str, Any], sig_field: str, val: Any, persona: str | None = None, kept_as: Any = None) -> None:
    if isinstance(val, bool):
        srcs = ["none"]
    elif sig_field == "personas.name":
        srcs = g1_sources("personas.name", str(val), cx, lab)
    elif sig_field.startswith("personas."):
        srcs = g1_sources("p." + sig_field.split(".", 1)[1], str(val), cx, lab)
    elif sig_field == "congress":
        srcs = g1_sources("congress", int(val), cx, lab)
    else:
        srcs = g1_sources(sig_field, str(val), cx, lab)
    _signal(cx, lab, "C2", sig_field, val, persona=persona, kept_as=kept_as, sources=srcs)


def _c2_try_one(
    lab: dict[str, Any], r: dict[str, Any]
) -> tuple[dict[str, Any], str, str | None, list[tuple[str, Any, Any]], list[tuple[str, Any, str | None, Any]]]:
    """Apply one active second-opinion ruling to a copy of `lab`.
    Returns `(new_lab, status, reason, chg_items, sig_items)`."""
    field = r["field"]
    fv = r["final_value"]
    fr = r.get("first_reviewer") or {}
    lv = fr.get("label_value")
    fr_type = fr.get("type")
    cand = copy.deepcopy(lab)
    chg: list[tuple[str, Any, Any]] = []
    sig: list[tuple[str, Any, str | None, Any]] = []

    # 1. Whole-person or personas list
    if field == "personas" or re.fullmatch(r"personas\[\d+\]", field):
        ps = list(cand.get("personas") or [])
        if field == "personas" and isinstance(fv, list):
            want = [{pk: p[pk] for pk in PERSONA_ORDER if pk in p and p[pk] is not None and p[pk] != [] and p[pk] != ""} for p in fv]
            if ps == want:
                return lab, "already_true", None, [], []
            used_b: set[int] = set()
            for pa in want:
                sa = _c2_surname(pa.get("name"))
                hit_i = next((i for i, pb in enumerate(ps) if i not in used_b and (pb.get("name") == pa.get("name") or (sa and _c2_surname(pb.get("name")) == sa))), None)
                if hit_i is None:
                    chg.append(("personas[+]", None, pa))
                else:
                    used_b.add(hit_i)
                    pb = ps[hit_i]
                    for pk in PERSONA_ORDER:
                        pb_v, pa_v = pb.get(pk), pa.get(pk)
                        if pb_v != pa_v:
                            chg.append((f"personas[{hit_i}].{pk}", pb_v, pa_v))
                            if isinstance(pb_v, list):
                                pa_list = pa_v if isinstance(pa_v, list) else []
                                for item in pb_v:
                                    if item not in pa_list:
                                        sig.append((f"personas.{pk}", item, pb.get("name"), None))
                            elif pb_v is not None:
                                sig.append((f"personas.{pk}", pb_v, pb.get("name"), pa_v))
            for i, pb in enumerate(ps):
                if i not in used_b:
                    chg.append((f"personas[{i}]", pb, None))
                    sig.append(("personas.name", pb.get("name"), pb.get("name"), None))
            cand["personas"] = want
        elif fv is None:
            targets = lv if isinstance(lv, list) else ([lv] if lv is not None else [])
            if not targets:
                if field != "personas":
                    return lab, "not_applied", f"no removal target for indexed field {field}", [], []
                if not ps:
                    return lab, "already_true", None, [], []
                for i, pb in enumerate(ps):
                    chg.append((f"personas[{i}]", pb, None))
                    sig.append(("personas.name", pb.get("name"), pb.get("name"), None))
                cand.pop("personas", None)
            else:
                drop_indices: set[int] = set()
                for t in targets:
                    t_name = t.get("name") if isinstance(t, dict) else str(t)
                    exact = [i for i, p in enumerate(ps) if i not in drop_indices and p.get("name") == t_name]
                    if len(exact) == 1:
                        drop_indices.add(exact[0])
                    elif len(exact) > 1:
                        return lab, "not_applied", f"multiple people matched name {t_name!r} for removal", [], []
                if not drop_indices:
                    return lab, "already_true", None, [], []
                for i in sorted(drop_indices):
                    pb = ps[i]
                    chg.append((f"personas[{i}]", pb, None))
                    sig.append(("personas.name", pb.get("name"), pb.get("name"), None))
                cand["personas"] = [p for i, p in enumerate(ps) if i not in drop_indices]
        elif isinstance(fv, dict):
            want_p = {pk: fv[pk] for pk in PERSONA_ORDER if pk in fv and fv[pk] is not None and fv[pk] != [] and fv[pk] != ""}
            sur = _c2_surname(want_p.get("name"))
            by_sur = [i for i, p in enumerate(ps) if sur and _c2_surname(p.get("name")) == sur]
            if not by_sur:
                if len(ps) >= PERSONAS_MAX:
                    return lab, "not_applied", f"personas at schema cap ({PERSONAS_MAX})", [], []
                ps.append(want_p)
                cand["personas"] = ps
                chg.append(("personas[+]", None, want_p))
            elif len(by_sur) == 1:
                idx = by_sur[0]
                if ps[idx] == want_p:
                    return lab, "already_true", None, [], []
                if isinstance(lv, dict) and _c2_surname(lv.get("name")) == sur:
                    pb = ps[idx]
                    ps[idx] = want_p
                    cand["personas"] = ps
                    for pk in PERSONA_ORDER:
                        pb_v, wp_v = pb.get(pk), want_p.get(pk)
                        if pb_v != wp_v:
                            chg.append((f"personas[{idx}].{pk}", pb_v, wp_v))
                            if isinstance(pb_v, list):
                                wp_list = wp_v if isinstance(wp_v, list) else []
                                for item in pb_v:
                                    if item not in wp_list:
                                        sig.append((f"personas.{pk}", item, pb.get("name"), None))
                            elif pb_v is not None:
                                sig.append((f"personas.{pk}", pb_v, pb.get("name"), wp_v))
                else:
                    return lab, "not_applied", f"label_value surname does not match {sur!r}", [], []
            else:
                return lab, "not_applied", f"multiple people matched surname {sur!r}", [], []
        else:
            return lab, "not_applied", f"unsupported whole-person final_value {type(fv).__name__}", [], []

    # 2. Person subfield: personas[i].<sub_field> or personas[i].education[j]
    elif (m_pf := re.fullmatch(r"personas\[\d+\]\.([a-z_]+)(?:\[(\d+)\])?", field)):
        sub_f, sub_idx = m_pf.group(1), m_pf.group(2)
        ps = list(cand.get("personas") or [])
        if not ps:
            return lab, "not_applied", "label has no personas", [], []
        idx, err_m = _c2_match_person_idx(ps, r, sub_f)
        if idx is None:
            return lab, "not_applied", err_m, [], []
        old_p = ps[idx]
        p = dict(old_p)
        if sub_idx is not None:
            cur_list = list(p.get(sub_f) or [])
            if fv is None:
                if lv not in cur_list:
                    return lab, "already_true", None, [], []
                p[sub_f] = [x for x in cur_list if x != lv]
            else:
                if fv in cur_list and (lv is None or lv == fv or lv not in cur_list):
                    return lab, "already_true", None, [], []
                if lv in cur_list:
                    p[sub_f] = list(dict.fromkeys(fv if x == lv else x for x in cur_list))
                else:
                    return lab, "not_applied", f"item {lv!r} not found in personas.{sub_f}", [], []
            if not p.get(sub_f):
                p.pop(sub_f, None)
            chg.append((f"personas[{idx}].{sub_f}", old_p.get(sub_f), p.get(sub_f)))
            for rem in [x for x in cur_list if x not in (p.get(sub_f) or [])]:
                sig.append((f"personas.{sub_f}", rem, old_p.get("name"), fv))
        else:
            if fv is None:
                if sub_f not in p or p[sub_f] is None:
                    return lab, "already_true", None, [], []
                old_v = p.pop(sub_f, None)
                chg.append((f"personas[{idx}].{sub_f}", old_v, None))
                if isinstance(old_v, list):
                    for item in old_v:
                        sig.append((f"personas.{sub_f}", item, old_p.get("name"), None))
                else:
                    sig.append((f"personas.{sub_f}", old_v, old_p.get("name"), None))
            else:
                if p.get(sub_f) == fv:
                    return lab, "already_true", None, [], []
                old_v = p.get(sub_f)
                p[sub_f] = fv
                chg.append((f"personas[{idx}].{sub_f}", old_v, fv))
                if isinstance(old_v, list):
                    fv_list = fv if isinstance(fv, list) else []
                    for item in old_v:
                        if item not in fv_list:
                            sig.append((f"personas.{sub_f}", item, old_p.get("name"), None))
                elif old_v is not None:
                    sig.append((f"personas.{sub_f}", old_v, old_p.get("name"), fv))
        ps[idx] = p
        cand["personas"] = ps

    # 3. Top-level unindexed list field
    elif field in C2_LIST_FIELDS:
        cur_list = list(cand.get(field) or [])
        if fv is None:
            if not cur_list:
                return lab, "already_true", None, [], []
            cand.pop(field, None)
        elif isinstance(fv, list):
            want_l = list(dict.fromkeys(fv))
            if cur_list == want_l:
                return lab, "already_true", None, [], []
            cand[field] = want_l
        else:
            if fv in cur_list:
                return lab, "already_true", None, [], []
            if fr_type in ("missing", "wrong_removal"):
                cand[field] = cur_list + [fv]
            else:
                return lab, "not_applied", f"scalar final_value on list field {field} with type {fr_type!r}", [], []
        new_list = list(cand.get(field) or [])
        chg.append((field, cur_list or None, new_list or None))
        kept_val = fv if not isinstance(fv, list) else None
        for rem in [x for x in cur_list if x not in new_list]:
            sig.append((field, rem, None, kept_val))

    # 4. Top-level indexed list field (e.g. refs[0], committees[1], short_titles[2])
    elif (m_lf := re.fullmatch(r"([a-z_]+)\[\d+\]", field)) and m_lf.group(1) in C2_LIST_FIELDS:
        base = m_lf.group(1)
        cur_list = list(cand.get(base) or [])
        if fv is None:
            if lv not in cur_list:
                return lab, "already_true", None, [], []
            cand[base] = [x for x in cur_list if x != lv]
        else:
            if fv in cur_list and (lv is None or lv == fv or lv not in cur_list):
                return lab, "already_true", None, [], []
            if lv in cur_list:
                cand[base] = list(dict.fromkeys(fv if x == lv else x for x in cur_list))
            elif fr_type in ("missing", "wrong_removal"):
                cand[base] = cur_list + [fv]
            else:
                return lab, "not_applied", f"item {lv!r} not found in {base}", [], []
        new_list = list(cand.get(base) or [])
        chg.append((base, cur_list or None, new_list or None))
        for rem in [x for x in cur_list if x not in new_list]:
            sig.append((base, rem, None, fv))

    # 5. Nested disclosure field
    elif field.startswith("disclosure."):
        sub_f = field.split(".", 1)[1]
        if not isinstance(cand.get("disclosure"), dict):
            return lab, "not_applied", "label has no disclosure object", [], []
        old_d = dict(cand["disclosure"])
        d = dict(old_d)
        if fv is None:
            if sub_f not in d or d[sub_f] is None:
                return lab, "already_true", None, [], []
            old_v = d.pop(sub_f, None)
            chg.append((field, old_v, None))
            if isinstance(old_v, list):
                for item in old_v:
                    sig.append((field, item, None, None))
            else:
                sig.append((field, old_v, None, None))
        else:
            old_dv = d.get(sub_f)
            if old_dv == fv:
                return lab, "already_true", None, [], []
            chg.append((field, old_dv, fv))
            d[sub_f] = fv
            if old_dv is not None:
                sig.append((field, old_dv, None, fv))
        cand["disclosure"] = d

    # 6. Top-level scalar field
    elif field in TOP_ORDER:
        old_v = cand.get(field)
        if fv is None:
            if field not in cand or cand[field] is None:
                return lab, "already_true", None, [], []
            cand.pop(field, None)
            chg.append((field, old_v, None))
            sig.append((field, old_v, None, None))
        else:
            if old_v == fv:
                return lab, "already_true", None, [], []
            cand[field] = fv
            chg.append((field, old_v, fv))
            if old_v is not None:
                sig.append((field, old_v, None, fv))
            if field == "status" and fv != "usable":
                for k_drop in ("primary_kind", "secondary_kinds", "subkind"):
                    if k_drop in cand:
                        val_drop = cand.pop(k_drop)
                        chg.append((k_drop, val_drop, None))
                        if isinstance(val_drop, list):
                            for item_drop in val_drop:
                                sig.append((k_drop, item_drop, None, None))
                        elif val_drop is not None:
                            sig.append((k_drop, val_drop, None, None))
    else:
        return lab, "not_applied", f"unsupported field {field!r}", [], []

    cand = canon(cand)
    err = validate(cand)
    if err:
        return lab, "not_applied", err, [], []
    if cand == canon(lab):
        return lab, "already_true", None, [], []
    return cand, "applied", None, chg, sig


def c2_second_opinion_rulings(lab: dict[str, Any], cx: Ctx) -> str | None:
    """Apply every `apply` and `modify` line from `second_opinion_rulings.jsonl` (never `reject`), last before
    validation. Each changed label is validated; an invalid result is left unapplied and recorded as `not_applied`."""
    rulings = _by_key(SECOND_OPINION).get(cx.lk)
    if not rulings:
        return None
    seen = cx.__dict__.setdefault("_c2", [])
    all_chg = cx.__dict__.setdefault("_c2_changes", [])
    notes: list[str] = []
    cur = canon(lab)
    held = _held_c2_rulings()
    for r in rulings:
        if r["ruling"] == "reject":
            seen.append({"n": r["n"], "status": "rejected_by_ruling", "reason": None})
            continue
        held_reason = held.get((cx.lk, int(r["n"])))
        if held_reason is not None:
            seen.append({"n": r["n"], "status": "held_for_owner", "reason": held_reason})
            continue
        new_lab, st, reason, chg, sig = _c2_try_one(cur, r)
        seen.append({"n": r["n"], "status": st, "reason": reason})
        if st == "applied":
            for sig_f, val, pers, kept_as in sig:
                _c2_emit_signal(cx, cur, sig_f, val, persona=pers, kept_as=kept_as)
            for cf, b_val, a_val in chg:
                all_chg.append((cf, b_val, a_val, r.get("quote")))
            cur = new_lab
            notes.append(f"{r['field']} -> {r['final_value']!r}")
    if notes:
        lab.clear()
        lab.update(cur)
        return "; ".join(notes)
    return None


DATA_RULES: list[tuple[str, Callable[[dict[str, Any], Ctx], str | None]]] = [
    ("A1", a1_transcript_witnesses), ("C1", c1_coordinator_adjudications), ("C2", c2_second_opinion_rulings),
]

LABEL_RULES: list[tuple[str, Callable[[dict[str, Any], Ctx], str | None]]] = [
    ("K1", k1_jct_description), ("K2", k2_statement_for_record), ("K3", k3_rules_committee_print),
    ("K4", k4_treaty), ("K5", k5_special_rule_report), ("K6", k6_agenda_sheet),
    ("K7", k7_committee_action_release), ("K8", k8_member_remarks_page), ("K9", k9_testify_invitation),
    ("K10", k10_legal_exhibit), ("K11", k11_property_resolution), ("K12", k12_placeholder),
    ("K13", k13_single_doc),
    ("F1", f1_names), ("F2", f2_grid_people), ("F3", f3_letter_roles), ("F4", f4_flow_scope),
    ("F6", f6_ref_grounding), ("F7", f7_subcommittee_spelling),
    ("F8", f8_ref_prefix), ("F10", f10_nonusable_kind), ("G1", g1_text_only), ("F5", f5_dates),
]
# A1 runs before F1 so the text rules hold its additions to the same standard as every other person (and a rerun
# finds them already settled); C1 runs last.
ALL_RULES = [r for r in LABEL_RULES if r[0].startswith("K")] + DATA_RULES[:1] + [r for r in LABEL_RULES if not r[0].startswith("K")] + DATA_RULES[1:]
ENABLED: set[str] = {"X1", "X2", "X3", "X4"} | {rid for rid, _ in ALL_RULES}


# --------------------------------------------------------------------------------------------------------------
# Diffing, validation, driver
# --------------------------------------------------------------------------------------------------------------
def diff_values(before: dict[str, Any], after: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    out: list[tuple[str, Any, Any]] = []
    for k in [k for k in TOP_ORDER if k in before or k in after]:
        b, a = before.get(k), after.get(k)
        if b == a:
            continue
        if k == "personas" and isinstance(b, list) and isinstance(a, list):
            out.extend(_diff_personas(b, a))
            continue
        out.append((k, b, a))
    return out


def _diff_personas(b: list[dict[str, Any]], a: list[dict[str, Any]]) -> list[tuple[str, Any, Any]]:
    """Align personas before/after (rules only rename by dropping tokens, change roles, or remove people), then
    report per-field changes as personas[i].field (i = index before) and removals as personas[i]."""
    def rest(p: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in p.items() if k not in ("name", "role")}

    def toks(n: Any) -> list[str]:
        return [_tok_norm(t) for t in str(n or "").split()]

    used: set[int] = set()
    out: list[tuple[str, Any, Any]] = []
    for pa in a:
        hit = None
        for i, pb in enumerate(b):
            if i in used or rest(pa) != rest(pb):
                continue
            if pa.get("name") == pb.get("name") or all(t in toks(pb.get("name")) for t in toks(pa.get("name"))):
                hit = i
                break
        if hit is None:
            out.append(("personas[+]", None, pa))
            continue
        used.add(hit)
        for pk in PERSONA_ORDER:
            if b[hit].get(pk) != pa.get(pk):
                out.append((f"personas[{hit}].{pk}", b[hit].get(pk), pa.get(pk)))
    for i, pb in enumerate(b):
        if i not in used:
            out.append((f"personas[{i}]", pb, None))
    return out


def validate(lab: dict[str, Any]) -> str | None:
    from congress_docmeta import strict_validate_v4
    from congress_docmeta.compact_wire_v6 import (
        OMITTED_DETERMINISTIC_V4_KEYS,
        encode_v4_to_compact_v6,
        expand_compact_json_str_to_v4,
    )

    ok, err = strict_validate_v4(lab)
    if not ok:
        return f"strict_validate_v4: {err}"
    rt, err2 = expand_compact_json_str_to_v4(json.dumps(encode_v4_to_compact_v6(lab), separators=(",", ":"), ensure_ascii=False))
    want = {k: v for k, v in lab.items() if k not in OMITTED_DETERMINISTIC_V4_KEYS}
    if rt != want or list(rt) != list(want):
        return f"compact round trip changed the label ({err2}): {sorted(set(map(str, rt.items())) ^ set(map(str, want.items())))[:3]}"
    return None


def apply_label_rules(lab0: dict[str, Any], cx: Ctx, trace: dict[str, dict[str, Any]] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply the label rules in order. `trace`, when given, receives each rule's input label (rule_dependencies)."""
    lab = copy.deepcopy(lab0)
    events: list[dict[str, Any]] = []
    cx.__dict__["_signal"] = []
    cx.__dict__["_c2"] = []
    cx.__dict__["_c2_changes"] = []
    cx.__dict__["_flags"] = set()
    cx.__dict__.pop("_k1_protect", None)
    rules = ALL_RULES
    if unreadable(cx):  # an unreadable text layer: no text rule judges it; the coordinator's reading (C1) does
        cx.__dict__["_flags"].add("unreadable_text")
        rules = DATA_RULES
    for rid, fn in rules:
        if rid not in ENABLED:
            continue
        before = copy.deepcopy(lab)
        if trace is not None:
            trace[rid] = copy.deepcopy(lab)
        ev = fn(lab, cx)
        lab = canon(lab)
        if ev is None:
            if lab != canon(before):
                raise AssertionError(f"{rid} changed {cx.lk} without reporting it")
            continue
        changes = [(f_, b_, a_) for f_, b_, a_, _ in cx.__dict__.get("_c2_changes", [])] if rid == "C2" else diff_values(canon(before), lab)
        if changes:
            events.append({"rule": rid, "evidence": ev, "changes": changes})
    return lab, events


def load_rows(in_paths: dict[str, Path]) -> list[tuple[str, dict[str, Any]]]:
    rows = []
    for s in SETS:
        for line in in_paths[s].open(encoding="utf-8"):
            if line.strip():
                rows.append((s, json.loads(line)))
    return rows


G1_MEASURE_FIELDS = ("congress", "chamber") + G1_DATE_FIELDS + G1_STRING_FIELDS


def _g1_values(lab: dict[str, Any]):
    for f in G1_MEASURE_FIELDS:
        if lab.get(f) is not None:
            yield f, lab[f]
    for f in ("committees", "subcommittees", "date_spans") + G1_LIST_FIELDS:
        for v in lab.get(f) or []:
            yield f, v
    for p in lab.get("personas") or []:
        for f in G1_PERSONA_FIELDS:
            if p.get(f):
                yield "p." + f, p[f]
    for v in lab.get("refs") or []:
        yield "refs", v


def measure_g1(rows: dict[str, tuple[dict[str, Any], "Ctx"]]) -> dict[str, Any]:
    """Per field, on the labels as they come in: stated in text / reviewer window only / only in known / only in
    filename / derived from a stated date / none (each value counted once, first source in SOURCE_ORDER), overall
    and for the five largest kinds. Non-Latin rows (left as labeled) are counted apart."""
    cats = ("text",) + SOURCE_ORDER
    tab: dict[str, Counter[str]] = defaultdict(Counter)
    by_kind: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    kinds = Counter((lab.get("primary_kind") or "status:" + lab.get("status", "")) for lab, _ in rows.values())
    big = [k for k, _ in kinds.most_common(5)]
    non_latin = 0
    for lk in sorted(rows):
        lab, cx = rows[lk]
        if lab.get("status", "usable") in HARD_ERROR_STATUSES:
            continue
        if _non_latin_share(cx.text) > 0.2:
            non_latin += 1
            continue
        f = facts(cx)
        k = lab.get("primary_kind") or "status:" + lab.get("status", "")
        for field, v in _g1_values(lab):
            if g1_value_stated(field, v, f, lab):
                cat = "text"
            else:
                srcs = g1_sources(field, v, cx, lab)
                cat = next(x for x in SOURCE_ORDER if x in srcs)
            tab[field][cat] += 1
            if k in big:
                by_kind[k][field][cat] += 1
    return {"categories": list(cats), "non_latin_rows_left_as_labeled": non_latin,
            "by_field": {f: {c: tab[f][c] for c in cats} for f in tab},
            "by_kind": {k: {f: {c: v[c] for c in cats} for f, v in d.items()} for k, d in by_kind.items()}}


# What each rule reads besides the training text and the label (for rule_dependencies.json).
RULE_READS = {
    "X1": ["production queue membership"], "X2": ["L3 drop list (link keys)"], "X3": ["L3 re-post pairs (link keys)"],
    "X4": ["production queue membership", "known string (format only)"], "K13": ["hand-read link-key list"],
    "F7": ["subcommittee roster spelling", "gold majority spelling"], "G1": ["known / filename / reviewer window for signal attribution only"],
    "F1": [], "F6": [],
    "A1": ["transcript_witness_additions.jsonl: a reviewed, machine-verified data file keyed by link key (not the filename or the hint)"],
    "C1": ["coordinator_adjudications.jsonl: the coordinator's reading, keyed by link key (not the filename or the hint; the filename only labels the signal source)"],
    "C2": ["second_opinion_rulings.jsonl: two-reviewer second-opinion rulings with machine-verified quotes, keyed by link key (not the filename or the hint)"],
}


def rule_dependency_row(deps: dict[str, Counter[str]], trace: dict[str, dict[str, Any]], cx: "Ctx",
                        c: dict[str, Any]) -> None:
    """Re-run every rule on its own input with the filename, `known` and reviewer window blanked: a different result
    means the rule's answer on this row depends on something other than the text."""
    blind = Ctx(cx.set_name, cx.raw, {**c, "known": "", "filename": "", "alt_text": ""})
    for rid, fn in ALL_RULES:
        if rid not in trace:
            continue
        a, b = copy.deepcopy(trace[rid]), copy.deepcopy(trace[rid])
        cx.__dict__["_signal"] = []
        blind.__dict__["_signal"] = []
        if rid == "G1":
            for o in (cx, blind):
                o.__dict__["_k1_protect"] = "K1" in trace and k1_jct_description(copy.deepcopy(trace["K1"]), o) is not None
        ra, rb = fn(a, cx), fn(b, blind)
        deps[rid]["rows"] += int(ra is not None)
        if canon(a) != canon(b):
            deps[rid]["rows_answer_differs_without_filename_known_window"] += 1


def rule_dependencies_report(deps: dict[str, Counter[str]], rule_rows: dict[str, set[str]]) -> dict[str, Any]:
    out = {}
    for rid in ["X1", "X2", "X3", "X4"] + [r for r, _ in ALL_RULES]:
        d = deps.get(rid, Counter())
        out[rid] = {
            "reads_besides_text_and_label": RULE_READS.get(rid, []),
            "rows_changed": len(rule_rows.get(rid, ())),
            "rows_whose_answer_changes_with_filename_known_window_blanked": d.get("rows_answer_differs_without_filename_known_window", 0),
            "text_alone_gives_same_answer": d.get("rows_answer_differs_without_filename_known_window", 0) == 0 and not RULE_READS.get(rid),
        }
    return out


def main() -> int:
    global SUBCMTE, CMTNAMES, ENABLED
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=N_DIR / "lookups_and_gold")
    ap.add_argument("--inputs-from-outputs", action="store_true", help="read the three output sets (idempotence check)")
    ap.add_argument("--in-dir", type=Path, default=None, help="with --inputs-from-outputs: where the outputs are")
    ap.add_argument("--rules", default="", help="comma list of rule ids to run (default: all)")
    ap.add_argument("--no-c2", action="store_true", help="skip rule C2 (pre-Stage-3 baseline mode)")
    args = ap.parse_args()
    if args.rules:
        ENABLED = set(args.rules.split(","))
    if args.no_c2:
        ENABLED.discard("C2")

    in_paths = dict(IN_PATHS)
    if args.inputs_from_outputs:
        src = args.in_dir or (N_DIR / "lookups_and_gold")
        in_paths = {s: src / OUT_NAMES[s] for s in SETS}
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    held = set(json.loads(HELDOUT_KEYS.read_text())["link_key_hex"])
    ctx_all = load_contexts(in_paths)
    rows = load_rows(in_paths)
    cxs = {r["link_key_hex"]: Ctx(s, r, ctx_all[r["link_key_hex"]]) for s, r in rows}
    labels0 = {r["link_key_hex"]: json.loads(r["messages"][-1]["content"]) for _, r in rows}
    SUBCMTE = SubcommitteeCanon(list(labels0.values()))
    CMTNAMES = CommitteeNames([(labels0[lk], cxs[lk]) for lk in labels0])  # signal attribution only
    R = json.loads((A_DIR / "lookups_and_gold" / "rosters_lookup_v6.json").read_text())
    ROSTER_SUBNAMES.update({k: v["name"] for k, v in R["subcommittees_meta"].items() if v.get("name")})
    g1_measure = measure_g1({lk: (labels0[lk], cxs[lk]) for lk in labels0})

    # ---- row level
    excluded: list[dict[str, Any]] = []
    changelog: list[dict[str, Any]] = []
    rule_rows: dict[str, set[str]] = defaultdict(set)
    rule_vals: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sets_by_lk = {r["link_key_hex"]: s for s, r in rows}
    texts = {lk: cx.text for lk, cx in cxs.items()}

    def log(lk: str, s: str, rid: str, field: str, before: Any, after: Any, quote: str | None = None) -> None:
        changelog.append({"link_key_hex": lk, "set": s, "rule": rid, "field": field, "before": before, "after": after,
                          **({"quote": quote} if quote else {})})
        rule_rows[rid].add(lk)
        rule_vals[rid] += 1

    def exclude(s: str, r: dict[str, Any], rid: str, reason: str) -> None:
        excluded.append({**r, "excluded_from_set": s, "excluded_rule": rid, "excluded_reason": reason})
        log(r["link_key_hex"], s, rid, "row", "present", "excluded")
        examples[rid].append({"lk": r["link_key_hex"], "fn": cxs[r["link_key_hex"]].fn, "evidence": reason})

    x3_test = {t: tr for t, tr in X3_REPOSTS}
    kept: list[tuple[str, dict[str, Any]]] = []
    for s, r in rows:
        lk = r["link_key_hex"]
        cx = cxs[lk]
        if "X1" in ENABLED and not cx.in_queue and cx.text.strip() == "[EMPTY_BODY]":
            exclude(s, r, "X1", "text is the literal [EMPTY_BODY] placeholder; no production queue row (production never sends an empty text)")
            continue
        if "X2" in ENABLED and s == "gapfill_train" and lk in X2_DROP_GAPFILL_TRAIN:
            exclude(s, r, "X2", "L3 drop list: sibling or re-post of a held-out doc (sampler mined held-out clusters)")
            continue
        if "X3" in ENABLED and s == "gapfill_test" and lk in x3_test:
            tr = x3_test[lk]
            if tr not in texts:
                raise AssertionError(f"X3 training copy {tr} missing for {lk}")
            j = jaccard(cx.text, texts[tr])
            if j < 0.5:
                raise AssertionError(f"X3 pair {lk}/{tr} re-measured at {j:.2f}")
            exclude(s, r, "X3", f"same document re-posted; training copy {tr} ({sets_by_lk[tr]}) kept; word 5-gram Jaccard {j:.2f}")
            continue
        kept.append((s, r))

    # ---- label rules and X4
    out_rows: dict[str, list[dict[str, Any]]] = {s: [] for s in SETS}
    failures: list[str] = []
    signal: list[dict[str, Any]] = []
    deps: dict[str, Counter[str]] = defaultdict(Counter)
    pending: dict[str, list[dict[str, Any]]] = defaultdict(list)
    a1_over_cap: list[dict[str, Any]] = []
    c1_lines: list[dict[str, Any]] = []
    c2_seen: dict[tuple[str, int], tuple[str, str | None]] = {}
    for s, r in kept:
        lk = r["link_key_hex"]
        cx = cxs[lk]
        r2 = copy.deepcopy(r)
        if "X4" in ENABLED and not cx.in_queue:
            u2, b, a = x4_rewrite_known(r2["messages"][0]["content"])
            if b is not None:
                r2["messages"][0]["content"] = u2
                log(lk, s, "X4", "messages[0].known", b, a)
                if len(examples["X4"]) < 5:
                    examples["X4"].append({"lk": lk, "fn": cx.fn, "evidence": f"{b}  ->  {a}"})
        lab0 = labels0[lk]
        trace: dict[str, dict[str, Any]] = {}
        lab, events = apply_label_rules(lab0, cx, trace)
        signal.extend(cx.__dict__.get("_signal", []))
        c1_lines.extend(cx.__dict__.pop("_c1", []))
        for rec_c2 in cx.__dict__.get("_c2", []):
            c2_seen[(lk, rec_c2["n"])] = (rec_c2["status"], rec_c2["reason"])
        c2_chgs = list(cx.__dict__.get("_c2_changes", []))
        if cx.__dict__.get("_a1_over_cap"):
            a1_over_cap.append({"link_key_hex": lk, "not_added": cx.__dict__["_a1_over_cap"]})
        for flag in sorted(cx.__dict__.get("_flags", set())):
            share, nw = cx.__dict__["_readable"]
            pending[flag].append({"link_key_hex": lk, "set": s, "primary_kind": lab0.get("primary_kind"),
                                  "filename": cx.fn, "readable_share": round(share, 3), "words": nw})
        if _non_latin_share(cx.text) > 0.2:
            pending["non_latin_text"].append({"link_key_hex": lk, "set": s, "primary_kind": lab0.get("primary_kind")})
        rule_dependency_row(deps, trace, cx, ctx_all[lk])
        for ev in events:
            if ev["rule"] == "C2":
                for field, b, a, q in c2_chgs:
                    log(lk, s, "C2", field, b, a, q)
                examples["C2"].append({"lk": lk, "fn": cx.fn, "set": s, "evidence": ev["evidence"], "changes": ev["changes"]})
                continue
            changes = ev["changes"]
            if ev["rule"] == "A1":  # one changelog line per added witness, with the words that name them
                changes = [("personas[+]", None, p) for f_, b_, a_ in changes for p in (a_ if f_ == "personas" and b_ is None else [a_])]
            for field, b, a in changes:
                q = cx.__dict__.get("_a1_quotes", {}).get(a.get("name")) if ev["rule"] == "A1" and isinstance(a, dict) else None
                log(lk, s, ev["rule"], field, b, a, q)
            examples[ev["rule"]].append({"lk": lk, "fn": cx.fn, "set": s, "evidence": ev["evidence"], "changes": ev["changes"]})
        err = validate(lab)
        if err:
            failures.append(f"{lk}: {err}")
        again, ev2 = apply_label_rules(lab, cx)
        if ev2 or again != lab:
            failures.append(f"{lk}: not idempotent: {[e['rule'] for e in ev2]}")
        content = json.dumps(lab, separators=(",", ":"), ensure_ascii=False)
        r2["messages"][-1]["content"] = content
        out_rows[s].append(r2)

    c2_applied: list[dict[str, Any]] = []
    if SECOND_OPINION.is_file() and "C2" in ENABLED:
        held_c2 = _held_c2_rulings()
        for line in SECOND_OPINION.open(encoding="utf-8"):
            if not line.strip():
                continue
            r_so = json.loads(line)
            lk_so, n_so = r_so["link_key_hex"], r_so["n"]
            if r_so["ruling"] == "reject":
                st_so, rsn_so = "rejected_by_ruling", None
            elif (lk_so, n_so) in c2_seen:
                st_so, rsn_so = c2_seen[(lk_so, n_so)]
            elif (lk_so, int(n_so)) in held_c2:
                st_so, rsn_so = "held_for_owner", held_c2[(lk_so, int(n_so))]
            else:
                st_so, rsn_so = "not_applied", "row excluded or not in input sets"
            c2_applied.append({
                "link_key_hex": lk_so,
                "n": n_so,
                "ruling": r_so["ruling"],
                "field": r_so["field"],
                "final_value": r_so["final_value"],
                "status": st_so,
                **({"reason": rsn_so} if rsn_so is not None else {}),
            })

    # ---- write
    for s in SETS:
        with (out_dir / OUT_NAMES[s]).open("w", encoding="utf-8") as f:
            for r in out_rows[s]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (out_dir / OUT_NAMES["excluded"]).open("w", encoding="utf-8") as f:
        for r in excluded:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (out_dir / OUT_NAMES["changelog"]).open("w", encoding="utf-8") as f:
        for c in changelog:
            f.write(json.dumps(c, ensure_ascii=False, default=str) + "\n")
    with (out_dir / OUT_NAMES["signal"]).open("w", encoding="utf-8") as f:
        for rec in signal:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    with (out_dir / OUT_NAMES["second_opinion"]).open("w", encoding="utf-8") as f:
        for rec in c2_applied:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    (out_dir / OUT_NAMES["pending"]).write_text(json.dumps({
        "about": "Rows held for the owner (coordinator rulings 2026-11-18): a Member's own statement for the record "
                 "left as labeled (K2); pages both marked 'Press Release' and titled 'Opening Statement' (K8: the title "
                 "wins). Shifted-letter and non-Latin texts are no longer pending: the coordinator read them (C1), and "
                 "normalize_summary.json lists them under read_by_coordinator.",
        **{k: pending.get(k, []) for k in ("K2_member_statement", "K8_both_marks")},
    }, indent=1, ensure_ascii=False) + "\n")
    (out_dir / OUT_NAMES["dependencies"]).write_text(
        json.dumps(rule_dependencies_report(deps, rule_rows), indent=1, ensure_ascii=False) + "\n")

    n_in = Counter(s for s, _ in rows)
    n_out = {s: len(out_rows[s]) for s in SETS}
    n_exc = Counter(e["excluded_from_set"] for e in excluded)
    all_out = [r["link_key_hex"] for s in SETS for r in out_rows[s]]
    held_kept = sorted(held & set(all_out))
    held_exc = [{"link_key_hex": e["link_key_hex"], "rule": e["excluded_rule"], "reason": e["excluded_reason"]}
                for e in excluded if e["link_key_hex"] in held]
    summary = {
        "generated_by": "normalize_gold_v6_5.py",
        "inputs": {s: {"path": str(in_paths[s]), "rows": n_in[s],
                       "sha256": hashlib.sha256(in_paths[s].read_bytes()).hexdigest()} for s in SETS},
        "outputs": {s: {"file": OUT_NAMES[s], "rows": n_out[s]} for s in SETS},
        "excluded": {"file": OUT_NAMES["excluded"], "rows": len(excluded), "by_set": dict(n_exc)},
        "counts_add_up": all(n_in[s] == n_out[s] + n_exc.get(s, 0) for s in SETS),
        "duplicate_link_keys_across_outputs": len(all_out) - len(set(all_out)),
        "heldout": {"listed": len(held), "present_in_old_output": len(held & {r['link_key_hex'] for r in out_rows['old']}),
                    "excluded": held_exc},
        "rules_enabled": sorted(ENABLED, key=lambda x: (x[0], int(x[1:]))),
        "per_rule": {rid: {"rows_touched": len(rule_rows.get(rid, ())), "values_changed": rule_vals.get(rid, 0)}
                     for rid in ["X1", "X2", "X3", "X4"] + [r for r, _ in ALL_RULES]},
        "validation_failures": failures,
        "signal": {"file": OUT_NAMES["signal"], "rows": len(signal),
                   "by_rule_field": {f"{k[0]}|{k[1]}": v for k, v in sorted(Counter((x["rule"], x["field"]) for x in signal).items())},
                   "by_source": dict(Counter(x["source"] for x in signal))},
        "g1_measure_on_inputs": g1_measure,
        "read_by_coordinator": {
            "about": "Text no rule can read (shifted-letter layer: readable share < %s; mostly non-Latin): the text rules "
                     "leave these labels as reviewed, the coordinator read them against the text, and C1 applies that "
                     "reading (coordinator_adjudications.jsonl)." % UNREADABLE_SHARE,
            "shifted_letter_text": [x["link_key_hex"] for x in pending.get("unreadable_text", [])],
            "non_latin_text": [x["link_key_hex"] for x in pending.get("non_latin_text", [])]},
        "data_files": {"A1": {"path": str(WITNESS_ADDITIONS), "present": WITNESS_ADDITIONS.is_file(),
                              "rows_listed": sum(map(len, _by_key(WITNESS_ADDITIONS).values())),
                              "not_added_schema_cap": a1_over_cap},
                       "C1": {"path": str(ADJUDICATIONS), "present": ADJUDICATIONS.is_file(),
                              "lines": sum(map(len, _by_key(ADJUDICATIONS).values())),
                              "applied": sum(x["applied"] for x in c1_lines),
                              "not_matched": [x for x in c1_lines if not x["applied"]]},
                       "C2": {"path": str(SECOND_OPINION), "present": SECOND_OPINION.is_file(),
                              "lines": len(c2_applied),
                              "by_status": dict(Counter(x["status"] for x in c2_applied)),
                              "not_applied": [x for x in c2_applied if x["status"] == "not_applied"]}},
    }
    notes_path = VERIFY_NOTES
    notes = json.loads(notes_path.read_text()) if notes_path.is_file() else {}
    for rid, d in summary["per_rule"].items():
        d.update(notes.get("auditor_counts", {}).get(rid, {}))
        d.update(notes.get("verified", {}).get(rid, {}))
    (out_dir / OUT_NAMES["summary"]).write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str) + "\n")
    write_review(out_dir / OUT_NAMES["review"], summary, examples, cxs, notes)
    (out_dir / "_scratch_c2").mkdir(parents=True, exist_ok=True)
    with (out_dir / "_scratch_c2" / "examples_all.json").open("w") as f:
        json.dump(examples, f, ensure_ascii=False, default=str)
    print(json.dumps({k: summary[k] for k in ("outputs", "excluded", "counts_add_up", "duplicate_link_keys_across_outputs")}, default=str))
    print({rid: (d["rows_touched"], d["values_changed"]) for rid, d in summary["per_rule"].items()})
    print("validation failures:", len(failures), failures[:5])
    return 1 if failures else 0


def write_review(path: Path, summary: dict[str, Any], examples: dict[str, list[dict[str, Any]]],
                 cxs: dict[str, Ctx], notes: dict[str, Any]) -> None:
    L: list[str] = []
    L.append("# Normalisation pass over the DocMeta gold: review (generated by normalize_gold_v6_5.py)\n")
    L.extend(notes.get("preamble", []))
    L.append("\n## Rule table\n")
    L.append("| Rule | Rows touched | Values changed | Auditor's count | Verified correct (read) |")
    L.append("|---|---|---|---|---|")
    for rid, d in summary["per_rule"].items():
        L.append(f"| {rid} | {d['rows_touched']} | {d['values_changed']} | {d.get('auditor', '')} | {d.get('verified', '')} |")
    g = summary.get("g1_measure_on_inputs") or {}
    if g:
        cats = g["categories"]
        sig = summary["signal"]["by_rule_field"]
        L.append("\n## G1 measurement (input labels; each value counted once, first source in this order)\n")
        L.append("| Field | " + " | ".join(cats) + " | share stated | removed by G1 |")
        L.append("|---" * (len(cats) + 3) + "|")
        for f, c in g["by_field"].items():
            n = sum(c.values()) or 1
            fk = "personas." + f[2:] if f.startswith("p.") else f
            rem = sig.get(f"G1|{fk}", 0) if f != "refs" else sig.get("F6|refs", 0)
            L.append(f"| {f} | " + " | ".join(str(c[x]) for x in cats) + f" | {c['text'] / n:.0%} | {rem} |")
        L.append(f"\nRows whose text is mostly non-Latin (left as labeled): {g['non_latin_rows_left_as_labeled']}. "
                 "G1 removals of committees count names removed outright; names kept without their chamber are in "
                 "the signal file with `kept_as` (source `chamber_not_in_text`). Refs are removed by F6.\n")
        for k, d in g.get("by_kind", {}).items():
            L.append(f"- {k}: " + "; ".join(f"{f} {d[f]['text']}/{sum(d[f].values())} stated" for f in ("congress", "chamber", "committees", "doc_date", "event_date") if f in d))
    for rid, d in summary["per_rule"].items():
        L.append(f"\n## {rid}\n")
        for para in notes.get("rule_notes", {}).get(rid, []):
            L.append(para)
        ex = examples.get(rid, [])
        if not ex:
            L.append("\nNo row changed.\n")
            continue
        # five examples spread over the hit list (deterministic: evenly spaced)
        idx = sorted({round(i * (len(ex) - 1) / 4) for i in range(5)}) if len(ex) > 5 else range(len(ex))
        for i in idx:
            e = ex[i]
            L.append(f"\n- `{e['lk']}` ({e.get('set', '')}) `{e['fn'][:80]}`")
            L.append(f"  - evidence: {str(e['evidence'])[:420]}")
            for field, b, a in (e.get("changes") or [])[:6]:
                L.append(f"  - `{field}`: {json.dumps(b, ensure_ascii=False)[:160]} -> {json.dumps(a, ensure_ascii=False)[:160]}")
    L.extend(notes.get("closing", []))
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
