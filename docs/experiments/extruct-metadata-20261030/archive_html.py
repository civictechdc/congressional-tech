# /// script
# requires-python = ">=3.14"
# dependencies = ["extruct==0.18.0", "warcio==1.7.5"]
# ///
"""Read HTML response payloads in the supplementary WARC/ARC inventory."""

import argparse
import gzip
import hashlib
import json
from collections import Counter
from io import BytesIO
from pathlib import Path

from extract import is_html
from warcio.archiveiterator import ArchiveIterator


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output
    extra = out / "additional"
    known = {json.loads(line)["sha256"] for line in (out / "bodies.jsonl").open()}
    counts = Counter()
    errors = []
    with (
        (extra / "html-bodies.jsonl").open("w") as manifest,
        (extra / "html-members.jsonl").open("w") as members,
    ):
        for line in (extra / "bodies.jsonl").open():
            parent = json.loads(line)
            try:
                with gzip.open(parent["local_path"], "rb") as source:
                    raw = source.read()
                assert (
                    len(raw) == parent["bytes"]
                    and hashlib.sha256(raw).hexdigest() == parent["sha256"]
                )
                counts["verified_parent_bodies"] += 1
                if is_html(raw):
                    counts["loose_html"] += 1
                    manifest.write(json.dumps(parent) + "\n")
                    continue
                if not any(
                    "warc" in (m or "") or "arc+gzip" in (m or "")
                    for m in parent["media_types"]
                ):
                    counts["other_non_html"] += 1
                    continue
                for index, record in enumerate(
                    ArchiveIterator(BytesIO(raw), arc2warc=True)
                ):
                    counts["archive_records"] += 1
                    if record.rec_type not in {"response", "resource"}:
                        continue
                    stream = record.content_stream()
                    prefix = stream.read(65536)
                    if not is_html(prefix):
                        counts["non_html_responses"] += 1
                        continue
                    body = prefix + stream.read()
                    sha = hashlib.sha256(body).hexdigest()
                    url = record.rec_headers.get_header("WARC-Target-URI")
                    status = (
                        record.http_headers.get_statuscode()
                        if record.http_headers
                        else None
                    )
                    key = f"archive-member:{parent['sha256']}:{index}"
                    member = {
                        "parent_body_key": parent["body_key"],
                        "parent_sha256": parent["sha256"],
                        "record_index": index,
                        "sha256": sha,
                        "url": url,
                        "bytes": len(body),
                        "duplicate_known_body": sha in known,
                    }
                    members.write(json.dumps(member) + "\n")
                    counts["html_response_records"] += 1
                    if sha in known:
                        counts["duplicate_html_payloads"] += 1
                        continue
                    path = extra / "html-payloads" / (sha + ".gz")
                    path.parent.mkdir(exist_ok=True)
                    path.write_bytes(gzip.compress(body, mtime=0))
                    metadata = {
                        "body_key": key,
                        "sha256": sha,
                        "bytes": len(body),
                        "urls": [url] if url else parent["urls"],
                        "statuses": [int(status)]
                        if status and status.isdigit()
                        else [],
                        "families": ["archive/html-responses"],
                        "fidelities": ["decoded-archive-response"],
                        "references": 1,
                        "local_path": str(path.resolve()),
                        "archive_source": member,
                    }
                    manifest.write(json.dumps(metadata) + "\n")
                    known.add(sha)
                    counts["new_html_payloads"] += 1
            except Exception as error:  # noqa: BLE001 -- record each failed archive explicitly
                errors.append(
                    {
                        "body_key": parent["body_key"],
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
    (extra / "html-summary.json").write_text(
        json.dumps({"counts": counts, "errors": errors}, indent=2)
    )
    print(json.dumps({"counts": counts, "errors": errors}, indent=2))


if __name__ == "__main__":
    main()
