"""Read the pinned November 20 release. All remote operations are reads.

Run this file first under archive_watchdog.py, passing the archive-release directory.
The two reconciliation commands consume its compact local evidence.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import file_digest, sha256
import gzip
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.fs as fs
import pyarrow.parquet as pq
from congress_shared.storage import connect_r2

RELEASE = "0e7084cde775d0064646c56b2200a14e1f13d8b512f1a61a6fe815d597faf4d3"
EXPORT = "7aea7925da324273d16c04e7dd7d53b2a7d3a0ade895f9343063015458d88688"
SELECTION = "bbeb4e1c94e195ac8ec5085578331543b2b2f709e77d2c83e523474e07bbe10b"
BUCKET = "congressional-tech-raw"
OUT = Path("long-tail-20261120/pdf-source")
OCR = Path("ocr-recovery-20261113")
SSOT = OCR / "repairs/body-text-ssot-20261116"
CLEANUP = Path("ticket-fixes-20261117/text-handoff/cleanup-readback")
TRIAGE = OCR / "coordination/greybeard-root-cause-20261113/inventory/body-triage.jsonl"
INVENTORY = Path("ct-z4w5-acceptance-20261120/inventory/invalid-sources.jsonl")
SELECTION_FILE = (
    Path(__file__).resolve().parents[2] / "model/jobs/inputs/body-text-selection-v13/selection.json.gz"
)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load(path):
    return json.loads(path.read_bytes())


def lines(path):
    with path.open() as stream:
        yield from map(json.loads, stream)


def write(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def selection():
    raw = gzip.decompress(SELECTION_FILE.read_bytes())
    require(sha256(raw).hexdigest() == SELECTION, "selection digest")
    return json.loads(raw)


def remote(root):
    config = load(root / "remote-runtime/remote.json")
    creds = load(root / "remote-runtime/credentials.json")
    endpoint = config["properties"]["s3.endpoint"]
    access = creds[config["secret_env"]["s3.access-key-id"]]
    secret = creds[config["secret_env"]["s3.secret-access-key"]]
    client = connect_r2(
        endpoint_url=endpoint,
        access_key_id=access,
        secret_access_key=secret,
        retries={"total_max_attempts": 4, "mode": "standard"},
    )
    filesystem = fs.S3FileSystem(
        endpoint_override=endpoint, access_key=access, secret_key=secret, region="auto"
    )
    return client, filesystem


def fingerprint(path):
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def release_files(root, names, client=None):
    directory = root / "published-releases" / RELEASE
    manifest = load(directory / "manifest.json")
    require(manifest["release_id"] == RELEASE, "release manifest")
    files = {r["name"]: r for r in manifest["files"]}
    paths = {}
    for name in names:
        filename = name + ".parquet"
        path = directory / filename
        if not path.exists():
            path = root / OUT / filename
        if not path.exists() and client is not None:
            data = client.get_object(Bucket=BUCKET, Key=f"viewer-publications/releases/{RELEASE}/{filename}")[
                "Body"
            ].read()
            require(sha256(data).hexdigest() == files[filename]["sha256"], filename)
            path.write_bytes(data)
        with path.open("rb") as source:
            require(file_digest(source, "sha256").hexdigest() == files[filename]["sha256"], filename)
        paths[name] = path
    return paths


def collect(root):
    out = root / OUT
    out.mkdir(exist_ok=True, parents=True)
    client, filesystem = remote(root)
    pointer = json.load(client.get_object(Bucket=BUCKET, Key="derived/body_text/current.json")["Body"])
    require(
        (pointer["release_id"], pointer["sha256"], pointer["selection"]["sha256"])
        == (RELEASE, EXPORT, SELECTION),
        "current pointer differs from pinned generation",
    )
    require(pointer["key"] == f"derived/body_text/{EXPORT}.parquet", "object key")
    release_files(root, ["detail", "list", "recoveries", "sources", "urls", "url_state"], client)
    cases = load(root / CLEANUP / "result.json")["cases"]
    review = load(root / SSOT / "review_packets/warc_review_packet.json")["cases"]
    full = sorted(
        {bytes.fromhex(r["body_sha256"]) for r in cases}
        | {bytes.fromhex(r["saved_body_hex"]) for r in review}
    )
    with filesystem.open_input_file(f"{BUCKET}/{pointer['key']}") as source:
        size = source.size()
        tail = source.read_at(8, size - 8)
        length = int.from_bytes(tail[:4], "little") + 8
        require(tail[4:] == b"PAR1" and size == pointer["bytes"] and 8 < length < 32 << 20, "footer")
        require(
            sha256(source.read_at(length, size - length)).hexdigest() == pointer["footer_sha256"],
            "footer digest",
        )
        parquet = pq.ParquetFile(source, pre_buffer=False)
        require(parquet.metadata.num_rows == pointer["rows"] == 326929, "export row count")

        def read(group):
            stats = parquet.metadata.row_group(group).column(0).statistics
            subset = [s for s in full if stats.min <= s <= stats.max]
            cols = ["saved_body", "page_offsets", "text_sha256"]
            metadata = parquet.read_row_group(group, columns=cols, use_threads=False)
            wanted = pc.is_in(metadata["saved_body"], value_set=pa.array(subset, pa.binary(32)))
            matched = None
            if pc.any(wanted).as_py():
                texts = parquet.read_row_group(group, columns=["text"], use_threads=False)
                matched = metadata.filter(wanted).append_column("text", texts.filter(wanted)["text"])
            return metadata, matched

        samples = []
        tmp = out / "v13-metadata.partial"
        with ThreadPoolExecutor(max_workers=12) as pool, pq.ParquetWriter(
            tmp,
            pa.schema([parquet.schema_arrow.field(n) for n in ["saved_body", "page_offsets", "text_sha256"]]),
        ) as writer:
            for metadata, matched in pool.map(read, range(parquet.num_row_groups)):
                writer.write_table(metadata)
                if matched is not None:
                    samples.append(matched)
    sample = pa.concat_tables(samples)
    require(sorted(sample["saved_body"].to_pylist()) == full, "missing or repeated reviewed text")
    pq.write_table(sample, out / "v13-reviewed-text.parquet")
    tmp.replace(out / "v13-metadata.parquet")
    write(out / "v13-pointer.json", pointer)
    write(
        out / "v13-readback.json",
        dict(
            export=EXPORT,
            footer_sha256=pointer["footer_sha256"],
            metadata_rows=pointer["rows"],
            row_groups=parquet.num_row_groups,
            targeted_texts=len(full),
            text_row_groups=len(samples),
            files={
                name: fingerprint(out / name)
                for name in ["v13-pointer.json", "v13-metadata.parquet", "v13-reviewed-text.parquet"]
            },
        ),
    )
    print(f"Read {pointer['rows']} metadata rows and {len(full)} targeted texts in {len(samples)} groups")


def archive_arg():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("archive_root", type=Path)
    return args.parse_args().archive_root.resolve()


if __name__ == "__main__":
    collect(archive_arg())
