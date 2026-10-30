# /// script
# requires-python = ">=3.14"
# dependencies = ["extruct==0.18.0"]
# ///
"""Extract six metadata syntaxes from every distinct retained HTML body.

The manifest retains all URL occurrences. Extraction uses one recorded URL per
body for relative URL resolution; that choice is recorded in each result.
No scripts execute, no government pages are fetched, and source files are read-only.
"""

import argparse
import gzip
import hashlib
import importlib.metadata
import json
import re
import resource
import signal
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import extruct
from lxml import html
from w3lib.encoding import html_to_unicode
from w3lib.html import get_base_url

SYNTAXES = ["microdata", "json-ld", "opengraph", "microformat", "rdfa", "dublincore"]
METADATA_MARKERS = re.compile(
    r"<(?:meta|link|script)\b|itemscope|itemprop|"
    r"\b(?:class|about|property|resource|typeof|vocab|prefix|rel|rev|role|datatype|xmlns)[\w:-]*\s*=",
    re.IGNORECASE,
)


def is_html(raw):
    sample = raw[:65536]
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        sample = sample.decode("utf-16", errors="replace").encode("utf-8")
    prefix = sample.lstrip(b"\xef\xbb\xbf\x00\t\n\r ")
    return prefix.startswith(b"<") and bool(
        re.search(
            rb"<(?:!doctype\s+html|html|head|body|title|meta|div|p|script)\b",
            sample,
            re.IGNORECASE,
        )
    )


def timeout(signum, frame):
    raise TimeoutError("Page extraction exceeded 30 seconds")


def meaningful(syntax, values):
    if syntax == "dublincore":
        return any(v.get("elements") or v.get("terms") for v in values)
    return bool(values)


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


