"""Shared DRY foundation for Corpus Quality & Dataset Validation (`corpus_quality.core`).

Provides canonical row/finding dataclasses, column-projected DuckDB/PyArrow Parquet
readers joining published tables (`detail.parquet`, `list.parquet`, `sources.parquet`)
with optional `docmeta_v6_1` sidecars by `link_key`, plus shared text windowing,
n-gram tokenization, structural shingling, and archive-unwrapped URL path templating.
"""
from __future__ import annotations

from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import re
from typing import Any, Literal
from urllib.parse import unquote

import duckdb
import pyarrow.parquet as pq

Severity = Literal["error", "warning", "info"]

DEFAULT_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
    }
)

_WAYBACK_RE = re.compile(
    r"^https?://web\.archive\.org/web/(\d{8,14})[a-z_]*/(https?://.+)$",
    re.I,
)
_WEBHARVEST_RE = re.compile(
    r"^https?://(?:www\.)?(?:congressional|senate)?\.?webharvest\.gov/[^/]+/(\d{8,14})/(https?://.+)$",
    re.I,
)
_SCHEME_HOST_RE = re.compile(r"^https?://([^/?#]+)(.*)$", re.I)

_WORD_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]*")
_PURE_DIGITS_RE = re.compile(r"^\d+$")
_APOSTROPHE_RE = re.compile(r"[’`]")

# Structural shingle normalization patterns
_SHINGLE_ISO_DATE_RE = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")
_SHINGLE_LONG_DATE_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+\d{1,2},?\s+(?:19|20)\d{2}\b",
    re.I,
)
_SHINGLE_CONGRESS_ORD_RE = re.compile(r"\b1\d{2}(?:st|nd|rd|th)\s+Congress\b", re.I)
_SHINGLE_CLERK_SLUG_RE = re.compile(
    r"\b(?:HHRG|HMTG|HMKP|BILLS|CRPT|CHRG|SHRG|CDOC|PLAW)-\d{3}[A-Za-z0-9._-]*\b",
    re.I,
)
_SHINGLE_HEX_RE = re.compile(r"\b[0-9a-fA-F]{12,64}\b")
_SHINGLE_NUM_RE = re.compile(r"\b\d+(?:[.,:/-]\d+)*\b")
_SHINGLE_WS_RE = re.compile(r"\s+")
_GPO_LINE_NUM_PREFIX_RE = re.compile(r"^\s*[·.]?\d{1,2}[·.]?\s+")

# URL segment normalization patterns
_UUID_SEG_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?:\.[a-z0-9]{1,6})?$",
    re.I,
)
_HEX_SEG_RE = re.compile(r"^[0-9a-f]{16,64}(?:\.[a-z0-9]{1,6})?$", re.I)
_YYYYMMDD_SEG_RE = re.compile(r"^(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])$")
_ISO_DATE_SEG_RE = re.compile(r"^(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")
_YYYY_MM_SEG_RE = re.compile(r"^(?:19|20)\d{2}-(?:0[1-9]|1[0-2])$")
_YEAR_SEG_RE = re.compile(r"^(?:19|20)\d{2}$")
_MONTH_SEG_RE = re.compile(r"^(?:0[1-9]|1[0-2])$")
_CONGRESS_SEG_RE = re.compile(r"^1[0-2]\d$")
_INT_SEG_RE = re.compile(r"^\d+$")
_CLERK_FILE_SEG_RE = re.compile(
    r"^(HHRG|HMTG|HMKP|BILLS|CRPT|CHRG|SHRG|CDOC|PLAW)-\d{3}[A-Za-z0-9._-]*?(\.[A-Za-z0-9]{2,5})?$",
    re.I,
)
_HOUSE_SUBCODE_SEG_RE = re.compile(r"^[A-Z]{2}\d{2}$")
_HOUSE_CMT2_SEG_RE = re.compile(r"^[A-Z]{2}$")
_COMMITTEE_KEY_SEG_RE = re.compile(r"^[a-z]{4}\d{2}$")


