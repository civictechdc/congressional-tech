"""Locked DocMeta V7 -> viewer_publication (`docmeta_v7`) release seam contract.

Defines the PyArrow sidecar schema, fail-closed validator, canonical DataFusion
join & invariant SQL, and architectural ownership constants so corpus building,
future local student inference, `viewer_publication`, `explorer_mcp`, and `site`
share one stable interface prior to Gate-1 archive integration.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import copy
import re
from typing import Any, Final

import pyarrow as pa

from .crosswalk import map_genre_to_document_kind
from .factory.grounding import (
    _iter_span_refs,
    repair_span_refs_in_payload,
    strip_invisible_format_chars,
)
from .models import DocStatus, GENRE_TO_FAMILY, MediaFormat, PrimaryGenre

DOCMETA_V7_CONTRACT_VERSION: Final[str] = "7.3"
DOCMETA_V7_TEXT_WINDOW_CHARS: Final[int] = 9000
DOCMETA_V7_TEXT_WINDOW_SPEC: Final[str] = "p12_clean_or_raw_head_9000"
DOCMETA_V7_STUDENT_TEXT_WINDOW_SPEC: Final[str] = "p12_clean_plus_p3_bidi_clean_9000"
SUPPORTED_TEXT_WINDOW_SPECS: Final[tuple[str, ...]] = (
    DOCMETA_V7_TEXT_WINDOW_SPEC,
    DOCMETA_V7_STUDENT_TEXT_WINDOW_SPEC,
)
DOCUMENT_CONTEXT_ALLOWED_FIELDS: Final[tuple[str, ...]] = (
    "page_count",
    "saved_bytes",
    "congress_gov_doc_title",
    "source_link_text",
)
DOCUMENT_CONTEXT_FORBIDDEN_FIELDS: Final[tuple[str, ...]] = (
    "filename",
    "congress_gov_role",
)
STUDENT_CONTEXT_DROPOUT_RATE: Final[float] = 0.50
DOCMETA_V7_JOIN_KEYS: Final[tuple[str, ...]] = ("link_key", "doc_key", "saved_body")
ENTITY_RESOLUTION_OWNER: Final[str] = "viewer_publication.org_entities"
FRBR_CROSS_DOC_POPULATED: Final[bool] = False

_GENERIC_LINK_TEXTS = frozenset(
    {
        "please click here",
        "click here",
        "download",
        "pdf",
        "view pdf",
        "here",
    }
)

_ZERO_SAVED_BODY: Final[bytes] = b"\x00" * 32
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_SQL_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

REQUIRED_RELEASE_SIDECAR_COLUMNS: Final[tuple[str, ...]] = (
    "link_key",
    "doc_key",
    "saved_body",
    "effective_body_sha",
    "package_id",
    "docmeta_source",
    "codebook_version",
    "text_window_spec",
    "text_window_sha256",
    "status",
    "media_format",
    "is_packet",
    "contains_genres",
    "primary_genre",
    "archive_document_kind",
    "specialist_family",
    "subkind",
    "verbatim_title",
    "doc_date",
    "chamber",
    "congress",
    "committees",
    "gist",
    "topics",
    "specialist_payload_json",
    "strict_v7_valid",
    "crosswalk_congress_gov_types",
    "crosswalk_docs_house_codes",
    "crosswalk_lcgft_uris",
)


def release_sidecar_arrow_schema() -> pa.Schema:
    """Return the canonical PyArrow schema for the `docmeta_v7` release sidecar."""
    return pa.schema(
        [
            pa.field("link_key", pa.binary(8), nullable=False),
            pa.field("doc_key", pa.string(), nullable=False),
            pa.field("saved_body", pa.binary(32), nullable=False),
            pa.field("effective_body_sha", pa.binary(32), nullable=True),
            pa.field("package_id", pa.string(), nullable=True),
            pa.field("docmeta_source", pa.string(), nullable=False),
            pa.field("codebook_version", pa.string(), nullable=False),
            pa.field("text_window_spec", pa.string(), nullable=False),
            pa.field("text_window_sha256", pa.string(), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            pa.field("media_format", pa.string(), nullable=True),
            pa.field("is_packet", pa.bool_(), nullable=False),
            pa.field("contains_genres", pa.list_(pa.string()), nullable=False),
            pa.field("primary_genre", pa.string(), nullable=True),
            pa.field("archive_document_kind", pa.string(), nullable=True),
            pa.field("specialist_family", pa.string(), nullable=True),
            pa.field("subkind", pa.string(), nullable=True),
            pa.field("verbatim_title", pa.string(), nullable=True),
            pa.field("doc_date", pa.string(), nullable=True),
            pa.field("chamber", pa.string(), nullable=True),
            pa.field("congress", pa.int64(), nullable=True),
            pa.field("committees", pa.list_(pa.string()), nullable=False),
            pa.field("gist", pa.string(), nullable=True),
            pa.field("topics", pa.list_(pa.string()), nullable=False),
            pa.field("specialist_payload_json", pa.string(), nullable=True),
            pa.field("strict_v7_valid", pa.bool_(), nullable=False),
            pa.field("crosswalk_congress_gov_types", pa.list_(pa.string()), nullable=False),
            pa.field("crosswalk_docs_house_codes", pa.list_(pa.string()), nullable=False),
            pa.field("crosswalk_lcgft_uris", pa.list_(pa.string()), nullable=False),
        ]
    )


def validate_release_sidecar_table(table: pa.Table) -> list[str]:
    """Validate columns, Arrow binary key types, identity invariants, and taxonomy alignment."""
    errors: list[str] = []
    expected_schema = release_sidecar_arrow_schema()
    actual_names = set(table.column_names)
    missing = [col for col in REQUIRED_RELEASE_SIDECAR_COLUMNS if col not in actual_names]
    if missing:
        errors.append(f"Missing required release sidecar columns: {missing}")
        return errors

    for expected_field in expected_schema:
        actual_field = table.schema.field(expected_field.name)
        if actual_field.type != expected_field.type:
            # Allow large_string / large_list variants? No: fail closed on type mismatch for release seam.
            errors.append(
                f"Column {expected_field.name!r} type mismatch: expected {expected_field.type}, got {actual_field.type}."
            )

    if errors:
        return errors

    rows = table.to_pylist()
    link_counter: Counter[bytes] = Counter()
    doc_counter: Counter[str] = Counter()
    pair_counter: Counter[tuple[bytes, str]] = Counter()
    valid_statuses = {s.value for s in DocStatus}
    valid_genres = {g.value for g in PrimaryGenre}
    valid_media_formats = {m.value for m in MediaFormat}
    valid_window_specs = frozenset(SUPPORTED_TEXT_WINDOW_SPECS)

    for idx, row in enumerate(rows):
        lk = row.get("link_key")
        dk = row.get("doc_key")
        sb = row.get("saved_body")
        eff_sb = row.get("effective_body_sha")

        if not isinstance(lk, (bytes, bytearray)) or len(lk) != 8:
            errors.append(f"row[{idx}]: link_key must be 8 raw bytes.")
        else:
            lk_b = bytes(lk)
            link_counter[lk_b] += 1

        if not isinstance(dk, str) or not dk.strip():
            errors.append(f"row[{idx}]: doc_key must be non-empty string.")
        else:
            if dk.startswith("doc:"):
                errors.append(f"row[{idx}]: fabricated 'doc:' doc_key is forbidden ({dk!r}).")
            doc_counter[dk] += 1
            if isinstance(lk, (bytes, bytearray)) and len(lk) == 8:
                pair_counter[(bytes(lk), dk)] += 1

        if not isinstance(sb, (bytes, bytearray)) or len(sb) != 32:
            errors.append(f"row[{idx}]: saved_body must be 32 raw bytes.")
        elif bytes(sb) == _ZERO_SAVED_BODY:
            errors.append(f"row[{idx}]: saved_body cannot be zeroed 32-byte digest.")

        if eff_sb is not None:
            if not isinstance(eff_sb, (bytes, bytearray)) or len(eff_sb) != 32:
                errors.append(f"row[{idx}]: effective_body_sha must be 32 raw bytes when present.")
            elif bytes(eff_sb) == _ZERO_SAVED_BODY:
                errors.append(f"row[{idx}]: effective_body_sha cannot be zeroed 32-byte digest.")

        tw_spec = row.get("text_window_spec")
        if tw_spec not in valid_window_specs:
            errors.append(f"row[{idx}]: unsupported text_window_spec {tw_spec!r}.")

        tw_sha = row.get("text_window_sha256")
        if not isinstance(tw_sha, str) or not _SHA256_HEX_RE.fullmatch(tw_sha):
            errors.append(f"row[{idx}]: text_window_sha256 must be 64 lowercase hex chars.")

        if row.get("strict_v7_valid") is not True:
            errors.append(f"row[{idx}]: strict_v7_valid must be True on every release sidecar row.")

        status = row.get("status")
        media_format = row.get("media_format")
        is_packet = row.get("is_packet")
        contains_genres = list(row.get("contains_genres") or [])
        genre = row.get("primary_genre")
        arch_dk = row.get("archive_document_kind")
        spec_fam = row.get("specialist_family")
        subkind = row.get("subkind")
        if status not in valid_statuses:
            errors.append(f"row[{idx}]: unknown status {status!r}.")
            continue

        if status == DocStatus.usable.value:
            if media_format not in valid_media_formats:
                errors.append(f"row[{idx}]: usable row has invalid media_format {media_format!r}.")
            if genre not in valid_genres:
                errors.append(f"row[{idx}]: usable row has invalid primary_genre {genre!r}.")
            else:
                expected_fam = GENRE_TO_FAMILY[PrimaryGenre(genre)].value
                if spec_fam != expected_fam:
                    errors.append(
                        f"row[{idx}]: specialist_family={spec_fam!r} does not match expected {expected_fam!r} "
                        f"for primary_genre={genre!r}."
                    )
                expected_dk = map_genre_to_document_kind(genre, subkind=subkind)
                if arch_dk != expected_dk:
                    errors.append(
                        f"row[{idx}]: archive_document_kind={arch_dk!r} does not match expected {expected_dk!r} "
                        f"for primary_genre={genre!r}, subkind={subkind!r}."
                    )
        else:
            if media_format is not None:
                errors.append(f"row[{idx}]: non-usable status={status!r} must have media_format=None.")
            if spec_fam is not None:
                errors.append(f"row[{idx}]: non-usable status={status!r} must have specialist_family=None.")
            if is_packet is not False:
                errors.append(f"row[{idx}]: non-usable status={status!r} must have is_packet=False.")
            if contains_genres:
                errors.append(f"row[{idx}]: non-usable status={status!r} must have empty contains_genres.")
            if genre is not None:
                errors.append(f"row[{idx}]: non-usable status={status!r} must have primary_genre=None.")
            if arch_dk is not None:
                errors.append(f"row[{idx}]: non-usable status={status!r} must have archive_document_kind=None.")

    dup_links = sum(1 for c in link_counter.values() if c > 1)
    dup_docs = sum(1 for c in doc_counter.values() if c > 1)
    dup_pairs = sum(1 for c in pair_counter.values() if c > 1)
    if dup_links:
        errors.append(f"Duplicate link_key values present ({dup_links}).")
    if dup_docs:
        errors.append(f"Duplicate doc_key values present ({dup_docs}).")
    if dup_pairs:
        errors.append(f"Duplicate (link_key, doc_key) pairs present ({dup_pairs}).")

    return errors


def _checked_ident(name: str) -> str:
    if not _SQL_IDENT_RE.fullmatch(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


def build_docmeta_v7_release_join_sql(unified_table: str = "docmeta_v7_unified") -> str:
    """Return canonical DataFusion release join SQL keeping the smaller sidecar on the left."""
    tbl = _checked_ident(unified_table)
    return "\n".join(
        [
            "-- Join materialized docmeta_v7 records onto internal release `details` keys.",
            "-- Keep small unified sidecar on the left (DataFusion hash-build side) without unpushed captures GROUP BY.",
            "SELECT",
            "    d.list_row,",
            "    u.link_key,",
            "    u.doc_key,",
            "    u.saved_body,",
            "    u.effective_body_sha,",
            "    coalesce(u.package_id, d.package_id) AS package_id,",
            "    u.docmeta_source,",
            "    u.codebook_version,",
            "    u.text_window_spec,",
            "    u.text_window_sha256,",
            "    u.status,",
            "    u.media_format,",
            "    u.is_packet,",
            "    u.contains_genres,",
            "    u.primary_genre,",
            "    u.archive_document_kind,",
            "    u.specialist_family,",
            "    u.subkind,",
            "    u.verbatim_title,",
            "    u.doc_date,",
            "    u.chamber,",
            "    u.congress,",
            "    u.committees,",
            "    u.gist,",
            "    u.topics,",
            "    u.specialist_payload_json,",
            "    u.strict_v7_valid,",
            "    u.crosswalk_congress_gov_types,",
            "    u.crosswalk_docs_house_codes,",
            "    u.crosswalk_lcgft_uris",
            f"FROM {tbl} u",
            "JOIN (SELECT list_row, doc_key, link_key, saved_body, package_id FROM details) d",
            "  ON u.link_key = d.link_key AND u.doc_key = d.doc_key",
            "ORDER BY d.list_row",
        ]
    )


def build_docmeta_v7_invariants_sql(unified_table: str = "docmeta_v7_unified") -> str:
    """Return fail-closed DataFusion invariant query (all counts must equal 0)."""
    tbl = _checked_ident(unified_table)
    return "\n".join(
        [
            "SELECT",
            f"    (SELECT count(*) FROM (SELECT link_key FROM {tbl} GROUP BY link_key HAVING count(*) > 1)) AS duplicate_docmeta_link_keys,",
            f"    (SELECT count(*) FROM (SELECT doc_key FROM {tbl} GROUP BY doc_key HAVING count(*) > 1)) AS duplicate_docmeta_doc_keys,",
            f"    (SELECT count(*) FROM {tbl} u LEFT ANTI JOIN details d ON u.link_key = d.link_key AND u.doc_key = d.doc_key) AS missing_release_documents,",
            f"    (SELECT count(*) FROM {tbl} u JOIN details d ON u.link_key = d.link_key AND u.doc_key = d.doc_key WHERE u.saved_body IS DISTINCT FROM d.saved_body) AS saved_body_mismatches,",
            f"    (SELECT count(*) FROM {tbl} WHERE strict_v7_valid IS DISTINCT FROM true OR starts_with(doc_key, 'doc:')) AS invalid_v7_rows",
        ]
    )


def _clean_invisible_format_chars(text: str) -> str:
    return strip_invisible_format_chars(text)


def _strip_span_quotes_inplace(payload: dict[str, Any]) -> None:
    for _, span in _iter_span_refs(payload):
        quote = span.get("quote")
        if isinstance(quote, str):
            clean_quote = strip_invisible_format_chars(quote)
            if clean_quote != quote:
                span["quote"] = clean_quote


def reanchor_payload_for_clean_text(
    raw_text: str,
    core_payload: Mapping[str, Any],
    specialist_payload: Mapping[str, Any] | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any] | None, list[str]]:
    """Strip invisible format chars from `raw_text` and re-anchor SpanRef offsets onto the cleaned text.

    Ensures legacy V7.3a candidates containing Unicode bidi/soft-hyphen characters maintain
    exact character-offset parity when emitted inside bidi-stripped `<<<DOC_TEXT>>>` for SFT.
    """
    src_text = str(raw_text or "")
    cleaned = strip_invisible_format_chars(src_text)
    repairs: list[str] = []
    if cleaned != src_text:
        repairs.append("stripped_invisible_format_chars")

    core_in = copy.deepcopy(dict(core_payload))
    _strip_span_quotes_inplace(core_in)
    repaired_core = repair_span_refs_in_payload(cleaned, core_in)
    for (path, orig_span), (_, new_span) in zip(_iter_span_refs(dict(core_payload)), _iter_span_refs(repaired_core)):
        if (
            orig_span.get("start") != new_span.get("start")
            or orig_span.get("end") != new_span.get("end")
            or orig_span.get("quote") != new_span.get("quote")
        ):
            repairs.append(f"core.{path}")

    repaired_spec: dict[str, Any] | None = None
    if specialist_payload is not None:
        spec_in = copy.deepcopy(dict(specialist_payload))
        _strip_span_quotes_inplace(spec_in)
        repaired_spec = repair_span_refs_in_payload(cleaned, spec_in)
        for (path, orig_span), (_, new_span) in zip(
            _iter_span_refs(dict(specialist_payload)), _iter_span_refs(repaired_spec)
        ):
            if (
                orig_span.get("start") != new_span.get("start")
                or orig_span.get("end") != new_span.get("end")
                or orig_span.get("quote") != new_span.get("quote")
            ):
                repairs.append(f"specialist.{path}")

    return cleaned, repaired_core, repaired_spec, repairs


def format_two_channel_input(
    doc_text: str,
    *,
    context: Mapping[str, Any] | None = None,
    filename_for_filter: str | None = None,
) -> str:
    """Format sovereign `<<<DOC_TEXT>>>` paired with optional sanitized `<<<DOCUMENT_CONTEXT>>>`.

    Rejects forbidden trap keys (`filename`, `congress_gov_role`) or unknown context keys,
    strips invisible Unicode bidi/format chars, and filters generic/filename `source_link_text`.
    """
    cleaned_doc = _clean_invisible_format_chars(str(doc_text or ""))
    rendered_ctx: list[str] = []
    if context is not None:
        allowed_set = frozenset(DOCUMENT_CONTEXT_ALLOWED_FIELDS)
        forbidden_set = frozenset(DOCUMENT_CONTEXT_FORBIDDEN_FIELDS)
        for k in context.keys():
            if k in forbidden_set:
                raise ValueError(f"Forbidden context key {k!r}: raw filename slugs and Congress.gov roles cannot be passed.")
            if k not in allowed_set:
                raise ValueError(f"Unknown context key {k!r}: allowed keys are {DOCUMENT_CONTEXT_ALLOWED_FIELDS}.")

        fn_cf = _clean_invisible_format_chars(str(filename_for_filter or "")).strip().casefold()
        for key in DOCUMENT_CONTEXT_ALLOWED_FIELDS:
            if key not in context or context[key] is None:
                continue
            val = context[key]
            if isinstance(val, str):
                s_val = " ".join(_clean_invisible_format_chars(val).split())
                if not s_val:
                    continue
                if key == "source_link_text":
                    low = s_val.casefold()
                    if len(s_val) < 15 or low in _GENERIC_LINK_TEXTS or (fn_cf and low == fn_cf):
                        continue
                rendered_ctx.append(f"{key}: {s_val}")
            elif isinstance(val, bool):
                raise ValueError(f"Context field {key!r} must not be boolean.")
            elif isinstance(val, int):
                if val <= 0:
                    continue
                rendered_ctx.append(f"{key}: {val}")
            else:
                s_val = " ".join(_clean_invisible_format_chars(str(val)).split())
                if s_val:
                    rendered_ctx.append(f"{key}: {s_val}")

    doc_block = f"<<<DOC_TEXT>>>\n{cleaned_doc}\n<<<END_DOC_TEXT>>>"
    if not rendered_ctx:
        return doc_block
    ctx_block = "<<<DOCUMENT_CONTEXT>>>\n" + "\n".join(rendered_ctx) + "\n<<<END_DOCUMENT_CONTEXT>>>"
    return f"{ctx_block}\n\n{doc_block}"


__all__ = [
    "DOCMETA_V7_CONTRACT_VERSION",
    "DOCMETA_V7_JOIN_KEYS",
    "DOCMETA_V7_STUDENT_TEXT_WINDOW_SPEC",
    "DOCMETA_V7_TEXT_WINDOW_CHARS",
    "DOCMETA_V7_TEXT_WINDOW_SPEC",
    "DOCUMENT_CONTEXT_ALLOWED_FIELDS",
    "DOCUMENT_CONTEXT_FORBIDDEN_FIELDS",
    "ENTITY_RESOLUTION_OWNER",
    "FRBR_CROSS_DOC_POPULATED",
    "REQUIRED_RELEASE_SIDECAR_COLUMNS",
    "STUDENT_CONTEXT_DROPOUT_RATE",
    "SUPPORTED_TEXT_WINDOW_SPECS",
    "build_docmeta_v7_invariants_sql",
    "build_docmeta_v7_release_join_sql",
    "format_two_channel_input",
    "reanchor_payload_for_clean_text",
    "release_sidecar_arrow_schema",
    "validate_release_sidecar_table",
]
