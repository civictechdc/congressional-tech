"""End-to-end promotion of unwrapped WARC/ARC payloads and envelope provenance (ct-ogcq)."""
import gzip
from hashlib import md5, sha256
from io import BytesIO
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pymupdf

from archive_job_fixture import spicy_input
from congress_api.lake import appearance_records as ar_lake, body_text, filenames, meeting_records as mr_lake, readings
from congress_api.lake.capture_staging import stage_captures
from congress_api.retention.provenance import parquet_output, run_job
from docspec_client.client import NativeDatasets
from viewer_publication import body_text_export as export
from viewer_publication.archive_model import build_release


def _pdf_bytes(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=9)
    return doc.tobytes()


def _warc_bytes(target_url: str, content_type: str, payload: bytes) -> bytes:
    header = (
        f"WARC/1.0\r\n"
        f"WARC-Type: response\r\n"
        f"WARC-Target-URI: {target_url}\r\n"
        f"WARC-Date: 2015-04-15T12:00:00Z\r\n"
        f"Content-Type: application/http; msgtype=response\r\n"
    ).encode("ascii")
    http = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(payload)}\r\n"
        f"\r\n"
    ).encode("ascii") + payload
    record = header + f"Content-Length: {len(http)}\r\n\r\n".encode("ascii") + http + b"\r\n\r\n"
    return gzip.compress(record, mtime=0)


def _arc_bytes(target_url: str, content_type: str, payload: bytes) -> bytes:
    http = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(payload)}\r\n"
        f"\r\n"
    ).encode("ascii") + payload
    filedesc = b"filedesc://fixture.arc.gz 0.0.0.0 20061013120000 text/plain 49\n1 0 Alexa/1.0\n\n"
    record = f"{target_url} 0.0.0.0 20061013120000 {content_type} {len(http)}\n".encode("ascii") + http + b"\n"
    return gzip.compress(filedesc + record, mtime=0)


def _store_body(raw, data: bytes, *, gzip_stored: bool = True):
    stored = gzip.compress(data, mtime=0) if gzip_stored else data
    digest = sha256(data).hexdigest()
    suffix = ".gz" if gzip_stored else ""
    rel = f"bodies/sha256/{digest[:2]}/{digest}{suffix}"
    path = raw / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(stored)
    return dict(
        sha256=digest,
        bytes=len(data),
        stored_suffix=suffix,
        stored_bytes=len(stored),
        stored_md5=md5(stored).hexdigest(),
    )


def _listing_html(title: str, n_links: int = 35) -> bytes:
    # Include non-UTF-8 Windows-1252 smart quote inside the first 8 KiB so the enclosing
    # WARC envelope sniffs as 'other', mirroring legacy committee pages in production.
    links = "".join(f'<li><a href="https://example.house.gov/doc-{i}.pdf">Item {i}</a></li>' for i in range(n_links))
    body = f"<html><head><title>{title}</title></head><body><p>Committee\u2019s index</p><ul>{links}</ul></body></html>"
    return body.encode("cp1252")


