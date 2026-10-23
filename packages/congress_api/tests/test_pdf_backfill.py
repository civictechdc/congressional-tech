"""Tests for packages/congress_api/src/congress_api/retention/pdf_backfill.py (ct-ec91)."""
from __future__ import annotations

import gzip
from hashlib import md5, sha256
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.pdf_backfill import backfill_uncompressed_pdfs
from congress_api.retention.r2 import PDF_CACHE_CONTROL, R2Store

ROOT = Path(__file__).resolve().parents[3]


class _MockR2S3Client:
    def __init__(self):
        self.meta = SimpleNamespace(
            config=SimpleNamespace(retries={"total_max_attempts": 1}),
            events=SimpleNamespace(register_first=lambda *args, **kwargs: None),
        )
        self.objects: dict[tuple[str, str], dict] = {}
        self.put_calls: list[dict] = []
        self.get_calls: list[tuple[str, str]] = []

    def head_object(self, *, Bucket: str, Key: str):
        if (Bucket, Key) not in self.objects:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadObject",
            )
        obj = self.objects[(Bucket, Key)]
        return {"ETag": obj["ETag"], "ContentLength": len(obj["Body"])}

    def get_object(self, *, Bucket: str, Key: str, **kwargs):
        self.get_calls.append((Bucket, Key))
        if (Bucket, Key) not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "NoSuchKey"}},
                "GetObject",
            )
        obj = self.objects[(Bucket, Key)]
        raw = obj["Body"]
        return {
            "Body": io.BytesIO(raw),
            "ContentLength": len(raw),
            "ETag": obj["ETag"],
        }

    def put_object(self, **kwargs):
        bucket = kwargs["Bucket"]
        key = kwargs["Key"]
        body = kwargs["Body"]
        raw = body.read() if hasattr(body, "read") else bytes(body)
        etag = f'"{md5(raw).hexdigest()}"'
        self.objects[(bucket, key)] = {
            "Body": raw,
            "ETag": etag,
            "ContentType": kwargs.get("ContentType"),
            "CacheControl": kwargs.get("CacheControl"),
            "ContentDisposition": kwargs.get("ContentDisposition"),
        }
        self.put_calls.append({**kwargs, "Body": raw})
        return {"ETag": etag}


def test_local_store_pdf_backfill_preserves_gz_and_is_idempotent(tmp_path: Path):
    store = LocalStore(tmp_path / "store", store_uncompressed_pdfs=True)
    pdf_bytes = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"
    pdf_sha = sha256(pdf_bytes).hexdigest()
    gz_key = f"bodies/sha256/{pdf_sha[:2]}/{pdf_sha}.gz"
    pdf_key = f"bodies/sha256/{pdf_sha[:2]}/{pdf_sha}.pdf"

    html_bytes = b"<html><body>Not a PDF</body></html>"
    html_sha = sha256(html_bytes).hexdigest()
    html_gz_key = f"bodies/sha256/{html_sha[:2]}/{html_sha}.gz"

    compressed_pdf = gzip.compress(pdf_bytes, compresslevel=1, mtime=0)
    store.put(gz_key, compressed_pdf, immutable=True)
    store.put(html_gz_key, gzip.compress(html_bytes, compresslevel=1, mtime=0), immutable=True)

    accepted = {
        "files": [
            {
                "sha256": pdf_sha,
                "body_key": gz_key,
                "content_type": "application/pdf",
                "decision": "accept",
            },
            {
                "sha256": html_sha,
                "body_key": html_gz_key,
                "content_type": "text/html",
                "decision": "accept",
            },
        ]
    }

    # First run: dry_run=True writes nothing
    dry = backfill_uncompressed_pdfs(store, accepted, dry_run=True)
    assert dry["would_backfill"] == [pdf_key]
    assert dry["backfilled"] == []
    assert store.read(pdf_key) is None

    # Second run: dry_run=False writes .pdf and keeps .gz intact
    first = backfill_uncompressed_pdfs(store, accepted, dry_run=False)
    assert first["backfilled"] == [pdf_key]
    assert first["already_present"] == []
    assert store.read(pdf_key) == pdf_bytes
    assert store.read(gz_key) == compressed_pdf

    # Third run: idempotent when .pdf already exists
    second = backfill_uncompressed_pdfs(store, accepted, dry_run=False)
    assert second["backfilled"] == []
    assert second["already_present"] == [pdf_key]


