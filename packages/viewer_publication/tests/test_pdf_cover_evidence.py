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


def test_pdf_cover_evidence_does_not_pull_capture_storage_into_definition_hashes():
    from viewer_publication.archive_model_profile import _definition_hashes
    hashes = _definition_hashes(ROOT)
    assert "packages/viewer_publication/src/viewer_publication/pdf_cover_evidence.py" in hashes
    assert "packages/viewer_publication/src/viewer_publication/body_text_slices.py" in hashes
    for excluded in (
        "packages/congress_api/src/congress_api/retention/body_store.py",
        "packages/congress_api/src/congress_api/retention/r2.py",
        "packages/congress_api/src/congress_api/retention/provenance_inventory.py",
        "packages/viewer_publication/src/viewer_publication/body_text_ssot.py",
        "packages/viewer_publication/src/viewer_publication/body_text_export.py",
    ):
        assert excluded not in hashes


def test_planted_wrong_kind_controls_and_page1_guards_abstain(tmp_path):
    """ct-fk4w: page-2 CRS citations, committee staff memos, committee reports quoting CBO,
    CRS attorney bios without CRS report banners, and support letters citing questionnaires must abstain."""
    def _rec(tag, text, offsets=None):
        return dict(
            body_sha=sha256(tag.encode()).digest(),
            parser="pdf_text",
            parser_version="a" * 64,
            text=text,
            text_sha256=sha256(text.encode()).digest(),
            page_offsets=offsets or [0],
        )

    p1 = "Statement of Jane Witness before the Committee on Energy and Commerce.\n" + ("A" * 300) + "\n\n"
    p2 = "Footnote 4: Congressional Research Service, https://crsreports.congress.gov, R47812.\n"
    page2_crs = _rec("p2-crs", p1 + p2, offsets=[0, len(p1)])

    staff_memo_crs = _rec(
        "staff-memo",
        "To: Subcommittee on Energy and Mineral Resources Members\n"
        "From: Subcommittee Staff\nRe: Hearing Background\n"
        "See Congressional Research Service, https://crsreports.congress.gov, R46762 for background.",
    )
    crs_bio = _rec(
        "crs-bio",
        "Todd Garvey has been a legislative attorney with the American Law Division of the "
        "Congressional Research Service since 2009. He authored report R45123 on executive privilege.",
    )
    committee_rept_cbo = _rec(
        "cmte-rept",
        "108TH CONGRESS REPT. 108-405 HOUSE OF REPRESENTATIVES 1st Session\n"
        "Committed to the Committee of the Whole House on the State of the Union and ordered to be printed.\n"
        "CONGRESSIONAL BUDGET OFFICE COST ESTIMATE\nAs ordered reported by the Committee.",
    )
    support_letter_q = _rec(
        "support-letter",
        "Dear Chairman Grassley and Ranking Member Durbin:\n"
        "Re: Letter in Support of Nominee\n"
        "In her Senate Judiciary Committee Questionnaire, Response to Question 12, she detailed her career.",
    )
    genuine_crs = _rec(
        "genuine-crs",
        "Federal Disaster Assistance After Hurricanes\nUpdated October 14, 2024\n"
        "Congressional Research Service\nhttps://crsreports.congress.gov\nR47812",
    )

    with NativeDatasets.from_config(os.environ["DOCSPEC_JOB_CONFIG"]) as engine:
        path, counts = classify_selected_covers(
            [page2_crs, staff_memo_crs, crs_bio, committee_rept_cbo, support_letter_q, genuine_crs],
            engine=engine,
            work=tmp_path / "controls",
            source_review_sha256="b" * 64,
        )
    assert counts["coverage"] == [dict(inspected=6, classified=1)]
    rows = pq.read_table(path).to_pylist()
    assert len(rows) == 1
    assert rows[0]["body_sha256"] == genuine_crs["body_sha"].hex()
    assert rows[0]["cover_document_kind"] == "crs-report"