def extract(body, syntaxes=None):
    syntaxes = SYNTAXES if syntaxes is None else syntaxes
    started = time.monotonic()
    result = {
        k: body[k]
        for k in (
            "body_key",
            "sha256",
            "bytes",
            "urls",
            "families",
            "statuses",
            "fidelities",
            "references",
        )
    }
    result["local_path"] = body["local_path"]
    try:
        signal.signal(signal.SIGALRM, timeout)
        signal.alarm(30)
        with gzip.open(body["local_path"], "rb") as stream:
            raw = stream.read()
        if (
            hashlib.sha256(raw).hexdigest() != body["sha256"]
            or len(raw) != body["bytes"]
        ):
            raise ValueError("Stored HTML does not match its retained digest/length")
        # Page-family URLs also return PDFs and JSON. Embedded tag-like bytes
        # inside those files do not make the response an HTML document.
        if not is_html(raw):
            result["outcome"] = "non_html"
            result["prefix"] = raw[:120].decode("utf-8", errors="replace")
            return result
        encoding, text = html_to_unicode(None, raw, default_encoding="utf-8")
        result["encoding"] = encoding
        urls = body["urls"]
        url = next(
            (u for u in urls if "web.archive.org/" not in u), urls[0] if urls else ""
        )
        base_url = get_base_url(text, url) if url else ""
        result["url"] = url
        result["base_url"] = base_url
        result["domain"] = (urlsplit(url).hostname or "(unknown)").removeprefix("www.")
        result["errors"] = {}
        try:
            # GovInfo transcripts often contain only title/body/pre. None of
            # extruct's six syntaxes can exist without one of these markers.
            # Avoid its expensive XML DOM conversion on unannotated transcripts.
            result["extruct_syntaxes"] = (
                syntaxes if METADATA_MARKERS.search(text) else []
            )
            metadata = (
                extruct.extract(
                    raw,
                    encoding=encoding,
                    base_url=base_url,
                    syntaxes=syntaxes,
                    errors="strict",
                )
                if result["extruct_syntaxes"]
                else {s: [] for s in SYNTAXES}
            )
        except Exception as exc:
            if isinstance(exc, TimeoutError):
                raise
            # A broken syntax must not suppress other syntaxes, nor look empty.
            metadata = {}
            for syntax in syntaxes:
                try:
                    metadata.update(
                        extruct.extract(
                            raw,
                            encoding=encoding,
                            base_url=base_url,
                            syntaxes=[syntax],
                            errors="strict",
                        )
                    )
                except Exception as error:
                    if isinstance(error, TimeoutError):
                        raise
                    result["errors"][syntax] = f"{type(error).__name__}: {error}"
        result["metadata"] = metadata
        result["syntaxes"] = [s for s in SYNTAXES if meaningful(s, metadata.get(s, []))]
        # extruct does not cover generic HTML meta, Twitter cards, or link rels.
        tree = html.fromstring(
            raw, parser=html.HTMLParser(encoding=encoding, no_network=True)
        )
        result["title"] = " ".join(tree.xpath("//title/text()"))
        result["meta"] = [dict(n.attrib) for n in tree.xpath("//meta")]
        result["links"] = [
            dict(n.attrib)
            for n in tree.xpath("//link[@rel]")
            if set((n.get("rel") or "").lower().split())
            & {"canonical", "alternate", "license", "author"}
        ]
        result["data_scripts"] = [
            dict(n.attrib)
            for n in tree.xpath("//script")
            if n.get("type") in {"application/json", "application/ld+json"}
            or n.get("id") == "__NEXT_DATA__"
        ]
        result["itemprops"] = dict(Counter(tree.xpath("//@itemprop")))
        title = result["title"].lower()
        result["error_page_hint"] = bool(
            re.search(
                r"access denied|just a moment|page not found|404 not found|403 forbidden|attention required|request rejected|error 404|access to this page has been denied",
                title,
            )
        )
        result["outcome"] = "partial" if result["errors"] else "ok"
    except Exception as error:  # noqa: BLE001 -- a bad body must remain a counted failure
        result["outcome"] = "error"
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        signal.alarm(0)
        result["seconds"] = round(time.monotonic() - started, 4)
        result["worker_peak_rss"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return result


def summarize(path):
    counts = Counter()
    syntax_counts = Counter()
    domain_counts = defaultdict(Counter)
    types = defaultdict(Counter)
    fields = defaultdict(Counter)
    examples = defaultdict(list)
    metadata_fields = Counter()
    syntax_seconds = 0
    max_rss = 0
    with gzip.open(path, "rt") as stream:
        for line in stream:
            r = json.loads(line)
            counts[r["outcome"]] += 1
            syntax_seconds += r["seconds"]
            max_rss = max(max_rss, r["worker_peak_rss"])
            if r["outcome"] not in {"ok", "partial"}:
                continue
            counts["html_bodies"] += 1
            counts["decoded_bytes"] += r["bytes"]
            counts["capture_references"] += r["references"]
            counts["error_page_hints"] += r["error_page_hint"]
            counts["bodies_with_metadata"] += bool(r["syntaxes"])
            domain = r["domain"]
            domain_counts[domain]["bodies"] += 1
            domain_counts[domain]["error_page_hints"] += r["error_page_hint"]
            metadata_fields.update(
                {
                    (
                        m.get("name") or m.get("property") or m.get("http-equiv") or ""
                    ).lower()
                    for m in r["meta"]
                }
            )
            for syntax in r["syntaxes"]:
                syntax_counts[syntax] += 1
                domain_counts[domain][syntax] += 1
                seen_fields, seen_types = set(), set()
                for node in nodes(r["metadata"][syntax]):
                    value = node.get("@type", node.get("type", []))
                    if isinstance(value, str):
                        value = [value]
                    if isinstance(value, list):
                        seen_types.update(v for v in value if isinstance(v, str))
                    seen_fields.update(node)
                    props = node.get("properties")
                    if isinstance(props, list):
                        seen_fields.update(
                            p[0] for p in props if isinstance(p, list) and len(p) == 2
                        )
                fields[syntax].update(seen_fields)
                types[syntax].update(seen_types)
                if len(examples[syntax]) < 5:
                    examples[syntax].append(
                        {"sha256": r["sha256"], "url": r["url"], "domain": domain}
                    )
    return {
        "counts": counts,
        "syntaxes": syntax_counts,
        "domains": domain_counts,
        "types": types,
        "fields": fields,
        "meta_fields": metadata_fields,
        "examples": examples,
        "total_worker_seconds": round(syntax_seconds, 2),
        "max_worker_peak_rss": max_rss,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    bodies = [json.loads(line) for line in args.manifest.read_text().splitlines()]
    if args.limit:
        bodies = bodies[: args.limit]
    path = args.output / "metadata.jsonl.gz"
    done = set()
    if path.exists():
        if not args.resume:
            raise FileExistsError("Use a new output directory or --resume")
        with gzip.open(path, "rt") as stream:
            done = {json.loads(line)["body_key"] for line in stream}
        bodies = [b for b in bodies if b["body_key"] not in done]
    started = time.monotonic()
    last_progress = started
    with (
        ProcessPoolExecutor(max_workers=args.workers) as pool,
        gzip.open(path, "at" if done else "wt", compresslevel=6) as stream,
    ):
        for count, result in enumerate(
            pool.map(extract, bodies, chunksize=8, buffersize=args.workers * 2), 1
        ):
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            if time.monotonic() - last_progress > 30:
                print(
                    json.dumps(
                        {
                            "processed": count,
                            "total": len(bodies),
                            "elapsed_seconds": round(time.monotonic() - started),
                        }
                    ),
                    flush=True,
                )
                last_progress = time.monotonic()
    summary = summarize(path)
    summary.update(
        elapsed_seconds=round(time.monotonic() - started, 2),
        workers=args.workers,
        versions={
            name: importlib.metadata.version(name)
            for name in ("extruct", "lxml", "rdflib", "w3lib", "mf2py", "pyRdfa3")
        },
    )
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in summary.items()
                if k
                in {
                    "counts",
                    "syntaxes",
                    "elapsed_seconds",
                    "total_worker_seconds",
                    "max_worker_peak_rss",
                    "versions",
                }
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
