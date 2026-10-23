"""Read-only publication checks with explicit pending gates and bounded catalogs."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request


def control(location, *, limit=2 * 1024**2, expected=None):
    if str(location).startswith(("http://", "https://")):
        request = urllib.request.Request(
            str(location),
            headers={"User-Agent": "congressional-tech-publication-status/1.0"},
        )
        stream = urllib.request.urlopen(request, timeout=20)
    else:
        stream = Path(location).open("rb")
    with stream:
        declared = (
            stream.headers.get("Content-Length") if hasattr(stream, "headers") else None
        )
        if declared is not None and (int(declared) < 0 or int(declared) > limit):
            raise ValueError("Verification response exceeds declared byte budget")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Verification response exceeds byte budget")
    if declared is not None and len(raw) != int(declared):
        raise ValueError("Incomplete verification response")
    if expected and (
        len(raw) != expected["bytes"]
        or hashlib.sha256(raw).hexdigest() != expected["sha256"]
    ):
        raise ValueError("Verification response differs from pinned bytes/hash")
    return raw


def catalog_differences(observed, *, max_bytes=32 * 1024**2, read=control):
    """Fully hash one bounded table, then decode only IDs/category columns in batches."""
    if observed["manifest"].get("version") == 6:
        return _native_catalog_differences(observed, max_bytes=max_bytes, read=read)
    manifest = observed["manifest"]
    item = manifest["files"]["documents"]
    if item["bytes"] > max_bytes:
        return {
            "state": "pending",
            "reason": "Selected document table exceeds explicit verification byte ceiling",
            "maximum_bytes": max_bytes,
        }
    from urllib.parse import urljoin

    raw = read(
        urljoin(observed["manifest_url"], item["path"]), limit=max_bytes, expected=item
    )
    import pyarrow.parquet as pq

    rows = {
        row["document_id"]: row
        for row in observed["loader"]["rows"]
        if row.get("document_id")
    }
    fields = ["document_kind", "document_family", "document_kind_source"]
    found = {}
    with tempfile.TemporaryDirectory(prefix="publication-status-") as folder:
        path = Path(folder) / "documents.parquet"
        path.write_bytes(raw)
        with pq.ParquetFile(path) as table:
            if (table.schema_arrow.metadata or {}).get(
                b"catalog_id", b""
            ).decode() != manifest["info"][
                "catalog_id"
            ] or table.metadata.num_rows != item["rows"]:
                raise ValueError("Verified document table catalog/count differs")
            for batch in table.iter_batches(
                batch_size=256, columns=["document_id", *fields]
            ):
                for row in batch.to_pylist():
                    if row["document_id"] in rows:
                        found[row["document_id"]] = {
                            field: row[field] for field in fields
                        }
    differences = []
    for identifier, review in rows.items():
        current = found.get(identifier)
        differences.append(
            {
                "document_id": identifier,
                "status": "missing" if current is None else "found",
                "catalog": current,
                "review_baseline": review["baseline"],
                "review_selected": review["selected"],
                "different_from_review_baseline": current is not None
                and current != review["baseline"],
            }
        )
    return {
        "state": "passed",
        "table_sha256": item["sha256"],
        "table_bytes": len(raw),
        "decoded_columns": ["document_id", *fields],
        "maximum_batch_rows": 256,
        "documents": differences,
        "withdrawn": observed.get("withdrawn", []),
    }


class _VerificationBudget(ValueError):
    pass


def _native_catalog_differences(observed, *, max_bytes, read):
    """Resolve reviewed IDs with the publisher's owners; never scan the catalog."""
    from urllib.parse import urljoin
    from viewer_publication.filename_native import (
        ViewerAssets,
        validate_publication,
        public_component,
    )
    import pyarrow.parquet as pq

    manifest = observed["manifest"]
    base = urljoin(observed["manifest_url"], "../../")
    rows = {row["document_id"]: row for row in observed["loader"]["rows"]}
    fields = ["document_kind", "document_family", "document_kind_source"]
    found, partitions, locations, total = {}, {}, {}, 0
    withdrawn = {row["document_id"] for row in observed.get("withdrawn", [])}

    def metadata(path):
        nonlocal total
        # Reserve one existing metadata-page budget before issuing a read.
        # The remainder is available to exact document partitions afterwards.
        if max_bytes - total < 1024**2:
            raise _VerificationBudget
        raw = read(urljoin(base, path), limit=1024**2)
        total += len(raw)
        return raw

    try:
        with tempfile.TemporaryDirectory(prefix="native-publication-status-") as folder:
            assets = ViewerAssets(Path(folder), read_asset=metadata)
            validate_publication(assets, manifest)
            for identity in rows:
                component = public_component(
                    assets, manifest["roots"]["components"], identity
                )
                if component is None:
                    if identity not in withdrawn:
                        raise ValueError(
                            "Bound reviewed document is missing from the selected catalog"
                        )
                    continue
                item = component["document_file"]
                digest = item["sha256"]
                if (
                    item["path"]
                    != f"releases/{digest[:32]}/{digest[32:]}/viewer-v2/documents.parquet"
                ):
                    raise ValueError(
                        "Reviewed document partition path differs from its immutable identity"
                    )
                if item["path"] in partitions and partitions[item["path"]] != item:
                    raise ValueError("Reviewed document partition identities disagree")
                partitions[item["path"]] = item
                locations[identity] = item["path"]
            for name, item in partitions.items():
                if type(item["bytes"]) is not int or item["bytes"] < 1:
                    raise ValueError(
                        "Reviewed document partition has invalid byte count"
                    )
                if item["bytes"] > max_bytes - total:
                    raise _VerificationBudget
                raw = read(urljoin(base, name), limit=max_bytes - total, expected=item)
                total += len(raw)
                path = Path(folder) / "documents.parquet"
                path.write_bytes(raw)
                with pq.ParquetFile(path) as table:
                    # Reused immutable parts retain their original schema metadata.
                    # The current root/proof and exact file hash authorize reuse.
                    if table.metadata.num_rows != item["rows"]:
                        raise ValueError("Verified document partition count differs")
                    for batch in table.iter_batches(
                        batch_size=256, columns=["document_id", *fields]
                    ):
                        for row in batch.to_pylist():
                            identity = row["document_id"]
                            if locations.get(identity) != name:
                                continue
                            if identity in found:
                                raise ValueError(
                                    "Reviewed document is repeated in its selected partition"
                                )
                            found[identity] = {field: row[field] for field in fields}
    except _VerificationBudget:
        return dict(
            state="pending",
            reason="Reviewed native partitions exceed the verification byte ceiling",
            maximum_bytes=max_bytes,
            bytes_read=total,
        )
    if any(identity not in found for identity in locations):
        raise ValueError("Reviewed document is missing from its selected partition")
    differences = [
        dict(
            document_id=identity,
            status="found" if identity in found else "missing",
            catalog=found.get(identity),
            review_baseline=review["baseline"],
            review_selected=review["selected"],
            different_from_review_baseline=identity in found
            and found[identity] != review["baseline"],
        )
        for identity, review in rows.items()
    ]
    return dict(
        state="passed",
        source_identity=manifest["source_identity"],
        partition_count=len(partitions),
        bytes_read=total,
        maximum_bytes=max_bytes,
        decoded_columns=["document_id", *fields],
        maximum_batch_rows=256,
        documents=differences,
        withdrawn=observed.get("withdrawn", []),
    )


