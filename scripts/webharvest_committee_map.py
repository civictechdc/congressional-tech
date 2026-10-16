#!/usr/bin/env python3
"""Build a source-backed Web Harvest map and generate (unverified) PDF lookups.

Uses requests and lxml from the repository environment. No capture-state writes.
"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import quote, urldefrag, urljoin, urlsplit, urlunsplit

from lxml import html
import requests


ROOT = "https://webharvest.gov"
SEED = ROOT + "/collections/congress118th/house_committees.html"
DEFAULT_MAP = Path(__file__).resolve().parents[1] / "docs/data/webharvest-committees"
PAGE = re.compile(r"/collections/congress(\d+)[a-z]{2}/(house|senate)_committees\.html$")
REPLAY = re.compile(r"^(https?://(?:www\.)?webharvest\.gov/congress(\d+)[a-z]{2}/([^/]+)/)(.+)$", re.I)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def split_replay(url):
    """Retain the published prefix; normalize only the embedded origin for indexing."""
    match = REPLAY.fullmatch(url)
    if not match:
        raise ValueError(f"Unrecognized Web Harvest replay: {url}")
    prefix, congress, selector, embedded = match.groups()
    if embedded.startswith(("http://", "https://")):
        original, style = embedded, "explicit_scheme"
    elif re.match(r"https?:/[^/]", embedded):
        original = embedded.replace(":/", "://", 1)
        style = "single_slash_scheme"
    else:
        original, style = "http://" + embedded, "omitted_scheme_assumed_http"
    parts = urlsplit(original)
    if not parts.hostname or parts.username or parts.password or parts.scheme not in {"http", "https"}:
        raise ValueError(f"Invalid embedded URL: {url}")
    return {
        "congress": int(congress), "domain": parts.hostname.lower(),
        "redirect_prefix": prefix, "selector": selector,
        "selector_kind": "timestamp" if re.fullmatch(r"\d{14}", selector) else "redirect_selector",
        "original_url": original, "embedded_url_literal": embedded,
        "embedded_url_style": style,
    }


def parse_page(body, source_url):
    page_match = PAGE.fullmatch(urlsplit(source_url).path)
    if not page_match:
        raise ValueError(f"Not a committee index: {source_url}")
    congress, chamber = page_match.groups()
    tree = html.fromstring(body)
    content = tree.xpath('//div[contains(concat(" ",normalize-space(@class)," ")," content ")]')
    if len(content) != 1:
        raise ValueError(f"Missing or ambiguous committee content: {source_url}")
    rows = []
    for anchor in content[0].xpath('.//a[@href]'):
        href = urljoin(source_url, anchor.get("href"))
        if not REPLAY.fullmatch(href):
            raise ValueError(f"Unexpected committee link: {href}")
        row = split_replay(href)
        if row["congress"] != int(congress):
            raise ValueError(f"Cross-Congress committee link: {href}")
        labels = anchor.getparent().xpath("./h3")
        headings = anchor.xpath("preceding::h2[1]")
        row.update(
            chamber=chamber, committee=" ".join(labels[0].itertext()).strip() if labels else "",
            category=" ".join(headings[0].itertext()).strip() if headings else "",
            published_replay_url=href, published_link_text=anchor.text_content().strip(),
            source_page=source_url, source_sha256=sha256(body),
            source_xpath=tree.getroottree().getpath(anchor),
        )
        if not row["committee"]:
            raise ValueError(f"Missing committee label: {href}")
        rows.append(row)
    if not rows:
        raise ValueError(f"Empty committee index: {source_url}")
    pages = sorted({urljoin(ROOT, a.get("href")) for a in tree.xpath('//a[@href]')
                    if PAGE.fullmatch(urlsplit(urljoin(ROOT, a.get("href"))).path)
                    and urlsplit(urljoin(ROOT, a.get("href"))).hostname in {"webharvest.gov", "www.webharvest.gov"}})
    return rows, pages


def build(output, seed=SEED, offline=False, delay=1.0):
    output.mkdir(parents=True, exist_ok=True)
    sources = output / "sources"
    sources.mkdir(exist_ok=True)
    pending, seen, rows, receipts = [seed], set(), [], []
    session = requests.Session()
    while pending:
        url = pending.pop(0)
        if url in seen:
            continue
        seen.add(url)
        match = PAGE.fullmatch(urlsplit(url).path)
        name = f"congress{match[1]}-{match[2]}"
        path, receipt_path = sources / f"{name}.html", sources / f"{name}.json"
        if not path.exists():
            if offline:
                raise ValueError(f"Missing retained source: {path}")
            response = session.get(url, timeout=30)
            receipt = {"url": url, "final_url": response.url, "status": response.status_code,
                       "headers": dict(response.headers), "retrieved_at": now(),
                       "sha256": sha256(response.content), "bytes": len(response.content)}
            save(receipt_path, receipt)
            path.write_bytes(response.content)
            response.raise_for_status()
            time.sleep(delay)
        body = path.read_bytes()
        receipt = json.loads(receipt_path.read_text())
        if receipt["status"] != 200 or sha256(body) != receipt["sha256"]:
            raise ValueError(f"Unsuccessful or changed retained source: {path}")
        entries, discovered = parse_page(body, url)
        rows.extend(entries)
        receipts.append({"file": str(path.relative_to(output)), **receipt, "entries": len(entries)})
        pending.extend(p for p in discovered if p not in seen and p not in pending)
        print(f"{name}: {len(entries)} entries", flush=True)
    rows.sort(key=lambda r: (r["congress"], r["chamber"], r["domain"], r["committee"]))
    by_congress, by_domain = {}, {}
    for i, row in enumerate(rows):
        row["id"] = i
        by_congress.setdefault(str(row["congress"]), {}).setdefault(row["domain"], []).append(i)
        by_domain.setdefault(row["domain"], {}).setdefault(str(row["congress"]), []).append(i)
    result = {"schema_version": 1, "seed": seed, "retrieved_at": max(r["retrieved_at"] for r in receipts),
              "scope": "All House and Senate committee index pages linked by the supplied collection; includes listed joint committees and task forces.",
              "availability": "Published archive routes, not verified PDF captures. A homepage timestamp does not prove a file exists.",
              "records": rows, "by_congress": by_congress, "by_domain": by_domain}
    save(output / "map.json", result)
    # Direct domain -> Congress -> prefixes view for consumers that do not need labels.
    prefixes = {domain: {congress: sorted({rows[i]["redirect_prefix"] for i in ids})
                         for congress, ids in congresses.items()} for domain, congresses in sorted(by_domain.items())}
    save(output / "domain-prefixes.json", prefixes)
    save(output / "manifest.json", {"sources": sorted(receipts, key=lambda r: r["url"]),
                                   "pages": len(receipts), "records": len(rows), "domains": len(by_domain),
                                   "congresses": sorted(map(int, by_congress)),
                                   "records_by_congress_chamber": dict(sorted(Counter(f'{r["congress"]}-{r["chamber"]}' for r in rows).items()))})
    return result


def lookup(mapping, url, congress=None, include_www=False):
    """Generate candidates; never infer a document's date, availability, or new path."""
    original = urldefrag(url)[0]
    parts = urlsplit(original)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Expected an absolute HTTP(S) URL without credentials")
    domain = parts.hostname.lower()
    domains = [(domain, "exact_domain")]
    if include_www:
        domains.append((domain[4:] if domain.startswith("www.") else "www." + domain, "www_variant"))
    found = {}
    for host, basis in domains:
        for number, ids in mapping["by_domain"].get(host, {}).items():
            if congress is not None and int(number) != congress:
                continue
            for index in ids:
                row = mapping["records"][index]
                # Preserve input scheme/path/query; www variants change only hostname.
                authority = host + (f":{parts.port}" if parts.port else "")
                target = urlunsplit((parts.scheme, authority, parts.path, parts.query, ""))
                variants = [(target, basis)]
                seed_scheme = urlsplit(row["original_url"]).scheme
                if seed_scheme != parts.scheme:
                    variants.append((urlunsplit((seed_scheme, authority, parts.path, parts.query, "")), basis + "+listed_scheme_variant"))
                for target, match_basis in variants:
                    candidate = row["redirect_prefix"] + target
                    if candidate not in found:
                        found[candidate] = {"congress": int(number), "candidate_url": candidate,
                                            "original_url": url, "target_url": target,
                                            "match_basis": match_basis, "map_record_ids": [],
                                            "availability": "unverified"}
                    if index not in found[candidate]["map_record_ids"]:
                        found[candidate]["map_record_ids"].append(index)
    return sorted(found.values(), key=lambda r: (-r["congress"], r["match_basis"], r["candidate_url"]))


