"""Unit tests for `scripts/measure/docmeta_v7_ocr_rescue.py` (`ct-o7ew`)."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import types
import urllib.error

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "docmeta_v7_ocr_rescue",
    ROOT / "scripts/measure/docmeta_v7_ocr_rescue.py",
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)


def _gzip_bytes(payload: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(payload)
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._bio = io.BytesIO(data)

    def read(self, n: int = -1) -> bytes:
        return self._bio.read(n)

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_a: object) -> None:
        return None


def test_stream_download_verified_pdf_accepts_valid_and_rejects_mismatch(tmp_path: Path) -> None:
    payload = b"%PDF-1.4\nSynthetic GPO Distiller payload bytes.\n%%EOF\n"
    sha = hashlib.sha256(payload).hexdigest()
    gz = _gzip_bytes(payload)

    seen_urls: list[str] = []

    def ok_opener(req, timeout=60.0):
        del timeout
        seen_urls.append(req.full_url)
        return _FakeResponse(gz)

    dst = tmp_path / "valid.pdf"
    st, n_b, err = mod.stream_download_verified_pdf(sha, dst, retries=0, opener=ok_opener)
    assert st == "ok" and err is None
    assert n_b == len(payload)
    assert dst.read_bytes() == payload
    assert seen_urls == [f"https://congressional-data.spicygov.ai/bodies/sha256/{sha[:2]}/{sha}.gz"]

    # Wrong digest MUST fail closed and remove temp file.
    bad_sha = "0" * 64
    bad_dst = tmp_path / "bad.pdf"
    st2, _n2, err2 = mod.stream_download_verified_pdf(bad_sha, bad_dst, retries=0, opener=ok_opener)
    assert st2 == "sha_mismatch"
    assert err2 is not None and bad_sha in err2
    assert not bad_dst.exists()


def test_run_ocr_resume_idempotence_and_package_validate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_a = b"%PDF-1.4 A"
    pdf_b = b"%PDF-1.4 B"
    sha_a = hashlib.sha256(pdf_a).hexdigest()
    sha_b = hashlib.sha256(pdf_b).hexdigest()

    (tmp_path / f"{sha_a}.pdf").write_bytes(pdf_a)
    (tmp_path / f"{sha_b}.pdf").write_bytes(pdf_b)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    targets = [
        {
            "saved_body_hex": sha_a,
            "saved_bytes": 400_000,
            "doc_key": "d78dcdd75e9a_sentinel",
            "doc_keys": ["d78dcdd75e9a_sentinel"],
            "link_keys": ["0000000000000001"],
            "filename": "Nomination_Hearing_GPO.pdf",
            "orig_status": "ocr_unreadable",
            "orig_chars": 0,
            "cohorts": ["ocr_unreadable", "sentinel"],
            "is_sentinel": True,
        },
        {
            "saved_body_hex": sha_b,
            "saved_bytes": 500_000,
            "doc_key": "other_doc_b",
            "doc_keys": ["other_doc_b"],
            "link_keys": ["0000000000000002"],
            "filename": "scan.pdf",
            "orig_status": "queued_llm_lt400",
            "orig_chars": 50,
            "cohorts": ["llm_queue_lt400"],
            "is_sentinel": False,
        },
    ]
    (out_dir / "targets.jsonl").write_text("".join(json.dumps(t) + "\n" for t in targets), encoding="utf-8")

    # Pre-checkpoint sha_a so `--resume` skips sha_a and only OCRs sha_b.
    pre_row = {
        "saved_body_hex": sha_a,
        "doc_key": "d78dcdd75e9a_sentinel",
        "filename": "Nomination_Hearing_GPO.pdf",
        "saved_bytes": 400_000,
        "cohorts": ["ocr_unreadable", "sentinel"],
        "orig_status": "ocr_unreadable",
        "orig_chars": 0,
        "is_sentinel": True,
        "elapsed_s": 1.2,
        "rescued_status": "ok",
        "page_failure_mode": "vector_outlined",
        "n_pages_total": 29,
        "pages_ocred": 5,
        "rescued_chars": 1500,
        "rescued_p12_chars": 600,
        "used_raster_ocr": True,
        "max_path_count": 340,
        "max_image_count": 0,
        "backends": ["apple-vision:accurate:b1"] * 5,
        "rescued_text": "S. HRG. 116-135 NOMINATION HEARING FOR DIRECTOR OF GPO",
        "rescued_text_sha256": hashlib.sha256(b"S. HRG. 116-135 NOMINATION HEARING FOR DIRECTOR OF GPO").hexdigest(),
        "error": None,
    }
    (out_dir / "rescued_pages.jsonl").write_text(json.dumps(pre_row) + "\n", encoding="utf-8")

    ocred_paths: list[str] = []

    class _FakePdfDoc:
        def __init__(self, _p: str) -> None:
            pass

        def __len__(self) -> int:
            return 2

        def close(self) -> None:
            pass

    class _FakeFastOCR:
        def __init__(self, **_kw: object) -> None:
            pass

        def __enter__(self) -> _FakeFastOCR:
            return self

        def __exit__(self, *_a: object) -> None:
            pass

        def ocr_pdf(self, pdf_path: Path, **kw: object) -> list[object]:
            ocred_paths.append(pdf_path.name)
            return [
                types.SimpleNamespace(page_index=0, text="Recovered statement text page 1 " * 10, backend_used="apple-vision:accurate:b1"),
                types.SimpleNamespace(page_index=1, text="Page 2 body text " * 10, backend_used="apple-vision:accurate:b1"),
            ]

    monkeypatch.setitem(sys.modules, "pypdfium2", types.SimpleNamespace(PdfDocument=_FakePdfDoc))
    monkeypatch.setitem(sys.modules, "fast_ocr", types.SimpleNamespace(FastOCR=_FakeFastOCR))
    monkeypatch.setitem(
        sys.modules,
        "fast_ocr.preprocess",
        types.SimpleNamespace(
            extract_native_pdf_text=lambda _p, page_indices=None: [
                types.SimpleNamespace(path_count=0, image_count=1, native_body_char_count=0, native_char_count=0)
                for _ in (page_indices or [0, 1])
            ]
        ),
    )

    res = mod.run_ocr(out_dir=out_dir, resume=True, local_cache_dir=tmp_path)
    assert res["processed"] == 1
    assert ocred_paths == [f"{sha_b}.pdf"]
    assert not (out_dir / ".tmp_pdf").exists()

    report = mod.package_and_validate(out_dir=out_dir)
    assert report["total_targets"] == 2
    assert report["overall"]["recovered_ge_400_chars"] == 2
    assert report["by_cohort"]["ocr_unreadable"]["recovered_ge_400_pct"] == 100.0

    tbl = pq.read_table(out_dir / "rescued_p15.parquet")
    assert tbl.num_rows == 2
    assert tbl.schema.field("saved_body").type == pa.binary(32)
    assert (out_dir / "validation_report.json").is_file()
    assert (out_dir / "spot_check_10.md").is_file()


def test_stream_download_verified_pdf_handles_suffixless_and_fallback(tmp_path: Path) -> None:
    payload = b"%PDF-1.7\nUncompressed new-spec body.\n%%EOF\n"
    sha = hashlib.sha256(payload).hexdigest()
    gz_url = f"https://congressional-data.spicygov.ai/bodies/sha256/{sha[:2]}/{sha}.gz"
    raw_url = f"https://congressional-data.spicygov.ai/bodies/sha256/{sha[:2]}/{sha}"

    seen_urls: list[str] = []

    def fallback_opener(req, timeout=60.0):
        del timeout
        seen_urls.append(req.full_url)
        if req.full_url == gz_url:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        assert req.full_url == raw_url
        return _FakeResponse(payload)

    dst = tmp_path / "fallback.pdf"
    st, n_b, err = mod.stream_download_verified_pdf(sha, dst, retries=0, opener=fallback_opener)
    assert st == "ok" and err is None
    assert n_b == len(payload)
    assert dst.read_bytes() == payload
    assert seen_urls == [gz_url, raw_url]

    # Explicit saved_suffix="" skips the .gz probe and goes straight to suffix-less URL.
    seen_urls.clear()
    dst_direct = tmp_path / "direct.pdf"
    st_dir, n_dir, err_dir = mod.stream_download_verified_pdf(
        sha, dst_direct, saved_suffix="", retries=0, opener=fallback_opener
    )
    assert st_dir == "ok" and err_dir is None
    assert n_dir == len(payload)
    assert seen_urls == [raw_url]

    # SHA mismatch on uncompressed body still fails closed.
    bad_dst = tmp_path / "bad_raw.pdf"
    st_bad, _n_bad, _err_bad = mod.stream_download_verified_pdf(
        "f" * 64,
        bad_dst,
        saved_suffix="",
        retries=0,
        opener=lambda req, timeout=60.0: _FakeResponse(payload),
    )
    assert st_bad == "sha_mismatch"
    assert not bad_dst.exists()


def test_run_ocr_retry_fetch_errors_updates_latest_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_a = b"%PDF-1.4 OK"
    pdf_b = b"%PDF-1.4 RETRY"
    sha_a = hashlib.sha256(pdf_a).hexdigest()
    sha_b = hashlib.sha256(pdf_b).hexdigest()

    (tmp_path / f"{sha_a}.pdf").write_bytes(pdf_a)
    (tmp_path / f"{sha_b}.pdf").write_bytes(pdf_b)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    targets = [
        {
            "saved_body_hex": sha_a,
            "saved_suffix": ".gz",
            "saved_bytes": 400_000,
            "doc_key": "doc_ok",
            "doc_keys": ["doc_ok"],
            "link_keys": ["0000000000000001"],
            "filename": "ok.pdf",
            "orig_status": "ocr_unreadable",
            "orig_chars": 0,
            "cohorts": ["ocr_unreadable"],
            "is_sentinel": False,
        },
        {
            "saved_body_hex": sha_b,
            "saved_suffix": "",
            "saved_bytes": 400_000,
            "doc_key": "doc_retry",
            "doc_keys": ["doc_retry"],
            "link_keys": ["0000000000000002"],
            "filename": "retry.pdf",
            "orig_status": "ocr_unreadable",
            "orig_chars": 0,
            "cohorts": ["ocr_unreadable"],
            "is_sentinel": False,
        },
    ]
    (out_dir / "targets.jsonl").write_text("".join(json.dumps(t) + "\n" for t in targets), encoding="utf-8")

    prior_rows = [
        {
            "saved_body_hex": sha_a,
            "doc_key": "doc_ok",
            "filename": "ok.pdf",
            "saved_bytes": 400_000,
            "cohorts": ["ocr_unreadable"],
            "orig_status": "ocr_unreadable",
            "orig_chars": 0,
            "is_sentinel": False,
            "elapsed_s": 0.5,
            "rescued_status": "ok",
            "page_failure_mode": "vector_outlined",
            "n_pages_total": 1,
            "pages_ocred": 1,
            "rescued_chars": 500,
            "rescued_p12_chars": 500,
            "used_raster_ocr": True,
            "max_path_count": 300,
            "max_image_count": 0,
            "backends": ["apple-vision:accurate:b1"],
            "rescued_text": "Already rescued " * 35,
            "rescued_text_sha256": hashlib.sha256(("Already rescued " * 35).encode()).hexdigest(),
            "error": None,
        },
        {
            "saved_body_hex": sha_b,
            "doc_key": "doc_retry",
            "filename": "retry.pdf",
            "saved_bytes": 400_000,
            "cohorts": ["ocr_unreadable"],
            "orig_status": "ocr_unreadable",
            "orig_chars": 0,
            "is_sentinel": False,
            "elapsed_s": 0.1,
            "rescued_status": "fetch_error",
            "page_failure_mode": "fetch_error",
            "n_pages_total": 0,
            "pages_ocred": 0,
            "rescued_chars": 0,
            "rescued_p12_chars": 0,
            "used_raster_ocr": False,
            "max_path_count": 0,
            "max_image_count": 0,
            "backends": [],
            "rescued_text": "",
            "rescued_text_sha256": hashlib.sha256(b"").hexdigest(),
            "error": "http_404",
        },
    ]
    (out_dir / "rescued_pages.jsonl").write_text("".join(json.dumps(r) + "\n" for r in prior_rows), encoding="utf-8")

    ocred: list[str] = []

    class _FakePdfDoc:
        def __init__(self, _p: str) -> None:
            pass

        def __len__(self) -> int:
            return 1

        def close(self) -> None:
            pass

    class _FakeFastOCR:
        def __init__(self, **_kw: object) -> None:
            pass

        def __enter__(self) -> _FakeFastOCR:
            return self

        def __exit__(self, *_a: object) -> None:
            pass

        def ocr_pdf(self, pdf_path: Path, **kw: object) -> list[object]:
            ocred.append(pdf_path.name)
            return [types.SimpleNamespace(page_index=0, text="Recovered suffixless body " * 20, backend_used="apple-vision:accurate:b1")]

    monkeypatch.setitem(sys.modules, "pypdfium2", types.SimpleNamespace(PdfDocument=_FakePdfDoc))
    monkeypatch.setitem(sys.modules, "fast_ocr", types.SimpleNamespace(FastOCR=_FakeFastOCR))
    monkeypatch.setitem(
        sys.modules,
        "fast_ocr.preprocess",
        types.SimpleNamespace(
            extract_native_pdf_text=lambda _p, page_indices=None: [
                types.SimpleNamespace(path_count=0, image_count=1, native_body_char_count=0, native_char_count=0)
                for _ in (page_indices or [0])
            ]
        ),
    )

    res = mod.run_ocr(out_dir=out_dir, resume=True, retry_fetch_errors=True, local_cache_dir=tmp_path)
    assert res["processed"] == 1
    assert ocred == [f"{sha_b}.pdf"]
    report = mod.package_and_validate(out_dir=out_dir)
    assert report["overall"]["status_counts"] == {"ok": 2}
    assert report["overall"]["recovered_ge_400_chars"] == 2
