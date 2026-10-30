"""Summarize retained extraction results without rereading source HTML."""

import argparse
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


def short(value):
    return value.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def declared_url(record):
    for link in record["links"]:
        if "canonical" in link.get("rel", "").lower().split() and link.get(
            "href", ""
        ).startswith(("http://", "https://")):
            return link["href"], "canonical"
    for meta in record["meta"]:
        if (
            meta.get("property") or meta.get("name") or ""
        ).lower() == "og:url" and meta.get("content", "").startswith(
            ("http://", "https://")
        ):
            return meta["content"], "og:url"
    return "", None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    counts = Counter()
    domains = defaultdict(Counter)
    families = defaultdict(Counter)
    syntax_all = Counter()
    syntax_eligible = Counter()
    types = defaultdict(Counter)
    fields = defaultdict(Counter)
    features = Counter()
    feature_domains = defaultdict(Counter)
    examples = defaultdict(list)
    urls = set()
    errors = []
    keys = set()
    capture_url_missing = 0
    hearing_records = []

    def example(name, record, url, domain, values):
        if len(examples[name]) < 8 and not any(
            e["domain"] == domain for e in examples[name]
        ):
            examples[name].append(
                {
                    "sha256": record["sha256"],
                    "body_key": record["body_key"],
                    "url": url,
                    "domain": domain,
                    "values": values,
                }
            )

    with gzip.open(args.metadata, "rt") as stream:
        for line in stream:
            r = json.loads(line)
            assert r["body_key"] not in keys, r["body_key"]
            keys.add(r["body_key"])
            counts[r["outcome"]] += 1
            if r["outcome"] == "error":
                errors.append({k: r.get(k) for k in ("body_key", "urls", "error")})
            if r["outcome"] not in {"ok", "partial"}:
                continue
            counts["html_bodies"] += 1
            counts["html_bytes"] += r["bytes"]
            counts["capture_references"] += r["references"]
            urls.update(r["urls"])
            counts["with_metadata"] += bool(r["syntaxes"])
            source_url = r.get("url")
            if not source_url:
                capture_url_missing += 1
            declaration, declaration_kind = declared_url(r)
            url = source_url or declaration
            domain = (urlsplit(url).hostname or "(unknown)").removeprefix("www.")
            counts["domain_from_page_declaration"] += bool(
                not source_url and declaration
            )
            statuses = [s for s in r["statuses"] if isinstance(s, int)]
            http_error = bool(statuses) and all(s >= 400 for s in statuses)
            eligible = not r["error_page_hint"] and not http_error
            counts["error_title_hints"] += r["error_page_hint"]
            counts["only_error_http_statuses"] += http_error
            counts["not_flagged_as_error"] += eligible
            domains[domain]["bodies"] += 1
            domains[domain]["not_flagged_as_error"] += eligible
            for family in r["families"]:
                families[family]["bodies"] += 1
                families[family]["not_flagged_as_error"] += eligible
                for syntax in r["syntaxes"]:
                    families[family][syntax] += 1
            for syntax in r["syntaxes"]:
                syntax_all[syntax] += 1
                domains[domain][syntax] += 1
                syntax_eligible[syntax] += eligible
                node_types = set()
                properties = set()
                for node in nodes(r["metadata"][syntax]):
                    ts = node.get("@type", node.get("type", []))
                    if isinstance(ts, str):
                        ts = [ts]
                    if isinstance(ts, list):
                        node_types.update(t for t in ts if isinstance(t, str))
                    properties.update(
                        k for k in node if k not in {"@context", "@id", "@type"}
                    )
                    if syntax == "opengraph" and isinstance(
                        node.get("properties"), list
                    ):
                        properties.update(
                            p[0]
                            for p in node["properties"]
                            if isinstance(p, list) and len(p) == 2
                        )
                    if syntax == "dublincore" and "name" in node and "content" in node:
                        properties.add("dc:" + node["name"])
                types[syntax].update(node_types)
                fields[syntax].update(properties)
            for syntax, message in r.get("errors", {}).items():
                errors.append(
                    {
                        "body_key": r["body_key"],
                        "url": url,
                        "syntax": syntax,
                        "error": message,
                    }
                )
            if not eligible:
                continue
            found = defaultdict(list)
            for node in nodes(r["metadata"].get("rdfa", [])):
                for key in (
                    "http://purl.org/rss/1.0/modules/content/encoded",
                    "http://schema.org/articleBody",
                ):
                    if node.get(key):
                        found["rdfa_article_body"].append(node[key])
            for node in nodes(r["metadata"].get("json-ld", [])):
                ts = node.get("@type", [])
                if isinstance(ts, str):
                    ts = [ts]
                ts = [short(t) for t in ts if isinstance(t, str)]
                if any(t.endswith("Event") or t == "EventSeries" for t in ts):
                    found["structured_event"].append(node)
                if "VideoObject" in ts:
                    found["structured_video"].append(node)
                if "Person" in ts:
                    found["structured_person"].append(node)
                if set(ts) & {"Article", "NewsArticle", "BlogPosting"}:
                    found["structured_article"].append(node)
                if "Organization" in ts and node.get("sameAs"):
                    found["organization_social_links"].append(node["sameAs"])
                for key in (
                    "datePublished",
                    "dateModified",
                    "startDate",
                    "endDate",
                    "eventStatus",
                    "location",
                    "organizer",
                    "keywords",
                    "author",
                    "license",
                ):
                    if node.get(key):
                        found["jsonld_" + key].append(node[key])
            for node in nodes(r["metadata"].get("microdata", [])):
                ts = node.get("type", [])
                if isinstance(ts, str):
                    ts = [ts]
                if any(short(t).endswith("Event") for t in ts if isinstance(t, str)):
                    found["microdata_event"].append(node)
                if any(short(t) == "VideoObject" for t in ts if isinstance(t, str)):
                    found["microdata_video"].append(node)
            for node in nodes(r["metadata"].get("microformat", [])):
                if "h-card" in node.get("type", []):
                    found["microformat_people"].append(node)
                if "h-event" in node.get("type", []):
                    found["microformat_event"].append(node)
            if found.get("microformat_event"):
                hearing_records.append(
                    {
                        **{
                            k: r[k]
                            for k in (
                                "sha256",
                                "url",
                                "urls",
                                "local_path",
                                "title",
                                "statuses",
                                "families",
                            )
                        },
                        "declared_url": declaration,
                        "events": found["microformat_event"],
                    }
                )
            og = r["metadata"].get("opengraph", [])
            og_pairs = [p for block in og for p in block.get("properties", [])]
            repeated = {
                k: n for k, n in Counter(p[0] for p in og_pairs).items() if n > 1
            }
            if repeated:
                found["repeated_opengraph"].append(repeated)
            for key in (
                "og:description",
                "og:image",
                "og:video",
                "og:video:url",
                "og:video:secure_url",
                "article:published_time",
                "article:modified_time",
                "article:tag",
                "article:author",
            ):
                values = [p[1] for p in og_pairs if p[0] == key and p[1]]
                if values:
                    found[key].extend(values)
            if declaration:
                found["declared_page_url"].append(
                    {"kind": declaration_kind, "url": declaration}
                )
            for m in r["meta"]:
                key = (m.get("name") or m.get("property") or "").lower()
                if key.startswith("twitter:") and m.get("content"):
                    found["twitter_cards"].append(m)
                if key in {
                    "keywords",
                    "citation_title",
                    "citation_author",
                    "citation_date",
                    "citation_publication_date",
                    "citation_pdf_url",
                } and m.get("content"):
                    found["meta_" + key].append(m["content"])
            for feature, values in found.items():
                features[feature] += 1
                feature_domains[feature][domain] += 1
                example(feature, r, url, domain, values)
    result = {
        "counts": counts,
        "unique_html_capture_urls": len(urls),
        "html_bodies_without_capture_url": capture_url_missing,
        "syntaxes_all": syntax_all,
        "syntaxes_not_flagged_as_error": syntax_eligible,
        "domains": dict(sorted(domains.items(), key=lambda x: -x[1]["bodies"])),
        "families": families,
        "types": types,
        "fields": fields,
        "features_not_flagged_as_error": features,
        "feature_domains": feature_domains,
        "examples": examples,
        "errors": errors,
    }
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    (args.output.parent / "hearing-microformats.json").write_text(
        json.dumps(
            {
                "counts": {
                    "bodies": len(hearing_records),
                    "events": sum(len(r["events"]) for r in hearing_records),
                },
                "records": hearing_records,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k
                in {
                    "counts",
                    "unique_html_capture_urls",
                    "syntaxes_all",
                    "features_not_flagged_as_error",
                }
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