def classify_redirect(url, status, headers, prefix=b""):
    """An HTTP 200 block page is not evidence of an archived capture."""
    title = re.search(br"<title[^>]*>(.*?)</title>", prefix, re.I | re.S)
    title = title[1].decode(errors="replace").strip() if title else ""
    if status == 429 or "rate limit reached" in title.lower():
        return {"outcome": "rate_limited", "page_title": title}
    if status in {401, 403} or "session verification" in title.lower():
        return {"outcome": "access_blocked", "page_title": title}
    if status in {301, 302, 303, 307, 308} and headers.get("location"):
        target = urljoin(url, headers["location"])
        try:
            parsed = split_replay(target)
        except ValueError:
            return {"outcome": "redirect_outside_collection", "location": target}
        if parsed["congress"] != split_replay(url)["congress"]:
            return {"outcome": "redirect_outside_collection", "location": target}
        if parsed["selector_kind"] == "timestamp":
            return {"outcome": "capture_redirect_observed", "location": target,
                    "resolved_prefix": parsed["redirect_prefix"], "resolved_original_url": parsed["original_url"]}
        return {"outcome": "intermediate_redirect", "location": target}
    parsed = split_replay(url)
    if status == 200 and parsed["selector_kind"] == "timestamp" and headers.get("memento-datetime"):
        return {"outcome": "capture_headers_observed", "resolved_prefix": parsed["redirect_prefix"],
                "resolved_original_url": parsed["original_url"]}
    return {"outcome": "unresolved_response", "page_title": title}


