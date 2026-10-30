"""Tests for single-bucket public R2 edge rules, uncompressed PDF storage, and deferred-body SHA-256 exclusion gate (ct-te1p)."""

import base64
import gzip
import hashlib
from io import BytesIO
from pathlib import Path
import zipfile

import boto3
from botocore.config import Config
from botocore.stub import ANY, Stubber
import pytest

from congress_api.retention.body_files import retain_body_file
from congress_api.retention.body_keys import (
    body_key_digest,
    is_pdf_bytes,
    is_pdf_format,
    physical_body_object_key,
    quarantine_body_key,
)
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.document_evidence import read_retained_body
from congress_api.retention.r2 import PDF_CACHE_CONTROL, R2Store, put_parameters
from congress_api.retention.r2_edge_rules import (
    PUBLIC_BUCKET,
    PUBLIC_HOSTNAME,
    build_declarative_ruleset_spec,
    evaluate_response_headers,
    format_content_disposition,
    load_edge_config,
)
from viewer_publication.apply_r2_edge_rules import validate_edge_config, verify_live_edge
from congress_api.retention.raw_archive import body_payload
from congress_api.retention.raw_storage import (
    DEFAULT_ACCEPTED_FILES_PATH,
    ExcludedBodyError,
    enforce_body_ingest_gate,
    load_excluded_body_hashes,
    migrate_pdf_bodies_to_uncompressed,
    store_public_body,
)


def _s3_client():
    return boto3.session.Session().client(
        "s3",
        region_name="auto",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=Config(retries={"total_max_attempts": 1, "mode": "standard"}),
    )


def test_logical_body_key_is_immutable_while_physical_key_splits_pdf_vs_gzip():
    pdf_bytes = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"
    xml_bytes = b"<?xml version='1.0'?><witness-list/>"
    pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()
    xml_sha = hashlib.sha256(xml_bytes).hexdigest()

    _, pdf_info = body_payload(pdf_bytes)
    _, xml_info = body_payload(xml_bytes)

    # Logical row["body_key"] is always bodies/sha256/<xx>/<sha256>.gz
    assert pdf_info["body_key"] == f"bodies/sha256/{pdf_sha[:2]}/{pdf_sha}.gz"
    assert xml_info["body_key"] == f"bodies/sha256/{xml_sha[:2]}/{xml_sha}.gz"
    assert body_key_digest(pdf_info["body_key"]) == pdf_sha

    # Physical object keys map PDFs to .pdf and non-PDFs to .gz without mutating logical body_key
    assert is_pdf_bytes(pdf_bytes) is True
    assert is_pdf_bytes(xml_bytes) is False
    assert is_pdf_format("pdf") is True
    assert is_pdf_format("application/pdf; charset=binary") is True
    assert is_pdf_format(["xml"]) is False

    assert (
        physical_body_object_key(pdf_info["body_key"], is_pdf=True)
        == f"bodies/sha256/{pdf_sha[:2]}/{pdf_sha}.pdf"
    )
    assert (
        physical_body_object_key(pdf_info["body_key"], "application/pdf")
        == f"bodies/sha256/{pdf_sha[:2]}/{pdf_sha}.pdf"
    )
    assert (
        physical_body_object_key(xml_info["body_key"], "application/xml")
        == f"bodies/sha256/{xml_sha[:2]}/{xml_sha}.gz"
    )


