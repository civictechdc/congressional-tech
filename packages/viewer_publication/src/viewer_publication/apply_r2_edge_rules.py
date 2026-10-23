"""Plan, apply, and verify Cloudflare R2 Custom Domain, CORS, WAF, and Response Header Transform Rules.

Supports:
  - ``plan`` / ``verify-config``: Validate ``infra/cloudflare/congressional-data-r2-edge.json`` and emit exact Cloudflare API payloads.
  - ``apply``: Apply R2 bucket CORS, ``http_request_firewall_custom``, and ``http_response_headers_transform`` rulesets via Cloudflare REST API v4.
  - ``verify-live``: Probe allowed and blocked paths on ``https://congressional-data.spicygov.ai`` and verify status codes, CORS, Cache-Control, CSP, and Content-Disposition headers.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import sys
from typing import Any
import urllib.error
import urllib.request

from congress_api.retention.r2_edge_rules import (
    DEFAULT_EDGE_CONFIG_PATH,
    evaluate_response_headers,
    evaluate_waf_request,
    load_edge_config,
)

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"


def validate_edge_config(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate the declarative edge configuration structure and policy invariants."""
    cfg = dict(config or load_edge_config())
    if cfg.get("version") != 1:
        raise ValueError(f"Unsupported edge config version: {cfg.get('version')!r}")
    domain = cfg.get("custom_domain") or {}
    if not domain.get("hostname") or not domain.get("bucket"):
        raise ValueError("custom_domain requires hostname and bucket")
    cors_rules = (cfg.get("cors") or {}).get("rules") or []
    if not cors_rules:
        raise ValueError("cors.rules must contain at least one rule")
    waf_rules = cfg.get("waf_custom_rules") or []
    if not waf_rules or not waf_rules[0].get("expression"):
        raise ValueError("waf_custom_rules must contain an expression")
    transform_rules = cfg.get("response_header_transform_rules") or []
    if not transform_rules:
        raise ValueError("response_header_transform_rules must contain at least one rule")

    # Verify simulated WAF and response header behavior against canonical paths
    sample_sha = "ab" + "cd" * 31
    allowed_checks = [
        ("GET", f"https://{domain['hostname']}/viewer-publications/manifest.json"),
        ("HEAD", f"https://{domain['hostname']}/exports/manifest.json"),
        ("OPTIONS", f"https://{domain['hostname']}/bodies/sha256/ab/{sample_sha}.pdf"),
    ]
    for method, url in allowed_checks:
        res = evaluate_waf_request(method, url, config=cfg)
        if not res.get("allowed"):
            raise ValueError(f"Config validation failed: expected allowed for {method} {url}, got {res}")

    blocked_checks = [
        ("GET", f"https://{domain['hostname']}/warehouse/table.parquet"),
        ("GET", f"https://{domain['hostname']}/receipts/run.json"),
        ("GET", f"https://{domain['hostname']}/quarantine/bodies/sha256/ab/{sample_sha}.pdf"),
        ("GET", f"https://{domain['hostname']}/indexes/raw.json"),
        ("GET", f"https://{domain['hostname']}/viewer-publications/accepted-files.json"),
        ("POST", f"https://{domain['hostname']}/viewer-publications/manifest.json"),
    ]
    for method, url in blocked_checks:
        res = evaluate_waf_request(method, url, config=cfg)
        if res.get("allowed") or res.get("status_code") != 403:
            raise ValueError(f"Config validation failed: expected 403 block for {method} {url}, got {res}")

    pdf_headers = evaluate_response_headers(
        f"https://{domain['hostname']}/bodies/sha256/ab/{sample_sha}.pdf?filename=hearing.pdf",
        content_type="application/pdf",
        config=cfg,
    )
    if "Content-Security-Policy" in pdf_headers:
        raise ValueError("PDF responses must omit sandbox Content-Security-Policy")
    if not pdf_headers.get("Content-Disposition", "").startswith('inline; filename="hearing.pdf"'):
        raise ValueError(f"Unexpected PDF Content-Disposition: {pdf_headers.get('Content-Disposition')!r}")

    json_headers = evaluate_response_headers(
        f"https://{domain['hostname']}/viewer-publications/manifest.json",
        content_type="application/json",
        config=cfg,
    )
    if json_headers.get("Cache-Control") != "no-store":
        raise ValueError("Manifest responses must use Cache-Control: no-store")
    if json_headers.get("Content-Security-Policy") != "sandbox; default-src 'none'":
        raise ValueError("Non-PDF responses must include sandbox Content-Security-Policy")

    return cfg


