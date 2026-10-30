"""Compare extracted Senate event microformats with the current listing parser.

Run in the project Python environment after generating hearing-microformats.json.
Page-declared URLs provide comparison context when capture URLs are missing;
they do not establish where the archived body was fetched.
"""

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from congress_api.parsers.senate import parse_listing_details, parse_listing_page
from congress_api.parsers.senate_page import DATE, written_day
from lxml import html


def url_key(url):
    parts = urlsplit(url)
    return parts.netloc.removeprefix("www."), parts.path, parts.query


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = json.loads((args.output / "hearing-microformats.json").read_text())
    counts = Counter()
    disagreements = []
    pm_examples = []
    event_urls = set()
    for record in source["records"]:
        url = record["url"] or record["declared_url"]
        site = urlsplit(url).netloc.removeprefix("www.")
        if not site.endswith("senate.gov"):
            continue
        counts["senate_bodies"] += 1
        with gzip.open(record["local_path"], "rt", errors="replace") as stream:
            page = stream.read()
        tree = html.fromstring(page)
        visible_days = {}
        for row in tree.xpath(
            '//*[contains(concat(" ", normalize-space(@class), " "), " vevent ")]'
        ):
            anchors = row.xpath(".//a[@href]")
            times = row.xpath(".//time")
            day = next(
                (
                    written_day(m)
                    for n in times
                    for m in DATE.finditer(n.text_content())
                ),
                None,
            )
            if day and anchors:
                visible_days[url_key(urljoin(url, anchors[0].get("href")))] = str(day)
        rows = parse_listing_page(page, site)
        details = parse_listing_details(page, site)
        current = {url_key(v[1]): v for v in rows}
        columns = {url_key(k): v for k, v in details.items()}
        counts["baseline_listing_rows"] += len(rows)
        for event in record["events"]:
            props = event["properties"]
            href = props.get("url", [""])[0]
            if not href:
                continue
            key = url_key(urljoin(url, href))
            start = props.get("start", [""])[0]
            counts["event_occurrences"] += 1
            event_urls.add(key)
            visible_day = visible_days.get(key)
            counts["visible_row_day_found"] += bool(visible_day)
            counts["metadata_day_matches_visible"] += visible_day == start[:10]
            if key in current:
                counts["matched_baseline_url"] += 1
                day = str(current[key][0])
                counts["matching_day"] += day == start[:10]
                if day != start[:10]:
                    counts["baseline_day_conflicts_with_visible_metadata_day"] += (
                        visible_day == start[:10]
                    )
                    disagreements.append(
                        {
                            "sha256": record["sha256"],
                            "page_url": url,
                            "event_url": urljoin(url, href),
                            "baseline_day": day,
                            "microformat_start": start,
                            "visible_day": visible_day,
                        }
                    )
            if key in columns:
                counts["baseline_details"] += 1
                counts["baseline_room"] += bool(columns[key].get("room"))
                counts["baseline_time"] += bool(columns[key].get("time"))
        for node in tree.xpath("//time[@datetime]"):
            value = node.get("datetime")
            visible = " ".join(node.text_content().split())
            if "PM" not in visible.upper() or "T" not in value:
                continue
            try:
                hour = int(value.split("T")[1].split(":")[0])
            except ValueError:
                continue
            if hour < 12:
                counts["pm_encoded_as_morning"] += 1
                if len(pm_examples) < 5:
                    pm_examples.append(
                        {
                            "sha256": record["sha256"],
                            "page_url": url,
                            "datetime": value,
                            "visible_text": visible,
                        }
                    )
    counts["distinct_declared_event_urls"] = len(event_urls)
    result = {
        "counts": counts,
        "day_disagreements": disagreements,
        "pm_examples": pm_examples,
        "note": "Occurrences across body versions; www prefixes normalized only for comparison. Missing capture URLs use the declared OG URL as unverified context. House pages excluded from Senate-parser comparison.",
    }
    (args.output / "hearing-microformat-comparison.json").write_text(
        json.dumps(result, indent=2)
    )
    print(
        json.dumps(
            {"counts": counts, "day_disagreement_examples": disagreements[:3]}, indent=2
        )
    )


if __name__ == "__main__":
    main()
