"""Build, verify, and optionally upload a byte-pinned DocSpec runtime artifact to R2.

Outputs the exact ``DOCSPEC_RUNTIME_ARTIFACT`` JSON descriptor consumed by
``.github/scripts/setup-native-runtime.py:artifact_descriptor()``.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import closing
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from congress_shared.custody import canonical_json_bytes, write_atomic_bytes
from congress_shared.storage import connect_r2
from docspec_client import QUALIFIED_DOCSPEC_RUNTIME, REQUIRED_LOOPBACK_CAPABILITIES

MAX_BINARY_BYTES = 1024**3
MAX_DESCRIPTOR_BYTES = 1024**2
SUPPORTED_ARTIFACT_PLATFORMS = ("linux-amd64", "darwin-arm64")


def compute_binary_identity(binary_path: Path | str) -> dict[str, Any]:
    """Compute streamed byte size, SHA-256 hex digest, and base64 Content-MD5 for a binary."""
    path = Path(binary_path)
    if not path.is_file():
        raise FileNotFoundError(f"DocSpec runtime binary not found: {path}")
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        if not 0 < size <= MAX_BINARY_BYTES:
            raise ValueError(f"DocSpec runtime binary size out of bounds: {size}")
        sha_digest = file_digest(stream, "sha256").hexdigest()
        stream.seek(0)
        md5_digest = file_digest(stream, "md5")
        after = os.fstat(stream.fileno()).st_size
    if after != size:
        raise ValueError(f"DocSpec runtime binary changed during hashing: {path}")
    return {
        "bytes": size,
        "sha256": sha_digest,
        "md5_hex": md5_digest.hexdigest(),
        "md5_b64": base64.b64encode(md5_digest.digest()).decode("ascii"),
    }


def build_runtime_descriptor(
    binary_path: Path | str,
    *,
    source_revision: str = QUALIFIED_DOCSPEC_RUNTIME["source_revision"],
    platform: str = "linux-amd64",
    bucket: str,
    build_features: list[str] | tuple[str, ...] = ("remote",),
    required_capabilities: list[str] | tuple[str, ...] = REQUIRED_LOOPBACK_CAPABILITIES,
) -> dict[str, Any]:
    """Build a ``DOCSPEC_RUNTIME_ARTIFACT`` descriptor matching ``setup-native-runtime.py``."""
    if platform not in SUPPORTED_ARTIFACT_PLATFORMS:
        raise ValueError(f"Unsupported runtime platform: {platform!r}")
    if not isinstance(source_revision, str) or not re.fullmatch(r"[0-9a-f]{40}", source_revision):
        raise ValueError(f"source_revision must be a 40-char lowercase hex SHA-1: {source_revision!r}")
    if not isinstance(bucket, str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
        raise ValueError(f"Invalid R2 bucket name: {bucket!r}")
    features = list(dict.fromkeys(build_features))
    if not features or "remote" not in features:
        raise ValueError("build_features must include 'remote'")
    capabilities = list(dict.fromkeys(required_capabilities))
    if not set(REQUIRED_LOOPBACK_CAPABILITIES).issubset(capabilities):
        raise ValueError("required_capabilities must include all protocol-1 loopback capabilities")

    identity = compute_binary_identity(binary_path)
    key = f"runtime/docspec/{source_revision}/{platform}/{identity['sha256']}/docspec"
    return {
        "version": 1,
        "platform": platform,
        "source_revision": source_revision,
        "bucket": bucket,
        "key": key,
        "bytes": identity["bytes"],
        "sha256": identity["sha256"],
        "build_features": features,
        "required_capabilities": capabilities,
    }


def verify_uploaded_runtime(client: Any, descriptor: dict[str, Any]) -> None:
    """Read back the uploaded R2 runtime object and verify exact byte length and SHA-256."""
    response = client.get_object(Bucket=descriptor["bucket"], Key=descriptor["key"])
    with closing(response["Body"]) as stream:
        content_length = response.get("ContentLength")
        if type(content_length) is not int or content_length != descriptor["bytes"]:
            raise ValueError(
                f"Uploaded runtime ContentLength {content_length!r} != {descriptor['bytes']}"
            )
        digest = sha256()
        total = 0
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > descriptor["bytes"]:
                raise ValueError("Uploaded runtime object exceeds expected byte size")
            digest.update(chunk)
    if total != descriptor["bytes"] or digest.hexdigest() != descriptor["sha256"]:
        raise ValueError("Uploaded runtime SHA-256 or byte length mismatch")


def upload_runtime_binary(
    binary_path: Path | str,
    descriptor: dict[str, Any],
    *,
    client: Any | None = None,
) -> dict[str, Any]:
    """Upload the runtime binary to R2 and verify exact byte length and SHA-256."""
    path = Path(binary_path)
    identity = compute_binary_identity(path)
    if identity["bytes"] != descriptor["bytes"] or identity["sha256"] != descriptor["sha256"]:
        raise ValueError("Binary changed after descriptor construction")
    s3 = client if client is not None else make_client(bucket=descriptor["bucket"])
    with path.open("rb") as stream:
        try:
            s3.put_object(
                Bucket=descriptor["bucket"],
                Key=descriptor["key"],
                Body=stream,
                ContentLength=descriptor["bytes"],
                ContentMD5=identity["md5_b64"],
                ContentType="application/octet-stream",
                IfNoneMatch="*",
            )
        except Exception as exc:
            response = getattr(exc, "response", None) or {}
            code = (response.get("Error") or {}).get("Code")
            if code not in {"PreconditionFailed", "412"}:
                raise
    verify_uploaded_runtime(s3, descriptor)
    return descriptor


def make_client(*, bucket: str) -> Any:
    return connect_r2(
        bucket=bucket,
        connect_timeout=15,
        read_timeout=180,
        retries={"total_max_attempts": 1},
    )


def main(argv: list[str] | None = None, *, client: Any | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True, help="Path to compiled docspec binary")
    parser.add_argument(
        "--source-revision",
        default=QUALIFIED_DOCSPEC_RUNTIME["source_revision"],
        help="40-character git commit SHA of docspec-rs",
    )
    parser.add_argument(
        "--platform",
        choices=SUPPORTED_ARTIFACT_PLATFORMS,
        default="linux-amd64",
        help="Target platform identifier (default: linux-amd64)",
    )
    parser.add_argument(
        "--bucket",
        required=True,
        help="Explicit private R2 bucket for runtime artifacts (congressional-tech-runtime in production)",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload the binary to R2 at runtime/docspec/<source_revision>/<platform>/<sha256>/docspec and verify readback",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the DOCSPEC_RUNTIME_ARTIFACT JSON descriptor",
    )
    parser.add_argument(
        "--expected-descriptor", type=Path,
        help="Require this approved descriptor to match the local binary before upload",
    )
    args = parser.parse_args(argv)

    expected = None
    if args.expected_descriptor is not None:
        with args.expected_descriptor.open("rb") as stream:
            data = stream.read(MAX_DESCRIPTOR_BYTES + 1)
        if len(data) > MAX_DESCRIPTOR_BYTES:
            raise ValueError("Expected runtime descriptor exceeds the metadata size limit")
        expected = json.loads(data)
    descriptor = build_runtime_descriptor(
        args.binary,
        source_revision=args.source_revision,
        platform=args.platform,
        bucket=args.bucket,
    )
    if args.expected_descriptor is not None and (
        canonical_json_bytes(expected, allow_nan=False)
        != canonical_json_bytes(descriptor, allow_nan=False)
    ):
        raise ValueError("Expected runtime descriptor differs from the local binary identity")
    if args.upload:
        upload_runtime_binary(args.binary, descriptor, client=client)
    rendered = json.dumps(descriptor, indent=2) + "\n"
    if args.output:
        write_atomic_bytes(
            args.output,
            rendered.encode("utf-8"),
            temp_mode="unique",
            fsync=False,
        )
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
