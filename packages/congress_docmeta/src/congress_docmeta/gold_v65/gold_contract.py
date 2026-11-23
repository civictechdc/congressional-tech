#!/usr/bin/env python3
"""DocMeta gold data contract: the check every labeled set passes before anything trains or scores on it.

    gold_contract.py check --input FILE[=SPLIT] ... [--out-dir DIR] [--json REPORT] [--warn-only-split S ...]
    gold_contract.py build-ssot ...      (writes N/ssot/docmeta_gold_v6_5.jsonl and MANIFEST.json)
    gold_contract.py verify-manifest     (file hashes, row counts, contract version and rule-list hash)
    gold_contract.py export --out-dir D  (per-split files the trainer and scorer read, from the SSOT)

Three layers, each rule tagged with its layer and severity (error: the trainer and scorer must refuse the data;
warn: reported only):
  label    the existing shape validators (validate_docmeta_v4 == strict_validate_v4, compact round trip, the gold
           gate's title/gist caps) plus the conventions overlay `docmeta_gold_conventions.schema.json`, whose
           $defs keys are rule ids;
  text     rules that need the text the model trains on (production queue text when the doc is in the queue,
           else the text inside the row's own prompt), plus filename-or-text templates that fix the kind;
  dataset  keys, splits, held-out membership, leakage and the prompt form the trainer sends.
A rule is data: RULES, KIND_TEMPLATES and the overlay's $defs. Run with the congressional-tech venv Python.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import functools
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable
import unicodedata

from ..schema_v4 import MAX_PERSONAS
from .paths import resolve_docmeta_v6_data_dir, resolve_docmeta_v65_dir, resolve_package_fallback

N_DIR = resolve_docmeta_v65_dir()
A_DIR = resolve_docmeta_v6_data_dir()
CONTRACT_DIR = N_DIR / "contract"
OVERLAY_PATH = resolve_package_fallback(CONTRACT_DIR / "docmeta_gold_conventions.schema.json", "docmeta_gold_conventions.schema.json")
# Rows a person read and ruled on (one JSON object per line): link_key_hex, rule, verdict "label_stands", quote (the
# document's words that justify the label), ruled_by, ruled_at. For genuine judgment calls only, never to silence a
# rule that is wrong in general: fix the rule instead.
ADJUDICATIONS_PATH = resolve_package_fallback(CONTRACT_DIR / "adjudications.jsonl", "adjudications.jsonl")
ADJUDICATION_FIELDS = ("link_key_hex", "rule", "verdict", "quote", "ruled_by", "ruled_at")
QUEUE_PARQUET = A_DIR / "parquets_v6_2" / "llm_queue_v6_2.parquet"
HELDOUT_KEYS_JSON = resolve_package_fallback(N_DIR / "lookups_and_gold" / "heldout_v6_4_183_link_keys.json", "heldout_v6_4_183_link_keys.json")
VAL48_JSON = A_DIR / "lookups_and_gold" / "eval_val48_v4_gold.json"
DOCS8_JSON = A_DIR / "lookups_and_gold" / "eval_docs8_v4_gold.json"
SSOT_DIR = N_DIR / "ssot"
SSOT_PATH = SSOT_DIR / "docmeta_gold_v6_5.jsonl"
MANIFEST_PATH = resolve_package_fallback(SSOT_DIR / "MANIFEST.json", "MANIFEST.json")
# The labels as reviewers wrote them (D15 compares every exported label with these) and the normaliser's sidecar.
ORIGINAL_INPUTS = (A_DIR / "lookups_and_gold" / "train_v6_4_complete_ssot_gold.jsonl",
                   N_DIR / "lookups_and_gold" / "train_v6_5_gapfill_train.jsonl",
                   N_DIR / "lookups_and_gold" / "eval_v6_5_gapfill_test.jsonl")
SIGNAL_PATH = N_DIR / "lookups_and_gold" / "gold_v6_5n_signal.jsonl"


def _docmeta_commit() -> dict[str, Any]:
    """The branch, commit, and schema people limit of the checked-in DocMeta package (read-only)."""
    import subprocess

    repo_root = Path(__file__).resolve().parents[4]
    info: dict[str, Any] = {"source": "congress_docmeta", "max_personas": MAX_PERSONAS}
    for key, args in (("commit", ["rev-parse", "HEAD"]), ("branch", ["rev-parse", "--abbrev-ref", "HEAD"])):
        try:
            out = subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True, text=True, timeout=10).stdout.strip()
            info[key] = out or None
        except Exception:  # noqa: BLE001
            info[key] = None
    return info


DOCMETA_SOURCE = "congress_docmeta"
DOCMETA_INFO = _docmeta_commit()

CONTRACT_VERSION = "docmeta-gold-contract/2"  # /2: the governing rule (P01-P17, T01-T03 text only, T04), D06 split, D15
SPLITS = ("train", "heldout_v6_4", "test_gapfill", "blind_val48", "blind_docs8", "excluded")
TEST_SPLITS = frozenset({"heldout_v6_4", "test_gapfill", "blind_val48", "blind_docs8"})
BLIND_SPLITS = frozenset({"blind_val48", "blind_docs8"})
ERROR_STATUSES = frozenset({"error_or_block", "stub_or_blank", "ocr_unreadable"})
KNOWN_KEY_ORDER = ("congress", "cmt", "chambers", "date")
SHINGLE_K = 5
NEAR_DUP_CONTAINMENT = 0.9


# --------------------------------------------------------------------------------------------------------------
# Rows and the text the model trains on
# --------------------------------------------------------------------------------------------------------------
@dataclass
class Row:
    lk: str
    split: str
    source: str
    line: int
    raw: dict[str, Any]
    label: dict[str, Any] | None = None
    label_error: str | None = None
    prompt_known: str = ""
    known: str = ""
    filename: str = ""
    text: str = ""
    window: str = ""          # the text inside the row's own prompt: what the reviewer read
    in_queue: bool = False
    locked_kind: str | None = None
    fmt: str = ""
    _views: dict[str, "View"] = field(default_factory=dict, repr=False)

    def view(self, source: str) -> "View":
        """The training text, the reviewer's window or the filename as one comparison index, built once."""
        if source not in self._views:
            raw = {"text": self.text, "window": self.window, "filename": self.filename}[source]
            self._views[source] = View(raw, filename=source == "filename")
        return self._views[source]

    def __getstate__(self) -> dict[str, Any]:  # views are rebuilt on demand, never pickled
        return {**self.__dict__, "_views": {}}

    @property
    def status(self) -> str:
        return str((self.label or {}).get("status") or "usable")

    @property
    def kind(self) -> str | None:
        return (self.label or {}).get("primary_kind")

    @property
    def cls(self) -> str:
        return (self.kind or "other") if self.status == "usable" else f"status:{self.status}"


TRANSLIT = str.maketrans({"\u00f8": "oe", "\u00d8": "Oe", "\u00e6": "ae", "\u00c6": "Ae", "\u0153": "oe",
                          "\u00df": "ss", "\u019f": "ti", "\u0142": "l", "\u0141": "L", "\u0111": "d", "\u0131": "i", "\u2019": "'",
                          "\u00b4": None, "\u02ca": None, "\u02cb": None, "`": None,
                          "\u200b": None, "\u200c": None, "\u200d": None, "\ufeff": None, "\u00ad": None})  # spacing accents (Rau´l)


def fold(text: str) -> str:
    """Lower-case, accents stripped, letters NFKD cannot split transliterated (o-slash as oe, so Moese matches):
    the comparison form for grounding checks."""
    nfkd = unicodedata.normalize("NFKD", (text or "").translate(TRANSLIT))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


WORD_RE = re.compile(r"[^\W_]+")  # letters and digits in any script (Cyrillic names too)
DIGITS_RE = re.compile(r"\d+")


PARSER_FORMAT = {"pdf_text": "pdf", "html_text": "html", "xml_text": "xml", "warc": "html", "cold_r2_excerpt": "excerpt"}


def file_format(parser: Any, filename: str) -> str:
    """Format for rows outside the queue: the row's parser, else the filename extension."""
    if parser in PARSER_FORMAT:
        return PARSER_FORMAT[parser]
    ext = Path(filename or "").suffix.lower().lstrip(".")
    return {"htm": "html", "aspx": "html", "cfm": "html", "php": "html"}.get(ext, ext or "unknown")


def load_heldout_keys() -> set[str]:
    return set(json.loads(HELDOUT_KEYS_JSON.read_text(encoding="utf-8"))["link_key_hex"])


def load_rows(specs: list[str]) -> list[Row]:
    """`FILE=SPLIT` (every row in SPLIT), `FILE=auto_v64` (old gold: held-out keys file decides) or `FILE` (rows
    carry their own `split`, as SSOT rows do)."""
    heldout = load_heldout_keys()
    rows: list[Row] = []
    for spec in specs:
        path_s, _, split_arg = spec.partition("=")
        path = Path(path_s)
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            raw = json.loads(line)
            lk = str(raw.get("link_key_hex") or "").strip().lower()
            if split_arg == "auto_v64":
                split = "heldout_v6_4" if lk in heldout else "train"
            else:
                split = split_arg or str(raw.get("split") or "")
            if lk in SSOT_EXCLUSIONS and split != "excluded":  # declared exclusions hold in every check, not only in the SSOT
                split = "excluded"
                raw = {**raw, "excluded_reason": SSOT_EXCLUSIONS[lk][1], "excluded_rule": SSOT_EXCLUSIONS[lk][0]}
            rows.append(Row(lk=lk, split=split, source=path.name, line=i, raw=raw))
    return rows


def attach_text(rows: list[Row]) -> None:
    """Fill known / filename / text the way `parse_gold_rows` does: the production queue row when the doc is in
    the queue (through the runner's own context builder), else the row's own prompt."""
    import duckdb
    from ..parquet_runner_v6 import _build_precomputed_context_from_queue_row
    from ..gold import _PROMPT_PARSE_RE

    keys = sorted({r.lk for r in rows if r.lk})
    con = duckdb.connect()
    con.execute("SET memory_limit='4GB'; SET threads=4")
    con.execute("CREATE TEMP TABLE k(lk VARCHAR)")
    con.executemany("INSERT INTO k VALUES (?)", [(k,) for k in keys])
    cols = ("link_key_hex", "filename", "effective_format", "p12_raw_text", "p12_clean_text", "known_json",
            "rel_congress", "rel_chamber", "rel_committees", "locked_primary_kind")
    cur = con.execute(f"SELECT {', '.join(cols)} FROM read_parquet('{QUEUE_PARQUET}') q SEMI JOIN k ON q.link_key_hex = k.lk")
    queue = {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}
    con.close()
    for r in rows:
        msgs = r.raw.get("messages") or [{}]
        user = str(msgs[0].get("content") or "")
        m = _PROMPT_PARSE_RE.search(user)
        p_known, p_fn, p_text = (m.group("known").strip(), m.group("filename").strip(), m.group("text") or "") if m else ("<NONE>", "", user)
        r.prompt_known, r.window = p_known, p_text
        q = queue.get(r.lk)
        if q is not None:
            r.known, _, r.filename, r.text, _ = _build_precomputed_context_from_queue_row(q)
            r.in_queue, r.locked_kind = True, q.get("locked_primary_kind")
            r.fmt = str(q.get("effective_format") or "").lower()
        else:
            r.known, r.filename, r.text = p_known, p_fn, p_text
        r.fmt = r.fmt or file_format(r.raw.get("parser"), r.filename)
        r._views = {}


def attach_labels(rows: list[Row]) -> None:
    for r in rows:
        try:
            msgs = r.raw.get("messages") or []
            obj = json.loads(msgs[-1]["content"]) if msgs else None
            if not isinstance(obj, dict):
                raise ValueError("label is not a JSON object")
            r.label = obj
        except Exception as exc:  # noqa: BLE001 - any unreadable label is a finding, not a crash
            r.label_error = f"label_unreadable:{exc}"[:200]


# --------------------------------------------------------------------------------------------------------------
# Label layer: shape validators + overlay schema, computed once per row and read by the label rules
# --------------------------------------------------------------------------------------------------------------
def load_overlay() -> dict[str, Any]:
    return json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))


def label_layer_errors(rows: list[Row], overlay: dict[str, Any]) -> dict[str, dict[str, str]]:
    """`rule id -> {link key: reason}` for the shape validators, the gold gate and every overlay rule."""
    import jsonschema
    from .. import canonicalize_docmeta_v4, strict_validate_v4, validate_docmeta_v4
    from ..compact_wire_v6 import (
        OMITTED_DETERMINISTIC_V4_KEYS,
        encode_v4_to_compact_v6,
        expand_compact_json_str_to_v4,
    )
    from .gold_gate_v6_2 import load_forbidden_sets, validate_gold_record

    rule_ids = [ref["$ref"].rsplit("/", 1)[-1] for ref in overlay["allOf"]]
    validator = jsonschema.Draft202012Validator(overlay)
    forbidden = load_forbidden_sets(include_prior_58=False, allow_rehydrate_360=True)  # blind (sacred) sets only
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for r in rows:
        if r.label is None:
            out["L00_shape"][r.lk] = r.label_error or "no label"
            continue
        ok, err = validate_docmeta_v4(r.label)
        ok_s, err_s = strict_validate_v4(r.label)
        if not (ok and ok_s):
            out["L00_shape"][r.lk] = f"validate_docmeta_v4:{err or err_s}"
        else:
            try:
                if canonicalize_docmeta_v4(dict(r.label)) != r.label:
                    out["L00_shape"][r.lk] = "label differs from canonicalize_docmeta_v4(label)"
            except Exception as exc:  # noqa: BLE001
                out["L00_shape"][r.lk] = f"canonicalize_error:{exc}"[:200]
        try:
            back, perr = expand_compact_json_str_to_v4(
                json.dumps(encode_v4_to_compact_v6(r.label), separators=(",", ":"), ensure_ascii=False))
            # refs and fiscal_years are left off the wire by design (rules add them after decoding).
            want = {k: v for k, v in r.label.items() if k not in OMITTED_DETERMINISTIC_V4_KEYS}
            if back != want:
                diff = sorted(k for k in set(want) | set(back or {}) if (back or {}).get(k) != want.get(k))
                out["L01_compact_roundtrip"][r.lk] = f"fields changed: {diff or perr}"
        except Exception as exc:  # noqa: BLE001
            out["L01_compact_roundtrip"][r.lk] = f"roundtrip_error:{exc}"[:200]
        _, gate_errs, _ = validate_gold_record(r.raw, forbidden)
        for e in gate_errs:
            if e.startswith(("composed_title_length", "gist_word_count")):
                out["L02_title_gist_caps"][r.lk] = e
            elif e.startswith("SACRED_LEAK"):
                if r.split not in BLIND_SPLITS:
                    out["D09_blind_set_overlap"].setdefault(r.lk, f"gold_gate:{e}")
            elif not e.startswith(("validate_docmeta_v4", "strict_validate_v4", "DUPLICATE_PRIOR")):
                out["D01_row_format"].setdefault(r.lk, e)
        for err in validator.iter_errors(r.label):
            rid = rule_ids[err.schema_path[1]] if len(err.schema_path) > 1 and err.schema_path[0] == "allOf" else "L00_shape"
            out[rid].setdefault(r.lk, f"{'/'.join(map(str, err.absolute_path)) or '(root)'}: {err.message}"[:240])
    return out


# --------------------------------------------------------------------------------------------------------------
# Text layer
# --------------------------------------------------------------------------------------------------------------
def within_one_edit(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i + (len(a) == len(b)):] == b[i + 1:]


# One comparison index per source. Every text check reads the training text; the reviewer's window and the filename
# are read only to say where an unstated value came from.
DOTTED_RE = re.compile(r"\b[a-z](?:\.\s?[a-z])+\b\.?")  # U.S. / D.C / H. R. -> us / dc / hr
STATE_CODES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar", "california": "ca", "colorado": "co",
    "connecticut": "ct", "delaware": "de", "florida": "fl", "georgia": "ga", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks", "kentucky": "ky", "louisiana": "la",
    "maine": "me", "maryland": "md", "massachusetts": "ma", "michigan": "mi", "minnesota": "mn",
    "mississippi": "ms", "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new hampshire": "nh", "new jersey": "nj", "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa",
    "rhode island": "ri", "south carolina": "sc", "south dakota": "sd", "tennessee": "tn", "texas": "tx",
    "utah": "ut", "vermont": "vt", "virginia": "va", "washington": "wa", "west virginia": "wv",
    "wisconsin": "wi", "wyoming": "wy", "district of columbia": "dc", "puerto rico": "pr", "guam": "gu",
    # AP-style abbreviations that are not also common words
    "ala": "al", "ariz": "az", "ark": "ar", "calif": "ca", "colo": "co", "conn": "ct", "fla": "fl",
    "kan": "ks", "kans": "ks", "mich": "mi", "minn": "mn", "mont": "mt", "neb": "ne", "nev": "nv",
    "okla": "ok", "ore": "or", "penn": "pa", "tenn": "tn", "tex": "tx", "wis": "wi", "wisc": "wi", "wyo": "wy",
}
AMBIGUOUS_CODES = frozenset("in or me oh hi ok de pa co la ma al id mt wa ne".split())  # also common words
_NAME_OF: dict[str, str] = {}
for _k, _c in STATE_CODES.items():
    if len(_k) > 4:
        _NAME_OF.setdefault(_c, _k)
PHRASE_CODES = {**{k: k.replace(" ", "") for k in STATE_CODES if " " in k}, "united states of america": "us",
                "united states": "us", "usa": "us", "united kingdom": "uk", "kiev": "kyiv"}
STATE_PHRASE_RE = re.compile(r"\b(" + "|".join(sorted(PHRASE_CODES, key=len, reverse=True)) + r")\b")
ABBREV = {  # one comparison form for spellings that mean the same word
    "department": "dept", "street": "st", "avenue": "ave", "boulevard": "blvd", "association": "assn",
    "assoc": "assn", "national": "natl", "international": "intl", "university": "univ", "corporation": "corp",
    "incorporated": "inc", "government": "govt", "building": "bldg", "suite": "ste", "centre": "center",
    "ctr": "center", "mount": "mt", "fort": "ft", "chairman": "chair", "chairwoman": "chair",
    "chairperson": "chair", "representative": "rep", "senator": "sen", "honorable": "hon", "secretary": "sec",
    "commissioner": "commr", "administrator": "admr", "director": "dir", "assistant": "asst", "vice": "vice",
    "colonel": "col", "general": "gen", "lieutenant": "lt", "captain": "capt", "sergeant": "sgt",
    "professor": "prof", "doctor": "dr", "junior": "jr", "senior": "sr", "company": "co", "brothers": "bros",
    "limited": "ltd", "laboratory": "lab", "institute": "inst", "commn": "commission", "comm": "committee",
    "governmental": "govt",
    "subcomm": "subcommittee",
    # a state is its name: unambiguous postal codes and AP abbreviations map to it (CA = California = Calif.)
    **{k: _NAME_OF[c].replace(" ", "") for k, c in STATE_CODES.items() if len(k) <= 5 and " " not in k and c in _NAME_OF},
    **{c: n.replace(" ", "") for c, n in _NAME_OF.items() if c not in AMBIGUOUS_CODES},
}
_ABBREV_FORMS = frozenset(ABBREV.values())


def _stem(t: str) -> str:
    """Plural to singular on both sides (counties = county, departments = department), then the abbreviation map."""
    t = ABBREV.get(t, t)
    if re.fullmatch(r"\d+s", t):  # P-8s, 1990s
        return t[:-1]
    if t in _ABBREV_FORMS or len(t) <= 3 or not t.isalpha():
        return t
    if t.endswith("ies") and len(t) > 4:
        t = t[:-3] + "y"
    elif t.endswith("s") and not t.endswith(("ss", "us", "is")):
        t = t[:-1]
    return ABBREV.get(t, t)
STOP = frozenset("the of and for on in at a an to by with its from as or be".split())


def norm_tokens(folded: str) -> list[str]:
    """Comparison tokens of folded text: dotted initials joined (U.S. = US, D.C. = DC), '&' = 'and', apostrophes
    dropped (Veterans' = Veterans), state names and common abbreviations mapped to one form on both sides."""
    s = DOTTED_RE.sub(lambda m: " " + re.sub(r"[.\s]", "", m.group(0)) + " ", folded)
    s = re.sub(r"['’`]s\b|['’`]", "", s.replace("&", " and "))
    s = re.sub(r"[^\w]+|_", " ", s)  # PDF separators: "Puerto)Rico", "Puerto%Rico"
    s = STATE_PHRASE_RE.sub(lambda m: " " + PHRASE_CODES[m.group(1)] + " ", s)
    return [_stem(t) for t in WORD_RE.findall(s)]