def verify(
    raw_manifest,
    observed,
    *,
    current_raw=False,
    read=control,
    raw_digest=None,
    expected_raw_digest=None,
):
    checks = []

    def check(name, state, detail):
        checks.append({"check": name, "state": state, "detail": detail})

    pointer, manifest = observed["pointer"], observed["manifest"]
    same = (
        pointer.get("source_manifest") == raw_manifest
        and manifest.get("source_manifest") == raw_manifest
        and pointer.get("catalog_id") == manifest.get("info", {}).get("catalog_id")
    )
    if manifest.get("version") == 6:
        identity = manifest.get("source_identity", {})
        selector_digest = hashlib.sha256(
            json.dumps(raw_manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        same = (
            same
            and raw_manifest.get("version") == 2
            and identity.get("selected_ref") == raw_manifest.get("selection")
            and identity.get("selector_sha256") == (raw_digest or selector_digest)
            and pointer.get("source_identity") == identity
        )
    else:
        same = same and pointer.get("catalog_id") == raw_manifest.get("catalog_id")
    check(
        "raw_viewer_identity",
        "passed" if same else "failed",
        {
            "raw_catalog_id": raw_manifest.get("catalog_id"),
            "viewer_catalog_id": pointer.get("catalog_id"),
            "immutable_manifest": observed["manifest_url"],
        },
    )
    check(
        "raw_run_output_binding",
        "pending"
        if expected_raw_digest is None
        else "passed"
        if raw_digest == expected_raw_digest
        else "failed",
        {
            "observed_sha256": raw_digest,
            "expected_run_output_sha256": expected_raw_digest,
        },
    )
    check(
        "raw_selector_freshness",
        "passed" if current_raw else "pending",
        "Current remote raw selector read"
        if current_raw
        else "Saved raw selector identity; live raw freshness has not been established",
    )
    if manifest.get("version") == 6:
        recovery = observed.get("recovery_identity", {})
        recovery_inputs = pointer.get("recovery_inputs", {})
        same_recovery = (
            recovery.get("source_identity") == identity
            and recovery.get("sha256") == pointer.get("recovery", {}).get("sha256")
            and recovery_inputs.get("version") == 2
            and recovery_inputs.get("source_identity") == identity
            and recovery_inputs.get("roots") == manifest.get("roots")
            and recovery_inputs.get("raw_manifest_sha256")
            == identity.get("selector_sha256")
            and recovery.get("accepted_sha256")
            == recovery_inputs.get("accepted", {}).get("sha256")
            and isinstance(recovery.get("accepted_sha256"), str)
            and any(
                row.get("url") == observed["manifest_url"]
                and row.get("sha256") == recovery_inputs.get("viewer_manifest_sha256")
                for row in observed.get("observations", [])
            )
        )
        check(
            "native_recovery_identity",
            "passed" if same_recovery else "failed",
            recovery,
        )
    info = observed.get("loader", {}).get("info", {})
    check(
        "maintained_live_review_loader",
        "passed" if info.get("reviewed_search") else "pending",
        info,
    )
    check(
        "pages_asset_readback",
        "passed" if observed.get("pages", {}).get("assets") else "pending",
        observed.get("pages"),
    )
    runtime = observed.get("pages", {}).get("runtime_execution", {})
    check(
        "deployed_pages_worker_compatibility",
        runtime.get("state", "pending") if isinstance(runtime, dict) else "pending",
        runtime,
    )
    differences = (
        catalog_differences(observed, read=read)
        if same
        else {"state": "pending", "reason": "Raw/viewer identities differ"}
    )
    check("document_category_readback", differences["state"], differences)
    failures = [item for item in checks if item["state"] == "failed"]
    pending = [item for item in checks if item["state"] == "pending"]
    return {
        "version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": "failed" if failures else "pending" if pending else "verified",
        "read_only": True,
        "checks": checks,
        "pins": {
            "raw_catalog_id": raw_manifest.get("catalog_id"),
            "viewer_pointer": pointer,
            "review_sha256": info.get("review_sha256"),
            "public_observations": observed.get("observations", []),
        },
        "withdrawn_reasons": observed.get("withdrawn", []),
    }


def live_observation(
    viewer_url, pages_url, descriptor, *, verifier_script=None, root=None, node="node"
):
    if verifier_script is None:
        if root is None:
            raise ValueError("Either verifier_script or root must be provided")
        verifier_script = Path(root) / "apps/site/scripts/verify-live-publication.mjs"
    verifier_script = Path(verifier_script)
    with tempfile.TemporaryDirectory(prefix="publication-live-status-") as folder:
        output = Path(folder) / "live.json"
        subprocess.run(
            [
                node,
                str(verifier_script),
                "--viewer-url",
                viewer_url,
                "--pages-url",
                pages_url,
                "--review-descriptor",
                str(descriptor),
                "--output",
                str(output),
            ],
            check=True,
            timeout=180,
            capture_output=True,
        )
        return json.loads(control(output, limit=32 * 1024**2))
