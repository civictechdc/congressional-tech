#!/usr/bin/env python3
"""Build a source-backed LoC Congressional Web Archive coverage map and cross-match tool.

Reads only https://www.loc.gov/.../?fo=json API endpoints (never webarchive.loc.gov,
webarchive-beta.loc.gov, www.gao.gov, or HTML www.loc.gov pages) at a conservative delay
(>= 6.0s between live requests) and aborts immediately on any rate-limit or bot-check
response without retrying.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import requests

LCWA_SEED = "https://www.loc.gov/collections/united-states-congressional-web-archive/?fo=json&c=100&sp=1"
USER_AGENT = "congressional-tech/1.0 (+https://github.com/civictechdc/congressional-tech)"
MIN_LOC_JSON_DELAY_SECONDS = 6.0
DEFAULT_DELAY_SECONDS = 6.5

_CONGRESS_PARTOF_RE = re.compile(r"\b(\d+)(?:st|nd|rd|th)\s+congress\b", re.I)
_CONGRESS_SUBJECT_RE = re.compile(r"\bcongress\s*\((\d+)(?:st|nd|rd|th)\b", re.I)
_DATE_RANGE_RE = re.compile(r"\[(\d{4})\s+TO\s+(\d{4}|\*)\]", re.I)
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_SCOPE_NOTE_RE = re.compile(r"\s+\(([^()]*)\)\s*$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def validate_loc_json_url(url: str) -> str:
    """Validate that a URL is strictly an HTTPS www.loc.gov JSON API request."""
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() != "www.loc.gov":
        raise ValueError(f"Refusing non-www.loc.gov or insecure URL: {url}")
    query = parse_qs(parts.query, keep_blank_values=True)
    if "json" not in [v.lower() for v in query.get("fo", [])]:
        raise ValueError(f"Refusing www.loc.gov URL without fo=json: {url}")
    return url


def _ensure_fo_json(url: str) -> str:
    parts = urlsplit(urljoin("https://www.loc.gov/", url))
    query = parse_qs(parts.query, keep_blank_values=True)
    if "fo" not in query:
        pairs = list(parse_qs(parts.query, keep_blank_values=True).items())
        flat: list[tuple[str, str]] = []
        for key, values in pairs:
            for val in values:
                flat.append((key, val))
        flat.append(("fo", "json"))
        parts = parts._replace(query=urlencode(flat))
    return validate_loc_json_url(urlunsplit(parts))


def fetch_loc_json(
    session: requests.Session,
    url: str,
    *,
    timeout: float = 30.0,
) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    """Fetch a single www.loc.gov ?fo=json URL, hard-aborting on screening or errors."""
    current = validate_loc_json_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    response = None
    for _hop in range(3):
        response = session.get(current, headers=headers, timeout=timeout, allow_redirects=False)
        lower_headers = {k.lower(): v for k, v in response.headers.items()}
        if "cf-mitigated" in lower_headers:
            raise RuntimeError(f"Cloudflare mitigation header on {current}: {lower_headers['cf-mitigated']}")
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            if not location:
                raise RuntimeError(f"Redirect without Location header from {current}")
            current = validate_loc_json_url(urljoin(current, location))
            continue
        break
    assert response is not None
    if response.status_code in {403, 429} or response.status_code >= 400:
        raise RuntimeError(f"LoC JSON request failed with HTTP {response.status_code} on {current} (zero retries)")
    content_type = (response.headers.get("Content-Type") or "").lower()
    raw = response.content
    if "json" not in content_type:
        snippet = raw[:200].decode("utf-8", errors="replace")
        raise RuntimeError(f"Non-JSON Content-Type {content_type!r} on {current}: {snippet!r}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object payload on {current}, got {type(payload).__name__}")
    meta = {
        "requested_url": url,
        "final_url": current,
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type"),
        "sha256": sha256_bytes(raw),
        "bytes": len(raw),
        "fetched_at": now_iso(),
    }
    return payload, raw, meta


def normalize_scope(raw_scope: str, *, source_field: str = "scopes") -> dict[str, str] | None:
    """Normalize an item.scopes entry or source_url into host + path prefix metadata."""
    text = (raw_scope or "").strip()
    if not text:
        return None
    note = ""
    match = _SCOPE_NOTE_RE.search(text)
    if match:
        note = match.group(1).strip()
        text = text[: match.start()].strip()
    if not text:
        return None
    candidate = text if "://" in text else f"http://{text}"
    parts = urlsplit(candidate)
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return None
    path_prefix = parts.path or "/"
    if not path_prefix.startswith("/"):
        path_prefix = "/" + path_prefix
    return {
        "raw": raw_scope,
        "source_field": source_field,
        "scope_note": note,
        "host": host,
        "path_prefix": path_prefix,
        "normalized_scope": f"{host}{path_prefix}",
    }


def parse_year_ranges(item: dict[str, Any]) -> list[dict[str, int | None]]:
    """Parse [YYYY TO YYYY] ranges (or fallback years) from LoC item metadata."""
    ranges: list[tuple[int, int | None]] = []
    raw_dates = item.get("dates") or []
    if isinstance(raw_dates, str):
        raw_dates = [raw_dates]
    for entry in raw_dates:
        text = str(entry)
        matched = False
        for start_s, end_s in _DATE_RANGE_RE.findall(text):
            matched = True
            start_y = int(start_s)
            end_y = int(end_s) if end_s.isdigit() else None
            ranges.append((start_y, end_y))
        if not matched:
            years = [int(y) for y in _YEAR_RE.findall(text)]
            if years:
                ranges.append((min(years), max(years)))
    if not ranges and item.get("date"):
        years = [int(y) for y in _YEAR_RE.findall(str(item["date"]))]
        if years:
            ranges.append((min(years), max(years)))
    seen: list[dict[str, int | None]] = []
    for start_y, end_y in sorted(set(ranges), key=lambda pair: (pair[0], pair[1] if pair[1] is not None else 9999)):
        seen.append({"start": start_y, "end": end_y})
    return seen


def parse_congresses(item: dict[str, Any]) -> list[int]:
    """Extract sorted Congress numbers from partof and item.subject_headings."""
    found: set[int] = set()
    for text in item.get("partof") or []:
        for num in _CONGRESS_PARTOF_RE.findall(str(text)):
            found.add(int(num))
    nested = item.get("item") if isinstance(item.get("item"), dict) else {}
    for text in nested.get("subject_headings") or []:
        for num in _CONGRESS_SUBJECT_RE.findall(str(text)):
            found.add(int(num))
    for text in item.get("subject") or []:
        for num in _CONGRESS_SUBJECT_RE.findall(str(text)):
            found.add(int(num))
    return sorted(found)


def extract_item_id(raw_item: dict[str, Any]) -> str:
    candidate = str(raw_item.get("url") or raw_item.get("id") or "").rstrip("/")
    if not candidate:
        raise ValueError("LoC catalog item missing url/id")
    return candidate.rsplit("/", 1)[-1]


def normalize_catalog_item(raw_item: dict[str, Any], *, collection: str = "united-states-congressional-web-archive") -> dict[str, Any]:
    """Normalize a single LoC search result record into canonical catalog metadata."""
    item_id = extract_item_id(raw_item)
    nested = raw_item.get("item") if isinstance(raw_item.get("item"), dict) else {}

    scopes: list[dict[str, str]] = []
    seen_scope_keys: set[tuple[str, str, str]] = set()
    for field, values in (
        ("scopes", nested.get("scopes") or []),
        ("source_url", nested.get("source_url") or []),
    ):
        for raw_val in values:
            norm = normalize_scope(str(raw_val), source_field=field)
            if norm is None:
                continue
            key = (norm["host"], norm["path_prefix"], norm["source_field"])
            if key not in seen_scope_keys:
                seen_scope_keys.add(key)
                scopes.append(norm)

    contributors: list[str] = []
    seen_contrib: set[str] = set()
    for val in list(nested.get("contributor_names") or []) + list(raw_item.get("contributor") or []):
        s = str(val).strip()
        if s and s not in seen_contrib:
            seen_contrib.add(s)
            contributors.append(s)

    replay_wildcards: list[str] = []
    for res in raw_item.get("resources") or []:
        if isinstance(res, dict) and res.get("url"):
            u = str(res["url"])
            if u not in replay_wildcards:
                replay_wildcards.append(u)

    url = str(raw_item.get("url") or raw_item.get("id") or f"https://www.loc.gov/item/{item_id}/")
    if url.startswith("http://www.loc.gov/"):
        url = "https://" + url[len("http://") :]

    return {
        "item_id": item_id,
        "url": url,
        "collection": collection,
        "title": str(raw_item.get("title") or "").strip(),
        "date": raw_item.get("date"),
        "dates": list(raw_item.get("dates") or []),
        "year_ranges": parse_year_ranges(raw_item),
        "congresses": parse_congresses(raw_item),
        "contributors": contributors,
        "access_restricted": bool(raw_item.get("access_restricted", False)),
        "scopes": scopes,
        "source_urls": [str(u) for u in (nested.get("source_url") or [])],
        "replay_wildcard_urls": replay_wildcards,
        "partof": list(raw_item.get("partof") or []),
    }


def _strip_www(host: str) -> str:
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def _year_in_ranges(year: int, ranges: list[dict[str, int | None]]) -> bool:
    for r in ranges:
        start_y = r["start"]
        end_y = r["end"]
        if start_y is not None and year >= start_y and (end_y is None or year <= end_y):
            return True
    return False


def build_domain_coverage(records: list[dict[str, Any]], *, generated_at: str | None = None) -> dict[str, Any]:
    """Build normalized host/scope coverage map from catalog records."""
    by_host: dict[str, dict[str, Any]] = {}
    records_by_id = {r["item_id"]: r for r in records}

    for rec in records:
        min_year: int | None = None
        max_year: int | None = None
        has_open_end = False
        for r in rec["year_ranges"]:
            s, e = r["start"], r["end"]
            if s is not None:
                min_year = s if min_year is None else min(min_year, s)
            if e is None:
                has_open_end = True
            else:
                max_year = e if max_year is None else max(max_year, e)

        for scope in rec["scopes"]:
            host = scope["host"]
            host_entry = by_host.setdefault(
                host,
                {
                    "host": host,
                    "bare_host": _strip_www(host),
                    "scopes": [],
                    "item_ids": [],
                    "congresses": [],
                    "min_year": None,
                    "max_year": None,
                    "has_open_end": False,
                },
            )
            scope_rec = {
                "item_id": rec["item_id"],
                "title": rec["title"],
                "catalog_url": rec["url"],
                "path_prefix": scope["path_prefix"],
                "source_field": scope["source_field"],
                "scope_note": scope["scope_note"],
                "year_ranges": rec["year_ranges"],
                "congresses": rec["congresses"],
                "access_restricted": rec["access_restricted"],
                "replay_wildcard_urls": rec["replay_wildcard_urls"],
            }
            host_entry["scopes"].append(scope_rec)
            if rec["item_id"] not in host_entry["item_ids"]:
                host_entry["item_ids"].append(rec["item_id"])
            host_entry["congresses"] = sorted(set(host_entry["congresses"]) | set(rec["congresses"]))
            if min_year is not None:
                cur_min = host_entry["min_year"]
                host_entry["min_year"] = min_year if cur_min is None else min(cur_min, min_year)
            if max_year is not None:
                cur_max = host_entry["max_year"]
                host_entry["max_year"] = max_year if cur_max is None else max(cur_max, max_year)
            host_entry["has_open_end"] = host_entry["has_open_end"] or has_open_end

    # Also build bare_host -> canonical host index for explicit www-variant lookup.
    bare_index: dict[str, list[str]] = defaultdict(list)
    for host in sorted(by_host):
        bare_index[_strip_www(host)].append(host)

    return {
        "schema_version": "loc-lcwa-coverage-v1",
        "generated_at": generated_at or now_iso(),
        "total_items": len(records),
        "unique_hosts": len(by_host),
        "hosts": dict(sorted(by_host.items())),
        "bare_host_index": dict(sorted(bare_index.items())),
        "items": records_by_id,
    }


def _path_matches_scope(target_path: str, scope_prefix: str) -> bool:
    t = (target_path or "/").lower()
    s = (scope_prefix or "/").lower()
    if s == "/":
        return True
    if s.endswith("/"):
        return t.startswith(s) or (t + "/") == s
    return t == s or t.startswith(s + "/")


def lookup_url(
    coverage: dict[str, Any],
    url: str,
    *,
    year: int | None = None,
    include_www: bool = True,
    include_subdomains: bool = False,
) -> dict[str, Any]:
    """Offline lookup of a target URL against domain-coverage.json."""
    clean_url = url.split("#", 1)[0].strip()
    parts = urlsplit(clean_url)
    target_host = (parts.hostname or "").lower().rstrip(".")
    target_path = parts.path or "/"
    hosts_map: dict[str, Any] = coverage.get("hosts", {})
    bare_index: dict[str, list[str]] = coverage.get("bare_host_index", {})

    candidate_hosts: list[tuple[str, str]] = []
    seen_hosts: set[str] = set()
    if target_host in hosts_map:
        candidate_hosts.append((target_host, "exact_host"))
        seen_hosts.add(target_host)
    if include_www:
        for alt_host in bare_index.get(_strip_www(target_host), []):
            if alt_host not in seen_hosts:
                candidate_hosts.append((alt_host, "www_variant"))
                seen_hosts.add(alt_host)
    if include_subdomains and target_host:
        labels = target_host.split(".")
        for i in range(1, len(labels) - 1):
            parent = ".".join(labels[i:])
            if parent in hosts_map and parent not in seen_hosts:
                candidate_hosts.append((parent, "parent_domain_scope"))
                seen_hosts.add(parent)

    matches: list[dict[str, Any]] = []
    seen_item_scope: set[tuple[str, str, str]] = set()
    for cand_host, host_basis in candidate_hosts:
        entry = hosts_map[cand_host]
        for scope in entry["scopes"]:
            if not _path_matches_scope(target_path, scope["path_prefix"]):
                continue
            if year is not None and scope["year_ranges"] and not _year_in_ranges(year, scope["year_ranges"]):
                continue
            dedup_key = (scope["item_id"], cand_host, scope["path_prefix"])
            if dedup_key in seen_item_scope:
                continue
            seen_item_scope.add(dedup_key)
            basis = host_basis if scope["path_prefix"] == "/" else f"{host_basis}+path_prefix"
            matches.append(
                {
                    "item_id": scope["item_id"],
                    "title": scope["title"],
                    "catalog_url": scope["catalog_url"],
                    "matched_host": cand_host,
                    "path_prefix": scope["path_prefix"],
                    "source_field": scope["source_field"],
                    "match_basis": basis,
                    "year_ranges": scope["year_ranges"],
                    "congresses": scope["congresses"],
                    "access_restricted": scope["access_restricted"],
                    "replay_wildcard_urls": scope["replay_wildcard_urls"],
                    "browser_lookup_url": f"https://webarchive.loc.gov/all/*/{clean_url}",
                }
            )

    return {
        "target_url": clean_url,
        "target_host": target_host,
        "target_path": target_path,
        "year_filter": year,
        "matched": bool(matches),
        "match_count": len(matches),
        "browser_lookup_url": f"https://webarchive.loc.gov/all/*/{clean_url}",
        "matches": matches,
    }


def _collect_items_from_pages(page_payloads: list[dict[str, Any]], *, collection: str) -> list[dict[str, Any]]:
    records_by_id: dict[str, dict[str, Any]] = {}
    for payload in page_payloads:
        results = payload.get("results") or []
        for raw_item in results:
            if not isinstance(raw_item, dict):
                continue
            norm = normalize_catalog_item(raw_item, collection=collection)
            item_id = norm["item_id"]
            if item_id not in records_by_id:
                records_by_id[item_id] = norm
    return sorted(records_by_id.values(), key=lambda r: r["item_id"])


def build_catalog(
    output: Path,
    *,
    seed: str = LCWA_SEED,
    offline: bool = False,
    delay: float = DEFAULT_DELAY_SECONDS,
    max_pages: int = 100,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Download (or read cached) LoC collection ?fo=json pages and emit catalog + coverage JSON."""
    if not offline and delay < MIN_LOC_JSON_DELAY_SECONDS:
        raise ValueError(f"Refusing delay < {MIN_LOC_JSON_DELAY_SECONDS}s for live LoC requests (got {delay}s)")
    output.mkdir(parents=True, exist_ok=True)
    pages_dir = output / "pages"
    pages_dir.mkdir(exist_ok=True)

    http = session or requests.Session()
    next_url: str | None = validate_loc_json_url(seed)
    page_num = 1
    page_payloads: list[dict[str, Any]] = []
    page_manifest: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    reported_total_hits: int | None = None
    reported_total_pages: int | None = None

    while next_url and page_num <= max_pages:
        if next_url in seen_urls:
            break
        seen_urls.add(next_url)
        page_path = pages_dir / f"page-{page_num:04d}.json"
        if page_path.exists():
            raw = page_path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
            source_mode = "cached"
        else:
            if offline:
                raise ValueError(f"Missing cached LoC page in --offline mode: {page_path}")
            if page_num > 1:
                time.sleep(delay)
            payload, raw, fetch_meta = fetch_loc_json(http, next_url)
            page_path.write_bytes(raw)
            source_mode = "fetched"
            save_json(pages_dir / f"page-{page_num:04d}.meta.json", fetch_meta)

        page_payloads.append(payload)
        pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
        if reported_total_hits is None and isinstance(pagination.get("of"), int):
            reported_total_hits = pagination["of"]
        if reported_total_pages is None and isinstance(pagination.get("total"), int):
            reported_total_pages = pagination["total"]

        page_manifest.append(
            {
                "page": page_num,
                "url": next_url,
                "file": str(page_path),
                "sha256": sha256_bytes(raw),
                "results_count": len(payload.get("results") or []),
                "source_mode": source_mode,
                "next": pagination.get("next"),
            }
        )

        raw_next = pagination.get("next")
        next_url = _ensure_fo_json(raw_next) if isinstance(raw_next, str) and raw_next.strip() else None
        page_num += 1

    records = _collect_items_from_pages(page_payloads, collection="united-states-congressional-web-archive")
    coverage = build_domain_coverage(records)
    manifest = {
        "schema_version": "loc-lcwa-manifest-v1",
        "generated_at": now_iso(),
        "seed": seed,
        "pages_collected": len(page_manifest),
        "reported_total_hits": reported_total_hits,
        "reported_total_pages": reported_total_pages,
        "unique_records": len(records),
        "unique_hosts": coverage["unique_hosts"],
        "pages": page_manifest,
    }
    save_json(output / "catalog-records.json", records)
    save_json(output / "domain-coverage.json", coverage)
    save_json(output / "manifest.json", manifest)
    return manifest