class View:
    """One source (training text, reviewer window or filename) as a comparison index: folded flat text,
    comparison tokens with positions, the word and run-in sets the name checks read, and its digits."""

    def __init__(self, raw: str, filename: bool = False):
        if filename:  # HHRG-115-IF18-Wstate-EisenbergR-20170216 -> HHRG 115 IF 18 Wstate Eisenberg R 20170216
            raw = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", raw or "")
            raw = re.sub(r"[_\-+]+|%20", " ", raw)
        self.is_filename = filename
        self.orig = re.sub(r"\s+", " ", raw or "").strip()
        self.flat = fold(self.orig)
        seq = WORD_RE.findall(self.flat)
        self.seq = seq
        self.words = set(seq) | {re.sub(r"\d+$", "", w) for w in seq if re.search(r"[a-z]\d+$", w)}  # footnote marks: "gee1"
        self.header_lines = frozenset(x.strip() for x in (raw or "").splitlines()
                                      if 0 < len(x.strip()) <= 40 and x.strip().isupper())
        self.pairs = {a + b for a, b in zip(seq, seq[1:])}  # OCR splits a name: "Kil dee", "Caupbe ll"
        self.alnum = "".join(seq)
        self.nows = re.sub(r"\s+", "", self.flat)
        self.digits = re.sub(r"\D", "", self.orig)
        self.toks = norm_tokens(self.flat)
        letters = [c for c in self.orig if c.isalpha()]
        self.non_latin = bool(letters) and sum(ord(c) > 0x24F for c in letters) > 0.3 * len(letters)
        self.unreadable = not filename and (self.non_latin or readable_share(raw or "") < 0.5)
        # Spaced-letter OCR ("K U R T R A N S O H O F F", "w w w . n c a i . o r g"), joined, at its token position.
        n = max(1, len(self.flat))
        self.runs = [(re.sub(r"[\s.]", "", m.group(0)), int(m.start() / n * len(self.toks)))
                     for m in re.finditer(r"\b(?:\w[\s.]{1,2})+\w\b", self.flat) if len(m.group(0)) >= 3]
        self.pos: dict[str, list[int]] = defaultdict(list)
        for i, t in enumerate(self.toks):
            self.pos[t].append(i)
        self._pair_pos: dict[str, list[int]] | None = None
        self._sorted: tuple[list[str], list[str]] | None = None
        self._name_by_len: dict[int, list[str]] | None = None
        self._tok_by_len: dict[int, list[str]] | None = None
        self._near: dict[str, list[int]] = {}
        self._near_all: dict[str, list[int]] = {}
        self.memo: dict[Any, Any] = {}

    def name_words_of_len(self, n: int) -> list[str]:
        if self._name_by_len is None:
            self._name_by_len = defaultdict(list)
            for w in self.words | self.pairs:
                self._name_by_len[len(w)].append(w)
        return self._name_by_len.get(n, [])

    def near(self, w: str) -> list[int]:
        """Positions of comparison token w; when absent: two adjacent words run together (Global Foundries), a 5+
        letter token run into its neighbour (HTML 'titleoversight'), or for 6+ letters one OCR edit away (also
        'rn' read as 'm': Raybum)."""
        if w not in self._near:
            p = self.pos.get(w) or []
            if not p and w.isalpha() and len(w) >= 4:
                if self._pair_pos is None:
                    self._pair_pos = defaultdict(list)
                    for i, (a, b) in enumerate(zip(self.toks, self.toks[1:])):
                        self._pair_pos[a + b].append(i)
                p = list(self._pair_pos.get(w, ()))
            if not p and w.isalpha() and len(w) >= 5:
                import bisect
                if self._sorted is None:
                    self._sorted = (sorted(self.pos), sorted(t[::-1] for t in self.pos))
                fwd, rev = self._sorted
                hits = []
                for arr, key, flip in ((fwd, w, False), (rev, w[::-1], True)):
                    j = bisect.bisect_left(arr, key)
                    while j < len(arr) and arr[j].startswith(key) and len(hits) < 20:
                        if len(arr[j]) <= len(w) + 12:
                            hits.append(arr[j][::-1] if flip else arr[j])
                        j += 1
                p = sorted(i for t in hits for i in self.pos[t])
            if not p and len(w) >= 6 and w.isalpha():
                if self._tok_by_len is None:
                    self._tok_by_len = defaultdict(list)
                    for t in self.pos:
                        self._tok_by_len[len(t)].append(t)
                ocr = w.replace("rn", "m")
                p = sorted(i for n in (len(w) - 2, len(w) - 1, len(w), len(w) + 1) for t in self._tok_by_len.get(n, ())
                           if within_one_edit(w, t) or (ocr != w and within_one_edit(ocr, t)) for i in self.pos[t])
            self._near[w] = p
        return self._near[w]

    def near_all(self, w: str) -> list[int]:
        """near() plus the OCR forms even when w also occurs exactly elsewhere ('Artic' beside 'Arctic', 'Raybum'),
        and spaced-letter runs that contain w."""
        if w not in self._near_all:
            p = set(self.near(w))
            if len(w) >= 6 and w.isalpha():
                if self._tok_by_len is None:
                    self._tok_by_len = defaultdict(list)
                    for t in self.pos:
                        self._tok_by_len[len(t)].append(t)
                ocr = w.replace("rn", "m")
                p |= {i for n in (len(w) - 2, len(w) - 1, len(w), len(w) + 1) for t in self._tok_by_len.get(n, ())
                      if within_one_edit(w, t) or (ocr != w and within_one_edit(ocr, t)) for i in self.pos[t]}
            p |= {i for run, i in self.runs if w == run or (len(w) >= 3 and w in run)}
            if (not p or len(w) >= 8) and len(w) >= 5 and w.isalpha():  # scan damage: "smull" for small, "oratsportation"
                if self._tok_by_len is None:
                    self._tok_by_len = defaultdict(list)
                    for t in self.pos:
                        self._tok_by_len[len(t)].append(t)
                import difflib
                p |= {i for n in range(len(w) - 2, len(w) + 3) for t in self._tok_by_len.get(n, ())
                      if (len(w) == 5 and within_one_edit(w, t)) or (len(w) >= 8 and similar(w, t, 0.8))
                      for i in self.pos[t]}
            if len(w) >= 6 and w.isalpha():  # the text abbreviates the value's word: "Transp." for Transportation
                p |= {i for t in self.pos if 4 <= len(t) < len(w) and w.startswith(t) for i in self.pos[t]}
            self._near_all[w] = sorted(p)
        return self._near_all[w]


def token_shown(tok: str, v: View) -> bool:
    """A name token is shown when all its alphanumeric parts occur as words, or their concatenation does
    (O'Brien / OBrien, Jackson-Lee / Jackson Lee), or two adjacent words run together (Kil dee); a 5+ letter token
    also passes one OCR edit away (HouGHron). In a filename a 4+ letter token also passes inside a run-in
    (honrussellvoughttestimony)."""
    parts = WORD_RE.findall(fold(tok))
    if not parts or all(p in v.words for p in parts):
        return True
    joined = "".join(parts)
    if joined in v.words or (len(joined) >= 3 and joined in v.pairs) or (v.is_filename and len(joined) >= 4 and joined in v.alnum):
        return True
    if len(joined) >= 4 and any(joined in run for run, _ in v.runs):
        return True
    if len(joined) < 5:
        return False
    if any(within_one_edit(joined, w) for n in (len(joined) - 1, len(joined), len(joined) + 1)
           for w in v.name_words_of_len(n)):
        return True
    return scan_damaged_hit(joined, v)


def similar(a: str, b: str, at_least: float) -> bool:
    """SequenceMatcher ratio >= at_least, rejecting first on its cheap upper bounds (the full ratio is the slow step)."""
    import difflib

    m = difflib.SequenceMatcher(None, a, b)
    return m.real_quick_ratio() >= at_least and m.quick_ratio() >= at_least and m.ratio() >= at_least


def scan_damaged_hit(word: str, v: View) -> bool:
    """Owner 2026-11-18: read through scan damage the way a person would ("Cassicdog" is Cassidy, "Thonspion" is
    Thompson, "Alsobrodkos" is Alsobrooks, "Nukheee" is Mukherjee): a text word at most three letters longer or
    shorter with a similarity ratio of at least 0.75, or 0.7 when the first letter also matches."""
    import difflib

    key = ("scan", word)
    if key not in v.memo:
        cands = (w for n in range(len(word) - 3, len(word) + 4) for w in v.name_words_of_len(n))
        v.memo[key] = any(similar(word, w, 0.7 if w[:1] == word[:1] else 0.75) for w in cands)
    return v.memo[key]


def people(r: Row) -> list[dict[str, Any]]:
    return [p for p in (r.label or {}).get("personas") or [] if p.get("entity_type") != "organization"]


def name_tokens_missing(name: str, v: View) -> list[str]:
    toks = name.split()
    miss = [tok for tok in toks if not token_shown(tok, v)]
    if miss and len(miss) < len(toks):  # read a short token through scan damage when the rest of the name is there
        miss = [t for t in miss if not (len(w := "".join(WORD_RE.findall(fold(t)))) == 4
                                        and any(within_one_edit(w, x) for x in v.name_words_of_len(4)))]
    return miss


def person_named(name: str, v: View) -> bool:
    """A person is named when a token of two or more letters is shown; an initial alone ("E.") does not count."""
    return any(len("".join(WORD_RE.findall(fold(t)))) >= 2 and token_shown(t, v) for t in name.split())


def check_names_tokens(r: Row) -> str | None:
    bad = []
    for p in people(r):
        name = str(p.get("name") or "")
        miss = name_tokens_missing(name, r.view("text"))
        if miss and len(miss) < len(name.split()):
            bad.append(f"{name} (not in text: {' '.join(miss)})")
    return "; ".join(bad) or None


def check_person_named(r: Row) -> str | None:
    bad = [f"{p.get('name')} [{fact_source('person_name', str(p.get('name') or ''), r)}]" for p in people(r)
           if not person_named(str(p.get("name") or ""), r.view("text"))]
    return "; ".join(bad) or None


ACT_YEAR_RE = re.compile(r"\bof (1[789]\d\d|20\d\d)\b")


def ref_number_groups(ref: str) -> list[str]:
    """Identifying digit groups of a ref: groups of two or more digits, less the year in an act's name
    ("Employee Retirement Income Security Act of 1974"). A `usc:` ref is identified by its section and an `fr:`
    ref by its page: title and volume are canonical form ("I.R.C. section 871" is `usc:26 U.S.C. 871`; "Federal
    Register (January 28, 2003), p. 4239" is `fr:68 FR 4239`). Date-form ids are not checked."""
    prefix, _, body = ref.partition(":")
    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", body):  # a date used as an id (olc:OLC Opinion 2019-11-03) is written in words
        return []
    groups = [g for g in DIGITS_RE.findall(ACT_YEAR_RE.sub(" ", body)) if len(g) >= 2]
    return groups[-1:] if prefix in ("usc", "fr") else groups


def ref_shown(ref: str, v: View) -> bool:
    """Every group occurs in the whitespace-free source, so OCR splits ("M 118") still count as shown."""
    return all(g in v.nows for g in ref_number_groups(ref))


def check_ref_numbers(r: Row) -> str | None:
    bad = [f"{ref} [{fact_source('refs', ref, r)}]" for ref in (r.label or {}).get("refs") or []
           if ref_number_groups(ref) and not ref_shown(ref, r.view("text"))]
    return "; ".join(bad) or None


def has_numeric_ref(r: Row) -> bool:
    return any(ref_number_groups(ref) for ref in (r.label or {}).get("refs") or [])


# --------------------------------------------------------------------------------------------------------------
# Provenance: every fact a label records is stated in the training text (owner rule 2026-11-18)
# --------------------------------------------------------------------------------------------------------------
# "The source text is the source of truth": the filename, upload slot, source path, the `known` hint, rosters and
# memory never supply a value. Each fact is classified by where it occurs, first hit wins:
#   text      the training text states it (the only class that passes)
#   window    only the reviewer's own prompt text, which differs from the training text for queue rows
#   known     only the `known` hint the trainer sends
#   filename  only the filename
#   derived   only follows from something stated: a Congress from a stated year, a chamber from a committee
#             that exists in one chamber only (Ways and Means, Finance)
#   none      nowhere
# Judgment fields (status, kinds, text_quality, roles, gist, topics, composed_title, event_type,
# correspondence_flow) are conclusions about the text and are not facts here; nor is chamber
# `executive_or_external`, which names no chamber.
SOURCES = ("text", "window", "known", "filename", "derived", "none")
# `unchecked` passes: chamber executive_or_external, which names no chamber. Garbled and non-English texts are
# judged like any other (owner: "interpretation is not hallucination"); T07 lists them for a person to read, and
# their rulings go in adjudications.jsonl.
_UNITS = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
          "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_ORDINAL_LAST = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
                 "nine": "ninth", "twelve": "twelfth"}


def _cardinal(n: int) -> str:
    if n < 20:
        return _UNITS[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _UNITS[n % 10])
    return "one hundred" + ("" if n == 100 else " " + _cardinal(n - 100))


def ordinal_words(n: int) -> list[str]:
    """118 -> ['one', 'hundred', 'eighteenth']."""
    *head, last = _cardinal(n).split()
    last = _ORDINAL_LAST.get(last) or (last[:-1] + "ieth" if last.endswith("y") else last + "th")
    return [*head, last]


def congress_of_year(year: int) -> int:
    return (year - 1789) // 2 + 1


# Every Congress the text names, with where. Stated by an ordinal ("118th Congress", "118th Cong.", congress.gov's
# "118th-congress", "116th United States Congress"; scan damage "117h", "117\"", "1i2th", "114*h"), the number in
# words ("One Hundred Eighteenth Congress"; misspelled or misread words within two edits: "ONE HUNDRED FIFTHTEENTH
# CONGRESS"), or a printed designator of the document (Serial No./Rept./Hrg./Doc./Print 118-NN, "S. HR9. 106-344",
# GovInfo ids BILLS-/CHRG-/CRPT-/HHRG-118). A public-law number says when a law passed, not when this document was
# made, and does not count; a year never states a Congress.
_ORDINAL_NUM = {" ".join(ordinal_words(n)): n for n in range(1, 131)}
_SPELLED_RE = "|".join(w.replace(" ", r"[\s\-]+(?:and[\s\-]+)?") for w in sorted(_ORDINAL_NUM, key=len, reverse=True))
_SPELLED_RE = _SPELLED_RE.replace(r"one[\s\-]+(?:and[\s\-]+)?hundred", r"(?:one|[a-z]{2,4})[\s\-]+hundred")
CONGRESS_MENTION_RE = re.compile(
    r"(?<![\w])(?P<num>(?=[\dil]*\d)[\dil]{1,3})\s?(?:st|nd|rd|th|d|h|t[a-z]?|[\x22”’\x27*]{1,2}h?)\.?[\s\-]*(?:united states\s+|u\.?\s?s\.?\s+)?cong(?:ress\b|\.|\b)"
    rf"|\b(?P<words>{_SPELLED_RE})[\s\-]+congress\b"
    r"|\b(?:serial|rept|rpt|report|hr[g9q]|doc|document|print|prt)\.?,?\s*(?:no\.?|number)?\s*(?P<desig>\d{2,3})\s?[\-\u2013]\s?\d"
    r"|\b(?:bills|crpt|chrg|cprt|cdoc|hhrg|hmtg|shrg)[\-\s]?(?P<pkg>\d{2,3})(?!\d)")
# A mention is the document's own Congress (masthead, header, document number) unless it reads as a passing
# mention: inside site navigation (a schedule or archive menu, or three or more different Congresses within 200
# characters), a bill or act "introduced/passed/enacted in the Nth Congress", or past the first 1,500 characters.
NAV_CUE_RE = re.compile(r"committee schedule|schedule|archives?|menu|skip to|select (?:a )?congress|previous congress|hearings\s*(?:&|and)?\s*(?:events|markups)?\s*$")
CITED_CUE_RE = re.compile(r"(?:introduced|passed|enacted|considered|reported|signed|during|throughout|since|as of|before|after|until|prior to)\s+(?:in|by)?\s*(?:the)?\s*$")
OWN_HEAD_CHARS = 1500


def edit_distance_at_most(a: str, b: str, k: int) -> bool:
    if abs(len(a) - len(b)) > k:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1] <= k


_ORDINAL_SEQ = [(n, [w for w in ordinal_words(n)]) for n in range(1, 131)]


def damaged_ordinal(words: list[str]) -> int | None:
    """The Congress whose ordinal words these are, each word exact or within two edits (one for words under eight
    letters; any short word for a misread 'one' before 'hundred')."""
    words = [w for w in words if w != "and"]
    for n, ow in sorted(_ORDINAL_SEQ, key=lambda x: -len(x[1])):
        if len(ow) > len(words):
            continue
        tail = words[-len(ow):]
        if all(a == b or (len(b) >= 5 and edit_distance_at_most(a, b, 2 if len(b) >= 8 else 1))
               or (b == "one" and i == 0 and len(ow) > 1 and 2 <= len(a) <= 4) for i, (a, b) in enumerate(zip(tail, ow))):
            return n
    return None


def congress_mentions(flat: str) -> list[tuple[int, int, bool]]:
    """(Congress, position, own) for every Congress the folded text names."""
    found = []
    for m in CONGRESS_MENTION_RE.finditer(flat):
        if m.group("words"):
            w = re.sub(r"[\s\-]+(?:and[\s\-]+)?", " ", m.group("words"))
            n = _ORDINAL_NUM.get(re.sub(r"^[a-z]{2,4} hundred", "one hundred", w))
        elif m.group("num"):
            n = int(re.sub(r"[il]", "1", m.group("num")))
        else:
            n = int(m.group("desig") or m.group("pkg"))
        if n and 1 <= n <= 130:
            found.append((n, m.start(), bool(m.group("desig") or m.group("pkg"))))
    taken = {p for _, p, _ in found}
    for m in re.finditer(r"\bcongress\b", flat):  # ordinal words damaged beyond the exact form
        words = re.findall(r"[a-z]+", flat[max(0, m.start() - 70): m.start()])[-5:]
        n = damaged_ordinal(words) if words else None
        if n and not any(m.start() - 80 <= q <= m.start() for q in taken):
            found.append((n, max(0, m.start() - 40), False))
    out = []
    for n, pos, designator in found:
        window = {k for k, q, _ in found if abs(q - pos) <= 200}
        before = flat[max(0, pos - 80): pos]
        nav = len(window) >= 3 or bool(NAV_CUE_RE.search(flat[max(0, pos - 40): pos]))
        cited = bool(CITED_CUE_RE.search(before)) and not designator
        in_link = flat[max(0, pos - 1): pos] in ("/", "=") or bool(re.search(r"https?://\S*$|www\.\S*$", flat[max(0, pos - 120): pos]))
        out.append((n, pos, not in_link and (designator or (pos < OWN_HEAD_CHARS and not nav and not cited))))
    return out


def view_congress_mentions(v: View) -> list[tuple[int, int, bool]]:
    if "congress_mentions" not in v.memo:
        v.memo["congress_mentions"] = congress_mentions(v.flat)
    return v.memo["congress_mentions"]


def congress_stated(value: Any, v: View) -> bool:
    return isinstance(value, int) and any(n == value for n, _, _ in view_congress_mentions(v))


CHAMBER_RES = {  # a chamber is stated by its name or by a committee name or office building that carries it
    "house": re.compile(
        r"house of representatives|\bu\.?\s?s\.? house\b|\bunited states house\b"
        r"|(?<!white )\bhouse (?:(?:permanent )?select |standing |sub)?committee"
        r"|(?<!white )\bhouse (?:[a-z0-9,'&\-]+ ){0,6}?(?:sub[\s\-]?)?comm[a-z0-9]*|\bh\.\s?(?:sub)?comm\.? on\b"
        r"|\bhouse (?:report|document|calendar)\b|\breported to the house\b|\bhouse floor\b|\bfor the use of the house\b"
        r"|\bhouse\W{0,8}\d{1,3}(?:st|nd|rd|th|d) congress"
        r"|\bcommittees? on (?:[a-z,'&\-]+ ){1,8}?of the house\b|\bcommittees? on house administration\b"
        r"|\b(?:rayburn|longworth|cannon)\s+(?:house\s+)?(?:office\s+)?(?:building|bldg)\b|\b\d{3,4}\s+(?:rayburn|longworth|cannon)\b"
        r"|\b\d{3,4}\s*(?:rhob|lhob|chob)\b|\bhvc[\s\-]?\d{3}\b|\b[\w\-]+\.house\.gov\b|\bthe full house\b"
        r"|\b(?:reported|report|favorably)\b.{0,40}\bto the house\b|\bhouse [\-\u2013\u2014] [a-z]|\bhouse rule\b|\brules of the house\b"
        r"|\bin the house of\b|\bh\.\s?(?:rept|rpt|doc|prt)\b|congressional record\W+house\b"
        r"|\bho\w{2,3}e\s+of\s+repr\w{6,}|\(house\)|\b(?:rayburn|longworth|cannon)\s+house\b"
        r"|\brepresentatives? (?:who are )?(?:members|on) (?:of )?this (?:sub)?committee\b"
        r"|\bamendment\b.{0,300}?\bo\w{4,6}\s+\S{1,2}\s+m[a-z_]{0,2}\.?[\s_]"),  # House form: "Offered by Mr. X of State", blank "M_. ____"
    "senate": re.compile(
        r"united states senate|\bu\.?\s?s\.? senate\b"
        r"|\bsenate (?:(?:special|select) )?(?:sub)?committee"
        r"|\bsenate (?:[a-z0-9,'&\-]+ ){0,6}?(?:sub[\s\-]?)?comm[a-z0-9]*|\bs\.\s?(?:sub)?comm\.? on\b"
        r"|\bsenate (?:report|document|calendar|office building)|\bsession\W{0,4}senate\b|\breported to the senate\b"
        r"|\bto the senate of the united states|\bsenate advises and consents|\badvice and consent of the senate|\bfor the use of the senate\b|\bsenate floor\b"
        r"|\bsenate\W{0,8}\d{1,3}(?:st|nd|rd|th|d) congress|(?:house of representatives|the house) and (?:the )?senate\b"
        r"|\bcommittees? on (?:[a-z,'&\-]+ ){1,8}?of the senate\b"
        r"|\b(?:dirksen|russell|hart)\s+(?:senate\s+)?(?:office\s+)?(?:building|bldg)\b|\b\d{2,4}\s+(?:dirksen|russell|hart)\b"
        r"|\b(?:room|location|loc\.)\W{0,3}s[dhr][\s\-]?\d{2,3}\b|\bs[dhr]-\d{2,3}\b|\b[\w\-]+\.senate\.gov\b|\bthe full senate\b"
        r"|\b(?:reported|report|favorably)\b.{0,40}\bto the senate\b|\bs\.\s?hrg\b|\bsenate [\-\u2013\u2014] [a-z]|\bin the senate of\b"
        r"|\brules of the senate\b|\bs\.\s?(?:rept|rpt|doc|prt)\b|congressional record\W+senate\b"
        r"|\bunited\s+states\s+sen\w{2,4}\b|\((?:u\.?\s?s\.?\s)?senate\)|\b(?:dirksen|russell|hart)\s+senate\b"
        r"|\bsenators? (?:who are )?(?:members|on) (?:of )?this (?:sub)?committee\b"
        r"|\bamendment no\.?\s*\d|(?<!union )(?<!house )\bcalendar no\.?\s*\d|\bsenate and (?:the )?house of representatives\b"),
    "joint": re.compile(r"\bjoint (?:economic |select |congressional )?committee|\bjoint commission\b"),
    "commission": re.compile(r"\bcommission\b"),
}
JUDGMENT_CHAMBERS = frozenset({"executive_or_external"})