def test_r2_put_pdf_body_and_file_set_inline_pdf_and_immutable_cache_headers(tmp_path):
    pdf_bytes = b"%PDF-1.5\n%test-pdf-body\n"
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    logical_key = f"bodies/sha256/{sha[:2]}/{sha}.gz"
    physical_pdf_key = f"bodies/sha256/{sha[:2]}/{sha}.pdf"
    md5_hex = hashlib.md5(pdf_bytes).hexdigest()
    md5_b64 = base64.b64encode(hashlib.md5(pdf_bytes).digest()).decode()

    params = put_parameters(PUBLIC_BUCKET, physical_pdf_key, pdf_bytes, IfNoneMatch="*")
    assert params["ContentType"] == "application/pdf"
    assert params["ContentDisposition"] == "inline"
    assert params["CacheControl"] == PDF_CACHE_CONTROL
    assert params["IfNoneMatch"] == "*"

    client = _s3_client()
    store = R2Store(client, PUBLIC_BUCKET)
    with Stubber(client) as stubber:
        stubber.add_response(
            "put_object",
            {"ETag": f'"{md5_hex}"'},
            {
                "Bucket": PUBLIC_BUCKET,
                "Key": physical_pdf_key,
                "Body": pdf_bytes,
                "ContentMD5": md5_b64,
                "ContentType": "application/pdf",
                "ContentDisposition": "inline",
                "CacheControl": PDF_CACHE_CONTROL,
                "IfNoneMatch": "*",
            },
        )
        assert store.put_pdf_body(logical_key, pdf_bytes) is True

        pdf_file = tmp_path / "sample.pdf"
        pdf_file.write_bytes(pdf_bytes)
        stubber.add_response(
            "put_object",
            {"ETag": f'"{md5_hex}"'},
            {
                "Bucket": PUBLIC_BUCKET,
                "Key": physical_pdf_key,
                "Body": ANY,
                "ContentLength": len(pdf_bytes),
                "ContentMD5": md5_b64,
                "ContentType": "application/pdf",
                "ContentDisposition": "inline",
                "CacheControl": PDF_CACHE_CONTROL,
                "IfNoneMatch": "*",
            },
        )
        assert store.put_pdf_file(logical_key, pdf_file) is True


def test_store_public_body_and_resumable_pdf_migration_including_zip_members(tmp_path):
    store = LocalStore(tmp_path / "r2")
    pdf_bytes = b"%PDF-1.4\n% Direct PDF document\n%%EOF\n"
    html_bytes = b"<!doctype html><html><body>Hearing notice</body></html>"
    zip_member_pdf = b"%PDF-1.6\n% Extracted from ZIP bundle\n%%EOF\n"

    pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()
    html_sha = hashlib.sha256(html_bytes).hexdigest()
    member_sha = hashlib.sha256(zip_member_pdf).hexdigest()

    # 1. Direct public body write stores .pdf uncompressed and non-PDF as .gz while keeping logical .gz key
    pdf_meta = store_public_body(store, pdf_bytes, content_type_or_format="application/pdf")
    assert pdf_meta["body_key"] == f"bodies/sha256/{pdf_sha[:2]}/{pdf_sha}.gz"
    assert pdf_meta["physical_key"] == f"bodies/sha256/{pdf_sha[:2]}/{pdf_sha}.pdf"
    assert store.read(pdf_meta["physical_key"]) == pdf_bytes
    assert store.read(pdf_meta["body_key"]) is None

    html_meta = store_public_body(store, html_bytes, content_type_or_format="text/html")
    assert html_meta["body_key"] == f"bodies/sha256/{html_sha[:2]}/{html_sha}.gz"
    assert html_meta["physical_key"] == html_meta["body_key"]
    assert gzip.decompress(store.read(html_meta["physical_key"])) == html_bytes

    # Transparent read fallback reads uncompressed .pdf via logical .gz key
    assert read_retained_body(store.root, pdf_meta["body_key"]) == pdf_bytes
    assert read_retained_body(store.root, pdf_meta["body_key"], read_compressed=store.read) == pdf_bytes
    assert read_retained_body(store.root, html_meta["body_key"]) == html_bytes

    # 2. Seed legacy .gz PDF and a .gz ZIP containing a PDF member for migration
    legacy_pdf_bytes = b"%PDF-1.3\n% Legacy gzipped PDF\n%%EOF\n"
    legacy_pdf_sha = hashlib.sha256(legacy_pdf_bytes).hexdigest()
    legacy_pdf_gz_key = f"bodies/sha256/{legacy_pdf_sha[:2]}/{legacy_pdf_sha}.gz"
    store.put(legacy_pdf_gz_key, gzip.compress(legacy_pdf_bytes, mtime=0), immutable=True)

    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("submittal/witness-statement.pdf", zip_member_pdf)
        zf.writestr("submittal/notes.txt", b"Plain text attachment")
    zip_bytes = zip_buf.getvalue()
    zip_sha = hashlib.sha256(zip_bytes).hexdigest()
    zip_gz_key = f"bodies/sha256/{zip_sha[:2]}/{zip_sha}.gz"
    store.put(zip_gz_key, gzip.compress(zip_bytes, mtime=0), immutable=True)

    first_run = migrate_pdf_bodies_to_uncompressed(store)
    expected_legacy_pdf_key = f"bodies/sha256/{legacy_pdf_sha[:2]}/{legacy_pdf_sha}.pdf"
    expected_member_pdf_key = f"bodies/sha256/{member_sha[:2]}/{member_sha}.pdf"

    assert expected_legacy_pdf_key in first_run["migrated_pdfs"]
    assert expected_member_pdf_key in first_run["migrated_zip_member_pdfs"]
    assert store.read(expected_legacy_pdf_key) == legacy_pdf_bytes
    assert store.read(expected_member_pdf_key) == zip_member_pdf
    assert html_meta["body_key"] in first_run["skipped_non_pdf"]

    # Second run is idempotent and skips already-present .pdf objects
    second_run = migrate_pdf_bodies_to_uncompressed(store)
    assert second_run["migrated_pdfs"] == []
    assert expected_legacy_pdf_key in second_run["already_present"]


