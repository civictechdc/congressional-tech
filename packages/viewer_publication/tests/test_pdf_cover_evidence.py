"""PDF cover inputs reuse the maintained classifier and ambiguous-slot policy."""
from hashlib import sha256
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.provenance import json_input, list_of, run_job
from docspec_client.client import NativeDatasets
from viewer_publication.pdf_cover_evidence import classify_selected_covers, model_input

ROOT = Path(__file__).parents[3]


def _reading(text):
    return dict(body_sha=sha256(b"original PDF").digest(), parser="pdf_text", parser_version="a"*64,
                text=text, text_sha256=sha256(text.encode()).digest(), page_offsets=[0])


def test_selected_pdf_cover_reaches_existing_kind_policy_and_preserves_official_bill(tmp_path):
    reading = _reading("TRUTH IN TESTIMONY DISCLOSURE FORM\nWITNESS NAME: Jane Doe\n"
                       "FEDERAL GRANTS OR CONTRACTS: none. FOREIGN GOVERNMENT SUPPORT: none.\n"
                       "House Committee on Agriculture. Statement of disclosure for the hearing.")
    engine = NativeDatasets.from_config(os.environ["DOCSPEC_JOB_CONFIG"])
    path, counts = classify_selected_covers([reading], engine=engine, work=tmp_path/"classified",
                                           source_review_sha256="b"*64)
    assert counts["coverage"] == [dict(inspected=1, classified=1)]
    assert pq.read_table(path).column("cover_document_kind").to_pylist() == ["testimony-disclosure"]
    assert pq.read_table(path).column("text_sha256").to_pylist() == [reading["text_sha256"].hex()]
    source, step = model_input(dict(path=str(path)), tmp_path/"inputs")
    inputs = [source, json_input(tmp_path, "body_signals", [], body_sha="Binary", status="Utf8",
                                  error_response="Boolean", cover_document_kind="Utf8"),
              json_input(tmp_path, "base_normalized", [
                  dict(doc_key="misfiled", filename="HHRG-119-AG00-Bio-DoeJ.pdf", document_kind=["witness-biography"], body_hex=reading["body_sha"].hex()),
                  dict(doc_key="official", filename="BILLS-119hr1ih.pdf", document_kind=["bill"], body_hex=reading["body_sha"].hex()),
              ], doc_key="Utf8", filename="Utf8", document_kind=list_of("Utf8"), body_hex="Utf8")]
    result = run_job(tmp_path/"policy", engine, inputs=inputs, steps=[step,
        dict(name="kinds", sql=(ROOT/"model/sql/body-cover-kinds.sql").read_text())], outputs=[],
        queries=[dict(name="rows", sql="SELECT * FROM kinds")])
    assert result["rows"] == [dict(doc_key="misfiled", cover_document_kind=["testimony-disclosure"],
                                    cover_document_family=["disclosure"])]


def test_unqualified_digest_and_unknown_kind_are_refused(tmp_path):
    row = _reading("Truth in testimony")
    row["text_sha256"] = b"x"*32
    with pytest.raises(ValueError, match="digest mismatch"):
        classify_selected_covers([row], engine=None, work=tmp_path/"wrong", source_review_sha256="b"*64)
    path = tmp_path/"unsupported.parquet"
    pq.write_table(pa.Table.from_pylist([dict(body_sha256="a"*64, parser_version="b"*64,
        text_sha256="c"*64, source_review_sha256="d"*64, cover_document_kind="invented")]), path)
    with pytest.raises(ValueError, match="supported kind"):
        model_input(dict(path=str(path)), tmp_path/"input")


def test_pdf_cover_input_requires_pinned_selection_in_model_spec(tmp_path):
    from archive_job_fixture import model_spec
    from viewer_publication.archive_model_job import validate_spec
    value = model_spec(tmp_path)
    value["pdf_cover_evidence"] = dict(path="cover.parquet", sha256="a"*64, size=10, selection_sha256="b"*64)
    checked = validate_spec(value, base=tmp_path)
    assert checked["pdf_cover_evidence"]["selection_sha256"] == "b"*64
    value["pdf_cover_evidence"]["selection_sha256"] = "latest"
    with pytest.raises(ValueError, match="exact accepted-selection"):
        validate_spec(value, base=tmp_path)
