"""Opt-in CPU BM25 / TF-IDF multi-crop evidence window selector (`lexical_multicrop_v6.py`).

Disabled by default in ``run_docmeta_parquet_sweep`` (``bm25_multicrop=False``) because
full-text prefill on fast-gemma4 is lossless and higher quality on <=3k-4k char docs,
while opt-in ``bm25_multicrop=True`` lets throughput-bound sweeps over very long documents
crop middle spans while preserving full raw text for post-pass/grounding/sidecar checks.

Top-level import is 100% Python stdlib (``/usr/bin/python3 -B -I -S`` clean).
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Literal, Sequence

from .atomic_validator_v6 import ALL_KIND_DESC_V6

LexicalMethod = Literal["bm25", "tfidf"]

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "have",
        "has",
        "had",
        "were",
        "was",
        "are",
        "not",
        "but",
        "you",
        "your",
        "all",
        "any",
        "can",
        "will",
        "would",
        "there",
        "their",
        "which",
        "who",
        "whom",
        "what",
        "when",
        "where",
        "into",
        "about",
        "other",
        "such",
        "than",
        "then",
        "them",
        "these",
        "those",
        "its",
        "our",
        "out",
        "been",
        "being",
        "also",
        "more",
        "only",
        "very",
    }
)


def _tokenize_lexical(text: str) -> list[str]:
    return [tok for tok in _TOKEN_RE.findall((text or "").lower()) if tok not in _STOPWORDS]


@dataclass(frozen=True)
class WindowSpan:
    """Sliding window chunk with retrieval score."""

    index: int
    start_char: int
    end_char: int
    text: str
    lexical_score: float = 0.0


def slice_document_windows(
    text: str,
    *,
    win_chars: int = 450,
    stride_chars: int = 320,
    skip_head_chars: int = 0,
    skip_tail_chars: int = 0,
) -> list[WindowSpan]:
    """Slice document text into deterministic sliding windows outside reserved anchor ranges."""
    clean = text or ""
    lo = max(0, int(skip_head_chars))
    hi = max(lo, len(clean) - max(0, int(skip_tail_chars)))
    span_src = clean[lo:hi]
    if not span_src.strip():
        return []
    win = max(64, int(win_chars))
    stride = max(32, int(stride_chars))
    out: list[WindowSpan] = []
    pos = 0
    idx = 0
    while pos < len(span_src):
        end = min(len(span_src), pos + win)
        chunk = span_src[pos:end].strip()
        if chunk:
            out.append(WindowSpan(index=idx, start_char=lo + pos, end_char=lo + end, text=chunk))
            idx += 1
        if end >= len(span_src):
            break
        pos += stride
    return out


def build_evidence_queries(
    conformal_set: Sequence[str] = (),
    *,
    filename: str = "",
    known_str: str = "",
) -> list[str]:
    """Construct congressional domain + CROQ-conditioned queries for middle-window ranking."""
    queries: list[str] = [
        "House Senate committee subcommittee hearing testimony chairman ranking member",
        "witness statement representative senator congressman congresswoman panel",
        "date january february march april may june july august september october november december 2023 2024 2025",
        "bill H.R. S. Res. Con. P.L. Congress letter correspondence",
    ]
    kind_cues = [f"{k.replace('_', ' ')} {ALL_KIND_DESC_V6.get(k, '')}".strip() for k in conformal_set[:4] if k]
    if kind_cues:
        queries.append(" ".join(kind_cues))
    ctx_bits = [b for b in (filename, known_str) if b and b != "<NONE>" and b != "{}"]
    if ctx_bits:
        queries.append(" ".join(ctx_bits))
    return queries


class LexicalWindowRanker:
    """Zero-dependency pure-Python CPU BM25 / sublinear TF-IDF window evidence ranker."""

    def __init__(
        self,
        *,
        method: LexicalMethod = "bm25",
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        if method not in ("bm25", "tfidf"):
            raise ValueError(f"Unsupported lexical method={method!r}")
        self.method: LexicalMethod = method
        self.k1 = float(k1)
        self.b = float(b)

    def score_windows(
        self,
        windows: Sequence[str],
        queries: Sequence[str],
        *,
        query_agg: Literal["max", "mean", "sum"] = "sum",
    ) -> list[float]:
        """Return lexical relevance scores ``len == len(windows)`` for ``queries``."""
        n_docs = len(windows)
        if n_docs == 0 or not queries:
            return [0.0] * n_docs

        doc_tokens = [_tokenize_lexical(w) for w in windows]
        tfs: list[dict[str, int]] = []
        df: dict[str, int] = {}
        for toks in doc_tokens:
            counts: dict[str, int] = {}
            for t in toks:
                counts[t] = counts.get(t, 0) + 1
            tfs.append(counts)
            for t in counts:
                df[t] = df.get(t, 0) + 1

        q_tok_lists = [_tokenize_lexical(q) for q in queries if q and q.strip()]
        if not q_tok_lists:
            return [0.0] * n_docs

        n_q = len(q_tok_lists)
        per_query_scores: list[list[float]] = [[0.0] * n_docs for _ in range(n_q)]
        if self.method == "bm25":
            avgdl = max(sum(len(t) for t in doc_tokens) / max(n_docs, 1), 1.0)
            for qi, qtoks in enumerate(q_tok_lists):
                uniq_q = set(qtoks)
                row_q = per_query_scores[qi]
                for di, counts in enumerate(tfs):
                    dl = len(doc_tokens[di])
                    norm_len = 1.0 - self.b + self.b * (dl / avgdl)
                    score = 0.0
                    for qt in uniq_q:
                        tf = counts.get(qt, 0)
                        if tf == 0:
                            continue
                        n_qi = df.get(qt, 0)
                        idf = math.log((n_docs - n_qi + 0.5) / (n_qi + 0.5) + 1.0)
                        denom = tf + self.k1 * norm_len
                        score += idf * ((tf * (self.k1 + 1.0)) / max(denom, 1e-12))
                    row_q[di] = score
        else:
            idf_map = {t: math.log((n_docs + 1.0) / (c + 1.0)) + 1.0 for t, c in df.items()}
            doc_vecs: list[dict[str, float]] = []
            doc_norms: list[float] = []
            for counts in tfs:
                vec = {t: (1.0 + math.log(tf)) * idf_map[t] for t, tf in counts.items()}
                norm = math.sqrt(sum(v * v for v in vec.values()))
                doc_vecs.append(vec)
                doc_norms.append(max(norm, 1e-12))
            for qi, qtoks in enumerate(q_tok_lists):
                q_counts: dict[str, int] = {}
                for t in qtoks:
                    if t in idf_map:
                        q_counts[t] = q_counts.get(t, 0) + 1
                q_vec = {t: (1.0 + math.log(tf)) * idf_map[t] for t, tf in q_counts.items()}
                q_norm = math.sqrt(sum(v * v for v in q_vec.values()))
                if q_norm <= 1e-12:
                    continue
                row_q = per_query_scores[qi]
                for di, d_vec in enumerate(doc_vecs):
                    dot = sum(qv * d_vec.get(t, 0.0) for t, qv in q_vec.items())
                    row_q[di] = dot / (q_norm * doc_norms[di])

        if query_agg == "max":
            return [max(per_query_scores[qi][di] for qi in range(n_q)) for di in range(n_docs)]
        if query_agg == "mean":
            return [sum(per_query_scores[qi][di] for qi in range(n_q)) / n_q for di in range(n_docs)]
        return [sum(per_query_scores[qi][di] for qi in range(n_q)) for di in range(n_docs)]


def pack_bm25_multicrop_text_v6(
    clean_text: str,
    *,
    conformal_set: Sequence[str] = (),
    filename: str = "",
    known_str: str = "",
    long_threshold: int = 3000,
    head_chars: int = 950,
    tail_chars: int = 350,
    win_chars: int = 450,
    stride_chars: int = 320,
    top_k: int = 2,
    min_gap_chars: int = 220,
    method: LexicalMethod = "bm25",
    ranker: LexicalWindowRanker | None = None,
) -> tuple[str, list[WindowSpan]]:
    """Pack long text as ``head + top-k non-overlapping BM25 windows + tail``."""
    raw = clean_text or ""
    if len(raw) <= long_threshold:
        return raw, []

    head = raw[:head_chars].rstrip()
    tail = raw[-tail_chars:].lstrip() if tail_chars > 0 and len(raw) > head_chars + tail_chars else ""
    skip_tail = tail_chars if tail else 0
    spans = slice_document_windows(
        raw,
        win_chars=win_chars,
        stride_chars=stride_chars,
        skip_head_chars=head_chars,
        skip_tail_chars=skip_tail,
    )
    if not spans:
        packed = f"{head}\n[...]\n{tail}" if tail else head
        return packed, []

    queries = build_evidence_queries(conformal_set, filename=filename, known_str=known_str)
    active_ranker = ranker or LexicalWindowRanker(method=method)
    scores = active_ranker.score_windows([s.text for s in spans], queries)
    ranked_order = sorted(range(len(spans)), key=lambda i: (-scores[i], i))

    selected: list[WindowSpan] = []
    for idx_s in ranked_order:
        if len(selected) >= max(0, int(top_k)):
            break
        sp = spans[idx_s]
        if any(abs(sp.start_char - sel.start_char) < min_gap_chars for sel in selected):
            continue
        selected.append(
            WindowSpan(
                index=sp.index,
                start_char=sp.start_char,
                end_char=sp.end_char,
                text=sp.text,
                lexical_score=round(float(scores[idx_s]), 6),
            )
        )

    selected_doc_order = sorted(selected, key=lambda x: x.start_char)
    parts = [head]
    for sp in selected_doc_order:
        parts.append(f"[EVIDENCE @{sp.start_char}]\n{sp.text}")
    if tail:
        parts.append(f"[TAIL]\n{tail}")
    return "\n[...]\n".join(parts), selected_doc_order


__all__ = [
    "LexicalMethod",
    "LexicalWindowRanker",
    "WindowSpan",
    "build_evidence_queries",
    "pack_bm25_multicrop_text_v6",
    "slice_document_windows",
]