def test_r2_store_pdf_backfill_sets_pdf_headers_and_skips_existing():
    s3 = _MockR2S3Client()
    bucket = "congressional-tech-raw"
    store = R2Store(s3, bucket, store_uncompressed_pdfs=True)

    pdf_bytes = b"%PDF-1.5\n% mocked r2 pdf payload\n%%EOF\n"
    pdf_sha = sha256(pdf_bytes).hexdigest()
    gz_key = f"bodies/sha256/{pdf_sha[:2]}/{pdf_sha}.gz"
    pdf_key = f"bodies/sha256/{pdf_sha[:2]}/{pdf_sha}.pdf"

    gz_bytes = gzip.compress(pdf_bytes, compresslevel=1, mtime=0)
    s3.objects[(bucket, gz_key)] = {
        "Body": gz_bytes,
        "ETag": f'"{md5(gz_bytes).hexdigest()}"',
    }

    accepted = [{"sha256": pdf_sha, "format": "pdf", "decision": "accept"}]
    result = backfill_uncompressed_pdfs(store, accepted)
    assert result["backfilled"] == [pdf_key]
    assert (bucket, pdf_key) in s3.objects
    stored_pdf = s3.objects[(bucket, pdf_key)]
    assert stored_pdf["Body"] == pdf_bytes
    assert stored_pdf["ContentType"] == "application/pdf"
    assert stored_pdf["CacheControl"] == PDF_CACHE_CONTROL
    assert stored_pdf["ContentDisposition"] == "inline"
    assert s3.objects[(bucket, gz_key)]["Body"] == gz_bytes

    # Re-running does not re-download .gz or re-upload .pdf
    s3.get_calls.clear()
    s3.put_calls.clear()
    again = backfill_uncompressed_pdfs(store, accepted)
    assert again["already_present"] == [pdf_key]
    assert again["backfilled"] == []
    assert s3.get_calls == []
    assert s3.put_calls == []


def test_pdf_backfill_rejects_sha256_mismatch(tmp_path: Path):
    store = LocalStore(tmp_path / "store", store_uncompressed_pdfs=True)
    claimed_pdf = b"%PDF-1.4\nexpected content\n%%EOF\n"
    claimed_sha = sha256(claimed_pdf).hexdigest()
    gz_key = f"bodies/sha256/{claimed_sha[:2]}/{claimed_sha}.gz"
    pdf_key = f"bodies/sha256/{claimed_sha[:2]}/{claimed_sha}.pdf"

    tampered_pdf = b"%PDF-1.4\ntampered content\n%%EOF\n"
    store.put(gz_key, gzip.compress(tampered_pdf, compresslevel=1, mtime=0), immutable=True)

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        backfill_uncompressed_pdfs(
            store,
            [{"sha256": claimed_sha, "content_type": "application/pdf", "decision": "accept"}],
        )
    assert store.read(pdf_key) is None


def test_backfill_cli_writes_output_report(tmp_path: Path):
    from viewer_publication import backfill_uncompressed_pdfs as cli_mod

    store_dir = tmp_path / "local-store"
    store = LocalStore(store_dir, store_uncompressed_pdfs=True)
    pdf_bytes = b"%PDF-1.7\ncli test\n%%EOF\n"
    pdf_sha = sha256(pdf_bytes).hexdigest()
    gz_key = f"bodies/sha256/{pdf_sha[:2]}/{pdf_sha}.gz"
    pdf_key = f"bodies/sha256/{pdf_sha[:2]}/{pdf_sha}.pdf"
    store.put(gz_key, gzip.compress(pdf_bytes), immutable=True)

    accepted_file = tmp_path / "accepted-files.json"
    accepted_file.write_text(
        json.dumps({"files": [{"sha256": pdf_sha, "content_type": "application/pdf", "decision": "accept"}]}),
        encoding="utf-8",
    )
    report_file = tmp_path / "report.json"

    rc = cli_mod.main(
        [
            "--accepted-files",
            str(accepted_file),
            "--local-store",
            str(store_dir),
            "--output",
            str(report_file),
        ]
    )
    assert rc == 0
    report = json.loads(report_file.read_text(encoding="utf-8"))
    assert report["backfilled"] == [pdf_key]
    assert store.read(pdf_key) == pdf_bytes
