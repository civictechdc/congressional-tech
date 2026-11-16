"""Unmapped-Tail & Emergent-Template Radar (`corpus_quality.tail_clusters`).

Repurposes header-template clustering into a deterministic, zero-heavy-ML-dependency
product radar that runs across published release tables (`detail.parquet` / `list.parquet` /
`sources.parquet`) and optional `docmeta_v6_1` sidecars:

1. **Target Tail Population Selection (`select_tail_population`):**
   - Selects unmapped/generic rows (`document_kind` empty, `'other'`, `'committee-document'`,
     or `'committee-document-numbered'` without a `docmeta` kind lock),
   - Clerk ambiguous upload-slot rows (`-Bio-`, `-Wstate-`, `-SD`, or `house_naming`
     `AMBIGUOUS_SLOT_KINDS`) lacking a deterministic cover/grammar lock,
   - Error/wrapper/unreadable candidates (`reading_status` / `docmeta_status` non-usable or
     matching `model/registries/page-signals.json` error/challenge/wrapper markers),
   - Open-extraction tail rows (`llm_open_extraction`, `llm_open_kind`,
     `deterministic_enriched_open_kind`), and
   - `docmeta` validation anomalies (`strict_v4_valid is False` or usable rows missing
     `docmeta_primary_kind`).

2. **Fast Deterministic Structural Clustering (`discover_tail_clusters`):**
   - Represents each tail document with `core.structural_shingles`, layout-shape profile
     (all-caps header density, Q&A markers, checkbox form markers, table/tally grids,
     correspondence salutations, short/empty stub status), `core.url_path_template`,
     Clerk slot markers, and host/extension tokens.
   - Deduplicates exact shingle micro-templates (`O(N)`), builds a deterministic
     densified One-Permutation MinHash sketch (`O(N * |S|)`), generates candidate pairs via
     multi-band LSH (plus exact inverted-index lookup on small canopies), and assigns
     members via weight-ordered leader-medoid exact Jaccard verification (`>= jaccard_threshold`)
     so hub-chaining cannot merge unrelated document genres.

3. **Actionable Product Output & Release-Gate Findings:**
   - Computes `--base` -> `--candidate` cluster growth deltas and flags newly spiked clusters,
   - Labels each cluster's top discriminative header phrases DRY via
     `tfidf_drift.compute_log_odds_signatures`,
   - Audits whether existing `congress_api.parsers.document_cover` or `page-signals.json`
     rules already match cluster members or whether a new `cover:*` / `page-signals:*` rule
     candidate is warranted, and
   - Exposes `row_to_cluster` and `member_link_keys` directly for
     `stratified_sampler.build_stratified_audit_packet`.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import functools
from hashlib import blake2b, sha256
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Literal

from congress_api.parsers.document_cover import document_page_fields
from house_naming import is_slot_kind_ambiguous

from .core import (
    DEFAULT_STOPWORDS,
    CorpusDocRow,
    QualityFinding,
    extract_header_footer_windows,
    extract_url_host,
    structural_shingles,
    url_path_template,
)

if TYPE_CHECKING:
    from .tfidf_drift import PhraseSignature

REPO_ROOT = Path(__file__).resolve().parents[5]
PAGE_SIGNALS_PATH = REPO_ROOT / "model" / "registries" / "page-signals.json"

TailPopulationReason = Literal[
    "unmapped_document_kind",
    "ambiguous_upload_slot",
    "error_response_candidate",
    "open_extraction_tail",
    "docmeta_anomaly",
]

RuleRecommendationKind = Literal[
    "existing_cover_rule_matches",
    "existing_page_signal_matches",
    "new_cover_rule_candidate",
    "new_error_or_wrapper_signal_candidate",
    "untemplated_prose_or_manual_review",
]

_UNMAPPED_KINDS: frozenset[str] = frozenset(
    {
        "",
        "other",
        "unknown",
        "unmapped",
        "committee-document",
        "committee-document-numbered",
    }
)
_NON_USABLE_STATUSES: frozenset[str] = frozenset(
    {
        "error_or_block",
        "ocr_unreadable",
        "stub_or_blank",
        "index_or_listing",
        "govinfo_wrapper",
        "error",
        "blocked",
        "unreadable",
        "empty",
    }
)
_OPEN_EXTRACTION_ROUTES: frozenset[str] = frozenset(
    {
        "llm_open_extraction",
        "llm_open_kind",
        "deterministic_enriched_open_kind",
    }
)
_ERROR_OUTCOMES: frozenset[str] = frozenset(
    {"error", "empty", "challenge", "wrapper", "refused", "blocked"}
)

_CLERK_SLOT_RE = re.compile(
    r"(?:^|[-_.])(Bio|Wstate|SD(?:\d{2,4})?)(?=[-_.0-9A-Za-z]|$)",
    re.I,
)
_QA_LINE_RE = re.compile(
    r"(?:^\s*(?:Q\.|A\.|QUESTION\s*\d*\s*[:.]|ANSWER\s*\d*\s*[:.]|RESPONSE\s*\d*\s*:)|"
    r"\bQUESTIONS?\s+FOR\s+THE\s+(?:HEARING\s+)?RECORD\b)",
    re.I | re.M,
)
_CHECKBOX_FORM_RE = re.compile(
    r"(?:[☐☑☒]|\[\s*[xX✓✔ ]?\s*\]|\bYES\s*\[\s*|\bTRUTH\s+IN\s+TESTIMONY\b|"
    r"\bWITNESS\s+DISCLOSURE\b|\bNONGOVERNMENTAL\s+ENTIT(?:Y|IES)\b)",
    re.I,
)
_TABLE_TALLY_RE = re.compile(
    r"(?:\b(?:YEAS?|AYES?)\b.{0,40}\b(?:NAYS?|NOES?)\b|"
    r"\bROLL\s+CALL\s+(?:VOTE|NO\.)\b|"
    r"(?:^[^\n]*\|[^\n]*\|[^\n]*$))",
    re.I | re.M,
)
_SALUTATION_LETTER_RE = re.compile(
    r"(?:\bDear\s+(?:Chair(?:man|woman)?|Ranking\s+Member|Senator|Representative|"
    r"Mr\.|Ms\.|Mrs\.|Madam|Dr\.|Secretary|Director|Administrator|Honorable)\b|"
    r"\bSincerely\s*,|\bRespectfully\s+submitted\b)",
    re.I,
)
_CMS_CHROME_RE = re.compile(
    r"(?:^\s*(?:Skip\s+to\s+(?:main\s+|primary\s+)?(?:content|navigation)|"
    r"Toggle\s+navigation|Stay\s+Up\s+To\s+Date\b|Report\s+Waste,\s*Fraud,\s*and\s+Abuse\b|"
    r"Media\s+Center\s+Press\s+Releases\b|Internships\s+News\s+Listening\b))",
    re.I | re.M,
)
_SLUG_SANITIZE_RE = re.compile(r"[^a-z0-9]+")

# Emergent rule candidate structural probes (for tail clusters NOT yet matched by document_cover / page-signals)
_EMERGENT_COVER_PROBES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "cover:hearing-notice",
        re.compile(
            r"\b(?:NOTICE\s+OF\s+(?:REVISED\s+|FULL\s+COMMITTEE\s+|SUBCOMMITTEE\s+|OVERSIGHT\s+|LEGISLATIVE\s+)*HEARING|"
            r"(?:FULL\s+COMMITTEE\s+|SUBCOMMITTEE\s+|REVISED\s+)?HEARING\s+NOTICE|"
            r"ADVISORY\b.{0,220}?\bANNOUNCES?\s+(?:A\s+|SUBCOMMITTEE\s+)?HEARING)\b",
            re.I | re.S,
        ),
    ),
    (
        "cover:committee-memorandum",
        re.compile(
            r"\b(?:MEMORANDUM|M\s+E\s+M\s+O\s+R\s+A\s+N\s+D\s+U\s+M|HEARING\s+CHARTER|"
            r"SUMMARY\s+OF\s+SUBJECT\s+MATTER)\b.{0,450}?\b(?:TO\s*:|MEMBERS\b|COMMITTEE\s+ON\b)",
            re.I | re.S,
        ),
    ),
    (
        "cover:press-release",
        re.compile(
            r"\b(?:FOR\s+IMMEDIATE\s+RELEASE|PRESS\s+RELEASE|NEWS\s+RELEASE)\b",
            re.I,
        ),
    ),
    (
        "cover:committee-vote",
        re.compile(
            r"\b(?:RECORD\s+OF\s+COMMITTEE\s+VOTE|FULL\s+COMMITTEE\s+VOTES|"
            r"ROLL\s+CALL\s+(?:VOTE|NO\.)|YEAS\s+AND\s+NAYS)\b",
            re.I,
        ),
    ),
    (
        "cover:questions-and-answers",
        re.compile(
            r"\b(?:QUESTIONS?\s+FOR\s+THE\s+(?:HEARING\s+)?RECORD|ANSWERS?\s+FOR\s+THE\s+RECORD|"
            r"ADVANCE\s+POLICY\s+QUESTIONS)\b",
            re.I,
        ),
    ),
    (
        "cover:committee-report",
        re.compile(
            r"\b(?:(?:HOUSE|SENATE|UNION|EXECUTIVE)\s+CALENDAR\s+NO\.|"
            r"SUBMITTED\s+THE\s+FOLLOWING\s+(?:CONFERENCE\s+)?(?:REPORT|R\s+E\s+P\s+O\s+R\s+T))\b",
            re.I,
        ),
    ),
    (
        "cover:committee-letter",
        re.compile(
            r"\b(?:CONGRESS\s+OF\s+THE\s+UNITED\s+STATES|UNITED\s+STATES\s+SENATE|"
            r"HOUSE\s+OF\s+REPRESENTATIVES)\b.{0,650}?\bDEAR\s+(?:MR\.|MS\.|MRS\.|DR\.|"
            r"SECRETARY|ADMINISTRATOR|DIRECTOR|COMMISSIONER|HONORABLE|CHAIR|SENATOR|REPRESENTATIVE)\b",
            re.I | re.S,
        ),
    ),
)

# Deterministic constants for densifying empty One-Permutation MinHash bins
_DENSIFY_SALTS: tuple[int, ...] = tuple(
    int.from_bytes(blake2b(f"opmh-salt-{i}".encode("ascii"), digest_size=8).digest(), "little")
    for i in range(64)
)
_EMPTY_BIN = (1 << 64) - 1


@dataclass(frozen=True, slots=True)
class _CompiledPageSignals:
    cover_rules: tuple[tuple[str, re.Pattern[str]], ...]
    error_body_rules: tuple[tuple[str, re.Pattern[str], bool], ...]
    wrapper_body_rules: tuple[tuple[str, re.Pattern[str]], ...]
    url_rules: tuple[tuple[str, str, re.Pattern[str]], ...]


@functools.cache
def _load_compiled_page_signals(registry_path: str = str(PAGE_SIGNALS_PATH)) -> _CompiledPageSignals:
    path = Path(registry_path)
    if not path.is_file():
        return _CompiledPageSignals((), (), (), ())
    entries = json.loads(path.read_text(encoding="utf-8"))
    cover_rules: list[tuple[str, re.Pattern[str]]] = []
    error_body_rules: list[tuple[str, re.Pattern[str], bool]] = []
    wrapper_body_rules: list[tuple[str, re.Pattern[str]]] = []
    url_rules: list[tuple[str, str, re.Pattern[str]]] = []

    for entry in entries:
        sig_id = str(entry.get("id") or "")
        kind = str(entry.get("kind") or "")
        pattern = entry.get("pattern")
        if not sig_id or not isinstance(pattern, str) or not pattern:
            continue
        rx = re.compile(pattern)
        if kind in {"cover_kind", "print_cover"}:
            cover_rules.append((sig_id, rx))
        elif kind in {"error_word", "body_marker"}:
            # `generic_error` includes bare `\berror\b`, so restrict it to short error/stub bodies
            short_only = sig_id == "generic_error"
            error_body_rules.append((sig_id, rx, short_only))
        elif kind == "wrapper_marker":
            wrapper_body_rules.append((sig_id, rx))
        elif kind in {"error_url", "wrapper_url", "landing_url", "feed_url", "api_endpoint"}:
            url_rules.append((sig_id, kind, rx))

    return _CompiledPageSignals(
        cover_rules=tuple(cover_rules),
        error_body_rules=tuple(error_body_rules),
        wrapper_body_rules=tuple(wrapper_body_rules),
        url_rules=tuple(url_rules),
    )


@dataclass(frozen=True, slots=True)
class LayoutShapeProfile:
    """Aggregated structural layout profile across documents in a tail cluster."""

    all_caps_header_ratio: float
    qa_marker_rate: float
    checkbox_form_rate: float
    table_pipe_or_grid_rate: float
    salutation_or_letter_rate: float
    short_or_stub_rate: float
    dominant_shape_bucket: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_caps_header_ratio": round(self.all_caps_header_ratio, 4),
            "qa_marker_rate": round(self.qa_marker_rate, 4),
            "checkbox_form_rate": round(self.checkbox_form_rate, 4),
            "table_pipe_or_grid_rate": round(self.table_pipe_or_grid_rate, 4),
            "salutation_or_letter_rate": round(self.salutation_or_letter_rate, 4),
            "short_or_stub_rate": round(self.short_or_stub_rate, 4),
            "dominant_shape_bucket": self.dominant_shape_bucket,
        }


@dataclass(frozen=True, slots=True)
class TailCluster:
    """Actionable product summary for a discovered unmapped/emergent document cluster."""

    cluster_id: str
    signature_bucket: str
    row_count: int
    baseline_count: int | None
    growth_delta: int | None
    growth_ratio: float | None
    is_emergent_spike: bool
    population_reasons: dict[str, int]
    dominant_hosts: tuple[tuple[str, int], ...]
    dominant_extensions: tuple[tuple[str, int], ...]
    dominant_url_templates: tuple[tuple[str, int], ...]
    exemplar_link_keys: tuple[str, ...]
    member_link_keys: tuple[str, ...]
    top_phrases: tuple[PhraseSignature, ...]
    layout_profile: LayoutShapeProfile
    partial_cover_matches: dict[str, int]
    recommendation_kind: RuleRecommendationKind
    suggested_rule_target: str | None
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "signature_bucket": self.signature_bucket,
            "row_count": self.row_count,
            "baseline_count": self.baseline_count,
            "growth_delta": self.growth_delta,
            "growth_ratio": round(self.growth_ratio, 4) if self.growth_ratio is not None else None,
            "is_emergent_spike": self.is_emergent_spike,
            "population_reasons": dict(self.population_reasons),
            "dominant_hosts": [[h, n] for h, n in self.dominant_hosts],
            "dominant_extensions": [[ext, n] for ext, n in self.dominant_extensions],
            "dominant_url_templates": [[tpl, n] for tpl, n in self.dominant_url_templates],
            "exemplar_link_keys": list(self.exemplar_link_keys),
            "member_link_keys": list(self.member_link_keys),
            "top_phrases": [p.to_dict() for p in self.top_phrases],
            "layout_profile": self.layout_profile.to_dict(),
            "partial_cover_matches": dict(self.partial_cover_matches),
            "recommendation_kind": self.recommendation_kind,
            "suggested_rule_target": self.suggested_rule_target,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class TailClusterReport:
    """Complete output of `discover_tail_clusters` for CLI reporting and stratified sampling."""

    total_input_rows: int
    target_tail_rows: int
    clustered_rows: int
    clusters: tuple[TailCluster, ...]
    row_to_cluster: dict[str, str]
    row_tail_reasons: dict[str, tuple[str, ...]]
    findings: tuple[QualityFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_input_rows": self.total_input_rows,
            "target_tail_rows": self.target_tail_rows,
            "clustered_rows": self.clustered_rows,
            "cluster_count": len(self.clusters),
            "emergent_spike_count": sum(1 for c in self.clusters if c.is_emergent_spike),
            "clusters": [c.to_dict() for c in self.clusters],
            "row_to_cluster": dict(self.row_to_cluster),
            "row_tail_reasons": {k: list(v) for k, v in self.row_tail_reasons.items()},
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass(frozen=True, slots=True)
class _DocShapeFlags:
    caps_ratio: float
    has_qa: bool
    has_checkbox: bool
    has_table: bool
    has_salutation: bool
    is_short_or_stub: bool
    shape_bucket: str


@dataclass(slots=True)
class _PreparedTailDoc:
    row: CorpusDocRow
    reasons: tuple[str, ...]
    host: str
    ext: str
    url_tpl: str
    slot_token: str
    shape: _DocShapeFlags
    canopy_key: str
    signature_bucket: str
    shingles: frozenset[str]
    header_text: str


def _extract_clerk_slot_token(filename: str) -> str:
    if not filename:
        return ""
    m = _CLERK_SLOT_RE.search(filename)
    if not m:
        return ""
    raw = m.group(1).lower()
    if raw.startswith("sd"):
        return "sd"
    return raw


def _detect_page_signal_errors(row: CorpusDocRow, signals: _CompiledPageSignals) -> list[str]:
    hits: list[str] = []
    url = row.source_url or row.listed_on or ""
    if url:
        url_low = url.lower()
        if any(tok in url_low for tok in ("404", "error", "notfound", "not-found")):
            for sig_id, kind, rx in signals.url_rules:
                if kind == "error_url" and rx.search(url):
                    hits.append(sig_id)
    text = row.p12_text or ""
    if text:
        head1200 = text[:1200]
        # Avoid stripping multi-kilobyte texts when checking `< 500` / `< 900` thresholds
        stripped_len = len(text[:1000].strip())
        for sig_id, rx, short_only in signals.error_body_rules:
            if short_only and stripped_len >= 500:
                continue
            if rx.search(head1200):
                hits.append(sig_id)
        if stripped_len < 900:
            for sig_id, rx in signals.wrapper_body_rules:
                if rx.search(head1200):
                    hits.append(sig_id)
    return hits


def select_tail_population(
    rows: Sequence[CorpusDocRow],
    *,
    include_aliases: bool = False,
) -> tuple[list[CorpusDocRow], dict[str, tuple[str, ...]]]:
    """Select unmapped, slot-ambiguous, error/wrapper, open-extraction, or anomalous rows."""
    signals = _load_compiled_page_signals()
    selected: list[CorpusDocRow] = []
    reasons_by_key: dict[str, tuple[str, ...]] = {}
    seen_keys: set[str] = set()

    for row in rows:
        if not include_aliases and row.is_alias:
            continue
        if not row.link_key_hex or row.link_key_hex in seen_keys:
            continue

        reasons: list[TailPopulationReason] = []
        r_status = (row.reading_status or "").strip().lower()
        d_status = (row.docmeta_status or "").strip().lower()
        v6_route = (row.v6_route or "").strip().lower()
        mc_outcome = (row.main_content_outcome or "").strip().lower()
        disp = (row.disposition or "").strip().lower()

        # 1. Error / refusal / wrapper / unreadable capture candidates
        if (
            r_status in _NON_USABLE_STATUSES
            or d_status in _NON_USABLE_STATUSES
            or v6_route == "deterministic_triage_non_usable"
            or mc_outcome in _ERROR_OUTCOMES
            or bool(_detect_page_signal_errors(row, signals))
        ):
            reasons.append("error_response_candidate")

        has_deterministic_lock = bool(
            (row.grammar_lock_source and row.grammar_lock_source.strip())
            or (row.zero_llm_source and row.zero_llm_source.strip())
            or (disp == "upstream_spicydocs" and row.docmeta_primary_kind)
            or v6_route in {"zero_llm_complete", "zero_llm_synthesized_docmeta", "tier1_or_cover_or_anchor_grammar_locked"}
        )

        pub_kind = (row.primary_published_kind or "").strip().lower()

        # 2. Unmapped or generic published document_kind without a deterministic docmeta lock
        if not has_deterministic_lock and not row.docmeta_primary_kind:
            if not row.document_kind or pub_kind in _UNMAPPED_KINDS:
                reasons.append("unmapped_document_kind")

        # 3. Ambiguous Clerk upload-slot rows (-Bio-, -Wstate-, -SD, witness-support, meeting-support) without a cover lock
        slot_tok = _extract_clerk_slot_token(row.filename)
        if not has_deterministic_lock and (
            bool(slot_tok) or is_slot_kind_ambiguous(pub_kind)
        ):
            reasons.append("ambiguous_upload_slot")

        # 4. Open-extraction LLM queue tail rows
        if v6_route in _OPEN_EXTRACTION_ROUTES and not has_deterministic_lock:
            reasons.append("open_extraction_tail")

        # 5. DocMeta validation / schema anomalies
        if row.strict_v4_valid is False or (
            d_status == "usable" and row.docmeta_json is not None and not row.docmeta_primary_kind
        ):
            reasons.append("docmeta_anomaly")

        if reasons:
            seen_keys.add(row.link_key_hex)
            selected.append(row)
            reasons_by_key[row.link_key_hex] = tuple(reasons)

    return selected, reasons_by_key


def _compute_doc_shape(row: CorpusDocRow, header_lines: tuple[str, ...], header_text: str) -> _DocShapeFlags:
    raw = row.p12_text or ""
    stripped = raw.strip()
    eff_fmt = (row.effective_format or row.format or row.file_ext or "").lower()

    if not stripped:
        return _DocShapeFlags(
            caps_ratio=0.0,
            has_qa=False,
            has_checkbox=False,
            has_table=False,
            has_salutation=False,
            is_short_or_stub=True,
            shape_bucket="empty_or_unreadable",
        )

    is_short = len(stripped) < 128
    alpha_Bearing = 0
    caps_lines = 0
    for ln in header_lines[:16]:
        alphas = [ch for ch in ln if ch.isalpha()]
        if len(alphas) >= 5:
            alpha_Bearing += 1
            if sum(1 for ch in alphas if ch.isupper()) / len(alphas) >= 0.80:
                caps_lines += 1
    caps_ratio = (caps_lines / alpha_Bearing) if alpha_Bearing > 0 else 0.0

    probe_text = raw[:2400]
    has_qa = bool(_QA_LINE_RE.search(probe_text))
    has_checkbox = bool(_CHECKBOX_FORM_RE.search(probe_text))
    has_table = bool(_TABLE_TALLY_RE.search(probe_text)) or sum(
        1 for ln in header_lines if ln.count("|") >= 2 or "\t" in ln
    ) >= 2
    has_salutation = bool(_SALUTATION_LETTER_RE.search(probe_text))
    has_cms_chrome = eff_fmt in {"html", "htm"} and bool(_CMS_CHROME_RE.search(header_text[:900]))

    if has_cms_chrome:
        bucket = "cms_html_chrome"
    elif is_short:
        bucket = "short_error_or_stub"
    elif has_checkbox:
        bucket = "checkbox_disclosure_form"
    elif has_table:
        bucket = "table_or_tally_grid"
    elif has_qa:
        bucket = "qa_or_qfr_packet"
    elif has_salutation:
        bucket = "formal_correspondence"
    elif caps_ratio >= 0.45:
        bucket = "caps_masthead_banner"
    else:
        bucket = "narrative_prose"

    return _DocShapeFlags(
        caps_ratio=caps_ratio,
        has_qa=has_qa,
        has_checkbox=has_checkbox,
        has_table=has_table,
        has_salutation=has_salutation,
        is_short_or_stub=is_short,
        shape_bucket=bucket,
    )


def _host_bucket(host: str) -> str:
    if not host:
        return "no_host"
    h = host.lower()
    if h == "docs.house.gov":
        return "docs.house.gov"
    if h.endswith(".house.gov") or h == "house.gov":
        return h
    if h.endswith(".senate.gov") or h == "senate.gov":
        return h
    if "govinfo.gov" in h or "gpo.gov" in h:
        return "govinfo.gov"
    if "congress.gov" in h:
        return "congress.gov"
    return h


def _url_dir_prefix(tpl: str) -> str:
    if not tpl:
        return ""
    parts = [p for p in tpl.split("/") if p]
    if len(parts) <= 2:
        return "/".join(parts)
    return "/".join(parts[:3])


def _prepare_tail_doc(row: CorpusDocRow, reasons: tuple[str, ...]) -> _PreparedTailDoc:
    win = extract_header_footer_windows(row.p12_text, max_header_lines=24, max_header_chars=1600)
    shape = _compute_doc_shape(row, win.header_lines, win.header)
    host = (row.host or extract_url_host(row.source_url or row.listed_on) or "").strip().lower()
    eff_fmt = (row.effective_format or row.format or "").strip().lower()
    fn_low = (row.filename or "").lower()
    if eff_fmt in {"html", "htm"} or fn_low.endswith((".html.gz", ".htm.gz")):
        ext = "html"
    elif fn_low.endswith(".pdf.gz"):
        ext = "pdf"
    else:
        ext = (row.file_ext or eff_fmt or "unknown").strip().lower() or "unknown"
    tpl = url_path_template(row.source_url or row.listed_on)
    slot_tok = _extract_clerk_slot_token(row.filename)

    base_shingles = set(structural_shingles((row.p12_text or "")[:2400], shingle_size=3, max_lines=32))
    if len(base_shingles) > 1:
        base_shingles.discard("shape:unstructured")

    base_shingles.add(f"ext:{ext}")
    base_shingles.add(f"layout:{shape.shape_bucket}")
    if slot_tok:
        base_shingles.add(f"slot:{slot_tok}")
    if host:
        base_shingles.add(f"host:{_host_bucket(host)}")
    if tpl:
        base_shingles.add(f"url_tpl:{tpl}")
        url_dir = _url_dir_prefix(tpl)
        if url_dir:
            base_shingles.add(f"url_dir:{url_dir}")

    if shape.shape_bucket in {"empty_or_unreadable", "short_error_or_stub"}:
        status_tok = (row.docmeta_status or row.reading_status or "empty").strip().lower()
        disp_tok = (row.disposition or "none").strip().lower()
        zsrc_tok = (row.zero_llm_source or "none").strip().lower()
        base_shingles.add(f"status:{status_tok}")
        base_shingles.add(f"disp:{disp_tok}")
        if zsrc_tok != "none":
            base_shingles.add(f"zsrc:{zsrc_tok}")

    fmt_group = "html" if ext in {"html", "htm", "asp", "aspx", "php"} else ("pdf" if ext == "pdf" else "other")
    canopy_key = f"{fmt_group}:{shape.shape_bucket}"
    sig_parts = [
        fmt_group,
        shape.shape_bucket,
        _host_bucket(host),
        slot_tok or ( _url_dir_prefix(tpl) or "no_tpl"),
    ]
    signature_bucket = "|".join(sig_parts)

    return _PreparedTailDoc(
        row=row,
        reasons=reasons,
        host=host,
        ext=ext,
        url_tpl=tpl,
        slot_token=slot_tok,
        shape=shape,
        canopy_key=canopy_key,
        signature_bucket=signature_bucket,
        shingles=frozenset(base_shingles),
        header_text=win.header,
    )


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / (len(a) + len(b) - inter)


def _opmh_signature(
    shingles: frozenset[str],
    num_bins: int,
    hash_cache: dict[str, int],
) -> tuple[int, ...]:
    """Compute deterministic densified One-Permutation MinHash signature in O(|shingles|)."""
    bins = [_EMPTY_BIN] * num_bins
    mask = num_bins - 1
    use_bitmask = (num_bins & mask) == 0

    for sh in shingles:
        h = hash_cache.get(sh)
        if h is None:
            h = int.from_bytes(blake2b(sh.encode("utf-8"), digest_size=8).digest(), "little")
            hash_cache[sh] = h
        b_idx = (h & mask) if use_bitmask else (h % num_bins)
        shifted = h >> 6
        if shifted < bins[b_idx]:
            bins[b_idx] = shifted

    # Deterministic circular densification when len(shingles) < num_bins
    if any(v == _EMPTY_BIN for v in bins):
        non_empty = [i for i, v in enumerate(bins) if v != _EMPTY_BIN]
        if not non_empty:
            return tuple(0 for _ in range(num_bins))
        for i in range(num_bins):
            if bins[i] == _EMPTY_BIN:
                # Pick nearest clockwise non-empty bin and mix with position salt
                for step in range(1, num_bins + 1):
                    cand = (i + step) % num_bins
                    if bins[cand] != _EMPTY_BIN:
                        salt = _DENSIFY_SALTS[step & 63]
                        bins[i] = (bins[cand] ^ salt) & ((1 << 58) - 1)
                        break

    return tuple(bins)


@dataclass(slots=True)
class _MicroTemplate:
    shingles: frozenset[str]
    doc_indices: list[int]
    signature_bucket: str
    canopy_key: str
    canonical_key: str
    minhash: tuple[int, ...] = ()


def _cluster_prepared_docs(
    docs: list[_PreparedTailDoc],
    *,
    jaccard_threshold: float,
    num_perm: int,
) -> list[list[int]]:
    """Cluster `_PreparedTailDoc` items deterministically via Micro-Template + LSH + Medoid Jaccard."""
    if not docs:
        return []

    eff_bins = 32 if num_perm >= 24 else (16 if num_perm >= 12 else 8)
    hash_cache: dict[str, int] = {}

    # Stage A: Collapse exact shingle-set micro-templates in O(N)
    micro_map: dict[tuple[str, frozenset[str]], _MicroTemplate] = {}
    for idx, doc in enumerate(docs):
        key = (doc.canopy_key, doc.shingles)
        mt = micro_map.get(key)
        if mt is None:
            mt = _MicroTemplate(
                shingles=doc.shingles,
                doc_indices=[idx],
                signature_bucket=doc.signature_bucket,
                canopy_key=doc.canopy_key,
                canonical_key=doc.row.link_key_hex,
            )
            micro_map[key] = mt
        else:
            mt.doc_indices.append(idx)
            if doc.row.link_key_hex < mt.canonical_key:
                mt.canonical_key = doc.row.link_key_hex

    by_canopy: dict[str, list[_MicroTemplate]] = defaultdict(list)
    for mt in micro_map.values():
        mt.minhash = _opmh_signature(mt.shingles, eff_bins, hash_cache)
        by_canopy[mt.canopy_key].append(mt)

    clusters_doc_indices: list[list[int]] = []

    # Stage B: Within each format+layout canopy, run LSH banding + heavy-leader exact Jaccard merge
    for canopy_key in sorted(by_canopy):
        mts = by_canopy[canopy_key]
        # Order heavy recurring templates first so true templates act as cluster medoids
        mts.sort(key=lambda m: (-len(m.doc_indices), -len(m.shingles), m.canonical_key))
        m_count = len(mts)
        if m_count == 1:
            clusters_doc_indices.append(list(mts[0].doc_indices))
            continue

        # Build candidate neighbor adjacency using LSH bands (+ inverted shingle index on small canopies)
        candidates_for: list[set[int]] = [set() for _ in range(m_count)]

        # 1) Multi-granularity LSH bands: r=2 (high recall for J>=0.30) and r=4 (high precision)
        band_specs: list[tuple[int, int]] = []
        for b_idx in range(0, eff_bins, 2):
            band_specs.append((b_idx, min(eff_bins, b_idx + 2)))
        if eff_bins >= 16:
            for b_idx in range(0, eff_bins, 4):
                band_specs.append((b_idx, min(eff_bins, b_idx + 4)))

        for lo, hi in band_specs:
            buckets: dict[tuple[int, ...], list[int]] = defaultdict(list)
            for i, mt in enumerate(mts):
                buckets[mt.minhash[lo:hi]].append(i)
            for members in buckets.values():
                if len(members) <= 1:
                    continue
                # Compare members against the top-8 heaviest templates in the bucket (prevents O(B^2) blowup!)
                anchors = members[:8]
                for a in anchors:
                    for b in members:
                        if a != b:
                            candidates_for[b].add(a)
                            candidates_for[a].add(b)

        # 2) For compact canopies (<= 350 micro-templates), also index informative shingles directly
        # so small test suites / committee slices have 100% exact Jaccard recall.
        if m_count <= 350:
            inv: dict[str, list[int]] = defaultdict(list)
            for i, mt in enumerate(mts):
                for sh in mt.shingles:
                    if sh.startswith(("ext:", "layout:")):
                        continue
                    inv[sh].append(i)
            for posting in inv.values():
                if 2 <= len(posting) <= 120:
                    anchors = posting[:10]
                    for a in anchors:
                        for b in posting:
                            if a != b:
                                candidates_for[b].add(a)
                                candidates_for[a].add(b)

        # Leader-medoid greedy assignment: every assigned micro-template must have exact Jaccard >= threshold
        # directly to an established cluster medoid (zero transitive hub-chaining).
        leader_indices: list[int] = []
        leader_Pos_by_mt: dict[int, int] = {}
        leader_members: list[list[int]] = []

        for i, mt in enumerate(mts):
            best_leader_slot = -1
            best_sim = -1.0
            for cand_mt_idx in sorted(candidates_for[i]):
                slot = leader_Pos_by_mt.get(cand_mt_idx)
                if slot is None:
                    continue
                sim = _jaccard(mt.shingles, mts[cand_mt_idx].shingles)
                if sim >= jaccard_threshold and (
                    sim > best_sim
                    or (sim == best_sim and cand_mt_idx < leader_indices[best_leader_slot])
                ):
                    best_sim = sim
                    best_leader_slot = slot

            if best_leader_slot >= 0:
                leader_members[best_leader_slot].extend(mt.doc_indices)
            else:
                new_slot = len(leader_indices)
                leader_indices.append(i)
                leader_Pos_by_mt[i] = new_slot
                leader_members.append(list(mt.doc_indices))

        clusters_doc_indices.extend(leader_members)

    return clusters_doc_indices


def _select_exemplars(
    member_indices: list[int],
    docs: list[_PreparedTailDoc],
    medoid_shingles: frozenset[str],
    max_exemplars: int,
) -> tuple[str, ...]:
    """Pick 3-5 representative `link_key_hex` exemplars closest to the cluster medoid."""
    scored: list[tuple[float, int, str]] = []
    # Bound exact Jaccard scoring on huge clusters while remaining 100% deterministic
    ordered = sorted(member_indices, key=lambda idx: docs[idx].row.link_key_hex)
    probe_slice = ordered if len(ordered) <= 400 else ordered[:400]
    for idx in probe_slice:
        d = docs[idx]
        sim = _jaccard(d.shingles, medoid_shingles)
        has_text = 1 if d.row.p12_text.strip() else 0
        scored.append((-sim, -has_text, d.row.link_key_hex))
    scored.sort()
    return tuple(lk for _, _, lk in scored[: max(1, max_exemplars)])


def _audit_cluster_rules(
    member_indices: list[int],
    docs: list[_PreparedTailDoc],
    layout_profile: LayoutShapeProfile,
    reason_counts: dict[str, int],
    top_phrases: tuple[PhraseSignature, ...],
    signals: _CompiledPageSignals,
) -> tuple[dict[str, int], RuleRecommendationKind, str | None, str]:
    """Audit existing `document_cover.py` / `page-signals.json` hits and recommend next action."""
    ordered = sorted(member_indices, key=lambda idx: docs[idx].row.link_key_hex)
    sample_indices = ordered[: min(len(ordered), 40)]
    sample_n = max(1, len(sample_indices))

    cover_Counter: Counter[str] = Counter()
    signal_Counter: Counter[str] = Counter()
    emergent_Counter: Counter[str] = Counter()

    for idx in sample_indices:
        row = docs[idx].row
        text = row.p12_text or ""
        url = row.source_url or row.listed_on or ""

        if text.strip():
            if "\f" in text:
                first_p, rest_p = text.split("\f", 1)
                second_p = rest_p.split("\f", 1)[0]
            else:
                first_p, second_p = text[:4500], ""
            cov_fields = document_page_fields(first_p, second_p)
            cov_kinds = cov_fields.get("content_document_kind") or []
            for ck in cov_kinds:
                cover_Counter[f"document_cover:{ck}"] += 1

            head2200 = text[:2200]
            for sig_id, rx in signals.cover_rules:
                if rx.search(head2200):
                    signal_Counter[sig_id] += 1
            for sig_id in _detect_page_signal_errors(row, signals):
                signal_Counter[f"page-signals:{sig_id}"] += 1

            for target_rule, rx in _EMERGENT_COVER_PROBES:
                if rx.search(head2200):
                    emergent_Counter[target_rule] += 1

        if url:
            for sig_id, kind, rx in signals.url_rules:
                if kind != "error_url" and rx.search(url):
                    signal_Counter[f"page-signals:{sig_id}"] += 1

    # Scale sample counts proportionally when len(ordered) > len(sample_indices)
    scale = len(ordered) / sample_n
    partial_matches: dict[str, int] = {}
    for k, v in (cover_Counter + signal_Counter).most_common(8):
        partial_matches[k] = int(round(v * scale))

    if cover_Counter:
        top_cov, top_cov_n = cover_Counter.most_common(1)[0]
        if top_cov_n / sample_n >= 0.30:
            pct = round(100.0 * top_cov_n / sample_n, 1)
            return (
                partial_matches,
                "existing_cover_rule_matches",
                top_cov,
                f"{pct}% of sampled cluster docs already match `{top_cov}` in `document_cover.py` "
                f"(verify cover-override wiring on ambiguous slots or non-PDF formats).",
            )

    if signal_Counter:
        top_sig, top_sig_n = signal_Counter.most_common(1)[0]
        if top_sig_n / sample_n >= 0.30:
            pct = round(100.0 * top_sig_n / sample_n, 1)
            return (
                partial_matches,
                "existing_page_signal_matches",
                top_sig,
                f"{pct}% of sampled cluster docs match `{top_sig}` in `model/registries/page-signals.json`.",
            )

    # Check if this is an error/wrapper/CMS chrome/unreadable stub cluster needing a page-signal rule
    dom_shape = layout_profile.dominant_shape_bucket
    if dom_shape in {"empty_or_unreadable", "short_error_or_stub", "cms_html_chrome"} or (
        reason_counts.get("error_response_candidate", 0) >= 0.5 * len(ordered)
    ):
        if dom_shape == "cms_html_chrome":
            target = "page-signals:cms_navigation_chrome"
            why = "Recurring HTML CMS navigation/header chrome precedes body text; candidate for CMS stripper / wrapper signal."
        elif dom_shape == "empty_or_unreadable":
            target = "page-signals:empty_or_scan_only_container"
            why = "Zero-text or scan-only container cluster; candidate for OCR queue or non-textual container triage rule."
        else:
            target = "page-signals:soft_error_or_stub"
            why = "Recurring short stub or soft-refusal response cluster; candidate for `page-signals.json` error/wrapper marker."
        return (partial_matches, "new_error_or_wrapper_signal_candidate", target, why)

    # Check if an emergent Congressional cover probe fires consistently (>= 50%)
    if emergent_Counter:
        top_em, top_em_n = emergent_Counter.most_common(1)[0]
        if top_em_n / sample_n >= 0.50:
            pct = round(100.0 * top_em_n / sample_n, 1)
            return (
                partial_matches,
                "new_cover_rule_candidate",
                top_em,
                f"{pct}% of sampled cluster docs share `{top_em}` header structure not yet locked by `document_cover.py`.",
            )

    # Check if top log-odds phrase + structured layout indicates a cohesive new template (>= 65% within_df)
    top_df = top_phrases[0].within_df if top_phrases else 0.0
    if top_df >= 0.65 and dom_shape in {
        "checkbox_disclosure_form",
        "table_or_tally_grid",
        "qa_or_qfr_packet",
        "caps_masthead_banner",
    }:
        phrase_slug = _SLUG_SANITIZE_RE.sub("-", top_phrases[0].phrase.lower()).strip("-")[:32]
        target = f"cover:emergent-{phrase_slug or dom_shape}"
        return (
            partial_matches,
            "new_cover_rule_candidate",
            target,
            f"High-cohesion `{dom_shape}` cluster (`{top_phrases[0].phrase}` in {round(top_df * 100, 1)}% of headers); "
            f"candidate for deterministic `{target}` rule.",
        )

    return (
        partial_matches,
        "untemplated_prose_or_manual_review",
        None,
        "Heterogeneous or narrative prose tail documents without a rigid cover banner; route to open-kind extraction or manual sample review.",
    )


def _make_cluster_slug(
    rank: int,
    dominant_hosts: tuple[tuple[str, int], ...],
    dominant_exts: tuple[tuple[str, int], ...],
    shape_bucket: str,
) -> str:
    host_tok = (dominant_hosts[0][0] if dominant_hosts else "nohost").lower()
    if host_tok.startswith("www."):
        host_tok = host_tok[4:]
    if host_tok in {"docs.house.gov", "govinfo.gov", "congress.gov"}:
        host_short = host_tok.replace(".", "-")
    elif host_tok.endswith(".senate.gov"):
        host_short = f"{host_tok.split('.')[0]}-senate"
    elif host_tok.endswith(".house.gov"):
        host_short = f"{host_tok.split('.')[0]}-house"
    else:
        host_short = host_tok.split(".")[0]
    host_clean = _SLUG_SANITIZE_RE.sub("-", host_short).strip("-")[:20] or "host"
    ext_clean = _SLUG_SANITIZE_RE.sub("", (dominant_exts[0][0] if dominant_exts else "doc").lower())[:6] or "doc"
    shape_short = shape_bucket.split("_")[0][:10]
    return f"tail-{rank:03d}-{host_clean}-{ext_clean}-{shape_short}"


def discover_tail_clusters(
    rows: Sequence[CorpusDocRow],
    *,
    baseline_rows: Sequence[CorpusDocRow] | None = None,
    min_cluster_size: int = 3,
    jaccard_threshold: float = 0.35,
    num_perm: int = 32,
    exemplars_per_cluster: int = 5,
    top_k_phrases: int = 8,
    spike_min_delta: int = 5,
    spike_min_ratio: float = 2.0,
    max_phrase_clusters: int = 60,
) -> TailClusterReport:
    """Discover emergent structural templates & error/slot anomalies in the unmapped tail."""
    if min_cluster_size < 1:
        raise ValueError(f"min_cluster_size must be >= 1, got {min_cluster_size}")
    if not (0.0 < jaccard_threshold <= 1.0):
        raise ValueError(f"jaccard_threshold must be in (0, 1], got {jaccard_threshold}")

    from .tfidf_drift import PhraseSignature, compute_log_odds_signatures

    tail_rows, row_tail_reasons = select_tail_population(rows)
    if not tail_rows:
        return TailClusterReport(
            total_input_rows=len(rows),
            target_tail_rows=0,
            clustered_rows=0,
            clusters=(),
            row_to_cluster={},
            row_tail_reasons={},
            findings=(),
        )

    docs = [_prepare_tail_doc(r, row_tail_reasons[r.link_key_hex]) for r in tail_rows]
    raw_groups = _cluster_prepared_docs(
        docs,
        jaccard_threshold=jaccard_threshold,
        num_perm=num_perm,
    )

    # Filter to clusters >= min_cluster_size and sort deterministically by (-size, canonical exemplar key)
    kept_groups: list[tuple[list[int], str]] = []
    for grp in raw_groups:
        if len(grp) >= min_cluster_size:
            min_lk = min(docs[i].row.link_key_hex for i in grp)
            kept_groups.append((grp, min_lk))
    kept_groups.sort(key=lambda item: (-len(item[0]), item[1]))

    if not kept_groups:
        return TailClusterReport(
            total_input_rows=len(rows),
            target_tail_rows=len(tail_rows),
            clustered_rows=0,
            clusters=(),
            row_to_cluster={},
            row_tail_reasons=row_tail_reasons,
            findings=(),
        )

    # Precompute medoid shingles & provisional IDs for kept clusters
    medoid_shingles_per_group: list[frozenset[str]] = []
    sig_bucket_per_group: list[str] = []
    for grp, _ in kept_groups:
        # Medoid = shingle set of the most common micro-template in `grp`
        sh_counts = Counter(docs[i].shingles for i in grp)
        best_sh = sorted(sh_counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))[0][0]
        medoid_shingles_per_group.append(best_sh)
        sb_counts = Counter(docs[i].signature_bucket for i in grp)
        best_sb = sorted(sb_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        sig_bucket_per_group.append(best_sb)

    # Baseline -> candidate cluster growth comparison when `baseline_rows` is supplied
    baseline_counts: list[int] | None = None
    if baseline_rows is not None:
        baseline_counts = [0] * len(kept_groups)
        base_tail_rows, base_reasons = select_tail_population(baseline_rows)
        if base_tail_rows:
            base_docs = [_prepare_tail_doc(r, base_reasons[r.link_key_hex]) for r in base_tail_rows]
            # Index candidate medoids by canopy_key and signature_bucket for fast O(N * K_canopy) matching
            medoids_by_canopy: dict[str, list[int]] = defaultdict(list)
            medoids_by_sig_bucket: dict[str, int] = {}
            for g_idx, (grp, _) in enumerate(kept_groups):
                ckey = docs[grp[0]].canopy_key
                medoids_by_canopy[ckey].append(g_idx)
                medoids_by_sig_bucket.setdefault(sig_bucket_per_group[g_idx], g_idx)

            for bdoc in base_docs:
                best_g = -1
                best_sim = -1.0
                for g_idx in medoids_by_canopy.get(bdoc.canopy_key, ()):
                    sim = _jaccard(bdoc.shingles, medoid_shingles_per_group[g_idx])
                    if sim >= jaccard_threshold and sim > best_sim:
                        best_sim = sim
                        best_g = g_idx
                if best_g < 0 and bdoc.signature_bucket in medoids_by_sig_bucket:
                    cand_g = medoids_by_sig_bucket[bdoc.signature_bucket]
                    if _jaccard(bdoc.shingles, medoid_shingles_per_group[cand_g]) >= jaccard_threshold * 0.75:
                        best_g = cand_g
                if best_g >= 0:
                    baseline_counts[best_g] += 1

    # DRY Discriminative Header Phrase Scoring via `tfidf_drift.compute_log_odds_signatures`
    groups_to_texts: dict[str, list[str]] = {}
    for g_idx, (grp, _) in enumerate(kept_groups[:max_phrase_clusters]):
        key = f"g{g_idx}"
        ordered_grp = sorted(grp, key=lambda idx: docs[idx].row.link_key_hex)
        # Bound per-cluster sample to 250 headers so 323K audits finish in < 1s
        sampled = ordered_grp[:250]
        texts = [docs[idx].header_text for idx in sampled if docs[idx].header_text.strip()]
        if texts:
            groups_to_texts[key] = texts

    phrase_map: dict[str, list[PhraseSignature]] = {}
    if groups_to_texts:
        bg_texts: list[str] | None = None
        if len(groups_to_texts) == 1:
            only_grp_set = set(kept_groups[0][0])
            other_headers = [
                docs[i].header_text
                for i in range(len(docs))
                if i not in only_grp_set and docs[i].header_text.strip()
            ][:300]
            if len(other_headers) < 5:
                tail_keys = set(row_tail_reasons)
                for r in rows:
                    if r.link_key_hex not in tail_keys and r.p12_text.strip():
                        other_headers.append(extract_header_footer_windows(r.p12_text).header)
                        if len(other_headers) >= 200:
                            break
            if other_headers:
                bg_texts = other_headers

        phrase_map = compute_log_odds_signatures(
            groups_to_texts,
            background_texts=bg_texts,
            ngram_range=(1, 3),
            top_k=top_k_phrases,
            min_df=1 if min_cluster_size == 1 else 2,
            min_group_docs=1 if min_cluster_size == 1 else 2,
            window="header",
            exclude_terms=DEFAULT_STOPWORDS,
        )

    signals = _load_compiled_page_signals()
    by_link: dict[str, CorpusDocRow] = {r.link_key_hex: r for r in tail_rows}
    row_to_cluster: dict[str, str] = {}
    clusters_out: list[TailCluster] = []
    findings_out: list[QualityFinding] = []
    clustered_total = 0

    for rank_idx, (grp, _) in enumerate(kept_groups, start=1):
        g_idx = rank_idx - 1
        sz = len(grp)
        clustered_total += sz
        medoid_sh = medoid_shingles_per_group[g_idx]
        sig_bucket = sig_bucket_per_group[g_idx]

        host_cnt = Counter(docs[i].host or "<no_host>" for i in grp)
        ext_cnt = Counter(docs[i].ext for i in grp)
        tpl_cnt = Counter(docs[i].url_tpl for i in grp if docs[i].url_tpl)
        reason_cnt: Counter[str] = Counter()
        shape_cnt: Counter[str] = Counter()

        caps_sum = 0.0
        qa_n = checkbox_n = table_n = sal_n = short_n = 0
        for i in grp:
            d = docs[i]
            for r_code in d.reasons:
                reason_cnt[r_code] += 1
            shape_cnt[d.shape.shape_bucket] += 1
            caps_sum += d.shape.caps_ratio
            if d.shape.has_qa:
                qa_n += 1
            if d.shape.has_checkbox:
                checkbox_n += 1
            if d.shape.has_table:
                table_n += 1
            if d.shape.has_salutation:
                sal_n += 1
            if d.shape.is_short_or_stub:
                short_n += 1

        dom_hosts = tuple(sorted(host_cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:5])
        dom_exts = tuple(sorted(ext_cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:4])
        dom_tpls = tuple(sorted(tpl_cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:4])
        dom_shape = sorted(shape_cnt.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

        layout_prof = LayoutShapeProfile(
            all_caps_header_ratio=caps_sum / sz,
            qa_marker_rate=qa_n / sz,
            checkbox_form_rate=checkbox_n / sz,
            table_pipe_or_grid_rate=table_n / sz,
            salutation_or_letter_rate=sal_n / sz,
            short_or_stub_rate=short_n / sz,
            dominant_shape_bucket=dom_shape,
        )

        cluster_id = _make_cluster_slug(rank_idx, dom_hosts, dom_exts, dom_shape)
        member_lks = tuple(sorted(docs[i].row.link_key_hex for i in grp))
        for lk in member_lks:
            row_to_cluster[lk] = cluster_id

        exemplars = _select_exemplars(grp, docs, medoid_sh, exemplars_per_cluster)
        top_phrases = tuple(phrase_map.get(f"g{g_idx}", ()))

        base_c: int | None = None
        g_delta: int | None = None
        g_ratio: float | None = None
        is_spike = False
        if baseline_counts is not None:
            base_c = baseline_counts[g_idx]
            g_delta = sz - base_c
            g_ratio = (sz + 1.0) / (base_c + 1.0)
            is_spike = (g_delta >= spike_min_delta) and (g_ratio >= spike_min_ratio)

        ordered_reasons = dict(sorted(reason_cnt.items(), key=lambda kv: (-kv[1], kv[0])))
        partial_matches, rec_kind, rec_target, rationale = _audit_cluster_rules(
            grp,
            docs,
            layout_prof,
            ordered_reasons,
            top_phrases,
            signals,
        )

        cluster_obj = TailCluster(
            cluster_id=cluster_id,
            signature_bucket=sig_bucket,
            row_count=sz,
            baseline_count=base_c,
            growth_delta=g_delta,
            growth_ratio=g_ratio,
            is_emergent_spike=is_spike,
            population_reasons=ordered_reasons,
            dominant_hosts=dom_hosts,
            dominant_extensions=dom_exts,
            dominant_url_templates=dom_tpls,
            exemplar_link_keys=exemplars,
            member_link_keys=member_lks,
            top_phrases=top_phrases,
            layout_profile=layout_prof,
            partial_cover_matches=partial_matches,
            recommendation_kind=rec_kind,
            suggested_rule_target=rec_target,
            rationale=rationale,
        )
        clusters_out.append(cluster_obj)

        primary_lk = exemplars[0]
        primary_row = by_link[primary_lk]
        top_phrase_strs = [p.phrase for p in top_phrases[:5]]

        if is_spike:
            findings_out.append(
                QualityFinding(
                    code="tail_cluster_emergent_spike",
                    severity="warning",
                    category="tail_cluster",
                    link_key_hex=primary_lk,
                    filename=primary_row.filename,
                    expected=base_c,
                    observed=sz,
                    score=float(g_ratio or 0.0),
                    evidence={
                        "cluster_id": cluster_id,
                        "growth_delta": g_delta,
                        "growth_ratio": round(float(g_ratio or 0.0), 4),
                        "dominant_host": dom_hosts[0][0] if dom_hosts else "",
                        "exemplar_link_keys": list(exemplars),
                        "top_phrases": top_phrase_strs,
                        "recommendation_kind": rec_kind,
                        "suggested_rule_target": rec_target,
                    },
                )
            )

        if rec_kind == "existing_cover_rule_matches" and rec_target is not None:
            matched_est = partial_matches.get(rec_target, 0)
            if matched_est / sz >= 0.50:
                findings_out.append(
                    QualityFinding(
                        code="tail_cluster_unapplied_cover_rule",
                        severity="warning",
                        category="tail_cluster",
                        link_key_hex=primary_lk,
                        filename=primary_row.filename,
                        expected=rec_target,
                        observed=primary_row.effective_kind or "<unmapped>",
                        score=round(matched_est / sz, 4),
                        evidence={
                            "cluster_id": cluster_id,
                            "row_count": sz,
                            "matched_count_est": matched_est,
                            "population_reasons": ordered_reasons,
                            "exemplar_link_keys": list(exemplars),
                            "top_phrases": top_phrase_strs,
                        },
                    )
                )

        if ordered_reasons.get("error_response_candidate", 0) >= max(min_cluster_size, int(0.5 * sz)):
            untriaged = sum(
                1
                for i in grp
                if (docs[i].row.docmeta_status or "").lower()
                not in {"error_or_block", "ocr_unreadable", "stub_or_blank", "index_or_listing", "govinfo_wrapper"}
            )
            if untriaged >= min_cluster_size:
                findings_out.append(
                    QualityFinding(
                        code="tail_cluster_untriaged_error_or_wrapper",
                        severity="warning",
                        category="tail_cluster",
                        link_key_hex=primary_lk,
                        filename=primary_row.filename,
                        expected="non_usable_status_or_page_signal",
                        observed=f"{untriaged}/{sz}_untriaged",
                        score=round(untriaged / sz, 4),
                        evidence={
                            "cluster_id": cluster_id,
                            "row_count": sz,
                            "untriaged_count": untriaged,
                            "dominant_host": dom_hosts[0][0] if dom_hosts else "",
                            "suggested_rule_target": rec_target,
                            "exemplar_link_keys": list(exemplars),
                            "top_phrases": top_phrase_strs,
                        },
                    )
                )

        if rec_kind in {"new_cover_rule_candidate", "new_error_or_wrapper_signal_candidate"} and sz >= max(
            min_cluster_size, 5
        ):
            findings_out.append(
                QualityFinding(
                    code="tail_cluster_new_rule_candidate",
                    severity="info",
                    category="tail_cluster",
                    link_key_hex=primary_lk,
                    filename=primary_row.filename,
                    expected=rec_target,
                    observed=f"{sz}_tail_docs",
                    score=float(top_phrases[0].z_score if top_phrases else sz),
                    evidence={
                        "cluster_id": cluster_id,
                        "row_count": sz,
                        "recommendation_kind": rec_kind,
                        "suggested_rule_target": rec_target,
                        "rationale": rationale,
                        "exemplar_link_keys": list(exemplars),
                        "top_phrases": top_phrase_strs,
                    },
                )
            )

    return TailClusterReport(
        total_input_rows=len(rows),
        target_tail_rows=len(tail_rows),
        clustered_rows=clustered_total,
        clusters=tuple(clusters_out),
        row_to_cluster=row_to_cluster,
        row_tail_reasons=row_tail_reasons,
        findings=tuple(findings_out),
    )


__all__ = [
    "LayoutShapeProfile",
    "RuleRecommendationKind",
    "TailCluster",
    "TailClusterReport",
    "TailPopulationReason",
    "discover_tail_clusters",
    "select_tail_population",
]
