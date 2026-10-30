# /// script
# requires-python = ">=3.14"
# dependencies = ["boto3==1.42.67"]
# ///
"""Read only the known missing archive keys, without listing the bucket."""

import argparse
import configparser
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
from botocore.config import Config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rclone-config", required=True)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    config = configparser.ConfigParser()
    config.read(args.rclone_config)
    connection = config["congressionalraw"]
    client = boto3.client(
        "s3",
        endpoint_url=connection["endpoint"],
        aws_access_key_id=connection["access_key_id"],
        aws_secret_access_key=connection["secret_access_key"],
        region_name="auto",
        config=Config(
            max_pool_connections=args.workers,
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=15,
            read_timeout=60,
        ),
    )
    keys = (args.output / "body-keys.txt").read_text().splitlines()

    def fetch(key):
        dest = args.output / "archive" / key
        if dest.exists():
            return {"key": key, "outcome": "cached", "bytes": dest.stat().st_size}
        try:
            response = client.get_object(Bucket="congressional-tech-raw", Key=key)
            with response["Body"] as stream:
                raw = stream.read()
            if len(raw) != response["ContentLength"]:
                raise ValueError("Incomplete object read")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".partial")
            tmp.write_bytes(raw)
            tmp.replace(dest)
            return {"key": key, "outcome": "downloaded", "bytes": len(raw)}
        except Exception as error:  # noqa: BLE001 -- retain per-object acquisition failures
            return {
                "key": key,
                "outcome": "error",
                "error": f"{type(error).__name__}: {error}",
            }

    started = last = time.monotonic()
    size = errors = 0
    with (
        ThreadPoolExecutor(max_workers=args.workers) as pool,
        (args.output / "download-results.jsonl").open("a") as stream,
    ):
        for i, result in enumerate(
            pool.map(fetch, keys, buffersize=args.workers * 2), 1
        ):
            stream.write(json.dumps(result) + "\n")
            size += result.get("bytes", 0)
            errors += result["outcome"] == "error"
            if time.monotonic() - last >= 30 or i == len(keys):
                print(
                    json.dumps(
                        {
                            "processed": i,
                            "total": len(keys),
                            "compressed_bytes": size,
                            "errors": errors,
                            "elapsed_seconds": round(time.monotonic() - started),
                        }
                    ),
                    flush=True,
                )
                last = time.monotonic()


if __name__ == "__main__":
    main()