def test_deferred_body_sha256_exclusion_gate_blocks_and_quarantines(tmp_path):
    accepted_files_path = tmp_path / "accepted-files.json"
    blocked_pdf = b"%PDF-1.7\n% Excluded witness draft\n"
    blocked_sha = hashlib.sha256(blocked_pdf).hexdigest()
    zip_member_sha = "20ce208ea9c9dc9f776c79c5eb74f7f67a32f9de422645d43d7d153eb57be840"
    accepted_sha = "0173cecd70e9fa3e5c57941f96ba382524c2a21b9d725b0b6e416bc03f03cd33"

    accepted_files_path.write_text(
        '{\n'
        '  "files": [\n'
        f'    {{"url": "https://example.gov/excluded.pdf", "sha256": "{blocked_sha}", "decision": "exclude",\n'
        f'     "zip_Check": {{"members": [{{"sha256": "{zip_member_sha}", "decision": "exclude"}}]}}}},\n'
        f'    {{"url": "https://example.gov/accepted.pdf", "sha256": "{accepted_sha}", "decision": "accept"}}\n'
        '  ]\n'
        '}\n',
        encoding="utf-8",
    )

    excluded_hashes = load_excluded_body_hashes(accepted_files_path)
    assert blocked_sha in excluded_hashes
    assert zip_member_sha in excluded_hashes
    assert accepted_sha not in excluded_hashes

    # Also test the flat list format used by --deferred accepted-files.json in corpus recovery
    flat_deferred_path = tmp_path / "deferred-list.json"
    flat_deferred_path.write_text(
        f'[{{"url": "https://example.gov/excluded.pdf", "sha256": "{blocked_sha}", "body_key": "bodies/sha256/{blocked_sha[:2]}/{blocked_sha}.gz"}}]',
        encoding="utf-8",
    )
    assert blocked_sha in load_excluded_body_hashes(flat_deferred_path)

    store = LocalStore(tmp_path / "archive", excluded_body_hashes=excluded_hashes)
    public_pdf_key = f"bodies/sha256/{blocked_sha[:2]}/{blocked_sha}.pdf"
    public_gz_key = f"bodies/sha256/{blocked_sha[:2]}/{blocked_sha}.gz"
    expected_quarantine_key = quarantine_body_key(blocked_sha, is_pdf=True)

    with pytest.raises(ExcludedBodyError) as exc_info:
        store_public_body(store, blocked_pdf, content_type_or_format="application/pdf")

    assert exc_info.value.sha256 == blocked_sha
    assert exc_info.value.quarantine_key == expected_quarantine_key
    assert store.read(public_pdf_key) is None
    assert store.read(public_gz_key) is None
    assert store.read(expected_quarantine_key) == blocked_pdf

    # Also verify retain_body_file enforces the exclusion gate
    blocked_file = tmp_path / "blocked.pdf"
    blocked_file.write_bytes(blocked_pdf)
    with pytest.raises(ExcludedBodyError):
        retain_body_file(store, blocked_file, tmp_path / "scratch.gz")


