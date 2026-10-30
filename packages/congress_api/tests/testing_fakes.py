"""Shared test doubles and fakes for congress_api tests."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError
import pyarrow as pa

from congress_api.models.content import RawContent
from congress_api.retention.derived_files import (
    check_identity,
    copy_checked,
    file_identity,
    require_derived_key,
)


class MemoryStore:
    """In-memory object store double for raw storage and catalog retention."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.writes: list[str] = []

    def read(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def read_body_cache_file(self, path: Path | str, *, expected_version: str) -> dict[str, Any]:
        key = "indexes/processing/bodies.parquet"
        if self.version(key) != expected_version:
            raise ValueError("Reader cache source changed")
        data = self.objects[key]
        result = copy_checked(BytesIO(data), path, size=len(data), key=key, exclusive=True)
        result["version"] = expected_version
        return result

    def read_derived_file(
        self, key: str, path: Path | str, *, expected: str | None = None
    ) -> dict[str, Any] | None:
        require_derived_key(key)
        data = self.read(key)
        if data is None:
            return None
        return copy_checked(BytesIO(data), path, size=len(data), expected=expected, key=key)

    def put_derived_file(self, key: str, path: Path | str, *, expected: str) -> None:
        require_derived_key(key)
        check_identity(file_identity(path), expected, key)
        return self.put(key, Path(path).read_bytes(), immutable=True)

    def put_catalog_manifest(self, data: bytes, *, expected_version: str | None) -> None:
        key = "indexes/catalog.json"
        current = self.read(key)
        version = sha256(current).hexdigest() if current is not None else None
        if version != expected_version:
            raise RuntimeError("Concurrent catalog update; selected snapshot preserved")
        return self.put(key, data)

    def put(self, key: str, body: bytes, *, immutable: bool = False) -> None:
        if immutable and key in self.objects:
            assert self.objects[key] == body
            return
        self.objects[key] = body
        self.writes.append(key)

    def put_file(self, key: str, path: Path | str) -> bool:
        if key in self.objects:
            return False
        self.put(key, Path(path).read_bytes(), immutable=True)
        return True

    def read_file(self, key: str, path: Path | str, *, max_bytes: int) -> None:
        data = self.read(key)
        if data is None or len(data) > max_bytes:
            raise ValueError("Stored object exceeds file budget or is missing")
        Path(path).write_bytes(data)

    def version(self, key: str) -> str:
        return sha256(self.objects[key]).hexdigest() if key in self.objects else "missing"

    def keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))


def response(
    url: str,
    body: bytes,
    media: str | None = None,
    status: int = 200,
    **extra: Any,
) -> dict[str, Any]:
    """Build a mock fetch response dictionary matching source capture schema."""
    if media is None:
        if "response_headers" in extra and "content-type" in extra["response_headers"]:
            media = extra["response_headers"]["content-type"]
        elif url.endswith(".xml") or body.strip().startswith(b"<"):
            media = "application/xml"
        elif url.endswith(".json") or body.strip().startswith((b"{", b"[")):
            media = "application/json"
        elif url.endswith(".m3u8"):
            media = "application/vnd.apple.mpegurl"
        elif url.endswith(".html") or body.strip().startswith((b"<!DOCTYPE", b"<html")):
            media = "text/html"
        else:
            media = "application/pdf"
    return dict(
        requested_url=url,
        url=url,
        http_status=status,
        response_headers={"content-type": media},
        response_header_items=[{"name": "content-type", "value": media}],
        complete=True,
        retrieved_at="2026-10-01T00:00:00+00:00",
        content=RawContent.from_bytes(body, media).source_dict(),
        **extra,
    )


def probe_response(
    url: str,
    body: bytes = b"",
    status: int = 200,
    media: str = "text/html",
    complete: bool = True,
    **headers: Any,
) -> Any:
    """Build a mock DocumentProbeResponse for document resolution tests."""
    from congress_api.models.documents import DocumentProbeResponse

    return DocumentProbeResponse(
        url=url,
        status_code=status,
        headers=headers,
        header_items=list(headers.items()),
        content=RawContent.from_bytes(body, media),
        complete=complete,
    )


