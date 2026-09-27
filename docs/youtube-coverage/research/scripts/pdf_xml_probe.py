"""Try the .xml sibling of every PDF URL in one or more document CSVs.

    python docs/youtube-coverage/research/scripts/pdf_xml_probe.py

Defaults to house_documents_found.csv. Only the final path extension changes;
this does not invent alternate directories or assume a PDF has an XML version.
GET responses must parse as XML and must not be HTML/error pages. Results are
checkpointed after each URL; successful XML is retained with its SHA-256 digest.
Reruns skip completed checks. Use --retry to repeat inconclusive checks.
"""
import argparse
import collections
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit, urlunsplit

from lxml import etree
import requests

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_INPUT = ROOT / "docs/youtube-coverage/research/data/house_documents_found.csv"
RETRYABLE = {"blocked", "network_error", "http_error", "too_large"}
MAX_BYTES = 20 * 1024 * 1024


def xml_url(pdf_url):
    """Preserve the URL except its PDF extension; malformed URLs remain visible."""
    parts = urlsplit(html.unescape(pdf_url.strip()))
    if not parts.path.lower().endswith(".pdf"):
        return ""
    if (parts.scheme not in {"http", "https"} or not parts.hostname
            or ":" in parts.netloc or re.search(r"\s", parts.netloc)):
        return ""
    return urlunsplit(parts._replace(path=parts.path[:-4] + ".xml", fragment=""))


def inventory(paths):
    found, sources = {}, []
    for path in paths:
        data = path.read_bytes()
        sources.append({"path": str(path), "sha256": hashlib.sha256(data).hexdigest()})
        with io.StringIO(data.decode("utf-8"), newline="") as stream:
            for row in csv.DictReader(stream):
                pdf = row.get("url", "").strip()
                if not urlsplit(pdf).path.lower().endswith(".pdf"):
                    continue
                item = found.setdefault(pdf, {"pdf_url": pdf, "xml_url": xml_url(pdf),
                                             "references": []})
                item["references"].append({"source": str(path), "event_id": row.get("event_id", ""),
                                           "kind": row.get("kind", ""), "name": row.get("name", "")})
    return found, sources


def classify(body):
    """Parse without resolving external entities, DTDs, or network resources."""
    stripped = body.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if stripped.startswith((b"<!doctype html", b"<html")):
        return "html", ""
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False)
    try:
        root = etree.fromstring(body, parser)
    except etree.XMLSyntaxError:
        return "not_xml", ""
    name = etree.QName(root).localname
    if name.lower() in {"html", "error", "errors", "errorresponse"}:
        return "html" if name.lower() == "html" else "xml_error", name
    return "xml", name


class Pace:
    def __init__(self, interval):
        self.interval = interval
        self.lock = threading.Lock()
        self.next_at = collections.defaultdict(float)
        self.blocks = collections.Counter()

    def wait(self, host):
        while True:
            with self.lock:
                if self.blocks[host] >= 3:
                    return False
                delay = self.next_at[host] - time.monotonic()
                if delay <= 0:
                    self.next_at[host] = time.monotonic() + self.interval
                    return True
            time.sleep(min(delay, 1))

    def cool_down(self, host, seconds):
        with self.lock:
            self.blocks[host] += 1
            self.next_at[host] = max(self.next_at[host], time.monotonic() + seconds)

    def reached(self, host):
        with self.lock:
            self.blocks[host] = 0