_STATE_NAMES = "|".join(sorted((k for k in STATE_CODES if len(k) > 4 and k != "washington"), key=len, reverse=True))
LOOKALIKE_BEFORE_RE = re.compile(  # a state legislature, or a career line ("28 years in the United States Senate")
    rf"(?:(?<!of )\bstate|legislature|assembly|commonwealth|\b(?:{_STATE_NAMES}))\W+(?:\w+\W+)?$"
    r"|\b(?:worked|served|serving|employed|staffer|aide|intern|retired|former)\b(?:\W+\w+){0,4}\W+$|\byears (?:in|on|with) (?:the )?$")
LOOKALIKE_AFTER_RE = re.compile(r"\W*bill\s+(?:no\.?\s*)?\d")  # a state "Senate Bill 12"
MEMBER_TITLE_RES = {
    "house": re.compile(r"\b(?:Rep\.|Representative|Congressman|Congresswoman|REP\.|REPRESENTATIVE|CONGRESSMAN|CONGRESSWOMAN)\s+[A-Z][\w'\-]+"),
    "senate": re.compile(r"\b(?:Sen\.|Senator|SEN\.|SENATOR)\s+[A-Z][\w'\-]+"),
}
MEMBER_EMPLOYER_RE = re.compile(r"\b(?:to|for|of|with|under|office of|staff|aide)\W+(?:the\W+)?$", re.I)
ROLL_COLUMN_RES = {"house": re.compile(r"\brepresentatives?\b.{0,80}\b(?:ayes?|yeas?|nays?|noes|present|not voting)\b"),
                   "senate": re.compile(r"\bsenators?\b.{0,80}\b(?:ayes?|yeas?|nays?|noes|present|not voting)\b")}
HEADER_LINES = {"house": {"HOUSE OF REPRESENTATIVES", "U.S. HOUSE OF REPRESENTATIVES"},
                "senate": {"SENATE", "UNITED STATES SENATE", "U.S. SENATE", "U. S. SENATE"}}


def all_committee_cores() -> set[tuple[str, ...]]:
    if "all_cores" not in _COMMITTEE_CACHE:
        _COMMITTEE_CACHE["all_cores"] = {c for cs in committee_groups()[1].values() for c in cs}
    return _COMMITTEE_CACHE["all_cores"]


def one_chamber_cores() -> dict[str, list[tuple[str, ...]]]:
    """Committee names that exist in one chamber only (production's code table): naming one states the chamber."""
    if "one_chamber" not in _COMMITTEE_CACHE:
        _, by_code, chamber = committee_groups()
        where: dict[tuple[str, ...], set[str]] = defaultdict(set)
        for code, cores in by_code.items():
            for c in cores:
                where[c].add(chamber.get(code, ""))
        out: dict[str, list[tuple[str, ...]]] = defaultdict(list)
        for c, chs in where.items():
            if len(chs) == 1 and c:
                out[next(iter(chs))].append(c)
        _COMMITTEE_CACHE["one_chamber"] = out
    return _COMMITTEE_CACHE["one_chamber"]


_COMMITTEE_CACHE: dict[str, Any] = {}


def chamber_evident(ch: str, v: View) -> bool:
    """Owner 2026-11-18: the chamber is stated when the text makes it evident: its name, a committee name carrying it
    or existing in it alone, a House or Senate office building or room code in a location line, the committee's own
    site (x.house.gov, x.senate.gov), a standalone 'SENATE' / 'HOUSE OF REPRESENTATIVES' header, 'Rep.'/'Senator'
    before a member's name in the head (or 'presiding'), a roll sheet with a Representative or Senator column, prose
    about this proceeding ('the full Senate', 'reported ... to the House'). Look-alikes fail: the White House, a state
    legislature, a career line, a state bill, a member who employs the witness."""
    rx = CHAMBER_RES[ch]
    flat = v.flat
    for m in rx.finditer(flat):
        if not LOOKALIKE_BEFORE_RE.search(flat[max(0, m.start() - 45): m.start()]) and not LOOKALIKE_AFTER_RE.match(flat[m.end(): m.end() + 14]):
            return True
    if HEADER_LINES[ch] & v.header_lines or ROLL_COLUMN_RES[ch].search(flat[:3000]):
        return True
    for m in MEMBER_TITLE_RES[ch].finditer(v.orig):
        presiding = re.match(r"[\w'\-]+(?:\W+\w+){0,6}?\W+(?:presiding|for (?:the|your|his|her) (?:kind )?invitation|for inviting|invited me)",
                             v.orig[m.end() - 1: m.end() + 90], re.I)
        if presiding or (m.start() < OWN_HEAD_CHARS and not MEMBER_EMPLOYER_RE.search(v.orig[max(0, m.start() - 25): m.start()])):
            return True
    if ONE_CHAMBER_ACRONYM_RES[ch].search(v.orig):
        return True
    if any(p > 0 and v.toks[p - 1] == ch for c in all_committee_cores() if c for p in v.pos.get(c[0], ())
           if tuple(v.toks[p: p + len(c)]) == c or len(c) == 1):
        return True
    return any(named_as_committee(c, v, "committee") for c in one_chamber_cores().get(ch, ())) or any(
        named_as_committee(c, v, "subcommittee") for c in one_chamber_subcommittee_cores().get(ch, ()))


def named_as_committee(core: tuple[str, ...], v: View, head: str) -> bool:
    """The committee's name with the word committee (or subcommittee) beside it: a bare 'climate crisis' in a
    biography is not the Select Committee on the Climate Crisis."""
    if not core_hit(core, v, head=head):
        return False
    heads = [q for h in {head, head + "s"} for q in v.near_all(h)]
    return any(abs(p - q) <= len(core) + 4 for p in v.near_all(core[0]) for q in heads)


ONE_CHAMBER_ACRONYM_RES = {  # usual acronyms of committees that exist in one chamber only (upper case as printed)
    "house": re.compile(r"\b(?:HASC|HFAC|HPSCI|HSGAC-House)\b"),
    "senate": re.compile(r"\b(?:EPW|HSGAC|SFRC|SSCI|SASC)\b"),
}


def one_chamber_subcommittee_cores() -> dict[str, list[tuple[str, ...]]]:
    """Subcommittee names (two or more words, from the roster's subcommittee table) found under one chamber only."""
    if "one_chamber_sub" not in _COMMITTEE_CACHE:
        meta = json.loads((A_DIR / "lookups_and_gold" / "rosters_lookup_v6.json").read_text(encoding="utf-8"))["subcommittees_meta"]
        where: dict[tuple[str, ...], set[str]] = defaultdict(set)
        for m in meta.values():
            for name in [m.get("name") or ""] + [x.get("name") or "" for x in m.get("names") or []]:
                core = committee_core(name)
                if len(core) >= 2:
                    where[core].add(str(m.get("chamber") or ""))
        out: dict[str, list[tuple[str, ...]]] = defaultdict(list)
        for c, chs in where.items():
            if len(chs) == 1:
                out[next(iter(chs))].append(c)
        _COMMITTEE_CACHE["one_chamber_sub"] = out
    return _COMMITTEE_CACHE["one_chamber_sub"]


def chamber_stated(value: Any, v: View) -> bool:
    """`joint` is also stated by a text that states both chambers (the gold's value for bicameral documents)."""
    key = ("chamber", value)
    if key not in v.memo:
        if value in ("house", "senate"):
            v.memo[key] = chamber_evident(str(value), v)
        else:
            rx = CHAMBER_RES.get(str(value))
            v.memo[key] = bool(rx and rx.search(v.flat)) or (
                value == "joint" and chamber_stated("house", v) and chamber_stated("senate", v))
    return v.memo[key]


def _span_hit(core: list[str], v: View, span: int, need: int, wide: bool = False) -> bool:
    """Some window of `span` token positions holds at least `need` distinct tokens of `core` (OCR-tolerant)."""
    uniq = list(dict.fromkeys(core))
    events = sorted((p, t) for t in uniq for p in (v.near_all(t) if wide else v.near(t)))
    if len({t for _, t in events}) < need:
        return False
    live: Counter[str] = Counter()
    j = 0
    for p, t in events:
        live[t] += 1
        while events[j][0] < p - span:
            live[events[j][1]] -= 1
            if not live[events[j][1]]:
                del live[events[j][1]]
            j += 1
        if len(live) >= need:
            return True
    return False


def window_hit(core: list[str], v: View, slack: int = 6) -> bool:
    """All content words within a span of 2 x len + 4 positions; values over `slack` words may miss one word in
    `slack` (OCR damage, a dropped article). Exact forms first, then the OCR and run-in forms."""
    n = len(dict.fromkeys(core))
    if n == 0:
        return True
    span, need = 2 * len(core) + 4, n - (n - 1) // slack
    return _span_hit(core, v, span, need) or _span_hit(core, v, span, need, wide=True)


LEAD_PREFIX = ("us", "united states", "the")


def content_tokens(text: str) -> list[str]:
    toks = [t for t in norm_tokens(fold(text)) if t not in STOP]
    return toks[1:] if len(toks) > 1 and toks[0] == "us" else toks  # U.S. / United States before a name is canonical form


def acronym_hit(value: str, v: View) -> bool:
    """An acronym is a usual form of a name: a parenthetical one in the value ("(SNAP)") or the initials of its
    capitalized words (GAO, DOD with 'of', HHS without the leading 'Department'), as an upper-case word."""
    cands = set(re.findall(r"\(([A-Za-z][A-Za-z&.\-]{1,11})\)", value))
    words = [w for w in re.findall(r"[A-Z][a-z']*|[a-z][a-z']*", re.sub(r"\([^)]*\)|\bU\.\s?S\.|\bUnited States\b", " ", value))]
    caps = [w for w in words if w[0].isupper() or w.lower() == "of"]
    for seq in (caps, caps[1:]):
        letters = "".join(w[0].upper() for w in seq if w.lower() not in STOP)
        with_of = "".join(w[0].upper() if w.lower() not in STOP else ("O" if w.lower() == "of" else "") for w in seq)
        cands |= {letters, with_of}
        cands |= {"US" + letters, letters[:-1]}  # USAID; CDC for Centers for Disease Control and Prevention
    cands = {re.sub(r"[.\s]", "", c) for c in cands}
    two = {c for c in cands if len(c) == 2 and len([w for w in caps if w.lower() not in STOP]) <= 3}  # UN, UK, VA
    return any((len(c) >= 3 or c in two) and re.search(rf"(?<![A-Za-z]){re.escape(c)}(?![A-Za-z])", v.orig) for c in cands)


def initials_index(v: View) -> str:
    """First letters of the source's content tokens, one per token (for acronyms the value uses and the text
    spells out: AASHTO = American Association of State Highway and Transportation Officials)."""
    if "initials" not in v.memo:
        v.memo["initials"] = "".join(t[0] for t in v.toks if t not in STOP)
    return v.memo["initials"]


def reverse_acronym_hit(part: str, v: View) -> bool:
    """Every upper-case word of 3+ letters in the value is spelled out in the text (initials of consecutive
    content words), and every other content word is stated."""
    acrs = [w for w in re.findall(r"\b[A-Z]{3,}\b", part)]
    if not acrs or not all(a.lower() in initials_index(v) for a in acrs):
        return False
    rest = [t for t in content_tokens(re.sub(r"\b[A-Z]{3,}\b", " ", part))]
    return window_hit(rest, v) if rest else True


PART_SPLIT = {  # how a value splits into parts, each of which must be stated
    "title": r"\s*(?:[:;|\u2014\u2013\u2026]|\s-\s|\.\.\.)\s*",   # "RESCHEDULED: Oversight of ...", elisions
    "name": r"\s*[;|]\s*|,\s+",                      # "Brennan Center for Justice, New York University School of Law"
    "plain": r"\s*[;|]\s*",
}
ROLE_WORDS = frozenset({"nominee", "nominated", "nomination"})  # "Nominee to be ..." is the role, written by the reviewer


def phrase_stated(value: Any, v: View, mode: str = "name", drop: frozenset[str] = frozenset()) -> bool:
    """A name or phrase is stated when each part has its content words close together in the source
    (window_hit), its parenthetical-free long form does, its acronym does, or the text spells out its acronym."""
    key = ("phrase", value, mode, drop)
    if key not in v.memo:
        ok = True
        for part in re.split(PART_SPLIT[mode], str(value)):
            long = re.sub(r"\([^)]*\)", " ", part)
            if not (window_hit([t for t in content_tokens(long) if t not in drop], v) or acronym_hit(part, v)
                    or reverse_acronym_hit(part, v)):
                ok = False
                break
        v.memo[key] = ok
    return v.memo[key]


def title_coverage(value: Any, v: View) -> float:
    """Share of the title's content words that occur anywhere in the text (OCR and run-in forms included)."""
    toks = list(dict.fromkeys(content_tokens(re.sub(r"\([^)]*\)", " ", str(value)))))
    return sum(bool(v.near_all(t)) or (len(t) >= 5 and t.isalpha() and scan_damaged_hit(t, v)) for t in toks) / len(toks) if toks else 1.0