@dataclass(frozen=True, slots=True)
class QualityFinding:
    """Standardized validation / drift / anomaly finding across all corpus-quality checks."""

    code: str
    severity: Severity
    category: str
    link_key_hex: str
    filename: str
    expected: Any = None
    observed: Any = None
    score: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "category": self.category,
            "link_key_hex": self.link_key_hex,
            "filename": self.filename,
            "expected": self.expected,
            "observed": self.observed,
            "score": round(float(self.score), 6),
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class CorpusDocRow:
    """Canonical joined document row across published release tables and optional `docmeta_v6_1`."""

    link_key_hex: str
    list_row: int = 0
    doc_key: str = ""
    saved_body_hex: str = ""
    effective_body_sha_hex: str = ""
    package_id: str | None = None
    filename: str = ""
    title: str | None = None
    format: str | None = None
    effective_format: str | None = None
    source_url: str | None = None
    listed_on: str | None = None
    member_path: str | None = None
    link_texts: tuple[str, ...] = ()
    host: str | None = None
    document_kind: tuple[str, ...] = ()
    document_family: tuple[str, ...] = ()
    congress: int | None = None
    committee_keys: tuple[str, ...] = ()
    chambers: tuple[str, ...] = ()
    document_date: str | None = None
    date_kind: str | None = None
    document_date_status: str | None = None
    document_date_source: str | None = None
    meeting_keys: tuple[str, ...] = ()
    measure_keys: tuple[str, ...] = ()
    bioguide_ids: tuple[str, ...] = ()
    witness_keys: tuple[str, ...] = ()
    main_content_outcome: str | None = None
    reading_status: str | None = None
    p12_text: str = ""
    text_source: str | None = None
    disposition: str | None = None
    sub_disposition: str | None = None
    v6_route: str | None = None
    zero_llm_source: str | None = None
    docmeta_primary_kind: str | None = None
    grammar_lock_source: str | None = None
    docmeta_status: str | None = None
    docmeta_congress: int | None = None
    docmeta_chamber: str | None = None
    docmeta_committees: tuple[str, ...] = ()
    docmeta_json: str | None = None
    strict_v4_valid: bool | None = None
    is_alias: bool = False

    @property
    def primary_published_kind(self) -> str | None:
        return self.document_kind[0] if self.document_kind else None

    @property
    def effective_kind(self) -> str | None:
        return self.docmeta_primary_kind or self.primary_published_kind

    @property
    def file_ext(self) -> str:
        if self.filename and "." in self.filename:
            ext = self.filename.rsplit(".", 1)[-1].strip().lower()
            if 1 <= len(ext) <= 6 and ext.isalnum():
                return ext
        return (self.effective_format or self.format or "").strip().lower()

    def to_dict(self) -> dict[str, Any]:
        return {
            "link_key_hex": self.link_key_hex,
            "list_row": self.list_row,
            "doc_key": self.doc_key,
            "saved_body_hex": self.saved_body_hex,
            "effective_body_sha_hex": self.effective_body_sha_hex,
            "package_id": self.package_id,
            "filename": self.filename,
            "title": self.title,
            "format": self.format,
            "effective_format": self.effective_format,
            "source_url": self.source_url,
            "listed_on": self.listed_on,
            "member_path": self.member_path,
            "link_texts": list(self.link_texts),
            "host": self.host,
            "document_kind": list(self.document_kind),
            "document_family": list(self.document_family),
            "congress": self.congress,
            "committee_keys": list(self.committee_keys),
            "chambers": list(self.chambers),
            "document_date": self.document_date,
            "date_kind": self.date_kind,
            "document_date_status": self.document_date_status,
            "document_date_source": self.document_date_source,
            "meeting_keys": list(self.meeting_keys),
            "measure_keys": list(self.measure_keys),
            "bioguide_ids": list(self.bioguide_ids),
            "witness_keys": list(self.witness_keys),
            "main_content_outcome": self.main_content_outcome,
            "reading_status": self.reading_status,
            "p12_text": self.p12_text,
            "text_source": self.text_source,
            "disposition": self.disposition,
            "sub_disposition": self.sub_disposition,
            "v6_route": self.v6_route,
            "zero_llm_source": self.zero_llm_source,
            "docmeta_primary_kind": self.docmeta_primary_kind,
            "grammar_lock_source": self.grammar_lock_source,
            "docmeta_status": self.docmeta_status,
            "docmeta_congress": self.docmeta_congress,
            "docmeta_chamber": self.docmeta_chamber,
            "docmeta_committees": list(self.docmeta_committees),
            "docmeta_json": self.docmeta_json,
            "strict_v4_valid": self.strict_v4_valid,
            "is_alias": self.is_alias,
        }


@dataclass(frozen=True, slots=True)
class HeaderFooterWindows:
    """Extracted opening header, middle body, and trailing footer slices of document text.

    Supports both attribute access (`win.header`, `win.footer`, `win.body`,
    `win.header_lines`, `win.footer_lines`) and 2-tuple unpacking
    (`header, footer = extract_header_footer_windows(text)`).
    """

    header: str
    footer: str
    body: str
    header_lines: tuple[str, ...]
    footer_lines: tuple[str, ...]

    def __iter__(self) -> Iterator[str]:
        yield self.header
        yield self.footer