def build_cloudflare_plan(
    config: Mapping[str, Any] | None = None,
    *,
    account_id: str = "<ACCOUNT_ID>",
    zone_id: str = "<ZONE_ID>",
) -> dict[str, Any]:
    """Build the exact Cloudflare REST API v4 payloads for R2 CORS, WAF, and Response Header Transform rules."""
    cfg = validate_edge_config(config)
    hostname = cfg["custom_domain"]["hostname"]
    bucket = cfg["custom_domain"]["bucket"]
    waf_rule = cfg["waf_custom_rules"][0]
    transform = cfg["response_header_transform_rules"][0]
    immutable_prefixes = transform["cache_control"]["immutable_prefixes"]
    no_store_paths = transform["cache_control"]["no_store_paths"]

    immutable_or = " or ".join(
        f'starts_with(http.request.uri.path, "{prefix}")' for prefix in immutable_prefixes
    )
    no_store_or = " or ".join(
        f'http.request.uri.path eq "{path}"' for path in no_store_paths
    )
    public_prefix_or = " or ".join(
        f'starts_with(http.request.uri.path, "{prefix}")'
        for prefix in waf_rule["allowed_prefixes"]
    )

    cors_payload = {"rules": cfg["cors"]["rules"]}
    waf_payload = {
        "name": f"{hostname} R2 public prefix allowlist",
        "description": waf_rule["description"],
        "kind": "zone",
        "phase": "http_request_firewall_custom",
        "rules": [
            {
                "ref": waf_rule["id"],
                "description": waf_rule["description"],
                "expression": waf_rule["expression"],
                "action": waf_rule["action"],
                "enabled": True,
            }
        ],
    }
    response_headers_payload = {
        "name": f"{hostname} R2 response headers",
        "description": transform["description"],
        "kind": "zone",
        "phase": "http_response_headers_transform",
        "rules": [
            {
                "ref": f"{transform['id']}-base-and-immutable-cache",
                "description": "Set nosniff, Referrer-Policy, and immutable Cache-Control on content-addressed R2 objects",
                "expression": f'(http.host eq "{hostname}") and ({immutable_or})',
                "action": "rewrite",
                "action_parameters": {
                    "headers": {
                        "X-Content-Type-Options": {"operation": "set", "value": "nosniff"},
                        "Referrer-Policy": {"operation": "set", "value": "no-referrer"},
                        "Cache-Control": {
                            "operation": "set",
                            "value": "public, max-age=31536000, immutable",
                        },
                    }
                },
                "enabled": True,
            },
            {
                "ref": f"{transform['id']}-mutable-manifests-no-store",
                "description": "Set nosniff, Referrer-Policy, sandbox CSP, and Cache-Control: no-store on top-level manifest selectors",
                "expression": (
                    f'(http.host eq "{hostname}") and ({no_store_or} or '
                    f'ends_with(http.request.uri.path, "/recovery-status.json"))'
                ),
                "action": "rewrite",
                "action_parameters": {
                    "headers": {
                        "X-Content-Type-Options": {"operation": "set", "value": "nosniff"},
                        "Referrer-Policy": {"operation": "set", "value": "no-referrer"},
                        "Content-Security-Policy": {
                            "operation": "set",
                            "value": transform["conditional_csp"]["value"],
                        },
                        "Cache-Control": {"operation": "set", "value": "no-store"},
                    }
                },
                "enabled": True,
            },
            {
                "ref": f"{transform['id']}-non-pdf-csp-and-disposition",
                "description": "Set sandbox CSP on non-PDF responses",
                "expression": (
                    f'(http.host eq "{hostname}") and ({public_prefix_or}) and '
                    f'not starts_with(lower(http.response.content_type.media_type), "application/pdf")'
                ),
                "action": "rewrite",
                "action_parameters": {
                    "headers": {
                        "Content-Security-Policy": {
                            "operation": "set",
                            "value": transform["conditional_csp"]["value"],
                        }
                    }
                },
                "enabled": True,
            },
            {
                "ref": f"{transform['id']}-pdf-filename-disposition",
                "description": "Set inline RFC 6266 Content-Disposition from ?filename= on PDF bodies",
                "expression": (
                    f'(http.host eq "{hostname}") and '
                    f'starts_with(http.request.uri.path, "{transform["filename_disposition"]["path_prefix"]}") and '
                    f'len(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"]) > 0 and '
                    f'len(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0]) <= 128 and '
                    f'not contains(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], "\\"") and '
                    f'not contains(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], "\\\\") and '
                    f'not contains(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], ";") and '
                    f'not contains(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], "/") and '
                    f'not contains(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], "..") and '
                    f'not contains(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], "\\r") and '
                    f'not contains(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], "\\n") and '
                    f'starts_with(lower(http.response.content_type.media_type), "application/pdf")'
                ),
                "action": "rewrite",
                "action_parameters": {
                    "headers": {
                        "Content-Disposition": {
                            "operation": "set",
                            "expression": (
                                f'concat("{transform["filename_disposition"]["pdf_disposition"]}; filename=\\"", '
                                f'http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], "\\"")'
                            ),
                        }
                    }
                },
                "enabled": True,
            },
            {
                "ref": f"{transform['id']}-non-pdf-filename-disposition",
                "description": "Set attachment RFC 6266 Content-Disposition from ?filename= on non-PDF bodies",
                "expression": (
                    f'(http.host eq "{hostname}") and '
                    f'starts_with(http.request.uri.path, "{transform["filename_disposition"]["path_prefix"]}") and '
                    f'len(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"]) > 0 and '
                    f'len(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0]) <= 128 and '
                    f'not contains(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], "\\"") and '
                    f'not contains(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], "\\\\") and '
                    f'not contains(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], ";") and '
                    f'not contains(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], "/") and '
                    f'not contains(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], "..") and '
                    f'not contains(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], "\\r") and '
                    f'not contains(http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], "\\n") and '
                    f'not starts_with(lower(http.response.content_type.media_type), "application/pdf")'
                ),
                "action": "rewrite",
                "action_parameters": {
                    "headers": {
                        "Content-Disposition": {
                            "operation": "set",
                            "expression": (
                                f'concat("{transform["filename_disposition"]["non_pdf_disposition"]}; filename=\\"", '
                                f'http.request.uri.args["{transform["filename_disposition"]["query_param"]}"][0], "\\"")'
                            ),
                        }
                    }
                },
                "enabled": True,
            },
        ],
    }

    return {
        "version": 1,
        "custom_domain": cfg["custom_domain"],
        "requests": [
            {
                "step": "r2_bucket_cors",
                "method": "PUT",
                "url": f"{CLOUDFLARE_API_BASE}/accounts/{account_id}/r2/buckets/{bucket}/cors",
                "payload": cors_payload,
            },
            {
                "step": "zone_waf_custom_rules",
                "method": "PUT",
                "url": f"{CLOUDFLARE_API_BASE}/zones/{zone_id}/rulesets/phases/http_request_firewall_custom/entrypoint",
                "payload": waf_payload,
            },
            {
                "step": "zone_response_header_transform_rules",
                "method": "PUT",
                "url": f"{CLOUDFLARE_API_BASE}/zones/{zone_id}/rulesets/phases/http_response_headers_transform/entrypoint",
                "payload": response_headers_payload,
            },
        ],
    }


