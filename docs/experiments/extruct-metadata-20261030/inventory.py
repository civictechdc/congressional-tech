# /// script
# requires-python = ">=3.12"
# dependencies = ["pyarrow==23.0.1", "blake3==1.0.8"]
# ///
"""Inventory HTML in a pinned retained archive; never modify the archive.

Run with uv run --script. The rclone config is passed through, never printed.
Only the selected capture Parquet files are downloaded, not the whole bucket.
"""

import argparse
import gzip
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq
from blake3 import blake3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--rclone-config", required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    remote = "congressionalraw:congressional-tech-raw"
    command = ["rclone", "--config", args.rclone_config]
    selector_path = out / "raw-selector.json"
    if not selector_path.exists():
        subprocess.run(
            command + ["copyto", remote + "/indexes/raw.json", str(selector_path)],
            check=True,
        )
    selector = json.loads(selector_path.read_bytes())
    ref = selector["captures"]["head"]
    batches = []
    manifests = []
    while ref:
        cached = (
            args.cache
            / "docspec-catalog/r2-native-manifests"
            / ref["key"].removeprefix("indexes/native-manifests/")
        )
        dest = out / ref["key"]
        if cached.is_file():
            raw = cached.read_bytes()
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                command + ["copyto", remote + "/" + ref["key"], str(dest)], check=True
            )
            raw = dest.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == ref["sha256"], ref["key"]
        assert len(raw) == ref["bytes"], ref["key"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        manifests.append(ref)
        node = json.loads(raw)
        batches.extend(node["batches"])
        ref = node.get("previous")
    batches.sort(key=lambda b: b["first_order"])
    position = 0
    objects = []
    for batch in batches:
        assert batch["first_order"] == position
        position += batch["rows"]
        group = batch["release"]["dataset"]["groups"]["source"]
        assert group["rows"] == batch["rows"]
        objects.extend(o for o in group["objects"] if o["path"].endswith(".parquet"))
    assert position == selector["captures"]["rows"]
    for obj in objects:
        obj["key"] = obj["path"].removeprefix("s3://congressional-tech-raw/")
    (out / "capture-objects.json").write_text(json.dumps(objects, indent=2))
    files = out / "capture-keys.txt"
    files.write_text("".join(o["key"] + "\n" for o in objects))
    print(
        json.dumps(
            {
                "capture_rows": position,
                "parts": len(objects),
                "download_bytes": sum(o["bytes"] for o in objects),
            }
        ),
        flush=True,
    )
    subprocess.run(
        command
        + [
            "copy",
            remote,
            str(out / "archive"),
            "--files-from",
            str(files),
            "--no-traverse",
            "--transfers",
            "8",
            "--checkers",
            "8",
            "--size-only",
            "--stats",
            "30s",
            "--stats-one-line",
        ],
        check=True,
    )
    counts = Counter()
    media_counts = Counter()
    family_counts = Counter()
    bodies = {}
    occurrence_path = out / "html-occurrences.jsonl.gz"
    with gzip.open(occurrence_path, "wt") as occurrences:
        for obj in objects:
            path = out / "archive" / obj["key"]
            # Verify the exact selected Parquet in the same read used for parsing.
            raw = path.read_bytes()
            assert len(raw) == obj["bytes"], obj["key"]
            # These remote pins may identify path+size, not content. Match the
            # producer's explicit convention and record a fresh content hash.
            # See docspec-rs storage/remote/objects.rs stat_identity_admitted.
            if blake3(raw).hexdigest() == obj["digest"]:
                obj["pin_kind"] = "blake3-content"
            else:
                assert (
                    blake3(f"{obj['path']}:{obj['bytes']}".encode()).hexdigest()
                    == obj["digest"]
                ), obj["key"]
                obj["pin_kind"] = "blake3-path-and-size"
            obj["downloaded_sha256"] = hashlib.sha256(raw).hexdigest()
            import pyarrow as pa

            file = pq.ParquetFile(pa.BufferReader(raw))
            for batch in file.iter_batches(batch_size=16384):
                for row in batch.to_pylist():
                    counts["capture_rows"] += 1
                    media = row.get("media_type") or ""
                    media_counts[media] += 1
                    family = row.get("family") or ""
                    # Include unknown media in page families; inspect bytes later.
                    explicit = "html" in media.lower() or any(
                        s in (row.get("pointer_json") or "")
                        for s in ("raw_html", "browserHtml")
                    )
                    candidate = explicit or family in {
                        "house/pages",
                        "senate/pages",
                        "senate/players",
                        "house/repository",
                        "youtube/watch-pages",
                        "govinfo/transcript-html",
                    }
                    if not candidate:
                        continue
                    counts["candidate_references"] += 1
                    family_counts[family] += 1
                    key = row.get("body_key")
                    if not key:
                        counts["references_without_body"] += 1
                        continue
                    occurrences.write(json.dumps(row, default=str) + "\n")
                    body = bodies.setdefault(
                        key,
                        {
                            "body_key": key,
                            "sha256": row["sha256"],
                            "bytes": row["bytes"],
                            "urls": set(),
                            "families": set(),
                            "statuses": set(),
                            "fidelities": set(),
                            "references": 0,
                            "explicit_html": False,
                        },
                    )
                    body["references"] += 1
                    body["explicit_html"] |= explicit
                    body["families"].add(family)
                    body["statuses"].add(row.get("http_status"))
                    body["fidelities"].add(row.get("fidelity"))
                    if row.get("context_url"):
                        body["urls"].add(row["context_url"])
    assert counts["capture_rows"] == position
    (out / "capture-objects.json").write_text(json.dumps(objects, indent=2))
    missing = []
    for body in bodies.values():
        for root in (
            args.cache / "docspec-catalog/r2-immutable",
            args.cache / "raw-bundles-20260930",
            args.cache / "congressional-tech-raw",
        ):
            p = root / body["body_key"]
            if p.is_file():
                body["local_path"] = str(p)
                counts["locally_available_bodies"] += 1
                break
        if "local_path" not in body:
            body["local_path"] = str(out / "archive" / body["body_key"])
            missing.append(body["body_key"])
        for key in ("urls", "families", "statuses", "fidelities"):
            body[key] = sorted(body[key], key=str)
    (out / "body-keys.txt").write_text("".join(k + "\n" for k in missing))
    with (out / "bodies.jsonl").open("w") as stream:
        for body in sorted(bodies.values(), key=lambda b: b["body_key"]):
            stream.write(json.dumps(body) + "\n")
    summary = {
        "counts": counts,
        "media_types": media_counts,
        "candidate_families": family_counts,
        "unique_candidate_bodies": len(bodies),
        "decoded_candidate_bytes": sum(b["bytes"] or 0 for b in bodies.values()),
        "missing_local_bodies": len(missing),
        "selector_sha256": hashlib.sha256(selector_path.read_bytes()).hexdigest(),
        "capture_head": selector["captures"]["head"],
        "manifests": manifests,
    }
    (out / "inventory.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