def extract_header_footer_windows(
    text: str | None,
    *,
    max_header_lines: int = 24,
    max_footer_lines: int = 12,
    max_header_chars: int = 1800,
    max_footer_chars: int = 900,
) -> HeaderFooterWindows:
    """Extract normalized opening header, middle body, and trailing footer windows."""
    if not text:
        return HeaderFooterWindows(
            header="",
            footer="",
            body="",
            header_lines=(),
            footer_lines=(),
        )
    non_empty = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not non_empty:
        return HeaderFooterWindows(
            header="",
            footer="",
            body="",
            header_lines=(),
            footer_lines=(),
        )

    h_lines = tuple(non_empty[:max_header_lines])
    header = "\n".join(h_lines)[:max_header_chars]

    if len(non_empty) <= max_header_lines:
        f_start = max(0, len(non_empty) - min(max_footer_lines, max(1, len(non_empty) // 3)))
        f_lines = tuple(non_empty[f_start:]) if len(non_empty) > 3 else ()
        body_lines = non_empty[len(h_lines) :]
    else:
        f_start = max(max_header_lines, len(non_empty) - max_footer_lines)
        f_lines = tuple(non_empty[f_start:])
        body_lines = non_empty[max_header_lines:f_start]

    footer = "\n".join(f_lines)[-max_footer_chars:] if f_lines else ""
    body = "\n".join(body_lines)
    return HeaderFooterWindows(
        header=header,
        footer=footer,
        body=body,
        header_lines=h_lines,
        footer_lines=f_lines,
    )


def tokenize_words(
    text: str | None,
    *,
    lowercase: bool = True,
    drop_pure_digits: bool = True,
    min_len: int = 2,
) -> list[str]:
    """Tokenize text into normalized word tokens for TF-IDF / log-odds scoring."""
    if not text:
        return []
    cleaned = _APOSTROPHE_RE.sub("'", text)
    if lowercase:
        cleaned = cleaned.lower()
    out: list[str] = []
    for m in _WORD_TOKEN_RE.finditer(cleaned):
        tok = m.group(0).strip("'-")
        if len(tok) < min_len:
            continue
        if drop_pure_digits and _PURE_DIGITS_RE.match(tok):
            continue
        out.append(tok)
    return out


def iter_word_ngrams(
    text: str | None,
    n: Sequence[int] = (1, 2, 3),
    *,
    ngram_range: tuple[int, int] | None = None,
    lowercase: bool = True,
    drop_pure_digits: bool = True,
    stopwords: Collection[str] = (),
) -> Iterator[str]:
    """Yield word `k`-grams across `text` for each `k` in `n` (or inclusive `ngram_range`).

    Unigrams in `stopwords` are skipped; higher-order n-grams drop boundary stopwords
    while preserving internal function words (`"truth in testimony"`, `"committee on rules"`).
    """
    if ngram_range is not None:
        lo, hi = int(ngram_range[0]), int(ngram_range[1])
        sizes = tuple(range(max(1, lo), max(1, hi) + 1))
    else:
        sizes = tuple(int(k) for k in n if int(k) >= 1)
    if not sizes or not text:
        return

    tokens = tokenize_words(text, lowercase=lowercase, drop_pure_digits=drop_pure_digits)
    if not tokens:
        return

    stop = {s.lower() if lowercase else s for s in stopwords} if stopwords else set()
    n_toks = len(tokens)
    for k in sizes:
        if k > n_toks:
            continue
        if k == 1:
            for tok in tokens:
                if tok not in stop:
                    yield tok
        else:
            for i in range(n_toks - k + 1):
                if stop and (tokens[i] in stop or tokens[i + k - 1] in stop):
                    continue
                yield " ".join(tokens[i : i + k])


def _normalize_structural_line(line: str) -> str:
    line = _GPO_LINE_NUM_PREFIX_RE.sub("", line).strip()
    if not line:
        return ""
    s = _SHINGLE_CLERK_SLUG_RE.sub("<SLUG>", line)
    s = _SHINGLE_ISO_DATE_RE.sub("<DATE>", s)
    s = _SHINGLE_LONG_DATE_RE.sub("<DATE>", s)
    s = _SHINGLE_CONGRESS_ORD_RE.sub("<CONG>", s)
    s = _SHINGLE_HEX_RE.sub("<HEX>", s)
    s = _SHINGLE_NUM_RE.sub("<NUM>", s)
    s = _SHINGLE_WS_RE.sub(" ", s).strip()
    return s


def structural_shingles(
    text: str | None,
    *,
    shingle_size: int = 3,
    max_lines: int = 40,
) -> frozenset[str]:
    """Compute deterministic structural header/form shingles for template clustering.

    Combines normalized opening-line skeletons (`line:...`), case/layout markers (`shape:...`),
    and sliding `shingle_size`-token shingles over the normalized header window (`tok:...`).
    """
    if not text:
        return frozenset({"shape:empty"})

    raw_lines = [ln for ln in text.splitlines() if ln.strip()][:max_lines]
    if not raw_lines:
        return frozenset({"shape:empty"})

    shingles: set[str] = set()
    norm_lines: list[str] = []
    caps_lines = 0
    qa_lines = 0
    checkbox_lines = 0
    pipe_lines = 0

    for idx, raw in enumerate(raw_lines):
        stripped = raw.strip()
        alpha = [c for c in stripped if c.isalpha()]
        if len(alpha) >= 6 and sum(1 for c in alpha if c.isupper()) / len(alpha) >= 0.80:
            caps_lines += 1
        if re.match(r"^(?:Q\.|A\.|QUESTION\s*\d*|ANSWER\s*\d*|MR\.|MS\.|SEN\.|REP\.|THE CHAIR)", stripped, re.I):
            qa_lines += 1
        if any(ch in stripped for ch in ("☐", "☑", "☒")) or re.search(r"\[\s*[xX ]?\s*\]", stripped):
            checkbox_lines += 1
        if stripped.count("|") >= 2 or "\t" in stripped:
            pipe_lines += 1

        norm = _normalize_structural_line(stripped)
        if not norm:
            continue
        norm_low = norm.lower()
        norm_lines.append(norm_low)
        if idx < 12:
            # Keep short structural line templates (headings, labels, form prompts)
            words = norm_low.split()
            if 1 <= len(words) <= 8:
                shingles.add(f"hdr:{' '.join(words)}")

    total = len(raw_lines)
    if caps_lines / total >= 0.35:
        shingles.add("shape:caps_heavy")
    if qa_lines >= 2:
        shingles.add("shape:qa_colloquy")
    if checkbox_lines >= 1:
        shingles.add("shape:checkbox_form")
    if pipe_lines >= 2:
        shingles.add("shape:table_grid")
    if len(text.strip()) < 240:
        shingles.add("shape:short_stub")

    joined = " ".join(norm_lines[:20])
    toks = re.findall(r"<[a-z]+>|[a-z][a-z'-]*", joined)
    k = max(1, int(shingle_size))
    if len(toks) < k and toks:
        shingles.add(f"tok:{' '.join(toks)}")
    else:
        for i in range(max(0, len(toks) - k + 1)):
            shingles.add(f"tok:{' '.join(toks[i : i + k])}")

    return frozenset(shingles) if shingles else frozenset({"shape:unstructured"})


def unwrap_archive_url(url: str | None) -> tuple[str, str | None, str | None]:
    """Unwrap Wayback (`web.archive.org`) or WebHarvest wrappers.

    Returns `(canonical_url, wrapper_kind, crawl_timestamp)`.
    """
    if not url or not isinstance(url, str):
        return ("", None, None)
    u = url.strip()
    wrapper_kind: str | None = None
    crawl_ts: str | None = None
    for _ in range(3):
        m_wb = _WAYBACK_RE.match(u)
        if m_wb:
            wrapper_kind = wrapper_kind or "wayback"
            crawl_ts = crawl_ts or m_wb.group(1)
            u = m_wb.group(2).strip()
            continue
        m_wh = _WEBHARVEST_RE.match(u)
        if m_wh:
            wrapper_kind = wrapper_kind or "webharvest"
            crawl_ts = crawl_ts or m_wh.group(1)
            u = m_wh.group(2).strip()
            continue
        break
    return (u, wrapper_kind, crawl_ts)


def extract_url_host(url: str | None) -> str | None:
    """Extract normalized lowercase hostname from a URL (after archive unwrapping)."""
    cu, _, _ = unwrap_archive_url(url)
    if not cu:
        return None
    m = _SCHEME_HOST_RE.match(cu)
    if not m:
        return None
    host = m.group(1).strip().lower()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if ":" in host:
        host_part, port = host.rsplit(":", 1)
        if port in ("80", "443", ""):
            host = host_part
    return host or None


def _template_segment(seg: str, *, prev_lower: str) -> str:
    decoded = unquote(seg).strip()
    if not decoded:
        return ""
    m_clerk = _CLERK_FILE_SEG_RE.match(decoded)
    if m_clerk:
        prefix = m_clerk.group(1).lower()
        ext = (m_clerk.group(2) or "").lower()
        return f"{{{prefix}_slug}}{ext}"
    if _UUID_SEG_RE.match(decoded):
        ext = "." + decoded.rsplit(".", 1)[-1].lower() if "." in decoded else ""
        return f"{{uuid}}{ext}"
    if _HEX_SEG_RE.match(decoded):
        ext = "." + decoded.rsplit(".", 1)[-1].lower() if "." in decoded else ""
        return f"{{hex}}{ext}"
    if _YYYYMMDD_SEG_RE.match(decoded):
        return "{yyyymmdd}"
    if _ISO_DATE_SEG_RE.match(decoded):
        return "{date}"
    if _YYYY_MM_SEG_RE.match(decoded):
        return "{yyyy-mm}"
    if _YEAR_SEG_RE.match(decoded):
        return "{yyyy}"
    if prev_lower in ("{yyyy}", "uploads", "files", "download") and _MONTH_SEG_RE.match(decoded):
        return "{mm}"
    if prev_lower in ("congress.gov", "committee-meeting", "hearing", "bill", "hearings") and _CONGRESS_SEG_RE.match(decoded):
        return "{congress}"
    if _INT_SEG_RE.match(decoded):
        return "{id}"
    if prev_lower == "meetings" and _HOUSE_CMT2_SEG_RE.match(decoded):
        return "{cmt2}"
    if prev_lower == "{cmt2}" and _HOUSE_SUBCODE_SEG_RE.match(decoded):
        return "{subcode}"
    if _COMMITTEE_KEY_SEG_RE.match(decoded):
        return "{cmt_key}"
    if "." in decoded:
        stem, ext = decoded.rsplit(".", 1)
        ext_l = ext.lower()
        if 1 <= len(ext_l) <= 5 and ext_l.isalnum():
            if len(stem) > 12 or any(ch.isdigit() for ch in stem):
                return f"{{file}}.{ext_l}"
            return f"{stem.lower()}.{ext_l}"
    if any(ch.isdigit() for ch in decoded) and len(decoded) > 10:
        return "{slug}"
    return decoded.lower()


def url_path_template(url: str | None) -> str:
    """Normalize an unwrapped URL into a structural `host/path` template for clustering."""
    cu, _, _ = unwrap_archive_url(url)
    if not cu:
        return ""
    m = _SCHEME_HOST_RE.match(cu)
    if not m:
        return ""
    host = extract_url_host(cu) or ""
    rest = m.group(2) or ""
    path_part = rest.split("#", 1)[0]
    query_part = ""
    if "?" in path_part:
        path_part, query_raw = path_part.split("?", 1)
        q_keys = sorted(
            {
                kv.split("=", 1)[0].strip().lower()
                for kv in query_raw.split("&")
                if kv.strip() and kv.split("=", 1)[0].strip()
            }
        )
        if q_keys:
            query_part = "?" + "&".join(f"{k}=*" for k in q_keys[:4])

    raw_segs = [s for s in path_part.split("/") if s]
    norm_segs: list[str] = []
    prev = host
    for seg in raw_segs[:10]:
        templated = _template_segment(seg, prev_lower=prev)
        if templated:
            norm_segs.append(templated)
            prev = templated
    if not norm_segs:
        return f"{host}/{query_part}".rstrip("/") if query_part else host
    return f"{host}/{'/'.join(norm_segs)}{query_part}"


def resolve_docmeta_paths(docmeta_dir: str | Path) -> dict[str, Path]:
    """Locate available `docmeta_v6_1` Parquet artifacts inside `docmeta_dir`."""
    base = Path(docmeta_dir)
    if not base.exists():
        raise FileNotFoundError(f"docmeta_dir does not exist: {base}")

    candidates: dict[str, tuple[str, ...]] = {
        "completed_no_llm": ("completed_no_llm_v6_1.parquet", "completed_no_llm.parquet"),
        "llm_queue": ("llm_queue_v6_1.parquet", "llm_queue.parquet"),
        "llm_results": ("llm_results_v6_1.parquet", "llm_results.parquet"),
        "deterministic": ("deterministic_323k_v6_1.parquet", "deterministic_323k.parquet"),
        "sha_dup_alias": ("sha_dup_alias_v6_1.parquet", "sha_dup_alias.parquet"),
    }
    found: dict[str, Path] = {}
    for key, names in candidates.items():
        for name in names:
            p = base / name
            if p.is_file():
                found[key] = p
                break

    # Optional sibling `p12_newlines_and_hygiene_323k.parquet` for full-323K p1..p2 text hydration
    for rel in (
        base / "p12_newlines_and_hygiene_323k.parquet",
        base.parent / "parquets" / "p12_newlines_and_hygiene_323k.parquet",
    ):
        if rel.is_file():
            found["p12_hygiene"] = rel
            break

    return found


def _sql_quote_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _parquet_cols(path: Path) -> set[str]:
    return set(pq.read_schema(path).names)


def _to_str_tuple(val: Any) -> tuple[str, ...]:
    if not val:
        return ()
    return tuple(str(x) for x in val if x is not None and str(x) != "")


def _default_doc_key(link_key_hex: str) -> str:
    if len(link_key_hex) == 16:
        try:
            return sha256(bytes.fromhex(link_key_hex)).hexdigest()
        except ValueError:
            pass
    return link_key_hex


def iter_corpus_rows(
    tables_dir: str | Path,
    *,
    docmeta_dir: str | Path | None = None,
    text_parquet: str | Path | None = None,
    limit: int | None = None,
    include_text: bool = True,
    batch_size: int = 8192,
) -> Iterator[CorpusDocRow]:
    """Stream canonical `CorpusDocRow` records joining published release tables & optional `docmeta_v6_1`."""
    tdir = Path(tables_dir)
    detail_path = tdir / "detail.parquet"
    list_path = tdir / "list.parquet"
    sources_path = tdir / "sources.parquet"

    if not detail_path.is_file():
        raise FileNotFoundError(f"Missing detail.parquet in {tdir}")

    d_cols = _parquet_cols(detail_path)
    has_list = list_path.is_file()
    l_cols = _parquet_cols(list_path) if has_list else set()

    def _dl_expr(col: str, cast_type: str, default_sql: str = "NULL") -> str:
        if col in d_cols:
            return f"CAST(d.{col} AS {cast_type})"
        if has_list and col in l_cols:
            return f"CAST(l.{col} AS {cast_type})"
        return f"CAST({default_sql} AS {cast_type})"

    def _dl_raw_expr(col: str, default_sql: str = "NULL") -> str:
        if col in d_cols:
            return f"d.{col}"
        if has_list and col in l_cols:
            return f"l.{col}"
        return default_sql

    mc_outcome_expr = "d.main_content.outcome" if "main_content" in d_cols else "CAST(NULL AS VARCHAR)"
    mc_reading_expr = "d.main_content.reading_status" if "main_content" in d_cols else "CAST(NULL AS VARCHAR)"
    mc_snippet_expr = "d.main_content.snippet" if "main_content" in d_cols else "CAST(NULL AS VARCHAR)"
    sel_text_expr = "d.selected_text" if "selected_text" in d_cols else "CAST(NULL AS VARCHAR)"
    doc_key_d_expr = "CAST(d.doc_key AS VARCHAR)" if "doc_key" in d_cols else "CAST(NULL AS VARCHAR)"

    ctes: list[str] = [
        f"""d_raw AS (
            SELECT row_number() OVER () - 1 AS list_row, *
            FROM read_parquet('{_sql_quote_path(detail_path)}')
        )"""
    ]
    list_join_sql = ""
    if has_list:
        ctes.append(
            f"""l_raw AS (
                SELECT row_number() OVER () - 1 AS list_row, *
                FROM read_parquet('{_sql_quote_path(list_path)}')
            )"""
        )
        list_join_sql = "LEFT JOIN l_raw l ON d.list_row = l.list_row"

    src_join_sql = ""
    src_select_sql = (
        "CAST(NULL AS VARCHAR) AS src_url, "
        "CAST(NULL AS VARCHAR) AS src_listed_on, "
        "CAST(NULL AS VARCHAR) AS src_member_path, "
        "CAST(NULL AS VARCHAR[]) AS src_link_texts"
    )
    if sources_path.is_file():
        s_cols = _parquet_cols(sources_path)
        ord_col = "ordinal" if "ordinal" in s_cols else "1"
        url_col = "url" if "url" in s_cols else "CAST(NULL AS VARCHAR)"
        lo_col = "listed_on" if "listed_on" in s_cols else "CAST(NULL AS VARCHAR)"
        mp_col = "member_path" if "member_path" in s_cols else "CAST(NULL AS VARCHAR)"
        lt_col = "link_text" if "link_text" in s_cols else "CAST(NULL AS VARCHAR)"
        ctes.append(
            f"""s_agg AS (
                SELECT list_row,
                       first({url_col} ORDER BY {ord_col}) FILTER (WHERE {url_col} IS NOT NULL AND {url_col} <> '') AS src_url,
                       first({lo_col} ORDER BY {ord_col}) FILTER (WHERE {lo_col} IS NOT NULL AND {lo_col} <> '') AS src_listed_on,
                       first({mp_col} ORDER BY {ord_col}) FILTER (WHERE {mp_col} IS NOT NULL AND {mp_col} <> '') AS src_member_path,
                       list({lt_col} ORDER BY {ord_col}) FILTER (WHERE {lt_col} IS NOT NULL AND trim({lt_col}) <> '') AS src_link_texts
                FROM read_parquet('{_sql_quote_path(sources_path)}')
                GROUP BY list_row
            )"""
        )
        src_join_sql = "LEFT JOIN s_agg s ON d.list_row = s.list_row"
        src_select_sql = "s.src_url, s.src_listed_on, s.src_member_path, s.src_link_texts"

    # Optional `docmeta_v6_1` sidecars keyed by `link_key_hex` (`lower(hex(link_key))`)
    dm_paths = resolve_docmeta_paths(docmeta_dir) if docmeta_dir is not None else {}
    dm_joins: list[str] = []

    comp_exprs = {
        "doc_key": "CAST(NULL AS VARCHAR)",
        "eff_sha": "CAST(NULL AS VARCHAR)",
        "disposition": "CAST(NULL AS VARCHAR)",
        "sub_disposition": "CAST(NULL AS VARCHAR)",
        "v6_route": "CAST(NULL AS VARCHAR)",
        "zero_llm_source": "CAST(NULL AS VARCHAR)",
        "primary_kind": "CAST(NULL AS VARCHAR)",
        "grammar_lock_source": "CAST(NULL AS VARCHAR)",
        "status": "CAST(NULL AS VARCHAR)",
        "congress": "CAST(NULL AS BIGINT)",
        "chamber": "CAST(NULL AS VARCHAR)",
        "committees": "CAST(NULL AS VARCHAR[])",
        "docmeta_json": "CAST(NULL AS VARCHAR)",
        "strict_v4_valid": "CAST(NULL AS BOOLEAN)",
        "is_alias": "false",
        "dm_text": "CAST(NULL AS VARCHAR)",
        "dm_text_source": "CAST(NULL AS VARCHAR)",
    }

    direct_parts: list[str] = []
    for part_key in ("completed_no_llm", "llm_results"):
        if part_key in dm_paths:
            p = dm_paths[part_key]
            pcols = _parquet_cols(p)
            lk_expr = "lower(hex(link_key))" if "link_key" in pcols else "CAST(link_key_hex AS VARCHAR)"
            dk_expr = "CAST(doc_key AS VARCHAR)" if "doc_key" in pcols else "CAST(NULL AS VARCHAR)"
            es_expr = (
                "CAST(effective_body_sha_hex AS VARCHAR)"
                if "effective_body_sha_hex" in pcols
                else ("lower(hex(saved_body))" if "saved_body" in pcols else "CAST(NULL AS VARCHAR)")
            )
            src_col = (
                "CAST(zero_llm_source AS VARCHAR)"
                if "zero_llm_source" in pcols
                else ("CAST(docmeta_source AS VARCHAR)" if "docmeta_source" in pcols else "CAST(NULL AS VARCHAR)")
            )
            direct_parts.append(
                f"""SELECT {lk_expr} AS lk_hex,
                           {dk_expr} AS dm_doc_key,
                           {es_expr} AS dm_eff_sha,
                           CAST(disposition AS VARCHAR) AS dm_disposition,
                           CAST(v6_route AS VARCHAR) AS dm_v6_route,
                           {src_col} AS dm_zero_llm_source,
                           CAST(primary_kind AS VARCHAR) AS dm_primary_kind,
                           CAST(status AS VARCHAR) AS dm_status,
                           CAST(congress AS BIGINT) AS dm_congress,
                           CAST(chamber AS VARCHAR) AS dm_chamber,
                           CAST(committees AS VARCHAR[]) AS dm_committees,
                           CAST(docmeta_json AS VARCHAR) AS dm_json,
                           CAST(strict_v4_valid AS BOOLEAN) AS dm_strict_valid
                    FROM read_parquet('{_sql_quote_path(p)}')"""
            )
    if direct_parts:
        ctes.append(f"dm_direct AS ({' UNION ALL '.join(direct_parts)})")
        dm_joins.append("LEFT JOIN dm_direct dmd ON lower(hex(d.link_key)) = dmd.lk_hex")

    has_queue = "llm_queue" in dm_paths
    if has_queue:
        qp = dm_paths["llm_queue"]
        qcols = _parquet_cols(qp)
        qlk = "lower(hex(link_key))" if "link_key" in qcols else "CAST(link_key_hex AS VARCHAR)"
        qdk = "CAST(doc_key AS VARCHAR)" if "doc_key" in qcols else "CAST(NULL AS VARCHAR)"
        qes = "CAST(effective_body_sha_hex AS VARCHAR)" if "effective_body_sha_hex" in qcols else "CAST(NULL AS VARCHAR)"
        qtxt = (
            "COALESCE(NULLIF(p12_clean_text, ''), p12_raw_text)"
            if ("p12_clean_text" in qcols and "p12_raw_text" in qcols)
            else ("p12_clean_text" if "p12_clean_text" in qcols else "CAST(NULL AS VARCHAR)")
        )
        qtsrc = "CAST(text_source AS VARCHAR)" if "text_source" in qcols else "CAST(NULL AS VARCHAR)"
        qlock = "CAST(locked_primary_kind AS VARCHAR)" if "locked_primary_kind" in qcols else "CAST(NULL AS VARCHAR)"
        qglock = "CAST(grammar_lock_source AS VARCHAR)" if "grammar_lock_source" in qcols else "CAST(NULL AS VARCHAR)"
        ctes.append(
            f"""dm_queue AS (
                SELECT {qlk} AS lk_hex,
                       {qdk} AS q_doc_key,
                       {qes} AS q_eff_sha,
                       CAST(disposition AS VARCHAR) AS q_disposition,
                       CAST(v6_route AS VARCHAR) AS q_v6_route,
                       {qlock} AS q_locked_kind,
                       {qglock} AS q_grammar_lock_source,
                       {qtxt if include_text else 'CAST(NULL AS VARCHAR)'} AS q_text,
                       {qtsrc} AS q_text_source
                FROM read_parquet('{_sql_quote_path(qp)}')
            )"""
        )
        dm_joins.append("LEFT JOIN dm_queue dmq ON lower(hex(d.link_key)) = dmq.lk_hex")

    has_alias = "sha_dup_alias" in dm_paths
    if has_alias:
        ap = dm_paths["sha_dup_alias"]
        acols = _parquet_cols(ap)
        alk = "lower(hex(link_key))" if "link_key" in acols else "CAST(link_key_hex AS VARCHAR)"
        clk = (
            "lower(hex(canonical_link_key))"
            if "canonical_link_key" in acols
            else "CAST(canonical_link_key_hex AS VARCHAR)"
        )
        adk = "CAST(doc_key AS VARCHAR)" if "doc_key" in acols else "CAST(NULL AS VARCHAR)"
        aes = "CAST(effective_body_sha_hex AS VARCHAR)" if "effective_body_sha_hex" in acols else "CAST(NULL AS VARCHAR)"
        asub = "CAST(sub_disposition AS VARCHAR)" if "sub_disposition" in acols else "CAST(NULL AS VARCHAR)"
        ctes.append(
            f"""dm_alias AS (
                SELECT {alk} AS lk_hex,
                       {clk} AS canon_lk_hex,
                       {adk} AS a_doc_key,
                       {aes} AS a_eff_sha,
                       CAST(disposition AS VARCHAR) AS a_disposition,
                       {asub} AS a_sub_disposition,
                       CAST(v6_route AS VARCHAR) AS a_v6_route
                FROM read_parquet('{_sql_quote_path(ap)}')
            )"""
        )
        dm_joins.append("LEFT JOIN dm_alias dma ON lower(hex(d.link_key)) = dma.lk_hex")
        if direct_parts:
            dm_joins.append("LEFT JOIN dm_direct dmc ON dma.canon_lk_hex = dmc.lk_hex")

    has_det = "deterministic" in dm_paths
    if has_det:
        dp = dm_paths["deterministic"]
        dtcols = _parquet_cols(dp)
        dtlk = "lower(hex(link_key))" if "link_key" in dtcols else "CAST(link_key_hex AS VARCHAR)"
        dtdk = "CAST(doc_key AS VARCHAR)" if "doc_key" in dtcols else "CAST(NULL AS VARCHAR)"
        dtes = "CAST(effective_body_sha_hex AS VARCHAR)" if "effective_body_sha_hex" in dtcols else "CAST(NULL AS VARCHAR)"
        dtsub = "CAST(sub_disposition AS VARCHAR)" if "sub_disposition" in dtcols else "CAST(NULL AS VARCHAR)"
        dtlock = "CAST(v6_locked_primary_kind AS VARCHAR)" if "v6_locked_primary_kind" in dtcols else "CAST(NULL AS VARCHAR)"
        dtglock = "CAST(v6_grammar_lock_source AS VARCHAR)" if "v6_grammar_lock_source" in dtcols else "CAST(NULL AS VARCHAR)"
        dttsrc = "CAST(text_source AS VARCHAR)" if "text_source" in dtcols else "CAST(NULL AS VARCHAR)"
        ctes.append(
            f"""dm_det AS (
                SELECT {dtlk} AS lk_hex,
                       {dtdk} AS dt_doc_key,
                       {dtes} AS dt_eff_sha,
                       CAST(disposition AS VARCHAR) AS dt_disposition,
                       {dtsub} AS dt_sub_disposition,
                       CAST(v6_route AS VARCHAR) AS dt_v6_route,
                       {dtlock} AS dt_locked_kind,
                       {dtglock} AS dt_grammar_lock_source,
                       {dttsrc} AS dt_text_source
                FROM read_parquet('{_sql_quote_path(dp)}')
            )"""
        )
        dm_joins.append("LEFT JOIN dm_det dmdt ON lower(hex(d.link_key)) = dmdt.lk_hex")

    # Optional external or sibling `p12` / `body_text` Parquet
    ext_txt_expr = "CAST(NULL AS VARCHAR)"
    if include_text:
        tp_path: Path | None = Path(text_parquet) if text_parquet is not None else dm_paths.get("p12_hygiene")
        if tp_path is not None and tp_path.is_file():
            tcols = _parquet_cols(tp_path)
            t_val = next(
                (c for c in ("p12_clean_text", "p12_text", "p12_lines", "text") if c in tcols),
                None,
            )
            if t_val is not None:
                if "link_key" in tcols:
                    ctes.append(
                        f"""txt_ext AS (
                            SELECT lower(hex(link_key)) AS lk_hex, CAST({t_val} AS VARCHAR) AS ext_text
                            FROM read_parquet('{_sql_quote_path(tp_path)}')
                        )"""
                    )
                    dm_joins.append("LEFT JOIN txt_ext tx ON lower(hex(d.link_key)) = tx.lk_hex")
                    ext_txt_expr = "tx.ext_text"
                elif "list_row" in tcols:
                    ctes.append(
                        f"""txt_ext AS (
                            SELECT CAST(list_row AS BIGINT) AS list_row, CAST({t_val} AS VARCHAR) AS ext_text
                            FROM read_parquet('{_sql_quote_path(tp_path)}')
                        )"""
                    )
                    dm_joins.append("LEFT JOIN txt_ext tx ON d.list_row = tx.list_row")
                    ext_txt_expr = "tx.ext_text"
                elif "saved_body" in tcols:
                    ctes.append(
                        f"""txt_ext AS (
                            SELECT saved_body, CAST({t_val} AS VARCHAR) AS ext_text
                            FROM read_parquet('{_sql_quote_path(tp_path)}')
                        )"""
                    )
                    dm_joins.append("LEFT JOIN txt_ext tx ON d.saved_body = tx.saved_body")
                    ext_txt_expr = "tx.ext_text"

    # Assemble coalesced docmeta expressions cleanly based on whichever tables exist
    dk_parts = [doc_key_d_expr]
    es_parts: list[str] = []
    disp_parts: list[str] = []
    sub_parts: list[str] = []
    route_parts: list[str] = []
    pk_parts: list[str] = []
    glock_parts: list[str] = []
    tsrc_parts: list[str] = []

    if direct_parts:
        dk_parts.insert(0, "dmd.dm_doc_key")
        es_parts.append("dmd.dm_eff_sha")
        disp_parts.append("dmd.dm_disposition")
        route_parts.append("dmd.dm_v6_route")
        pk_parts.append("dmd.dm_primary_kind")
        comp_exprs["zero_llm_source"] = (
            "COALESCE(dmd.dm_zero_llm_source, dmc.dm_zero_llm_source)"
            if has_alias
            else "dmd.dm_zero_llm_source"
        )
        comp_exprs["status"] = "COALESCE(dmd.dm_status, dmc.dm_status)" if has_alias else "dmd.dm_status"
        comp_exprs["congress"] = "COALESCE(dmd.dm_congress, dmc.dm_congress)" if has_alias else "dmd.dm_congress"
        comp_exprs["chamber"] = "COALESCE(dmd.dm_chamber, dmc.dm_chamber)" if has_alias else "dmd.dm_chamber"
        comp_exprs["committees"] = (
            "COALESCE(dmd.dm_committees, dmc.dm_committees)" if has_alias else "dmd.dm_committees"
        )
        comp_exprs["docmeta_json"] = "COALESCE(dmd.dm_json, dmc.dm_json)" if has_alias else "dmd.dm_json"
        comp_exprs["strict_v4_valid"] = (
            "COALESCE(dmd.dm_strict_valid, dmc.dm_strict_valid)" if has_alias else "dmd.dm_strict_valid"
        )
        if has_alias:
            pk_parts.append("dmc.dm_primary_kind")
    if has_queue:
        dk_parts.append("dmq.q_doc_key")
        es_parts.append("dmq.q_eff_sha")
        disp_parts.append("dmq.q_disposition")
        route_parts.append("dmq.q_v6_route")
        pk_parts.append("dmq.q_locked_kind")
        glock_parts.append("dmq.q_grammar_lock_source")
        tsrc_parts.append("dmq.q_text_source")
    if has_alias:
        dk_parts.append("dma.a_doc_key")
        es_parts.append("dma.a_eff_sha")
        disp_parts.append("dma.a_disposition")
        sub_parts.append("dma.a_sub_disposition")
        route_parts.append("dma.a_v6_route")
        comp_exprs["is_alias"] = "COALESCE(dma.lk_hex IS NOT NULL, false)"
    if has_det:
        dk_parts.append("dmdt.dt_doc_key")
        es_parts.append("dmdt.dt_eff_sha")
        disp_parts.append("dmdt.dt_disposition")
        sub_parts.append("dmdt.dt_sub_disposition")
        route_parts.append("dmdt.dt_v6_route")
        pk_parts.append("dmdt.dt_locked_kind")
        glock_parts.append("dmdt.dt_grammar_lock_source")
        tsrc_parts.append("dmdt.dt_text_source")

    def _coal(exprs: list[str], cast_type: str) -> str:
        return f"COALESCE({', '.join(exprs)})" if exprs else f"CAST(NULL AS {cast_type})"

    comp_exprs["doc_key"] = _coal(dk_parts, "VARCHAR")
    comp_exprs["eff_sha"] = _coal(es_parts, "VARCHAR")
    comp_exprs["disposition"] = _coal(disp_parts, "VARCHAR")
    comp_exprs["sub_disposition"] = _coal(sub_parts, "VARCHAR")
    comp_exprs["v6_route"] = _coal(route_parts, "VARCHAR")
    comp_exprs["primary_kind"] = _coal(pk_parts, "VARCHAR")
    comp_exprs["grammar_lock_source"] = _coal(glock_parts, "VARCHAR")
    comp_exprs["dm_text_source"] = _coal(tsrc_parts, "VARCHAR")

    if include_text:
        txt_candidates = [ext_txt_expr]
        if has_queue:
            txt_candidates.append("dmq.q_text")
        txt_candidates.extend([f"NULLIF({sel_text_expr}, '')", f"NULLIF({mc_snippet_expr}, '')"])
        text_sql = f"COALESCE({', '.join(txt_candidates)}, '')"
    else:
        text_sql = "''"

    limit_sql = f"LIMIT {int(limit)}" if limit is not None else ""
    sql = f"""
        WITH {', '.join(ctes)}
        SELECT
            d.list_row,
            lower(hex(d.link_key)) AS link_key_hex,
            {comp_exprs['doc_key']} AS doc_key,
            CASE WHEN d.saved_body IS NOT NULL THEN lower(hex(d.saved_body)) ELSE '' END AS saved_body_hex,
            {comp_exprs['eff_sha']} AS eff_sha_hex,
            {_dl_expr('package_id', 'VARCHAR')} AS package_id,
            COALESCE({_dl_expr('filename', 'VARCHAR')}, '') AS filename,
            {_dl_expr('title', 'VARCHAR')} AS title,
            {_dl_expr('format', 'VARCHAR')} AS format,
            {_dl_expr('saved_suffix', 'VARCHAR')} AS saved_suffix,
            {src_select_sql},
            {_dl_raw_expr('document_kind')} AS document_kind,
            {_dl_raw_expr('document_family')} AS document_family,
            {_dl_expr('congress', 'BIGINT')} AS congress,
            {_dl_raw_expr('committee_keys')} AS committee_keys,
            {_dl_raw_expr('chambers')} AS chambers,
            {_dl_expr('document_date', 'VARCHAR')} AS document_date,
            {_dl_expr('date_kind', 'VARCHAR')} AS date_kind,
            {_dl_expr('document_date_status', 'VARCHAR')} AS document_date_status,
            {_dl_expr('document_date_source', 'VARCHAR')} AS document_date_source,
            {_dl_raw_expr('meeting_keys')} AS meeting_keys,
            {_dl_raw_expr('measure_keys')} AS measure_keys,
            {_dl_raw_expr('bioguide_ids')} AS bioguide_ids,
            {_dl_raw_expr('witness_keys')} AS witness_keys,
            {mc_outcome_expr} AS main_content_outcome,
            {mc_reading_expr} AS reading_status,
            {text_sql} AS p12_text,
            {comp_exprs['dm_text_source']} AS text_source,
            {comp_exprs['disposition']} AS disposition,
            {comp_exprs['sub_disposition']} AS sub_disposition,
            {comp_exprs['v6_route']} AS v6_route,
            {comp_exprs['zero_llm_source']} AS zero_llm_source,
            {comp_exprs['primary_kind']} AS docmeta_primary_kind,
            {comp_exprs['grammar_lock_source']} AS grammar_lock_source,
            {comp_exprs['status']} AS docmeta_status,
            {comp_exprs['congress']} AS docmeta_congress,
            {comp_exprs['chamber']} AS docmeta_chamber,
            {comp_exprs['committees']} AS docmeta_committees,
            {comp_exprs['docmeta_json']} AS docmeta_json,
            {comp_exprs['strict_v4_valid']} AS strict_v4_valid,
            {comp_exprs['is_alias']} AS is_alias
        FROM d_raw d
        {list_join_sql}
        {src_join_sql}
        {' '.join(dm_joins)}
        ORDER BY d.list_row
        {limit_sql}
    """

    con = duckdb.connect()
    try:
        cur = con.execute(sql)
        while True:
            batch = cur.fetchmany(batch_size)
            if not batch:
                break
            for r in batch:
                lk_hex = r[1] or ""
                sb_hex = r[3] or ""
                raw_url = r[10]
                raw_lo = r[11]
                unwrapped_url = unwrap_archive_url(raw_url)[0] if raw_url else None
                host = extract_url_host(raw_url) or extract_url_host(raw_lo)
                fmt = r[8]
                sfx = (r[9] or "").lstrip(".").lower() or None
                yield CorpusDocRow(
                    list_row=int(r[0]),
                    link_key_hex=lk_hex,
                    doc_key=r[2] or _default_doc_key(lk_hex),
                    saved_body_hex=sb_hex,
                    effective_body_sha_hex=r[4] or sb_hex,
                    package_id=r[5],
                    filename=r[6] or "",
                    title=r[7],
                    format=fmt,
                    effective_format=sfx or fmt,
                    source_url=unwrapped_url or raw_url,
                    listed_on=raw_lo,
                    member_path=r[12],
                    link_texts=_to_str_tuple(r[13]),
                    host=host,
                    document_kind=_to_str_tuple(r[14]),
                    document_family=_to_str_tuple(r[15]),
                    congress=int(r[16]) if r[16] is not None else None,
                    committee_keys=_to_str_tuple(r[17]),
                    chambers=_to_str_tuple(r[18]),
                    document_date=r[19],
                    date_kind=r[20],
                    document_date_status=r[21],
                    document_date_source=r[22],
                    meeting_keys=_to_str_tuple(r[23]),
                    measure_keys=_to_str_tuple(r[24]),
                    bioguide_ids=_to_str_tuple(r[25]),
                    witness_keys=_to_str_tuple(r[26]),
                    main_content_outcome=r[27],
                    reading_status=r[28],
                    p12_text=r[29] or "",
                    text_source=r[30],
                    disposition=r[31],
                    sub_disposition=r[32],
                    v6_route=r[33],
                    zero_llm_source=r[34],
                    docmeta_primary_kind=r[35],
                    grammar_lock_source=r[36],
                    docmeta_status=r[37],
                    docmeta_congress=int(r[38]) if r[38] is not None else None,
                    docmeta_chamber=r[39],
                    docmeta_committees=_to_str_tuple(r[40]),
                    docmeta_json=r[41],
                    strict_v4_valid=bool(r[42]) if r[42] is not None else None,
                    is_alias=bool(r[43]),
                )
    finally:
        con.close()


def load_corpus_rows(
    tables_dir: str | Path,
    *,
    docmeta_dir: str | Path | None = None,
    text_parquet: str | Path | None = None,
    limit: int | None = None,
    include_text: bool = True,
) -> list[CorpusDocRow]:
    """Load canonical `CorpusDocRow` list from published release tables + optional `docmeta_v6_1`."""
    return list(
        iter_corpus_rows(
            tables_dir,
            docmeta_dir=docmeta_dir,
            text_parquet=text_parquet,
            limit=limit,
            include_text=include_text,
        )
    )