def title_cut_by_field(value: Any, v: View) -> bool:
    """A form field cut the title mid-word ("Examining Local Needs in Di"): the text holds a prefix of the title,
    at least 20 characters and half its length, that stops inside a word."""
    vt = " ".join(WORD_RE.findall(fold(str(value))))
    tt = " ".join(v.seq)
    for k in range(len(vt) - 1, max(19, len(vt) // 2) - 1, -1):
        if vt[k - 1] != " " and vt[k] != " " and (vt[:k] + " ") in tt:
            return True
    return False


def title_stated(value: Any, v: View) -> bool:
    """A title is stated when its words sit together (one missing in four for OCR), when all its words are in the
    text (a title assembled from the text's own heading and bill list), or when a form field cut it mid-word."""
    key = ("title", value)
    if key not in v.memo:
        v.memo[key] = (all(window_hit(content_tokens(re.sub(r"\([^)]*\)", " ", part)), v, slack=4) or acronym_hit(part, v)
                           for part in re.split(PART_SPLIT["title"], str(value)))
                       or title_coverage(value, v) == 1.0 or title_cut_by_field(value, v))
    return v.memo[key]


GENERIC = frozenset("""inc corp co ltd llc lp plc foundation inst institution center council assn society organization
company group coalition alliance network partnership project league federation union club system natl intl american
us federal state the program initiative""".split())


def short_name_stated(value: Any, v: View) -> bool:
    """An organisation or program named by its distinctive words alone ("Heritage" for The Heritage Foundation,
    "Clayton Christensen" for the Clayton Christensen Institute); words like Department, Office, Agency and Bureau
    stay required."""
    for part in re.split(PART_SPLIT["name"], str(value)):
        toks = content_tokens(re.sub(r"\([^)]*\)", " ", part))
        dist = [t for t in toks if t not in GENERIC]
        if not (dist and window_hit(dist, v)) and not window_hit(toks, v) and not acronym_hit(part, v) and not reverse_acronym_hit(part, v):
            return False
    return True


def person_title_stated(value: Any, v: View) -> bool:
    return phrase_stated(value, v, "name", ROLE_WORDS)


def program_stated(value: Any, v: View) -> bool:
    return phrase_stated(value, v, "plain") or short_name_stated(value, v)


EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
PHONE_RE = re.compile(r"\+?\(?\d[\d\s().\-]{6,}\d")


def contact_stated(value: Any, v: View) -> bool:
    """Emails as written (spaces ignored), phone numbers by their last ten digits, the rest as a phrase."""
    s = str(value)
    for e in EMAIL_RE.findall(s):
        if fold(e) not in v.nows and re.sub(r"[^a-z0-9]", "", fold(e)) not in {run for run, _ in v.runs}:
            return False
    for ph in PHONE_RE.findall(s):
        if re.sub(r"\D", "", ph)[-10:] not in v.digits:
            return False
    rest = PHONE_RE.sub(" ", EMAIL_RE.sub(" ", s))
    return all(phrase_stated(part, v) for part in re.split(r"\s*[|;,()]\s*", rest) if WORD_RE.search(part))


COMMITTEE_STOP = STOP | {"house", "senate", "committee", "subcommittee", "select", "permanent", "special", "standing",
                         "us", "united", "states", "congressional"}


def committee_core(name: str) -> tuple[str, ...]:
    return tuple(t for t in norm_tokens(fold(name)) if t not in COMMITTEE_STOP)


def _committee_groups() -> tuple[dict[tuple[str, ...], set[tuple[str, ...]]], dict[str, set[tuple[str, ...]]], dict[str, str]]:
    """Era names of one committee are one committee (production's own code table): core -> every core of its
    committee, parent code -> cores, parent code -> chamber."""
    from .. import provenance_rules_v5 as pr

    codes = set(pr._STATIC_COMMITTEE_CANONICAL) | {"hsed00", "hsgo00", "hssy00", "hsfa00", "hsso00", "hsii00",
                                                   "hsba00", "hsif00", "ssga00", "hlvc00"}
    by_code: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    chamber: dict[str, str] = {}
    for code in codes:
        for c in (None, *range(80, 121)):
            hit = pr.committee_code_to_canonical(code, c)
            if hit:
                chamber[code] = hit[0]
                by_code[code].add(committee_core(hit[1]))
    by_core: dict[tuple[str, ...], set[tuple[str, ...]]] = defaultdict(set)
    for cores in by_code.values():
        for core in cores:
            by_core[core] |= cores
    return by_core, by_code, chamber


_COMMITTEES: list[Any] = []


def committee_groups() -> tuple[dict[tuple[str, ...], set[tuple[str, ...]]], dict[str, set[tuple[str, ...]]], dict[str, str]]:
    if not _COMMITTEES:
        _COMMITTEES.extend(_committee_groups())
    return _COMMITTEES[0], _COMMITTEES[1], _COMMITTEES[2]


def core_hit(core: tuple[str, ...], v: View, head: str = "committee") -> bool:
    """A one-word core needs 'committee' (or 'subcommittee') within three words: "Committee on the Judiciary",
    "Judiciary Committee"; a longer core needs all its words close together."""
    if not core:
        return True
    if len(core) == 1:  # a committee is also named in its subcommittee's name ("House Appropriations Subcommittee")
        heads = [q for h in ({head, "subcommittee"} if head == "committee" else {head}) for q in v.near_all(h)]
        return any(abs(p - q) <= 3 for p in v.near(core[0]) for q in heads)
    return window_hit(list(core), v)


def label_chamber_word(name: str) -> str | None:
    m = re.match(r"\s*(house|senate)\b", fold(name))
    return m.group(1) if m else None


def committee_named(value: Any, v: View) -> bool:
    """The text names the committee in any usual form: "Committee on X", "X Committee", an era name of the same
    committee, or the chamber's short form ("Senate Commerce Committee", "Senate Homeland Security Committee")."""
    key = ("committee_named", value)
    if key not in v.memo:
        core = committee_core(str(value))
        cores = committee_groups()[0].get(core) or {core}
        ok = any(core_hit(c, v) for c in cores)
        ch = label_chamber_word(str(value))
        if not ok:  # the committee's usual acronym, as printed (E&C, HSGAC, EPW, W&M)
            fams = {code for code, cs in committee_groups()[1].items() if core in cs}
            ok = any(code in fams and re.search(rf"(?<![A-Za-z&]){re.escape(a)}(?![A-Za-z&])", v.orig)
                     for a, code in COMMITTEE_ACRONYMS.items())
        if not ok and ch and len(core) >= 2:
            ok = any(re.search(rf"\b{ch} {re.escape(' '.join(c[:k]))} committee", " ".join(v.toks))
                     for c in cores for k in (1, 2) if len(c) > k)
        v.memo[key] = ok
    return v.memo[key]


COMMITTEE_ACRONYMS = {"E&C": "hsif00", "T&I": "hspw00", "W&M": "hswm00", "HSGAC": "ssga00", "HELP": "sshr00",
                      "EPW": "ssev00", "SFRC": "ssfr00", "HFAC": "hsfa00", "HASC": "hsas00", "SASC": "ssas00",
                      "OGR": "hsgo00", "HPSCI": "hlig00", "SSCI": "slin00", "JEC": "jsec00", "JCT": "jstx00",
                      "ENR": "sseg00", "HVAC": "hsvr00", "SVAC": "ssva00", "HSC": "hshm00"}


def chamber_before_name(ch: str, value: Any, v: View) -> bool:
    """The chamber word right before the committee's name ("House Judiciary", "House Smull Business")."""
    core = committee_core(str(value))
    return bool(core) and any(p > 0 and v.toks[p - 1] == ch for p in v.near_all(core[0]))


def committee_stated(value: Any, v: View) -> bool:
    """Named (committee_named, or the chamber's short form "House Judiciary"), and a chamber written into the label's
    name is itself evident in the text (or stands right before the name)."""
    ch = label_chamber_word(str(value))
    short = bool(ch) and chamber_before_name(ch, value, v)
    return (committee_named(value, v) or short) and (ch is None or short or chamber_stated(ch, v))


def subcommittee_stated(value: Any, v: View) -> bool:
    """The name ("Subcommittee on X", "X Subcommittee"), without an Appropriations "and Related Agencies/Programs"
    tail, or its short form: the first one or two words of the name right before "Subcommittee" ("Financial
    Services Subcommittee", "THUD" excepted)."""
    key = ("subcommittee", value)
    if key not in v.memo:
        name = re.sub(r",?\s+and\s+related\s+(?:agencies|programs)\s*$", "", str(value), flags=re.I)
        core = committee_core(re.sub(r"^subcommittee on departments? of\s+", "Subcommittee on ", name, flags=re.I))
        ok = core_hit(core, v, head="subcommittee")
        if not ok and len(core) >= 2:
            joined = " ".join(v.toks)
            sep = r"(?:\s+(?:and|of|the|on|for))?\s+"
            ok = any(re.search(rf"\b{sep.join(map(re.escape, core[:k]))} subcommittee\b", joined) for k in (1, 2))
        v.memo[key] = ok
    return v.memo[key]


MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")


UK_MONTHS = ("сiчня|січня", "лютого", "березня", "квiтня|квітня", "травня", "червня", "липня", "серпня", "вересня", "жовтня",
             "листопада", "грудня")


def _mon(m: int) -> str:
    full = MONTHS[m - 1]
    return rf"(?:{full}|{full[:3]}{'|sept' if m == 9 else ''}|{UK_MONTHS[m - 1]})\.?"


FUZZY_DATE_PATTERNS: set[str] = set()


def _remember_fuzzy(rx: re.Pattern[str]) -> re.Pattern[str]:
    FUZZY_DATE_PATTERNS.add(rx.pattern)
    return rx


def _fuzzy_month(m: int) -> str:
    """The month name with any one letter misread by OCR (Mune for June)."""
    full = MONTHS[m - 1]
    return "|".join(full[:i] + "[a-z0-9]" + full[i + 1:] for i in range(len(full))) if len(full) >= 4 else full


def _fuzzy_year(y: int) -> str:
    """The year with any one digit misread (3013 for 2013), used only after an exact month and day."""
    ys = str(y)
    return "|".join(ys[:i] + r"\d" + ys[i + 1:] for i in range(4))


@functools.lru_cache(maxsize=None)
def date_res(value: str) -> list[re.Pattern[str]]:
    """A date is stated in any written format: "March 20, 2017", "Mar. 20th, 2017", "20 March 2017", "the 20th day
    of March, 2017", inside a range ("March 19-20, 2017"), "3/20/2017", "03.20.17", "2017-03-20", "20170320";
    or as "March 20" when the year is written elsewhere in the text. YYYY-MM is stated by "March 2017" or any date
    in that month; YYYY by the year."""
    parts = [int(x) for x in value.split("-")]
    y, yy = parts[0], f"{parts[0] % 100:02d}"
    if len(parts) == 1:
        return [re.compile(rf"(?<!\d){y}(?!\d)")]
    m = parts[1]
    mon = _mon(m)
    if len(parts) == 2:
        return [re.compile(rf"\b{mon},?\s*(?:\d{{1,2}}(?:st|nd|rd|th)?\b[\s,\-–]*(?:\d{{1,2}}(?:st|nd|rd|th)?,?\s*)?)?{y}"),
                re.compile(rf"(?<!\d)0?{m}\s?[/.\-]\s?(?:\d{{1,2}}\s?[/.\-]\s?)?(?:{y}|{yy})(?!\d)"),
                re.compile(rf"(?<!\d){y}\s?[/.\-]\s?0?{m}(?!\d)|(?<!\d){y}{m:02d}\d\d(?!\d)"),
                re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s*(?:day of\s*)?{mon},?\s*{y}")]
    d = parts[2]
    dd = rf"0?{d}(?:st|nd|rd|th|d)?"
    rng = r"\s*(?:-|–|—|and|&|to|through|,)\s*"
    return [
        re.compile(rf"\b{mon},?\s*(?:\d{{1,2}}(?:st|nd|rd|th)?{rng})*{dd}\b(?:{rng}\d{{1,2}}(?:st|nd|rd|th)?\b)*,?\s*{y}"),
        re.compile(rf"(?<!\d)0?{m}[/1l|]0?{d}[/1l|]{y}(?!\d)"),
        re.compile(rf"\b{dd}\s*(?:day of\s*)?{mon},?\s*{y}"),
        re.compile(rf"(?<!\d)0?{m}\s?[/.\-\u2022\u00b7:\\,|]\s?0?{d}\s?[/.\-\u2022\u00b7:\\,|]\s?(?:{y}|{yy})(?!\d)"),
        _remember_fuzzy(re.compile(rf"\b(?:{_fuzzy_month(m)})\.?\s*{dd}\b,?\s*{y}|\b{mon}\s*{dd}\b,?\s*(?:{_fuzzy_year(y)})(?!\d)")),
        re.compile(rf"(?<!\d){y}\s?[/.\-]\s?0?{m}\s?[/.\-]\s?0?{d}(?!\d)"),
        re.compile(rf"(?<!\d)(?:{y}{m:02d}{d:02d}|{m:02d}{d:02d}{y}|{m:02d}{d:02d}{yy})(?!\d)"),
    ]


@functools.lru_cache(maxsize=None)
def month_day_res(value: str) -> tuple[re.Pattern[str], re.Pattern[str]] | None:
    """"March 20" with no year after it, and the year on its own: together they state a full date."""
    parts = [int(x) for x in value.split("-")]
    if len(parts) != 3:
        return None
    rng = r"\s*(?:-|\u2013|\u2014|and|&|to|through|,)\s*"
    md = re.compile(rf"\b{_mon(parts[1])}\s*(?:\d{{1,2}}(?:st|nd|rd|th)?{rng})*0?{parts[2]}(?:st|nd|rd|th|d)?\b(?!,?\s*\d{{4}})")
    return md, re.compile(rf"(?<!\d){parts[0]}(?!\d)")


def date_stated(value: Any, v: View) -> bool:
    key = ("date", value)
    if key not in v.memo:
        ok = bool(re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", str(value))) and any(rx.search(v.flat) or rx.search(ocr_digits(v)) for rx in date_res(str(value)))
        md = None if ok or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)) else month_day_res(str(value))
        v.memo[key] = ok or bool(md and md[0].search(v.flat) and md[1].search(v.flat))
    return v.memo[key]


def ocr_digits(v: View) -> str:
    """The folded text with scan-damaged digits read as digits where they touch digits or date separators: l | i and a
    single ! as 1, o as 0 ('4:14.ll' is 4:14.11, '1/25/!1' is 1/25/11; '2|9/!!' is left unread), and a day misread as
    a letter before the year ('MARCH Z, 2017' is March 2, 2017)."""
    if "ocr_digits" not in v.memo:
        t = v.flat
        for _ in range(2):
            t = re.sub(r"(?<=[\d/.:\-])(?:[l|i]+|!(?!!))(?=[\d\s/.:\-,]|$)|(?<=[\s/.:\-])(?:[l|i]+|!(?!!))(?=\d)",
                       lambda m: "1" * len(m.group(0)), t)
            t = re.sub(r"(?<=\d)o(?=\d)|(?<=\d)o\b", "0", t)
        t = re.sub(r"\b((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s)([zsoli])(?=,?\s*(?:19|20)\d\d\b)",
                   lambda m: m.group(1) + "25011"["zsoli".index(m.group(2))], t)
        v.memo["ocr_digits"] = t
    return v.memo["ocr_digits"]


def span_stated(value: Any, v: View) -> bool:
    """date_spans are verbatim substrings, compared on letters and digits only (OCR separators: '3.3-11')."""
    return re.sub(r"[^a-z0-9]", "", fold(str(value))) in v.alnum


def org_stated(value: Any, v: View) -> bool:
    return (phrase_stated(value, v) or short_name_stated(value, v)
            or (bool(re.search(r"\bcommittee\b", str(value), re.I)) and committee_stated(value, v)))


def name_stated(value: Any, v: View) -> bool:
    return person_named(str(value), v)


def ref_stated(value: Any, v: View) -> bool:
    return ref_shown(str(value), v)


# field -> (matcher, rule id, what it reads). Order is the report's order.
FACT_FIELDS: dict[str, tuple[Callable[[Any, View], bool], str]] = {
    "congress": (congress_stated, "P01_congress_stated"),
    "chamber": (chamber_stated, "P02_chamber_stated"),
    "committees": (committee_stated, "P03_committees_stated"),
    "subcommittees": (subcommittee_stated, "P04_subcommittees_stated"),
    "doc_date": (date_stated, "P05_doc_date_stated"),
    "event_date": (date_stated, "P06_event_date_stated"),
    "due_date": (date_stated, "P07_due_date_stated"),
    "date_spans": (span_stated, "P08_date_spans_verbatim"),
    "event_title": (title_stated, "P09_event_title_stated"),
    "verbatim_title": (title_stated, "P10_verbatim_title_stated"),
    "issuer_org": (org_stated, "P11_issuer_org_stated"),
    "orgs_mentioned": (org_stated, "P12_orgs_mentioned_stated"),
    "places": (phrase_stated, "P13_places_stated"),
    "programs": (program_stated, "P14_programs_stated"),
    "person_org": (org_stated, "P15_person_org_stated"),
    "person_title": (person_title_stated, "P16_person_title_stated"),
    "person_address": (contact_stated, "P17_person_address_stated"),
    "person_name": (name_stated, "T02_person_named_in_text"),
    "refs": (ref_stated, "T03_ref_numbers_in_text"),
}
LABEL_FIELDS = ("congress", "chamber", "committees", "subcommittees", "doc_date", "event_date", "due_date", "date_spans",
                "event_title", "verbatim_title", "issuer_org", "orgs_mentioned", "places", "programs", "refs")


def label_facts(label: dict[str, Any] | None) -> list[tuple[str, Any]]:
    """(field, value) for every fact in a label. Person fields: org (and an organization persona's name), title,
    address (work_addr, official_contact); person names (people only) are T01/T02's."""
    lab = label or {}
    out: list[tuple[str, Any]] = []
    for f in LABEL_FIELDS:
        v = lab.get(f)
        for x in (v if isinstance(v, list) else [v] if v not in (None, "") else []):
            if f == "refs" and not ref_number_groups(str(x)):
                continue  # refs with no identifying number (rule:House Rule XI) are not checked
            out.append((f, x))
    for p in lab.get("personas") or []:
        if p.get("entity_type") == "organization":
            out.append(("person_org", p.get("name")))
        else:
            out.append(("person_name", p.get("name")))
        for k, f in (("org", "person_org"), ("title", "person_title"), ("work_addr", "person_address"),
                     ("official_contact", "person_address")):
            if p.get(k):
                out.append((f, p[k]))
    return [(f, x) for f, x in out if x not in (None, "")]


def known_dict(r: Row) -> dict[str, Any]:
    try:
        d = json.loads(r.known) if r.known.strip().startswith("{") else {}
    except Exception:  # noqa: BLE001
        d = {}
    return d if isinstance(d, dict) else {}


_SUBCOMMITTEE_NAMES: dict[str, str] = {}


def subcommittee_name_for_code(code: str) -> str | None:
    if not _SUBCOMMITTEE_NAMES:
        meta = json.loads((A_DIR / "lookups_and_gold" / "rosters_lookup_v6.json").read_text(encoding="utf-8"))["subcommittees_meta"]
        _SUBCOMMITTEE_NAMES.update({k: v.get("name") or "" for k, v in meta.items()})
    return _SUBCOMMITTEE_NAMES.get(code)


def in_known(f: str, value: Any, r: Row) -> bool:
    """The value is what the `known` hint says: congress, a chamber in chambers, a committee whose code (any era
    name) is in cmt, a subcommittee whose roster name is, or the date (a YYYY-MM or YYYY value: its prefix)."""
    k = known_dict(r)
    if not k:
        return False
    if f == "congress":
        return k.get("congress") == value
    if f == "chamber":
        return value in (k.get("chambers") or [])
    codes = [str(c).lower() for c in k.get("cmt") or []]
    if f == "committees":
        from ..provenance_rules_v5 import normalize_parent_committee_code
        _, by_code, _ = committee_groups()
        core = committee_core(str(value))
        return any(core in by_code.get(normalize_parent_committee_code(c) or "", ()) for c in codes)
    if f == "subcommittees":
        return any(committee_core(subcommittee_name_for_code(c) or "") == committee_core(str(value)) for c in codes if not c.endswith("00"))
    if f in ("doc_date", "event_date", "due_date"):
        return bool(k.get("date")) and str(k["date"]).startswith(str(value))
    return False


def derived(f: str, value: Any, r: Row) -> bool:
    """Congress from a year written in the text (a calculation, never a statement)."""
    v = r.view("text")
    if f == "congress" and isinstance(value, int):
        return any(congress_of_year(int(y)) == value for y in set(re.findall(r"(?<!\d)(1[789]\d\d|20[0-3]\d)(?!\d)", v.flat)))
    return False


def committee_named_without_chamber(f: str, value: Any, r: Row) -> bool:
    return f == "committees" and committee_named(value, r.view("text"))


def fact_source(f: str, value: Any, r: Row) -> str:
    """Where a fact occurs (SOURCES), or 'unchecked'."""
    if f == "chamber" and value in JUDGMENT_CHAMBERS:
        return "unchecked"
    match = FACT_FIELDS[f][0]
    if match(value, r.view("text")):
        return "text"
    if committee_named_without_chamber(f, value, r):
        return "derived"  # the text names the committee; the chamber in the label's name comes from knowledge
    if r.window and r.window != r.text and match(value, r.view("window")):
        return "window"
    if in_known(f, value, r):
        return "known"
    if r.filename and match(value, r.view("filename")):
        return "filename"
    if derived(f, value, r):
        return "derived"
    return "none"


def row_provenance(r: Row) -> list[tuple[str, Any, str]]:
    return [(f, x, fact_source(f, x, r)) for f, x in label_facts(r.label)] if usable_or_masthead(r) else []


def usable_or_masthead(r: Row) -> bool:
    """Every label that can carry facts (usable and the masthead statuses; the triage statuses carry none)."""
    return r.label is not None and r.status not in ERROR_STATUSES


def provenance_of(rows: list[Row], ctx: "Ctx") -> dict[str, list[tuple[str, Any, str]]]:
    if "provenance" not in ctx.cache:  # one classification pass, read by every P rule and the report table
        ctx.cache["provenance"] = {r.lk: row_provenance(r) for r in rows}
    return ctx.cache["provenance"]


def provenance_check(field_name: str) -> "Check":
    def run(rows: list[Row], ctx: "Ctx") -> tuple[int, dict[str, str]]:
        prov = provenance_of(rows, ctx)
        out, checked = {}, 0
        for r in rows:
            facts = [(x, s) for f, x, s in prov.get(r.lk, []) if f == field_name]
            checked += bool(facts)
            bad = [f"{x} [{s}]" for x, s in facts if s not in ("text", "unchecked")]
            if bad:
                out[r.lk] = f"{field_name}: " + "; ".join(bad)
        return checked, out
    return run


def provenance_table(rows: list[Row], ctx: "Ctx", top_kinds: int = 8) -> dict[str, Any]:
    """Counts of facts by source: overall, per split and for the largest kinds."""
    prov = provenance_of(rows, ctx)
    by_lk = {r.lk: r for r in rows}

    def table(keys: set[str]) -> dict[str, dict[str, int]]:
        t: dict[str, Counter[str]] = {f: Counter() for f in FACT_FIELDS}
        for lk in keys:
            for f, _, s in prov.get(lk, []):
                t[f][s] += 1
        return {f: dict(c) for f, c in t.items() if c}
    kinds = Counter(r.cls for r in rows if r.split != "excluded").most_common(top_kinds)
    return {
        "sources": [*SOURCES, "unchecked"],
        "overall": table({r.lk for r in rows if r.split != "excluded"}),
        "by_split": {s: table({r.lk for r in rows if r.split == s}) for s in sorted({r.split for r in rows})},
        "by_kind": {k: table({lk for lk, r in by_lk.items() if r.cls == k and r.split != "excluded"}) for k, _ in kinds},
    }


# doc_date is filled only when the text states a document date (owner decision 2026-11-18, replacing "doc_date is
# the event date"). A doc_date equal to event_date passes only when that date is written as the document's own:
# right after a dating word ("Dated", "Date:", "Issued", "Released", "Posted", "Submitted", "Revised", "As of"),
# within 120 characters after a release header ("For Immediate Release", "Press Release", "Media Advisory"), or as
# a letter's date line (a salutation within 400 characters after it).
DOC_DATE_BEFORE_RE = re.compile(  # 'Date:' is not here: on a vote sheet or form it is the event date (rubric)
    r"(?:\bdated|\badopted|\bapproved|\bagreed to|\bissued|\breleased|\bposted|\bpublished|\bupdated|\brevised"
    r"|\bsubmitted|\bsigned|\bas of)(?: on)?\W{0,6}(?:[a-z]+day,?\s*)?$")
RELEASE_RE = re.compile(r"for immediate release|press release|news release|media advisory|\bcontact:")
RELEASE_PAGE_RE = re.compile(r"press release|for immediate release|news release|media advisory|share on (?:facebook|x|twitter|linkedin)|\btags?:")
PRINTED_DATE_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s{0,2}(\d{1,2})(?:st|nd|rd|th)?,?\s{0,2}((?:19|20)\d\d)\b"
    r"|\b(\d{1,2})(?:st|nd|rd|th)?\s(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s((?:19|20)\d\d)\b"
    r"|(?<![\d/])(\d{1,2})/(\d{1,2})/((?:19|20)?\d\d)(?![\d/])|\b((?:19|20)\d\d)-(\d\d)-(\d\d)\b")
EVENT_TIED_KINDS = frozenset({"hearing_transcript", "witness_statement", "witness_list", "member_opening_statement",
                              "committee_vote", "attendance_quorum_sheet", "meeting_results", "event_web_page",
                              "hearing_notice", "markup_notice", "witness_biography", "truth_in_testimony_disclosure"})


def printed_dates(flat: str) -> set[str]:
    """Every full date printed in the folded text, as YYYY-MM-DD."""
    mon = {m[:3]: i + 1 for i, m in enumerate(MONTHS)}
    out = set()
    for m in PRINTED_DATE_RE.finditer(flat):
        g = m.groups()
        try:
            if g[0]:
                y, mo, d = int(g[2]), mon[g[0]], int(g[1])
            elif g[3]:
                y, mo, d = int(g[5]), mon[g[4]], int(g[3])
            elif g[6]:
                y = int(g[8]); y = y + (2000 if y < 50 else 1900) if y < 100 else y
                mo, d = int(g[6]), int(g[7])
            else:
                y, mo, d = int(g[9]), int(g[10]), int(g[11])
            if 1 <= mo <= 12 and 1 <= d <= 31:
                out.add(f"{y:04d}-{mo:02d}-{d:02d}")
        except (KeyError, ValueError):
            pass
    return out
SALUTATION_RE = re.compile(r"\bdear\b")
EVENT_CUE_RE = re.compile(r"hearing|meeting|mark-?\s?up|roundtable|briefing|before the|testimony|testify|statement of|session"
                          r"|will (?:be held|convene|meet)|\b\d{1,2}:\d{2}|\b[ap]\.\s?m\b|\broom\b|office building")


def date_line_alone(r: Row, d: str) -> bool:
    """The date written on a line of its own (a weekday allowed) with no event words on the two lines either side:
    the date line of a memo, report or cover, not the line saying when a hearing is held."""
    lines = [fold(x).strip() for x in r.text.splitlines()]
    for i, line in enumerate(lines):
        bare = re.sub(r"^(?:[a-z]+day,?\s*)", "", line).strip(" .,:;")
        if bare and any(rx.fullmatch(bare) for rx in date_res(d)):
            near = " ".join(lines[max(0, i - 2): i] + lines[i + 1: i + 3])
            if not EVENT_CUE_RE.search(near):
                return True
    return False


def date_positions(value: str, flat: str) -> list[int]:
    return sorted({m.start() for rx in date_res(value) for m in rx.finditer(flat)})


def mention_only(r: Row) -> str | None:
    """T05: the label's Congress occurs in the text only as a passing mention, not as the document's own. (Dates and
    chambers are not judged: a document's own date or chamber also sits late in the text, in an 'Adopted:' line, a
    report footer or a contact block, so position cannot tell a masthead from a mention for them.)"""
    c = (r.label or {}).get("congress")
    if not isinstance(c, int):
        return None
    ms = [own for n, _, own in view_congress_mentions(r.view("text")) if n == c]
    if ms and not any(ms):
        return f"congress {c} only in a passing mention (navigation, a link, a cited bill, or past {OWN_HEAD_CHARS} characters)"
    return None


def own_date(r: Row, d: str) -> bool:
    """The text marks this date as the document's own: after a dating word (Dated, Date:, Adopted:, Submitted,
    Issued, Released, Revised, As of), within 120 characters after a release header, on a release page (press-release
    or share-bar cues in the head) in the head or after a Washington dateline, a letter's date line (a salutation
    within 400 characters after it), a date line of its own away from event words (documents not tied to an event: a letter's or memo's date line), or beside a JCT
    document number. The date under a hearing title is the event date, never the document's own."""
    flat = r.view("text").flat
    release_page = bool(RELEASE_PAGE_RE.search(flat[:OWN_HEAD_CHARS]))
    for rx in date_res(d):
        for m in rx.finditer(flat):
            before, after = flat[max(0, m.start() - 160): m.start()], flat[m.end(): m.end() + 400]
            if (DOC_DATE_BEFORE_RE.search(before[-40:]) or RELEASE_RE.search(before[-120:]) or SALUTATION_RE.search(after)
                    or re.search(r"\bjc[xs]-\d", before[-200:] + after[:200])
                    or (release_page and (m.start() < OWN_HEAD_CHARS or re.search(r"\bwashington\b\W{0,4}(?:d\.?\s?c\.?)?\W{0,4}$", before[-30:])))):
                return True
    return not event_tied(r.label or {}) and date_line_alone(r, d)


def event_tied(lab: dict[str, Any]) -> bool:
    return bool(lab.get("event_type") or lab.get("event_title")) or lab.get("primary_kind") in EVENT_TIED_KINDS


def date_in_one_place(r: Row) -> str | None:
    """T04 (rubric, Dates): a date goes in exactly one place. A doc_date equal to event_date needs the text to mark it
    as the document's own; an event-tied document whose only printed date sits in doc_date (no event_date) has it in
    the wrong field."""
    lab = r.label or {}
    d, e = lab.get("doc_date"), lab.get("event_date")
    if not d:
        return None
    if d == e:
        return None if own_date(r, str(d)) else f"doc_date {d} repeats event_date; the text does not mark it as the document's own"
    if not e and event_tied(lab) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d)) and printed_dates(r.view("text").flat) == {d} \
            and not own_date(r, str(d)):
        return f"doc_date {d} is the only printed date of an event document: it is the event_date"
    return None


def initial_beside_surname(r: Row) -> str | None:
    """T06: a name written as an initial and a surname ("E. Cummings") needs that initial beside the surname in the
    text (the token or one before it); otherwise the initial came from somewhere else (a normaliser artifact)."""
    bad = []
    seq = r.view("text").seq
    for p in people(r):
        m = re.fullmatch(r"\s*([A-Za-z])\.?\s+([A-Za-z][\w'\-]+)\s*", str(p.get("name") or ""))
        if not m:
            continue
        ini, sur = m.group(1).lower(), "".join(WORD_RE.findall(fold(m.group(2))))
        pos = [i for i, w in enumerate(seq) if w == sur or (len(sur) >= 5 and within_one_edit(sur, w))]
        if pos and not any(ini in seq[max(0, i - 2): i] for i in pos):
            bad.append(f"{p['name']} (the text has {sur} but not {ini.upper()}. beside it)")
    return "; ".join(bad) or None