class SelectorStore(MemoryStore):
    """MemoryStore supporting optimistic concurrency index selector updates."""

    def __init__(self) -> None:
        super().__init__()
        self.lose_reply = False

    def put_index_selector(self, key: str, data: bytes, *, expected_version: str | None) -> None:
        current = self.objects.get(key)
        version = sha256(current).hexdigest() if current is not None else None
        if version != expected_version:
            raise RuntimeError("Concurrent raw update")
        self.put(key, data)
        if self.lose_reply:
            self.lose_reply = False
            raise TimeoutError("reply lost")


class MemoryNative:
    """In-memory mock for native DocSpec table processing and reading."""

    def __init__(self) -> None:
        self.tables: dict[str, pa.Table] = {}
        self.writes: list[str] = []
        self.reads: list[str] = []
        self.calls: list[str] = []

    def execution_files(self) -> tuple[()]:
        return ()

    def run_table(
        self,
        table: pa.Table,
        *,
        dataset: str,
        operation: str | None = None,
        definition: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(dataset)
        if dataset in self.tables and not self.tables[dataset].equals(table):
            raise ValueError("Conflicting test native request")
        if dataset not in self.tables:
            self.tables[dataset] = table
            self.writes.append(dataset)
        return dict(
            verified=True,
            id=dataset,
            dataset_key=dataset,
            dataset=dict(
                dataset=dataset,
                version=dataset,
                groups=dict(source=dict(rows=len(table))),
            ),
        )

    @contextmanager
    def source_batches(self, pin: dict[str, Any], *, schema: pa.Schema | None = None):
        dataset = pin.get("dataset_key") or pin.get("dataset", {}).get("dataset")
        self.reads.append(dataset)
        table = self.tables[dataset]
        if schema is not None:
            table = table.cast(schema)
        yield pa.RecordBatchReader.from_batches(table.schema, table.to_batches(max_chunksize=2))


# Backward compatibility alias for catalog batch tests
Native = MemoryNative


class AsyncMemoryStore(MemoryStore):
    """MemoryStore double for asynchronous capture pipelines."""

    def __init__(self, upload: Any) -> None:
        super().__init__()
        self.upload = upload

    @asynccontextmanager
    async def async_bodies(self):
        owner = self

        class Bodies:
            async def put(self, key: str, data: bytes) -> None:
                await owner.upload(key, data)
                return owner.put(key, data, immutable=True)

            async def read(self, key: str) -> bytes | None:
                return owner.read(key)

        yield Bodies()


def receipts(store: MemoryStore) -> list[dict[str, Any]]:
    """Extract and parse all JSONL gzip receipts stored in store."""
    import gzip
    import json

    result: list[dict[str, Any]] = []
    for key in store.keys("receipts/"):
        data = store.read(key)
        if data is not None:
            for line in gzip.decompress(data).splitlines():
                result.append(json.loads(line))
    return result


class FakeR2Remote:
    """Mock boto3 S3/R2 remote client for publication tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts = 0
        self.bodies: list[BytesIO] = []

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        raw = self.objects[Key]
        body = BytesIO(raw)
        self.bodies.append(body)
        return {"Body": body, "ContentLength": len(raw), "ETag": sha256(raw).hexdigest()}

    def put_object(self, **kw: Any) -> dict[str, str]:
        if kw.get("IfNoneMatch") == "*" and kw["Key"] in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[kw["Key"]] = kw["Body"]
        self.puts += 1
        return {"ETag": sha256(kw["Body"]).hexdigest()}

    def get_paginator(self, name: str) -> Any:
        remote = self

        class Pages:
            def paginate(self, **kw: Any):
                prefix = kw.get("Prefix", "")
                yield {"Contents": [{"Key": key} for key in remote.objects if key.startswith(prefix)]}

        return Pages()
