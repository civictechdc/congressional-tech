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

from congress_api.retention.body_keys import (
    body_key_digest,
    is_pdf_bytes,
    is_pdf_format,
    physical_body_object_key,
)
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

