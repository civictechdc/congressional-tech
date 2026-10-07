"""Disk recovery must publish only complete, version-pinned and qualified bytes."""

import gzip
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import runpy
from zipfile import ZipFile, ZIP_DEFLATED

import httpx
import pytest

from congress_api.acquisition.streamed_recovery import (
    download_ranges,
    recover_pdf,
    recover_zip,
    retain_file,
)
from congress_api.retention.raw_archive import Archive
from test_raw_source_sync import MemoryStore

URL = "https://www.govinfo.gov/content/pkg/CHRG-118hhrg56269.zip"
PDF = "https://www.govinfo.gov/content/pkg/CHRG-118hhrg56269/pdf/CHRG-118hhrg56269.pdf"
DATE = "Mon, 05 Oct 2026 23:35:53 GMT"
RUN = "20261006T210000Z-aabbccddeeff"


@pytest.fixture(autouse=True)
def fixed_capture_clock(monkeypatch):
    # Receipt paths must use the same day as the fixed run IDs in these fixtures.
    class FixtureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 10, 6, 21, tzinfo=timezone.utc)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr("congress_api.retention.raw_archive.datetime", FixtureClock)
    monkeypatch.setattr(
        "congress_api.acquisition.streamed_recovery.datetime", FixtureClock
    )


class FileStore(MemoryStore):
    def put_file(self, key, path):
        if key in self.objects:
            return False
        self.put(key, Path(path).read_bytes(), immutable=True)
        return True

    def read_file(self, key, path, *, max_bytes):
        data = self.objects[key]
        assert len(data) <= max_bytes
        Path(path).write_bytes(data)
        return len(data)


def range_client(body, calls, fail=None):
    def respond(request):
        start, end = map(int, request.headers["range"][6:].split("-"))
        calls.append((start, end))
        assert request.headers["if-unmodified-since"] == DATE
        if fail and fail(start):
            raise httpx.ReadTimeout("test interrupted stream")
        return httpx.Response(
            206,
            content=body[start : end + 1],
            headers={
                "Content-Range": f"bytes {start}-{end}/{len(body)}",
                "Last-Modified": DATE,
            },
        )

    return httpx.Client(transport=httpx.MockTransport(respond))


def test_ranges_resume_after_failure_without_repeating_completed_bytes(tmp_path):
    body = b"abcdefghij"
    calls = []
    path = tmp_path / "source.zip"
    with range_client(body, calls, lambda start: start == 4) as client:
        with pytest.raises(httpx.ReadTimeout):
            download_ranges(
                client, URL, path, size=len(body), last_modified=DATE, range_bytes=4
            )
    assert path.read_bytes() == b"abcd"
    with range_client(body, calls) as client:
        result = download_ranges(
            client, URL, path, size=len(body), last_modified=DATE, range_bytes=4
        )
    assert calls == [(0, 3), (4, 7), (4, 7), (8, 9)]
    assert path.read_bytes() == body
    assert result["sha256"] == hashlib.sha256(body).hexdigest()


def test_first_range_failure_is_resumable_and_corrupt_prefix_refused(tmp_path):
    path = tmp_path / "source.zip"
    with range_client(b"abcd", [], lambda _: True) as client:
        with pytest.raises(httpx.ReadTimeout):
            download_ranges(client, URL, path, size=4, last_modified=DATE)
    with range_client(b"abcd", []) as client:
        download_ranges(client, URL, path, size=4, last_modified=DATE)
    path.write_bytes(b"xxxx")
    with range_client(b"abcd", []) as client, pytest.raises(
        ValueError, match="checksum"
    ):
        download_ranges(client, URL, path, size=4, last_modified=DATE)