PARTY_WORDS = {"r": "republican", "d": "democrat", "i": "independent"}


def party_state_basis(r: Row) -> str | None:
    """T08: a person's party_state ("R-GA") needs the text to give that party and state near the person's name
    ("(R-GA)", "R-Ga.", "[R-GA-1]", "Republican of Georgia", "Rep. Carter (R-Georgia)"); a state-only value needs the
    state there. Within 120 characters of the surname, anywhere when the surname is not found."""
    flat = r.view("text").flat
    bad = []
    for p in people(r):
        ps = str(p.get("party_state") or "").strip()
        if not ps:
            continue
        m = re.fullmatch(r"(?:([RDI])\s*-\s*)?([A-Z]{2})(?:\s*-\s*\d{1,2}|-AL)?", ps.upper())
        if not m:
            continue
        party, code = (m.group(1) or "").lower(), m.group(2).lower()
        names = [k for k, c in STATE_CODES.items() if c == code]
        st = "|".join([re.escape(code)] + [re.escape(n) for n in names])
        pats = [rf"(?<![a-z]){party}\s*[-\u2013.,/]\s*(?:{st})\.?(?![a-z])", rf"\b{PARTY_WORDS[party]}\w*\W+(?:\w+\W+){{0,2}}(?:{st})\b",
                rf"\b(?:{st})\W+(?:\w+\W+){{0,1}}\(?{party}\)"] if party else [rf"(?<![a-z])(?:{st})(?![a-z])"]
        sur = surname(str(p.get("name") or ""))
        spans = [(max(0, i.start() - 120), i.end() + 120) for i in re.finditer(rf"\b{re.escape(sur)}\b", flat)] if sur else []
        hays = [flat[a:b] for a, b in spans] or [flat]
        if not any(re.search(pt, h) for pt in pats for h in hays):
            bad.append(f"{p.get('name')}: {ps}")
    return ("party_state with no basis near the name: " + "; ".join(bad)) if bad else None


def venue_basis(r: Row) -> str | None:
    """T09: a venue needs a basis in the text: every room number in it (2+ digit groups) occurs in the text, and at
    least one of its place words does (a building, city or 'virtual'). T09b separately needs a place or mode for any venue_kind; a
    venue T09 fails."""
    venue = str((r.label or {}).get("venue") or "").strip()
    if not venue:
        return None
    v = r.view("text")
    nums = [g for g in re.findall(r"\d{2,}", venue)]
    missing = [g for g in nums if g not in v.nows]
    words = [t for t in content_tokens(venue) if t.isalpha() and t not in {"room", "rm", "suite", "ste", "building", "bldg",
                                                                           "office", "floor", "hall", "dc", "wa", "house", "senate"}]
    no_words = bool(words) and not any(v.near_all(t) or (len(t) >= 5 and scan_damaged_hit(t, v)) for t in words)
    if missing or no_words:
        why = (f"room number {', '.join(missing)} nowhere in the text" if missing else "") + \
              ("; " if missing and no_words else "") + ("none of its place words in the text" if no_words else "")
        return f"venue {venue!r}: {why}"
    return None


PLACE_OR_MODE_RE = re.compile(
    r"\b(?:rayburn|longworth|cannon|dirksen|hart|russell|capitol|visitor center)\b|\broom\s*[a-z]?-?\d|\brm\.?\s*\d"
    r"|\b(?:hvc|svc|sd|sh|sr|h)-?\s?\d{2,3}\b|\b\d{3,4}\s*[rlc]hob\b|office building|\blocation:|\bheld (?:at|in)\b"
    r"|virtual|remote(?:ly)?\b|webex|zoom|online|video ?conference|teleconference|livestream|field hearing")


def venue_kind_basis(r: Row) -> str | None:
    """T09b: a venue_kind needs the text to give a place or mode for the event: a room, building or location line,
    'virtual'/'remote'/'Webex', or 'field hearing'."""
    vk = (r.label or {}).get("venue_kind")
    if vk and not PLACE_OR_MODE_RE.search(r.view("text").flat):
        return f"venue_kind {vk}: the text gives no place or mode for the event"
    return None


_LETTER_RUN_RE = re.compile(r"[^\W\d_]{3,}")
_WORD_SHAPE_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+")
_VOWEL_RE = re.compile(r"[aeiouyAEIOUY]")
_CONSONANT_RUN_RE = re.compile(r"[bcdfghjklmnpqrstvwxz]{5,}")


WITNESS_ADDITIONS_PATH = N_DIR / "lookups_and_gold" / "transcript_witness_additions.jsonl"


def transcript_witnesses(rows: list[Row], ctx: "Ctx") -> tuple[int, dict[str, str]]:
    """T24 (rubric: hearing transcripts list their witnesses): every person the witness-additions pass found on a
    transcript is in that transcript's label as a witness, matched by surname. Not run while the file is missing."""
    if not WITNESS_ADDITIONS_PATH.is_file():
        ctx.cache.setdefault("notes", {})["T24_transcript_witnesses_listed"] = f"not run: {WITNESS_ADDITIONS_PATH.name} does not exist yet"
        return 0, {}
    need: dict[str, list[str]] = defaultdict(list)
    for line in WITNESS_ADDITIONS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            e = json.loads(line)
            name = str(e.get("name") or e.get("person") or e.get("witness") or "")
            if name:
                need[str(e.get("link_key_hex") or "").lower()].append(name)
    out, checked = {}, 0
    for r in rows:
        if r.lk not in need or r.label is None:
            continue
        checked += 1
        have = {surname(str(p.get("name") or "")) for p in (r.label.get("personas") or []) if p.get("role") == "witness"}
        missing = [n for n in need[r.lk] if surname(n) not in have]
        if missing:
            out[r.lk] = "witnesses the transcript names, missing from the label: " + "; ".join(missing)
    return checked, out


def readable_share(text: str) -> float:
    """Share of the words (3+ letters) in the first 9,000 characters that are word-shaped (T07)."""
    toks = _LETTER_RUN_RE.findall((text or "")[:9000])
    if not toks:
        return 1.0
    ok = sum(bool(_WORD_SHAPE_RE.fullmatch(t)) and bool(_VOWEL_RE.search(t)) and not _CONSONANT_RUN_RE.search(t.lower())
             for t in toks)
    return ok / len(toks)


def unreadable_text(r: Row) -> str | None:
    share, non_latin = readable_share(r.text), r.view("text").non_latin
    if share >= 0.5 and not non_latin:  # surname grids on vote sheets score 0.55; font cipher scores under 0.2
        return None
    why = "mostly non-Latin script" if non_latin else "font cipher or garbled scan"
    return f"readable share {share:.2f} ({why}): a person must read this text; rulings go in adjudications.jsonl"


@dataclass(frozen=True)
class KindTemplate:
    """A text or filename pattern that fixes the kind. Matching rows are checked; a mismatch fails."""
    id: str
    severity: str
    rubric: str
    detect: str                                  # regex on the folded head of the text
    expect_kinds: tuple[str, ...] = ()           # allowed primary_kind (usable labels)
    expect_secondary: tuple[str, ...] = ()       # must all be in secondary_kinds
    expect_status: str | None = None
    head_chars: int = 1500
    filename: str | None = None                  # regex on the filename, must also match
    unless: str | None = None                    # regex on the folded head that cancels the match
    max_chars: int | None = None                 # only texts at most this long (whitespace-collapsed)
    only_if_kind: tuple[str, ...] = ()           # only judge rows labeled with one of these kinds
    formats: tuple[str, ...] = ()                # only rows of these file formats (the row's own format)
    blind: str = ""

    def matches(self, r: Row) -> bool:
        if r.label is None:
            return False
        flat = re.sub(r"\s+", " ", fold(r.text)).strip()
        if self.max_chars is not None and len(flat) > self.max_chars:
            return False
        if self.filename and not re.search(self.filename, r.filename or "", re.I):
            return False
        if self.only_if_kind and r.kind not in self.only_if_kind:
            return False
        if self.formats and r.fmt not in self.formats:
            return False
        head = flat[: self.head_chars]
        return bool(re.search(self.detect, head)) and not (self.unless and re.search(self.unless, head))

    def violation(self, r: Row) -> str | None:
        lab = r.label or {}
        if self.expect_status is not None:
            return None if r.status == self.expect_status else f"status {r.status}/{r.kind}, expected {self.expect_status}"
        if r.status != "usable":
            return f"status {r.status}, expected usable {'/'.join(self.expect_kinds)}"
        if self.expect_kinds and r.kind not in self.expect_kinds:
            return f"kind {r.kind}, expected {'/'.join(self.expect_kinds)}"
        missing = [k for k in self.expect_secondary if k not in (lab.get("secondary_kinds") or [])]
        return f"secondary_kinds lacks {', '.join(missing)}" if missing else None


SFR = r"statement for the record|submitted for the record|for the hearing record"
TESTIMONY = (r"\btestimony of\b|\btestimony before\b|\bstatement of .{0,200}\bbefore the\b|\bbefore the (sub)?committee\b"
             r"|thank you for (the opportunity|inviting me|having me) to (testify|appear)|\bappear before\b|\bto testify\b")
KIND_TEMPLATES: tuple[KindTemplate, ...] = (
    KindTemplate(
        "T10_jct_description", "error",
        "V6.5: JCT \"Description of H.R. ...\" pamphlets and one-page substitute descriptions (JCX-NN-YY): `section_by_section`.",
        r"^.{0,300}description of\b.{0,1200}joint committee on taxation.{0,120}jcx-\d+-\d+",
        expect_kinds=("section_by_section",),
        blind="JCT descriptions whose title is not within the first 300 characters; non-JCT descriptions."),
    KindTemplate(
        "T11_jct_description_revenue", "warn",
        "V6.5: (JCT descriptions) add `revenue_or_cost_estimate` to `secondary_kinds` when it carries a revenue table or score.",
        r"^(?=.{0,300}description of\b.{0,1200}joint committee on taxation.{0,120}jcx-\d+-\d+)"
        r"(?=.*(estimated (federal )?(fiscal year )?(budget|revenue) effects|fiscal years \[(millions|billions)|budget receipts))",
        expect_secondary=("revenue_or_cost_estimate",), head_chars=9000, only_if_kind=("section_by_section",),
        blind="Scores stated in other words; tables cut from the training text; descriptions still mis-kinded "
              "(T10 reports those first)."),
    KindTemplate(
        "T12_rules_committee_print_text", "error",
        "V6.5: Rules Committee Prints of bill text (\"TEXT OF H.R. ... [Showing the text of ...]\"): `bill_or_draft`, whatever the file format.",
        r"^.{0,300}rules committee print \d+ ?[-\u2013] ?\d+\b.{0,500}\[showing (the )?texts? ",
        unless=r"rules committee print \d+ ?[-\u2013] ?\d+\b.{0,40}(text of )?(the )?(house|senate) amendment to|comparing the base document|showing the differences",
        head_chars=1200, expect_kinds=("bill_or_draft",),
        blind="Prints of amendment text (left out on purpose); prints whose heading the extraction moved."),
    KindTemplate(
        "T13_treaty_transmittal_or_resolution", "error",
        "V6.5: Treaty paperwork: presidential transmittals, resolutions of advice and consent ... are all `treaty_document`.",
        r"message from the president of the united states.{0,400}transmitting|resolution of advice and consent to ratification.{0,300}resolved",
        unless=r"s\. hrg\.|hearing before", expect_kinds=("treaty_document",),
        blind="Transmittals without the standard heading; hearing transcripts on treaties are excluded on purpose."),
    KindTemplate(
        "T14_treaty_executive_report", "error",
        "V6.5: ... Senate Executive Reports on a treaty are all `treaty_document` (an Executive Report also gets `committee_report` in `secondary_kinds`).",
        r"exec(utive)?\.? (rept|report)\.?.{0,600}\[to accompany treaty doc",
        expect_kinds=("treaty_document",), expect_secondary=("committee_report",),
        blind="Executive reports whose accompany line is outside the first 1,500 characters."),
    KindTemplate(
        "T15_special_rule_report", "error",
        "V6.5: House Rules \"special rule\" reports (a numbered House Report providing for consideration of a bill): `committee_report`, with `committee_resolution` in `secondary_kinds`.",
        r"^(?=.*providing for (the )?consideration of)(?:(?=.*committee on rules,? submitted the following r ?e ?p ?o ?r ?t)"
        r"|(?=.{0,400}\bh\.\s?res\.\s?\d+.{0,400}(?:report no\.|h\.\s?rept\.|house report)\s*\d{2,3}\s?[\-\u2013]\s?\d+))",
        unless=r"bills to be considered|for the week of|pursuant to title 17 section 105", head_chars=3000, expect_kinds=("committee_report",), expect_secondary=("committee_resolution",),
        blind="Special rules whose report number or 'providing for consideration' falls past 3,000 characters; resolutions "
              "printed without the report number (the rubric's test needs it)."),
    KindTemplate(
        "T16_agenda_sheet", "warn",
        "V6.5: One-page meeting or markup agenda sheet (date, time, bullet agenda): `markup_notice`.",
        r"\bagenda\b.{0,200}\b(markup|business meeting|meeting)\b|\b(markup|business meeting|meeting)\b.{0,200}\bagenda\b",
        head_chars=400, max_chars=1500, filename=r"\.pdf$",
        unless=r"\bhearing\b|witness|resolved|attendance",
        expect_kinds=("markup_notice",),
        blind="Agenda sheets longer than 1,500 characters, not PDF, or without the word agenda near the top; hearing "
              "agendas (not covered); scraped event pages (event_web_page by rule)."),
    KindTemplate(
        "T17_announces_committee_action", "error",
        "V6.5: \"Announces Committee Action on H.R. ...\" releases (what a markup decided): `meeting_results`, with `press_release_or_fact_sheet` in `secondary_kinds`.",
        r"announces (sub)?committee (\w+ ){0,3}action", head_chars=600,
        expect_kinds=("meeting_results",), expect_secondary=("press_release_or_fact_sheet",),
        blind="The same release under other wording."),
    KindTemplate(
        "T18a_release_page_with_remarks", "warn",
        "V6.5: Committee web pages carrying a member's hearing remarks, as the page presents itself: a page the committee marks \"Press Release\" ... is `press_release_or_fact_sheet`, with `member_opening_statement` in `secondary_kinds`.",
        r"press release.{0,800}(opening (statement|remarks)|delivered the following|as prepared for delivery)",
        unless=r"floor (remarks|statement)|on the (house|senate) floor", formats=("html",), head_chars=1500,
        expect_kinds=("press_release_or_fact_sheet",), expect_secondary=("member_opening_statement",),
        blind="Pages that headline with a quote instead of a 'Press Release' mark (not detected); scraped pages whose "
              "mark sits past 1,500 characters of site chrome."),
    KindTemplate(
        "T18b_opening_remarks_page", "warn",
        "V6.5: ... A page titled \"Opening Remarks\" or \"Opening Statement\" is `member_opening_statement`.",
        r"^.{0,250}\bopening (remarks|statement)\b", unless=r"press release|floor (remarks|statement)",
        formats=("html",), head_chars=1500, expect_kinds=("member_opening_statement",),
        blind="Titles past 250 characters of site chrome; whether the page sits in a news section (the secondary "
              "press_release_or_fact_sheet is not checked)."),
    KindTemplate(
        "T19_witness_invitation_letter", "error",
        "V6.5: Letters asking someone to testify, including \"Dear Colleague\" Member Day letters: `witness_invitation`.",
        r"\b(i|we) (would like to |cordially |hereby )?invite you to (testify|appear)\b|(i am|we are) writing to (request your testimony|invite you to testify)"
        r"|\bwrite to invite you to testify|\b(i|we) (write to )?request that you( or your designee)? (testify|appear)\b",
        head_chars=3000, unless=r"thank you for (the|your) invitation", expect_kinds=("witness_invitation",),
        blind="Invitations worded otherwise; an invitation quoted inside another document."),
    KindTemplate(
        "T20_gsa_va_lease_resolution", "error",
        "V6.5: GSA and VA lease or prospectus resolutions: `gsa_prospectus_or_property`, with `committee_resolution` in `secondary_kinds`.",
        r"resolved by the committee on (transportation and infrastructure|environment and public works|veterans' affairs).{0,400}(\u00a7 ?33(07|15)|prospectus|\blease\b)",
        head_chars=2500, expect_kinds=("gsa_prospectus_or_property",), expect_secondary=("committee_resolution",),
        blind="Resolutions whose resolving clause is past 2,500 characters."),
    KindTemplate(
        "T21_placeholder_page", "error",
        "V6.5: Pages with no document content (download-redirect \"please wait\" pages, a sheet holding only a video link, empty bodies): `status: \"stub_or_blank\"`.",
        r"please wait.{0,40}download|your (file )?download will begin|^.{0,160}https?://(www\.)?(youtube\.com|youtu\.be|vimeo\.com)\S*$",
        max_chars=300, expect_status="stub_or_blank",
        blind="Placeholders over 300 characters (site chrome around a redirect); other video hosts; [EMPTY_BODY] rows "
              "(D10 refuses them outright)."),
    KindTemplate(
        "T22_sfr_submitted_not_testimony", "warn",
        "V6.5: Statements for the record: decide from the text ... A statement the text says was submitted for the record by someone who did not appear is `public_comment_or_submission`. The filename's slot does not decide it.",
        SFR, unless=TESTIMONY, head_chars=2500, only_if_kind=("witness_statement",),
        expect_kinds=("public_comment_or_submission",),
        blind="Whether the author appeared (the text rarely says 'did not appear'; for-the-record wording without any "
              "testimony wording stands in for it), hence warn."),
    KindTemplate(
        "T23_testimony_presented", "warn",
        "V6.5: Testimony presented to the committee (\"Testimony of ...\", \"Statement of ... before the Committee\", an address to the chair as a witness) is `witness_statement`. The filename's slot does not decide it.",
        TESTIMONY, unless=SFR, head_chars=2500, only_if_kind=("public_comment_or_submission",),
        expect_kinds=("witness_statement",),
        blind="Submissions that quote testimony wording; testimony worded otherwise. Warn: the text-only reading has not "
              "been checked against a blind read."),
)


# --------------------------------------------------------------------------------------------------------------
# Dataset layer
# --------------------------------------------------------------------------------------------------------------
def shingles(text: str) -> set[int]:
    w = WORD_RE.findall(fold(text))
    return {hash(tuple(w[i:i + SHINGLE_K])) for i in range(max(0, len(w) - SHINGLE_K + 1))}


# Near-duplicate classes (coordinator decision 2026-11-18). A pair at containment >= 0.9 is a RE-POST (same text,
# another filename or hearing: error) when both documents are nearly all shared (symmetric containment >= 0.95)
# and carry the same numbers (digit-token Jaccard >= 0.9). It is a TEMPLATE or edition sibling (same form, other
# content: warn, and the SSOT flags the test row seen_template) when the numbers differ (Jaccard < 0.9). Pairs in
# between are classified by reading, in REVIEWED_NEAR_DUPLICATES; an unreviewed pair there counts as a re-post.
# Calibrated on the 13 pairs read by L3 and C1 on 2026-11-18 (thin margins: re-post 3fdc6cb0 sits at 0.931).
REPOST_SYMMETRIC = 0.95
SAME_NUMBERS = 0.9
REVIEWED_NEAR_DUPLICATES = {  # (test link key, train link key) -> (class, why)
    ("3fdc6cb033021e21", "fec9a7db0967b9d4"): ("repost", "DHS press release filed at two hearings"),
    ("5e70b6a7b6c2822f", "a386fe06ccb33851"): ("template", "Travis biography; the train doc is his statement, whose window holds the same bio"),
    ("a2f53b7823a7d830", "11e9106e5fe529d3"): ("template", "invitation letters for one hearing, different invitee"),
}


def near_duplicate_pairs(rows: list[Row]) -> list[dict[str, Any]]:
    """Every (test row, training row) pair sharing >= 90% of the smaller doc's word 5-shingles, classified.
    Exact: one sorted (shingle, train doc) array and a bincount per test doc."""
    import numpy as np

    train = [r for r in rows if r.split == "train"]
    test = [r for r in rows if r.split in TEST_SPLITS]
    tr_sets = [shingles(r.text) for r in train]
    sizes = np.array([len(s) for s in tr_sets], dtype=np.int64)
    hs = np.fromiter((h for s in tr_sets for h in s), dtype=np.int64, count=int(sizes.sum()))
    ds = np.repeat(np.arange(len(train), dtype=np.int64), sizes)
    order = np.argsort(hs, kind="stable")
    hs, ds = hs[order], ds[order]
    pairs: list[dict[str, Any]] = []
    for r in test:
        s = shingles(r.text)
        if len(s) < 20:  # under 25 words: too short to tell a re-post from shared boilerplate
            continue
        q = np.fromiter(s, dtype=np.int64, count=len(s))
        lo, hi = np.searchsorted(hs, q, "left"), np.searchsorted(hs, q, "right")
        hit = hi > lo
        if not hit.any():
            continue
        idx = np.concatenate([np.arange(a, b) for a, b in zip(lo[hit], hi[hit])])
        overlap = np.bincount(ds[idx], minlength=len(train))
        cont = overlap / np.maximum(np.minimum(sizes, len(s)), 1)
        for j in np.flatnonzero((cont >= NEAR_DUP_CONTAINMENT) & (sizes >= 20)):
            t = train[int(j)]
            sym = float(overlap[j] / max(int(sizes[j]), len(s)))
            na, nb = set(DIGITS_RE.findall(r.text)), set(DIGITS_RE.findall(t.text))
            num_j = len(na & nb) / max(1, len(na | nb))
            reviewed = REVIEWED_NEAR_DUPLICATES.get((r.lk, t.lk))
            if reviewed:
                cls, why = reviewed[0], f"reviewed: {reviewed[1]}"
            elif num_j < SAME_NUMBERS:
                cls, why = "template", "numbers differ"
            elif sym >= REPOST_SYMMETRIC:
                cls, why = "repost", "same text and numbers"
            else:
                cls, why = "repost", "unreviewed: same numbers, symmetric containment under 0.95 (add to REVIEWED_NEAR_DUPLICATES)"
            pairs.append({"test": r.lk, "train": t.lk, "train_source": t.source, "class": cls,
                          "containment": round(float(cont[j]), 3), "symmetric": round(sym, 3), "numbers_jaccard": round(num_j, 2),
                          "why": why, "kinds": f"{r.cls} / {t.cls}"})
    return pairs