def probe(item, cache, pace, headers=None, retain_response=False):
    url = item["xml_url"]
    result = {"pdf_url": item["pdf_url"], "xml_url": url,
              "checked_at": datetime.now(timezone.utc).isoformat(), "status": "invalid_url",
              "http_status": "", "final_url": "", "content_type": "", "root": "",
              "bytes": 0, "sha256": "", "body_path": "", "error": ""}
    if not url:
        return result
    host = urlsplit(url).netloc
    if not pace.wait(host):
        return None  # Leave unrequested URLs pending after repeated host refusals.
    result["checked_at"] = datetime.now(timezone.utc).isoformat()
    try:
        with requests.get(url, timeout=(10, 25), stream=True,
                          headers={"User-Agent": "CongressionalTech-XML-availability-research/1.0", **(headers or {})}) as response:
            result.update(http_status=response.status_code, final_url=response.url,
                          content_type=response.headers.get("Content-Type", ""))
            if retain_response and response.status_code != 200:
                # Retain a bounded error-page excerpt for small diagnostic runs.
                excerpt = next(response.iter_content(65536), b"")
                folder = cache / "responses"
                folder.mkdir(exist_ok=True)
                target = folder / (hashlib.sha256(url.encode()).hexdigest() + ".excerpt")
                target.write_bytes(excerpt)
                result["body_path"] = str(target)
            if response.status_code in {403, 429}:
                retry = response.headers.get("Retry-After", "")
                pace.cool_down(host, max(45, min(int(retry), 600)) if retry.isdigit() else 45)
                result["status"] = "blocked"
                return result
            pace.reached(host)
            if response.status_code in {404, 410}:
                result["status"] = "not_found"
                return result
            if response.status_code != 200:
                result["status"] = "http_error"
                return result
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    result["status"] = "too_large"
                    result["bytes"] = len(body)
                    return result
            body = bytes(body)
            result["bytes"] = len(body)
            result["sha256"] = hashlib.sha256(body).hexdigest()
            result["status"], result["root"] = classify(body)
            if retain_response and result["status"] != "xml":
                folder = cache / "responses"
                folder.mkdir(exist_ok=True)
                target = folder / (hashlib.sha256(url.encode()).hexdigest() + ".body")
                target.write_bytes(body)
                result["body_path"] = str(target)
            if result["status"] == "xml":
                target = cache / "xml" / (hashlib.sha256(url.encode()).hexdigest() + ".xml")
                target.write_bytes(body)
                result["body_path"] = str(target)
    except requests.RequestException as error:
        result["status"] = "network_error"
        result["error"] = str(error)[:400]
    return result


def save_report(cache, items, results, running=True):
    relevant = [results[url] for url in items if url in results]
    summary = {"updated_at": datetime.now(timezone.utc).isoformat(),
               "running": running, "pid": os.getpid(),
               "pdf_references": sum(len(item["references"]) for item in items.values()),
               "distinct_pdf_urls": len(items), "checked": len(relevant),
               "pending": len(items) - len(relevant),
               "outcomes": dict(collections.Counter(row["status"] for row in relevant)),
               "inconclusive": sum(row["status"] in RETRYABLE for row in relevant),
               "xml_roots": dict(collections.Counter(row["root"] for row in relevant if row["status"] == "xml"))}
    temp = cache / "summary.tmp"
    temp.write_text(json.dumps(summary, indent=2) + "\n")
    temp.replace(cache / "summary.json")
    with (cache / "results.csv").open("w", newline="") as stream:
        fields = ["pdf_url", "xml_url", "status", "http_status", "root", "final_url", "content_type",
                  "bytes", "checked_at", "sha256", "body_path", "error"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(relevant)
    return summary


def main(args):
    cache = args.cache.expanduser().resolve()
    (cache / "xml").mkdir(parents=True, exist_ok=True)
    lock = (cache / "run.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(f"A probe already holds {cache / 'run.lock'}")
    items, sources = inventory([path.resolve() for path in (args.input or [DEFAULT_INPUT])])
    (cache / "sources.json").write_text(json.dumps(sources, indent=2) + "\n")
    with (cache / "inventory.jsonl").open("w") as stream:
        for item in items.values():
            stream.write(json.dumps(item) + "\n")
    results = {}
    journal = cache / "attempts.jsonl"
    if journal.exists():
        with journal.open() as stream:
            for line in stream:
                if line.strip():
                    row = json.loads(line)
                    results[row["pdf_url"]] = row
    todo = [item for url, item in items.items()
            if url not in results or (args.retry and results[url]["status"] in RETRYABLE)]
    # Stable shuffle spreads the first results across dates, committees, and kinds.
    todo.sort(key=lambda item: hashlib.sha256(item["pdf_url"].encode()).digest())
    if args.limit:
        todo = todo[:args.limit]
    print(json.dumps(save_report(cache, items, results)), flush=True)
    pace = Pace(args.interval)
    with journal.open("a", buffering=1) as stream, ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(probe, item, cache, pace) for item in todo]
        for n, future in enumerate(as_completed(futures), 1):
            row = future.result()
            if row is None:
                continue
            stream.write(json.dumps(row) + "\n")
            results[row["pdf_url"]] = row
            if n % 100 == 0:
                print(json.dumps(save_report(cache, items, results)), flush=True)
    print(json.dumps(save_report(cache, items, results, running=False)), flush=True)
    lock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", help="Document CSV with a url column; repeatable")
    parser.add_argument("--cache", type=Path, default=Path("~/hearing-text/pdf_xml_probe"))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--interval", type=float, default=0.4, help="Minimum seconds between requests to the same host")
    parser.add_argument("--limit", type=int, help="Check this many remaining URLs")
    parser.add_argument("--retry", action="store_true", help="Retry previously inconclusive responses")
    args = parser.parse_args()
    if args.workers < 1 or args.interval < 0 or (args.limit is not None and args.limit < 1):
        parser.error("workers and limit must be positive; interval must be nonnegative")
    main(args)