def _load_non_loc_outcomes(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in json.loads(path.read_text(encoding="utf-8")):
        by_case[row["case"]].append(row)
    summarized: dict[str, dict[str, Any]] = {}
    for case_id, rows in by_case.items():
        qualified = [
            r
            for r in rows
            if r.get("qualification_status") == "qualified"
            and r.get("identity_status") != "rejected_different_hearing_2013"
        ]
        if qualified:
            best = qualified[0]
            summarized[case_id] = {
                "step1a_status": "qualified_non_loc",
                "lead_kind": best.get("lead_kind"),
                "candidate_url": best.get("candidate_url"),
                "fetched_bytes": best.get("fetched_bytes"),
                "pages": best.get("pages"),
                "receipt_key": best.get("receipt_key"),
            }
        else:
            last = rows[-1]
            summarized[case_id] = {
                "step1a_status": f"unresolved_non_loc ({last.get('qualification_reason') or last.get('qualification_status')})",
                "lead_kind": last.get("lead_kind"),
                "candidate_url": last.get("candidate_url"),
                "fetched_bytes": last.get("fetched_bytes"),
                "pages": last.get("pages"),
                "receipt_key": last.get("receipt_key"),
            }
    return summarized


def _load_hearing_print_outcomes(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {row["case"]: row for row in payload.get("cases", [])}


def _extract_year_from_url_or_date(url: str, date_str: str | None = None) -> int | None:
    if date_str:
        m = _YEAR_RE.search(date_str)
        if m:
            return int(m.group(1))
    # Explicit congressional-file filename patterns like YYYYMMDD or M-D-YY
    m_full = re.search(r"(?:^|[/_-])((?:19|20)\d{2})(?:\d{4})(?:\.pdf|$|[/_-])", url, re.I)
    if m_full:
        return int(m_full.group(1))
    m_ymd = re.search(r"/((?:20\d{2}))/(?:0?\d|1[0-2])/", url)
    if m_ymd:
        return int(m_ymd.group(1))
    m_short = re.search(r"(?:^|[/_-])\d{1,2}[-_]\d{1,2}[-_](1\d|2\d|0\d)(?:[_.-]|$)", url)
    if m_short:
        return 2000 + int(m_short.group(1))
    return None


def cross_match_inventory(
    coverage: dict[str, Any],
    *,
    damaged_manifest: Path,
    invalid_sources: Path,
    output: Path,
    non_loc_results: Path | None = None,
    hearing_prints: Path | None = None,
    supplemental_json: list[Path] | None = None,
    remaining_loc_targets: Path | None = None,
) -> dict[str, Any]:
    """Cross-match LoC domain coverage against the 49 damaged PDFs and open inventory records."""
    # Optionally merge supplemental web-archive JSON searches into an augmented coverage view
    supplemental_items: list[dict[str, Any]] = []
    for spath in supplemental_json or []:
        if spath.exists():
            spayload = json.loads(spath.read_text(encoding="utf-8"))
            for raw_item in spayload.get("results") or []:
                if isinstance(raw_item, dict):
                    supplemental_items.append(
                        normalize_catalog_item(raw_item, collection=spath.stem)
                    )

    combined_items = list(coverage.get("items", {}).values())
    existing_ids = {rec["item_id"] for rec in combined_items}
    extra_items = []
    for srec in supplemental_items:
        if srec["item_id"] not in existing_ids:
            existing_ids.add(srec["item_id"])
            combined_items.append(srec)
            extra_items.append(srec)
    augmented_coverage = build_domain_coverage(combined_items) if extra_items else coverage

    non_loc_by_case = _load_non_loc_outcomes(non_loc_results)
    prints_by_case = _load_hearing_print_outcomes(hearing_prints)
    manual_loc_cases: set[str] = set()
    if remaining_loc_targets and remaining_loc_targets.exists():
        for t in json.loads(remaining_loc_targets.read_text(encoding="utf-8")):
            manual_loc_cases.add(t["case_id"])

    damaged_rows: list[dict[str, Any]] = []
    if damaged_manifest.exists():
        with damaged_manifest.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                case_id = row["case"]
                urls = [u for u in (row.get("urls") or "").split() if u]
                year_hint = None
                for u in urls:
                    year_hint = _extract_year_from_url_or_date(u)
                    if year_hint is not None:
                        break
                # Look up against LCWA catalog first, then augmented coverage (general web archives)
                lcwa_matches = [lookup_url(coverage, u, year=year_hint) for u in urls]
                aug_matches = [lookup_url(augmented_coverage, u, year=year_hint) for u in urls]
                # Also test old Oversight Testimony path for oversight.house.gov PDFs
                extra_old_matches: list[dict[str, Any]] = []
                for u in urls:
                    parts = urlsplit(u)
                    if (parts.hostname or "").lower() == "oversight.house.gov" and "/wp-content/uploads/" in parts.path:
                        fname = parts.path.rsplit("/", 1)[-1]
                        old_u = f"http://oversight.house.gov/images/stories/Testimony/{fname}"
                        extra_old_matches.append(lookup_url(coverage, old_u, year=year_hint))

                if case_id in non_loc_by_case and non_loc_by_case[case_id]["step1a_status"] == "qualified_non_loc":
                    resolution_state = "qualified_non_loc"
                elif case_id in prints_by_case:
                    resolution_state = prints_by_case[case_id]["disposition"]
                elif case_id in manual_loc_cases:
                    resolution_state = "queued_for_loc_browser_capture"
                elif case_id in non_loc_by_case:
                    resolution_state = non_loc_by_case[case_id]["step1a_status"]
                else:
                    resolution_state = "no_automatic_lead_yet"

                damaged_rows.append(
                    {
                        "case": case_id,
                        "urls": urls,
                        "year_hint": year_hint,
                        "resolution_state": resolution_state,
                        "lcwa_matched": any(m["matched"] for m in lcwa_matches),
                        "lcwa_plus_supplemental_matched": any(m["matched"] for m in aug_matches),
                        "matched_items": sorted(
                            {
                                (item["item_id"], augmented_coverage["items"].get(item["item_id"], {}).get("collection", "lcwa"))
                                for m in aug_matches
                                for item in m["matches"]
                            }
                        ),
                        "matched_details": aug_matches,
                        "old_oversight_path_lookup": extra_old_matches,
                    }
                )

    open_counts: Counter[str] = Counter()
    open_by_failure: Counter[str] = Counter()
    open_matched_by_host: Counter[str] = Counter()
    open_matched_by_failure: Counter[str] = Counter()
    open_unmatched_by_host: Counter[str] = Counter()
    matched_open_samples: list[dict[str, Any]] = []
    unmatched_open_url_samples: list[dict[str, Any]] = []

    if invalid_sources.exists():
        with invalid_sources.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if not rec.get("recovery_open"):
                    continue
                open_counts["open_total"] += 1
                fcat = rec.get("failure_category") or "unknown"
                open_by_failure[fcat] += 1

                urls: list[str] = []
                for u in rec.get("source_urls") or []:
                    if u and u not in urls:
                        urls.append(u)
                for tgt in rec.get("targets") or []:
                    for cand in [tgt.get("requested_target"), *(tgt.get("observed_aliases") or [])]:
                        if cand and cand not in urls:
                            urls.append(cand)

                if not urls:
                    open_counts["open_missing_source_url"] += 1
                    continue

                open_counts["open_with_urls"] += 1
                doc_date = None
                for rel in rec.get("release_associations_20261117") or []:
                    if rel.get("document_date"):
                        doc_date = str(rel["document_date"])
                        break
                year_hint = _extract_year_from_url_or_date(urls[0], doc_date)

                rec_matches_lcwa = [lookup_url(coverage, u, year=year_hint) for u in urls]
                rec_matches_lcwa_any_year = [lookup_url(coverage, u, year=None) for u in urls]
                rec_matches_aug = [lookup_url(augmented_coverage, u, year=year_hint) for u in urls]

                any_lcwa_year = any(m["matched"] for m in rec_matches_lcwa)
                any_lcwa_host = any(m["matched"] for m in rec_matches_lcwa_any_year)
                any_aug = any(m["matched"] for m in rec_matches_aug)

                hosts_in_rec = sorted({(urlsplit(u).hostname or "").lower() for u in urls if urlsplit(u).hostname})
                if any_lcwa_year:
                    open_counts["open_matched_lcwa_with_year"] += 1
                if any_lcwa_host:
                    open_counts["open_matched_lcwa_host_any_year"] += 1
                    open_matched_by_failure[fcat] += 1
                    for h in hosts_in_rec:
                        open_matched_by_host[h] += 1
                    matched_open_samples.append(
                        {
                            "record_id": rec["record_id"],
                            "failure_category": fcat,
                            "year_hint": year_hint,
                            "urls": urls,
                            "lcwa_items": sorted({m_item["item_id"] for res in rec_matches_lcwa_any_year for m_item in res["matches"]}),
                            "year_matched": any_lcwa_year,
                        }
                    )
                else:
                    open_counts["open_unmatched_in_lcwa"] += 1
                    for h in hosts_in_rec:
                        open_unmatched_by_host[h] += 1
                    unmatched_open_url_samples.append(
                        {
                            "record_id": rec["record_id"],
                            "failure_category": fcat,
                            "year_hint": year_hint,
                            "urls": urls,
                            "matched_in_supplemental_general_archives": any_aug,
                        }
                    )
                if any_aug and not any_lcwa_year:
                    open_counts["open_matched_only_supplemental_or_other_year"] += 1

    state_counts = Counter(r["resolution_state"] for r in damaged_rows)
    still_missing = [r for r in damaged_rows if r["resolution_state"] not in {"qualified_non_loc", "queued_for_loc_browser_capture"}]

    overlap = {
        "schema_version": "loc-inventory-overlap-v1",
        "generated_at": now_iso(),
        "catalog_summary": {
            "lcwa_items": coverage["total_items"],
            "lcwa_unique_hosts": coverage["unique_hosts"],
            "supplemental_extra_items": len(extra_items),
        },
        "damaged_49_summary": {
            "total": len(damaged_rows),
            "by_resolution_state": dict(sorted(state_counts.items())),
            "lcwa_domain_matched_count": sum(1 for r in damaged_rows if r["lcwa_matched"]),
            "supplemental_matched_count": sum(1 for r in damaged_rows if r["lcwa_plus_supplemental_matched"]),
        },
        "damaged_49_rows": damaged_rows,
        "unresolved_or_non_qualified_highlight": still_missing,
        "invalid_sources_open_summary": {
            "counts": dict(open_counts),
            "by_failure_category": dict(open_by_failure.most_common()),
            "matched_lcwa_by_failure_category": dict(open_matched_by_failure.most_common()),
            "matched_lcwa_hosts": dict(open_matched_by_host.most_common()),
            "unmatched_lcwa_hosts": dict(open_unmatched_by_host.most_common()),
        },
        "matched_open_records": matched_open_samples,
        "unmatched_open_url_records_sample": unmatched_open_url_samples[:30],
    }

    output.mkdir(parents=True, exist_ok=True)
    save_json(output / "inventory-overlap.json", overlap)

    lines = [
        "# LoC Congressional Web Archive Coverage & Inventory Cross-Match",
        "",
        f"- Generated: {overlap['generated_at']}",
        f"- LCWA catalog items indexed: {coverage['total_items']} across {coverage['unique_hosts']} unique normalized hosts/subdomains",
        f"- Supplemental `web-archives` items inspected: {len(extra_items)}",
        "",
        "## 49 Damaged Zero-Page PDFs — Current Standing + LoC Coverage",
        "",
    ]
    for state, count in sorted(state_counts.items()):
        lines.append(f"- `{state}`: {count}")
    lines.extend([
        "",
        "### Remaining Special / Unresolved Damaged Cases",
        "",
        "| Case | Filename / URL | Current State | LCWA Match | Supplemental Match |",
        "|---|---|---|---|---|",
    ])
    for row in still_missing:
        u0 = row["urls"][0] if row["urls"] else ""
        fname = u0.rsplit("/", 1)[-1]
        lines.append(
            f"| `{row['case']}` | `{fname}` | `{row['resolution_state']}` | {row['lcwa_matched']} | {row['lcwa_plus_supplemental_matched']} |"
        )
    lines.extend([
        "",
        "## Open Recovery Inventory (`invalid-sources.jsonl`) Cross-Match",
        "",
        f"- Open records total: {open_counts.get('open_total', 0)}",
        f"- Open records missing `source_urls` (`house-meeting-not-found` etc.): {open_counts.get('open_missing_source_url', 0)}",
        f"- Open records with URLs: {open_counts.get('open_with_urls', 0)}",
        f"- Open records whose host matches LCWA (any year): {open_counts.get('open_matched_lcwa_host_any_year', 0)}",
        f"- Open records whose host + year overlaps LCWA: {open_counts.get('open_matched_lcwa_with_year', 0)}",
        f"- Open records with URLs not in LCWA: {open_counts.get('open_unmatched_in_lcwa', 0)}",
        "",
        "### Open Matched Hosts in LCWA",
        "",
    ])
    for host, count in open_matched_by_host.most_common():
        lines.append(f"- `{host}`: {count}")
    lines.extend(["", "### Open Unmatched Hosts (Outside LCWA Scope)", ""])
    for host, count in open_unmatched_by_host.most_common():
        lines.append(f"- `{host}`: {count}")

    (output / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return overlap


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build_p = sub.add_parser("build", help="Fetch or rebuild LCWA catalog & domain coverage map from ?fo=json")
    build_p.add_argument("--output", type=Path, required=True)
    build_p.add_argument("--seed", default=LCWA_SEED)
    build_p.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS)
    build_p.add_argument("--max-pages", type=int, default=100)
    build_p.add_argument("--offline", action="store_true")

    lookup_p = sub.add_parser("lookup", help="Offline lookup of a URL against domain-coverage.json")
    lookup_p.add_argument("url")
    lookup_p.add_argument("--year", type=int)
    lookup_p.add_argument("--map", type=Path, required=True)
    lookup_p.add_argument("--no-www", action="store_true")
    lookup_p.add_argument("--include-subdomains", action="store_true")

    cm_p = sub.add_parser("cross-match", help="Cross-match domain-coverage.json against damaged manifest & inventory")
    cm_p.add_argument("--map", type=Path, required=True)
    cm_p.add_argument("--damaged-manifest", type=Path, required=True)
    cm_p.add_argument("--invalid-sources", type=Path, required=True)
    cm_p.add_argument("--output", type=Path, required=True)
    cm_p.add_argument("--non-loc-results", type=Path)
    cm_p.add_argument("--hearing-prints", type=Path)
    cm_p.add_argument("--remaining-loc-targets", type=Path)
    cm_p.add_argument("--supplemental", type=Path, action="append", default=[])

    args = parser.parse_args()
    if args.command == "build":
        res = build_catalog(
            args.output,
            seed=args.seed,
            offline=args.offline,
            delay=args.delay,
            max_pages=args.max_pages,
        )
        print(json.dumps({k: v for k, v in res.items() if k != "pages"}, indent=2))
    elif args.command == "lookup":
        coverage = json.loads(args.map.read_text(encoding="utf-8"))
        print(
            json.dumps(
                lookup_url(
                    coverage,
                    args.url,
                    year=args.year,
                    include_www=not args.no_www,
                    include_subdomains=args.include_subdomains,
                ),
                indent=2,
            )
        )
    else:
        coverage = json.loads(args.map.read_text(encoding="utf-8"))
        res = cross_match_inventory(
            coverage,
            damaged_manifest=args.damaged_manifest,
            invalid_sources=args.invalid_sources,
            output=args.output,
            non_loc_results=args.non_loc_results,
            hearing_prints=args.hearing_prints,
            supplemental_json=args.supplemental,
            remaining_loc_targets=args.remaining_loc_targets,
        )
        print(
            json.dumps(
                {
                    "damaged_49_summary": res["damaged_49_summary"],
                    "invalid_sources_open_summary": res["invalid_sources_open_summary"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