def test_warc_and_arc_payloads_promote_while_envelopes_stay_traceable(tmp_path):
    raw = tmp_path / "raw"
    pdf_url = "https://science.house.gov/sites/republicans.science.house.gov/files/documents/hearings/012010_Castellani.pdf"
    arc_html_url = "https://waysandmeans.house.gov/Legacy/fullcomm/105cong/fc-34act.htm"
    listing_url = "http://veterans.house.gov/witness-testimony/unpublished-listing"
    rec_listing_url = "http://veterans.house.gov/witness-testimony/alan-ross"
    rec_copy_url = "http://veterans.house.gov/Media/file/111/7-21-10/Rosssubmission.pdf"

    pdf_payload = _pdf_bytes("Statement of Dr. Castellani on federal science policy.")
    # Windows-1252 HTML declared as windows-1252 with \x92 smart quote so the enclosing ARC
    # envelope triggers UnicodeDecodeError in sniff and falls back to format='other'.
    arc_html_payload = (
        '<html><head><meta http-equiv="Content-Type" content="text/html; charset=windows-1252">'
        "<title>Full Committee Hearing on Trade</title></head>"
        "<body><p>Chairman\u2019s opening statement on the trade agreement before the committee. "
        + ("Substantive testimony record. " * 20)
        + "</p></body></html>"
    ).encode("cp1252")
    listing_payload = _listing_html("Unpublished Witness Index")
    rec_listing_payload = _listing_html("Alan Ross Witness Page")
    rec_pdf_payload = _pdf_bytes("Prepared statement of Alan Ross before Veterans Affairs.")

    warc_pdf_env = _warc_bytes(pdf_url, "application/pdf", pdf_payload)
    arc_html_env = _arc_bytes(arc_html_url, "text/html", arc_html_payload)
    warc_listing_env = _warc_bytes(listing_url, "text/html", listing_payload)
    warc_rec_listing_env = _warc_bytes(rec_listing_url, "text/html", rec_listing_payload)

    pdf_stored = _store_body(raw, pdf_payload)
    arc_html_stored = _store_body(raw, arc_html_payload)
    listing_stored = _store_body(raw, listing_payload)
    rec_listing_stored = _store_body(raw, rec_listing_payload)
    rec_pdf_stored = _store_body(raw, rec_pdf_payload)

    warc_pdf_stored = _store_body(raw, warc_pdf_env)
    arc_html_stored_env = _store_body(raw, arc_html_env)
    warc_listing_stored_env = _store_body(raw, warc_listing_env)
    warc_rec_listing_stored_env = _store_body(raw, warc_rec_listing_env)

    def _pair_line(url: str, sib_stored: dict, sib_media: str, env_stored: dict, env_media: str, retrieved_at: str):
        return dict(
            writer=dict(job="fixture", commit="a" * 40),
            run_id="fixture",
            mode="fetch",
            family="documents",
            outcome="stored",
            requested_url=url,
            url=url,
            response_headers={},
            http_status=200,
            complete=True,
            retrieved_at=retrieved_at,
            captures=[
                dict(
                    **sib_stored,
                    family="documents",
                    media_type=sib_media,
                    fidelity="exact-bytes",
                    sniffed_format=None,
                    sniff_version=None,
                    intact=None,
                    context_url=url,
                ),
                dict(
                    **env_stored,
                    family="external/provider-responses",
                    media_type=env_media,
                    fidelity="exact-bytes",
                    sniffed_format=None,
                    sniff_version=None,
                    intact=None,
                    context_url=url,
                ),
            ],
        )

    lines = [
        _pair_line(pdf_url, pdf_stored, "application/pdf", warc_pdf_stored, "application/warc+gzip", "2010-01-20T12:00:00Z"),
        _pair_line(arc_html_url, arc_html_stored, "text/html", arc_html_stored_env, "application/arc+gzip", "2006-10-13T12:00:00Z"),
        _pair_line(listing_url, listing_stored, "text/html", warc_listing_stored_env, "application/warc+gzip", "2011-05-01T12:00:00Z"),
        _pair_line(rec_listing_url, rec_listing_stored, "text/html", warc_rec_listing_stored_env, "application/warc+gzip", "2011-05-02T12:00:00Z"),
        dict(
            writer=dict(job="fixture", commit="a" * 40),
            run_id="fixture-recovery",
            mode="retained_import",
            family="documents",
            outcome="saved",
            requested_url=rec_copy_url,
            url=rec_copy_url,
            response_headers={},
            http_status=200,
            complete=True,
            retrieved_at="2026-10-15T12:00:00Z",
            source_associations=[dict(original_url=rec_listing_url, basis="user_accepted_url_variant")],
            recovery_evidence=dict(
                original_url=rec_listing_url,
                imported_at="2026-10-15T12:00:00Z",
                match_basis="user_accepted_url_variant",
                acquisition=dict(prior_access_category="recovered_document", recovered_url=rec_copy_url, source="user_accepted_recovery"),
            ),
            captures=[
                dict(
                    **rec_pdf_stored,
                    media_type="application/pdf",
                    fidelity="exact-bytes",
                    sniffed_format="pdf",
                    sniff_version=readings.current_version("sniff"),
                    intact=True,
                    context_url=rec_copy_url,
                )
            ],
        ),
    ]

    receipt = raw / "receipts/documents/2026-10-27/slice.jsonl.gz"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    encoded = gzip.compress(("".join(json.dumps(r) + "\n" for r in lines)).encode(), mtime=0)
    receipt.write_bytes(encoded)
    pin = tmp_path / "receipt-pin.json"
    pin.write_text(json.dumps(dict(path=str(receipt), size=len(encoded), sha256=sha256(encoded).hexdigest(), producer="fixture")))

    decisions = tmp_path / "recoveries.jsonl"
    decisions.write_text(json.dumps(dict(
        id="rec-alan-ross",
        body_sha256=rec_pdf_stored["sha256"],
        original_url=rec_listing_url,
        recovered_filename="Rosssubmission.pdf",
        recovered_url=rec_copy_url,
        kind="recovered_document",
        identity_note="Recovered witness testimony PDF",
        decided_at="2026-10-27T12:00:00Z",
        supersedes=None,
        recovery_record_version=2,
    )) + "\n")
    recovery_files = [dict(key="provenance/recoveries/fixture.jsonl", path=str(decisions))]

    engine = NativeDatasets.from_config(os.environ["DOCSPEC_JOB_CONFIG"])
    captures = stage_captures(
        [dict(key=receipt.relative_to(raw).as_posix(), path=str(receipt), qualification=str(pin))],
        engine=engine,
        work=tmp_path / "capture-stage",
    ) / "captures.parquet"

    inventory = tmp_path / "inventory"
    inventory.mkdir()
    run_job(
        inventory,
        engine,
        inputs=[dict(name="captures", kind="parquet", path=str(captures))],
        steps=[],
        outputs=[parquet_output(
            inventory,
            "bodies",
            """SELECT DISTINCT sha256 AS body_sha,
            'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS physical_key,
            'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS relative_path,
            stored_bytes FROM captures WHERE sha256 IS NOT NULL""",
            ["body_sha"],
        )],
    )
    pages = readings.stage_once(
        captures=captures,
        body_inventory=inventory / "bodies.parquet",
        local_root=raw,
        engine=engine,
        work=tmp_path / "reading-stage",
        decided_at="2026-10-27T12:00:00Z",
    )
    names = filenames.stage(
        captures=captures,
        recovery_files=recovery_files,
        engine=engine,
        work=tmp_path / "filename-stage",
        decided_at="2026-10-27T12:00:00Z",
    )

    # Confirm the real sniffer reproduces format='other' on binary/non-UTF8 WARC/ARC envelopes.
    sniff_formats = {
        r["body_sha"].hex(): r["format"]
        for r in pq.read_table(pages["readings"]).to_pylist()
        if r["parser"] == "sniff"
    }
    env_shas = {
        warc_pdf_stored["sha256"],
        arc_html_stored_env["sha256"],
        warc_listing_stored_env["sha256"],
        warc_rec_listing_stored_env["sha256"],
    }
    assert all(sniff_formats[s] == "other" for s in env_shas)

    release_dir = tmp_path / "release"
    model_dir = tmp_path / "model"
    build_release(
        captures=captures,
        readings=pages["readings"],
        filename_readings=names["readings"],
        recovery_files=recovery_files,
        parser_versions={
            **{p: readings.current_version(p) for p in ("sniff", "html", "xml", "json")},
            "meeting_records": mr_lake.current_versions(),
            "appearance_records": ar_lake.current_versions(),
        },
        catalog_version=names["catalog_version"],
        spicy_regs=spicy_input(),
        include_entities=True,
        engine=engine,
        output=release_dir,
        scratch=model_dir,
    )

    # All six admission invariant suites pass with zero violations.
    queries = {q["name"]: q["data"] for q in json.loads((model_dir / "result.json").read_text())["queries"]}
    for suite in ("invariants", "model_invariants", "url_state_invariants", "profile_completeness",
                  "entity_profile_completeness", "relationship_invariants"):
        assert not any(queries[suite][0].values()), (suite, queries[suite])

    detail = pq.read_table(release_dir / "detail.parquet").to_pylist()
    listed = pq.read_table(release_dir / "list.parquet").to_pylist()
    assert len(detail) == len(listed) == 3

    by_body = {r["saved_body"].hex(): (r, l) for r, l in zip(detail, listed)}
    assert set(by_body) == {pdf_stored["sha256"], arc_html_stored["sha256"], rec_pdf_stored["sha256"]}
    assert env_shas.isdisjoint(by_body)

    assert by_body[pdf_stored["sha256"]][1]["format"] == "pdf"
    assert by_body[pdf_stored["sha256"]][0]["saved_media_type"] == "application/pdf"
    assert by_body[arc_html_stored["sha256"]][1]["format"] == "html"
    assert by_body[arc_html_stored["sha256"]][0]["saved_media_type"] == "text/html"
    assert by_body[rec_pdf_stored["sha256"]][1]["format"] == "pdf"
    assert by_body[rec_pdf_stored["sha256"]][1]["saved_kind"] == "recovery"
    assert by_body[rec_pdf_stored["sha256"]][0]["saved_media_type"] == "application/pdf"
    assert all(r["alternates"] == [] for r in detail)

    # Envelopes are classified as 'envelope' / not real files while 1:1 custody in capture_evidence stays intact.
    roles = pq.read_table(model_dir / "evidence/record_roles.parquet").to_pylist()
    env_roles = [r for r in roles if r["sha256"] and r["sha256"].hex() in env_shas]
    assert len(env_roles) == 4
    assert all(r["record_role"] == "envelope" and r["is_real_file"] is False for r in env_roles)

    ce = pq.read_table(model_dir / "evidence/capture_evidence.parquet").to_pylist()
    by_line = {(r["receipt_key"], r["receipt_line"]): {} for r in ce}
    for r in ce:
        by_line[r["receipt_key"], r["receipt_line"]][r["capture_index"]] = r
    assert {by_line[r["receipt_key"], r["receipt_line"]][0]["sha256"].hex() for r in env_roles} == {
        pdf_stored["sha256"],
        arc_html_stored["sha256"],
        listing_stored["sha256"],
        rec_listing_stored["sha256"],
    }

    # body_text_export exports the promoted unwrapped PDF/HTML payloads under saved_body = payload_sha256.
    bt_versions = body_text.current_versions()
    bt_rows = [
        dict(
            body_sha=bytes.fromhex(pdf_stored["sha256"]),
            parser="pdf_text",
            parser_version=bt_versions["pdf_text"],
            text="Statement of Dr. Castellani on federal science policy.",
            page_offsets=[0],
            ocr_pages=[],
            text_sha256=sha256(b"Statement of Dr. Castellani on federal science policy.").digest(),
            macos_build=None,
        ),
        dict(
            body_sha=bytes.fromhex(arc_html_stored["sha256"]),
            parser="html_text",
            parser_version=bt_versions["html_text"],
            text="Chairman\u2019s opening statement on the trade agreement before the committee.",
            page_offsets=[0],
            ocr_pages=[],
            text_sha256=sha256("Chairman\u2019s opening statement on the trade agreement before the committee.".encode()).digest(),
            macos_build=None,
        ),
        dict(
            body_sha=bytes.fromhex(rec_pdf_stored["sha256"]),
            parser="pdf_text",
            parser_version=bt_versions["pdf_text"],
            text="Prepared statement of Alan Ross before Veterans Affairs.",
            page_offsets=[0],
            ocr_pages=[],
            text_sha256=sha256(b"Prepared statement of Alan Ross before Veterans Affairs.").digest(),
            macos_build=None,
        ),
    ]
    bt_path = tmp_path / "body-text.parquet"
    pq.write_table(pa.Table.from_pylist(sorted(bt_rows, key=lambda r: r["body_sha"]), schema=body_text._text_schema()), bt_path)
    pointer = export.export(
        engine=engine,
        work=tmp_path / "bt-export",
        body_text=bt_path,
        detail=release_dir / "detail.parquet",
        release_id="r" * 64,
    )
    exported = {r["saved_body"].hex(): r["text"] for r in pq.read_table(tmp_path / "bt-export/export.parquet").to_pylist()}
    assert set(exported) == {pdf_stored["sha256"], arc_html_stored["sha256"], rec_pdf_stored["sha256"]}
    assert pointer["coverage"]["bodies_with_text"] == {"html_text": 1, "pdf_text": 2}