def resolve_zyte(mapping, output, env_file, ca_bundle, limit=600, delay=2.0, geolocation=None):
    """Resolve homepage routes via Zyte. Stop on block pages; retain each observation."""
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new output directory to preserve earlier redirect observations")
    if limit < 1 or delay < 0:
        raise ValueError("Request limit must be positive and delay must be nonnegative")
    token = os.environ.get("ZYTE_TOKEN")
    if not token and env_file:
        for line in env_file.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "ZYTE_TOKEN":
                token = value.strip().strip('"').strip("'")
    if not token:
        raise ValueError("Supply ZYTE_TOKEN or --env-file containing ZYTE_TOKEN")
    proxy = "https://" + quote(token, safe="") + ":@api.zyte.com:8014"
    session = requests.Session()
    session.trust_env = False
    session.proxies = {"http": proxy, "https": proxy}
    session.verify = str(ca_bundle)
    session.headers["Zyte-Disable-Follow-Redirect"] = "true"
    if geolocation:
        session.headers["Zyte-Geolocation"] = geolocation
    output.mkdir(parents=True, exist_ok=True)
    urls = sorted({row["published_replay_url"] for row in mapping["records"]},
                  key=lambda u: (-split_replay(u)["congress"], u))
    receipts, stopped = [], "completed"
    for published in urls[:limit]:
        # The www -> bare-host redirect is common to all source links and does
        # not select a capture. Start at the canonical archive host.
        url = published.replace("https://www.webharvest.gov/", ROOT + "/", 1)
        for hop in range(6):
            receipt = {"published_replay_url": published, "requested_url": url,
                       "requested_at": now(), "route": "zyte_https_proxy", "geolocation": geolocation,
                       "hop": hop, "method": "GET", "automatic_redirects": False}
            try:
                with session.get(url, allow_redirects=False, stream=True, timeout=(15, 45)) as response:
                    headers = {k.lower(): v for k, v in response.headers.items()
                               if k.lower() not in {"set-cookie", "authorization", "proxy-authorization"}}
                    prefix = next(response.iter_content(16384), b"") if response.status_code == 200 else b""
                    receipt.update(status=response.status_code, headers=headers,
                                   prefix_bytes=len(prefix), prefix_sha256=sha256(prefix),
                                   **classify_redirect(url, response.status_code, headers, prefix))
                    if prefix:
                        body_name = sha256((published + str(hop)).encode()) + ".prefix"
                        (output / body_name).write_bytes(prefix)
                        receipt["body_prefix_file"] = body_name
            except requests.RequestException as error:
                # Request exception strings can contain proxy credentials.
                receipt.update(outcome="transport_error", error_type=type(error).__name__)
            receipts.append(receipt)
            save(output / "receipts.json", receipts)
            print(json.dumps({"done": len({r["published_replay_url"] for r in receipts}),
                              "total": len(urls), "url": published, "outcome": receipt["outcome"]}), flush=True)
            if receipt["outcome"] in {"rate_limited", "access_blocked"}:
                stopped = receipt["outcome"]
                break
            if receipt["outcome"] != "intermediate_redirect":
                break
            url = receipt["location"]
            time.sleep(delay)
        if stopped != "completed":
            break
        time.sleep(delay)
    observed = {r["published_replay_url"]: r for r in receipts}
    resolved = {u: r for u, r in observed.items() if r.get("resolved_prefix")}
    prefixes = {}
    for row in mapping["records"]:
        if row["published_replay_url"] in resolved:
            prefix = resolved[row["published_replay_url"]]["resolved_prefix"]
            values = prefixes.setdefault(row["domain"], {}).setdefault(str(row["congress"]), [])
            if prefix not in values:
                values.append(prefix)
    save(output / "resolved-domain-prefixes.json", prefixes)
    if stopped == "completed" and len(observed) < len(urls):
        stopped = "request_limit"
    summary = {"checked_at": now(), "stop_reason": stopped, "unique_published_links": len(urls),
               "attempted_links": len(observed), "resolved_links": len(resolved),
               "unattempted_links": len(urls) - len(observed),
               "outcomes": dict(Counter(r["outcome"] for r in observed.values())),
               "scope": "Homepage redirect/header observations only; no PDF availability check.",
               "mapping_canonical_sha256": sha256(json.dumps(mapping, sort_keys=True, ensure_ascii=False).encode())}
    save(output / "summary.json", summary)
    return summary