@pytest.mark.parametrize(
    "status,headers",
    [
        (200, {}),
        (206, {"Last-Modified": "changed"}),
        (206, {"Content-Range": "bytes 0-3/5"}),
        (206, {"Content-Encoding": "gzip"}),
    ],
)
def test_range_version_or_response_mismatch_never_commits(tmp_path, status, headers):
    def respond(request):
        return httpx.Response(
            status,
            stream=httpx.ByteStream(b"abcd"),
            headers={"Content-Range": "bytes 0-3/4", "Last-Modified": DATE, **headers},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client, pytest.raises(
        ValueError
    ):
        download_ranges(
            client, URL, tmp_path / "source.zip", size=4, last_modified=DATE
        )
    assert json.loads((tmp_path / "source.ranges.json").read_text())["bytes"] == 0


def fixture_zip(
    data=b"%PDF-1.7\ncomplete\n%%EOF",
    name="CHRG-118hhrg56269/pdf/CHRG-118hhrg56269.pdf",
):
    out = io.BytesIO()
    with ZipFile(out, "w", compression=ZIP_DEFLATED) as z:
        z.writestr(name, data)
    body = out.getvalue()
    with ZipFile(io.BytesIO(body)) as z:
        info = z.infolist()[0]
    manifest = dict(
        url=URL,
        bytes=len(body),
        last_modified=DATE,
        members=[
            dict(
                name=name,
                bytes=len(data),
                crc32=f"{info.CRC:08x}",
                sha256=hashlib.sha256(data).hexdigest(),
                media_type="application/pdf",
                source_url=PDF,
            )
        ],
    )
    return body, manifest


def test_zip_recovers_pdf_with_normal_receipts_no_second_download_and_reuses_bodies(
    tmp_path,
):
    body, manifest = fixture_zip()
    store = FileStore()
    archive = Archive(store, RUN)
    calls = []
    archive.seed({"url": PDF})
    archive.state[PDF].update(outcome="retained", body_key="partial")
    with range_client(body, calls) as client:
        result = recover_zip(archive, client, manifest, tmp_path)
    assert (
        result["fetch"] == 1
        and result["replay"] == 1
        and result["archive_member_captures"] == 1
    )
    assert archive.state[PDF]["sha256"] == manifest["members"][0]["sha256"]
    assert archive.state[PDF]["attempts"] == 0
    receipts = [
        json.loads(line)
        for key in store.keys("receipts/")
        for line in gzip.decompress(store.read(key)).splitlines()
    ]
    derived = next(r for r in receipts if r["record"]["mode"] == "replay")
    assert derived["record"]["transport"] == "retained_archive_member"
    assert derived["record"]["http_status"] is None
    verifier = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / ".github/scripts/verify-capture-run.py"
        )
    )
    assert verifier["verify_run"](store, result)["verified"]
    prior_keys = set(store.keys("bodies/"))
    # An already qualified document does not receive a second replay receipt.
    with range_client(body, calls) as client:
        again = recover_zip(
            Archive(store, "20261006T210100Z-aabbccddeeff"), client, manifest, tmp_path
        )
    assert (
        again["fetch"] == 1
        and again["replay"] == 0
        and set(store.keys("bodies/")) == prior_keys
    )
    assert len(calls) == 1  # Complete on-disk source was checked and reused.


def test_publisher_hash_failure_preserves_state_and_publishes_no_receipts(tmp_path):
    body, manifest = fixture_zip()
    manifest["members"][0]["sha256"] = "0" * 64
    store = FileStore()
    archive = Archive(store, RUN)
    with range_client(body, []) as client, pytest.raises(
        ValueError, match="publisher checksum"
    ):
        recover_zip(archive, client, manifest, tmp_path)
    assert not list(store.keys("receipts/")) and not archive.pending
    assert PDF not in archive.state


def test_member_names_never_become_local_paths(tmp_path):
    body, manifest = fixture_zip(name="../escaped.pdf")
    store = FileStore()
    with range_client(body, []) as client:
        result = recover_zip(Archive(store, RUN), client, manifest, tmp_path)
    assert result["saved"] == 2 and not (tmp_path.parent / "escaped.pdf").exists()
    receipts = [
        json.loads(line)
        for key in store.keys("receipts/")
        for line in gzip.decompress(store.read(key)).splitlines()
    ]
    assert receipts[0]["record"]["archive_members"][0]["unsafe_name"]


def test_orphan_body_reuse_verifies_actual_gzip_bytes(tmp_path):
    raw = b"hello"
    path = tmp_path / "raw"
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    key = f"bodies/sha256/{digest[:2]}/{digest}.gz"
    store = FileStore()
    store.objects[key] = gzip.compress(raw, mtime=42)
    info = retain_file(Archive(store, RUN), path, tmp_path / "scratch")
    assert info["stored_sha256"] == hashlib.sha256(store.objects[key]).hexdigest()
    store.objects[key] = gzip.compress(b"wrong", mtime=42)
    with pytest.raises(ValueError, match="checksum"):
        retain_file(Archive(store, RUN), path, tmp_path / "scratch")