def near_dup_failures(rows: list[Row], ctx: "Ctx", cls: str) -> tuple[int, dict[str, str]]:
    if "near_dup_pairs" not in ctx.cache:  # computed once per check, read by D06a, D06b and D14
        ctx.cache["near_dup_pairs"] = near_duplicate_pairs(rows)
    pairs = ctx.cache["near_dup_pairs"]
    repost_rows = {p["test"] for p in pairs if p["class"] == "repost"}
    out: dict[str, str] = {}
    for p in pairs:
        if p["class"] != cls or (cls == "template" and p["test"] in repost_rows):
            continue
        out.setdefault(p["test"], f"{p['class']} of train {p['train']} ({p['train_source']}): containment {p['containment']}, "
                                  f"symmetric {p['symmetric']}, numbers {p['numbers_jaccard']}; {p['why']}; kinds {p['kinds']}")
    return sum(1 for r in rows if r.split in TEST_SPLITS), out


def seen_template_mismatch(rows: list[Row], ctx: "Ctx") -> tuple[int, dict[str, str]]:
    """SSOT rows: the seen_template flag is set exactly on the test rows D06b finds (catches a stale flag)."""
    ssot = [r for r in rows if "label_sha256" in r.raw and r.split in TEST_SPLITS]
    _, templates = near_dup_failures(rows, ctx, "template")
    out = {}
    for r in ssot:
        flagged, sibling = bool(r.raw.get("seen_template")), r.lk in templates
        if flagged != sibling:
            out[r.lk] = "seen_template set but no template sibling found" if flagged else "template sibling without seen_template"
    return len(ssot), out


def knowns_sent(r: Row) -> list[tuple[str, str]]:
    """The known strings the model is given for this row: the trainer's (queue first), plus, for blind sets, the
    row's own prompt known, which the scorer's val48/docs8 record sets send as stored."""
    out = [("trainer", r.known)]
    if r.split in BLIND_SPLITS and r.prompt_known != r.known:
        out.append(("blind record set", r.prompt_known))
    return [(who, k) for who, k in out if k.strip() not in ("", "<NONE>")]


def known_order_violation(r: Row) -> str | None:
    bad = []
    for who, known in knowns_sent(r):
        try:
            d = json.loads(known)
        except Exception:  # noqa: BLE001
            bad.append(f"{who}: known is not JSON: {known[:80]}")
            continue
        keys = list(d) if isinstance(d, dict) else []
        if keys != [k for k in KNOWN_KEY_ORDER if k in keys] or not set(keys) <= set(KNOWN_KEY_ORDER):
            bad.append(f"{who}: known key order {keys}")
    return "; ".join(bad) or None


def known_form_violation(r: Row) -> str | None:
    if known_order_violation(r):
        return None
    bad = [f"{who}: {k[:90]}" for who, k in knowns_sent(r)
           if k != json.dumps(json.loads(k), separators=(",", ":"), ensure_ascii=False)]
    return ("known not in production serialization: " + "; ".join(bad)) if bad else None


def blind_overlap_trainer_keys(rows: list[Row]) -> dict[str, str]:
    """Rows the trainer would silently drop because they share body hash, 600-char head or (filename, 200-char
    head) with a blind eval doc (the trainer's own keys, `load_blind_keys`)."""
    from ..gold import _norm_ws, load_blind_keys

    blind = load_blind_keys((VAL48_JSON, DOCS8_JSON))
    out = {}
    for r in rows:
        if r.split in BLIND_SPLITS:
            continue
        msgs = r.raw.get("messages") or [{}]
        m = re.search(r"\nText:\n(.*)\Z", str(msgs[0].get("content") or ""), re.S)
        norms = [_norm_ws(t) for t in (r.text, m.group(1) if m else "")]
        if str(r.raw.get("saved_body_hex") or "") in blind["body_sha"]:
            out[r.lk] = "trainer:body_sha"
        elif any(n and (n[:600] in blind["head600"] or (r.filename, n[:200]) in blind["fn_head200"]) for n in norms):
            out[r.lk] = "trainer:head600_or_filename_head200"
    return out


def dup_counts(rows: list[Row]) -> dict[str, str]:
    c = Counter(r.lk for r in rows)
    return {lk: f"link key appears {n} times ({', '.join(sorted({r.source for r in rows if r.lk == lk}))})"
            for lk, n in c.items() if n > 1 or not lk}


def same_doc_across_splits(rows: list[Row]) -> dict[str, str]:
    """Same saved body or doc key under different link keys in a training and a test split."""
    out: dict[str, str] = {}
    for key in ("saved_body_hex", "doc_key"):
        by: dict[str, list[Row]] = defaultdict(list)
        for r in rows:
            if r.split != "excluded" and r.raw.get(key):
                by[str(r.raw[key])].append(r)
        for v, rs in by.items():
            splits = {x.split for x in rs}
            if len(rs) > 1 and "train" in splits and splits & TEST_SPLITS:
                for x in rs:
                    if x.split in TEST_SPLITS:
                        out.setdefault(x.lk, f"{key} {v[:16]} shared with " + ", ".join(f"{y.lk}({y.split})" for y in rs if y is not x))
    return out


def heldout_membership(rows: list[Row]) -> tuple[int, dict[str, str]]:
    keys = load_heldout_keys()
    by = {r.lk: r for r in rows}
    out = {}
    for k in sorted(keys):
        r = by.get(k)
        if r is None:
            out[k] = "held-out key missing from the dataset"
        elif r.split == "excluded":
            if not str(r.raw.get("excluded_reason") or "").strip():
                out[k] = "excluded without excluded_reason"
        elif r.split != "heldout_v6_4":
            out[k] = f"held-out key in split {r.split}"
    stray = [r for r in rows if r.split == "heldout_v6_4" and r.lk not in keys]
    for r in stray:
        out[r.lk] = "row in heldout_v6_4 is not one of the 183 keys"
    return len(keys) + len(stray), out


def subcommittee_spelling_key(name: str) -> str:
    """Spelling-insensitive key: '&' = 'and', 'the' dropped, no commas or case."""
    k = re.sub(r"\bthe\b", " ", fold(name).replace("&", " and ").replace(",", " "))
    return re.sub(r"\s+", " ", k).strip()


def subcommittee_minority_spellings(rows: list[Row]) -> dict[str, str]:
    """Rows that spell a subcommittee differently from the dataset's majority spelling of the same name."""
    spellings: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        for s in (r.label or {}).get("subcommittees") or []:
            spellings[subcommittee_spelling_key(s)][s] += 1
    major = {k: c.most_common(1)[0][0] for k, c in spellings.items() if len(c) > 1}
    out = {}
    for r in rows:
        bad = [f"{s!r} -> {major[k]!r}" for s in (r.label or {}).get("subcommittees") or []
               if (k := subcommittee_spelling_key(s)) in major and s != major[k]]
        if bad:
            out[r.lk] = "; ".join(bad)
    return out


def split_validity(r: Row) -> str | None:
    if r.split not in SPLITS:
        return f"split {r.split!r} not in {SPLITS}"
    if r.split == "excluded" and not str(r.raw.get("excluded_reason") or "").strip():
        return "excluded without excluded_reason"
    return None


def forbidden_prompt_tokens(r: Row) -> str | None:
    msgs = r.raw.get("messages") or [{}]
    hay = {"prompt": str(msgs[0].get("content") or ""), "text": r.text}
    bad = [f"{tok} in {where}" for where, s in hay.items() for tok in ("<|think|>", "[EMPTY_BODY]") if tok in s]
    return "; ".join(bad) or None


# D15: nothing inferred is silently dropped. Sidecar field names for the fact fields.
SIGNAL_FIELDS = {"person_org": ("personas.org", "personas.name"), "person_title": ("personas.title",),
                 "person_address": ("personas.work_addr", "personas.official_contact"), "person_name": ("personas.name",)}
EXPORTED_SPLITS = frozenset({"train", "heldout_v6_4", "test_gapfill"})
SIGNAL_TO_FACT = {sf: f for f, sfs in SIGNAL_FIELDS.items() for sf in sfs if f != "person_org" or sf == "personas.org"}


