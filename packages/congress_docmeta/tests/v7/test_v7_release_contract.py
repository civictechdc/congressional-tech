"""Unit tests for the locked DocMeta V7 -> viewer_publication release contract."""

from __future__ import annotations

import hashlib

import pytest
import pyarrow as pa

from congress_docmeta.v7.codebook import codebook_version
from congress_docmeta.v7.crosswalk import (
    map_genre_to_congress_gov,
    map_genre_to_docs_house_gov,
    map_genre_to_document_kind,
    map_genre_to_lcgft,
)
from congress_docmeta.v7.models import SpanRef, verify_span_in_text
from congress_docmeta.v7.release_contract import (
    DOCMETA_V7_STUDENT_TEXT_WINDOW_SPEC,
    DOCMETA_V7_TEXT_WINDOW_SPEC,
    DOCUMENT_CONTEXT_ALLOWED_FIELDS,
    DOCUMENT_CONTEXT_FORBIDDEN_FIELDS,
    ENTITY_RESOLUTION_OWNER,
    FRBR_CROSS_DOC_POPULATED,
    REQUIRED_RELEASE_SIDECAR_COLUMNS,
    STUDENT_CONTEXT_DROPOUT_RATE,
    SUPPORTED_TEXT_WINDOW_SPECS,
    build_docmeta_v7_invariants_sql,
    build_docmeta_v7_release_join_sql,
    format_two_channel_input,
    reanchor_payload_for_clean_text,
    release_sidecar_arrow_schema,
    validate_release_sidecar_table,
)


def _valid_row(idx: int = 1, *, usable: bool = True) -> dict:
    genre = "witness_testimony" if usable else None
    subkind = None
    return {
        "link_key": idx.to_bytes(8, "big"),
        "doc_key": hashlib.sha256(f"canonical-doc-{idx}".encode("utf-8")).hexdigest()[:16],
        "saved_body": hashlib.sha256(f"captured-bytes-{idx}".encode("utf-8")).digest(),
        "effective_body_sha": None,
        "package_id": "HHRG-119-IF00",
        "docmeta_source": "docmeta_v7_3b_student",
        "codebook_version": codebook_version(),
        "text_window_spec": DOCMETA_V7_TEXT_WINDOW_SPEC,
        "text_window_sha256": hashlib.sha256(f"window-{idx}".encode("utf-8")).hexdigest(),
        "status": "usable" if usable else "error_or_block",
        "media_format": "prose" if usable else None,
        "is_packet": False,
        "contains_genres": [],
        "primary_genre": genre,
        "archive_document_kind": map_genre_to_document_kind(genre, subkind=subkind) if genre else None,
        "specialist_family": "testimony_bio_disclosure" if usable else None,
        "subkind": subkind,
        "verbatim_title": "Testimony of Witness" if usable else None,
        "doc_date": "2026-03-10" if usable else None,
        "chamber": "house" if usable else None,
        "congress": 119 if usable else None,
        "committees": ["hsif00"] if usable else [],
        "gist": "Written testimony." if usable else None,
        "topics": ["energy"] if usable else [],
        "specialist_payload_json": None,
        "strict_v7_valid": True,
        "crosswalk_congress_gov_types": map_genre_to_congress_gov(genre) if genre else [],
        "crosswalk_docs_house_codes": map_genre_to_docs_house_gov(genre) if genre else [],
        "crosswalk_lcgft_uris": map_genre_to_lcgft(genre) if genre else [],
    }


