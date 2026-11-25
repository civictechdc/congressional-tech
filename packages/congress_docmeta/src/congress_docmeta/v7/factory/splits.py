"""Event-grouped + 2026 temporal splits, dual-mode decontamination & psychometric metrics.

Addresses Horizon 0 findings:
- Finding 2: Zero same-hearing-event, near-duplicate template, or 2026 temporal leakage.
- Finding 4: Dual-mode decontamination (exact SHA, normalized text hash, 8/13-gram
  word shingle containment, TF-IDF cosine, and optional MiniLM dense cosine).
- Law 3: Always report `accuracy`, `macro_f1`, `weighted_f1`, multi-class `cohen_kappa`,
  multi-class `gwet_ac1`, per-class `(n, pred, tp, f1, kappa, ac1)`, and confusion dict.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np


# House/GovInfo structured event filenames, e.g.:
# - HHRG-115-IF14-TTF-WingC-20170726.pdf -> ("house", "115", "IF14", "20170726")
# - HHRG-117-IF18-20210525-SD008.pdf -> ("house", "117", "IF18", "20210525")
# - HMTG-112-HHRG-IF03-20120619.pdf -> ("house", "112", "IF03", "20120619")
# - HMKP-114-IF16-MState-U000031-20160912.pdf -> ("house", "114", "IF16", "20160912")
# - CRPT-119-BA00-Vote252-20260304.pdf -> ("crpt", "119", "BA00", "20260304")
_HOUSE_EVENT_RE = re.compile(
    r"\b(?:HHRG|HMTG|HMKP|CHRG)-(\d+)-(?:(?:HHRG|HMTG|HMKP)-)?([A-Z]{2}\d{2}|[A-Z0-9]{2,8})(?:-[A-Za-z0-9_]+)*-(\d{8})(?:\b|[-_.])",
    re.IGNORECASE,
)
_HOUSE_SIMPLE_RE = re.compile(
    r"\b(HHRG|HMTG|HMKP|CHRG)-(\d+)-([A-Z0-9]+)-(\d{8})\b",
    re.IGNORECASE,
)
_CRPT_EVENT_RE = re.compile(
    r"\bCRPT-(\d+)-([A-Z0-9]+)(?:-[A-Za-z0-9_]+)*-(\d{6,8})(?:\b|[-_.])",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?\b")
_WORD_RE = re.compile(r"[a-z0-9]+")


def normalize_text_for_dedup(text: str) -> str:
    """Canonical lowercase whitespace/punctuation normalization for near-dup hashing."""
    return " ".join(_WORD_RE.findall(text.casefold()))


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalized_text_sha256(text: str) -> str:
    return hashlib.sha256(normalize_text_for_dedup(text).encode("utf-8")).hexdigest()


def word_tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.casefold())


def word_shingles(tokens: Sequence[str], n: int) -> set[int]:
    """Compute hashed n-gram word shingles for fast containment checks."""
    if n <= 0 or len(tokens) < n:
        return set()
    out: set[int] = set()
    for i in range(len(tokens) - n + 1):
        gram = " ".join(tokens[i : i + n])
        # 64-bit blake2b digest prevents Python hash randomization across runs.
        h = int.from_bytes(hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest(), "big")
        out.add(h)
    return out


def _parse_date_tuple(raw: Any) -> tuple[int, int, int] | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Handle compact YYYYMMDD or YYYYMM from filenames.
    m_compact = re.fullmatch(r"(\d{4})(\d{2})(\d{2})?", s)
    if m_compact:
        yr = int(m_compact.group(1))
        mo = int(m_compact.group(2))
        dy = int(m_compact.group(3) or "1")
        if 1900 <= yr <= 2100 and 1 <= mo <= 12 and 1 <= dy <= 31:
            return (yr, mo, dy)
    m = _ISO_DATE_RE.search(s)
    if not m:
        return None
    yr = int(m.group(1))
    mo = int(m.group(2) or "1")
    dy = int(m.group(3) or "1")
    if 1900 <= yr <= 2100 and 1 <= mo <= 12 and 1 <= dy <= 31:
        return (yr, mo, dy)
    return None


def _norm_committee_key(committees: Any) -> str:
    if not committees:
        return ""
    if isinstance(committees, str):
        items = [committees]
    elif isinstance(committees, Iterable):
        items = [str(x) for x in committees if x]
    else:
        return ""
    cleaned = []
    for c in items:
        toks = [
            t
            for t in _WORD_RE.findall(c.casefold())
            if t not in {"house", "senate", "united", "states", "u", "s", "committee", "on", "the", "subcommittee"}
        ]
        if toks:
            cleaned.append("-".join(toks))
    return "|".join(sorted(set(cleaned)))


def extract_event_group_key(doc: Mapping[str, Any]) -> tuple[str | None, tuple[int, int, int] | None]:
    """Extract canonical event group key and parsed date tuple from filename or metadata.

    Supports:
    - `HHRG|HMTG|HMKP|CHRG-<cong>-<comm>-...-<YYYYMMDD>` (including `-TTF-`, `-Wstate-`, `-SDxxx`)
    - `CRPT-<cong>-<comm>-...-<YYYYMMDD|YYYYMM>`
    - `(chamber, committees, event_date)` fallback when filename is unstructured.
    """
    filename = str(doc.get("filename") or "")
    parsed_date: tuple[int, int, int] | None = None

    for candidate_date in (doc.get("event_date"), doc.get("doc_date"), doc.get("date")):
        dt = _parse_date_tuple(candidate_date)
        if dt is not None:
            parsed_date = dt
            break

    if filename:
        m = _HOUSE_EVENT_RE.search(filename)
        if m:
            cong, comm, ymd = m.group(1), m.group(2).upper(), m.group(3)
            f_dt = _parse_date_tuple(ymd)
            if parsed_date is None or (f_dt is not None and f_dt > parsed_date):
                parsed_date = f_dt
            return f"house:{cong}:{comm}:{ymd}", parsed_date

        m_simple = _HOUSE_SIMPLE_RE.search(filename)
        if m_simple:
            _, cong, comm, ymd = m_simple.groups()
            f_dt = _parse_date_tuple(ymd)
            if parsed_date is None or (f_dt is not None and f_dt > parsed_date):
                parsed_date = f_dt
            return f"house:{cong}:{comm.upper()}:{ymd}", parsed_date

        m_crpt = _CRPT_EVENT_RE.search(filename)
        if m_crpt:
            cong, comm, dt_part = m_crpt.groups()
            f_dt = _parse_date_tuple(dt_part)
            if parsed_date is None or (f_dt is not None and f_dt > parsed_date):
                parsed_date = f_dt
            return f"crpt:{cong}:{comm.upper()}:{dt_part}", parsed_date

    chamber = str(doc.get("chamber") or "").strip().lower()
    comm_key = _norm_committee_key(doc.get("committees"))
    ev_date = str(doc.get("event_date") or doc.get("doc_date") or "").strip()
    ev_dt = _parse_date_tuple(ev_date)
    if ev_dt is not None and (chamber or comm_key):
        iso_norm = f"{ev_dt[0]:04d}-{ev_dt[1]:02d}-{ev_dt[2]:02d}"
        return f"meta:{chamber or 'unk'}:{comm_key or 'nocomm'}:{iso_norm}", parsed_date or ev_dt

    return None, parsed_date


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if ra < rb:
                self.parent[rb] = ra
            else:
                self.parent[ra] = rb


@dataclass
class SplitAssignmentResult:
    """Output of `build_event_temporal_splits`."""

    assignments: dict[str, str]
    splits: dict[str, list[dict[str, Any]]]
    event_keys: dict[str, str | None]
    cluster_ids: dict[str, str]
    counts: dict[str, int]
    temporal_cutoff: str


def build_event_temporal_splits(
    docs: Sequence[Mapping[str, Any]],
    *,
    temporal_cutoff: str = "2026-01-01",
    dev_fraction: float = 0.15,
    near_dup_ngram8_threshold: float = 0.50,
    seed: int = 42,
    text_key: str = "text",
    id_key: str = "doc_key",
) -> SplitAssignmentResult:
    """Assign docs to `train`, `dev_iter`, and `sealed_temporal_2026` atomically by event & near-dup cluster."""
    cutoff_tuple = _parse_date_tuple(temporal_cutoff) or (2026, 1, 1)
    n = len(docs)
    uf = _UnionFind(n)

    event_owner: dict[str, int] = {}
    norm_hash_owner: dict[str, int] = {}
    doc_ids: list[str] = []
    doc_texts: list[str] = []
    doc_event_keys: list[str | None] = []
    doc_dates: list[tuple[int, int, int] | None] = []
    doc_shingles8: list[set[int]] = []

    for idx, doc in enumerate(docs):
        dk = str(doc.get(id_key) or f"doc_{idx}")
        txt = str(doc.get(text_key) or "")
        doc_ids.append(dk)
        doc_texts.append(txt)

        ev_key, dt_tuple = extract_event_group_key(doc)
        doc_event_keys.append(ev_key)
        doc_dates.append(dt_tuple)
        if ev_key is not None:
            if ev_key in event_owner:
                uf.union(idx, event_owner[ev_key])
            else:
                event_owner[ev_key] = idx

        nh = normalized_text_sha256(txt)
        if nh in norm_hash_owner:
            uf.union(idx, norm_hash_owner[nh])
        else:
            norm_hash_owner[nh] = idx

        toks = word_tokens(txt)
        doc_shingles8.append(word_shingles(toks, 8))

    # Near-duplicate 8-gram cluster union using inverted shingle index.
    if 0.0 < near_dup_ngram8_threshold <= 1.0:
        posting: dict[int, list[int]] = defaultdict(list)
        for idx, sh in enumerate(doc_shingles8):
            if not sh:
                continue
            cand_hits: Counter[int] = Counter()
            for gram in sh:
                for prev in posting[gram]:
                    cand_hits[prev] += 1
            for prev, inter in cand_hits.items():
                denom = min(len(sh), len(doc_shingles8[prev]))
                if denom > 0 and (inter / denom) >= near_dup_ngram8_threshold:
                    uf.union(idx, prev)
            for gram in sh:
                posting[gram].append(idx)

    # Group docs into atomic clusters.
    clusters: dict[int, list[int]] = defaultdict(list)
    for idx in range(n):
        clusters[uf.find(idx)].append(idx)

    temporal_clusters: list[int] = []
    pre_cutoff_clusters: list[int] = []
    for root, members in sorted(clusters.items()):
        is_post_cutoff = any(
            doc_dates[m] is not None and doc_dates[m] >= cutoff_tuple  # type: ignore[operator]
            for m in members
        )
        if is_post_cutoff:
            temporal_clusters.append(root)
        else:
            pre_cutoff_clusters.append(root)

    # Deterministic seeded shuffle of pre-cutoff clusters into `train` and `dev_iter`.
    def _cluster_sort_key(root: int) -> str:
        ev = next((doc_event_keys[m] for m in clusters[root] if doc_event_keys[m]), None)
        base = ev or doc_ids[clusters[root][0]]
        return hashlib.sha256(f"{seed}:{base}".encode("utf-8")).hexdigest()

    ordered_pre = sorted(pre_cutoff_clusters, key=_cluster_sort_key)
    total_pre_docs = sum(len(clusters[r]) for r in ordered_pre)
    target_dev_docs = int(round(total_pre_docs * max(0.0, min(0.9, dev_fraction))))
    if dev_fraction > 0 and len(ordered_pre) >= 2 and target_dev_docs == 0:
        target_dev_docs = 1

    cluster_split: dict[int, str] = {}
    for root in temporal_clusters:
        cluster_split[root] = "sealed_temporal_2026"

    dev_accum = 0
    for i, root in enumerate(ordered_pre):
        # Always keep at least the last pre-cutoff cluster for `train` when >= 2 clusters exist.
        if dev_accum < target_dev_docs and (i < len(ordered_pre) - 1 or total_pre_docs == 0):
            cluster_split[root] = "dev_iter"
            dev_accum += len(clusters[root])
        else:
            cluster_split[root] = "train"

    assignments: dict[str, str] = {}
    splits: dict[str, list[dict[str, Any]]] = {
        "train": [],
        "dev_iter": [],
        "sealed_temporal_2026": [],
    }
    event_keys_out: dict[str, str | None] = {}
    cluster_ids_out: dict[str, str] = {}

    for idx, doc in enumerate(docs):
        dk = doc_ids[idx]
        root = uf.find(idx)
        sp = cluster_split[root]
        assignments[dk] = sp
        event_keys_out[dk] = doc_event_keys[idx]
        cluster_ids_out[dk] = f"cluster_{root}"
        row_copy = dict(doc)
        row_copy["split"] = sp
        row_copy["event_group_key"] = doc_event_keys[idx]
        row_copy["cluster_id"] = f"cluster_{root}"
        splits[sp].append(row_copy)

    counts = {k: len(v) for k, v in splits.items()}
    return SplitAssignmentResult(
        assignments=assignments,
        splits=splits,
        event_keys=event_keys_out,
        cluster_ids=cluster_ids_out,
        counts=counts,
        temporal_cutoff=temporal_cutoff,
    )


@dataclass
class DecontamFlag:
    """Single flagged contamination match between an eval doc and `train`."""

    eval_doc_key: str
    eval_split: str
    matched_train_doc_key: str
    reasons: list[str]
    ngram8_containment: float = 0.0
    ngram13_containment: float = 0.0
    tfidf_cosine: float = 0.0
    minilm_cosine: float | None = None


@dataclass
class DecontaminationReport:
    """Summary of dual-mode decontamination audit."""

    clean: bool
    train_count: int
    eval_count: int
    flagged_count: int
    flagged_docs: list[DecontamFlag] = field(default_factory=list)
    reason_counts: dict[str, int] = field(default_factory=dict)
    minilm_checked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "clean": self.clean,
            "train_count": self.train_count,
            "eval_count": self.eval_count,
            "flagged_count": self.flagged_count,
            "reason_counts": dict(self.reason_counts),
            "minilm_checked": self.minilm_checked,
            "flagged_docs": [
                {
                    "eval_doc_key": f.eval_doc_key,
                    "eval_split": f.eval_split,
                    "matched_train_doc_key": f.matched_train_doc_key,
                    "reasons": list(f.reasons),
                    "ngram8_containment": round(f.ngram8_containment, 4),
                    "ngram13_containment": round(f.ngram13_containment, 4),
                    "tfidf_cosine": round(f.tfidf_cosine, 4),
                    "minilm_cosine": round(f.minilm_cosine, 4) if f.minilm_cosine is not None else None,
                }
                for f in self.flagged_docs
            ],
        }


def _compute_tfidf_vectors(
    docs_tokens: Sequence[list[str]],
    *,
    idf_map: dict[str, float] | None = None,
) -> tuple[list[dict[str, float]], dict[str, float]]:
    """Build L2-normalized sparse TF-IDF dicts in pure Python + math (zero sklearn dependency)."""
    if idf_map is None:
        n_docs = len(docs_tokens)
        df: Counter[str] = Counter()
        for toks in docs_tokens:
            for tok in set(toks):
                df[tok] += 1
        idf_map = {tok: math.log((1.0 + n_docs) / (1.0 + cnt)) + 1.0 for tok, cnt in df.items()}

    vecs: list[dict[str, float]] = []
    for toks in docs_tokens:
        if not toks:
            vecs.append({})
            continue
        tf = Counter(toks)
        vec: dict[str, float] = {}
        sq_sum = 0.0
        for tok, cnt in tf.items():
            idf = idf_map.get(tok)
            if idf is None:
                continue
            w = (1.0 + math.log(cnt)) * idf
            vec[tok] = w
            sq_sum += w * w
        if sq_sum > 0.0:
            inv_norm = 1.0 / math.sqrt(sq_sum)
            for tok in vec:
                vec[tok] *= inv_norm
        vecs.append(vec)
    return vecs, idf_map


def _sparse_cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b[tok] for tok, w in a.items() if tok in b)


_MINILM_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_MINILM_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


def _encode_minilm_via_offline_subprocess(texts: Sequence[str]) -> tuple[np.ndarray | None, bool]:
    """Run local cached all-MiniLM-L6-v2 via uv --offline --no-project --python 3.13 without mutating .venv."""
    if not texts:
        return np.zeros((0, 384), dtype=np.float32), True
    try:
        with tempfile.TemporaryDirectory(prefix="docmeta_minilm_") as tmpdir:
            tmp_p = Path(tmpdir)
            in_path = tmp_p / "texts.json"
            out_path = tmp_p / "embs.npy"
            safe_texts = [t[:3000].encode("utf-8", errors="replace").decode("utf-8") for t in texts]
            in_path.write_text(json.dumps(safe_texts, ensure_ascii=True), encoding="utf-8")
            worker = (
                "import json, pathlib, numpy as np, torch\n"
                "from sentence_transformers import SentenceTransformer\n"
                "torch.set_num_threads(4)\n"
                f"in_p = pathlib.Path({str(in_path)!r})\n"
                f"out_p = pathlib.Path({str(out_path)!r})\n"
                "texts = json.loads(in_p.read_text(encoding='utf-8'))\n"
                f"m = SentenceTransformer({_MINILM_MODEL!r}, revision={_MINILM_REVISION!r}, local_files_only=True, device='cpu')\n"
                "arr = np.asarray(m.encode(texts, batch_size=128, normalize_embeddings=True, show_progress_bar=False), dtype=np.float32)\n"
                "np.save(out_p, arr)\n"
            )
            env = {**os.environ, "HF_HUB_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false"}
            proc = subprocess.run(
                [
                    "uv",
                    "run",
                    "--offline",
                    "--no-project",
                    "--python",
                    "3.13",
                    "--with",
                    "sentence-transformers==6.2.0",
                    "python",
                    "-c",
                    worker,
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if proc.returncode != 0 or not out_path.is_file():
                return None, False
            arr = np.asarray(np.load(out_path), dtype=np.float32)
            if arr.ndim == 2 and len(arr) == len(texts):
                return arr, True
            return None, False
    except Exception:
        return None, False


def _try_minilm_embeddings(
    texts: Sequence[str],
    *,
    embed_fn: Callable[[Sequence[str]], np.ndarray] | None = None,
    use_minilm: bool | str = "auto",
) -> tuple[np.ndarray | None, bool]:
    if embed_fn is not None:
        arr = np.asarray(embed_fn(texts), dtype=np.float32)
        if arr.ndim == 2 and len(arr) == len(texts):
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            norms = np.where(norms == 0.0, 1.0, norms)
            return arr / norms, True
        return None, False

    if use_minilm is False:
        return None, False

    if importlib.util.find_spec("sentence_transformers") is not None and use_minilm != "subprocess":
        try:
            st_mod = importlib.import_module("sentence_transformers")
            try:
                model = st_mod.SentenceTransformer(
                    _MINILM_MODEL,
                    revision=_MINILM_REVISION,
                    local_files_only=True,
                    device="cpu",
                )
            except Exception:
                model = st_mod.SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True, device="cpu")
            arr = np.asarray(
                model.encode(list(texts), batch_size=128, normalize_embeddings=True, show_progress_bar=False),
                dtype=np.float32,
            )
            return arr, True
        except Exception:
            pass

    if use_minilm == "subprocess" or (use_minilm in (True, "auto") and os.environ.get("DOCMETA_MINILM_SUBPROCESS") == "1"):
        return _encode_minilm_via_offline_subprocess(texts)

    return None, False


def audit_decontamination(
    train_docs: Sequence[Mapping[str, Any]],
    eval_docs: Sequence[Mapping[str, Any]],
    *,
    ngram8_threshold: float = 0.50,
    ngram13_threshold: float = 0.50,
    tfidf_threshold: float = 0.80,
    minilm_threshold: float = 0.90,
    use_minilm: bool | str = "auto",
    embed_fn: Callable[[Sequence[str]], np.ndarray] | None = None,
    text_key: str = "text",
    id_key: str = "doc_key",
) -> DecontaminationReport:
    """Run dual-mode decontamination checks of `eval_docs` against `train_docs`."""
    train_texts = [str(d.get(text_key) or "") for d in train_docs]
    eval_texts = [str(d.get(text_key) or "") for d in eval_docs]
    train_ids = [str(d.get(id_key) or f"train_{i}") for i, d in enumerate(train_docs)]
    eval_ids = [str(d.get(id_key) or f"eval_{i}") for i, d in enumerate(eval_docs)]
    eval_splits = [str(d.get("split") or "eval") for d in eval_docs]

    if not train_docs or not eval_docs:
        return DecontaminationReport(
            clean=True,
            train_count=len(train_docs),
            eval_count=len(eval_docs),
            flagged_count=0,
            minilm_checked=False,
        )

    # Exact & normalized hashes + event keys.
    train_exact: dict[str, str] = {}
    train_norm: dict[str, str] = {}
    train_events: dict[str, str] = {}
    for i, txt in enumerate(train_texts):
        tid = train_ids[i]
        train_exact.setdefault(text_sha256(txt), tid)
        train_norm.setdefault(normalized_text_sha256(txt), tid)
        ev, _ = extract_event_group_key(train_docs[i])
        if ev:
            train_events.setdefault(ev, tid)

    # 8-gram and 13-gram inverted indexes over train docs.
    train_tokens = [word_tokens(t) for t in train_texts]
    eval_tokens = [word_tokens(t) for t in eval_texts]

    train_sh8 = [word_shingles(toks, 8) for toks in train_tokens]
    train_sh13 = [word_shingles(toks, 13) for toks in train_tokens]
    post8: dict[int, list[int]] = defaultdict(list)
    post13: dict[int, list[int]] = defaultdict(list)
    for ti, sh in enumerate(train_sh8):
        for g in sh:
            post8[g].append(ti)
    for ti, sh in enumerate(train_sh13):
        for g in sh:
            post13[g].append(ti)

    # TF-IDF vectors (vocab/IDF built across combined corpus for accurate rarity weighting).
    all_vecs, _ = _compute_tfidf_vectors(train_tokens + eval_tokens)
    train_vecs = all_vecs[: len(train_docs)]
    eval_vecs = all_vecs[len(train_docs) :]
    tfidf_post: dict[str, list[int]] = defaultdict(list)
    for ti, vec in enumerate(train_vecs):
        for tok in vec:
            tfidf_post[tok].append(ti)

    # Optional dense MiniLM embeddings.
    dense_embs, minilm_checked = _try_minilm_embeddings(
        train_texts + eval_texts,
        embed_fn=embed_fn,
        use_minilm=use_minilm,
    )
    train_dense = dense_embs[: len(train_docs)] if dense_embs is not None else None
    eval_dense = dense_embs[len(train_docs) :] if dense_embs is not None else None

    flagged: list[DecontamFlag] = []
    reason_counts: Counter[str] = Counter()

    for ei, etxt in enumerate(eval_texts):
        eid = eval_ids[ei]
        esp = eval_splits[ei]
        reasons: list[str] = []
        best_train_id = ""

        ex_h = text_sha256(etxt)
        if ex_h in train_exact:
            reasons.append("exact_sha")
            best_train_id = train_exact[ex_h]

        nm_h = normalized_text_sha256(etxt)
        if nm_h in train_norm:
            reasons.append("normalized_text_hash")
            best_train_id = best_train_id or train_norm[nm_h]

        ev_key, _ = extract_event_group_key(eval_docs[ei])
        if ev_key and ev_key in train_events:
            reasons.append("event_group_overlap")
            best_train_id = best_train_id or train_events[ev_key]

        # 8-gram containment (checked against eval length AND substantial train docs >= 10 shingles).
        e_sh8 = word_shingles(eval_tokens[ei], 8)
        max8 = 0.0
        max8_ti: int | None = None
        if e_sh8:
            hits8: Counter[int] = Counter()
            for g in e_sh8:
                for ti in post8.get(g, ()):
                    hits8[ti] += 1
            for ti, inter in hits8.items():
                score = inter / len(e_sh8)
                if len(train_sh8[ti]) >= 10:
                    score = max(score, inter / len(train_sh8[ti]))
                if score > max8:
                    max8 = score
                    max8_ti = ti
            if max8 >= ngram8_threshold:
                reasons.append("ngram8_containment")
                if max8_ti is not None and not best_train_id:
                    best_train_id = train_ids[max8_ti]

        # 13-gram containment.
        e_sh13 = word_shingles(eval_tokens[ei], 13)
        max13 = 0.0
        max13_ti: int | None = None
        if e_sh13:
            hits13: Counter[int] = Counter()
            for g in e_sh13:
                for ti in post13.get(g, ()):
                    hits13[ti] += 1
            for ti, inter in hits13.items():
                score = inter / len(e_sh13)
                if len(train_sh13[ti]) >= 10:
                    score = max(score, inter / len(train_sh13[ti]))
                if score > max13:
                    max13 = score
                    max13_ti = ti
            if max13 >= ngram13_threshold:
                reasons.append("ngram13_containment")
                if max13_ti is not None and not best_train_id:
                    best_train_id = train_ids[max13_ti]

        # TF-IDF cosine via inverted candidate postings.
        e_vec = eval_vecs[ei]
        max_tfidf = 0.0
        max_tfidf_ti: int | None = None
        if e_vec:
            cand_tis: set[int] = set()
            for tok in e_vec:
                cand_tis.update(tfidf_post.get(tok, ()))
            for ti in cand_tis:
                cos = _sparse_cosine(e_vec, train_vecs[ti])
                if cos > max_tfidf:
                    max_tfidf = cos
                    max_tfidf_ti = ti
            if max_tfidf >= tfidf_threshold:
                reasons.append("tfidf_cosine")
                if max_tfidf_ti is not None and not best_train_id:
                    best_train_id = train_ids[max_tfidf_ti]

        # Optional MiniLM dense cosine.
        max_minilm: float | None = None
        if train_dense is not None and eval_dense is not None:
            sims = train_dense @ eval_dense[ei]
            best_dense_ti = int(np.argmax(sims))
            max_minilm = float(sims[best_dense_ti])
            if max_minilm >= minilm_threshold:
                reasons.append("minilm_cosine")
                if not best_train_id:
                    best_train_id = train_ids[best_dense_ti]

        if reasons:
            for r in reasons:
                reason_counts[r] += 1
            flagged.append(
                DecontamFlag(
                    eval_doc_key=eid,
                    eval_split=esp,
                    matched_train_doc_key=best_train_id,
                    reasons=reasons,
                    ngram8_containment=max8,
                    ngram13_containment=max13,
                    tfidf_cosine=max_tfidf,
                    minilm_cosine=max_minilm,
                )
            )

    return DecontaminationReport(
        clean=len(flagged) == 0,
        train_count=len(train_docs),
        eval_count=len(eval_docs),
        flagged_count=len(flagged),
        flagged_docs=flagged,
        reason_counts=dict(reason_counts),
        minilm_checked=minilm_checked,
    )


def _label_str(val: Any) -> str:
    return "<NONE>" if val is None else str(val)


def _binary_kappa_and_ac1(tp: int, fp: int, fn: int, tn: int) -> tuple[float, float]:
    n = tp + fp + fn + tn
    if n == 0:
        return 0.0, 0.0
    po = (tp + tn) / n
    r_pos = tp + fn
    c_pos = tp + fp
    r_neg = tn + fp
    c_neg = tn + fn

    pe_k = (r_pos * c_pos + r_neg * c_neg) / (n * n)
    if abs(1.0 - pe_k) < 1e-12:
        kappa = 1.0 if abs(po - 1.0) < 1e-12 else 0.0
    else:
        kappa = (po - pe_k) / (1.0 - pe_k)

    pi_pos = (r_pos + c_pos) / (2.0 * n)
    pe_ac1 = 2.0 * pi_pos * (1.0 - pi_pos)
    if abs(1.0 - pe_ac1) < 1e-12:
        ac1 = 1.0 if abs(po - 1.0) < 1e-12 else 0.0
    else:
        ac1 = (po - pe_ac1) / (1.0 - pe_ac1)
    return kappa, ac1


def compute_agreement_metrics(
    y_true: Sequence[Any],
    y_pred: Sequence[Any],
    *,
    labels: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Compute accuracy, Macro-F1, Weighted-F1, multi-class Cohen's kappa, Gwet's AC1, and confusion."""
    if len(y_true) != len(y_pred):
        raise ValueError(f"Length mismatch: len(y_true)={len(y_true)} vs len(y_pred)={len(y_pred)}")

    n = len(y_true)
    if n == 0:
        return {
            "n_total": 0,
            "labels": [],
            "accuracy": 0.0,
            "macro_f1": 0.0,
            "weighted_f1": 0.0,
            "cohen_kappa": 0.0,
            "gwet_ac1": 0.0,
            "per_class": {},
            "confusion": {},
        }

    true_s = [_label_str(x) for x in y_true]
    pred_s = [_label_str(x) for x in y_pred]

    observed_labels = sorted(set(true_s) | set(pred_s))
    if labels is not None:
        ordered = [_label_str(x) for x in labels]
        for lbl in observed_labels:
            if lbl not in ordered:
                ordered.append(lbl)
        label_list = ordered
    else:
        label_list = observed_labels

    confusion_counter: dict[str, Counter[str]] = defaultdict(Counter)
    row_sum: Counter[str] = Counter()
    col_sum: Counter[str] = Counter()
    correct = 0

    for t, p in zip(true_s, pred_s):
        confusion_counter[t][p] += 1
        row_sum[t] += 1
        col_sum[p] += 1
        if t == p:
            correct += 1

    po = correct / n

    # Multi-class Cohen's kappa.
    pe_kappa = sum((row_sum[lbl] / n) * (col_sum[lbl] / n) for lbl in label_list)
    if abs(1.0 - pe_kappa) < 1e-12:
        cohen_kappa = 1.0 if abs(po - 1.0) < 1e-12 else 0.0
    else:
        cohen_kappa = (po - pe_kappa) / (1.0 - pe_kappa)

    # Multi-class Gwet's AC1 (Gwet, 2008).
    k_cls = len(label_list)
    if k_cls < 2:
        gwet_ac1 = 1.0 if abs(po - 1.0) < 1e-12 else 0.0
    else:
        sum_pi_one_minus = sum(
            ((row_sum[lbl] + col_sum[lbl]) / (2.0 * n))
            * (1.0 - ((row_sum[lbl] + col_sum[lbl]) / (2.0 * n)))
            for lbl in label_list
        )
        pe_ac1 = sum_pi_one_minus / (k_cls - 1)
        if abs(1.0 - pe_ac1) < 1e-12:
            gwet_ac1 = 1.0 if abs(po - 1.0) < 1e-12 else 0.0
        else:
            gwet_ac1 = (po - pe_ac1) / (1.0 - pe_ac1)

    per_class: dict[str, dict[str, Any]] = {}
    f1_vals: list[float] = []
    weighted_f1_sum = 0.0
    for lbl in label_list:
        tp = confusion_counter[lbl][lbl]
        sup = row_sum[lbl]
        pred_cnt = col_sum[lbl]
        fp = pred_cnt - tp
        fn = sup - tp
        tn = n - tp - fp - fn

        prec = tp / pred_cnt if pred_cnt > 0 else 0.0
        rec = tp / sup if sup > 0 else 0.0
        f1 = (2.0 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        k_bin, ac1_bin = _binary_kappa_and_ac1(tp, fp, fn, tn)

        per_class[lbl] = {
            "n": sup,
            "pred": pred_cnt,
            "tp": tp,
            "precision": prec,
            "recall": rec,
            "f1": f1,
            "kappa": k_bin,
            "ac1": ac1_bin,
        }
        f1_vals.append(f1)
        weighted_f1_sum += sup * f1

    macro_f1 = sum(f1_vals) / len(f1_vals) if f1_vals else 0.0
    weighted_f1 = weighted_f1_sum / n

    confusion = {
        t_lbl: {p_lbl: int(cnt) for p_lbl, cnt in sorted(preds.items())}
        for t_lbl, preds in sorted(confusion_counter.items())
    }

    return {
        "n_total": n,
        "labels": label_list,
        "accuracy": po,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "cohen_kappa": cohen_kappa,
        "gwet_ac1": gwet_ac1,
        "per_class": per_class,
        "confusion": confusion,
    }


__all__ = [
    "DecontamFlag",
    "DecontaminationReport",
    "SplitAssignmentResult",
    "audit_decontamination",
    "build_event_temporal_splits",
    "compute_agreement_metrics",
    "extract_event_group_key",
    "normalized_text_sha256",
    "normalize_text_for_dedup",
    "text_sha256",
    "word_shingles",
    "word_tokens",
]