def load_signal(paths: list[Path]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                e = json.loads(line)
                out[str(e["link_key_hex"])].append(e)
    return dict(out)


def original_labels() -> dict[str, dict[str, Any]]:
    out = {}
    for path in ORIGINAL_INPUTS:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                try:
                    out[str(row["link_key_hex"])] = json.loads(row["messages"][-1]["content"])
                except Exception:  # noqa: BLE001 - an unreadable original has nothing to compare
                    pass
    return out


def fact_key(f: str, value: Any) -> tuple[str, ...]:
    """Spelling-insensitive identity of a value: a respelling ('&' to 'and', a dropped chamber) is not a removal."""
    if f in ("committees", "subcommittees"):
        return committee_core(str(value))
    if f == "refs":
        return tuple(ref_number_groups(str(value)))
    return tuple(norm_tokens(fold(str(value))))


def surname(name: str) -> str:
    toks = WORD_RE.findall(fold(name))
    return toks[-1] if toks else ""


def removed_unstated(orig: dict[str, Any], new: dict[str, Any] | None, r: Row) -> list[tuple[str, Any, str]]:
    """Facts of the original label that are gone from the exported one (not merely respelled) and that the
    training text does not state: the values that must be in the sidecar. Facts of a person the export no longer
    lists are covered by that person's name."""
    new = new or {}
    have: dict[str, set[Any]] = defaultdict(set)
    for f, x in label_facts(new):
        have[f] |= {str(x), fact_key(f, x)}
    kept_people = {surname(str(p.get("name") or "")) for p in new.get("personas") or []}
    out = []
    for f, x in label_facts(orig):
        if str(x) in have[f] or fact_key(f, x) in have[f]:
            continue
        if f in ("person_org", "person_title", "person_address") and not any(
                str(p.get(k)) == str(x) and surname(str(p.get("name") or "")) in kept_people
                for p in orig.get("personas") or [] for k in ("org", "title", "work_addr", "official_contact", "name")):
            continue
        src = fact_source(f, x, r)
        if src not in ("text", "unchecked"):
            out.append((f, x, src))
    return out


def check_signal(rows: list[Row], ctx: "Ctx") -> tuple[int, dict[str, str]]:
    orig = ctx.cache["original_labels"] if "original_labels" in ctx.cache else ctx.cache.setdefault("original_labels", original_labels())
    out, checked = {}, 0
    for r in rows:
        if r.split not in EXPORTED_SPLITS or r.lk not in orig or r.label is None:
            continue
        checked += 1
        entries = r.raw.get("signal") if isinstance(r.raw.get("signal"), list) else ctx.signal.get(r.lk, [])
        logged = {(str(e.get("field")), str(e.get("value"))) for e in entries}
        logged |= {(str(e.get("field")), fact_key(SIGNAL_TO_FACT.get(str(e.get("field")), str(e.get("field"))), e.get("value")))
                   for e in entries}
        missing = [f"{f}: {x} [{src}]" for f, x, src in removed_unstated(orig[r.lk], r.label, r)
                   if not any((sf, str(x)) in logged or (sf, fact_key(f, x)) in logged for sf in SIGNAL_FIELDS.get(f, (f,)))]
        if missing:
            out[r.lk] = "removed without a signal entry: " + "; ".join(missing)
    return checked, out


def date_written(value: str, v: View) -> bool:
    """The date in a full written form (not 'March 28' with the year elsewhere, which a corrected date can share)."""
    return any(rx.search(v.flat) or rx.search(ocr_digits(v)) for rx in date_res(value) if rx.pattern not in FUZZY_DATE_PATTERNS)


def check_dates_kept(rows: list[Row], ctx: "Ctx") -> tuple[int, dict[str, str]]:
    orig = ctx.cache["original_labels"] if "original_labels" in ctx.cache else ctx.cache.setdefault("original_labels", original_labels())
    out, checked = {}, 0
    for r in rows:
        if r.split not in EXPORTED_SPLITS or r.lk not in orig or not usable_or_masthead(r):
            continue  # a triage status (stub, error page) carries no dates by rule L12
        checked += 1
        kept = [str(x) for x in (r.label.get("doc_date"), r.label.get("event_date")) if x]
        lost = [f"{f} {x}" for f in ("doc_date", "event_date") if (x := orig[r.lk].get(f))
                and not any(k.startswith(str(x)) for k in kept) and date_written(str(x), r.view("text"))]
        if lost:
            out[r.lk] = "stated date dropped from both fields: " + "; ".join(lost)
    return checked, out


def label_sha(r: Row) -> str | None:
    if "label_sha256" not in r.raw:
        return None
    got = hashlib.sha256(str(r.raw["messages"][-1]["content"]).encode("utf-8")).hexdigest()
    return None if got == r.raw["label_sha256"] else "label_sha256 does not match the label"


# --------------------------------------------------------------------------------------------------------------
# The rule table
# --------------------------------------------------------------------------------------------------------------
Check = Callable[[list[Row], "Ctx"], tuple[int, dict[str, str]]]


@dataclass
class Ctx:
    label_errors: dict[str, dict[str, str]]
    cache: dict[str, Any] = field(default_factory=dict)
    signal: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # link key -> sidecar entries (--signal)


@dataclass(frozen=True)
class Rule:
    id: str
    layer: str
    severity: str
    rubric: str
    check: str
    blind: str
    run: Check


def per_row(fn: Callable[[Row], str | None], applies: Callable[[Row], bool] = lambda r: True) -> Check:
    def run(rows: list[Row], ctx: Ctx) -> tuple[int, dict[str, str]]:
        sel = [r for r in rows if applies(r)]
        return len(sel), {r.lk: v for r in sel if (v := fn(r))}
    return run


def from_label_layer(rule_id: str) -> Check:
    def run(rows: list[Row], ctx: Ctx) -> tuple[int, dict[str, str]]:
        return len(rows), dict(ctx.label_errors.get(rule_id, {}))
    return run


def whole(fn: Callable[[list[Row]], dict[str, str]], applies: Callable[[Row], bool] = lambda r: True) -> Check:
    def run(rows: list[Row], ctx: Ctx) -> tuple[int, dict[str, str]]:
        return sum(1 for r in rows if applies(r)), fn(rows)
    return run


def usable(r: Row) -> bool:
    return r.label is not None and r.status == "usable"


SHAPE_RULES = [
    Rule("L00_shape", "label", "error", "Exact `DocMetaV4Causal` Schema (apply_batch_labels.py enforces 100% match)",
         "validate_docmeta_v4 / strict_validate_v4 pass and the label equals canonicalize_docmeta_v4(label).",
         "Values that are in-domain but wrong.", from_label_layer("L00_shape")),
    Rule("L01_compact_roundtrip", "label", "error", "The trainer trains on encode_v4_to_compact_v6(label).",
         "encode_v4_to_compact_v6 -> expand_compact_json_str_to_v4 returns the label unchanged, less refs and "
         "fiscal_years, which the wire omits by design (post_pass_v6 adds them).",
         "Whether the compact form is what production decodes (only that the round trip is lossless).",
         from_label_layer("L01_compact_roundtrip")),
    Rule("L02_title_gist_caps", "label", "error", "`composed_title`: 8..109 chars; `gist`: 4..22 words.",
         "The gold gate's caps on composed_title and gist (usable labels).", "Whether title and gist are grounded.",
         from_label_layer("L02_title_gist_caps")),
]

GOVERNING = "V6.5 governing rule: the source text is the source of truth; the filename, upload slot, `known`, rosters and memory never supply a value."
TEXT_RULES = [
    Rule("T01_name_tokens_in_text", "text", "error",
         "V6.5: Write a name as the text shows it ... Never supply a first or middle name from memory.",
         "Every token of every person's name (first, middle, suffix) occurs as a word in the training text (one OCR "
         "edit allowed on 5+ letter tokens; adjacent words run together count). The filename does not ground a name.",
         "Text cut by the trainer's token cap; a token found elsewhere in the text (common first names, single "
         "initials) or one edit from another word passes; organizations are P15's.", per_row(check_names_tokens, usable)),
    Rule("T02_person_named_in_text", "text", "error", "V6.5: A person who is not named in the text is not listed. " + GOVERNING,
         "At least one token of two or more letters of each person's name occurs in the training text (not the "
         "filename); the failure names where the name does occur.",
         "OCR damage beyond one edit (Sco,, for Scott) looks absent; a surname that occurs for another reason passes.",
         per_row(check_person_named, usable)),
    Rule("T03_ref_numbers_in_text", "text", "error",
         "V6.5: `refs`: only references whose identifying numbers appear in the text shown. " + GOVERNING,
         "Every identifying digit group (2+ digits; an act's year excluded; usc: section and fr: page only; "
         "date-form ids skipped) of every ref occurs in the training text, whitespace removed (not the filename).",
         "Refs with no 2-digit group (names, Roman-numeral rules); a group found inside another number or in an "
         "unrelated place passes; refs are not trained (the wire omits them), so this guards scoring only.",
         per_row(check_ref_numbers, lambda r: usable(r) and has_numeric_ref(r))),
    Rule("T04_date_in_one_place", "text", "error",
         "Rubric V6.5, Dates: a date goes in exactly one place. A document tied to a hearing, markup or meeting that "
         "prints a single date has it in event_date and no doc_date; doc_date is only for a date the text marks as the "
         "document's own (letter date line, press release dateline, Adopted:, Dated:, Submitted:, or a second date).",
         "A doc_date equal to event_date passes only when the text marks that date as the document's own (after a "
         "dating word incl. Adopted:/Submitted:; within 120 characters after a release header; on a release page in "
         "the head or after a Washington dateline; a letter's date line with a salutation after it; a date line of "
         "its own away from event words; beside a JCX number). A doc_date with no event_date fails when the document "
         "is event-tied (event_type, event_title or an event kind), prints exactly one full date, and does not mark "
         "it as its own.",
         "Own-date marks in other words; event ties the label does not record; documents whose single printed date "
         "is a print stamp.", per_row(date_in_one_place, usable_or_masthead)),
    Rule("T06_initial_beside_surname", "text", "error",
         "Owner 2026-11-18: an initial plus a surname where the text has no such initial beside the surname "
         "(\"E. Cummings\") is a normaliser artifact.",
         "A person named as one initial and a surname has that initial as one of the two words before the surname "
         "somewhere in the text (the surname matched exactly or one edit away).",
         "Initials after the surname; surnames the text lacks (T02 reports those).", per_row(initial_beside_surname, usable)),
    Rule("T08_party_state_basis", "text", "error",
         "Rubric V6.5, Interpret, do not invent: a value with no basis in the text could only have come from a roster "
         "or memory (\"R-GA\" on \"Rep. Buddy Carter\" when the text gives no party or state).",
         "Every person's party_state has its party and state in the text within 120 characters of the person's surname "
         "(\"(R-GA)\", \"R-Ga.\", \"[R-GA-1]\", \"Republican of Georgia\", \"Georgia (R)\"); a state-only value needs "
         "the state there. Anywhere in the text when the surname is not found.",
         "Party and state written apart from the name by more than 120 characters (a roster table); a state "
         "abbreviation that is also a word.", per_row(party_state_basis, usable)),
    Rule("T09_venue_basis", "text", "error",
         "Rubric V6.5, Interpret, do not invent (an independent review found venues whose room number appears nowhere "
         "in the text).",
         "The venue's room numbers (2+ digit groups) all occur in the text, whitespace removed, and at least one of its "
         "place words (building, city, 'virtual'; OCR and scan damage tolerated) does.",
         "A room number printed in another form ('Rm. 2-123'); a venue whose words are all generic.", per_row(venue_basis, usable)),
    Rule("T09b_venue_kind_basis", "text", "error",
         "Rubric V6.5, Interpret, do not invent; coordinator 2026-11-18: venue_kind needs a place or mode in the text.",
         "A label with venue_kind is on a text that gives a place or mode for the event: a room or room code "
         "(Room 2123, SD-366, HVC-210, 2123 RHOB), a House or Senate office building or the Capitol, a 'Location:' or "
         "'held at/in' line, 'virtual', 'remote', 'Webex', 'Zoom', 'online', 'videoconference', or 'field hearing'.",
         "Whether the kind matches the place (a virtual cue beside a capitol_room kind passes); places written "
         "without these words.",
         per_row(venue_kind_basis, usable)),
    Rule("T24_transcript_witnesses_listed", "text", "error",
         "Rubric V6.5, Hearing transcripts list their witnesses: every witness the transcript's own witness list or "
         "contents page names is a person in the label, role witness.",
         "Every person `transcript_witness_additions.jsonl` (a dedicated, quote-verified pass over the transcripts) "
         "lists for a transcript is in that transcript's label with role witness, matched by surname. Not run while the "
         "file is missing.", "Witnesses the pass did not find; two witnesses sharing a surname.", transcript_witnesses),
    Rule("T07_readable_text", "text", "warn",
         "Owner 2026-11-18: damaged or garbled text is still read (interpretation is not hallucination); rows the "
         "matchers cannot read are listed for a person, whose rulings go in adjudications.jsonl.",
         "The text is not mostly non-Latin, and at least 50% of the first 9,000 characters' words (3+ letters) are "
         "word-shaped (lower, Capitalized or UPPER case, a vowel, no five-consonant run).",
         "Readable text in another alphabet (counted unreadable here and listed as non-Latin); garble that happens "
         "to be word-shaped.", per_row(unreadable_text, usable_or_masthead)),
    Rule("T05_value_only_in_passing_mention", "text", "warn",
         "Coordinator 2026-11-18: 'stated in the text' means the document's own value (masthead, header, dateline), not "
         "site navigation, a citation of a bill from another Congress or a quoted title.",
         f"The label's congress is named only in passing, never as the document's own. A mention is passing when it sits "
         f"inside site navigation (a schedule or archive menu, or three or more different Congresses within 200 "
         f"characters), inside a link, after 'introduced/passed/enacted/during ... the', or past the first "
         f"{OWN_HEAD_CHARS} characters; a document number (Serial No., H. Rept., S. Hrg., BILLS-118) outside a link is own.",
         "A masthead that belongs to an attached older document (its letterhead counts as own, which it is for that "
         "document); a header past 1,500 characters of site chrome; a quoted title inside the first 1,500 characters; "
         "dates and chambers (position cannot tell their mastheads from mentions: 'Adopted:' lines, footers).",
         per_row(mention_only, usable_or_masthead)),
]

FACT_RULE_TEXT = {  # field -> (how a value is stated, what the matcher cannot see)
    "congress": ("ordinal ('118th Congress', '118th Cong.', '118th-congress'; scan damage '117h', '1i2th'), words "
                 "('One Hundred Eighteenth Congress'; misread words within two edits: 'FIFTHTEENTH'), or a printed "
                 "designator of the document (Serial No./Rept./Hrg./Doc./Print 118-NN, 'S. HR9. 106-344', "
                 "BILLS-/CHRG-/CRPT-/HHRG-118). A year never states it; a public-law number does not.",
                 "Whether the stated Congress is the document's (a text naming two Congresses passes either); public "
                 "law numbers are left out on purpose."),
    "chamber": ("evident to a careful reader (owner 2026-11-18): 'House of Representatives' / 'United States "
                "Senate' / 'U.S. House|Senate'; a committee name carrying the chamber or existing in one chamber only "
                "(Ways and Means, Finance); a House or Senate office building or room code (Rayburn, 2123 RHOB, SD-366); "
                "the committee's site (x.house.gov); a standalone SENATE header; 'Rep.'/'Senator' before a member's name "
                "in the head or 'presiding'; a Representative or Senator roll column; 'the full Senate', 'reported ... to "
                "the House'; S. Hrg., H./S. Rept. Look-alikes refused: the White House, a state legislature or state "
                "bill, a career line, a member who employs the witness. joint: a joint committee or both chambers; "
                "commission: 'Commission'. executive_or_external names no chamber and is not checked.",
                "A member title or office building that is a look-alike in other words; a chamber stated only past the "
                "head by a member title."),
    "committees": ("the core name (production's committee table, any era name of the same committee) as 'Committee on "
                   "X' / 'X Committee' (one-word cores need 'committee' within three words), its words close together; "
                   "a chamber in the label's name must itself be stated (chamber rule).",
                   "Acronyms (HELP, HSGAC) and short forms ('Senate Commerce Committee') fail; a name stated in "
                   "another role (a cited committee) passes."),
    "subcommittees": ("the core name with 'subcommittee' within three words for one-word cores ('Subcommittee on "
                      "Health', 'Health Subcommittee'), else all words close together.",
                      "Whether the stated subcommittee is the document's; renamed subcommittees."),
    "doc_date": ("any written format: 'March 20, 2017', 'Mar. 20th, 2017', '20 March 2017', '20th day of March, 2017', "
                 "inside a range ('March 19-20, 2017'), '3/20/2017', '03.20.17', '2017-03-20', '20170320', or 'March 20' "
                 "with the year written elsewhere; YYYY-MM by 'March 2017' or any date in that month; YYYY by the year.",
                 "Whether the stated date is the document's (see T04 for echoes of the event date)."),
    "event_title": ("its content words (case, punctuation, '&'/'and', U.S./US, state names and common abbreviations "
                    "folded) close together in the text; one word in six may be missing (OCR).",
                    "A title stated in pieces far apart; paraphrases close to the text pass."),
    "issuer_org": ("as event_title, or the name's acronym (GAO, DOD, HHS, a parenthetical '(SNAP)') as an upper-case "
                   "word; committee names by the committee rule.", "An organization named only by a short form "
                   "other than its initials (the VA, the Fed)."),
    "person_address": ("work_addr as a phrase; official_contact: emails as written, phone numbers by their last ten digits.",
                       "Addresses split across letterhead lines far apart."),
}
for _f, _same in (("event_date", "doc_date"), ("due_date", "doc_date"), ("verbatim_title", "event_title"),
                  ("orgs_mentioned", "issuer_org"), ("places", "event_title"), ("programs", "issuer_org"),
                  ("person_org", "issuer_org"), ("person_title", "event_title")):
    FACT_RULE_TEXT[_f] = FACT_RULE_TEXT[_same]
FACT_RULE_TEXT["date_spans"] = ("the span itself, case and whitespace ignored (spans are verbatim by definition).",
                                "OCR spacing inside digits.")
# Fields whose matcher measured under 95% correct on two blind reads (acronyms that are not initials such as Fed,
# EXIM, OHCHR, TALF; OCR damage; values translated from non-English text): reported, not blocking.
WARN_FACT_FIELDS = frozenset({"date_spans", "verbatim_title", "issuer_org", "orgs_mentioned", "places", "programs",
                              "person_org", "person_title", "person_address"})
def title_check(composed: bool) -> "Check":
    """P09 / P09b: failing event titles split by how many of their words the text has (60% or more: a partly
    composed title, warn; fewer: not stated, error)."""
    def run(rows: list[Row], ctx: "Ctx") -> tuple[int, dict[str, str]]:
        prov, by = provenance_of(rows, ctx), {r.lk: r for r in rows}
        out, checked = {}, 0
        for lk, facts in prov.items():
            vals = [(x, s) for f, x, s in facts if f == "event_title"]
            checked += bool(vals)
            bad = [f"{x} [{s}; words in text {title_coverage(x, by[lk].view('text')):.0%}]" for x, s in vals
                   if s not in ("text", "unchecked") and (title_coverage(x, by[lk].view("text")) >= 0.6) == composed]
            if bad:
                out[lk] = "event_title: " + "; ".join(bad)
        return checked, out
    return run


FACT_RULES = [
    Rule(rid, "text", "warn" if f in WARN_FACT_FIELDS else "error", GOVERNING,
         f"Every {f.replace('_', ' ')} value is stated in the training text: {FACT_RULE_TEXT[f][0]} The failure names "
         f"where the value does occur ({', '.join(SOURCES[1:])}).", FACT_RULE_TEXT[f][1],
         title_check(False) if f == "event_title" else provenance_check(f))
    for f, (_, rid) in FACT_FIELDS.items() if rid.startswith("P")
]
FACT_RULES.insert(next(i for i, r in enumerate(FACT_RULES) if r.id.startswith("P09")) + 1, Rule(
    "P09b_event_title_partly_composed", "text", "warn",
    "Owner 2026-11-18: a title assembled from the text's own words passes; the remaining composed-title cases are warn.",
    "An event title that fails P09's stated test but has at least 60% of its words in the text (a title partly "
    "composed by the reviewer).", "Whether the missing words are paraphrase or OCR damage.", title_check(True)))

DATASET_RULES = [
    Rule("D01_row_format", "dataset", "error", "gold_gate_v6_2.validate_gold_record (provenance, hex keys, 2-turn messages)",
         "The gold gate's row-format checks other than leakage and label shape.", "Whether provenance values are true.",
         from_label_layer("D01_row_format")),
    Rule("D02_link_key_unique", "dataset", "error", "One row per labeled document.",
         "Every link key is present and appears once across all inputs.", "The same document under two link keys (see D04).",
         whole(dup_counts)),
    Rule("D03_one_valid_split", "dataset", "error", "Every row in exactly one split.",
         f"split is one of {', '.join(SPLITS)}; excluded rows carry excluded_reason.", "Whether the split is the right one.",
         per_row(split_validity)),
    Rule("D04_same_doc_across_splits", "dataset", "error", "Nothing trained on is also tested.",
         "No saved_body_hex or doc_key is shared by a training row and a test row.", "Re-posts with different bytes (see D06).",
         whole(same_doc_across_splits, lambda r: r.split in TEST_SPLITS)),
    Rule("D05_heldout_183", "dataset", "error", "heldout_v6_4_183_link_keys.json fixes the held-out docs of the old gold.",
         "Each of the 183 keys is in heldout_v6_4 or excluded with a reason; no other row is in heldout_v6_4.",
         "Whether a held-out label was changed (by design it may be).", lambda rows, ctx: heldout_membership(rows)),
    Rule("D06a_test_repost_of_train", "dataset", "error", "Nothing trained on is also tested.",
         f"No test row is a re-post of a training row: containment >= {NEAR_DUP_CONTAINMENT} of the smaller doc's word "
         f"{SHINGLE_K}-shingles, symmetric containment >= {REPOST_SYMMETRIC} and digit-token Jaccard >= {SAME_NUMBERS} "
         "(pairs in between: REVIEWED_NEAR_DUPLICATES, else counted as re-posts).",
         "Texts under 20 shingles; re-posts windowed differently (under 0.9 containment, e.g. L3's slide deck at 0.72); "
         "the class thresholds rest on 13 read pairs.",
         lambda rows, ctx: near_dup_failures(rows, ctx, "repost")),
    Rule("D06b_test_template_sibling_of_train", "dataset", "warn",
         "Coordinator decision 2026-11-18: template or edition siblings are reported, and flagged seen_template in the SSOT.",
         f"Test rows at containment >= {NEAR_DUP_CONTAINMENT} with a training row whose numbers differ (same form, "
         "other content: vote sheets, lease resolutions, rules for another Congress).",
         "Siblings under 0.9 containment (L3 found more at 0.8 to 0.9); whether the differing content is what is scored.",
         lambda rows, ctx: near_dup_failures(rows, ctx, "template")),
    Rule("D07_known_key_order", "dataset", "error", "Prompts carry production `known`: congress, cmt, chambers, date.",
         "The known JSON the trainer sends (and, for blind sets, the one the scorer's record sets send) has keys "
         "in production order.", "Whether the known values are right.",
         per_row(known_order_violation)),
    Rule("D08_known_serialization", "dataset", "warn", "Prompts carry production `known` byte-for-byte.",
         "The known JSON uses the production serialization (compact separators), as the queue's known_json does.",
         "Rows in the queue (they take the queue's known by construction).", per_row(known_form_violation)),
    Rule("D09_blind_set_overlap", "dataset", "error", "Blind sets (val48, docs8) are never trained on or re-tested.",
         "No non-blind row matches a blind doc by the gold gate's keys or the trainer's load_blind_keys (rows the "
         "trainer would drop silently).", "Blind docs re-posted with different text heads.",
         lambda rows, ctx: (len(rows), {**(ctx.cache["blind_trainer"] if "blind_trainer" in ctx.cache else ctx.cache.setdefault("blind_trainer", blind_overlap_trainer_keys(rows))),
                                        **ctx.label_errors.get("D09_blind_set_overlap", {})})),
    Rule("D10_no_think_or_empty_body", "dataset", "error", "Training prompts are what production sends.",
         "No prompt or training text contains <|think|> or [EMPTY_BODY].", "Other template tokens.",
         per_row(forbidden_prompt_tokens)),
    Rule("D11_test_row_in_queue", "dataset", "warn", "The sweep scorer scores only test docs that have a queue row.",
         "Every test row (except blind sets, which carry their own text) has a production queue row.",
         "Nothing about label quality.", per_row(lambda r: None if r.in_queue else "no llm_queue row: the sweep scorer skips it",
                                                 lambda r: r.split in TEST_SPLITS - BLIND_SPLITS)),
    Rule("D12_label_sha256", "dataset", "error", "SSOT rows carry label_sha256 of their label string.",
         "label_sha256 (when present) equals sha256 of messages[-1].content.", "Rows without the field.",
         per_row(label_sha, lambda r: "label_sha256" in r.raw)),
    Rule("D13_subcommittee_majority_spelling", "dataset", "warn",
         "V6.5: Subcommittee names: the roster spelling (\"and\", not \"&\"; no leading \"the\").",
         "Every subcommittee uses the dataset's majority spelling of that name ('&'/'and', 'the', commas and case "
         "folded together).", "Whether the majority spelling is the roster spelling; names spelled one way only.",
         whole(subcommittee_minority_spellings, lambda r: bool((r.label or {}).get("subcommittees")))),
    Rule("D14_seen_template_flag", "dataset", "error", "The SSOT's seen_template flag is derived data and must stay true.",
         "On SSOT test rows, seen_template is set exactly on the rows D06b reports.",
         "Rows outside the SSOT format (no label_sha256).", seen_template_mismatch),
    Rule("D16_stated_date_not_lost", "dataset", "error",
         "Rubric V6.5, Dates: a stated date is never dropped from both fields.",
         "For every exported training and test row that may carry dates, each doc_date or event_date of the "
         "reviewer's original label that the training text writes in full is still in doc_date or event_date (or a "
         "more specific date within it is).",
         "Dates the original label did not carry; a stated date moved to due_date.", lambda rows, ctx: check_dates_kept(rows, ctx)),
    Rule("D15_removed_values_in_signal", "dataset", "error",
         "Owner rule 2026-11-18: every value the text does not state comes out of the labels and is kept beside them "
         "as marked signal; nothing inferred is silently dropped.",
         "For every exported training and test row, each fact of the reviewer's original label that the exported label "
         "no longer has (respellings excluded) and that the training text does not state has a sidecar entry with the "
         "same field and value (the SSOT row's `signal`, else the --signal file).",
         "Values the normaliser changed rather than removed where the new spelling has other words; whether a sidecar "
         "entry's recorded source is right; facts of people removed whole (covered by the name's entry).",
         check_signal),
]


def overlay_rules(overlay: dict[str, Any]) -> list[Rule]:
    rules = []
    for ref in overlay["allOf"]:
        rid = ref["$ref"].rsplit("/", 1)[-1]
        d = overlay["$defs"][rid]
        rules.append(Rule(rid, "label", d["x-severity"], d["$comment"], d["description"],
                          d.get("x-blind", "Anything that needs the text: the overlay sees the label alone."),
                          from_label_layer(rid)))
    return rules


def template_rules() -> list[Rule]:
    def run_for(t: KindTemplate) -> Check:
        return per_row(t.violation, t.matches)
    def expect(t: KindTemplate) -> str:
        parts = [f"status {t.expect_status}"] if t.expect_status else []
        parts += ["kind " + "/".join(t.expect_kinds)] if t.expect_kinds else []
        parts += ["secondary " + ", ".join(t.expect_secondary)] if t.expect_secondary else []
        scope = f" (rows labeled {'/'.join(t.only_if_kind)})" if t.only_if_kind else ""
        return f"Text/filename pattern{scope} -> {' + '.join(parts)}"
    return [Rule(t.id, "text", t.severity, t.rubric, expect(t), t.blind, run_for(t)) for t in KIND_TEMPLATES]


def all_rules(overlay: dict[str, Any]) -> list[Rule]:
    return [*SHAPE_RULES, *overlay_rules(overlay), *TEXT_RULES, *FACT_RULES, *template_rules(), *DATASET_RULES]


def rules_sha256(rules: list[Rule], overlay: dict[str, Any]) -> str:
    table = [[r.id, r.layer, r.severity, r.check] for r in rules]
    templates = [t.__dict__ for t in KIND_TEMPLATES]
    payload = json.dumps({"version": CONTRACT_VERSION, "rules": table, "templates": templates, "overlay": overlay},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def contract_sha256() -> str:
    """The contract's own bytes (this file and the overlay): detector code the rule list hash cannot see."""
    return hashlib.sha256(Path(__file__).read_bytes() + OVERLAY_PATH.read_bytes()).hexdigest()


def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------------------------------------------
def load_adjudications() -> tuple[dict[tuple[str, str], dict[str, Any]], list[str]]:
    """(link key, rule) -> ruling, for well-formed `label_stands` rulings; and the problems with the rest."""
    out, problems = {}, []
    if not ADJUDICATIONS_PATH.is_file():
        return out, problems
    for i, line in enumerate(ADJUDICATIONS_PATH.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"line {i}: not JSON ({exc})")
            continue
        missing = [k for k in ADJUDICATION_FIELDS if not str(e.get(k) or "").strip()]
        if missing or e.get("verdict") != "label_stands":
            problems.append(f"line {i}: missing {missing}" if missing else f"line {i}: verdict {e.get('verdict')!r} is not label_stands")
            continue
        out[(str(e["link_key_hex"]).lower(), str(e["rule"]))] = e
    return out, problems


def quote_in_text(quote: str, r: Row) -> bool:
    """A ruling's quote must be the document's own words (case and whitespace folded). On a text T07 lists (font
    cipher, non-Latin) the matchers cannot read it, and the quote may be the reader's reason."""
    q = re.sub(r"\s+", " ", fold(quote)).strip()
    t = re.sub(r"\s+", " ", fold(r.text))
    return bool(q) and (q in t or q in re.sub(r"(\w)- (\w)", r"\1\2", t))  # a word broken at a line end ("sub- mit")


def run_check(specs: list[str], warn_only_splits: set[str], signal: list[Path] | None = None) -> tuple[dict[str, Any], list[Row]]:
    rows = load_rows(specs)
    attach_labels(rows)
    attach_text(rows)
    overlay = load_overlay()
    rules = all_rules(overlay)
    ctx = Ctx(label_errors=label_layer_errors(rows, overlay), signal=load_signal(signal or []))
    by_lk = {r.lk: r for r in rows}
    rulings, ruling_problems = load_adjudications()
    results = []
    applied, refused = 0, []
    for rule in rules:
        checked, fails = rule.run(rows, ctx)
        demoted = {k for k in fails if k in by_lk and by_lk[k].split in warn_only_splits | {"excluded"}}
        waived = {}
        for k in fails:
            ruling = rulings.get((k, rule.id))
            if ruling is None:
                continue
            if k in by_lk and (quote_in_text(str(ruling["quote"]), by_lk[k]) or by_lk[k].view("text").unreadable):
                waived[k] = f"label stands ({ruling['ruled_by']}, {ruling['ruled_at']}): \"{ruling['quote']}\""
            else:
                refused.append(f"{k} {rule.id}: the quoted words are not in the training text")
        applied += len(waived)
        blocking = len(set(fails) - demoted - set(waived)) if rule.severity == "error" else 0
        results.append({
            "id": rule.id, "layer": rule.layer, "severity": rule.severity, "rubric": rule.rubric,
            "check": rule.check, "cannot_see": rule.blind, "rows_checked": checked, "rows_failing": len(fails),
            "rows_blocking": blocking, "rows_waived": len(waived), "waived": dict(sorted(waived.items())),
            "failing_by_split": dict(Counter(by_lk[k].split if k in by_lk else "?" for k in fails)),
            "failures": {k: fails[k] for k in sorted(fails)},
        })
    counts: dict[str, Any] = {}
    for split in sorted({r.split for r in rows}):
        sel = [r for r in rows if r.split == split]
        counts[split] = {"rows": len(sel), "in_queue": sum(r.in_queue for r in sel),
                         "by_class": dict(sorted(Counter(r.cls for r in sel).items()))}
    report = {
        "contract_version": CONTRACT_VERSION,
        "rules_sha256": rules_sha256(rules, overlay),
        "inputs": [{"spec": s, "sha256": file_sha256(Path(s.partition("=")[0]))} for s in specs]
                  + [{"signal": str(p), "sha256": file_sha256(p)} for p in signal or []],
        "contract_sha256": contract_sha256(),
        "docmeta_source": DOCMETA_SOURCE,
        "docmeta": DOCMETA_INFO,
        "warn_only_splits": sorted(warn_only_splits | {"excluded"}),
        "rows": len(rows),
        "counts": counts,
        "rules": results,
        "blocking_errors": sum(x["rows_blocking"] for x in results),
        "provenance": provenance_table(rows, ctx),
        "adjudications": {"path": str(ADJUDICATIONS_PATH),
                          "sha256": file_sha256(ADJUDICATIONS_PATH) if ADJUDICATIONS_PATH.is_file() else None,
                          "entries": len(rulings), "applied": applied, "refused": refused, "malformed": ruling_problems},
        "notes": ctx.cache.get("notes", {}),
        "expected_exclusions": {r.lk: str(r.raw.get("excluded_reason") or "") for r in rows
                                if r.split == "excluded" and r.lk in load_heldout_keys()},
    }
    report["status"] = "fail" if report["blocking_errors"] else "pass"
    return report, rows


def write_outputs(report: dict[str, Any], rows: list[Row], out_dir: Path, json_path: Path | None) -> None:
    by_lk = {r.lk: r for r in rows}
    fail_dir = out_dir / "failing"
    fail_dir.mkdir(parents=True, exist_ok=True)
    for old in fail_dir.glob("*.tsv"):
        old.unlink()
    for res in report["rules"]:
        if res["rows_failing"]:
            lines = ["link_key_hex\tsplit\tsource\treason"]
            for k, why in res["failures"].items():
                r = by_lk.get(k)
                lines.append(f"{k}\t{r.split if r else '?'}\t{r.source if r else '?'}\t{why}")
            (fail_dir / f"{res['id']}.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
            res["failing_file"] = str(fail_dir / f"{res['id']}.tsv")
    if json_path is not None:
        slim = {**report, "rules": [{k: v for k, v in x.items() if k != "failures"} | {"failing_keys": sorted(x["failures"])}
                                    for x in report["rules"]]}
        json_path.write_text(json.dumps(slim, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def print_report(report: dict[str, Any]) -> None:
    print(f"{report['contract_version']}  rules {report['rules_sha256'][:12]}  rows {report['rows']}  status {report['status'].upper()}")
    for split, c in report["counts"].items():
        print(f"  split {split:14s} rows {c['rows']:5d}  in queue {c['in_queue']}")
    print(f"\n{'rule':42s} {'layer':8s} {'sev':5s} {'checked':>7s} {'failing':>7s}  by split")
    for x in report["rules"]:
        print(f"{x['id']:42s} {x['layer']:8s} {x['severity']:5s} {x['rows_checked']:7d} {x['rows_failing']:7d}  "
              f"{' '.join(f'{k}:{v}' for k, v in sorted(x['failing_by_split'].items()))}")
    print_provenance(report["provenance"]["overall"], "Where each label fact occurs (rows outside excluded)")
    adj = report["adjudications"]
    waived = {x["id"]: x["rows_waived"] for x in report["rules"] if x.get("rows_waived")}
    print(f"\nadjudications: {adj['entries']} rulings, {adj['applied']} waived failures {waived or ''}"
          f"{'; refused: ' + '; '.join(adj['refused']) if adj['refused'] else ''}"
          f"{'; malformed: ' + '; '.join(adj['malformed']) if adj['malformed'] else ''}")
    for rid, note in report.get("notes", {}).items():
        print(f"{rid}: {note}")
    for lk, why in report["expected_exclusions"].items():
        print(f"held-out key excluded: {lk}: {why[:110]}")
    print(f"\nblocking errors: {report['blocking_errors']}  -> {report['status'].upper()}")


def print_provenance(table: dict[str, dict[str, int]], title: str) -> None:
    cols = [*SOURCES, "unchecked"]
    print(f"\n{title}\n{'field':16s}{'values':>8s}" + "".join(f"{c:>10s}" for c in cols))
    for f, c in table.items():
        n = sum(c.values())
        print(f"{f:16s}{n:8d}" + "".join(f"{(f'{100 * c.get(s, 0) / n:.1f}%' if c.get(s) else ''):>10s}" for s in cols))


def cmd_check(args: argparse.Namespace) -> int:
    report, rows = run_check(args.input, set(args.warn_only_split or ()), args.signal)
    write_outputs(report, rows, args.out_dir, args.json)
    print_report(report)
    return 1 if report["status"] == "fail" else 0


def cmd_rules(args: argparse.Namespace) -> int:
    """The rule table as Markdown (CONTRACT.md embeds it)."""
    print("| id | layer | severity | checks | cannot see |\n|---|---|---|---|---|")
    for r in all_rules(load_overlay()):
        cells = [c.replace("|", "\\|").replace("\n", " ") for c in (r.id, r.layer, r.severity, r.check, r.blind)]
        print("| " + " | ".join(cells) + " |")
    return 0


# --------------------------------------------------------------------------------------------------------------
# Single source of truth: one row per labeled document, in the gold row format plus four fields
# --------------------------------------------------------------------------------------------------------------
SSOT_FIELDS = ("split", "excluded_reason", "source_batch", "label_sha256", "seen_template", "signal")
# Rows the SSOT moves to `excluded` on top of the normaliser's own exclusions (data; a no-op once the normaliser
# excludes the row itself). link key -> (rule, reason).
SSOT_EXCLUSIONS = {
    "85afe0532f6c8e0b": ("contract:D06a", "identical error page to training row a3002f39e37a6384; held-out membership is "
                         "fixed by key, so the held-out copy is excluded (coordinator decision 2026-11-18)"),
}
SET_NAME = {"gold_v6_5n_old.jsonl": "old", "gold_v6_5n_gapfill_train.jsonl": "gapfill_train",
            "gold_v6_5n_gapfill_test.jsonl": "gapfill_test"}
DEFAULT_LAYOUT = {  # export file -> (source_batch, splits); the normaliser's output names, read by trainer and scorer
    "gold_v6_5n_old.jsonl": ("v6_4_old", ("train", "heldout_v6_4")),
    "gold_v6_5n_gapfill_train.jsonl": ("v6_5_gapfill", ("train",)),
    "gold_v6_5n_gapfill_test.jsonl": ("v6_5_gapfill", ("test_gapfill",)),
    "gold_v6_5n_excluded.jsonl": (None, ("excluded",)),
}
BLIND_SOURCES = (("blind_val48", "v4_blind_val48", VAL48_JSON), ("blind_docs8", "v4_blind_docs8", DOCS8_JSON))
EXCLUDED_ORIGIN = {"old": "v6_4_old", "gapfill_train": "v6_5_gapfill", "gapfill_test": "v6_5_gapfill"}


def dumps_row(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False)


def label_string_sha(row: dict[str, Any]) -> str:
    return hashlib.sha256(str(row["messages"][-1]["content"]).encode("utf-8")).hexdigest()


def blind_rows() -> list[dict[str, Any]]:
    """val48 and docs8 in the gold row format, labels unchanged (serialized as stored). The link key comes from
    the deterministic table: by body hash (val48; the queue's link key when a body has two) or by filename (docs8,
    which has no body hash)."""
    import duckdb
    from .. import build_prompt_v4

    det = A_DIR / "parquets_v6_2" / "deterministic_323k_v6_2.parquet"
    blind = [(split, batch, r) for split, batch, path in BLIND_SOURCES for r in json.loads(path.read_text(encoding="utf-8"))]
    shas = sorted({str(r["body_sha"]) for _, _, r in blind if r.get("body_sha")})
    fns = sorted({str(r["filename"]) for _, _, r in blind if not r.get("body_sha")})
    con = duckdb.connect()
    con.execute("SET memory_limit='4GB'; SET threads=4")
    hits = con.execute(
        f"SELECT d.link_key_hex, d.saved_body_hex, d.effective_body_sha_hex, d.doc_key, d.filename, "
        f"q.link_key_hex IS NOT NULL AS in_queue FROM read_parquet('{det}') d "
        f"LEFT JOIN (SELECT link_key_hex FROM read_parquet('{QUEUE_PARQUET}')) q USING (link_key_hex) "
        f"WHERE d.saved_body_hex IN (SELECT unnest(?)) OR d.effective_body_sha_hex IN (SELECT unnest(?)) "
        f"OR d.filename IN (SELECT unnest(?))", [shas, shas, fns]).fetchall()
    con.close()
    by_sha: dict[str, list[tuple]] = defaultdict(list)
    by_fn: dict[str, list[tuple]] = defaultdict(list)
    for h in hits:
        for sha in {h[1], h[2]} - {None}:
            by_sha[sha].append(h)
        by_fn[h[4]].append(h)
    out = []
    for split, batch, r in blind:
        cands = by_sha.get(str(r.get("body_sha"))) if r.get("body_sha") else by_fn.get(str(r["filename"]))
        cands = sorted(set(cands or ()), key=lambda h: (not h[5], h[0]))  # queue row first, then smallest key
        best = cands[0] if cands else None
        known = r.get("known") or "<NONE>"
        known = known if isinstance(known, str) else json.dumps(known)
        row: dict[str, Any] = {
            "messages": [{"role": "user", "content": build_prompt_v4(known, str(r.get("filename") or ""), str(r.get("text") or ""))},
                         {"role": "assistant", "content": json.dumps(r["gold"], separators=(",", ":"), ensure_ascii=False)}],
            "saved_body_hex": str(r.get("body_sha") or (best[1] if best else "")),
            "link_key_hex": best[0] if best else "",
            "stratum": str(r.get("stratum") or r.get("tag") or ""),
            "reviewer_id": batch,
        }
        if best and best[3]:
            row["doc_key"] = best[3]
        if len(cands) > 1:
            row["alt_link_keys"] = [h[0] for h in cands[1:]]
        row.update(split=split, excluded_reason=None, source_batch=batch)
        out.append(row)
    return out


def build_ssot_rows(lookups: Path) -> list[dict[str, Any]]:
    heldout = load_heldout_keys()
    rows: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []  # SSOT_EXCLUSIONS rows go after the normaliser's excluded rows
    for name, (batch, splits) in DEFAULT_LAYOUT.items():
        for line in (lookups / name).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if "excluded" in splits:
                split, src = "excluded", EXCLUDED_ORIGIN.get(str(row.get("excluded_from_set")), "unknown")
            elif batch == "v6_4_old":
                split, src = ("heldout_v6_4" if row["link_key_hex"] in heldout else "train"), batch
            else:
                split, src = splits[0], batch
            if split != "excluded" and row["link_key_hex"] in SSOT_EXCLUSIONS:
                rule, why = SSOT_EXCLUSIONS[row["link_key_hex"]]
                row.update(excluded_from_set=SET_NAME[name], excluded_rule=rule, excluded_reason=why, split="excluded", source_batch=src)
                moved.append(row)
                continue
            if split != "excluded":  # excluded rows keep their excluded_reason in place: exports stay byte-identical
                row["excluded_reason"] = None
            row.update(split=split, source_batch=src)
            rows.append(row)
    rows.extend(moved)
    rows.extend(blind_rows())
    signal = load_signal([SIGNAL_PATH]) if (lookups / SIGNAL_PATH.name).is_file() else {}
    keep = ("field", "value", "source", "rule", "kept_as", "persona")
    for row in rows:
        row["label_sha256"] = label_string_sha(row)
        if row["link_key_hex"] in signal:  # what the normaliser took out of this label, and where it occurs
            row["signal"] = [{k: e[k] for k in keep if k in e} for e in signal[row["link_key_hex"]]]
    return rows


def _portable_manifest_path(p: Path) -> str:
    res = p.resolve()
    n_res, a_res = N_DIR.resolve(), A_DIR.resolve()
    if res.is_relative_to(n_res):
        return str(res.relative_to(n_res))
    if res.is_relative_to(a_res):
        return f"docmeta-v6-20261116/{res.relative_to(a_res)}"
    return res.name


def _resolve_manifest_input_path(raw: str) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p
    if raw.startswith("docmeta-v6-20261116/"):
        return A_DIR / raw.removeprefix("docmeta-v6-20261116/")
    return N_DIR / p


def manifest_for(ssot: Path, report: dict[str, Any], inputs: list[Path]) -> dict[str, Any]:
    from datetime import date

    rows = [json.loads(l) for l in ssot.read_text(encoding="utf-8").splitlines() if l.strip()]
    per_split: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        lab = json.loads(row["messages"][-1]["content"])
        st = str(lab.get("status") or "usable")
        per_split[row["split"]][(lab.get("primary_kind") or "other") if st == "usable" else f"status:{st}"] += 1
    adj = report["adjudications"]
    return {
        "ssot": {"path": _portable_manifest_path(ssot), "sha256": file_sha256(ssot), "rows": len(rows)},
        "rows_per_split": {k: sum(v.values()) for k, v in sorted(per_split.items())},
        "rows_per_split_and_kind": {k: dict(sorted(v.items())) for k, v in sorted(per_split.items())},
        "contract": {"version": report["contract_version"], "rules_sha256": report["rules_sha256"],
                     "contract_sha256": report["contract_sha256"], "rules": [x["id"] for x in report["rules"]]},
        "check": {"status": report["status"], "blocking_errors": report["blocking_errors"],
                  "warn_only_splits": report["warn_only_splits"],
                  "blocking_by_rule": {x["id"]: x["rows_blocking"] for x in report["rules"] if x["rows_blocking"]},
                  "failing_by_rule": {x["id"]: x["rows_failing"] for x in report["rules"] if x["rows_failing"]}},
        "inputs": [{"path": _portable_manifest_path(p), "sha256": file_sha256(p)} for p in inputs],
        "adjudications": {"path": _portable_manifest_path(Path(adj["path"])),
                          "sha256": adj["sha256"], "entries": adj["entries"], "applied": adj["applied"]},
        "docmeta": report.get("docmeta"),
        "date": date.today().isoformat(),
    }


def seal(ssot: Path, inputs: list[Path], warn_only: set[str]) -> int:
    """Re-check the SSOT and rewrite its manifest: the one way a label edit becomes usable."""
    report, rows = run_check([str(ssot)], warn_only)
    write_outputs(report, rows, SSOT_DIR / "check", SSOT_DIR / "ssot_report.json")
    print_report(report)
    out_manifest = SSOT_DIR / "MANIFEST.json"
    out_manifest.write_text(json.dumps(manifest_for(ssot, report, inputs), indent=1) + "\n", encoding="utf-8")
    print(f"manifest: {out_manifest}")
    return 1 if report["status"] == "fail" else 0


def flag_seen_templates(rows: list[dict[str, Any]], tmp: Path) -> int:
    """Set seen_template on test rows whose nearest training sibling is a template or edition (D06b), so scores
    can be reported with and without them."""
    tmp.write_text("".join(dumps_row(r) + "\n" for r in rows), encoding="utf-8")
    loaded = load_rows([str(tmp)])
    attach_labels(loaded)
    attach_text(loaded)
    ctx = Ctx(label_errors={})
    _, templates = near_dup_failures(loaded, ctx, "template")
    first = {}
    for p in ctx.cache["near_dup_pairs"]:
        if p["test"] in templates and p["class"] == "template":
            first.setdefault(p["test"], {"train_link_key": p["train"], "containment": p["containment"],
                                         "numbers_jaccard": p["numbers_jaccard"]})
    for row in rows:
        row.pop("seen_template", None)
        if row["link_key_hex"] in first:
            row["seen_template"] = first[row["link_key_hex"]]
    return len(first)


def cmd_build_ssot(args: argparse.Namespace) -> int:
    rows = build_ssot_rows(args.lookups)
    SSOT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SSOT_PATH.with_suffix(".jsonl.tmp")
    print(f"seen_template set on {flag_seen_templates(rows, tmp)} test rows")
    tmp.write_text("".join(dumps_row(r) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(SSOT_PATH)
    inputs = [args.lookups / n for n in DEFAULT_LAYOUT] + [p for _, _, p in BLIND_SOURCES]
    inputs += [args.lookups / SIGNAL_PATH.name] if (args.lookups / SIGNAL_PATH.name).is_file() else []
    return seal(SSOT_PATH, inputs, set(BLIND_SPLITS))


def cmd_seal(args: argparse.Namespace) -> int:
    m_path = (SSOT_DIR / "MANIFEST.json") if (SSOT_DIR / "MANIFEST.json").is_file() else MANIFEST_PATH
    prior = json.loads(m_path.read_text(encoding="utf-8")) if m_path.is_file() else {"inputs": []}
    return seal(SSOT_PATH, [_resolve_manifest_input_path(x["path"]) for x in prior["inputs"]], set(BLIND_SPLITS))


def verify_manifest(require_pass: bool) -> list[str]:
    """Problems with the SSOT against its manifest; empty when it verifies."""
    if not MANIFEST_PATH.is_file():
        return [f"no manifest at {MANIFEST_PATH}"]
    m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    problems = []
    if file_sha256(SSOT_PATH) != m["ssot"]["sha256"]:
        problems.append("SSOT sha256 differs from the manifest (edited without sealing)")
    rows = [json.loads(l) for l in SSOT_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    got = dict(sorted(Counter(r["split"] for r in rows).items()))
    if got != m["rows_per_split"]:
        problems.append(f"rows per split {got} != manifest {m['rows_per_split']}")
    bad_sha = sum(label_string_sha(r) != r.get("label_sha256") for r in rows)
    if bad_sha:
        problems.append(f"{bad_sha} rows whose label_sha256 does not match their label")
    overlay = load_overlay()
    if rules_sha256(all_rules(overlay), overlay) != m["contract"]["rules_sha256"]:
        problems.append("rule list changed since the manifest was written (re-seal)")
    if contract_sha256() != m["contract"]["contract_sha256"]:
        problems.append("contract code or overlay changed since the manifest was written (re-seal)")
    if require_pass and m["check"]["status"] != "pass":
        problems.append(f"the sealed check failed: {m['check']['blocking_errors']} blocking errors "
                        f"({', '.join(f'{k}:{v}' for k, v in m['check']['blocking_by_rule'].items())})")
    return problems


def cmd_verify_manifest(args: argparse.Namespace) -> int:
    problems = verify_manifest(not args.allow_failed_check)
    exports = args.exports / "EXPORT_MANIFEST.json" if args.exports else None
    if exports is not None:
        em = json.loads(exports.read_text(encoding="utf-8"))
        if em["ssot_sha256"] != file_sha256(SSOT_PATH):
            problems.append("exports were written from another SSOT version")
        for name, meta in em["files"].items():
            if file_sha256(args.exports / name) != meta["sha256"]:
                problems.append(f"export {name} changed since it was written")
    for p in problems:
        print(f"FAIL {p}")
    print("manifest verifies" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_export(args: argparse.Namespace) -> int:
    """Per-split files in the normaliser's names and row format (SSOT fields stripped), then a row-for-row
    comparison with the files in --compare-dir."""
    rows = [json.loads(l) for l in SSOT_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Any] = {}
    status = 0
    for name, (batch, splits) in DEFAULT_LAYOUT.items():
        lines = []
        for row in rows:
            if row["split"] not in splits or (batch is not None and row["source_batch"] != batch):
                continue
            keep = {"excluded_reason"} if row["split"] == "excluded" else set()
            lines.append(dumps_row({k: v for k, v in row.items() if k not in set(SSOT_FIELDS) - keep}))
        path = args.out_dir / name
        path.write_text("".join(l + "\n" for l in lines), encoding="utf-8")
        files[name] = {"rows": len(lines), "sha256": file_sha256(path)}
        if args.compare_dir:
            # Expected = the reference file, less rows SSOT_EXCLUSIONS moved out of it, plus (excluded file) those rows.
            ref = (args.compare_dir / name).read_text(encoding="utf-8").splitlines()
            ref_keys = [json.loads(l)["link_key_hex"] for l in ref]
            out_keys = [json.loads(l)["link_key_hex"] for l in lines]
            if "excluded" in splits:
                expected = ref + [l for l, k in zip(lines, out_keys) if k in SSOT_EXCLUSIONS and k not in ref_keys]
            else:
                expected = [l for l, k in zip(ref, ref_keys) if k not in SSOT_EXCLUSIONS]
            moved = abs(len(expected) - len(ref))
            same = sum(a == b for a, b in zip(lines, expected))
            ok = len(lines) == len(expected) == same
            files[name].update(compare_rows=len(ref), identical_rows=same, declared_moves=moved,
                               byte_identical=lines == ref and file_sha256(path) == file_sha256(args.compare_dir / name))
            note = f" (after {moved} declared SSOT exclusion{'s' if moved != 1 else ''})" if moved else ""
            print(f"{name}: {len(lines)} rows, {same} identical to {args.compare_dir / name} ({len(ref)} rows){note} -> "
                  f"{'IDENTICAL' if ok else 'DIFFERS'}")
            status |= 0 if ok else 1
    em = {"ssot_sha256": file_sha256(SSOT_PATH), "manifest_sha256": file_sha256(MANIFEST_PATH) if MANIFEST_PATH.is_file() else None,
          "files": files}
    (args.out_dir / "EXPORT_MANIFEST.json").write_text(json.dumps(em, indent=1) + "\n", encoding="utf-8")
    return status


def cmd_summary(args: argparse.Namespace) -> int:
    """What we train and test on: rows per split by kind, then per split by file format and by whether the model
    is given the Congress and the committee (`known`), and how many test rows are seen templates."""
    problems = verify_manifest(require_pass=False)
    m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.is_file() else {}
    print(f"SSOT {args.ssot}  manifest: {'verifies' if not problems else '; '.join(problems)}"
          f"  sealed check: {m.get('check', {}).get('status', 'n/a')}")
    rows = load_rows([str(args.ssot)])
    attach_labels(rows)
    attach_text(rows)
    splits = [s for s in SPLITS if any(r.split == s for r in rows)]
    by = Counter((r.cls, r.split) for r in rows)
    classes = sorted({c for c, _ in by}, key=lambda c: (-sum(by[c, s] for s in splits), c))
    w = max(len(c) for c in classes) + 2
    head = "".join(f"{s[:12]:>13s}" for s in splits)
    print(f"\nRows per split by kind\n{'kind':{w}s}{head}{'total':>8s}")
    for c in classes:
        print(f"{c:{w}s}" + "".join(f"{by[c, s] or '':>13}" for s in splits) + f"{sum(by[c, s] for s in splits):>8d}")
    print(f"{'total':{w}s}" + "".join(f"{sum(r.split == s for r in rows):>13d}" for s in splits) + f"{len(rows):>8d}")

    def stated_or_signal(r: Row, f: str) -> str:
        """The label carries it (a sealed SSOT guarantees the text states it), or the normaliser moved it to the
        signal (and where it occurs: the known hint, the filename, ...), or neither."""
        if (r.label or {}).get(f):
            return "stated in text"
        srcs = sorted({str(e.get("source")) for e in r.raw.get("signal") or [] if e.get("field") == f})
        return f"not stated; signal: {'/'.join(srcs)}" if srcs else "not stated; no value"
    facets = {
        "format": lambda r: r.fmt or "unknown",
        "Congress": lambda r: stated_or_signal(r, "congress"),
        "committee": lambda r: stated_or_signal(r, "committees"),
        "known hint has a Congress": lambda r: "yes" if known_dict(r).get("congress") else "no",
        "in production queue": lambda r: "yes" if r.in_queue else "no",
        "seen_template": lambda r: "yes" if r.raw.get("seen_template") else "no",
    }
    for name, fn in facets.items():
        c = Counter((fn(r), r.split) for r in rows)
        vals = sorted({v for v, _ in c}, key=lambda v: -sum(c[v, s] for s in splits))
        print(f"\nBy {name}\n{'':{w}s}{head}")
        for v in vals:
            print(f"{v:{w}s}" + "".join(f"{c[v, s] or '':>13}" for s in splits))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="run every rule; exit 1 on any blocking error")
    p.add_argument("--input", action="append", required=True, help="FILE[=SPLIT|=auto_v64]; FILE alone reads each row's split")
    p.add_argument("--out-dir", type=Path, required=True, help="failing-key files go to OUT_DIR/failing/<rule>.tsv")
    p.add_argument("--json", type=Path, default=None, help="write the JSON report here")
    p.add_argument("--warn-only-split", action="append", help="failures in this split are reported, never blocking")
    p.add_argument("--signal", action="append", type=Path, help="a signal sidecar (gold_v6_5n_signal.jsonl) for D15")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("rules", help="print the rule table as Markdown")
    p.set_defaults(fn=cmd_rules)
    p = sub.add_parser("build-ssot", help="build the SSOT from the normaliser's files and the blind sets, then seal")
    p.add_argument("--lookups", type=Path, default=N_DIR / "lookups_and_gold")
    p.set_defaults(fn=cmd_build_ssot)
    p = sub.add_parser("seal", help="re-check the SSOT after an edit and rewrite MANIFEST.json")
    p.set_defaults(fn=cmd_seal)
    p = sub.add_parser("verify-manifest", help="exit 1 unless the SSOT (and exports) match a passing manifest")
    p.add_argument("--exports", type=Path, default=None, help="also verify an export folder's EXPORT_MANIFEST.json")
    p.add_argument("--allow-failed-check", action="store_true", help="verify hashes only, even if the sealed check failed")
    p.set_defaults(fn=cmd_verify_manifest)
    p = sub.add_parser("summary", help="what we train and test on: per split by kind, format, known Congress and committee")
    p.add_argument("--ssot", type=Path, default=SSOT_PATH)
    p.set_defaults(fn=cmd_summary)
    p = sub.add_parser("export", help="write the per-split files the trainer and scorer read, from the SSOT")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--compare-dir", type=Path, default=None, help="prove the exports row-for-row equal to these files")
    p.set_defaults(fn=cmd_export)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
