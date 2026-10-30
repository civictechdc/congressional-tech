"""Verify declarative Cloudflare R2 Custom Domain, CORS, and Response Header Transform Rules.

Origin rules (CORS, cache headers, CSP, and ``?filename=``) are managed declaratively via
``infra/cloudflare/congressional-data-r2-edge.json`` and Terraform ``cloudflare_ruleset`` in
``infra/cloudflare/main.tf`` without whole-phase REST API overwrites or the legacy firewall path allowlist.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
from pathlib import Path
import sys
from typing import Any
import urllib.error
import urllib.request

from congress_api.retention.r2_edge_rules import (
    DEFAULT_EDGE_CONFIG_PATH,
    DEFAULT_TERRAFORM_CONFIG_PATH,
    build_declarative_ruleset_spec,
    evaluate_response_headers,
    load_edge_config,
)


def validate_edge_config(
    config: Mapping[str, Any] | None = None,
    *,
    terraform_path: Path | None = None,
) -> dict[str, Any]:
    """Validate the declarative edge configuration structure and policy invariants."""
    cfg = dict(config or load_edge_config())
    if cfg.get("version") != 1:
        raise ValueError(f"Unsupported edge config version: {cfg.get('version')!r}")
    if "waf_custom_rules" in cfg:
        raise ValueError("Legacy firewall path allowlist (waf_custom_rules) is retired")
    domain = cfg.get("custom_domain") or {}
    if not domain.get("hostname") or not domain.get("bucket"):
        raise ValueError("custom_domain requires hostname and bucket")
    cors_rules = (cfg.get("cors") or {}).get("rules") or []
    if not cors_rules:
        raise ValueError("cors.rules must contain at least one rule")
    transform_rules = cfg.get("response_header_transform_rules") or []
    if not transform_rules:
        raise ValueError("response_header_transform_rules must contain at least one rule")

    spec = build_declarative_ruleset_spec(cfg, terraform_path=terraform_path)
    ruleset = spec["cloudflare_ruleset"]
    if ruleset.get("phase") != "http_response_headers_transform":
        raise ValueError(f"Expected http_response_headers_transform phase, got {ruleset.get('phase')!r}")
    rules_by_ref = {r["ref"]: r for r in ruleset.get("rules", [])}
    required_refs = {
        "public-r2-security-and-disposition-headers-base-and-immutable-cache",
        "public-r2-security-and-disposition-headers-mutable-manifests-no-store",
        "public-r2-security-and-disposition-headers-non-pdf-csp-and-disposition",
        "public-r2-security-and-disposition-headers-pdf-filename-disposition",
        "public-r2-security-and-disposition-headers-non-pdf-filename-disposition",
    }
    if set(rules_by_ref) != required_refs:
        raise ValueError(f"Unexpected ruleset refs: {sorted(rules_by_ref)}")
    for disp_ref in (
        "public-r2-security-and-disposition-headers-pdf-filename-disposition",
        "public-r2-security-and-disposition-headers-non-pdf-filename-disposition",
    ):
        expr = rules_by_ref[disp_ref]["expression"]
        for forbidden in ("%", '\\"', "\\\\", ";", "/", "..", "\\r", "\\n"):
            if f'not contains(http.request.uri.args["filename"][0], "{forbidden}")' not in expr:
                raise ValueError(f"Missing header-injection guard {forbidden!r} in {disp_ref}")

    sample_sha = "ab" + "cd" * 31
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

    return spec


def _default_http_probe(
    method: str,
    url: str,
    headers: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, str]]:
    from viewer_publication.constants import USER_AGENT
    req_headers = {"User-Agent": USER_AGENT, **dict(headers or {})}
    req = urllib.request.Request(url, headers=req_headers, method=method)
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
    """Probe live or simulated edge endpoints to verify CORS, Cache-Control, CSP, and Content-Disposition."""
    base = base_url.rstrip("/")
    probe = http_probe or _default_http_probe
    checks: list[dict[str, Any]] = []

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
    http_probe: Callable[[str, str, Mapping[str, str] | None], tuple[int, Mapping[str, str]]] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_cfg = subparsers.add_parser(
        "verify-config",
        help="Validate declarative edge JSON and Terraform cloudflare_ruleset specification",
    )
    verify_cfg.add_argument("--config", type=Path, default=DEFAULT_EDGE_CONFIG_PATH)
    verify_cfg.add_argument("--terraform", type=Path, default=DEFAULT_TERRAFORM_CONFIG_PATH)

    live_p = subparsers.add_parser(
        "verify-live",
        help="Probe live domain for CORS, Cache-Control, CSP, and Content-Disposition headers",
    )
    live_p.add_argument("--base-url", default="https://congressional-data.spicygov.ai")
    live_p.add_argument("--pdf-path", help="Optional /bodies/sha256/<xx>/<sha256>.pdf path to probe")

    args = parser.parse_args(argv)
    if args.command == "verify-config":
        cfg = load_edge_config(args.config)
        result = validate_edge_config(cfg, terraform_path=args.terraform)
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
