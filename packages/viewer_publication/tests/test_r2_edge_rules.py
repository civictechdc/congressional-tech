from __future__ import annotations

import json
from pathlib import Path

import pytest
from congress_api.retention.r2_edge_rules import evaluate_response_headers, evaluate_waf_request
from viewer_publication import apply_r2_edge_rules as edge_cli


def test_plan_and_verify_config_emit_valid_cloudflare_payloads(capsys):
    rc = edge_cli.main(["plan", "--account-id", "acc123", "--zone-id", "zone456"])
    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["custom_domain"]["hostname"] == "congressional-data.spicygov.ai"
    assert plan["custom_domain"]["bucket"] == "congressional-tech-raw"
    steps = {r["step"]: r for r in plan["requests"]}
    assert set(steps) == {
        "r2_bucket_cors",
        "zone_waf_custom_rules",
        "zone_response_header_transform_rules",
    }
    assert steps["r2_bucket_cors"]["url"].endswith("/accounts/acc123/r2/buckets/congressional-tech-raw/cors")
    waf_rules = steps["zone_waf_custom_rules"]["payload"]["rules"]
    assert len(waf_rules) == 1
    assert "/viewer-publications/" in waf_rules[0]["expression"]
    assert "/bodies/sha256/" in waf_rules[0]["expression"]
    assert "/exports/" in waf_rules[0]["expression"]
    transform_rules = {
        r["ref"]: r for r in steps["zone_response_header_transform_rules"]["payload"]["rules"]
    }
    assert "public-r2-security-and-disposition-headers-pdf-filename-disposition" in transform_rules
    assert "public-r2-security-and-disposition-headers-non-pdf-filename-disposition" in transform_rules
    pdf_disp = transform_rules["public-r2-security-and-disposition-headers-pdf-filename-disposition"]
    assert "Content-Disposition" in pdf_disp["action_parameters"]["headers"]
    assert 'inline; filename=\\"' in pdf_disp["action_parameters"]["headers"]["Content-Disposition"]["expression"]
    for forbidden in ('\\"', "\\\\", ";", "/", "..", "\\r", "\\n"):
        assert f'not contains(http.request.uri.args["filename"][0], "{forbidden}")' in pdf_disp["expression"]


def test_apply_executes_all_three_cloudflare_api_mutations(capsys):
    calls: list[tuple[str, str, dict, dict]] = []

    def mock_transport(method, url, headers, payload):
        calls.append((method, url, dict(headers), dict(payload or {})))
        return {"success": True, "result": {"id": "ruleset-1"}}

    rc = edge_cli.main(
        [
            "apply",
            "--api-token",
            "cf-secret-token",
            "--account-id",
            "174055408ff1560e60601c4d12c561c4",
            "--zone-id",
            "zone999",
        ],
        transport=mock_transport,
    )
    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "applied"
    assert len(calls) == 3
    assert all(hdrs["Authorization"] == "Bearer cf-secret-token" for _, _, hdrs, _ in calls)


def test_verify_live_validates_waf_blocks_cors_cache_and_pdf_disposition(capsys):
    sample_sha = "12" + "34" * 31
    pdf_path = f"/bodies/sha256/12/{sample_sha}.pdf"

    def simulated_edge_probe(method, url, headers):
        waf = evaluate_waf_request(method, url)
        if not waf["allowed"]:
            return waf["status_code"], {}
        content_type = "application/pdf" if ".pdf" in url else "application/json"
        resp_headers = evaluate_response_headers(url, content_type=content_type)
        status = 206 if headers and "Range" in headers and ".pdf" in url else 200
        return status, resp_headers

    rc = edge_cli.main(
        [
            "verify-live",
            "--base-url",
            "https://congressional-data.spicygov.ai",
            "--pdf-path",
            pdf_path,
        ],
        http_probe=simulated_edge_probe,
    )
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "verified"
    check_names = {c["check"] for c in report["checks"]}
    assert "block:GET:/warehouse/test.parquet" in check_names
    assert "allow:GET:/viewer-publications/manifest.json" in check_names
    assert f"allow:GET:{pdf_path}" in check_names


def test_verify_live_fails_when_blocked_prefix_is_exposed():
    def leaky_probe(method, url, headers):
        return 200, {}

    with pytest.raises(ValueError, match="Expected 403"):
        edge_cli.verify_live_edge(
            "https://congressional-data.spicygov.ai",
            http_probe=leaky_probe,
        )
