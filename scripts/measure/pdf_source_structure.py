"""Identify the source bytes behind the 345 historical zero-page diagnostics, without OCR."""

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import re
import zlib

import pyarrow.parquet as pq

from pdf_source_evidence import BUCKET, OCR, OUT, TRIAGE, archive_arg, lines, load, remote, require, write


def zero_page_rows(root):
    return {
        r["body_sha256"]: r
        for r in lines(root / TRIAGE)
        if "ValueError: select at least one distinct page" in ((r.get("recovery") or {}).get("error") or "")
    }


def truncated_header(prefix, size):
    """A PDF linearization dictionary records the expected size of the original."""
    if not prefix.lstrip().startswith(b"%PDF-"):
        return None
    match = re.search(rb"<<[^<>]{0,2048}/Linearized\s+[\d.]+[^<>]{0,2048}>>", prefix)
    length = re.search(rb"/L\s*(\d+)\b", match[0]) if match else None
    if length and int(length[1]) > size:
        return int(length[1])
    return None


def collect_structure(root):
    keys = zero_page_rows(root)
    require(len(keys) == 345, "zero-page diagnostic population")
    prior_path = OCR / "repairs/zero-page-cause-inventory-20261115/cause-inventory.json"
    prior = {r["body_sha256"]: r for r in load(root / prior_path)["rows"]}
    work = {r["body_sha256"]: r for r in load(root / OCR / "work-list.json")}
    cap = defaultdict(list)
    for r in pq.read_table(
        root / OCR / "captures-target.parquet",
        columns=[
            "sha256",
            "outcome",
            "complete",
            "receipt_key",
            "receipt_line",
            "capture_index",
            "requested_url",
            "url",
            "http_status",
        ],
    ).to_pylist():
        cap[r.pop("sha256").hex()].append(r)
    client, _ = remote(root)

    def inspect(sha):
        item = work[sha]
        row = dict(
            body_sha256=sha,
            diagnostic=keys[sha]["recovery"]["evidence"],
            captures=cap[sha],
            bytes=item["decoded_bytes"],
            key=item["physical_key"],
            etag=item["listed_etag"],
        )
        if sha in prior:
            return dict(
                row, bucket=prior[sha]["cause"], source=str(prior_path), details=prior[sha]["details"]
            )
        size = item["stored_bytes"]
        stop = min(8192, size) - 1
        args = dict(Bucket=BUCKET, Key=item["physical_key"], IfMatch=item["listed_etag"])
        response = client.get_object(**args, Range=f"bytes=0-{stop}")
        require(response.get("ContentRange") == f"bytes 0-{stop}/{size}", f"{sha} prefix range")
        with response["Body"] as stream:
            stored = stream.read()
        require(len(stored) == stop + 1, "short prefix")
        prefix = zlib.decompressobj(31).decompress(stored, 8192) if stored.startswith(b"\x1f\x8b") else stored
        row.update(
            prefix_hex=prefix[:96].hex(),
            prefix_bytes=len(prefix),
            prefix_sha256=sha256(prefix).hexdigest(),
            stored_prefix_bytes=len(stored),
        )
        declared = truncated_header(prefix, item["decoded_bytes"])
        if declared:
            return dict(row, bucket="incomplete_pdf_shorter_than_declared_length", declared_length=declared)
        outcomes = {c["outcome"] for c in cap[sha] if c["complete"] is False}
        reasons = {
            "request_failed": "incomplete_pdf_failed_transfer",
            "size_limit": "incomplete_pdf_capped_transfer",
        }
        require(
            prefix.lstrip().startswith(b"%PDF-") and len(outcomes) == 1 and outcomes <= reasons.keys(),
            f"{sha} needs individual structural review",
        )
        return dict(row, bucket=reasons[outcomes.pop()])

    with ThreadPoolExecutor(max_workers=5) as pool:
        rows = list(pool.map(inspect, sorted(keys)))
    write(root / OUT / "zero-page-structure.json", rows)
    print(Counter(r["bucket"] for r in rows))


if __name__ == "__main__":
    collect_structure(archive_arg())
