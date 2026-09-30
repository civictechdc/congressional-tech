"""Enrich legacy Senate state from retained HTML without a new acquisition.

Live observations are protected. A cached page can enrich legacy state only when
its parsed text lines exactly match the saved lines. Existing witness/document
rows and associations are retained, so richer metadata does not change their IDs.
Run with explicit, distinct input/output paths; nothing fetches or rematches.

Compatibility and source-specific protection rules:
/docs/congress-api-contracts.md#replay-protection-matrix
"""

import argparse
import gzip
import hashlib
import json
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from congress_api.acquisition.senate import DOCUMENT_FIELDS, PAGE_FIELDS, WITNESS_FIELDS
from congress_api.matching.senate_pages import mark_possible_matches, retained_matches
from congress_api.parsers.senate import PARSER_VERSION, parsed
from congress_api.parsers.senate_page import source_details
from congress_api.retention.senate import cached_html_path
from congress_api.retention.tables import read_state, write_csv, write_state


def replay(state, cache, *, meetings, parsed_at=None):
    result, counts, pages = deepcopy(state), Counter(), []
    parsed_at = parsed_at or datetime.now(UTC).isoformat()
    for host, site in result.items():
        for url, page in site.get("pages", {}).items():
            counts["pages"] += 1
            path = cached_html_path(cache, url)
            reason = None
            if page.get("retrieved_at") or page.get("observation_check") or (page.get("last_check") or {}).get("mode") == "live":
                reason = "protected_live_observation"
            elif page.get("parser_version", 0) >= PARSER_VERSION:
                reason = "current_parser"
            elif not path.is_file():
                reason = "no_cached_html"
            if reason:
                counts[reason] += 1
                pages.append({"url": url, "status": reason})
                continue
            body = path.read_bytes()
            raw = body.decode("utf-8", "replace")
            fresh = parsed(raw, url)
            if not fresh["title"] or fresh["lines"] != page.get("lines"):
                counts["different_or_unrecognized_page"] += 1
                pages.append({"url": url, "status": "different_or_unrecognized_page"})
                continue
            metadata, people, content = source_details(raw, url, page.get("witnesses") or [])
            page["document_metadata"], page["witness_metadata"], page["page_metadata"] = metadata, people, content
            page["document_labels"] = {**fresh.get("document_labels", {}), **page.get("document_labels", {})}
            # Preserve the existing source rows and their identity. Additional
            # directly linked formats do not overwrite a previous description.
            known = {document[2] for document in page.get("documents", [])}
            additions = [list(document) for document in fresh["documents"] if document[2] not in known]
            page.setdefault("documents", []).extend(additions)
            counts["additional_document_urls"] += len(additions)
            if fresh.get("event") and not page.get("event"):
                page["event"] = fresh["event"]
                counts["event_headers_added"] += 1
            page["parser_version"] = PARSER_VERSION
            page["cache_replay"] = {"cache_file": path.name, "raw_sha256": hashlib.sha256(body).hexdigest(),
                                    "parsed_at": parsed_at, "parser_version": PARSER_VERSION,
                                    "acquisition_time": None, "basis": "retained HTML with identical saved text lines"}
            counts["replayed_pages"] += 1
            counts["documents_with_witness_ownership"] += sum(bool(value["witness_indexes"]) for value in metadata.values())
            counts["witness_cards"] += len(people)
            counts["witness_locations"] += sum(bool(value.get("location")) for value in people.values())
            counts["witness_panels"] += sum(bool(value.get("panel")) for value in people.values())
            counts["pages_with_embedded_media"] += bool(content.get("media"))
            pages.append({"url": url, "status": "replayed", "raw_sha256": page["cache_replay"]["raw_sha256"],
                          "added_document_urls": [document[2] for document in additions],
                          "owned_documents": sum(bool(value["witness_indexes"]) for value in metadata.values())})
    # New structured event headers must retain the same native-duplicate guard
    # as live collection. This records candidates; it never changes a match.
    mark_possible_matches(meetings, result)
    return result, {"counts": dict(counts), "pages": pages}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True, help="seed cache root; HTML is read from senate_pages/")
    parser.add_argument("--meetings", type=Path, required=True, help="native meeting JSONL.gz for the same-day duplicate guard")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir / "senate.json.gz"
    if output.resolve() == args.input.resolve():
        parser.error("the output must differ from the input state")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.meetings, "rt", encoding="utf-8") as stream:
        meetings = [json.loads(line) for line in stream]
    state, report = replay(read_state(args.input), args.cache, meetings=meetings)
    write_state(output, state)
    for name, rows, fields in zip(("senate_hearing_pages_found", "senate_witnesses_found", "senate_documents_found"),
                                  retained_matches(state), (PAGE_FIELDS, WITNESS_FIELDS, DOCUMENT_FIELDS)):
        write_csv(args.output_dir / f"{name}.csv", rows, fields)
    (args.output_dir / "replay-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report["counts"], indent=2))


if __name__ == "__main__":
    main()