def test_cloudflare_r2_custom_domain_waf_and_transform_rules():
    cfg = load_edge_config()
    assert cfg["custom_domain"]["hostname"] == PUBLIC_HOSTNAME
    assert cfg["custom_domain"]["bucket"] == PUBLIC_BUCKET
    assert cfg["custom_domain"]["retired_worker"] == "congressional-viewer-data"
    assert "waf_custom_rules" not in cfg
    transform = cfg["response_header_transform_rules"][0]
    assert transform["allowed_prefixes"] == [
        "/viewer-publications/",
        "/bodies/sha256/",
        "/exports/",
    ]
    spec = build_declarative_ruleset_spec(cfg)
    assert validate_edge_config(cfg) == spec
    assert spec["cloudflare_ruleset"]["phase"] == "http_response_headers_transform"
    rules_by_ref = {r["ref"]: r for r in spec["cloudflare_ruleset"]["rules"]}
    assert set(rules_by_ref) == {
        "public-r2-security-and-disposition-headers-base-and-immutable-cache",
        "public-r2-security-and-disposition-headers-mutable-manifests-no-store",
        "public-r2-security-and-disposition-headers-non-pdf-csp-and-disposition",
        "public-r2-security-and-disposition-headers-pdf-filename-disposition",
        "public-r2-security-and-disposition-headers-non-pdf-filename-disposition",
    }
    pdf_disp = rules_by_ref["public-r2-security-and-disposition-headers-pdf-filename-disposition"]
    for forbidden in ('\\"', "\\\\", ";", "/", "..", "\\r", "\\n"):
        assert f'not contains(http.request.uri.args["filename"][0], "{forbidden}")' in pdf_disp["expression"]

    sha = "ab" * 32
    release = "cd" * 16

    # Response Header Transform Rules: PDF omits sandbox CSP and sets inline Content-Disposition
    pdf_headers = evaluate_response_headers(
        f"https://{PUBLIC_HOSTNAME}/bodies/sha256/ab/{sha}.pdf?filename=Hearing%20%231.pdf"
    )
    assert "Content-Security-Policy" not in pdf_headers
    assert pdf_headers["Content-Type"] == "application/pdf"
    assert pdf_headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert pdf_headers["Content-Disposition"] == (
        "inline; filename=\"Hearing #1.pdf\"; filename*=UTF-8''Hearing%20%231.pdf"
    )
    assert pdf_headers["Access-Control-Allow-Origin"] == "*"
    assert pdf_headers["Access-Control-Allow-Methods"] == "GET, HEAD, OPTIONS"

    # Non-PDF body gets sandbox CSP and attachment Content-Disposition
    gz_headers = evaluate_response_headers(
        f"https://{PUBLIC_HOSTNAME}/bodies/sha256/ab/{sha}.gz?filename=witnesses.xml"
    )
    assert gz_headers["Content-Security-Policy"] == "sandbox; default-src 'none'"
    assert gz_headers["Content-Disposition"] == (
        "attachment; filename=\"witnesses.xml\"; filename*=UTF-8''witnesses.xml"
    )
    assert format_content_disposition("inline", "../traversal.pdf") == "inline"

    # /exports/* response headers: no-store on mutable manifest pointer, immutable on release Parquet
    export_manifest_headers = evaluate_response_headers(
        f"https://{PUBLIC_HOSTNAME}/exports/manifest.json"
    )
    assert export_manifest_headers["Access-Control-Allow-Origin"] == "*"
    assert export_manifest_headers["Cache-Control"] == "no-store"
    assert export_manifest_headers["Content-Type"] == "application/json; charset=utf-8"
    assert export_manifest_headers["Content-Security-Policy"] == "sandbox; default-src 'none'"

    export_parquet_headers = evaluate_response_headers(
        f"https://{PUBLIC_HOSTNAME}/exports/releases/{release}/committee-meetings.parquet"
    )
    assert export_parquet_headers["Access-Control-Allow-Origin"] == "*"
    assert export_parquet_headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert export_parquet_headers["Content-Type"] == "application/vnd.apache.parquet"
    assert export_parquet_headers["Content-Security-Policy"] == "sandbox; default-src 'none'"

    # Live-edge check validates CORS, Cache-Control, CSP, and ?filename= without legacy WAF path blocks
    pdf_path = f"/bodies/sha256/ab/{sha}.pdf"

    def simulated_edge_probe(method, url, headers):
        ctype = "application/pdf" if ".pdf" in url else "application/json"
        resp_headers = evaluate_response_headers(url, content_type=ctype)
        status = 206 if headers and "Range" in headers and ".pdf" in url else 200
        return status, resp_headers

    live_report = verify_live_edge(
        f"https://{PUBLIC_HOSTNAME}",
        pdf_path=pdf_path,
        http_probe=simulated_edge_probe,
    )
    assert live_report["status"] == "verified"
    assert {c["check"] for c in live_report["checks"]} == {
        "allow:GET:/viewer-publications/manifest.json",
        f"allow:GET:{pdf_path}",
    }