def test_large_verifier_uses_bounded_file_path(tmp_path):
    # Incompressible-enough identity is unnecessary: decoded size triggers disk verification.
    body, manifest = fixture_zip(data=b"%PDF" + b"x" * (65 * 1024**2))
    store = FileStore()
    with range_client(body, []) as client:
        result = recover_zip(Archive(store, RUN), client, manifest, tmp_path)
    original = store.read

    def guarded(key):
        if key.startswith("bodies/") and key.endswith(
            manifest["members"][0]["sha256"] + ".gz"
        ):
            pytest.fail("Large body must not be read into memory")
        return original(key)

    store.read = guarded
    verifier = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / ".github/scripts/verify-capture-run.py"
        )
    )
    assert verifier["verify_run"](store, result)["verified"]


def test_crc_failure_prevents_receipts_even_without_publisher_hash(tmp_path):
    body, manifest = fixture_zip()
    # Patch the central-directory CRC: decompression must check the full member.
    altered = bytearray(body)
    position = altered.index(b"PK\x01\x02") + 16
    altered[position : position + 4] = b"\x00" * 4
    manifest["members"][0]["crc32"] = "00000000"
    manifest["members"][0].pop("sha256")
    manifest["members"][0].pop("source_url")
    store = FileStore()
    from zipfile import BadZipFile

    with range_client(bytes(altered), []) as client, pytest.raises(BadZipFile):
        recover_zip(Archive(store, RUN), client, manifest, tmp_path)
    assert not list(store.keys("receipts/"))


def test_range_failure_after_partial_write_discards_only_uncommitted_tail(tmp_path):
    class Interrupted(httpx.SyncByteStream):
        def __iter__(self):
            yield b"ab"
            raise httpx.ReadError("test")

    def respond(request):
        return httpx.Response(
            206,
            stream=Interrupted(),
            headers={"Content-Range": "bytes 0-3/4", "Last-Modified": DATE},
        )

    path = tmp_path / "source.zip"
    with httpx.Client(transport=httpx.MockTransport(respond)) as client, pytest.raises(
        httpx.ReadError
    ):
        download_ranges(client, URL, path, size=4, last_modified=DATE)
    assert json.loads((tmp_path / "source.ranges.json").read_text())["bytes"] == 0
    with range_client(b"abcd", []) as client:
        download_ranges(client, URL, path, size=4, last_modified=DATE)
    assert path.read_bytes() == b"abcd"


def pdf_manifest(body):
    return dict(
        kind="file", url=PDF, bytes=len(body), last_modified=DATE,
        sha256=hashlib.sha256(body).hexdigest(), media_type="application/pdf",
    )


def test_exact_pdf_has_normal_verified_receipt(tmp_path):
    body = b"%PDF-1.7\ncomplete\n%%EOF"
    store = FileStore()
    archive = Archive(store, RUN)
    archive.seed({"url": PDF})
    archive.state[PDF]["outcome"] = "resource_limit"
    with range_client(body, []) as client:
        result = recover_pdf(archive, client, pdf_manifest(body), tmp_path)
    assert result["fetch"] == 1 and result["replay"] == 0
    assert result["archive_member_captures"] == 0
    assert archive.state[PDF]["sha256"] == hashlib.sha256(body).hexdigest()
    verifier = runpy.run_path(str(Path(__file__).resolve().parents[1]
                                 / ".github/scripts/verify-capture-run.py"))
    assert verifier["verify_run"](store, result)["verified"]


@pytest.mark.parametrize("fault", ["hash", "not_pdf", "stop", "spool", "unqualified"])
def test_failed_pdf_qualification_cannot_publish_receipt(tmp_path, fault):
    body = b"not a PDF" if fault == "not_pdf" else b"%PDF-1.7\ncomplete\n%%EOF"
    manifest = pdf_manifest(body)
    if fault == "hash":
        manifest["sha256"] = "0" * 64
    elif fault == "spool":
        manifest["bytes"] = 3 * 1024**3
    elif fault == "unqualified":
        manifest.pop("sha256")
    store = FileStore()
    archive = Archive(store, RUN)
    with range_client(body, []) as client, pytest.raises((ValueError, InterruptedError)):
        recover_pdf(archive, client, manifest, tmp_path, stop=lambda: fault == "stop")
    assert not list(store.keys("receipts/")) and not archive.pending
    assert not list(store.keys("bodies/")) and PDF not in archive.state