def test_release_sidecar_schema_and_validator_accepts_and_rejects() -> None:
    assert ENTITY_RESOLUTION_OWNER == "viewer_publication.org_entities"
    assert FRBR_CROSS_DOC_POPULATED is False

    schema = release_sidecar_arrow_schema()
    assert tuple(schema.names) == REQUIRED_RELEASE_SIDECAR_COLUMNS

    ok_table = pa.Table.from_pylist([_valid_row(1, usable=True), _valid_row(2, usable=False)], schema=schema)
    assert validate_release_sidecar_table(ok_table) == []

    # Reject fabricated `doc:` key prefix (legacy sidecar_builder regression).
    bad_doc_key = _valid_row(3)
    bad_doc_key["doc_key"] = "doc:0000000000000003"
    errs = validate_release_sidecar_table(pa.Table.from_pylist([bad_doc_key], schema=schema))
    assert any("doc:" in e for e in errs)

    # Reject zeroed saved_body placeholder digest.
    bad_sb = _valid_row(4)
    bad_sb["saved_body"] = b"\x00" * 32
    errs_sb = validate_release_sidecar_table(pa.Table.from_pylist([bad_sb], schema=schema))
    assert any("zeroed" in e for e in errs_sb)

    # Reject unaligned archive_document_kind.
    bad_kind = _valid_row(5)
    bad_kind["archive_document_kind"] = "wrong-kind"
    errs_kind = validate_release_sidecar_table(pa.Table.from_pylist([bad_kind], schema=schema))
    assert any("archive_document_kind" in e for e in errs_kind)

    # Reject duplicates.
    dup_tbl = pa.Table.from_pylist([_valid_row(1), _valid_row(1)], schema=schema)
    errs_dup = validate_release_sidecar_table(dup_tbl)
    assert any("Duplicate" in e for e in errs_dup)

    # Reject bad text_window_spec, zeroed effective_body_sha, invalid media_format, mismatched family,
    # and non-usable rows with populated packet/genre/family metadata.
    bad_ws = _valid_row(6)
    bad_ws["text_window_spec"] = "unsupported_window_spec"
    assert any("text_window_spec" in e for e in validate_release_sidecar_table(pa.Table.from_pylist([bad_ws], schema=schema)))

    bad_eff = _valid_row(7)
    bad_eff["effective_body_sha"] = b"\x00" * 32
    assert any("effective_body_sha" in e for e in validate_release_sidecar_table(pa.Table.from_pylist([bad_eff], schema=schema)))

    bad_mf = _valid_row(8)
    bad_mf["media_format"] = "fax_image"
    assert any("media_format" in e for e in validate_release_sidecar_table(pa.Table.from_pylist([bad_mf], schema=schema)))

    bad_fam = _valid_row(9)
    bad_fam["specialist_family"] = "event_logistics"
    assert any("specialist_family" in e for e in validate_release_sidecar_table(pa.Table.from_pylist([bad_fam], schema=schema)))

    bad_non_usable = _valid_row(10, usable=False)
    bad_non_usable["media_format"] = "prose"
    bad_non_usable["specialist_family"] = "event_logistics"
    bad_non_usable["is_packet"] = True
    bad_non_usable["contains_genres"] = ["witness_testimony"]
    nu_errs = validate_release_sidecar_table(pa.Table.from_pylist([bad_non_usable], schema=schema))
    assert len(nu_errs) == 4


def test_release_join_and_invariants_sql() -> None:
    join_sql = build_docmeta_v7_release_join_sql()
    assert "ON u.link_key = d.link_key AND u.doc_key = d.doc_key" in join_sql
    assert "FROM docmeta_v7_unified u" in join_sql
    assert "JOIN (SELECT list_row, doc_key, link_key, saved_body, package_id FROM details) d" in join_sql

    inv_sql = build_docmeta_v7_invariants_sql()
    for expected in (
        "duplicate_docmeta_link_keys",
        "duplicate_docmeta_doc_keys",
        "missing_release_documents",
        "saved_body_mismatches",
        "invalid_v7_rows",
        "starts_with(doc_key, 'doc:')",
    ):
        assert expected in inv_sql