def join_targets(mapping, targets, output, exclusions=(), include_www=False):
    """Join a pinned local backlog snapshot. Exclusions are explicit URL-keyed JSON files."""
    excluded, inputs = set(), []
    for path in exclusions:
        raw = path.read_bytes()
        values = json.loads(raw)
        if not isinstance(values, dict):
            raise ValueError(f"Expected URL-keyed recovery object: {path}")
        excluded.update(values)
        inputs.append({"path": str(path.resolve()), "sha256": sha256(raw), "urls": len(values)})
    raw = targets.read_bytes()
    # Decode the bytes that were hashed so a concurrently changing input cannot mix snapshots.
    import io
    records = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    counts, seen, unmatched = Counter(), set(), Counter()
    output.mkdir(parents=True, exist_ok=True)
    with (output / "pdf-candidates.jsonl").open("w") as stream, (output / "unmatched-pdfs.jsonl").open("w") as missing:
        for row in records:
            url = row["url"]
            if url in seen:
                continue
            seen.add(url)
            counts["unique_input_urls"] += 1
            if url in excluded:
                counts["excluded_recovered_urls"] += 1
                continue
            if not urlsplit(url).path.lower().endswith(".pdf"):
                counts["non_pdf_suffix_urls"] += 1
                continue
            counts["remaining_pdf_suffix_urls"] += 1
            candidates = lookup(mapping, url, include_www=include_www)
            if candidates:
                counts["pdf_urls_with_candidates"] += 1
                counts["candidate_urls"] += len(candidates)
                for candidate in candidates:
                    stream.write(json.dumps(candidate) + "\n")
            else:
                counts["pdf_urls_without_domain_match"] += 1
                unmatched[urlsplit(url).hostname] += 1
                missing.write(json.dumps({"url": url, "reason": "domain_not_in_committee_map"}) + "\n")
    summary = {"generated_at": now(), "input": {"path": str(targets.resolve()), "sha256": sha256(raw)},
               "mapping_canonical_sha256": sha256(json.dumps(mapping, sort_keys=True, ensure_ascii=False).encode()),
               "exclusion_inputs": inputs, "counts": dict(counts), "include_www_variants": include_www,
               "unmatched_domains": dict(unmatched.most_common()),
               "scope": "Local snapshot; PDF identified by URL path suffix, not MIME. Extensionless downloads excluded. Candidates do not establish archive availability. No cloud state refreshed or changed."}
    save(output / "lookup-summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--output", type=Path, default=DEFAULT_MAP)
    build_parser.add_argument("--offline", action="store_true")
    build_parser.add_argument("--delay", type=float, default=1.0)
    lookup_parser = sub.add_parser("lookup")
    lookup_parser.add_argument("url")
    lookup_parser.add_argument("--congress", type=int)
    join_parser = sub.add_parser("join")
    join_parser.add_argument("--targets", type=Path, required=True)
    join_parser.add_argument("--output", type=Path, required=True)
    join_parser.add_argument("--exclude-recovered", type=Path, action="append", default=[])
    resolve_parser = sub.add_parser("resolve-zyte")
    resolve_parser.add_argument("--map", type=Path, default=DEFAULT_MAP / "map.json")
    resolve_parser.add_argument("--output", type=Path, required=True)
    resolve_parser.add_argument("--env-file", type=Path)
    resolve_parser.add_argument("--ca-bundle", type=Path, required=True)
    resolve_parser.add_argument("--geolocation")
    resolve_parser.add_argument("--limit", type=int, default=600)
    resolve_parser.add_argument("--delay", type=float, default=2.0)
    for command in (lookup_parser, join_parser):
        command.add_argument("--map", type=Path, default=DEFAULT_MAP / "map.json")
        command.add_argument("--include-www", action="store_true")
    args = parser.parse_args()
    if args.command == "build":
        build(args.output, offline=args.offline, delay=args.delay)
    else:
        mapping = json.loads(args.map.read_text())
        if args.command == "lookup":
            print(json.dumps(lookup(mapping, args.url, args.congress, args.include_www), indent=2))
        elif args.command == "resolve-zyte":
            print(json.dumps(resolve_zyte(mapping, args.output, args.env_file, args.ca_bundle,
                                          args.limit, args.delay, args.geolocation), indent=2))
        else:
            print(json.dumps(join_targets(mapping, args.targets, args.output, args.exclude_recovered, args.include_www), indent=2))


if __name__ == "__main__":
    main()