def test_senate_seed_fetch_detects_pdf_magic_and_stores_cas_pdf(tmp_path):
    from congress_api.retention.senate import cached_html_path, seed_fetch
    url = "https://www.senate.gov/isvp/hearing.pdf"
    cache_path = cached_html_path(tmp_path, url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_content = b"%PDF-1.4\n%Binary stream\n%%EOF"
    cache_path.write_bytes(pdf_content)

    result = seed_fetch(tmp_path, url)
    assert result == ""
    digest = hashlib.sha256(pdf_content).hexdigest()
    cas_pdf = tmp_path / "bodies" / "sha256" / digest[:2] / f"{digest}.pdf"
    assert cas_pdf.is_file()
    assert cas_pdf.read_bytes() == pdf_content


def test_senate_seed_fetch_detects_corrupt_replacement_characters_and_stores_cas_pdf(tmp_path):
    from congress_api.retention.senate import cached_html_path, seed_fetch
    url = "https://www.senate.gov/isvp/corrupt_binary.html"
    cache_path = cached_html_path(tmp_path, url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    # Binary with high invalid byte count, resulting in > 5% U+FFFD characters
    binary_content = b"<html>" + (b"\xff\xfe\x80\x81\x82\x83" * 50) + b"</html>"
    cache_path.write_bytes(binary_content)

    result = seed_fetch(tmp_path, url)
    assert result == ""
    digest = hashlib.sha256(binary_content).hexdigest()
    cas_pdf = tmp_path / "bodies" / "sha256" / digest[:2] / f"{digest}.pdf"
    assert cas_pdf.is_file()
    assert cas_pdf.read_bytes() == binary_content


def test_senate_seed_fetch_preserves_valid_text_html(tmp_path):
    from congress_api.retention.senate import cached_html_path, seed_fetch
    url = "https://www.senate.gov/isvp/valid.html"
    cache_path = cached_html_path(tmp_path, url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    html_content = "<html><body><h1>Senate Committee Hearing</h1></body></html>"
    cache_path.write_bytes(html_content.encode("utf-8"))

    result = seed_fetch(tmp_path, url)
    assert result == html_content
    assert not (tmp_path / "bodies").exists()