def test_two_channel_student_input_contract_and_sanitization() -> None:
    assert DOCMETA_V7_STUDENT_TEXT_WINDOW_SPEC == "p12_clean_plus_p3_bidi_clean_9000"
    assert DOCMETA_V7_TEXT_WINDOW_SPEC in SUPPORTED_TEXT_WINDOW_SPECS
    assert DOCMETA_V7_STUDENT_TEXT_WINDOW_SPEC in SUPPORTED_TEXT_WINDOW_SPECS
    assert STUDENT_CONTEXT_DROPOUT_RATE == 0.50
    assert DOCUMENT_CONTEXT_FORBIDDEN_FIELDS == ("filename", "congress_gov_role")
    assert "congress_gov_doc_title" in DOCUMENT_CONTEXT_ALLOWED_FIELDS

    # Context=None emits clean DOC_TEXT only and strips invisible bidi chars.
    plain = format_two_channel_input("\u202dWritten Testimony of Witness\u202c")
    assert plain == "<<<DOC_TEXT>>>\nWritten Testimony of Witness\n<<<END_DOC_TEXT>>>"

    # Reject forbidden filename / role fields fail-closed.
    with pytest.raises(ValueError, match="Forbidden context key"):
        format_two_channel_input("text", context={"filename": "HHRG-119-Wstate-Trap.pdf"})
    with pytest.raises(ValueError, match="Forbidden context key"):
        format_two_channel_input("text", context={"congress_gov_role": "Witness Statement"})
    with pytest.raises(ValueError, match="Unknown context key"):
        format_two_channel_input("text", context={"custom_hint": "value"})

    # Filters generic / short / filename source_link_text and renders allowed context.
    only_generic = format_two_channel_input(
        "Chart values",
        context={"source_link_text": "please click here"},
        filename_for_filter="chart.pdf",
    )
    assert "<<<DOCUMENT_CONTEXT>>>" not in only_generic

    same_as_fn = format_two_channel_input(
        "Nomination hearing text",
        context={"source_link_text": "Nomination_Hearing_GPO.pdf"},
        filename_for_filter="Nomination_Hearing_GPO.pdf",
    )
    assert "<<<DOCUMENT_CONTEXT>>>" not in same_as_fn

    rich = format_two_channel_input(
        "Executive Order 14112",
        context={
            "page_count": 5,
            "saved_bytes": 217288,
            "congress_gov_doc_title": "\u202dFTR - E.O. 14112 - Rep. Leger Fernandez\u202c",
            "source_link_text": "The second slide provides a breakdown of 50,000 assets",
        },
    )
    assert "<<<DOCUMENT_CONTEXT>>>\npage_count: 5\nsaved_bytes: 217288\n" in rich
    assert "congress_gov_doc_title: FTR - E.O. 14112 - Rep. Leger Fernandez\n" in rich
    assert "source_link_text: The second slide provides a breakdown of 50,000 assets\n<<<END_DOCUMENT_CONTEXT>>>" in rich
    assert rich.endswith("<<<DOC_TEXT>>>\nExecutive Order 14112\n<<<END_DOC_TEXT>>>")


def test_reanchor_payload_for_clean_text_bidi_offset_parity() -> None:
    raw_text = (
        "\u202dWritten Testimony of Dr. Jayesh K. Gupta\u202c\n"
        "Before the House Committee on Science\n"
        "Hearing Date: \u202dJuly 16, 2025\u202c\n"
    )
    t0 = raw_text.index("\u202dWritten")
    t1 = t0 + len("\u202dWritten Testimony of Dr. Jayesh K. Gupta\u202c")
    d0 = raw_text.index("\u202dJuly 16, 2025\u202c")
    d1 = d0 + len("\u202dJuly 16, 2025\u202c")
    core = {
        "verbatim_title": "Written Testimony of Dr. Jayesh K. Gupta",
        "title_span": {"quote": raw_text[t0:t1], "start": t0, "end": t1},
        "doc_date": "2025-07-16",
        "date_spans": [{"quote": raw_text[d0:d1], "start": d0, "end": d1}],
    }
    spec = {"event_date_span": {"quote": raw_text[d0:d1], "start": d0, "end": d1}}

    cleaned, rec_core, rec_spec, repairs = reanchor_payload_for_clean_text(raw_text, core, spec)
    formatted = format_two_channel_input(raw_text)
    assert formatted == f"<<<DOC_TEXT>>>\n{cleaned}\n<<<END_DOC_TEXT>>>"
    assert "stripped_invisible_format_chars" in repairs
    assert verify_span_in_text(SpanRef.model_validate(rec_core["title_span"]), cleaned, normalize_ws=False) is True
    assert verify_span_in_text(SpanRef.model_validate(rec_core["date_spans"][0]), cleaned, normalize_ws=False) is True
    assert rec_spec is not None
    assert verify_span_in_text(SpanRef.model_validate(rec_spec["event_date_span"]), cleaned, normalize_ws=False) is True
    assert rec_core["title_span"]["start"] == 0
    assert rec_core["title_span"]["quote"] == "Written Testimony of Dr. Jayesh K. Gupta"
