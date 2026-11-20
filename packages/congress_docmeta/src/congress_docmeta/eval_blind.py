#!/usr/bin/env python3
"""Blind end-to-end DocMeta eval for a packed/fused Gemma-4 checkpoint.

Runs the production `PythonicEngineV6.run_records` path (pre-pass, grammar-locked decode, post-pass)
on three held-out sets and scores the final `DocMetaV4Causal` objects against gold:

  val48        eval_val48_v4_gold.json (48 stratified blind docs), via `PythonicEngineV6.run_records`
  docs8        eval_docs8_v4_gold.json (8 stress-test docs), via `run_records`
  valid_sweep  the split `gold.select_val_indices` holds out of the V6.4 gold, via `run_docmeta_parquet_sweep`
  val48_sweep  the val48 docs present in the sweep queue, via `run_docmeta_parquet_sweep`

The `*_sweep` sets feed the model the queue rows the production sweep will feed it, through the sweep's own
code path. `--llm-only` turns the deterministic pre/post rules off for the `run_records` sets.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import time
from typing import Any, Mapping
import unicodedata

from .gold import (
    DEFAULT_DOCS8_JSON,
    DEFAULT_GOLD_JSONL,
    DEFAULT_QUEUE_PARQUET,
    DEFAULT_VAL48_JSON,
    head_tail_window_chars,
    load_queue_rows,
    parse_gold_rows,
    select_val_indices,
)

KIND_FAMILIES = {
    "qfr_request": "qfr",
    "qfr_response": "qfr",
    "witness_statement": "statement",
    "member_opening_statement": "statement",
    "member_or_floor_statement": "statement",
    "hearing_notice": "notice",
    "markup_notice": "notice",
    "committee_vote": "vote_or_results",
    "meeting_results": "vote_or_results",
    "oversight_letter": "letter_or_submission",
    "witness_invitation": "letter_or_submission",
    "nomination_or_support_letter": "letter_or_submission",
    "external_submission_letter": "letter_or_submission",
    "public_comment_or_submission": "letter_or_submission",
    "agency_or_gao_crs_report": "report",
    "external_report_or_whitepaper": "report",
    "committee_report": "report",
    "bill_or_draft": "legislative_text",
    "committee_amendment": "legislative_text",
    "comparative_print": "legislative_text",
    "section_by_section": "legislative_text",
    "explanatory_statement": "legislative_text",
    "investigative_exhibit": "investigative",
    "legal_or_investigative_filing": "investigative",
}
SCALAR_KEYS = ("status", "text_quality", "chamber", "congress", "event_type", "primary_kind", "correspondence_flow")
LIST_KEYS = ("subcommittees", "secondary_kinds", "short_titles", "refs", "fiscal_years", "topics")
DATE_KEYS = ("doc_date", "event_date", "due_date")

_CMT_STOP_RE = re.compile(
    r"\b(u\.?s\.?|united states|house|senate|committee|on|the|of|and|select|permanent|special)\b"
)
_HONORIFIC_RE = re.compile(
    r"\b(Jr\.?|Sr\.?|II|III|IV|M\.?D\.?|Ph\.?D\.?|Esq\.?|Hon\.?|Rep\.?|Sen\.?|Mr\.?|Ms\.?|Mrs\.?|Dr\.?)\b", re.I
)


def norm_cmt(c: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _CMT_STOP_RE.sub(" ", c.lower())).strip()


def surname_of(name: str) -> str:
    parts = [p for p in re.split(r"[^A-Za-z'-]+", _HONORIFIC_RE.sub("", name)) if len(p) > 1]
    return parts[-1].lower() if parts else name.lower().strip()


def _norm_str(x: Any) -> str:
    return re.sub(r"\s+", " ", str(x)).strip().lower()


def _norm_subc(name: Any) -> str:
    """Subcommittee comparison key insensitive to `&`/`and`, `the`, punctuation, and leading committee prefix."""
    flat = re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKC", str(name or "")).lower().replace("&", "and"))
    flat = re.sub(r"^.*?\b(?:select )?subcommittee (?:on|for) ", "", f" {flat} ").strip()
    return " ".join(re.sub(r"\b(?:the|and)\b", " ", flat).split())


_PARTY_STATE_RE = re.compile(r"\(\s*[DRI]\s*[-–]\s*[A-Z]{2}(?:\s*[-–]\s*(?:\d{1,2}|AL|At\s+Large))?\s*\)", re.I)
_TRAILING_TITLE_RE = re.compile(
    r",\s*(?:(?:Subcommittee\s+|Full\s+Committee\s+|Acting\s+|Vice\s+|Co-?)?"
    r"(?:Chair(?:man|woman|person)?|Ranking\s+(?:Minority\s+)?Member|Member|Senator|Representative|"
    r"Director|Secretary|President|Commissioner|Administrator|Counsel|Chief|CEO)\b.*)$",
    re.I,
)
_HONORIFIC_EXT_RE = re.compile(
    r"\b(?:The\s+Honorable|Honorable|Hon\.?|Rep\.?|Representative|Sen\.?|Senator|Congressman|Congresswoman|"
    r"Chairman|Chairwoman|Chair|Mr\.?|Ms\.?|Mrs\.?|Miss|Dr\.?|Prof\.?|Professor|Amb\.?|Ambassador|"
    r"Gen\.?|General|Adm\.?|Admiral|Col\.?|Colonel|Jr\.?|Sr\.?|II|III|IV|V|M\.?D\.?|Ph\.?D\.?|Esq\.?|Ret\.?)\b",
    re.I,
)
_NICKNAME_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"elizabeth", "liz", "beth", "betsy"}),
    frozenset({"william", "bill", "billy", "will"}),
    frozenset({"robert", "bob", "bobby", "rob"}),
    frozenset({"james", "jim", "jimmy"}),
    frozenset({"michael", "mike"}),
    frozenset({"richard", "dick", "rick"}),
    frozenset({"charles", "chuck", "charlie"}),
    frozenset({"thomas", "tom", "tommy"}),
    frozenset({"joseph", "joe"}),
    frozenset({"edward", "ed", "ted"}),
    frozenset({"daniel", "dan", "danny"}),
    frozenset({"christopher", "chris"}),
    frozenset({"benjamin", "ben"}),
    frozenset({"bernard", "bernie"}),
    frozenset({"patrick", "pat"}),
    frozenset({"kenneth", "ken"}),
    frozenset({"stephen", "steven", "steve"}),
    frozenset({"gregory", "greg"}),
    frozenset({"timothy", "tim"}),
    frozenset({"anthony", "tony"}),
    frozenset({"matthew", "matt"}),
    frozenset({"nicholas", "nick"}),
    frozenset({"alexander", "alex"}),
    frozenset({"katherine", "catherine", "kathy", "katie", "kate"}),
    frozenset({"margaret", "peggy", "meg", "maggie"}),
    frozenset({"deborah", "debbie", "deb"}),
)
_NICKNAME_MAP: dict[str, frozenset[str]] = {n: grp for grp in _NICKNAME_GROUPS for n in grp}


def _fold_ascii_letters(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def parse_person_key_v2(p: Mapping[str, Any] | str) -> tuple[str, str, tuple[str, ...]]:
    """Return `(kind, primary_token, given_tokens)` for 1-to-1 persona matching (`ct-2cig`)."""
    if isinstance(p, Mapping):
        raw_name = str(p.get("name") or "")
        etype = str(p.get("entity_type") or "")
    else:
        raw_name, etype = str(p or ""), ""

    folded = _fold_ascii_letters(raw_name).strip()
    if etype == "organization":
        org_key = re.sub(r"[^a-z0-9]+", " ", folded.lower()).strip()
        return ("org", org_key, ())

    s = _PARTY_STATE_RE.sub(" ", folded)
    s = _TRAILING_TITLE_RE.sub("", s)
    s = _HONORIFIC_EXT_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip(" ,.;:-")
    # Handle `Last, First [Middle]` inversion when a single comma separates two alpha segments
    if "," in s:
        left, right = s.split(",", 1)
        left_t = [t for t in re.findall(r"[A-Za-z'-]+", left) if any(c.isalpha() for c in t)]
        right_t = [t for t in re.findall(r"[A-Za-z'-]+", right) if any(c.isalpha() for c in t)]
        if 1 <= len(left_t) <= 2 and 1 <= len(right_t) <= 3:
            s = f"{right.strip()} {left.strip()}"

    toks = [t.strip("'-").lower() for t in re.findall(r"[A-Za-z'-]+", s)]
    toks = [t for t in toks if t and any(c.isalpha() for c in t)]
    if not toks:
        return ("person", _norm_str(raw_name), ())
    # Drop trailing 1-char initials left by stray citations (`Paul S. 558` -> `paul`, given=`s`? No: keep `paul` only if no surname)
    while len(toks) > 1 and len(toks[-1]) == 1:
        toks.pop()
    surname = toks[-1]
    given = tuple(toks[:-1])
    return ("person", surname, given)


def _given_compatible(ga: tuple[str, ...], gb: tuple[str, ...]) -> tuple[bool, int]:
    """`(compatible, specificity_rank)` for two given-name token tuples sharing a surname."""
    if not ga or not gb:
        return True, 1  # bare surname (`Chairman Pallone`) matches `Frank Pallone` when unambiguous
    set_a, set_b = set(ga), set(gb)
    if set_a & set_b:
        return True, 3 if any(len(x) > 1 for x in (set_a & set_b)) else 2
    fa, fb = ga[0], gb[0]
    if _NICKNAME_MAP.get(fa) and fb in _NICKNAME_MAP[fa]:
        return True, 3
    if len(fa) == 1 and any(t.startswith(fa) for t in gb):
        return True, 2
    if len(fb) == 1 and any(t.startswith(fb) for t in ga):
        return True, 2
    if len(fa) >= 3 and len(fb) >= 3 and (fa.startswith(fb) or fb.startswith(fa)):
        return True, 2
    return False, 0


def _match_persona_pairs(
    pred_pers: list[dict[str, Any]],
    gold_pers: list[dict[str, Any]],
) -> list[tuple[int, int]]:
    """Greedy 1-to-1 matching by specificity so two Smiths stay distinct and `Jane` != `John` (`ct-2cig`)."""
    p_keys = [parse_person_key_v2(p) for p in pred_pers]
    g_keys = [parse_person_key_v2(g) for g in gold_pers]
    cands: list[tuple[int, int, int]] = []
    for pi, pk in enumerate(p_keys):
        for gi, gk in enumerate(g_keys):
            if pk[0] != gk[0] or pk[1] != gk[1] or not pk[1]:
                continue
            if pk[0] == "org":
                cands.append((4, pi, gi))
            else:
                ok, rank = _given_compatible(pk[2], gk[2])
                if ok:
                    cands.append((rank, pi, gi))
    cands.sort(key=lambda item: (-item[0], item[1], item[2]))
    used_p: set[int] = set()
    used_g: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _, pi, gi in cands:
        if pi not in used_p and gi not in used_g:
            used_p.add(pi)
            used_g.add(gi)
            pairs.append((pi, gi))
    return pairs


class _F1:
    def __init__(self) -> None:
        self.tp = self.p = self.g = 0

    def add(self, pred: set, gold: set) -> None:
        self.tp += len(pred & gold)
        self.p += len(pred)
        self.g += len(gold)

    def add_counts(self, tp: int, p: int, g: int) -> None:
        self.tp += tp
        self.p += p
        self.g += g

    def value(self) -> float:
        return 100.0 if self.p + self.g == 0 else round(200.0 * self.tp / (self.p + self.g), 1)


def work_addr_match(pred: str, gold: str) -> bool:
    """Same office: the street / room / box number and the ZIP agree where both sides give one; a gold address with
    no number ("Los Angeles, CA") is matched by any address that says at least that. "N.W." and "NW" are one."""
    p_tok, g_tok = (re.findall(r"[a-z0-9]+", re.sub(r"(?<=\b[a-z])\.", "", a.lower())) for a in (pred, gold))
    p_num, g_num = (next((t for t in toks if t[0].isdigit()), None) for toks in (p_tok, g_tok))
    if g_num is None:
        return set(g_tok) <= set(p_tok)
    p_zip, g_zip = (next((t for t in reversed(toks) if re.fullmatch(r"\d{5}", t)), None) for toks in (p_tok, g_tok))
    return p_num == g_num and (p_zip == g_zip or p_zip is None or g_zip is None)


def _personas(obj: dict[str, Any]) -> list[dict[str, Any]]:
    raw = obj.get("personas")
    return [p for p in (raw if isinstance(raw, list) else []) if isinstance(p, dict) and str(p.get("name") or "").strip()]


def score_legacy(objs: list[dict[str, Any] | None], golds: list[dict[str, Any]], valid_flags: list[bool]) -> dict[str, Any]:
    """Pre-`ct-2cig` scorer kept so reports emit old and new metrics side by side."""
    n = len(golds)
    hit: Counter[str] = Counter()
    tot: Counter[str] = Counter()
    f1 = {k: _F1() for k in ("committees", "dates", "personas_name", "personas_name_role", "personas_name_etype", *LIST_KEYS)}
    kind_family = other = roster_spam = 0
    addr: Counter[str] = Counter()
    per_doc: list[dict[str, Any]] = []

    for obj_raw, gold in zip(objs, golds):
        obj = obj_raw if isinstance(obj_raw, dict) else {}
        for k in SCALAR_KEYS:
            if k in gold:
                tot[k] += 1
                hit[k] += int(obj.get(k) == gold[k])
        pk_p, pk_g = obj.get("primary_kind"), gold.get("primary_kind")
        other += int(pk_p == "other")
        if pk_g is not None:
            kind_family += int(pk_p == pk_g or KIND_FAMILIES.get(pk_p, pk_p) == KIND_FAMILIES.get(pk_g, pk_g))

        f1["committees"].add(
            {norm_cmt(x) for x in obj.get("committees") or [] if isinstance(x, str) and norm_cmt(x)},
            {norm_cmt(x) for x in gold.get("committees") or [] if isinstance(x, str) and norm_cmt(x)},
        )
        f1["dates"].add(
            {str(obj[k]) for k in DATE_KEYS if obj.get(k) not in (None, "", "N/A")},
            {str(gold[k]) for k in DATE_KEYS if gold.get(k) not in (None, "", "N/A")},
        )
        for k in LIST_KEYS:
            f1[k].add(
                {_norm_str(x) for x in obj.get(k) or [] if isinstance(x, (str, int))},
                {_norm_str(x) for x in gold.get(k) or [] if isinstance(x, (str, int))},
            )

        p_pers, g_pers = _personas(obj), _personas(gold)
        roster_spam += int(len(p_pers) > 10 or (pk_g == "committee_vote" and len(p_pers) > 4))
        f1["personas_name"].add({surname_of(p["name"]) for p in p_pers}, {surname_of(str(p["name"])) for p in g_pers})
        f1["personas_name_role"].add(
            {(surname_of(p["name"]), str(p.get("role"))) for p in p_pers},
            {(surname_of(str(p["name"])), str(p.get("role"))) for p in g_pers},
        )
        f1["personas_name_etype"].add(
            {(surname_of(p["name"]), str(p.get("entity_type"))) for p in p_pers},
            {(surname_of(str(p["name"])), str(p.get("entity_type"))) for p in g_pers},
        )
        g_addr = {surname_of(str(p["name"])): str(p["work_addr"]) for p in g_pers if p.get("work_addr")}
        p_addr = {surname_of(p["name"]): str(p["work_addr"]) for p in p_pers if p.get("work_addr")}
        addr["gold"] += len(g_addr)
        addr["pred"] += len(p_addr)
        addr["matched"] += sum(1 for k, a in p_addr.items() if k in g_addr and work_addr_match(a, g_addr[k]))
        addr["pred_gold_has"] += sum(1 for k in p_addr if k in g_addr)
        per_doc.append({"gold_kind": pk_g, "pred_kind": pk_p, "kind_ok": pk_p == pk_g})

    def pct(a: int, b: int) -> float:
        return round(100.0 * a / max(b, 1), 1)

    metrics: dict[str, Any] = {
        "n": n,
        "strict_valid_pct": pct(sum(valid_flags), n),
        **{f"{k}_acc": pct(hit[k], tot[k]) for k in SCALAR_KEYS},
        "primary_kind_family_acc": pct(kind_family, tot["primary_kind"]),
        **{f"{k}_f1": v.value() for k, v in f1.items()},
        "other_count": other,
        "roster_spam_docs": roster_spam,
        "work_addr_gold": addr["gold"],
        "work_addr_pred": addr["pred"],
        "work_addr_matched": addr["matched"],
        "work_addr_recall": pct(addr["matched"], addr["gold"]),
        "work_addr_precision": pct(addr["matched"], addr["pred"]),
        "work_addr_agreement": pct(addr["matched"], addr["pred_gold_has"]),
        "work_addr_pred_gold_blank": addr["pred"] - addr["pred_gold_has"],
    }
    headline = (
        "primary_kind_acc", "status_acc", "chamber_acc", "congress_acc", "committees_f1",
        "dates_f1", "personas_name_f1", "personas_name_role_f1",
    )
    metrics["headline_mean"] = round(sum(float(metrics[k]) for k in headline) / len(headline), 2)
    return {"metrics": metrics, "per_doc": per_doc}


def score(objs: list[dict[str, Any] | None], golds: list[dict[str, Any]], valid_flags: list[bool]) -> dict[str, Any]:
    """Score final V4 objects against gold (`ct-2cig`: role-aware dates, false-positive scalars, normalized subcommittees, 1-to-1 personas)."""
    n = len(golds)
    hit: Counter[str] = Counter()
    tot: Counter[str] = Counter()
    f1 = {k: _F1() for k in ("committees", "dates", "personas_name", "personas_name_role", "personas_name_etype", *LIST_KEYS)}
    kind_family = other = roster_spam = 0
    addr: Counter[str] = Counter()
    per_doc: list[dict[str, Any]] = []

    for obj_raw, gold in zip(objs, golds):
        obj = obj_raw if isinstance(obj_raw, dict) else {}
        for k in SCALAR_KEYS:
            g_has = gold.get(k) not in (None, "")
            p_has = obj.get(k) not in (None, "")
            if g_has or p_has:
                tot[k] += 1
                hit[k] += int(g_has and p_has and obj.get(k) == gold.get(k))
        pk_p, pk_g = obj.get("primary_kind"), gold.get("primary_kind")
        other += int(pk_p == "other")
        if pk_g is not None or pk_p is not None:
            kind_family += int(
                pk_g is not None
                and pk_p is not None
                and (pk_p == pk_g or KIND_FAMILIES.get(pk_p, pk_p) == KIND_FAMILIES.get(pk_g, pk_g))
            )

        f1["committees"].add(
            {norm_cmt(x) for x in obj.get("committees") or [] if isinstance(x, str) and norm_cmt(x)},
            {norm_cmt(x) for x in gold.get("committees") or [] if isinstance(x, str) and norm_cmt(x)},
        )
        f1["dates"].add(
            {(k, str(obj[k])) for k in DATE_KEYS if obj.get(k) not in (None, "", "N/A")},
            {(k, str(gold[k])) for k in DATE_KEYS if gold.get(k) not in (None, "", "N/A")},
        )
        for k in LIST_KEYS:
            norm_fn = _norm_subc if k == "subcommittees" else _norm_str
            f1[k].add(
                {v for x in obj.get(k) or [] if isinstance(x, (str, int)) and (v := norm_fn(x))},
                {v for x in gold.get(k) or [] if isinstance(x, (str, int)) and (v := norm_fn(x))},
            )

        p_pers, g_pers = _personas(obj), _personas(gold)
        roster_spam += int(len(p_pers) > 10 or (pk_g == "committee_vote" and len(p_pers) > 4))
        pairs = _match_persona_pairs(p_pers, g_pers)
        f1["personas_name"].add_counts(len(pairs), len(p_pers), len(g_pers))
        role_tp = sum(1 for pi, gi in pairs if str(p_pers[pi].get("role")) == str(g_pers[gi].get("role")))
        etype_tp = sum(1 for pi, gi in pairs if str(p_pers[pi].get("entity_type")) == str(g_pers[gi].get("entity_type")))
        f1["personas_name_role"].add_counts(role_tp, len(p_pers), len(g_pers))
        f1["personas_name_etype"].add_counts(etype_tp, len(p_pers), len(g_pers))

        g_addr_idx = {gi: str(g_pers[gi]["work_addr"]) for gi in range(len(g_pers)) if g_pers[gi].get("work_addr")}
        p_addr_idx = {pi: str(p_pers[pi]["work_addr"]) for pi in range(len(p_pers)) if p_pers[pi].get("work_addr")}
        addr["gold"] += len(g_addr_idx)
        addr["pred"] += len(p_addr_idx)
        for pi, gi in pairs:
            if pi in p_addr_idx and gi in g_addr_idx:
                addr["pred_gold_has"] += 1
                addr["matched"] += int(work_addr_match(p_addr_idx[pi], g_addr_idx[gi]))
        per_doc.append({"gold_kind": pk_g, "pred_kind": pk_p, "kind_ok": pk_p == pk_g})

    def pct(a: int, b: int) -> float:
        return round(100.0 * a / max(b, 1), 1)

    metrics: dict[str, Any] = {
        "n": n,
        "strict_valid_pct": pct(sum(valid_flags), n),
        **{f"{k}_acc": pct(hit[k], tot[k]) for k in SCALAR_KEYS},
        "primary_kind_family_acc": pct(kind_family, tot["primary_kind"]),
        **{f"{k}_f1": v.value() for k, v in f1.items()},
        "other_count": other,
        "roster_spam_docs": roster_spam,
        # Not in the headline. recall = gold addresses found; precision counts a gold-blank person as wrong;
        # agreement is precision over the people gold does give an address for.
        "work_addr_gold": addr["gold"],
        "work_addr_pred": addr["pred"],
        "work_addr_matched": addr["matched"],
        "work_addr_recall": pct(addr["matched"], addr["gold"]),
        "work_addr_precision": pct(addr["matched"], addr["pred"]),
        "work_addr_agreement": pct(addr["matched"], addr["pred_gold_has"]),
        "work_addr_pred_gold_blank": addr["pred"] - addr["pred_gold_has"],
    }
    # One headline number: mean of the fields a reader actually searches by.
    headline = (
        "primary_kind_acc", "status_acc", "chamber_acc", "congress_acc", "committees_f1",
        "dates_f1", "personas_name_f1", "personas_name_role_f1",
    )
    metrics["headline_mean"] = round(sum(float(metrics[k]) for k in headline) / len(headline), 2)
    return {"metrics": metrics, "per_doc": per_doc}


def load_record_sets(names: list[str]) -> dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    out: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    for name, path in (("val48", DEFAULT_VAL48_JSON), ("docs8", DEFAULT_DOCS8_JSON)):
        if name in names:
            rows = json.loads(path.read_text(encoding="utf-8"))
            recs = [
                {"known": r.get("known", "<NONE>"), "filename": r.get("filename", ""), "text": r.get("text") or "",
                 "format": r.get("format")}
                for r in rows
            ]
            out[name] = (recs, [r["gold"] for r in rows])
    return out


def load_sweep_sets(
    names: list[str],
    gold_jsonl: Path,
    extra: dict[str, Path] | None = None,
    *,
    augment_personas: bool = False,
) -> dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """`name -> (queue rows, golds)` for the held-out docs the sweep queue contains.

    Held-out evaluation defaults to `augment_personas=False` (untouched reviewer gold, `ct-2cig`);
    pass `augment_personas=True` only when computing side-by-side legacy metrics.
    """
    out: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    for name, path in (extra or {}).items():
        rows = [
            r
            for r in parse_gold_rows(
                path, (DEFAULT_VAL48_JSON, DEFAULT_DOCS8_JSON), augment_personas=augment_personas
            )[0]
            if r["queue_row"] is not None
        ]
        out[name] = ([r["queue_row"] for r in rows], [r["gold_v4"] for r in rows])
    if "valid_sweep" in names:
        parsed, _ = parse_gold_rows(
            gold_jsonl, (DEFAULT_VAL48_JSON, DEFAULT_DOCS8_JSON), augment_personas=augment_personas
        )
        val_idx, _ = select_val_indices(parsed)
        rows = [parsed[i] for i in sorted(val_idx) if parsed[i]["queue_row"] is not None]
        out["valid_sweep"] = ([r["queue_row"] for r in rows], [r["gold_v4"] for r in rows])
    if "val48_sweep" in names:
        v48 = json.loads(DEFAULT_VAL48_JSON.read_text(encoding="utf-8"))
        by_sha = load_queue_rows(DEFAULT_QUEUE_PARQUET, {str(r["body_sha"]) for r in v48}, "saved_body_hex")
        hits = [r for r in v48 if str(r["body_sha"]) in by_sha]
        out["val48_sweep"] = ([by_sha[str(r["body_sha"])] for r in hits], [r["gold"] for r in hits])
    return out


def run_sweep_sets(
    eng: Any,
    sets: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]],
    args: argparse.Namespace,
    *,
    legacy_golds: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, dict[str, Any]]:
    """One pass of the real sweep over every set's queue rows, scored per set."""
    import tempfile

    import pyarrow as pa
    import pyarrow.parquet as pq

    from .parquet_runner_v6 import run_docmeta_parquet_sweep

    all_rows = {str(r["link_key_hex"]): r for rows, _ in sets.values() for r in rows}
    tp_raw = str(getattr(args, "two_phase_pass2", "auto")).strip().lower()
    two_phase_pass2: bool | str = True if tp_raw == "true" else (False if tp_raw == "false" else "auto")
    with tempfile.TemporaryDirectory(prefix="docmeta_eval_") as td:
        in_p, out_p = Path(td) / "in.parquet", Path(td) / "out.parquet"
        pq.write_table(pa.Table.from_pylist(list(all_rows.values())), in_p)
        summary = run_docmeta_parquet_sweep(
            eng,
            in_p,
            out_p,
            chunk_rows=getattr(args, "chunk_rows", 4096),
            b_slots=args.b_slots,
            refill_min=getattr(args, "refill_min", 32),
            max_tokens=args.max_tokens,
            use_ane_ring="auto" if args.ane_ring else False,
            wire_format=args.wire_format,
            embed_ane=getattr(args, "embed_ane", "none"),
            grammar_router=getattr(args, "grammar_router", "none"),
            atomic_verifier=args.atomic_verifier,
            kev_batch_docs=getattr(args, "kev_batch_docs", 8),
            repair_persona_roles=args.repair_persona_roles,
            escalate_gpt_oss=args.escalate_gpt_oss,
            gpt_oss_model_dir=getattr(args, "gpt_oss_model_dir", None),
            gpt_oss_batch_size=getattr(args, "gpt_oss_batch_size", 8),
            gpt_oss_k=getattr(args, "gpt_oss_k", 1),
            two_phase_pass2=two_phase_pass2,
        )
        out_rows = {str(r["link_key_hex"]): r for r in pq.read_table(out_p).to_pylist()}

    results: dict[str, dict[str, Any]] = {}
    for name, (rows, golds) in sets.items():
        outs = [out_rows.get(str(r["link_key_hex"])) or {} for r in rows]
        objs = [json.loads(o["docmeta_json"]) if o.get("docmeta_json") else None for o in outs]
        valids = [bool(o.get("strict_v4_valid")) for o in outs]
        scored = score(objs, golds, valids)
        leg_g = (legacy_golds or {}).get(name, golds)
        scored["legacy_metrics"] = score_legacy(objs, leg_g, valids)["metrics"]
        toks = [int(o.get("completion_tokens") or 0) for o in outs]
        toks = [t for t in toks if t]
        scored["metrics"].update(
            {
                "llm_docs": len(toks),
                "avg_out_tok": round(sum(toks) / max(len(toks), 1), 1),
                "truncated_docs": sum(1 for t in toks if t >= args.max_tokens),
                "anomaly_flagged": sum(1 for o in outs if o.get("needs_teacher_escalation")),
            }
        )
        for d, r, o in zip(scored["per_doc"], rows, objs):
            d["filename"] = r.get("filename")
            d["link_key_hex"] = r.get("link_key_hex")
            d["pred"] = o
        results[name] = scored
    sweep_stats = {
        "docs": summary.docs_processed,
        "elapsed_sec": round(summary.elapsed_sec, 1),
        "docs_per_sec": round(summary.docs_per_sec, 3),
        "decode_tok_s": round(summary.decode_tok_s, 1),
        "prompt_tokens": summary.prompt_tokens,
        "completion_tokens": summary.completion_tokens,
        "pass2_escalated": summary.pass2_escalated_docs,
        "pass2_accepted": summary.pass2_accepted_docs,
        # None means the ring did not engage (off, or its bundle was missing or not fully on the ANE): a ring-on
        # run that fell back to GPU only would otherwise look like perfect parity.
        "ane_ring_bundle": f"{bundle.parent.name}/{bundle.name}" if (bundle := eng.ane_ring_bundle) else None,
    }
    for scored in results.values():
        scored["sweep"] = sweep_stats
    return results