def _default_api_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=dict(headers), method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def apply_cloudflare_plan(
    config: Mapping[str, Any] | None = None,
    *,
    api_token: str,
    account_id: str,
    zone_id: str,
    transport: Callable[[str, str, Mapping[str, str], Mapping[str, Any] | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply the R2 CORS policy, WAF custom ruleset, and response header transform ruleset via Cloudflare API."""
    if not api_token or not account_id or not zone_id:
        raise ValueError("CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, and CLOUDFLARE_ZONE_ID are required for apply")
    plan = build_cloudflare_plan(config, account_id=account_id, zone_id=zone_id)
    send = transport or _default_api_transport
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    results = []
    for req in plan["requests"]:
        response = send(req["method"], req["url"], headers, req["payload"])
        if not response.get("success", False):
            raise RuntimeError(f"Cloudflare API step {req['step']} failed: {response.get('errors')}")
        results.append({"step": req["step"], "method": req["method"], "url": req["url"], "success": True})
    return {
        "status": "applied",
        "custom_domain": plan["custom_domain"],
        "steps": results,
    }


def _default_http_probe(
    method: str,
    url: str,
    headers: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, str]]:
    req = urllib.request.Request(url, headers=dict(headers or {}), method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as err:
        return err.code, {k.lower(): v for k, v in (err.headers.items() if err.headers else ())}


def verify_live_edge(
    base_url: str = "https://congressional-data.spicygov.ai",
    *,
    pdf_path: str | None = None,
    http_probe: Callable[[str, str, Mapping[str, str] | None], tuple[int, Mapping[str, str]]] | None = None,
) -> dict[str, Any]:
    """Probe live or simulated edge endpoints to verify WAF blocking, CORS, Cache-Control, CSP, and Content-Disposition."""
    base = base_url.rstrip("/")
    probe = http_probe or _default_http_probe
    checks: list[dict[str, Any]] = []

    # 1. Blocked prefixes and methods must return 403
    for method, path in (
        ("GET", "/warehouse/test.parquet"),
        ("GET", "/receipts/test.json"),
        ("GET", "/quarantine/test.pdf"),
        ("GET", "/indexes/raw.json"),
        ("GET", "/viewer-publications/accepted-files.json"),
        ("POST", "/viewer-publications/manifest.json"),
    ):
        status, _ = probe(method, f"{base}{path}", None)
        if status != 403:
            raise ValueError(f"Expected 403 on {method} {path}, got {status}")
        checks.append({"check": f"block:{method}:{path}", "status": status})

    # 2. Allowed manifest endpoint must return 200 with CORS, nosniff, no-store, and sandbox CSP
    manifest_status, manifest_headers = probe(
        "GET",
        f"{base}/viewer-publications/manifest.json",
        {"Origin": "https://congressional-tech.spicygov.ai"},
    )
    lower_headers = {k.lower(): v for k, v in manifest_headers.items()}
    if manifest_status != 200:
        raise ValueError(f"Expected 200 on /viewer-publications/manifest.json, got {manifest_status}")
    if lower_headers.get("access-control-allow-origin") != "*":
        raise ValueError("Missing Access-Control-Allow-Origin: * on manifest.json")
    if lower_headers.get("x-content-type-options") != "nosniff":
        raise ValueError("Missing X-Content-Type-Options: nosniff on manifest.json")
    if "no-store" not in (lower_headers.get("cache-control") or ""):
        raise ValueError(f"Expected Cache-Control: no-store on manifest.json, got {lower_headers.get('cache-control')!r}")
    if "sandbox" not in (lower_headers.get("content-security-policy") or ""):
        raise ValueError("Expected sandbox Content-Security-Policy on JSON manifest")
    checks.append({"check": "allow:GET:/viewer-publications/manifest.json", "status": manifest_status})

    # 3. Optional PDF body probe (verifies Range / immutable Cache-Control / inline Content-Disposition / no sandbox CSP)
    if pdf_path:
        rel_pdf = pdf_path if pdf_path.startswith("/") else f"/{pdf_path}"
        sep = "&" if "?" in rel_pdf else "?"
        pdf_status, pdf_headers = probe(
            "GET",
            f"{base}{rel_pdf}{sep}filename=committee-hearing.pdf",
            {"Range": "bytes=0-4", "Origin": "https://congressional-tech.spicygov.ai"},
        )
        lower_pdf = {k.lower(): v for k, v in pdf_headers.items()}
        if pdf_status not in (200, 206):
            raise ValueError(f"Expected 200/206 on PDF probe {rel_pdf}, got {pdf_status}")
        if "immutable" not in (lower_pdf.get("cache-control") or ""):
            raise ValueError(f"Expected immutable Cache-Control on PDF, got {lower_pdf.get('cache-control')!r}")
        if "sandbox" in (lower_pdf.get("content-security-policy") or ""):
            raise ValueError("PDF response must not include sandbox Content-Security-Policy")
        if "inline" not in (lower_pdf.get("content-disposition") or ""):
            raise ValueError(f"Expected inline Content-Disposition on PDF, got {lower_pdf.get('content-disposition')!r}")
        checks.append({"check": f"allow:GET:{rel_pdf}", "status": pdf_status})

    return {"status": "verified", "base_url": base, "checks": checks}


def main(
    argv: list[str] | None = None,
    *,
    transport: Callable[[str, str, Mapping[str, str], Mapping[str, Any] | None], dict[str, Any]] | None = None,
    http_probe: Callable[[str, str, Mapping[str, str] | None], tuple[int, Mapping[str, str]]] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for cmd in ("plan", "verify-config"):
        sub = subparsers.add_parser(cmd, help="Validate edge config and print Cloudflare API plan")
        sub.add_argument("--config", type=Path, default=DEFAULT_EDGE_CONFIG_PATH)
        sub.add_argument("--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID", "<ACCOUNT_ID>"))
        sub.add_argument("--zone-id", default=os.environ.get("CLOUDFLARE_ZONE_ID", "<ZONE_ID>"))

    apply_p = subparsers.add_parser("apply", help="Apply R2 CORS, WAF, and Transform Rules via Cloudflare API")
    apply_p.add_argument("--config", type=Path, default=DEFAULT_EDGE_CONFIG_PATH)
    apply_p.add_argument("--api-token", default=os.environ.get("CLOUDFLARE_API_TOKEN", ""))
    apply_p.add_argument("--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""))
    apply_p.add_argument("--zone-id", default=os.environ.get("CLOUDFLARE_ZONE_ID", ""))

    live_p = subparsers.add_parser("verify-live", help="Probe live domain for WAF, CORS, Cache-Control, and CSP headers")
    live_p.add_argument("--base-url", default="https://congressional-data.spicygov.ai")
    live_p.add_argument("--pdf-path", help="Optional /bodies/sha256/<xx>/<sha256>.pdf path to probe")

    args = parser.parse_args(argv)
    if args.command in ("plan", "verify-config"):
        cfg = load_edge_config(args.config)
        result = build_cloudflare_plan(cfg, account_id=args.account_id, zone_id=args.zone_id)
    elif args.command == "apply":
        cfg = load_edge_config(args.config)
        result = apply_cloudflare_plan(
            cfg,
            api_token=args.api_token,
            account_id=args.account_id,
            zone_id=args.zone_id,
            transport=transport,
        )
    else:
        result = verify_live_edge(
            args.base_url,
            pdf_path=args.pdf_path,
            http_probe=http_probe,
        )
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
