"""Prepare one published congressional archive for SpicyEngine and install it on the local runtime."""

import argparse
import fcntl
import json
import os
import re
import subprocess
from contextlib import closing
from hashlib import file_digest, sha256
from pathlib import Path
from urllib.request import Request, urlopen

import duckdb
import pyarrow.parquet as pq

from congress_shared.custody import write_atomic_bytes
from viewer_publication.archive_format import release_identity

ORIGIN = "https://congressional-data.spicygov.ai"
RECIPE = "search-v1"
FIELDS = {
    "title": "title", "text": ["body"], "url": "source_url", "identifiers": "identifiers",
    "page_offsets": {"body": "page_offsets"},
    "date_default": "document_date",
    "labels": {"committee_keys": "Committees", "document_kind": "Document kind",
               "document_family": "Document family", "document_date": "Document date",
               "chambers": "Chambers", "text_status": "Text coverage", "archive_title": "Archive title",
               "page_offsets": "Page offsets (UTF-8 bytes)", "saved_body_sha256": "Archived file SHA-256",
               "text_sha256": "Selected text SHA-256", "member_path": "File inside source archive"},
}
DOCUMENTS = """CREATE TEMPORARY TABLE documents AS
SELECT d.link_key, d.saved_body, d.saved_suffix, d.title AS archive_title, d.filename, d.package_id,
           substr(coalesce(lower(hex(d.saved_body)), lower(hex(d.link_key))), 1, 2) AS shard,
           d.format, d.document_date, d.document_date_status, d.congress, d.chambers, d.committee_keys,
           d.document_kind, d.document_family, s.url AS publisher_url, s.link_text, s.member_path
    FROM read_parquet(?) AS d
    LEFT JOIN read_parquet(?, file_row_number=true) AS s
      ON s.file_row_number = CASE WHEN d.src_len > 0 THEN d.src_start END AND s.ordinal = 0
    WHERE d.hidden IS NOT TRUE
"""
PARTITION = """SELECT 'archive-documents'::VARCHAR AS source_id, lower(hex(d.link_key)) AS member_key,
       coalesce(nullif(d.archive_title, ''), nullif(d.filename, ''), nullif(d.link_text, ''),
                nullif(d.package_id, ''), lower(hex(d.link_key))) AS title,
       b.text AS body,
       coalesce(d.publisher_url, 'https://congressional-data.spicygov.ai/bodies/sha256/' ||
                left(lower(hex(d.saved_body)), 2) || '/' || lower(hex(d.saved_body)) || d.saved_suffix) AS source_url,
       CASE WHEN nullif(d.package_id,'') IS NULL THEN []::VARCHAR[] ELSE [d.package_id] END AS identifiers,
       d.document_date, d.document_date_status, d.congress, d.chambers, d.committee_keys,
       d.document_kind, d.document_family, d.format, d.filename, d.archive_title, d.member_path,
       lower(hex(d.saved_body)) AS saved_body_sha256, lower(hex(b.text_sha256)) AS text_sha256, b.page_offsets,
       CASE WHEN b.saved_body IS NULL THEN 'No text in this export'
            WHEN b.text IS NULL THEN 'Null exported text'
            WHEN b.text = '' THEN 'Empty exported text' ELSE 'Selected text' END AS text_status
      FROM (SELECT * FROM read_parquet(?)
            WHERE saved_body BETWEEN from_hex(?) AND from_hex(?)) AS b
      RIGHT JOIN (SELECT * FROM documents WHERE shard=?) AS d ON b.saved_body=d.saved_body"""