def rescore(report_path: Path, out_path: Path, gold_jsonl: Path, label: str | None) -> int:
    """Score an earlier report's saved predictions again, reporting legacy and fixed metrics side by side (`ct-2cig`)."""
    from . import strict_validate_v4

    report = json.loads(report_path.read_text(encoding="utf-8"))
    names = list(report["sets"])
    golds = {**load_record_sets(names), **load_sweep_sets(names, gold_jsonl, augment_personas=False)}
    legacy_golds = {**load_record_sets(names), **load_sweep_sets(names, gold_jsonl, augment_personas=True)}
    for name, old in report["sets"].items():
        objs = [d.get("pred") for d in old["per_doc"]]
        assert len(objs) == len(golds[name][1]), f"{name}: the gold set changed size since {report_path}"
        valid = [bool(strict_validate_v4(o)[0]) if isinstance(o, dict) else False for o in objs]
        leg = score_legacy(objs, legacy_golds[name][1], valid)
        fresh = score(objs, golds[name][1], valid)
        old["legacy_metrics"] = {**{k: v for k, v in old["metrics"].items() if k not in leg["metrics"]}, **leg["metrics"]}
        moved = {
            k: (old["legacy_metrics"].get(k), v)
            for k, v in fresh["metrics"].items()
            if old["legacy_metrics"].get(k, v) != v
        }
        if moved:
            print(f"[{name}] side-by-side (legacy, new): {moved}")
        old["metrics"].update(fresh["metrics"])
    if label:
        report["label"] = label
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", type=Path, default=None, help="required unless --rescore")
    ap.add_argument("--label", default=None)
    ap.add_argument("--wire-format", choices=("auto", "v4", "compact"), default="auto")
    ap.add_argument("--sets", default="val48,docs8,valid_sweep,val48_sweep")
    ap.add_argument("--extra-sweep-set", action="append", default=[], metavar="NAME=GOLD_JSONL",
                    help="score every queue doc of another labeled file as its own sweep set (repeatable)")
    ap.add_argument("--gold-jsonl", type=Path, default=DEFAULT_GOLD_JSONL)
    ap.add_argument("--max-tokens", type=int, default=768)
    ap.add_argument("--chunk-rows", type=int, default=4096)
    ap.add_argument("--b-slots", type=int, default=256)
    ap.add_argument("--refill-min", type=int, default=32)
    ap.add_argument("--max-chars", type=int, default=9000, help="head/tail char window applied to every doc text")
    ap.add_argument("--llm-only", action="store_true", help="disable deterministic pre/post rules")
    ap.add_argument("--embed-ane", choices=("none", "bge-small", "embeddinggemma-2"), default="none",
                    help="pure-ANE search embeddings for the *_sweep sets")
    ap.add_argument("--grammar-router", choices=("none", "fast", "ane"), default="none",
                    help="pre-decode calibrated grammar router for the *_sweep sets")
    ap.add_argument("--atomic-verifier", choices=("none", "laya-ane", "kev-0.8b", "both"), default="none",
                    help="post-LLM output validator for the *_sweep sets")
    ap.add_argument("--kev-batch-docs", type=int, default=8,
                    help="cross-document batch size for Stage-2 Kev-0.8B MLX validator (default: 8)")
    ap.add_argument("--repair-persona-roles", action="store_true", help="let the validator repair suspect roles")
    ap.add_argument("--ane-ring", action="store_true", help="hybrid ANE prefill ring for the *_sweep sets")
    ap.add_argument("--escalate-gpt-oss", action="store_true",
                    help="send anomaly-flagged docs to the fast-gpt-oss Pass-2 teacher (*_sweep sets)")
    ap.add_argument("--gpt-oss-model-dir", default=None, help="override GPT-OSS Pass-2 model directory")
    ap.add_argument("--gpt-oss-batch-size", type=int, default=8)
    ap.add_argument("--gpt-oss-k", type=int, default=1)
    ap.add_argument("--two-phase-pass2", choices=("auto", "true", "false"), default="auto",
                    help="unload Pass-1 Gemma-4 before loading GPT-OSS-20B Pass-2 ('auto' enables on <=48 GiB Macs)")
    ap.add_argument("--ane-variant", choices=("w8", "fp16"), default="fp16", help="bundle the ring runs")
    ap.add_argument("--memory-limit-gb", type=float, default=24.0,
                    help="MLX active memory cap in GiB (default: 24.0; <=0 disables)")
    ap.add_argument("--cache-limit-gb", type=float, default=2.0,
                    help="MLX free-buffer cache cap in GiB (default: 2.0; <0 disables, 0 turns caching off)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--rescore", type=Path, default=None,
                    help="re-score the saved predictions of an earlier report with this script's metrics; no model run")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.rescore is not None:
        return rescore(args.rescore, args.out, args.gold_jsonl, args.label)
    if args.model_dir is None:
        ap.error("--model-dir is required unless --rescore is given")

    from fast_gemma4 import FastGemma4Engine
    from . import PythonicEngineV6, strict_validate_v4
    from .silicon_runtime_v6 import (
        clear_mlx_wave_cache,
        mlx_limits_scope,
        mlx_wired_limit_scope,
        run_silicon_preflight,
    )

    preflight = run_silicon_preflight(
        escalate_gpt_oss=bool(args.escalate_gpt_oss),
        require_r8_deps=True,
        once=True,
    )

    names = [s.strip() for s in args.sets.split(",") if s.strip()]
    sets = load_record_sets(names)
    extra_sets = {k: Path(v) for k, v in (item.split("=", 1) for item in args.extra_sweep_set)}
    sweep_sets = load_sweep_sets(names, args.gold_jsonl, extra_sets, augment_personas=False)
    legacy_sweep_golds = {
        k: v[1] for k, v in load_sweep_sets(names, args.gold_jsonl, extra_sets, augment_personas=True).items()
    }
    with (
        mlx_limits_scope(memory_limit_gb=args.memory_limit_gb, cache_limit_gb=args.cache_limit_gb) as mlx_limits,
        mlx_wired_limit_scope(),
    ):
        eng = FastGemma4Engine(
            model_dir=args.model_dir, default_mode="auto" if args.ane_ring else "gpu", ane_variant=args.ane_variant,
            ane_ring_variant=args.ane_variant,
            warmup=True,
            warmup_ane=args.ane_ring,
        )
        pe = PythonicEngineV6(eng, wire_format=args.wire_format)
        rule_flags = {
            k: not args.llm_only
            for k in (
                "use_provenance", "use_multipage", "use_provenance_link_anchor", "use_hygiene", "use_cover_locks",
                "use_citations", "use_relational", "use_zero_llm_bypass", "short_circuit_triage",
            )
        }

        report: dict[str, Any] = {
            "label": args.label or args.model_dir.name,
            "model_dir": str(args.model_dir),
            "wire_format": pe.wire_format,
            "llm_only": args.llm_only,
            "b_slots": args.b_slots,
            "chunk_rows": args.chunk_rows,
            "refill_min": args.refill_min,
            "embed_ane": args.embed_ane,
            "grammar_router": args.grammar_router,
            "atomic_verifier": args.atomic_verifier,
            "kev_batch_docs": args.kev_batch_docs,
            "repair_persona_roles": args.repair_persona_roles,
            "escalate_gpt_oss": args.escalate_gpt_oss,
            "gpt_oss_k": args.gpt_oss_k,
            "max_tokens": args.max_tokens,
            "mlx_limits": mlx_limits,
            "preflight": preflight,
            "sets": {},
        }
        try:
            for name, (recs, golds) in sets.items():
                for r in recs:
                    r["text"] = head_tail_window_chars(r["text"], args.max_chars)
                t0 = time.perf_counter()
                res = pe.run_records(
                    recs,
                    max_tokens=args.max_tokens,
                    B_slots=args.b_slots,
                    refill_min=args.refill_min,
                    **rule_flags,
                )
                clear_mlx_wave_cache(256)
                wall = time.perf_counter() - t0
                objs = res["clean_objs"]
                valid = [bool(strict_validate_v4(o)[0]) if isinstance(o, dict) else False for o in objs]
                scored = score(objs, golds, valid)
                scored["legacy_metrics"] = score_legacy(objs, golds, valid)["metrics"]
                llm_n = len(recs) - len(res["zero_llm_bypassed_indices"]) - len(res["triage_short_circuited_indices"])
                toks = [t for t in res["out_tok_lens"] if t]
                scored["metrics"].update(
                    {
                        "wall_sec": round(wall, 1),
                        "docs_per_sec": round(len(recs) / wall, 3),
                        "llm_docs": llm_n,
                        "avg_out_tok": round(sum(toks) / max(len(toks), 1), 1),
                        "truncated_docs": sum(1 for t in toks if t >= args.max_tokens),
                        "mask_fallbacks": res["mask_fallbacks"],
                    }
                )
                for d, r, o in zip(scored["per_doc"], recs, objs):
                    d["filename"] = r["filename"]
                    d["pred"] = o
                report["sets"][name] = scored
                print(f"[{report['label']}] {name}: {json.dumps(scored['metrics'])}", flush=True)
            if sweep_sets:
                for name, scored in run_sweep_sets(eng, sweep_sets, args, legacy_golds=legacy_sweep_golds).items():
                    report["sets"][name] = scored
                    print(f"[{report['label']}] {name}: {json.dumps(scored['metrics'])} {json.dumps(scored['sweep'])}", flush=True)
        finally:
            eng.close()
            clear_mlx_wave_cache(0, force=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
