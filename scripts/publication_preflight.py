#!/usr/bin/env python3
"""Bounded read-only publication preflight using only the Python standard library.

The result can skip expensive setup for a verified no-op. It never authorizes a
later write; preparation and the original fresh conditional gate remain required.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

_PKG = Path(__file__).resolve().parents[1] / "packages/viewer_publication/src"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from viewer_publication.constants import (
    BUCKET,
    PREFIX,
    PUBLIC_URL,
    PUBLISHER_VERSION,
    USER_AGENT,
    ACCEPTED_KEY as ACCEPTED,
    LIMITS,
)
from viewer_release_identity import encoded, source_files, locked_runtime


def object_kind(key):
    """The complete signed read surface; no tables, bodies, queries or arbitrary keys."""
    if key in ("indexes/catalog.json", PREFIX + "manifest.json"):
        return "manifest"
    if key == ACCEPTED:
        return "accepted"
    if re.fullmatch(PREFIX + r"releases/[a-f0-9]{32}/manifest.json", key):
        return "manifest"
    if re.fullmatch(
        PREFIX + r"releases/[a-f0-9]{32}/[a-f0-9]{32}/viewer-v2/recovery-status.json",
        key,
    ):
        return "recovery"
    raise ValueError("Object is outside the preflight read allowlist")


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        # Refuse before urllib can forward signed Authorization to another URL.
        return None


def constants(root=None):
    return {
        "PUBLISHER_VERSION": PUBLISHER_VERSION,
        "PUBLIC_URL": PUBLIC_URL,
        "PREFIX": PREFIX,
        "BUCKET": BUCKET,
        "ACCEPTED_KEY": ACCEPTED,
    }


def bounded(response, limit):
    with response:
        declared = response.headers.get("Content-Length")
        if declared is not None and (not declared.isdecimal() or int(declared) > limit):
            raise ValueError("Preflight response exceeds declared control limit")
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Preflight response exceeds streamed control limit")
    if declared is not None and len(raw) != int(declared):
        raise ValueError("Incomplete preflight control response")
    return raw


def sigv4_request(account, key, access_key, secret_key, now=None):
    if not re.fullmatch("[a-f0-9]{32}", account):
        raise ValueError("Invalid R2 account identity")
    object_kind(key)
    if not re.fullmatch("[A-Za-z0-9]+", access_key) or not secret_key:
        raise ValueError("Invalid signing credentials")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Signing time requires a timezone")
    now = now.astimezone(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    day = stamp[:8]
    host = account + ".r2.cloudflarestorage.com"
    uri = urllib.parse.quote("/" + BUCKET + "/" + key, safe="/")
    payload = hashlib.sha256(b"").hexdigest()
    headers = f"host:{host}\nx-amz-content-sha256:{payload}\nx-amz-date:{stamp}\n"
    names = "host;x-amz-content-sha256;x-amz-date"
    scope = day + "/auto/s3/aws4_request"
    canonical = "GET\n" + uri + "\n\n" + headers + "\n" + names + "\n" + payload
    sign = lambda key, value: hmac.new(key, value.encode(), hashlib.sha256).digest()
    key_date = sign(("AWS4" + secret_key).encode(), day)
    key_region = sign(key_date, "auto")
    key_service = sign(key_region, "s3")
    signing = sign(key_service, "aws4_request")
    message = (
        "AWS4-HMAC-SHA256\n"
        + stamp
        + "\n"
        + scope
        + "\n"
        + hashlib.sha256(canonical.encode()).hexdigest()
    )
    signature = hmac.new(signing, message.encode(), hashlib.sha256).hexdigest()
    return urllib.request.Request(
        "https://" + host + uri,
        method="GET",
        headers={
            "x-amz-date": stamp,
            "x-amz-content-sha256": payload,
            "Authorization": "AWS4-HMAC-SHA256 Credential="
            + access_key
            + "/"
            + scope
            + ", SignedHeaders="
            + names
            + ", Signature="
            + signature,
        },
    )


ALLOWED_PUBLIC_URLS = frozenset(
    {
        "https://congressional-data.spicygov.ai/viewer-publications/",
        "https://congressional-data.spicygov.ai/",
    }
)


class ReadOnlyR2:
    def __init__(self, account, access_key, secret_key, *, public_url):
        self.account, self.access_key, self.secret_key = account, access_key, secret_key
        if public_url not in ALLOWED_PUBLIC_URLS:
            raise ValueError("Public read endpoint is outside the preflight allowlist")
        self.public_url = public_url
        self.requests = 0
        self.response_bytes = 0
        self.opener = urllib.request.build_opener(NoRedirects())

    def read(self, key, *, kind="manifest", optional=False):
        if object_kind(key) != kind:
            raise ValueError("Preflight control kind differs from allowed object")
        if optional and key not in (ACCEPTED, PREFIX + "manifest.json"):
            raise ValueError("Only selected pointer and accepted mapping may be absent")
        self.requests += 1
        try:
            response = self.opener.open(
                sigv4_request(self.account, key, self.access_key, self.secret_key),
                timeout=30,
            )
        except urllib.error.HTTPError as error:
            if optional and error.code == 404:
                error.close()
                return None
            error.close()
            raise
        etag = response.headers.get("ETag")
        modified = response.headers.get("Last-Modified")
        raw = bounded(response, LIMITS[kind])
        self.response_bytes += len(raw)
        return {
            "value": json.loads(raw),
            "etag": etag,
            "modified": modified,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "raw": raw,
        }

    def public(self, path, *, kind="manifest"):
        if path != "manifest.json" and not re.fullmatch(
            r"releases/[a-f0-9]{32}/[a-f0-9]{32}/viewer-v2/recovery-status.json", path
        ):
            raise ValueError("Public object is outside the preflight read allowlist")
        if object_kind(PREFIX + path) != kind:
            raise ValueError("Public control kind differs from allowed object")
        self.requests += 1
        request = urllib.request.Request(
            self.public_url + path,
            headers={
                "User-Agent": "congressional-tech-publication-preflight/1.0",
                "Origin": "https://civictechdc.github.io",
            },
        )
        try:
            response = self.opener.open(request, timeout=30)
        except urllib.error.HTTPError as error:
            error.close()
            raise
        cors = response.headers.get("Access-Control-Allow-Origin")
        raw = bounded(response, LIMITS[kind])
        self.response_bytes += len(raw)
        return raw, cors


def preflight(reader, identity, *, publisher_version):
    source = reader.read("indexes/catalog.json")
    pointer_record = reader.read(PREFIX + "manifest.json", optional=True)
    accepted = reader.read(ACCEPTED, kind="accepted", optional=True)
    required = {
        "status": "preparation_required",
        "write_authority": False,
        "table_reads": 0,
        "publication_writes": 0,
    }
    if pointer_record is None:
        return dict(required, reason="viewer_not_selected")
    pointer = pointer_record["value"]
    if (
        pointer.get("source_manifest") != source["value"]
        or pointer.get("publisher_version") != publisher_version
        or pointer.get("full_release_inputs") != identity
    ):
        return dict(required, reason="full_release_inputs_changed")
    mapping = accepted["value"] if accepted is not None else None
    if mapping is not None and (
        not isinstance(mapping, dict)
        or mapping.get("version") != 1
        or not isinstance(mapping.get("recoveries"), list)
    ):
        return dict(required, reason="accepted_mapping_requires_validation")
    rows = mapping["recoveries"] if mapping is not None else []
    inputs = pointer.get("recovery_inputs", {})
    if (
        inputs.get("raw_manifest_sha256") != source["sha256"]
        or inputs.get("full_release_inputs") != identity
        or inputs.get("accepted")
        != {
            "present": mapping is not None,
            "sha256": hashlib.sha256(encoded(rows)).hexdigest(),
        }
    ):
        return dict(required, reason="recovery_inputs_changed")
    location = pointer.get("manifest", "")
    if not re.fullmatch(r"releases/[a-f0-9]{32}/manifest.json", location):
        raise ValueError("Invalid selected immutable manifest")
    manifest_record = reader.read(PREFIX + location)
    manifest = manifest_record["value"]
    native = manifest.get("version") == 6
    basis_matches = (
        (
            inputs.get("version") == 2
            and inputs.get("source_identity") == manifest.get("source_identity")
            and pointer.get("source_identity") == manifest.get("source_identity")
            and inputs.get("roots") == manifest.get("roots")
            and manifest["source_identity"]["selector_sha256"] == source["sha256"]
            and manifest["source_identity"]["selected_ref"]
            == source["value"].get("selection")
        )
        if native
        else (
            inputs.get("files")
            == {
                name: manifest["files"][name]["sha256"]
                for name in ("filenames", "groups")
            }
        )
    )
    if (
        manifest_record["sha256"] != inputs.get("viewer_manifest_sha256")
        or manifest.get("source_manifest") != source["value"]
        or manifest.get("info", {}).get("catalog_id") != pointer.get("catalog_id")
        or not basis_matches
    ):
        raise ValueError("Selected immutable manifest input identity differs")
    descriptor = pointer.get("recovery", {})
    if (
        not isinstance(descriptor, dict)
        or not re.fullmatch(
            r"releases/[a-f0-9]{32}/[a-f0-9]{32}/viewer-v2/recovery-status.json",
            descriptor.get("path", ""),
        )
        or type(descriptor.get("bytes")) is not int
        or not 0 < descriptor["bytes"] <= LIMITS["recovery"]
    ):
        raise ValueError("Invalid selected recovery descriptor")
    recovery = reader.read(PREFIX + descriptor["path"], kind="recovery")
    if len(recovery["raw"]) != descriptor["bytes"] or recovery[
        "sha256"
    ] != descriptor.get("sha256"):
        raise ValueError("Selected recovery status length/hash differs")
    index = recovery["value"]
    if (
        index.get("version") != (2 if native else 1)
        or index.get("catalog_id") != pointer.get("catalog_id")
        or native
        and (
            index.get("source_identity") != manifest["source_identity"]
            or any(
                index.get(key) != manifest["info"][key] for key in ("rows", "entries")
            )
        )
    ):
        raise ValueError("Selected recovery status catalog differs")
    public, cors = reader.public(descriptor["path"], kind="recovery")
    if public != recovery["raw"] or cors != "*":
        raise ValueError("Public recovery bytes or CORS differs")
    public, _ = reader.public("manifest.json")
    if json.loads(public) != pointer:
        raise ValueError("Public viewer pointer differs")
    # These are separate freshness reads. They are never an authority for a write.
    for key, saved, kind in (
        ("indexes/catalog.json", source, "manifest"),
        (ACCEPTED, accepted, "accepted"),
        (PREFIX + "manifest.json", pointer_record, "manifest"),
    ):
        if reader.read(key, kind=kind, optional=key != "indexes/catalog.json") != saved:
            raise ValueError(
                "Preflight protected input advanced during observation: " + key
            )
    return dict(
        required,
        status="unchanged",
        reason="exact_control_and_public_readback",
        catalog_id=pointer["catalog_id"],
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    reader = None
    try:
        values = constants(args.root)
        identity = {
            "version": 1,
            "implementation": hashlib.sha256(
                encoded(source_files(args.root))
            ).hexdigest(),
            "dependencies": locked_runtime(args.root),
            "publisher_version": values["PUBLISHER_VERSION"],
        }
        reader = ReadOnlyR2(
            os.environ["CLOUDFLARE_ACCOUNT_ID"],
            os.environ["R2_ACCESS_KEY_ID"],
            os.environ["R2_SECRET_ACCESS_KEY"],
            public_url=values["PUBLIC_URL"],
        )
        result = preflight(
            reader, identity, publisher_version=values["PUBLISHER_VERSION"]
        )
    except (ValueError, SyntaxError, KeyError, TypeError) as error:
        if reader is not None:
            result = {
                "status": "failed",
                "reason": "protected_control_check_failed",
                "error_type": type(error).__name__,
                "write_authority": False,
            }
            raise
        result = {
            "status": "preparation_required",
            "reason": "locked_runtime_or_source_requires_validation",
            "error_type": type(error).__name__,
            "write_authority": False,
            "table_reads": 0,
            "publication_writes": 0,
        }
    except BaseException as error:
        result = {
            "status": "failed",
            "reason": "read_only_preflight_failed",
            "error_type": type(error).__name__,
            "write_authority": False,
        }
        raise
    finally:
        if "result" in locals():
            result.update(
                elapsed_seconds=time.perf_counter() - started,
                requests=reader.requests if reader else 0,
                response_bytes=reader.response_bytes if reader else 0,
                workspace_sync=False,
                native_tools_install=False,
            )
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, indent=2) + "\n")
            if os.environ.get("GITHUB_OUTPUT"):
                with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
                    stream.write("status=" + result["status"] + "\n")
            print(json.dumps(result))


if __name__ == "__main__":
    main()