def open_object(origin, key, offset=0):
    headers = {"User-Agent": "congressional-tech-release-gate/1", "Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    return urlopen(Request(f"{origin.rstrip('/')}/{key}", headers=headers), timeout=120)


def fetch_json(origin, key):
    with open_object(origin, key) as response:
        return json.load(response)


def save(path, value):
    write_atomic_bytes(path, (json.dumps(value, sort_keys=True) + "\n").encode(), fsync_dir=True)


def resolve(origin, saved=None):
    if saved:
        pin = json.loads(saved.read_text())
    else:
        archive = fetch_json(origin, "viewer-publications/manifest.json")
        text = fetch_json(origin, "derived/body_text/current.json")
        pin = {"release_id": archive["release_id"], "text": text}
    release, text = pin["release_id"], pin["text"]
    if (not re.fullmatch("[0-9a-f]{64}", release) or text["release_id"] != release
            or not re.fullmatch("[0-9a-f]{64}", text["sha256"])
            or text["key"] != f"derived/body_text/{text['sha256']}.parquet"):
        raise ValueError("Archive and body-text pointers must identify the same immutable release")
    return pin


def download(origin, key, target, digest, size):
    """Resume the owned partial at its pinned URL and verify bytes before naming a completed input."""
    target.parent.mkdir(exist_ok=True)
    partial = target.with_suffix(".part")
    with partial.open("a+b") as output:
        offset = output.tell()
        if offset > size:
            raise ValueError(f"Oversized partial download: {partial}")
        output.seek(0)
        hasher = file_digest(output, "sha256") if offset else sha256()
        if offset < size:
            with open_object(origin, key, offset) as response:
                if response.status == 206:
                    if response.headers.get("Content-Range") != f"bytes {offset}-{size - 1}/{size}":
                        raise ValueError(f"Unexpected range for {key}")
                elif offset:
                    output.truncate(0)
                    hasher = sha256()
                    offset = 0
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    if offset + len(chunk) > size:
                        raise ValueError(f"Download exceeds pinned size for {key}")
                    output.write(chunk)
                    hasher.update(chunk)
                    offset += len(chunk)
        if offset != size:
            raise ValueError(f"Incomplete download of {key}; retained {offset} bytes")
        if hasher.hexdigest() != digest:
            partial.replace(partial.with_suffix(".invalid"))
            raise ValueError(f"Downloaded bytes differ from the pin for {key}")
        output.flush()
        os.fsync(output.fileno())
    partial.replace(target)


def source_files(origin, work, pin, local):
    release, text = pin["release_id"], pin["text"]
    prefix = f"viewer-publications/releases/{release}"
    manifest = fetch_json(origin, prefix + "/manifest.json")
    if manifest["release_id"] != release or release_identity(manifest["schema_version"], manifest["files"]) != release:
        raise ValueError("Archive manifest identity differs from the release")
    entries = {f["name"]: f for f in manifest["files"]}
    if text["detail"] != {k: entries["detail.parquet"][k] for k in ("sha256", "size")}:
        raise ValueError("Text export and archive detail pins disagree")
    inputs = {name: (f"{prefix}/{name}", entries[name]["sha256"], entries[name]["size"])
              for name in ("detail.parquet", "sources.parquet")}
    inputs["body_text.parquet"] = (text["key"], text["sha256"], text["bytes"])
    def locate(name):
        key, digest, size = inputs[name]
        target = work / "downloads" / name
        existing = local / name if local else None
        if existing and existing.is_file():
            with existing.open("rb") as stream:
                if existing.stat().st_size != size or file_digest(stream, "sha256").hexdigest() != digest:
                    raise ValueError(f"Local {name} differs from the selected release")
            target = existing
        elif target.exists():
            if target.stat().st_size != size:
                raise ValueError(f"Incomplete retained download: {name}")
        else:
            download(origin, key, target, digest, size)
        return str(target)
    return locate


def prepare(origin, work, pin, local):
    ready = work / "prepared.json"
    if ready.is_file():
        return json.loads(ready.read_text())
    locate = source_files(origin, work, pin, local)
    body = None
    output = work / "prepared"
    output.mkdir(exist_ok=True)
    with closing(duckdb.connect(config={"threads": 1, "preserve_insertion_order": False})) as db:
        db.execute(DOCUMENTS, [locate("detail.parquet"), locate("sources.parquet")])
        counts = dict(db.execute("SELECT shard, count(*) FROM documents GROUP BY shard").fetchall())
        total = sum(counts.values())
        if total != db.execute("SELECT count(DISTINCT link_key) FROM documents").fetchone()[0]:
            raise ValueError("Visible document identities are missing or duplicated")
        for shard, expected in sorted((counts or {"00": 0}).items()):
            if not re.fullmatch("[0-9a-f]{2}", shard):
                raise ValueError("Invalid document identity")
            target = output / f"archive-{shard}.parquet"
            if target.exists():
                if pq.read_metadata(target).num_rows != expected:
                    raise ValueError(f"Incomplete retained partition {shard}")
                continue
            tmp = target.with_suffix(".partial")
            if body is None:
                body = locate("body_text.parquet")
            reader = db.execute(PARTITION, [body, shard + "00" * 31, shard + "ff" * 31, shard]).to_arrow_reader(8)
            rows = 0
            with pq.ParquetWriter(tmp, reader.schema, compression="zstd", compression_level=3) as writer:
                for batch in reader:
                    writer.write_batch(batch)
                    rows += batch.num_rows
            if rows != expected:
                raise ValueError(f"Partition {shard} produced {rows} of {expected} document identities")
            with tmp.open("rb") as completed:
                os.fsync(completed.fileno())
            os.replace(tmp, target)
    directory = os.open(output, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    result = {"records": total}
    save(ready, result)
    return result


def update(root, *, origin=ORIGIN, saved=None, local=None, engine=None, check_query=None):
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".release.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pin = resolve(origin, saved)
        release = pin["release_id"]
        work = root / RECIPE / release / pin["text"]["sha256"]
        work.mkdir(parents=True, exist_ok=True)
        if not (work / "pin.json").is_file():
            save(work / "pin.json", pin)
        ready = prepare(origin, work, pin, local)
        links = work / "source-links.parquet"
        if not links.is_file():
            # The live index already holds page starts. Only the small release metadata supplies listing URLs.
            locate = source_files(origin, work, pin, local)
            temporary = links.with_suffix(".partial")
            with closing(duckdb.connect(config={"threads": 1})) as db:
                db.sql("""WITH sources AS (
                    SELECT file_row_number - ordinal AS src_start,
                           arg_min(listed_on, ordinal) FILTER (WHERE listed_on <> url AND
                               regexp_matches(listed_on, '^https?://', 'i')) AS listed_on,
                           max(url) FILTER (WHERE ordinal=0 AND is_saved AND nullif(member_path,'') IS NULL AND
                               regexp_matches(url, '^https?://[^?#]+[.]pdf([?#].*)?$', 'i')) AS direct_pdf
                    FROM read_parquet(?, file_row_number=true) GROUP BY 1
                ) SELECT 'archive-documents:' || lower(hex(d.link_key)) AS id, s.listed_on,
                         CASE WHEN d.format='pdf' AND d.saved_suffix='.pdf' THEN coalesce(s.direct_pdf,
                             ? || '/bodies/sha256/' || left(lower(hex(d.saved_body)),2) || '/' ||
                             lower(hex(d.saved_body)) || '.pdf') END AS pdf_url
                  FROM read_parquet(?) d LEFT JOIN sources s ON d.src_len>0 AND s.src_start=d.src_start
                  WHERE d.hidden IS NOT TRUE AND (listed_on IS NOT NULL OR pdf_url IS NOT NULL)
                  ORDER BY id""", params=[locate("sources.parquet"), ORIGIN, locate("detail.parquet")]
                ).write_parquet(str(temporary), compression="zstd", row_group_size=2048)
            with temporary.open("rb") as complete:
                os.fsync(complete.fileno())
            temporary.replace(links)
        # Once preparation commits, only the search partitions are needed locally.
        for name in ("body_text.parquet", "detail.parquet", "sources.parquet"):
            (work / "downloads" / name).unlink(missing_ok=True)
        manifest = work / "dataset.json"
        definition = {"input": {"parquet": str(work / "serving" / "*.parquet")}, "text_storage": "source",
                      "label": f"Congressional archive · {release[:12]}", "fields": FIELDS, "source_links": str(links)}
        if not manifest.exists() or json.loads(manifest.read_text()) != definition:
            save(manifest, definition)
        if engine:
            args = [engine, "publish", str(manifest), "--shards-from", str(work / "prepared"),
                    "--expected-rows", str(ready["records"])]
            if check_query:
                args.extend(["--check-query", check_query])
            subprocess.run(args, check=True)
        return work


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--pin", type=Path, help="Replay a saved pin.json, including after the upstream pointer moves")
    parser.add_argument("--source-dir", type=Path, help="Reuse matching local detail, sources and body_text Parquet")
    parser.add_argument("--engine", help="Installed spicyengine executable; omit to prepare only")
    parser.add_argument("--check-query", help="Search to verify before activating a new index")
    args = parser.parse_args()
    print(update(args.root, saved=args.pin, local=args.source_dir, engine=args.engine, check_query=args.check_query))


if __name__ == "__main__":
    main()
